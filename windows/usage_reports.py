"""Read local CLI token counters and produce offline, content-free HTML reports."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from html import escape
from usage_privacy import display_text, metadata_label
import os
from pathlib import Path
import tempfile
import time

from usage_artifacts import generated_directory, prune_reports
from usage_config import application_directory, load_prices
from usage_ingestion import discover, parsed_entries, scan_observations, verified_prefix
from usage_time import DEFAULT_TIMEZONE, RangeContext, local_datetime, resolve_range
from usage_records import Record, Tokens
from usage_reconciliation import reconcile_observations
from usage_observations import CanonicalEvent, extract_claude, extract_codex, recorded_effort, timestamp
from usage_service import (QueryContext, SourceQuality, UsageResult, build_usage_result, collect_usage,
                           default_roots, summarize_values)
from usage_valuation import (Price, PRICES, PRICE_SOURCE, PRICE_DATE, MODEL_PRICE_SOURCES,
                             DEFAULT_PLAN_FEES, POLICY_VERSION, RateCatalog, aggregate_values, bounded_decimal,
                             build_catalog, money_text, price_for, rate_text, value_event,
                             value_text as summary_value_text)


def estimate(record: Record, overrides: dict | None = None) -> float | None:
    """Legacy float projection only; authoritative consumers use value_event."""
    amount = value_event(record, build_catalog(overrides)).amount_usd
    return float(amount) if amount is not None else None


def value_text(records, prices=None, precision=4):
    catalog = build_catalog(prices)
    return summary_value_text(aggregate_values(value_event(r, catalog) for r in records), precision)


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

    def query_result(self):
        """Snapshot mutable legacy inputs at the adapter boundary, once per render."""
        by_identity = {id(event.record): event for event in self.events}
        entries = tuple(by_identity.get(id(r), r) for r in self.records)
        context = QueryContext(tuple(self.ranges.items()), self.end, self.period, self.timezone,
                               demo=self.demo, filtered=self.filtered)
        sources = tuple(SourceQuality(p, scan.state, tuple(scan.issues),
                        tuple(self.accounting_issues.get(p, ())), scan.roots_read,
                        scan.files_discovered, scan.files_read) for p, scan in self.scans.items())
        calendar_compatible = set(self.ranges) == set(self.periods) and all(
            r.start == self.periods[p][0] for p, r in self.ranges.items())
        return build_usage_result(entries, context, self.catalog, self.plan_costs, sources,
                                  self.notices, calendar_compatible)

    def valuation_view(self):
        return {id(d.record): d.valuation for d in self.query_result().details}

    def summarize_value(self, records=None, view=None):
        if records is None and view is None:
            return self.query_result().total.value
        view = self.valuation_view() if view is None else view
        return summarize_values(view[id(r)] for r in (self.records if records is None else records)).value

    def comparisons(self, view=None):
        # view is a legacy parameter; scope and pricing always come from one snapshot.
        result = self.query_result()
        return result.comparisons, result.combined_comparison


def collect_report(period="session", providers=("Codex", "Claude"), snapshots=None,
                   roots=None, now=None, prices=None, demo=False, plan_costs=None, timezone=DEFAULT_TIMEZONE) -> Report:
    """Compatible mutable container; collection and all query semantics live in the service."""
    collected = collect_usage(period, providers, snapshots, roots, now, demo, timezone)
    context = collected.context
    events = tuple(e for e in collected.entries if isinstance(e, CanonicalEvent))
    records = [e.record if isinstance(e, CanonicalEvent) else e for e in collected.entries]
    return Report(sorted(records, key=lambda r: r.timestamp),
                  {p: (r.start, r.label) for p, r in context.ranges}, context.captured_at,
                  list(collected.notices), prices or {}, demo, period,
                  dict(DEFAULT_PLAN_FEES) if plan_costs is None else dict(plan_costs), timezone,
                  dict(context.ranges), {s.provider: s for s in collected.sources},
                  {s.provider: s.accounting_issues for s in collected.sources}, events)


def _result(report):
    return report if isinstance(report, UsageResult) else report.query_result()


def plan_comparison(report: Report | UsageResult, view=None) -> list[str]:
    result = _result(report)
    if result.context.period != "month" or result.context.is_filtered:
        return []
    results, combined = result.comparisons, result.combined_comparison
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
            f"App {report.app_version}; build {report.build_id}; parser {report.parser_version}; "
            f"reconciliation {report.reconciliation_version}; query {report.query_version}; "
            f"settings {report.settings_version or 'explicit_programmatic_inputs'}. "
            "Coverage describes configured rates, not full source/account accuracy.")


def render_report(report: Report | UsageResult, *, include_metadata=False) -> str:
    report = _result(report)
    context = report.context
    def text(value):
        return escape(display_text(value), quote=True)

    def date(value):
        return local_datetime(value, context.timezone).strftime("%Y-%m-%d %H:%M:%S %z")

    def reasoning_text(reasoning):
        if reasoning.known_tokens is None:
            return "not recorded"
        return f"{reasoning.known_tokens:,}" + (" + not recorded" if reasoning.unknown_records else "")

    def table(title, dimension):
        rows = []
        for group in report.groups_for(dimension):
            tokens, value = group.summary.tokens, group.summary.value
            label = " / ".join(metadata_label(v, "project" if dimension == "project" else "id", include_metadata)
                               if dimension in ("project", "conversation") and i else v for i, v in enumerate(group.key))
            cells = [label, f"{tokens.input:,}", f"{tokens.cached:,}", f"{tokens.write5m:,}", f"{tokens.write1h:,}", f"{tokens.output:,}", reasoning_text(group.summary.reasoning), f"{tokens.total:,}", summary_value_text(value)]
            rows.append("<tr>" + "".join(f"<td>{text(c)}</td>" for c in cells) + "</tr>")
        headers = [title, "Uncached input", "Cache read", "Cache write 5m", "Cache write 1h", "Output incl. reasoning", "Reasoning (subset)", "Total tokens", "Est. API value (USD)"]
        return f"<h2>{text(title)}</h2><div class='scroll'><table><thead><tr>" + "".join(f"<th>{text(h)}</th>" for h in headers) + "</tr></thead><tbody>" + ("".join(rows) or "<tr><td colspan='9'>No local records in this period</td></tr>") + "</tbody></table></div>"

    def history():
        headers = [f"Time ({context.timezone})", "Provider", "Model", "Effort", "Effort source", "Conversation", "Turn ID", "Uncached input", "Cache read", "Cache write 5m", "Cache write 1h", "Output incl. reasoning", "Reasoning (subset)", "Total tokens", "Est. API value (USD)"]
        rows = []
        for detail in report.details:
            record = detail.record
            tokens = detail.summary.tokens
            cost = detail.valuation.amount_usd
            cells = [date(record.timestamp), record.provider, record.model, record.effort,
                     record.effort_source, metadata_label(record.session, "id", include_metadata),
                     metadata_label(record.turn_id or "not recorded", "id", include_metadata),
                     f"{tokens.input:,}", f"{tokens.cached:,}", f"{tokens.write5m:,}", f"{tokens.write1h:,}",
                     f"{tokens.output:,}", reasoning_text(detail.summary.reasoning), f"{tokens.total:,}",
                     summary_value_text(detail.summary.value) if cost is not None else "unpriced"]
            rows.append("<tr>" + "".join(f"<td>{text(c)}</td>" for c in cells) + "</tr>")
        return f"<h2>Turn and usage-event history</h2><p>Each row is a recorded usage increment or completed Claude message. A turn can contain several rows. Effort is taken from that turn or message's recorded metadata; missing values stay unknown.</p><details><summary>Show {len(rows):,} usage records</summary><div class='scroll'><table><thead><tr>" + "".join(f"<th>{text(h)}</th>" for h in headers) + "</tr></thead><tbody>" + "".join(rows) + "</tbody></table></div></details>"

    totals = report.total.tokens
    valuation_summary = report.total.value
    money, unknown = summary_value_text(valuation_summary), valuation_summary.unpriced_records
    boundaries = "".join(f"<li><b>{text(p)}</b>: {text(date(start))} to {text(date(context.captured_at))} (end exclusive) — {text(label)}</li>" for p, (start, label) in ((p, (r.start, r.label)) for p, r in context.ranges))
    notices = list(report.notices)
    if report.missing_effort_records:
        notices.append(f"Effort was not recorded for {report.missing_effort_records:,} usage records ({report.missing_effort_tokens:,} tokens). These remain in an unknown-effort bucket; today's settings and thinking budgets are not used to guess historical effort.")
    if unknown:
        models = report.unpriced_models
        notices.append("Unpriced usage by model (token counts included, dollar subtotal incomplete): " + ", ".join(models))
    notice_html = "".join(f"<li>{text(n)}</li>" for n in notices)
    pricing = []
    for model in report.models:
        selection = report.catalog.lookup(model)
        p = selection.price if selection else None
        values = "Unknown — excluded from dollar subtotal" if p is None else f"input ${p.input:g}; output ${p.output:g}; cache read ${p.cached:g}; cache write 5m ${rate_text(p.write5m)}; cache write 1h ${rate_text(p.write1h)}"
        if p and p.threshold and p.high:
            values += f"; above {p.threshold:,} input tokens/request: input ${p.high[0]:g}, output ${p.high[1]:g}, cache read ${p.high[2]:g}"
        source = selection.source if selection else PRICE_SOURCE
        source_link = "Custom rates" if selection and selection.custom else f"<a href='{text(source)}'>Rate source</a>"
        pricing.append(f"<li><b>{text(model)}</b>: {text(values)} ({source_link})</li>")
    comparison = plan_comparison(report)
    sections = ("<section>" + "".join(f"<p>{text(line)}</p>" for line in comparison) + "</section>" if comparison else "") + (
        table("Provider", "provider")
        + table("Model + effort", "model_effort")
        + table("Effort", "effort")
        + table("Model", "model")
        + table("Project", "project")
        + table("Conversation", "conversation")
        + table(f"Day ({context.timezone})", "day")
        + history()
    )
    metadata_note = "Full project paths and IDs explicitly included; review before sharing." if include_metadata else "Reduced metadata: project basenames and abbreviated ID digests; this is not anonymization."
    demo = "<p class='notice'>DEMO — sample data; no local logs or accounts were accessed.</p>" if context.demo else ""
    return """<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'">
