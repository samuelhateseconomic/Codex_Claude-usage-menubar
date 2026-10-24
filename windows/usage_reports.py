"""Read local CLI token counters and produce offline, content-free HTML reports."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime
from html import escape
import json
import math
import os
from pathlib import Path
import re
import tempfile
import time


# Standard USD per million tokens. No subscription price or quota conversion.
# Snapshot of LiteLLM's public price registry, checked 2026-10-23 Pacific.
# https://github.com/BerriAI/litellm/blob/main/model_prices_and_context_window.json
PRICE_SOURCE = "https://github.com/BerriAI/litellm/blob/main/model_prices_and_context_window.json"
PRICE_DATE = "2026-10-23"
MODEL_PRICE_SOURCES = {
    "gpt-6.1-sol": "https://developers.openai.com/api/docs/models/gpt-6.1-sol",
    "claude-opus-5-5": "https://platform.claude.com/docs/en/models/opus-5-5/overview",
}


@dataclass(frozen=True)
class Price:
    input: float
    output: float
    cached: float
    write5m: float = 0
    write1h: float = 0
    threshold: int | None = None
    high: tuple[float, float, float] | None = None


PRICES = {
    # Official model pages verified 2026-10-23. Standard USD per 1M tokens.
    "gpt-6.1-sol": Price(2, 10, 0.1, threshold=272000, high=(4, 15, 0.2)),
    "claude-opus-5-5": Price(4, 20, 0.2, 5, 8),
    "gpt-5": Price(1.25, 10, 0.125),
    "gpt-5-codex": Price(1.25, 10, 0.125),
    "gpt-5.1": Price(1.25, 10, 0.125),
    "gpt-5.1-codex": Price(1.25, 10, 0.125),
    "gpt-5.1-codex-max": Price(1.25, 10, 0.125),
    "gpt-5.1-codex-mini": Price(0.25, 2, 0.025),
    "gpt-5.2": Price(1.75, 14, 0.175),
    "gpt-5.2-codex": Price(1.75, 14, 0.175),
    "gpt-5.3-codex": Price(1.75, 14, 0.175),
    "gpt-5.4": Price(2.5, 15, 0.25, threshold=272000, high=(5, 22.5, 0.5)),
    "claude-opus-4-6": Price(5, 25, 0.5, 6.25, 10),
    "claude-opus-4-5": Price(5, 25, 0.5, 6.25, 10),
    "claude-sonnet-4-6": Price(3, 15, 0.3, 3.75, 6),
    "claude-sonnet-4-5": Price(3, 15, 0.3, 3.75, 6),
    "claude-haiku-4-5": Price(1, 5, 0.1, 1.25, 2),
}


@dataclass(frozen=True)
class Tokens:
    input: int = 0  # Uncached input only, for both providers.
    output: int = 0  # Includes reasoning; reasoning is never added twice.
    cached: int = 0
    write5m: int = 0
    write1h: int = 0

    @property
    def total(self):
        return self.input + self.output + self.cached + self.write5m + self.write1h

    def __add__(self, other):
        return Tokens(*(a + b for a, b in zip(asdict(self).values(), asdict(other).values())))


@dataclass(frozen=True)
class Record:
    provider: str
    timestamp: float
    session: str
    project: str
    model: str
    tokens: Tokens
    effort: str = "unknown"
    effort_source: str = "not recorded"
    turn_id: str | None = None
    reasoning_tokens: int | None = None  # A subset of output, never an extra charge.


def price_for(model: str, overrides: dict | None = None) -> Price | None:
    prices = dict(PRICES)
    prices.update(overrides or {})
    if model in prices:
        return prices[model]
    # Only dated snapshots inherit a known model's price, never an unknown variant.
    base = re.sub(r"-(?:\d{8}|\d{4}-\d{2}-\d{2})$", "", model)
    return prices.get(base)


def estimate(record: Record, overrides: dict | None = None) -> float | None:
    price = price_for(record.model, overrides)
    if price is None:
        return None
    tokens = record.tokens
    inp, out, cached = price.input, price.output, price.cached
    if price.threshold and tokens.input + tokens.cached > price.threshold and price.high:
        inp, out, cached = price.high
    return (tokens.input * inp + tokens.output * out + tokens.cached * cached
            + tokens.write5m * price.write5m + tokens.write1h * price.write1h) / 1_000_000


def value_text(records, prices, precision=4):
    """An unknown price is unavailable, never a zero-dollar estimate."""
    values = [estimate(record, prices) for record in records]
    known = [value for value in values if value is not None]
    if not values:
        return "Unavailable (no usage records)"
    if not known:
        return "Unavailable (all usage unpriced)"
    return f"${sum(known):,.{precision}f}" + (" + unpriced usage" if len(known) < len(values) else "")


def load_prices(path: Path | None) -> dict:
    if path is None:
        return {}
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict):
        raise ValueError("Prices must be an object keyed by exact model name.")
    prices = {}
    for name, values in data.items():
        if not isinstance(name, str) or not isinstance(values, dict):
            raise ValueError("Invalid model price entry.")
        if not {"input", "output", "cached"} <= values.keys():
            raise ValueError("Each model needs input, output, and cached USD per million tokens.")
        if values.keys() - {"input", "output", "cached", "write5m", "write1h"}:
            raise ValueError("Unsupported price fields; use input, output, cached, write5m, write1h.")
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v < 0 for v in values.values()):
            raise ValueError("Prices must be finite, nonnegative numbers.")
        prices[name] = Price(**values)
    return prices


def timestamp(value) -> float | None:
    if not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.timestamp() if dt.tzinfo is not None else None
    except (ValueError, OverflowError, OSError):
        return None


def count(value) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def object_value(value) -> dict:
    return value if isinstance(value, dict) else {}


def recorded_effort(*sources: tuple[str, dict]) -> tuple[str, str] | None:
    """Only read explicit metadata; never infer effort from budgets or text."""
    for name, data in sources:
        for key in ("effort", "reasoning_effort", "reasoningEffort", "effortValue", "effortLevel"):
            if key not in data:
                continue
            value = data[key]
            if isinstance(value, str) and value.strip() and len(value) <= 80 and not any(ord(c) < 32 for c in value):
                # Preserve wire values: xhigh, max, and ultra are distinct.
                return value.strip(), f"{name}.{key}"
            return "unknown", f"{name}.{key} (unavailable)"
    return None


def reasoning_count(usage: dict, output: int) -> int | None:
    value = usage.get("reasoning_output_tokens")
    if "reasoning_output_tokens" not in usage:
        value = object_value(usage.get("output_tokens_details")).get("reasoning_tokens")
    if isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= output:
        return value
    return None


def log_files(roots: list[Path], notices: list[str], since: float | None = None):
    for root in roots:
        if not root.is_dir():
            notices.append(f"Log folder not found: {root}")
            continue
        errors = []
        for directory, _, files in os.walk(root, followlinks=False, onerror=errors.append):
            for name in sorted(files):
                path = Path(directory) / name
                if path.suffix == ".jsonl" and not path.is_symlink():
                    try:
                        if since is not None and path.stat().st_mtime < since:
                            continue
                    except OSError:
                        notices.append(f"A log file could not be inspected: {path.name}")
                        continue
                    yield path
        if errors:
            notices.append(f"Some folders could not be read under {root}.")


def lines(path: Path, notices: list[str]):
    invalid = False
    try:
        with path.open(encoding="utf-8-sig", errors="replace") as stream:
            for line in stream:
                if not line.strip():
                    continue
                try:
                    data = json.loads(line)
                except ValueError:
                    invalid = True
                    continue
                if isinstance(data, dict):
                    yield data
    except OSError:
        notices.append(f"A log file could not be read: {path.name}")
    if invalid:
        notices.append(f"Malformed or incomplete records skipped in {path.name}.")


def read_claude(roots: list[Path], notices: list[str], since: float | None = None) -> list[Record]:
    messages = {}
    for path in log_files(roots, notices, since):
        session_root = None
        turn_effort = None
        turn_id = None
        for entry in lines(path, notices):
            if session_root is None and isinstance(entry.get("cwd"), str):
                session_root = entry["cwd"]
            msg = object_value(entry.get("message"))
            if entry.get("type") == "user":
                content = msg.get("content")
                tool_result = (isinstance(content, list) and bool(content)
                               and all(isinstance(block, dict) and block.get("type") == "tool_result" for block in content))
                if not tool_result:
                    # Each new user turn resets effort. A missing setting must
                    # not inherit the preceding turn's explicit setting.
                    turn_effort = recorded_effort(("Claude user", entry), ("Claude user message", msg),
                                                  ("Claude user output_config", object_value(msg.get("output_config"))))
                    turn_id = str(entry["uuid"]) if entry.get("uuid") else None
                continue
            if entry.get("type") != "assistant":
                continue
            usage = object_value(msg.get("usage"))
            when = timestamp(entry.get("timestamp"))
            model = msg.get("model")
            if not usage or when is None or model == "<synthetic>":
                continue
            session = str(entry.get("sessionId") or path.stem)
            # Missing identifiers cannot safely be deduplicated; report the gap.
            if not msg.get("id"):
                notices.append("Claude usage records without message IDs were skipped.")
                continue
            creation = object_value(usage.get("cache_creation"))
            write5m = count(creation.get("ephemeral_5m_input_tokens"))
            write1h = count(creation.get("ephemeral_1h_input_tokens"))
            if not creation:
                write5m = count(usage.get("cache_creation_input_tokens"))
                if write5m:
                    notices.append("Legacy Claude cache writes without TTL details are estimated at the 5-minute write price.")
            tokens = Tokens(count(usage.get("input_tokens")), count(usage.get("output_tokens")),
                            count(usage.get("cache_read_input_tokens")), write5m, write1h)
            key = (session, str(msg["id"]), str(entry.get("requestId") or ""))
            previous = messages.get(key)
            explicit_effort = recorded_effort(
                ("Claude assistant", entry), ("Claude assistant message", msg),
                ("Claude output_config", object_value(msg.get("output_config"))),
                ("Claude request output_config", object_value(object_value(entry.get("request")).get("output_config"))),
            )
            effort, source = explicit_effort or ((previous.effort, previous.effort_source) if previous else None) or turn_effort or ("unknown", "not recorded")
            reasoning = reasoning_count(usage, tokens.output)
            if previous:
                # Streamed assistant records update the same usage. Keep maxima,
                # not a sum of chunks, and attribute to the final response time.
                tokens = Tokens(*(max(a, b) for a, b in zip(asdict(tokens).values(), asdict(previous.tokens).values())))
                when = max(when, previous.timestamp)
                if previous.reasoning_tokens is not None:
                    reasoning = max(reasoning if reasoning is not None else 0, previous.reasoning_tokens)
            messages[key] = Record("Claude", when, session, session_root or path.parent.name,
                                   str(model or "unknown"), tokens, effort, source,
                                   previous.turn_id if previous else turn_id, reasoning)
    return list(messages.values())


def read_codex(roots: list[Path], notices: list[str], since: float | None = None) -> list[Record]:
    records = {}
    for path in log_files(roots, notices, since):
        session, project, model = path.stem, "Unknown project", "unknown"
        previous = (0, 0, 0)
        previous_reasoning = 0
        effort, effort_source = "unknown", "not recorded"
        turn_id = None
        last_only_seen = set()
        created = None
        forked = False
        for entry in lines(path, notices):
            kind = entry.get("type")
            payload = object_value(entry.get("payload"))
            if kind == "session_meta":
                session = str(payload.get("id") or session)
                project = str(payload.get("cwd") or project)
                created = timestamp(entry.get("timestamp"))
                forked = bool(payload.get("forked_from_id") or payload.get("forked_from_thread_id"))
                continue
            if kind == "turn_context":
                model = str(payload.get("model") or "unknown")
                effort, effort_source = recorded_effort(
                    ("Codex turn_context", payload),
                    ("Codex collaboration settings", object_value(object_value(payload.get("collaboration_mode")).get("settings"))),
                ) or ("unknown", "not recorded")
                turn_id = str(payload["turn_id"]) if payload.get("turn_id") else None
                continue
            if kind != "event_msg" or payload.get("type") != "token_count":
                continue
            when = timestamp(entry.get("timestamp"))
            info = object_value(payload.get("info"))
            totals = object_value(info.get("total_token_usage"))
            last = object_value(info.get("last_token_usage"))
            if when is None or not info:
                continue
            if totals:
                current = tuple(count(totals.get(key)) for key in ("input_tokens", "output_tokens", "cached_input_tokens"))
                current_reasoning = reasoning_count(totals, current[1])
                if any(a < b for a, b in zip(current, previous)):
                    notices.append("A Codex cumulative counter reset; an ambiguous interval was excluded.")
                    previous = current
                    previous_reasoning = current_reasoning
                    continue
                delta = tuple(a - b for a, b in zip(current, previous))
                reasoning = None
                if current_reasoning is not None and previous_reasoning is not None:
                    change = current_reasoning - previous_reasoning
                    if 0 <= change <= delta[1]:
                        reasoning = change
                if current != previous or current_reasoning is not None:
                    previous_reasoning = current_reasoning
                previous = current
                identity = (session, current)
            elif last:
                delta = tuple(count(last.get(key)) for key in ("input_tokens", "output_tokens", "cached_input_tokens"))
                reasoning = reasoning_count(last, delta[1])
                identity = (session, when, delta)
                if identity in last_only_seen:
                    continue
                last_only_seen.add(identity)
                notices.append("Codex records without cumulative counters use timestamp deduplication.")
            else:
                continue
            if forked and created is not None and when < created:
                continue  # Inherited history seeds counters but is not new fork usage.
            if not any(delta):
                continue  # Quota notifications often repeat the same cumulative totals.
            if delta[2] > delta[0]:
                notices.append("A Codex cached-input counter exceeded total input; that record was skipped.")
                continue
            # cached_input_tokens is a subset of input_tokens. Reasoning is a
            # subset of output_tokens and is deliberately not added again.
            tokens = Tokens(delta[0] - delta[2], delta[1], delta[2])
            records.setdefault(identity, Record("Codex", when, session, project, model, tokens,
                                                 effort, effort_source, turn_id, reasoning))
    return list(records.values())


def default_roots() -> dict[str, list[Path]]:
    codex = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")
    claude = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")
    return {"Codex": [codex / "sessions", codex / "archived_sessions"], "Claude": [claude / "projects"]}


def period_bounds(period: str, now: float, snapshot=None) -> tuple[float, str]:
    if period == "month":
        return datetime.fromtimestamp(now).replace(day=1, hour=0, minute=0, second=0, microsecond=0).timestamp(), "Month to date (local time)"
    if period == "today":
        return datetime.fromtimestamp(now).replace(hour=0, minute=0, second=0, microsecond=0).timestamp(), "Today (local time)"
    if period == "week":
        return now - 7 * 86400, "Last 7 days"
    if snapshot:
        for window in snapshot.windows:
            if window.duration_minutes == 300 and window.resets_at and now < window.resets_at <= now + 5 * 3600:
                return window.resets_at - 5 * 3600, "Current 5-hour quota session (provider reset time)"
    return now - 5 * 3600, "Last 5 hours (current quota-session boundary unavailable)"


@dataclass
class Report:
    records: list[Record]
    periods: dict[str, tuple[float, str]]
    end: float
    notices: list[str] = field(default_factory=list)
    prices: dict = field(default_factory=dict)
    demo: bool = False
    period: str = "session"
    plan_costs: dict = field(default_factory=lambda: {"Codex": 20.0, "Claude": 20.0})


def collect_report(period="session", providers=("Codex", "Claude"), snapshots=None,
                   roots=None, now=None, prices=None, demo=False, plan_costs=None) -> Report:
    now = time.time() if now is None else now
    roots = default_roots() if roots is None else roots
    snapshots = snapshots or {}
    periods = {p: period_bounds(period, now, snapshots.get(p)) for p in providers}
    records, notices = [], []
    for provider in providers:
        if demo:
            candidates = [Record(provider, now - 60 * (3 - i), "demo-conversation", "Demo project",
                                 "gpt-5.4" if provider == "Codex" else "claude-sonnet-4-6",
                                 Tokens(4000, 1000 * (i + 1), 12000), effort, "demo metadata",
                                 f"demo-turn-{i + 1}", 300 * (i + 1) if provider == "Codex" else None)
                          for i, effort in enumerate(("medium", "high", "ultra"))]
        else:
            reader = read_codex if provider == "Codex" else read_claude
            candidates = reader(roots.get(provider, []), notices, periods[provider][0])
        records.extend(r for r in candidates if periods[provider][0] <= r.timestamp <= now)
    if not records:
        notices.append("No local token records found in this period. This does not establish zero account usage.")
    return Report(sorted(records, key=lambda r: r.timestamp), periods, now, sorted(set(notices)), prices or {}, demo,
                  period, {"Codex": 20.0, "Claude": 20.0} if plan_costs is None else dict(plan_costs))


def plan_comparison(report: Report) -> list[str]:
    if report.period != "month":
        return []
    lines = ["MONTH-TO-DATE PLAN COMPARISON", "Estimated API value = recorded tokens multiplied by model token prices.",
             "Comparison uses the full monthly fee; calendar month, not your billing cycle."]
    total_value = total_fee = 0.0
    comparable = True
    incomplete = False
    for provider in report.periods:
        records = [r for r in report.records if r.provider == provider]
        fee = report.plan_costs.get(provider)
        if fee is None or not records:
            lines.append(f"{provider}: comparison unavailable (missing plan price or local usage records).")
            comparable = False
            continue
        values = [estimate(r, report.prices) for r in records]
        if all(value is None for value in values):
            lines.append(f"{provider}: comparison unavailable (all usage unpriced); monthly plan ${fee:,.2f}.")
            comparable = False
            continue
        partial = any(value is None for value in values)
        incomplete |= partial
        value = sum(value for value in values if value is not None)
        total_value += value
        total_fee += fee
        difference = value - fee
        label = "Priced subtotal minus monthly fee" if partial else "Estimated savings so far" if difference >= 0 else "Below monthly fee by"
        lines += [f"{provider}: Estimated API value ${value:,.2f} | Monthly plan ${fee:,.2f}",
                  f"  {label}: {'-' if partial and difference < 0 else ''}${abs(difference):,.2f}" + (" (priced usage only; unpriced models excluded)" if partial else "")]
    if comparable:
        difference = total_value - total_fee
        lines.append(f"Combined: API value ${total_value:,.2f} | Monthly plans ${total_fee:,.2f}")
        label = "Priced subtotal minus monthly fees: " if incomplete else "Estimated savings so far: " if difference >= 0 else "Below monthly fees by: "
        lines.append(label + ("-" if incomplete and difference < 0 else "")
                     + f"${abs(difference):,.2f}" + (" (priced usage only)" if incomplete else ""))
    lines.append("Estimates cover local logs only, across accounts; no monthly projection or actual bill.")
    return lines


def render_report(report: Report) -> str:
    def text(value):
        return escape(str(value), quote=True)

    def date(value):
        return datetime.fromtimestamp(value).strftime("%Y-%m-%d %H:%M:%S")

    def summarize(records):
        tokens = Tokens()
        cost = 0
        unknown = 0
        for record in records:
            tokens += record.tokens
            amount = estimate(record, report.prices)
            if amount is None:
                unknown += 1
            else:
                cost += amount
        money = value_text(records, report.prices)
        return tokens, money, unknown

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
        headers = ["Local time", "Provider", "Model", "Effort", "Effort source", "Conversation", "Turn ID", "Uncached input", "Cache read", "Cache write 5m", "Cache write 1h", "Output incl. reasoning", "Reasoning (subset)", "Total tokens", "Est. API value (USD)"]
        rows = []
        for record in report.records:
            tokens = record.tokens
            cost = estimate(record, report.prices)
            cells = [date(record.timestamp), record.provider, record.model, record.effort,
                     record.effort_source, record.session, record.turn_id or "not recorded",
                     f"{tokens.input:,}", f"{tokens.cached:,}", f"{tokens.write5m:,}", f"{tokens.write1h:,}",
                     f"{tokens.output:,}", reasoning_text([record]), f"{tokens.total:,}",
                     f"${cost:,.4f}" if cost is not None else "unpriced"]
            rows.append("<tr>" + "".join(f"<td>{text(c)}</td>" for c in cells) + "</tr>")
        return f"<h2>Turn and usage-event history</h2><p>Each row is a recorded usage increment or completed Claude message. A turn can contain several rows. Effort is taken from that turn or message's recorded metadata; missing values stay unknown.</p><details><summary>Show {len(rows):,} usage records</summary><div class='scroll'><table><thead><tr>" + "".join(f"<th>{text(h)}</th>" for h in headers) + "</tr></thead><tbody>" + "".join(rows) + "</tbody></table></div></details>"

    totals, money, unknown = summarize(report.records)
    boundaries = "".join(f"<li><b>{text(p)}</b>: {text(date(start))} to {text(date(report.end))} — {text(label)}</li>" for p, (start, label) in report.periods.items())
    notices = list(report.notices)
    missing_effort = [r for r in report.records if r.effort == "unknown"]
    if missing_effort:
        notices.append(f"Effort was not recorded for {len(missing_effort):,} usage records ({sum(r.tokens.total for r in missing_effort):,} tokens). These remain in an unknown-effort bucket; today's settings and thinking budgets are not used to guess historical effort.")
    if unknown:
        models = sorted({r.model for r in report.records if price_for(r.model, report.prices) is None})
        notices.append("Unpriced models (token counts included, dollar subtotal incomplete): " + ", ".join(models))
    notice_html = "".join(f"<li>{text(n)}</li>" for n in notices)
    pricing = []
    for model in sorted({r.model for r in report.records}):
        p = price_for(model, report.prices)
        values = "Unknown — excluded from dollar subtotal" if p is None else f"input ${p.input:g}; output ${p.output:g}; cache read ${p.cached:g}; cache write 5m ${p.write5m:g}; cache write 1h ${p.write1h:g}"
        if p and p.threshold and p.high:
            values += f"; above {p.threshold:,} input tokens/request: input ${p.high[0]:g}, output ${p.high[1]:g}, cache read ${p.high[2]:g}"
        source = MODEL_PRICE_SOURCES.get(model, PRICE_SOURCE)
        source_link = "Custom rates" if model in report.prices else f"<a href='{text(source)}'>Rate source</a>"
        pricing.append(f"<li><b>{text(model)}</b>: {text(values)} ({source_link})</li>")
    comparison = plan_comparison(report)
    sections = ("<section>" + "".join(f"<p>{text(line)}</p>" for line in comparison) + "</section>" if comparison else "") + (
        table("Provider", lambda r: r.provider)
        + table("Model + effort", lambda r: f"{r.provider} / {r.model} / {r.effort}")
        + table("Effort", lambda r: f"{r.provider} / {r.effort}")
        + table("Model", lambda r: f"{r.provider} / {r.model}")
        + table("Project", lambda r: f"{r.provider} / {r.project}")
        + table("Conversation", lambda r: f"{r.provider} / {r.session}")
        + table("Day (local time)", lambda r: date(r.timestamp)[:10])
        + history()
    )
    demo = "<p class='notice'>DEMO — sample data; no local logs or accounts were accessed.</p>" if report.demo else ""
    return """<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Usage Tray — estimated API value</title><style>
