"""Read local CLI token counters and produce offline, content-free HTML reports."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime
from html import escape
from decimal import Decimal
import json
import os
from pathlib import Path
import tempfile
import time

from usage_ingestion import discover, parsed_entries, scan_observations, verified_prefix
from usage_time import DEFAULT_TIMEZONE, RangeContext, local_datetime, resolve_range
from usage_records import Record, Tokens
from usage_reconciliation import reconcile_observations
from usage_observations import CanonicalEvent, extract_claude, extract_codex, recorded_effort, timestamp
from usage_valuation import (Price, PRICES, PRICE_SOURCE, PRICE_DATE, MODEL_PRICE_SOURCES,
                             DEFAULT_PLAN_FEES, POLICY_VERSION, RateCatalog, ComparisonScope, aggregate_values, bounded_decimal,
                             build_catalog, compare_plans, money_text, price_for, rate_text, value_event,
                             value_text as summary_value_text)


def estimate(record: Record, overrides: dict | None = None) -> float | None:
    """Legacy float projection only; authoritative consumers use value_event."""
    amount = value_event(record, build_catalog(overrides)).amount_usd
    return float(amount) if amount is not None else None


def value_text(records, prices=None, precision=4):
    catalog = build_catalog(prices)
    return summary_value_text(aggregate_values(value_event(r, catalog) for r in records), precision)


def load_prices(path: Path | None) -> dict:
    if path is None:
        return {}
    def reject_constant(_):
        raise ValueError("Non-finite prices are unsupported.")
    data = json.loads(path.read_text(encoding="utf-8-sig"), parse_float=Decimal, parse_constant=reject_constant)
    if not isinstance(data, dict):
        raise ValueError("Prices must be an object keyed by exact model name.")
    prices = {}
    for name, values in data.items():
        if not isinstance(name, str) or not name.strip() or not isinstance(values, dict):
            raise ValueError("Invalid model price entry.")
        if not {"input", "output", "cached"} <= values.keys():
            raise ValueError("Each model needs input, output, and cached USD per million tokens.")
        if values.keys() - {"input", "output", "cached", "write5m", "write1h"}:
            raise ValueError("Unsupported price fields; use input, output, cached, write5m, write1h.")
        # Price validates exact numeric bounds/scale; JSON decimal strings are also supported.
        prices[name] = Price(**{key: bounded_decimal(value) for key, value in values.items()})
    return prices


def count(value) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def object_value(value) -> dict:
    return value if isinstance(value, dict) else {}


def reasoning_count(usage: dict, output: int) -> int | None:
    value = usage.get("reasoning_output_tokens")
    if "reasoning_output_tokens" not in usage:
        value = object_value(usage.get("output_tokens_details")).get("reasoning_tokens")
    if isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= output:
        return value
    return None


def log_files(roots: list[Path], notices: list[str], since: float | None = None):
    # since is retained for API compatibility, never used as an mtime filter.
    paths, issues, _ = discover(roots)
    notices.extend(issue.message for issue in issues)
    yield from paths


def source_lines(path: Path, notices: list[str]):
    """Compatible parsed-line interface over one verified file prefix."""
    data, _, issues = verified_prefix(path)
    if data is not None:
        yield from parsed_entries(data, path, issues)
    notices.extend(issue.message for issue in issues)


def lines(path: Path, notices: list[str]):
    for _, data in source_lines(path, notices):
        yield data


def read_observations(provider: str, roots: list[Path], notices: list[str], since: float | None = None):
    result = scan_observations(provider, roots)
    notices.extend(issue.message for issue in result.issues)
    return list(result.observations)


def read_claude(roots: list[Path], notices: list[str], since: float | None = None) -> list[Record]:
    return _reconciled_records("Claude", roots, notices, since)


def read_codex(roots: list[Path], notices: list[str], since: float | None = None) -> list[Record]:
    return _reconciled_records("Codex", roots, notices, since)


def _reconciled_records(provider, roots, notices, since):
    result = reconcile_observations(read_observations(provider, roots, notices, since))
    notices.extend(issue.message for issue in result.issues)
    return [event.record for event in result.events]


def default_roots() -> dict[str, list[Path]]:
    codex = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")
    claude = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")
    return {"Codex": [codex / "sessions", codex / "archived_sessions"], "Claude": [claude / "projects"]}


def period_bounds(period: str, now: float, snapshot=None, timezone=DEFAULT_TIMEZONE) -> tuple[float, str]:
    """Compatibility projection; resolve_range exposes the full half-open context."""
    context = resolve_range(period, now, snapshot, timezone)
    return context.start, context.label


@dataclass
class Report:
    records: list[Record]
    periods: dict[str, tuple[float, str]]
    end: float
    notices: list[str] = field(default_factory=list)
    prices: dict = field(default_factory=dict)
    demo: bool = False
    period: str = "session"
    plan_costs: dict = field(default_factory=lambda: dict(DEFAULT_PLAN_FEES))
    timezone: str = DEFAULT_TIMEZONE
    ranges: dict[str, RangeContext] = field(default_factory=dict)
    scans: dict = field(default_factory=dict)
    accounting_issues: dict = field(default_factory=dict)
    events: tuple[CanonicalEvent, ...] = ()
    filtered: bool = False
    catalog: RateCatalog = field(init=False, repr=False)

    def __post_init__(self):
        self.prices = dict(self.prices)
        self.catalog = build_catalog(self.prices)
        self.plan_costs = {p: bounded_decimal(fee) if fee is not None else None
                           for p, fee in self.plan_costs.items()}
        if not self.ranges:
            self.ranges = {p: RangeContext(start, self.end, self.timezone, label)
                           for p, (start, label) in self.periods.items()}

    @property
    def source_states(self):
        return {provider: scan.state for provider, scan in self.scans.items()}

    @property
    def issue_counts(self):
        return {provider: scan.issue_counts for provider, scan in self.scans.items()}

    def valuation_view(self):
        by_identity = {id(event.record): event for event in self.events}
        view = {}
        for record in self.records:
            if id(record) not in view:
                view[id(record)] = value_event(by_identity.get(id(record), record), self.catalog)
        return view

    def summarize_value(self, records=None, view=None):
        view = self.valuation_view() if view is None else view
        records = self.records if records is None else records
        return aggregate_values(view[id(record)] for record in records)

    def comparisons(self, view=None):
        view = self.valuation_view() if view is None else view
        calendar = self.period == "month" and set(self.ranges) == set(self.periods) and all(
            context.start == resolve_range("month", self.end, timezone=self.timezone).start
            and context.start == self.periods[provider][0]
            and context.end == self.end and context.timezone == self.timezone
            for provider, context in self.ranges.items())
        scope = ComparisonScope(tuple(self.periods), self.period, calendar, self.filtered)
        qualifications = {}
        for provider in self.periods:
            flags = ["demo" if self.demo else "ingestion_" + self.source_states.get(provider, "not_supplied")]
            if self.accounting_issues.get(provider):
                flags.append("accounting_issues_present")
            qualifications[provider] = tuple(flags)
        return compare_plans((view[id(r)] for r in self.records), scope, self.plan_costs, qualifications)



def collect_report(period="session", providers=("Codex", "Claude"), snapshots=None,
                   roots=None, now=None, prices=None, demo=False, plan_costs=None, timezone=DEFAULT_TIMEZONE) -> Report:
    now = time.time() if now is None else now
    roots = default_roots() if roots is None else roots
    snapshots = snapshots or {}
    ranges = {p: resolve_range(period, now, snapshots.get(p), timezone) for p in providers}
    periods = {p: (context.start, context.label) for p, context in ranges.items()}
    records, notices, scans, accounting, events = [], [], {}, {}, []
    for provider in providers:
        if demo:
            candidates = [Record(provider, now - 60 * (3 - i), "demo-conversation", "Demo project",
                                 "gpt-5.4" if provider == "Codex" else "claude-sonnet-4-6",
                                 Tokens(4000, 1000 * (i + 1), 12000), effort, "demo metadata",
                                 f"demo-turn-{i + 1}", 300 * (i + 1) if provider == "Codex" else None)
                          for i, effort in enumerate(("medium", "high", "ultra"))]
        else:
            scan = scan_observations(provider, roots.get(provider, []))
            scans[provider] = scan
            result = reconcile_observations(scan.observations)
            accounting[provider] = result.issues
            events.extend(event for event in result.events if ranges[provider].contains(event.record.timestamp))
            notices.extend(issue.message for issue in scan.issues)
            notices.extend(issue.message for issue in result.issues)
            notices.append(f"{provider} source scan: {scan.state}. This describes available local files, not account-wide coverage.")
            if scan.issue_counts:
                notices.append(provider + " ingestion issues: " + ", ".join(f"{code}={count}" for code, count in scan.issue_counts.items()))
            candidates = [event.record for event in result.events]
        records.extend(r for r in candidates if ranges[provider].contains(r.timestamp))
    if not records:
        notices.append("No local token records found in this period. This does not establish zero account usage.")
    return Report(sorted(records, key=lambda r: r.timestamp), periods, now, sorted(set(notices)), prices or {}, demo,
                  period, dict(DEFAULT_PLAN_FEES) if plan_costs is None else dict(plan_costs),
                  timezone, ranges, scans, accounting, tuple(events))


def plan_comparison(report: Report, view=None) -> list[str]:
    if report.period != "month" or report.filtered:
        return []
    results, combined = report.comparisons(view)
    lines = ["MONTH-TO-DATE PLAN COMPARISON", "Estimated API value = recorded tokens multiplied by model token prices.",
             "Comparison uses the full monthly fee; calendar month, not your billing cycle."]
    for result in (*results, combined):
        if not result.available:
            lines.append(f"{result.provider}: comparison unavailable ({result.reason}).")
            continue
        if result.provider == "Combined":
            lines.append(f"Combined: API value {money_text(result.value_usd, 2)} | Monthly plans {money_text(result.fee_usd, 2)}")
        else:
            lines.append(f"{result.provider}: Estimated API value {money_text(result.value_usd, 2)} | Monthly plan {money_text(result.fee_usd, 2)}")
        partial = result.pricing_state == "partial"
        label = "Priced subtotal minus monthly fee" if partial else "Estimated API value minus monthly fee"
        if result.provider == "Combined":
            label += "s"
        lines.append(f"  {label}: {money_text(result.difference_usd, 2, signed=True)}"
                     + (" (priced usage only; unpriced models excluded)" if partial else ""))
        lines.append("  Qualifications: " + ", ".join(result.qualifications))
    lines.append("Estimates cover local logs only, across accounts; no monthly projection, actual bill, or realized savings.")
    return lines


def pricing_note(report, summary):
    return (f"Pricing coverage: {summary.state}; unpriced records {summary.unpriced_records:,} / "
            f"tokens {summary.unpriced_tokens:,}; assumption-bearing records {summary.assumed_records:,}. "
            f"Pricing version {report.catalog.version}; policy {POLICY_VERSION}. "
            "Coverage describes configured rates, not full source/account accuracy.")


def render_report(report: Report) -> str:
    view = report.valuation_view()
    def text(value):
        return escape(str(value), quote=True)

    def date(value):
        return local_datetime(value, report.timezone).strftime("%Y-%m-%d %H:%M:%S %z")

    def summarize(records):
        summary = report.summarize_value(records, view)
        return summary.tokens, summary_value_text(summary), summary.unpriced_records

    def reasoning_text(records):
        known = [r.reasoning_tokens for r in records if r.reasoning_tokens is not None]
        if not known:
            return "not recorded"
        return f"{sum(known):,}" + (" + not recorded" if len(known) < len(records) else "")

    def table(title, key):
        groups = defaultdict(list)
        for record in report.records:
            groups[key(record)].append(record)
        rows = []
        for label, records in sorted(groups.items()):
            tokens, money, _ = summarize(records)
            cells = [label, f"{tokens.input:,}", f"{tokens.cached:,}", f"{tokens.write5m:,}", f"{tokens.write1h:,}", f"{tokens.output:,}", reasoning_text(records), f"{tokens.total:,}", money]
            rows.append("<tr>" + "".join(f"<td>{text(c)}</td>" for c in cells) + "</tr>")
        headers = [title, "Uncached input", "Cache read", "Cache write 5m", "Cache write 1h", "Output incl. reasoning", "Reasoning (subset)", "Total tokens", "Est. API value (USD)"]
        return f"<h2>{text(title)}</h2><div class='scroll'><table><thead><tr>" + "".join(f"<th>{text(h)}</th>" for h in headers) + "</tr></thead><tbody>" + ("".join(rows) or "<tr><td colspan='9'>No local records in this period</td></tr>") + "</tbody></table></div>"

    def history():
        headers = [f"Time ({report.timezone})", "Provider", "Model", "Effort", "Effort source", "Conversation", "Turn ID", "Uncached input", "Cache read", "Cache write 5m", "Cache write 1h", "Output incl. reasoning", "Reasoning (subset)", "Total tokens", "Est. API value (USD)"]
        rows = []
        for record in report.records:
            tokens = record.tokens
            cost = view[id(record)].amount_usd
            cells = [date(record.timestamp), record.provider, record.model, record.effort,
                     record.effort_source, record.session, record.turn_id or "not recorded",
                     f"{tokens.input:,}", f"{tokens.cached:,}", f"{tokens.write5m:,}", f"{tokens.write1h:,}",
                     f"{tokens.output:,}", reasoning_text([record]), f"{tokens.total:,}",
                     summary_value_text(aggregate_values([view[id(record)]])) if cost is not None else "unpriced"]
            rows.append("<tr>" + "".join(f"<td>{text(c)}</td>" for c in cells) + "</tr>")
        return f"<h2>Turn and usage-event history</h2><p>Each row is a recorded usage increment or completed Claude message. A turn can contain several rows. Effort is taken from that turn or message's recorded metadata; missing values stay unknown.</p><details><summary>Show {len(rows):,} usage records</summary><div class='scroll'><table><thead><tr>" + "".join(f"<th>{text(h)}</th>" for h in headers) + "</tr></thead><tbody>" + "".join(rows) + "</tbody></table></div></details>"

    totals, money, unknown = summarize(report.records)
    valuation_summary = report.summarize_value(view=view)
    boundaries = "".join(f"<li><b>{text(p)}</b>: {text(date(start))} to {text(date(report.end))} (end exclusive) — {text(label)}</li>" for p, (start, label) in report.periods.items())
    notices = list(report.notices)
    missing_effort = [r for r in report.records if r.effort == "unknown"]
    if missing_effort:
        notices.append(f"Effort was not recorded for {len(missing_effort):,} usage records ({sum(r.tokens.total for r in missing_effort):,} tokens). These remain in an unknown-effort bucket; today's settings and thinking budgets are not used to guess historical effort.")
    if unknown:
        models = sorted({r.model for r in report.records if view[id(r)].state == "unpriced"})
        notices.append("Unpriced usage by model (token counts included, dollar subtotal incomplete): " + ", ".join(models))
    notice_html = "".join(f"<li>{text(n)}</li>" for n in notices)
    pricing = []
    for model in sorted({r.model for r in report.records}):
        selection = report.catalog.lookup(model)
        p = selection.price if selection else None
        values = "Unknown — excluded from dollar subtotal" if p is None else f"input ${p.input:g}; output ${p.output:g}; cache read ${p.cached:g}; cache write 5m ${rate_text(p.write5m)}; cache write 1h ${rate_text(p.write1h)}"
        if p and p.threshold and p.high:
            values += f"; above {p.threshold:,} input tokens/request: input ${p.high[0]:g}, output ${p.high[1]:g}, cache read ${p.high[2]:g}"
        source = selection.source if selection else PRICE_SOURCE
        source_link = "Custom rates" if selection and selection.custom else f"<a href='{text(source)}'>Rate source</a>"
        pricing.append(f"<li><b>{text(model)}</b>: {text(values)} ({source_link})</li>")
    comparison = plan_comparison(report, view)
    sections = ("<section>" + "".join(f"<p>{text(line)}</p>" for line in comparison) + "</section>" if comparison else "") + (
        table("Provider", lambda r: r.provider)
        + table("Model + effort", lambda r: f"{r.provider} / {r.model} / {r.effort}")
        + table("Effort", lambda r: f"{r.provider} / {r.effort}")
        + table("Model", lambda r: f"{r.provider} / {r.model}")
        + table("Project", lambda r: f"{r.provider} / {r.project}")
        + table("Conversation", lambda r: f"{r.provider} / {r.session}")
        + table(f"Day ({report.timezone})", lambda r: date(r.timestamp)[:10])
        + history()
    )
    demo = "<p class='notice'>DEMO — sample data; no local logs or accounts were accessed.</p>" if report.demo else ""
    return """<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Usage Tray — estimated API value</title><style>
