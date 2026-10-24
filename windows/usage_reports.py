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
        for entry in lines(path, notices):
            if session_root is None and isinstance(entry.get("cwd"), str):
                session_root = entry["cwd"]
            if entry.get("type") != "assistant":
                continue
            msg = object_value(entry.get("message"))
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
            if previous:
                # Streamed assistant records update the same usage. Keep maxima,
                # not a sum of chunks, and attribute to the final response time.
                tokens = Tokens(*(max(a, b) for a, b in zip(asdict(tokens).values(), asdict(previous.tokens).values())))
                when = max(when, previous.timestamp)
            messages[key] = Record("Claude", when, session, session_root or path.parent.name,
                                   str(model or "unknown"), tokens)
    return list(messages.values())


def read_codex(roots: list[Path], notices: list[str], since: float | None = None) -> list[Record]:
    records = {}
    for path in log_files(roots, notices, since):
        session, project, model = path.stem, "Unknown project", "unknown"
        previous = (0, 0, 0)
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
                if any(a < b for a, b in zip(current, previous)):
                    notices.append("A Codex cumulative counter reset; an ambiguous interval was excluded.")
                    previous = current
                    continue
                delta = tuple(a - b for a, b in zip(current, previous))
                previous = current
                identity = (session, current)
            elif last:
                delta = tuple(count(last.get(key)) for key in ("input_tokens", "output_tokens", "cached_input_tokens"))
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
            records.setdefault(identity, Record("Codex", when, session, project, model, tokens))
    return list(records.values())


def default_roots() -> dict[str, list[Path]]:
    codex = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")
    claude = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")
    return {"Codex": [codex / "sessions", codex / "archived_sessions"], "Claude": [claude / "projects"]}


def period_bounds(period: str, now: float, snapshot=None) -> tuple[float, str]:
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


def collect_report(period="session", providers=("Codex", "Claude"), snapshots=None,
                   roots=None, now=None, prices=None, demo=False) -> Report:
    now = time.time() if now is None else now
    roots = default_roots() if roots is None else roots
    snapshots = snapshots or {}
    periods = {p: period_bounds(period, now, snapshots.get(p)) for p in providers}
    records, notices = [], []
    for provider in providers:
        if demo:
            candidates = [Record(provider, now - 60, "demo-conversation", "Demo project", "gpt-5.4" if provider == "Codex" else "claude-sonnet-4-6", Tokens(12000, 2500, 40000))]
        else:
            reader = read_codex if provider == "Codex" else read_claude
            candidates = reader(roots.get(provider, []), notices, periods[provider][0])
        records.extend(r for r in candidates if periods[provider][0] <= r.timestamp <= now)
    if not records:
        notices.append("No local token records found in this period. This does not establish zero account usage.")
    return Report(sorted(records, key=lambda r: r.timestamp), periods, now, sorted(set(notices)), prices or {}, demo)


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
        money = f"${cost:,.4f}" + (" + unpriced usage" if unknown else "")
        return tokens, money, unknown

    def table(title, key):
        groups = defaultdict(list)
        for record in report.records:
            groups[key(record)].append(record)
        rows = []
        for label, records in sorted(groups.items()):
            tokens, money, _ = summarize(records)
            cells = [label, f"{tokens.input:,}", f"{tokens.cached:,}", f"{tokens.write5m:,}", f"{tokens.write1h:,}", f"{tokens.output:,}", f"{tokens.total:,}", money]
            rows.append("<tr>" + "".join(f"<td>{text(c)}</td>" for c in cells) + "</tr>")
        headers = [title, "Uncached input", "Cache read", "Cache write 5m", "Cache write 1h", "Output incl. reasoning", "Total tokens", "Est. USD"]
        return f"<h2>{text(title)}</h2><div class='scroll'><table><thead><tr>" + "".join(f"<th>{text(h)}</th>" for h in headers) + "</tr></thead><tbody>" + ("".join(rows) or "<tr><td colspan='8'>No local records in this period</td></tr>") + "</tbody></table></div>"

    totals, money, unknown = summarize(report.records)
    boundaries = "".join(f"<li><b>{text(p)}</b>: {text(date(start))} to {text(date(report.end))} — {text(label)}</li>" for p, (start, label) in report.periods.items())
    notices = list(report.notices)
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
        pricing.append(f"<li><b>{text(model)}</b>: {text(values)}</li>")
    sections = table("Provider", lambda r: r.provider) + table("Model", lambda r: f"{r.provider} / {r.model}") + table("Project", lambda r: f"{r.provider} / {r.project}") + table("Conversation", lambda r: f"{r.provider} / {r.session}") + table("Day (local time)", lambda r: date(r.timestamp)[:10])
    demo = "<p class='notice'>DEMO — sample data; no local logs or accounts were accessed.</p>" if report.demo else ""
    return """<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Usage Tray — token and cost report</title><style>
body{font:15px system-ui,sans-serif;background:#101827;color:#e5ecf5;max-width:1250px;margin:32px auto;padding:0 20px;line-height:1.55}h1,h2{color:#fff}a{color:#86ccff}.summary{display:flex;gap:30px;flex-wrap:wrap;padding:20px;background:#1d2b42;border-radius:12px}.summary strong{display:block;font-size:28px}.scroll{overflow:auto}table{border-collapse:collapse;width:100%;font-size:13px}td,th{padding:10px;text-align:right;border-bottom:1px solid #344259;white-space:nowrap}td:first-child,th:first-child{text-align:left;white-space:normal;overflow-wrap:anywhere}th{color:#a8c5df}.notice{padding:12px;background:#473c23;border-radius:8px}small{color:#b7c7d9}
</style><h1>Token usage &amp; API-equivalent value</h1>""" + demo + f"<div class='summary'><div><strong>{totals.total:,}</strong>Local recorded tokens</div><div><strong>{text(money)}</strong>Estimated API-equivalent value</div><div><strong>{len({(r.provider, r.session) for r in report.records}):,}</strong>Conversations</div></div><ul>{boundaries}</ul>" + "<p>Dollar values estimate standard API list-price usage. They are not subscription charges, savings, or a conversion of your limit percentage. Counts include only token records available on this computer, across accounts using these log folders. Browser chat, remote/cloud tasks, other devices, missing logs, and unrecorded activity are excluded. Reasoning is included in output; cached input is counted once. No prompts or replies appear in this report.</p>" + (f"<ul class='notice'>{notice_html}</ul>" if notices else "") + sections + f"<h2>Pricing assumptions (USD per million tokens)</h2><p>Bundled standard prices checked {PRICE_DATE}; <a href='{PRICE_SOURCE}'>price registry source</a>. Custom exact-model rates override bundled entries. Discounts, service-tier premiums, tool charges, taxes, and other unrecorded billing adjustments are excluded.</p><ul>{''.join(pricing)}</ul><small>Generated locally {text(date(report.end))}. This file contains local project names and conversation IDs; review before sharing.</small></html>"


def report_directory() -> Path:
    return Path(os.environ.get("LOCALAPPDATA") or Path.home() / ".local" / "share") / "UsageTray" / "Reports"


def save_report(report: Report, output: Path | None = None) -> Path:
    if output is None:
        base = report_directory()
        base.mkdir(parents=True, exist_ok=True)
        handle, filename = tempfile.mkstemp(prefix="usage-" + datetime.now().strftime("%Y%m%d-%H%M%S-"), suffix=".html", dir=base)
        os.close(handle)
        output = Path(filename)
    else:
        output = Path(output).expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_report(report), encoding="utf-8")
    return output.resolve()
