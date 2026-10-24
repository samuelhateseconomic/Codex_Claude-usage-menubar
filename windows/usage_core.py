"""Provider adapters for Usage Tray. No GUI dependencies or token persistence."""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import queue
import shutil
import subprocess
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from urllib import error, request

from usage_identity import APP_VERSION
from usage_process import ChildTree


class UsageError(Exception):
    """A safe, actionable adapter message plus an allowlisted recovery category."""
    def __init__(self, message, *, category="provider_error"):
        super().__init__(message)
        self.category = category if category in {"provider_error", "login_required", "network_error", "cooldown", "unsupported_response", "unexpected_local", "cancelled"} else "unexpected_local"


def check_cancelled(cancel_event):
    if cancel_event is not None and cancel_event.is_set():
        raise UsageError("Provider check cancelled during shutdown.", category="cancelled")


class RateLimited(UsageError):
    def __init__(self, retry_after: float = 300):
        super().__init__("Rate limited; waiting before retrying.", category="cooldown")
        self.retry_after = max(300, retry_after) if isinstance(retry_after, (int, float)) and math.isfinite(retry_after) else 300


@dataclass(frozen=True)
class Window:
    label: str
    used: float
    resets_at: float | None = None
    duration_minutes: float | None = None

    @property
    def remaining(self) -> float:
        return max(0, min(100, 100 - self.used))

    def text(self) -> str:
        reset = "reset time unavailable"
        if self.resets_at is not None:
            try:
                reset = "resets " + datetime.fromtimestamp(self.resets_at).strftime("%a %H:%M")
            except (ValueError, OverflowError, OSError):
                pass
        return f"{self.label}: {self.remaining:.0f}% left · {reset}"


@dataclass(frozen=True)
class Snapshot:
    provider: str
    windows: list[Window]
    checked_at: float = field(default_factory=time.time)
    note: str = ""
    blocked: bool = False

    def to_dict(self) -> dict:
        result = asdict(self)
        for original, serialized in zip(self.windows, result["windows"]):
            serialized["remaining"] = original.remaining
        return result


def number(value) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


def parse_codex(payload: dict) -> Snapshot:
    """Consume Codex app-server's documented camelCase response schema."""
    buckets = payload.get("rateLimitsByLimitId")
    if not isinstance(buckets, dict) or not buckets:
        buckets = {"codex": payload.get("rateLimits", {})}
    windows = []
    for bucket_id, bucket in buckets.items():
        if not isinstance(bucket, dict):
            continue
        name = bucket.get("limitName") or bucket_id
        for key in ("primary", "secondary"):
            window = bucket.get(key)
            if not isinstance(window, dict):
                continue
            used = number(window.get("usedPercent"))
            if used is None:
                continue
            minutes = number(window.get("windowDurationMins"))
            duration = {300: "5h", 10080: "weekly"}.get(minutes)
            if duration is None:
                duration = f"{minutes:g}m" if minutes and minutes > 0 else key
            windows.append(Window(f"{name} {duration}", used, number(window.get("resetsAt")), minutes))
    if not windows:
        raise UsageError("No Codex limits returned. Use a ChatGPT subscription login, not an API key.", category="unsupported_response")
    note = ""
    if payload.get("ordinaryUsageAllowed") is False:
        note = "Codex reports included usage is blocked; percentages do not override this status."
    return Snapshot("Codex", windows, note=note, blocked=payload.get("ordinaryUsageAllowed") is False)


def parse_claude(payload: dict) -> Snapshot:
    windows = []
    labels = {"five_hour": "Session (5h)", "seven_day": "Weekly", "seven_day_opus": "Opus weekly", "seven_day_sonnet": "Sonnet weekly"}
    for key, label in labels.items():
        window = payload.get(key)
        if not isinstance(window, dict):
            continue
        used = number(window.get("utilization"))
        if used is None:
            continue
        reset = None
        raw = window.get("resets_at")
        if isinstance(raw, str):
            try:
                parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
                if parsed.tzinfo is not None:
                    reset = parsed.timestamp()
            except (ValueError, OverflowError):
                pass
        windows.append(Window(label, used, reset, 300 if key == "five_hour" else 10080))
    if not windows:
        raise UsageError("Claude returned no supported usage windows.", category="unsupported_response")
    return Snapshot("Claude", windows)