body{font:15px system-ui,sans-serif;background:#101827;color:#e5ecf5;max-width:1250px;margin:32px auto;padding:0 20px;line-height:1.55}h1,h2{color:#fff}a{color:#86ccff}.summary{display:flex;gap:30px;flex-wrap:wrap;padding:20px;background:#1d2b42;border-radius:12px}.summary strong{display:block;font-size:28px}.scroll{overflow:auto}table{border-collapse:collapse;width:100%;font-size:13px}td,th{padding:10px;text-align:right;border-bottom:1px solid #344259;white-space:nowrap}td:first-child,th:first-child{text-align:left;white-space:normal;overflow-wrap:anywhere}th{color:#a8c5df}.notice{padding:12px;background:#473c23;border-radius:8px}small{color:#b7c7d9}
</style><h1>Token usage &amp; API-equivalent value</h1>""" + demo + f"<div class='summary'><div><strong>{totals.total:,}</strong>Local recorded tokens</div><div><strong>{text(money)}</strong>Estimated API-equivalent value<br>{text(pricing_note(report, valuation_summary))}</div><div><strong>{len({(r.provider, r.session) for r in report.records}):,}</strong>Conversations</div></div><ul>{boundaries}</ul>" + "<p>Dollar values estimate standard API list-price usage. They are not subscription charges or a conversion of your limit percentage. The monthly comparison subtracts your monthly plan fee from the estimated API value of recorded usage so far. Counts include only token records available on this computer, across accounts using these log folders. Browser chat, remote/cloud tasks, other devices, missing logs, and unrecorded activity are excluded. Reasoning is included in output; cached input is counted once. No prompts or replies appear in this report.</p><p>Effort is the recorded request setting, not a measurement of thinking performed. Switching medium, high, or ultra changes the usage bucket for subsequent recorded work. Cost uses actual recorded tokens and model prices without an effort multiplier. Reasoning tokens, when recorded separately, are shown as a subset of output and are never billed twice. Labels such as xhigh, max, and ultra are preserved separately.</p>" + (f"<ul class='notice'>{notice_html}</ul>" if notices else "") + sections + f"<h2>Pricing assumptions (USD per million tokens)</h2><p>Bundled standard prices checked {PRICE_DATE}; <a href='{PRICE_SOURCE}'>price registry source</a>. Custom exact-model rates override bundled entries. Discounts, service-tier premiums, tool charges, taxes, and other unrecorded billing adjustments are excluded.</p><ul>{''.join(pricing)}</ul><small>Generated locally {text(date(report.end))}. This file contains local project names and conversation IDs; review before sharing.</small></html>"


def render_text_report(report: Report) -> str:
    """Render local usage in a readable terminal format without browser dependencies."""
    view = report.valuation_view()
    def clean(value):
        return "".join(c if c.isprintable() else " " for c in str(value))

    def summary(records):
        value = report.summarize_value(records, view)
        tokens = value.tokens
        reasoning = [r.reasoning_tokens for r in records if r.reasoning_tokens is not None]
        return [
            f"  Total tokens: {tokens.total:,} | Est. API value: {summary_value_text(value)}",
            f"  Input: {tokens.input:,} | Cache read: {tokens.cached:,} | Output: {tokens.output:,}",
            f"  Cache write 5m: {tokens.write5m:,} | Cache write 1h: {tokens.write1h:,}",
            "  Reasoning (already in output): " + (f"{sum(reasoning):,}" if reasoning else "not recorded")
            + (" (partial coverage)" if reasoning and len(reasoning) < len(records) else ""),
        ]

    lines = ["USAGE TRAY - ESTIMATED API VALUE", "=" * 64,
             "What these tokens would approximately cost at API token prices.",
             "This is a comparison estimate, not an actual charge."]
    if report.demo:
        lines.append("DEMO - sample data; no local logs or accounts accessed.")
    for provider, (start, label) in report.periods.items():
        lines.append(f"{provider}: {label}")
        lines.append(f"  {local_datetime(start, report.timezone):%Y-%m-%d %H:%M %z} to {local_datetime(report.end, report.timezone):%Y-%m-%d %H:%M %z} ({report.timezone}; end exclusive)")
    lines += ["", "TOTAL"] + summary(report.records)
    lines.append(pricing_note(report, report.summarize_value(view=view)))
    comparison = plan_comparison(report, view)
    if comparison:
        lines += [""] + comparison
    for title, key in [
        ("PROVIDER", lambda r: r.provider),
        ("MODEL + EFFORT", lambda r: f"{r.provider} / {r.model} / {r.effort}"),
        ("PROJECT", lambda r: f"{r.provider} / {r.project}"),
        ("CONVERSATION", lambda r: f"{r.provider} / {r.session}"),
        ("DAY", lambda r: local_datetime(r.timestamp, report.timezone).strftime("%Y-%m-%d")),
    ]:
        groups = defaultdict(list)
        for record in report.records:
            groups[key(record)].append(record)
        lines += ["", title, "-" * 64]
        for label, records in sorted(groups.items()):
            lines += [clean(label)] + summary(records)
    lines += ["", "NOTES", "Dollar values are API-equivalent estimates, not subscription charges.",
              "Only local recorded usage is included. Unknown effort stays unknown.",
              "Reasoning is included in output; cached input is counted once.",
              f"Bundled pricing snapshot: {PRICE_DATE}. Custom prices apply when configured."]
    unpriced = sorted({r.model for r in report.records if view[id(r)].state == "unpriced"})
    if unpriced:
        lines.append("Unpriced usage by model (USD subtotal incomplete): " + clean(", ".join(unpriced)))
    lines += ["", "RATES - USD PER MILLION TOKENS"]
    for model in sorted({r.model for r in report.records}):
        selection = report.catalog.lookup(model)
        price = selection.price if selection else None
        if price is None:
            lines.append(clean(model) + ": no published rate configured; excluded from USD subtotal.")
            continue
        lines.append(f"{clean(model)}: input ${price.input:g} | output ${price.output:g} | cache read ${price.cached:g}")
        if (price.write5m is not None or price.write1h is not None
                or any(r.model == model and (r.tokens.write5m or r.tokens.write1h) for r in report.records)):
            lines.append(f"  Cache write 5m ${rate_text(price.write5m)} | 1h ${rate_text(price.write1h)}")
        if price.threshold and price.high:
            lines.append(f"  Above {price.threshold:,} request input tokens: input ${price.high[0]:g} | output ${price.high[1]:g} | cache read ${price.high[2]:g}")
        lines.append("  Source: " + ("custom prices" if selection.custom else selection.source))
    missing = sum(r.effort == "unknown" for r in report.records)
    if missing:
        lines.append(f"Effort not recorded for {missing:,} usage records.")
    lines += [clean(notice) for notice in report.notices]
    return "\n".join(lines) + "\n"


def report_directory() -> Path:
    return Path(os.environ.get("LOCALAPPDATA") or Path.home() / ".local" / "share") / "UsageTray" / "Reports"


def save_report(report: Report, output: Path | None = None, format="html") -> Path:
    if format not in ("html", "text"):
        raise ValueError("Unsupported report format")
    if output is None:
        base = report_directory()
        base.mkdir(parents=True, exist_ok=True)
        handle, filename = tempfile.mkstemp(prefix="usage-" + datetime.now().strftime("%Y%m%d-%H%M%S-"), suffix=".txt" if format == "text" else ".html", dir=base)
        os.close(handle)
        output = Path(filename)
    else:
        output = Path(output).expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_text_report(report) if format == "text" else render_report(report), encoding="utf-8")
    return output.resolve()
