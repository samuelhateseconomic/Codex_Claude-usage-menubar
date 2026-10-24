"""Read-only local dashboard preview over the existing accounting core.

No database or network provider polling occurs here. Each browser query uses
one immutable in-memory dataset and one captured range; rescan is explicit.
"""
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from decimal import Decimal
import hashlib
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import threading
import time
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from usage_reports import (Record, Tokens, Price, PRICE_DATE, default_roots,
                           read_claude, read_codex)
from usage_value import summarize_records
from usage_valuation import (DEFAULT_PLAN_FEES, bounded_decimal, build_catalog,
                             compare_plans, ComparisonScope, value_event)


def decimal_text(value):
    if value is None:
        return None
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text

PROVIDERS = ("Codex", "Claude")
TOKEN_FIELDS = {"input": "uncached_input_tokens", "output": "output_tokens", "cached": "cache_read_tokens",
                "write5m": "cache_write_5m_tokens", "write1h": "cache_write_1h_tokens"}
STATIC = Path(__file__).with_name("dashboard")


def identifier(provider, session):
    return hashlib.sha256(json.dumps([provider, session], ensure_ascii=True).encode()).hexdigest()[:32]


def summary_dto(records, prices):
    summary = summarize_records(records, prices)
    tokens = {TOKEN_FIELDS[key]: str(value) for key, value in asdict(summary.tokens).items()}
    tokens["total_tokens"] = str(summary.tokens.total)
    return {"tokens": tokens, "record_count": summary.record_count,
            "reasoning_tokens": None if summary.reasoning_tokens is None else str(summary.reasoning_tokens),
            "reasoning_records": summary.reasoning_records,
            "value": {"state": summary.state, "amount_usd": decimal_text(summary.amount),
                      "unpriced_records": summary.unpriced_records, "unpriced_tokens": str(summary.unpriced_tokens)}}


def demo_records(now, zone):
    """Reviewed synthetic fixture. Rates are explicitly sample, not live prices."""
    rows = [
        ("Codex", "usage-hub", "high", 23, 10000, 1830000, 1000000, 0, 0, 1260000),
        ("Claude", "portfolio", "high", 23, 20000, 400000, 600000, 50000, 0, None),
        ("Claude", "research-notes", "unknown", 23, 10000, 300000, 500000, 0, 20000, None),
        ("Codex", "usage-hub", "medium", 22, 20000, 300000, 600000, 0, 0, 90000),
        ("Codex", "portfolio", "high", 21, 10000, 250000, 500000, 0, 0, 80000),
        ("Claude", "research-notes", "high", 20, 10000, 100000, 300000, 20000, 0, None),
        ("Codex", "tools", "medium", 18, 10000, 200000, 400000, 0, 0, 60000),
        ("Claude", "tools", "high", 17, 10000, 80000, 200000, 0, 0, None),
        ("Codex", "usage-hub", "high", 10, 10000, 150000, 300000, 0, 0, 40000),
        ("Claude", "portfolio", "unknown", 8, 10000, 60000, 180000, 0, 0, None),
        ("Codex", "research-notes", "medium", 5, 10000, 100000, 200000, 0, 0, 30000),
        ("Claude", "usage-hub", "high", 1, 10000, 40000, 100000, 0, 0, None),
    ]
    local = datetime.fromtimestamp(now, zone)
    records = []
    for i, (provider, project, effort, day, inp, out, cache, w5, w1, reasoning) in enumerate(rows):
        when = local.replace(day=min(day, local.day), hour=10, minute=i, second=0, microsecond=0).timestamp()
        records.append(Record(provider, min(when, now - 1), f"demo-{provider.lower()}-{i + 1:02}", project,
                              "gpt-6.1-sol" if provider == "Codex" else "claude-opus-5-5",
                              Tokens(inp, out, cache, w5, w1), effort, "demo metadata", f"demo-turn-{i + 1}", reasoning))
    return tuple(records)


@dataclass(frozen=True)
class Dataset:
    revision: str
    captured_at: float
    records: tuple[Record, ...]
    issues: tuple[str, ...]