class RpcClient:
    """A short-lived stdio app-server client with bounded waits and cleanup."""

    def __init__(self, command: list[str], timeout: float = 40, cancel_event=None):
        self.cancel_event = cancel_event
        self.tree = ChildTree()
        self.command = command
        self.timeout = timeout
        self.process = None
        self.reader = None
        self.messages = queue.Queue()
        self.sequence = 0

    def __enter__(self):
        check_cancelled(self.cancel_event)
        try:
            self.process = self.tree.start(
                self.command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, text=True, encoding="utf-8",
            )
        except OSError:
            raise UsageError("Cannot start Codex. Install the Codex CLI and run codex login.", category="unexpected_local") from None
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()
        try:
            self.call("initialize", {"clientInfo": {"name": "usage_tray", "title": "Usage Tray", "version": APP_VERSION}})
            self._send({"method": "initialized", "params": {}})
        except BaseException:
            self.__exit__(None, None, None)
            raise
        return self

    def _read(self):
        try:
            for line in self.process.stdout:
                try:
                    message = json.loads(line)
                except (ValueError, TypeError):
                    continue
                if isinstance(message, dict):
                    self.messages.put(message)
        except (OSError, ValueError):
            pass
        finally:
            self.messages.put(None)

    def _send(self, message: dict):
        check_cancelled(self.cancel_event)
        try:
            self.process.stdin.write(json.dumps(message) + "\n")
            self.process.stdin.flush()
        except (OSError, ValueError):
            raise UsageError("Codex app-server disconnected. Check codex login and your CLI version.", category="network_error") from None

    def call(self, method: str, params: dict) -> dict:
        self.sequence += 1
        request_id = self.sequence
        self._send({"id": request_id, "method": method, "params": params})
        deadline = time.monotonic() + self.timeout
        while True:
            check_cancelled(self.cancel_event)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise UsageError("Codex did not respond in time. Check your connection and sign-in.", category="network_error")
            try:
                message = self.messages.get(timeout=min(0.1, remaining))
            except queue.Empty:
                continue
            if message is None:
                raise UsageError("Codex app-server stopped. Update the CLI and check codex login.", category="network_error")
            # Server and client request IDs are separate namespaces.
            if "id" in message and "method" in message:
                self._send({"id": message["id"], "error": {"code": -32601, "message": "Unsupported method"}})
                continue
            if message.get("id") != request_id:
                continue
            if "error" in message:
                # Server error text can contain remote response bodies: do not log or display it.
                raise UsageError(f"Codex could not complete {method}. Check codex login, connectivity, and CLI updates.", category="provider_error")
            result = message.get("result")
            if not isinstance(result, dict):
                raise UsageError("Codex returned an unsupported response. Update the CLI.", category="unsupported_response")
            return result

    def __exit__(self, *_):
        if self.process is None:
            return
        try:
            self.tree.close()
        finally:
            if self.reader:
                self.reader.join(timeout=1)
            for stream in (self.process.stdin, self.process.stdout):
                if stream:
                    stream.close()


def codex_command() -> list[str]:
    executable = shutil.which("codex")
    if not executable:
        raise UsageError("Codex CLI not found. Install it, then run codex login.", category="unexpected_local")
    # npm installs codex.cmd on Windows. Invoke its JS entry through node without
    # a command shell, so spaces and shell characters in user paths stay literal.
    if Path(executable).suffix.lower() in (".cmd", ".bat", ".ps1"):
        entry = Path(executable).parent / "node_modules" / "@openai" / "codex" / "bin" / "codex.js"
        node = shutil.which("node")
        if not entry.is_file() or not node:
            raise UsageError("Cannot resolve the npm Codex launcher. Reinstall @openai/codex with Node.js.", category="unexpected_local")
        return [node, str(entry), "app-server"]
    return [executable, "app-server"]


def fetch_codex(cancel_event=None) -> Snapshot:
    check_cancelled(cancel_event)
    with RpcClient(codex_command(), cancel_event=cancel_event) as client:
        account = client.call("account/read", {"refreshToken": False}).get("account")
        if not isinstance(account, dict) or account.get("type") != "chatgpt":
            raise UsageError("Sign in to Codex with ChatGPT using codex login. API-key usage limits are unavailable.", category="login_required")
        return parse_codex(client.call("account/rateLimits/read", {}))


def claude_credentials_path() -> Path:
    base = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")
    return base / ".credentials.json"


class NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Never forward a bearer credential to a redirect destination.
        return None


def fetch_claude(cancel_event=None) -> Snapshot:
    check_cancelled(cancel_event)
    try:
        data = json.loads(claude_credentials_path().read_text(encoding="utf-8-sig"))
        oauth = data.get("claudeAiOauth", {})
        token = oauth.get("accessToken")
        expires = number(oauth.get("expiresAt"))
    except (OSError, ValueError, AttributeError):
        raise UsageError("Claude Code login not found. Run claude, then /login on this Windows account.", category="login_required") from None
    if not isinstance(token, str) or not token or any(c in token for c in "\r\n"):
        raise UsageError("Claude Code has no usable subscription login. Run claude, then /login.", category="login_required")
    if expires is not None and expires / 1000 <= time.time():
        raise UsageError("Claude login expired. Open Claude Code to renew it, then refresh here.", category="login_required")
    req = request.Request("https://api.anthropic.com/api/oauth/usage", headers={
        "Authorization": f"Bearer {token}", "anthropic-beta": "oauth-2025-04-20", "Accept": "application/json",
        "User-Agent": f"UsageTray/{APP_VERSION}",
    })
    check_cancelled(cancel_event)
    try:
        with request.build_opener(NoRedirect()).open(req, timeout=25) as response:
            payload = json.load(response)
    except error.HTTPError as exc:
        code = exc.code
        retry_after = exc.headers.get("Retry-After", "300")
        exc.close()
        if code in (401, 403):
            raise UsageError("Claude sign-in was rejected. Open Claude Code and run /login.", category="login_required") from None
        if code == 429:
            try:
                delay = float(retry_after)
                if not math.isfinite(delay):
                    delay = 300
            except ValueError:
                from email.utils import parsedate_to_datetime
                try:
                    delay = parsedate_to_datetime(retry_after).timestamp() - time.time()
                except (ValueError, TypeError, OverflowError):
                    delay = 300
            raise RateLimited(delay) from None
        raise UsageError(f"Claude usage request failed (HTTP {code}).", category="network_error") from None
    except (error.URLError, TimeoutError, OSError):
        raise UsageError("Cannot reach Claude. Check your network connection.", category="network_error") from None
    except ValueError:
        raise UsageError("Claude returned an unsupported response.", category="unsupported_response") from None
    if not isinstance(payload, dict):
        raise UsageError("Claude returned an unsupported response.", category="unsupported_response")
    check_cancelled(cancel_event)
    return parse_claude(payload)


def demo_snapshot(provider: str) -> Snapshot:
    windows = [Window("Session (5h)", 23 if provider == "Codex" else 42, time.time() + 7200), Window("Weekly", 55, time.time() + 172800)]
    return Snapshot(provider, windows, note="DEMO — sample data, no account was accessed.")