<title>Usage Tray — estimated API value</title><style>
body{font:15px system-ui,sans-serif;background:#101827;color:#e5ecf5;max-width:1250px;margin:32px auto;padding:0 20px;line-height:1.55}h1,h2{color:#fff}a{color:#86ccff}.summary{display:flex;gap:30px;flex-wrap:wrap;padding:20px;background:#1d2b42;border-radius:12px}.summary strong{display:block;font-size:28px}.scroll{overflow:auto}table{border-collapse:collapse;width:100%;font-size:13px}td,th{padding:10px;text-align:right;border-bottom:1px solid #344259;white-space:nowrap}td:first-child,th:first-child{text-align:left;white-space:normal;overflow-wrap:anywhere}th{color:#a8c5df}.notice{padding:12px;background:#473c23;border-radius:8px}small{color:#b7c7d9}
</style><h1>Token usage &amp; API-equivalent value</h1>""" + demo + f"<p>{metadata_note}</p><div class='summary'><div><strong>{totals.total:,}</strong>Local recorded tokens</div><div><strong>{text(money)}</strong>Estimated API-equivalent value<br>{text(pricing_note(report, valuation_summary))}</div><div><strong>{report.total.conversation_count:,}</strong>Conversations</div></div><ul>{boundaries}</ul>" + "<p>Dollar values estimate standard API list-price usage. They are not subscription charges or a conversion of your limit percentage. The monthly comparison subtracts your monthly plan fee from the estimated API value of recorded usage so far. Counts include only token records available on this computer, across accounts using these log folders. Browser chat, remote/cloud tasks, other devices, missing logs, and unrecorded activity are excluded. Reasoning is included in output; cached input is counted once. No prompts or replies appear in this report.</p><p>Effort is the recorded request setting, not a measurement of thinking performed. Switching medium, high, or ultra changes the usage bucket for subsequent recorded work. Cost uses actual recorded tokens and model prices without an effort multiplier. Reasoning tokens, when recorded separately, are shown as a subset of output and are never billed twice. Labels such as xhigh, max, and ultra are preserved separately.</p>" + (f"<ul class='notice'>{notice_html}</ul>" if notices else "") + sections + f"<h2>Pricing assumptions (USD per million tokens)</h2><p>Bundled standard prices checked {PRICE_DATE}; <a href='{PRICE_SOURCE}'>price registry source</a>. Custom exact-model rates override bundled entries. Discounts, service-tier premiums, tool charges, taxes, and other unrecorded billing adjustments are excluded.</p><ul>{''.join(pricing)}</ul><small>Generated locally {text(date(context.captured_at))}. This file contains local project names and usage metadata; review before sharing. Full paths and IDs require an explicit metadata export.</small></html>"


def render_text_report(report: Report | UsageResult, *, include_metadata=False) -> str:
    """Format an authoritative headless result without calculating usage."""
    report = _result(report)
    context = report.context
    def clean(value):
        return display_text(value)

    def summary(summary):
        value, tokens, reasoning = summary.value, summary.tokens, summary.reasoning
        return [
            f"  Total tokens: {tokens.total:,} | Est. API value: {summary_value_text(value)}",
            f"  Input: {tokens.input:,} | Cache read: {tokens.cached:,} | Output: {tokens.output:,}",
            f"  Cache write 5m: {tokens.write5m:,} | Cache write 1h: {tokens.write1h:,}",
            "  Reasoning (already in output): " + (f"{reasoning.known_tokens:,}" if reasoning.known_tokens is not None else "not recorded")
            + (" (partial coverage)" if reasoning.known_tokens is not None and reasoning.unknown_records else ""),
        ]

    lines = ["USAGE TRAY - ESTIMATED API VALUE", "=" * 64,
             "What these tokens would approximately cost at API token prices.",
             "This is a comparison estimate, not an actual charge.",
             "Full project paths and conversation IDs explicitly included; review before sharing." if include_metadata else
             "Reduced metadata: project basenames and abbreviated ID digests; this is not anonymization."]
    if context.demo:
        lines.append("DEMO - sample data; no local logs or accounts accessed.")
    for provider, r in context.ranges:
        start, label = r.start, r.label
        lines.append(f"{provider}: {label}")
        lines.append(f"  {local_datetime(start, context.timezone):%Y-%m-%d %H:%M %z} to {local_datetime(context.captured_at, context.timezone):%Y-%m-%d %H:%M %z} ({context.timezone}; end exclusive)")
    lines += ["", "TOTAL"] + summary(report.total)
    lines.append(pricing_note(report, report.total.value))
    comparison = plan_comparison(report)
    if comparison:
        lines += [""] + comparison
    for title, dimension in [("PROVIDER", "provider"), ("MODEL + EFFORT", "model_effort"),
                             ("PROJECT", "project"), ("CONVERSATION", "conversation"), ("DAY", "day")]:
        lines += ["", title, "-" * 64]
        for group in report.groups_for(dimension):
            label = " / ".join(metadata_label(v, "project" if dimension == "project" else "id", include_metadata)
                               if dimension in ("project", "conversation") and i else v for i, v in enumerate(group.key))
            lines += [label] + summary(group.summary)
    lines += ["", "NOTES", "Dollar values are API-equivalent estimates, not subscription charges.",
              "Only local recorded usage is included. Unknown effort stays unknown.",
              "Reasoning is included in output; cached input is counted once.",
              f"Bundled pricing snapshot: {PRICE_DATE}. Custom prices apply when configured."]
    unpriced = report.unpriced_models
    if unpriced:
        lines.append("Unpriced usage by model (USD subtotal incomplete): " + clean(", ".join(unpriced)))
    lines += ["", "RATES - USD PER MILLION TOKENS"]
    for model in report.models:
        selection = report.catalog.lookup(model)
        price = selection.price if selection else None
        if price is None:
            lines.append(clean(model) + ": no published rate configured; excluded from USD subtotal.")
            continue
        lines.append(f"{clean(model)}: input ${price.input:g} | output ${price.output:g} | cache read ${price.cached:g}")
        if (price.write5m is not None or price.write1h is not None
                or model in report.write_models):
            lines.append(f"  Cache write 5m ${rate_text(price.write5m)} | 1h ${rate_text(price.write1h)}")
        if price.threshold and price.high:
            lines.append(f"  Above {price.threshold:,} request input tokens: input ${price.high[0]:g} | output ${price.high[1]:g} | cache read ${price.high[2]:g}")
        lines.append("  Source: " + ("custom prices" if selection.custom else selection.source))
    missing = report.missing_effort_records
    if missing:
        lines.append(f"Effort not recorded for {missing:,} usage records.")
    lines += [clean(notice) for notice in report.notices]
    return "\n".join(clean(line) for line in lines) + "\n"


def report_directory() -> Path:
    return application_directory() / "Reports"


def save_report(report: Report | UsageResult, output: Path | None = None, format="html", *, include_metadata=False) -> Path:
    if format not in ("html", "text"):
        raise ValueError("Unsupported report format")
    generated = output is None
    if generated:
        base = generated_directory()
        base.mkdir(parents=True, exist_ok=True)
        handle, filename = tempfile.mkstemp(prefix="usage-" + datetime.now().strftime("%Y%m%d-%H%M%S-"), suffix=".txt" if format == "text" else ".html", dir=base)
        os.close(handle)
        output = Path(filename)
    else:
        output = Path(output).expanduser().resolve()
        if output.is_relative_to(generated_directory()):
            raise ValueError("The generated folder is reserved for automatic reports; choose another output directory.")
        output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_text_report(report, include_metadata=include_metadata) if format == "text" else render_report(report, include_metadata=include_metadata), encoding="utf-8")
    if generated:
        outcome = prune_reports(keep=output)
        if outcome.failed:
            import warnings
            warnings.warn("Generated report retention could not finish; saved report is available.", RuntimeWarning)
    return output.resolve()