class HubService:
    def __init__(self, *, demo=False, roots=None, prices=None, fees=None, timezone="America/Los_Angeles",
                 states=(), clock=time.time):
        self.demo = demo
        self.roots = default_roots() if roots is None else roots
        self.prices = dict(prices or {})
        if demo:
            self.prices.update({"gpt-6.1-sol": Price(2, 10, .1), "claude-opus-5-5": Price(4, 20, .2, 5, 8)})
        configured_fees = DEFAULT_PLAN_FEES if fees is None else fees
        self.fees = {p: bounded_decimal(configured_fees[p]) if configured_fees.get(p) is not None else None
                     for p in PROVIDERS}
        try:
            self.zone = ZoneInfo(timezone)
        except ZoneInfoNotFoundError:
            raise ValueError("Named timezone data unavailable. Install the pinned tzdata dependency.") from None
        self.states, self.clock = states, clock
        self.lock = threading.Lock()
        self.scan_lock = threading.Lock()
        self.dataset = None
        self.scan_error = None
        self.last_scan = None

    def refresh(self):
        if not self.scan_lock.acquire(blocking=False):
            return {"state": "in_progress"}
        try:
            now = self.clock()
            if self.last_scan is not None and now - self.last_scan < 5:
                return {"state": "cooldown", "retry_after_seconds": 5}
            self.last_scan = now
            issues = []
            try:
                if self.demo:
                    records = demo_records(now, self.zone)
                else:
                    records = tuple(read_codex(self.roots.get("Codex", []), issues) +
                                    read_claude(self.roots.get("Claude", []), issues))
                if any("could not be read" in issue or "could not be inspected" in issue or
                       "Some folders could not" in issue or "changed during" in issue for issue in issues):
                    raise OSError("source_read_failed")
                dataset = Dataset(secrets.token_hex(12), now, tuple(records), tuple(sorted(set(issues))))
                with self.lock:
                    self.dataset, self.scan_error = dataset, None
                return {"state": "complete", "usage_revision": dataset.revision}
            except Exception:
                with self.lock:
                    self.scan_error = "Local scan failed. Check approved log-folder access; the previous snapshot is retained when available."
                return {"state": "failed", "retained_previous": self.dataset is not None}
        finally:
            self.scan_lock.release()

    def query(self, params):
        allowed = {"period", "provider", "project", "model", "effort", "q", "day", "conversation", "revision", "page"}
        if params.keys() - allowed or any(len(str(value)) > 512 for value in params.values()):
            raise ValueError("invalid_query")
        with self.lock:
            dataset, scan_error = self.dataset, self.scan_error
        if dataset is None:
            raise RuntimeError("scan_unavailable")
        if params.get("revision") and params["revision"] != dataset.revision:
            raise LookupError("revision_conflict")
        provider, period = params.get("provider", "both"), params.get("period", "month")
        if provider not in ("both", "codex", "claude") or period not in ("month", "week", "today"):
            raise ValueError("invalid_filter")
        local = datetime.fromtimestamp(dataset.captured_at, self.zone)
        start = (local.replace(day=1, hour=0, minute=0, second=0, microsecond=0).timestamp() if period == "month"
                 else local.replace(hour=0, minute=0, second=0, microsecond=0).timestamp() if period == "today"
                 else dataset.captured_at - 168 * 3600)
        records = [r for r in dataset.records if start <= r.timestamp < dataset.captured_at
                   and (provider == "both" or r.provider.lower() == provider)]
        facets = {key: sorted({getattr(r, key) for r in records}) for key in ("project", "model", "effort")}
        for key in ("project", "model", "effort"):
            if params.get(key):
                records = [r for r in records if getattr(r, key) == params[key]]
        if params.get("q"):
            query = params["q"].casefold()
            records = [r for r in records if query in r.project.casefold() or query in r.session.casefold()]
        if params.get("day"):
            datetime.strptime(params["day"], "%Y-%m-%d")
            records = [r for r in records if datetime.fromtimestamp(r.timestamp, self.zone).strftime("%Y-%m-%d") == params["day"]]
        selected = tuple(records)
        groups = defaultdict(list)
        projects = defaultdict(list)
        models = defaultdict(list)
        days = defaultdict(list)
        for record in records:
            groups[identifier(record.provider, record.session)].append(record)
            projects[record.project].append(record)
            models[(record.provider, record.model, record.effort)].append(record)
            days[datetime.fromtimestamp(record.timestamp, self.zone).strftime("%Y-%m-%d")].append(record)

        def group_dto(key, items):
            first = min(items, key=lambda r: r.timestamp)
            last = max(items, key=lambda r: r.timestamp)
            return dict(id=key, provider=first.provider, project=last.project, session=first.session,
                        models=sorted({r.model for r in items}), efforts=sorted({r.effort for r in items}),
                        first_at=first.timestamp, last_at=last.timestamp, **summary_dto(items, self.prices))

        conversations = sorted((group_dto(key, items) for key, items in groups.items()),
                               key=lambda group: (-group["last_at"], group["id"]))
        detail = None
        if params.get("conversation"):
            items = groups.get(params["conversation"])
            if items is None:
                raise KeyError("conversation_not_in_query")
            detail = group_dto(params["conversation"], items)
            detail["events"] = [dict(timestamp=r.timestamp, model=r.model, effort=r.effort,
                effort_source=r.effort_source, turn_id=r.turn_id, **summary_dto([r], self.prices))
                for r in sorted(items, key=lambda r: r.timestamp)]
        page = int(params.get("page", "1"))
        if page < 1 or page > 1_000_000:
            raise ValueError("invalid_page")
        comparisons = []
        comparable = period == "month" and not any(params.get(k) for k in ("project", "model", "effort", "q", "day"))
        if comparable:
            catalog = build_catalog(self.prices)
            scope = ComparisonScope(PROVIDERS if provider == "both" else (provider.title(),), period, True)
            results, _ = compare_plans((value_event(record, catalog) for record in selected), scope, self.fees)
            comparisons = [{"provider": value.provider, "fee_usd": decimal_text(value.fee_usd),
                            "state": value.pricing_state, "difference_usd": decimal_text(value.difference_usd)}
                           for value in results]
        normalized = {key: params[key] for key in sorted(params) if key not in ("conversation", "page", "revision") and params[key]}
        context_id = hashlib.sha256(json.dumps([dataset.revision, start, dataset.captured_at, normalized], sort_keys=True).encode()).hexdigest()[:32]
        def contribution(item):
            amount = item["value"]["amount_usd"]
            return amount is None, -Decimal(amount or "0")
        project_groups = sorted([dict(project=key, **summary_dto(items, self.prices))
                                 for key, items in sorted(projects.items())], key=contribution)
        model_groups = sorted([dict(provider=key[0], model=key[1], effort=key[2], **summary_dto(items, self.prices))
                               for key, items in sorted(models.items())], key=contribution)
        return {"dataset": "demo" if self.demo else "real", "scope": "all_local_accounts_unmatched",
            "usage_revision": dataset.revision, "query_context_id": context_id,
            "captured_at": dataset.captured_at, "range": {"start_at": start, "end_at": dataset.captured_at,
                "timezone": str(self.zone), "end_exclusive": True}, "period": period,
            "quality": "stale" if scan_error else "partial" if dataset.issues else "available",
            "issues": list(dataset.issues) + ([scan_error] if scan_error else []),
            "pricing": {"version": "sample-v2" if self.demo else PRICE_DATE, "tier_policy": "sample fixed rates" if self.demo
                else "Compatibility estimate: event input counters do not prove per-request context; bundled rates are a snapshot."},
            "summary": dict(conversation_count=len(groups), project_count=len(projects), **summary_dto(selected, self.prices)),
            "facets": facets, "comparisons": comparisons,
            "days": [dict(day=day, **summary_dto(items, self.prices)) for day, items in sorted(days.items())],
            "projects": project_groups, "models": model_groups,
            "conversations": conversations[(page-1)*6:page*6], "page": page,
            "page_count": max(1, (len(conversations)+5)//6), "detail": detail,
            "settings": {"fees_usd": {p: decimal_text(self.fees[p]) for p in PROVIDERS}, "timezone": str(self.zone),
                "editable": False, "roots": {} if self.demo else {p: [str(root) for root in self.roots.get(p, [])] for p in PROVIDERS}},
            "limits": self.limits()}

    def limits(self):
        if self.demo:
            return [{"provider": provider, "state": "demo", "remaining": remaining,
                     "note": "Sample capacity; not a live account reading."} for provider, remaining in (("Codex", 62), ("Claude", 28))]
        result = []
        for provider in PROVIDERS:
            state = next((s for s in self.states if s.provider == provider), None)
            if state is None:
                result.append({"provider": provider, "state": "unavailable", "note": "Open from the tray to use its cached provider readings."})
                continue
            with state.lock:
                snapshot = state.snapshot
                result.append({"provider": provider, "state": "stale" if state.error and snapshot else "available" if snapshot else "unavailable",
                    "snapshot": None if snapshot is None else snapshot.to_dict(), "note": state.error,
                    "remaining": min((w.remaining for w in snapshot.windows), default=None) if snapshot else None})
        return result


def create_server(service, port=8765):
    if getattr(service, 'contract_version', None) == 'usage-hub-v1':
        from usage_api_http import handler_class, LocalSessions
        class LocalServer(ThreadingHTTPServer):
            def __init__(self, *args):
                self.closing = False
                self.inflight = 0
                self.drained = threading.Condition()
                super().__init__(*args)

            def process_request(self, request, client_address):
                # Count before thread creation, so shutdown cannot miss an
                # accepted operation whose worker has not started yet.
                with self.drained:
                    self.inflight += 1
                try:
                    super().process_request(request, client_address)
                except BaseException:
                    self.request_finished()
                    raise

            def request_finished(self):
                with self.drained:
                    self.inflight -= 1
                    self.drained.notify_all()

            def process_request_thread(self, request, client_address):
                try:
                    super().process_request_thread(request, client_address)
                finally:
                    self.request_finished()

            def wait_drained(self, timeout):
                with self.drained:
                    return self.drained.wait_for(lambda: self.inflight == 0, timeout=timeout)

            def handle_error(self, request, client_address):
                pass  # Never print untrusted query/header/provider payloads.
        server = LocalServer(('127.0.0.1', port), handler_class(service))
        server.sessions = LocalSessions()
        server.daemon_threads = True
        return server
    token = secrets.token_urlsafe(32)
    files = {"/": ("index.html", "text/html; charset=utf-8"), "/app.js": ("app.js", "text/javascript; charset=utf-8"),
             "/style.css": ("style.css", "text/css; charset=utf-8"),
             "/format.js": ("format.js", "text/javascript; charset=utf-8")}
    for path in STATIC.glob("*.js"):
        files["/" + path.name] = (path.name, "text/javascript; charset=utf-8")
    for path in (STATIC / "assets").glob("*"):
        if path.suffix in (".svg", ".woff2"):
            files["/assets/" + path.name] = ("assets/" + path.name, "image/svg+xml" if path.suffix == ".svg" else "font/woff2")

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass  # Never log IDs, queries, source metadata, or cookies.

        def respond(self, status, body, kind="application/json", cookie=False):
            if not isinstance(body, bytes):
                body = json.dumps(body, ensure_ascii=True).encode()
            self.send_response(status)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; font-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
            if cookie:
                self.send_header("Set-Cookie", f"usage_hub={token}; HttpOnly; SameSite=Strict; Path=/")
            try:
                self.end_headers()
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                # A superseded browser query may close the socket. There is no
                # recipient for a second error response or raw traceback.
                self.close_connection = True

        def permitted(self, api=False):
            origin = f"http://127.0.0.1:{self.server.server_port}"
            if self.headers.get("Host") != origin.removeprefix("http://"):
                return False
            if self.headers.get("Origin") not in (None, origin) or self.headers.get("Sec-Fetch-Site") == "cross-site":
                return False
            if api:
                try:
                    cookie = SimpleCookie(self.headers.get("Cookie", ""))
                    value = cookie.get("usage_hub")
                    return bool(value and secrets.compare_digest(value.value, token) and self.headers.get("X-Usage-Hub") == "1")
                except Exception:
                    return False
            return True

        def do_GET(self):
            if not self.permitted():
                return self.respond(403, {"error": "origin_rejected"})
            url = urlsplit(self.path)
            if url.path == "/api/preview/query":
                if not self.permitted(api=True):
                    return self.respond(403, {"error": "session_required"})
                try:
                    if len(self.path) > 4096:
                        raise ValueError()
                    parsed = parse_qs(url.query, keep_blank_values=True, max_num_fields=16)
                    if any(len(values) != 1 for values in parsed.values()):
                        raise ValueError()
                    return self.respond(200, service.query({key: values[0] for key, values in parsed.items()}))
                except KeyError:
                    return self.respond(404, {"error": "conversation_not_in_query"})
                except (ValueError, OverflowError):
                    return self.respond(400, {"error": "invalid_query"})
                except LookupError:
                    return self.respond(409, {"error": "revision_conflict"})
                except RuntimeError:
                    return self.respond(503, {"error": "scan_unavailable"})
                except Exception:
                    return self.respond(500, {"error": "local_query_failed"})
            if url.path not in files:
                return self.respond(404, {"error": "not_found"})
            filename, kind = files[url.path]
            try:
                body = (STATIC / filename).read_bytes()
                if url.path == "/":
                    body = body.replace(b'<html lang="en">', b'<html lang="en" data-api-mode="preview">', 1)
                return self.respond(200, body, kind, cookie=url.path == "/")
            except OSError:
                return self.respond(500, {"error": "asset_unavailable"})

        def do_POST(self):
            if not self.permitted(api=True):
                return self.respond(403, {"error": "session_required"})
            if self.path != "/api/preview/rescan":
                return self.respond(404, {"error": "not_found"})
            if self.headers.get("Content-Length", "0") != "0" or self.headers.get("Transfer-Encoding"):
                return self.respond(400, {"error": "unexpected_body"})
            result = service.refresh()
            return self.respond(503 if result["state"] == "failed" else 200, result)

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.daemon_threads = True
    return server