body{font:15px system-ui,sans-serif;background:#101827;color:#e5ecf5;max-width:1250px;margin:32px auto;padding:0 20px;line-height:1.55}h1,h2{color:#fff}a{color:#86ccff}.summary{display:flex;gap:30px;flex-wrap:wrap;padding:20px;background:#1d2b42;border-radius:12px}.summary strong{display:block;font-size:28px}.scroll{overflow:auto}table{border-collapse:collapse;width:100%;font-size:13px}td,th{padding:10px;text-align:right;border-bottom:1px solid #344259;white-space:nowrap}td:first-child,th:first-child{text-align:left;white-space:normal;overflow-wrap:anywhere}th{color:#a8c5df}.notice{padding:12px;background:#473c23;border-radius:8px}small{color:#b7c7d9}
</style><h1>Token usage &amp; API-equivalent value</h1>""" + demo + f"<div class='summary'><div><strong>{totals.total:,}</strong>Local recorded tokens</div><div><strong>{text(money)}</strong>Estimated API-equivalent value</div><div><strong>{len({(r.provider, r.session) for r in report.records}):,}</strong>Conversations</div></div><ul>{boundaries}</ul>" + "<p>Dollar values estimate standard API list-price usage. They are not subscription charges or a conversion of your limit percentage. The monthly comparison subtracts your monthly plan fee from the estimated API value of recorded usage so far. Counts include only token records available on this computer, across accounts using these log folders. Browser chat, remote/cloud tasks, other devices, missing logs, and unrecorded activity are excluded. Reasoning is included in output; cached input is counted once. No prompts or replies appear in this report.</p><p>Effort is the recorded request setting, not a measurement of thinking performed. Switching medium, high, or ultra changes the usage bucket for subsequent recorded work. Cost uses actual recorded tokens and model prices without an effort multiplier. Reasoning tokens, when recorded separately, are shown as a subset of output and are never billed twice. Labels such as xhigh, max, and ultra are preserved separately.</p>" + (f"<ul class='notice'>{notice_html}</ul>" if notices else "") + sections + f"<h2>Pricing assumptions (USD per million tokens)</h2><p>Bundled standard prices checked {PRICE_DATE}; <a href='{PRICE_SOURCE}'>price registry source</a>. Custom exact-model rates override bundled entries. Discounts, service-tier premiums, tool charges, taxes, and other unrecorded billing adjustments are excluded.</p><ul>{''.join(pricing)}</ul><small>Generated locally {text(date(report.end))}. This file contains local project names and conversation IDs; review before sharing.</small></html>"


def render_text_report(report: Report) -> str:
    """Render local usage in a readable terminal format without browser dependencies."""
    def clean(value):
        return "".join(c if c.isprintable() else " " for c in str(value))

    def summary(records):
        tokens = Tokens()
        cost = 0.0
        unpriced = False
        for record in records:
            tokens += record.tokens
            amount = estimate(record, report.prices)
            if amount is None:
                unpriced = True
            else:
                cost += amount
        reasoning = [r.reasoning_tokens for r in records if r.reasoning_tokens is not None]
        return [
            f"  Total tokens: {tokens.total:,} | Est. API value: {value_text(records, report.prices)}",
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
        lines.append(f"  {datetime.fromtimestamp(start):%Y-%m-%d %H:%M} to {datetime.fromtimestamp(report.end):%Y-%m-%d %H:%M}")
    lines += ["", "TOTAL"] + summary(report.records)
    comparison = plan_comparison(report)
    if comparison:
        lines += [""] + comparison
    for title, key in [
        ("PROVIDER", lambda r: r.provider),
        ("MODEL + EFFORT", lambda r: f"{r.provider} / {r.model} / {r.effort}"),
        ("PROJECT", lambda r: f"{r.provider} / {r.project}"),
        ("CONVERSATION", lambda r: f"{r.provider} / {r.session}"),
        ("DAY", lambda r: datetime.fromtimestamp(r.timestamp).strftime("%Y-%m-%d")),
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
    unpriced = sorted({r.model for r in report.records if estimate(r, report.prices) is None})
    if unpriced:
        lines.append("Unpriced models (USD subtotal incomplete): " + clean(", ".join(unpriced)))
    lines += ["", "RATES - USD PER MILLION TOKENS"]
    for model in sorted({r.model for r in report.records}):
        price = price_for(model, report.prices)
        if price is None:
            lines.append(clean(model) + ": no published rate configured; excluded from USD subtotal.")
            continue
        lines.append(f"{clean(model)}: input ${price.input:g} | output ${price.output:g} | cache read ${price.cached:g}")
        if price.write5m or price.write1h:
            lines.append(f"  Cache write 5m ${price.write5m:g} | 1h ${price.write1h:g}")
        if price.threshold and price.high:
            lines.append(f"  Above {price.threshold:,} request input tokens: input ${price.high[0]:g} | output ${price.high[1]:g} | cache read ${price.high[2]:g}")
        lines.append("  Source: " + ("custom prices" if model in report.prices else MODEL_PRICE_SOURCES.get(model, PRICE_SOURCE)))
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
