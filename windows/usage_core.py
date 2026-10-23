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


class UsageError(Exception):
    """A safe, actionable message that may be shown in the tray."""


class RateLimited(UsageError):
    def __init__(self, retry_after: float = 300):
        super().__init__("Rate limited; waiting before retrying.")
        self.retry_after = max(300, retry_after)


@dataclass(frozen=True)
class Window:
    label: str
    used: float
    resets_at: float | None = None

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
            windows.append(Window(f"{name} {duration}", used, number(window.get("resetsAt"))))
    if not windows:
        raise UsageError("No Codex limits returned. Use a ChatGPT subscription login, not an API key.")
    note = ""
    if payload.get("ordinaryUsageAllowed") is False:
        note = "Codex reports included usage is blocked; percentages do not override this status."
    return Snapshot("Codex", windows, note=note)


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
        windows.append(Window(label, used, reset))
    if not windows:
        raise UsageError("Claude returned no supported usage windows.")
    return Snapshot("Claude", windows)


class RpcClient:
    """A short-lived stdio app-server client with bounded waits and cleanup."""

    def __init__(self, command: list[str], timeout: float = 40):
        self.command = command
        self.timeout = timeout
        self.process = None
        self.reader = None
        self.messages = queue.Queue()
        self.sequence = 0

    def __enter__(self):
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        try:
            self.process = subprocess.Popen(
                self.command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, text=True, encoding="utf-8",
                creationflags=flags,
            )
        except OSError:
            raise UsageError("Cannot start Codex. Install the Codex CLI and run codex login.") from None
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()
        try:
            self.call("initialize", {"clientInfo": {"name": "usage_tray", "title": "Usage Tray", "version": "0.1.0"}})
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
        finally:
            self.messages.put(None)

    def _send(self, message: dict):
        try:
            self.process.stdin.write(json.dumps(message) + "\n")
            self.process.stdin.flush()
        except (OSError, ValueError):
            raise UsageError("Codex app-server disconnected. Check codex login and your CLI version.") from None

    def call(self, method: str, params: dict) -> dict:
        self.sequence += 1
        request_id = self.sequence
        self._send({"id": request_id, "method": method, "params": params})
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                message = self.messages.get(timeout=max(0, deadline - time.monotonic()))
            except queue.Empty:
                raise UsageError("Codex did not respond in time. Check your connection and sign-in.") from None
            if message is None:
                raise UsageError("Codex app-server stopped. Update the CLI and check codex login.")
            # Server and client request IDs are separate namespaces.
            if "id" in message and "method" in message:
                self._send({"id": message["id"], "error": {"code": -32601, "message": "Unsupported method"}})
                continue
            if message.get("id") != request_id:
                continue
            if "error" in message:
                # Server error text can contain remote response bodies: do not log or display it.
                raise UsageError(f"Codex could not complete {method}. Check codex login, connectivity, and CLI updates.")
            result = message.get("result")
            if not isinstance(result, dict):
                raise UsageError("Codex returned an unsupported response. Update the CLI.")
            return result

    def __exit__(self, *_):
        if self.process is None:
            return
        try:
            if self.process.stdin:
                self.process.stdin.close()
            if self.process.poll() is None:
                self.process.terminate()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=3)
        finally:
            if self.reader:
                self.reader.join(timeout=1)
            if self.process.stdout:
                self.process.stdout.close()


def codex_command() -> list[str]:
    executable = shutil.which("codex")
    if not executable:
        raise UsageError("Codex CLI not found. Install it, then run codex login.")
    # npm installs codex.cmd on Windows. Invoke its JS entry through node without
    # a command shell, so spaces and shell characters in user paths stay literal.
    if Path(executable).suffix.lower() in (".cmd", ".bat", ".ps1"):
        entry = Path(executable).parent / "node_modules" / "@openai" / "codex" / "bin" / "codex.js"
        node = shutil.which("node")
        if not entry.is_file() or not node:
            raise UsageError("Cannot resolve the npm Codex launcher. Reinstall @openai/codex with Node.js.")
        return [node, str(entry), "app-server"]
    return [executable, "app-server"]


def fetch_codex() -> Snapshot:
    with RpcClient(codex_command()) as client:
        account = client.call("account/read", {"refreshToken": False}).get("account")
        if not isinstance(account, dict) or account.get("type") != "chatgpt":
            raise UsageError("Sign in to Codex with ChatGPT using codex login. API-key usage limits are unavailable.")
        return parse_codex(client.call("account/rateLimits/read", {}))


def claude_credentials_path() -> Path:
    base = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")
    return base / ".credentials.json"


class NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Never forward a bearer credential to a redirect destination.
        return None


def fetch_claude() -> Snapshot:
    try:
        data = json.loads(claude_credentials_path().read_text(encoding="utf-8-sig"))
        oauth = data.get("claudeAiOauth", {})
        token = oauth.get("accessToken")
        expires = number(oauth.get("expiresAt"))
    except (OSError, ValueError, AttributeError):
        raise UsageError("Claude Code login not found. Run claude, then /login on this Windows account.") from None
    if not isinstance(token, str) or not token or any(c in token for c in "\r\n"):
        raise UsageError("Claude Code has no usable subscription login. Run claude, then /login.")
    if expires is not None and expires / 1000 <= time.time():
        raise UsageError("Claude login expired. Open Claude Code to renew it, then refresh here.")
    req = request.Request("https://api.anthropic.com/api/oauth/usage", headers={
        "Authorization": f"Bearer {token}", "anthropic-beta": "oauth-2025-04-20", "Accept": "application/json",
        "User-Agent": "UsageTray/0.1.0",
    })
    try:
        with request.build_opener(NoRedirect()).open(req, timeout=25) as response:
            payload = json.load(response)
    except error.HTTPError as exc:
        code = exc.code
        retry_after = exc.headers.get("Retry-After", "300")
        exc.close()
        if code in (401, 403):
            raise UsageError("Claude sign-in was rejected. Open Claude Code and run /login.") from None
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
        raise UsageError(f"Claude usage request failed (HTTP {code}).") from None
    except (error.URLError, TimeoutError, OSError):
        raise UsageError("Cannot reach Claude. Check your network connection.") from None
    except ValueError:
        raise UsageError("Claude returned an unsupported response.") from None
    if not isinstance(payload, dict):
        raise UsageError("Claude returned an unsupported response.")
    return parse_claude(payload)


def demo_snapshot(provider: str) -> Snapshot:
    windows = [Window("Session (5h)", 23 if provider == "Codex" else 42, time.time() + 7200), Window("Weekly", 55, time.time() + 172800)]
    return Snapshot(provider, windows, note="DEMO — sample data, no account was accessed.")
