import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch
from urllib import error

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import usage_core as core
from usage_tray import ProviderState, main


class ParsingTests(unittest.TestCase):
    def test_codex_multiple_buckets_and_actual_durations(self):
        snapshot = core.parse_codex({"rateLimitsByLimitId": {
            "codex": {"primary": {"usedPercent": 22, "windowDurationMins": 300, "resetsAt": 2000000000},
                      "secondary": {"usedPercent": 105, "windowDurationMins": 10080}},
            "review": {"limitName": "Reviews", "primary": {"usedPercent": 8, "windowDurationMins": 60}},
        }, "ordinaryUsageAllowed": False})
        self.assertEqual([w.remaining for w in snapshot.windows], [78, 0, 92])
        self.assertEqual([w.label for w in snapshot.windows], ["codex 5h", "codex weekly", "Reviews 60m"])
        self.assertIn("blocked", snapshot.note)
        self.assertEqual(snapshot.windows[0].resets_at, 2000000000)

    def test_codex_legacy_fallback(self):
        snapshot = core.parse_codex({"rateLimitsByLimitId": None, "rateLimits": {"primary": {"usedPercent": 10}}})
        self.assertEqual(snapshot.windows[0].remaining, 90)
        self.assertIn("primary", snapshot.windows[0].label)

    def test_missing_limits_are_not_full_capacity(self):
        for parser in (core.parse_codex, core.parse_claude):
            with self.subTest(parser=parser.__name__), self.assertRaises(core.UsageError):
                parser({})

    def test_claude_timestamps_and_optional_windows(self):
        snapshot = core.parse_claude({"five_hour": {"utilization": 30.5, "resets_at": "2026-10-24T12:00:00.123Z"},
                                     "seven_day": None, "seven_day_opus": {"utilization": 40, "resets_at": "bad"}})
        self.assertEqual(len(snapshot.windows), 2)
        self.assertEqual(snapshot.windows[0].remaining, 69.5)
        self.assertIsNotNone(snapshot.windows[0].resets_at)
        self.assertIsNone(snapshot.windows[1].resets_at)

    def test_invalid_numbers_are_rejected(self):
        for value in [True, "23", float("nan"), float("inf"), None]:
            with self.subTest(value=value), self.assertRaises(core.UsageError):
                core.parse_claude({"five_hour": {"utilization": value}})


class ProtocolTests(unittest.TestCase):
    def command(self, mode="ok"):
        return [sys.executable, str(Path(__file__).with_name("fake_codex.py")), mode]

    def test_full_handshake_accounts_usage_and_cleanup(self):
        with core.RpcClient(self.command(), timeout=3) as client:
            account = client.call("account/read", {"refreshToken": False})
            self.assertEqual(account["account"]["type"], "chatgpt")
            snapshot = core.parse_codex(client.call("account/rateLimits/read", {}))
            self.assertEqual(snapshot.windows[0].remaining, 75)
        self.assertIsNotNone(client.process.poll())
        self.assertFalse(client.reader.is_alive())

    def test_timeout_cleans_up_failed_initialization(self):
        client = core.RpcClient(self.command("timeout"), timeout=0.1)
        with self.assertRaisesRegex(core.UsageError, "in time"):
            with client:
                pass
        self.assertIsNotNone(client.process.poll())

    def test_exited_server_is_actionable(self):
        with self.assertRaisesRegex(core.UsageError, "stopped"):
            with core.RpcClient(self.command("exit"), timeout=3):
                pass

    def test_server_error_body_is_not_exposed(self):
        with self.assertRaises(core.UsageError) as raised:
            with core.RpcClient(self.command("error"), timeout=3):
                pass
        self.assertNotIn("SECRET", str(raised.exception))

    def test_fetch_codex_uses_protocol(self):
        with patch.object(core, "codex_command", return_value=self.command()):
            self.assertEqual(core.fetch_codex().windows[0].remaining, 75)

    def test_npm_windows_launcher_avoids_shell(self):
        with patch.object(core.shutil, "which", side_effect=["C:/User Name/npm/codex.cmd", "C:/Program Files/node.exe"]), patch.object(Path, "is_file", return_value=True):
            command = core.codex_command()
        self.assertEqual(command[0], "C:/Program Files/node.exe")
        self.assertIn("User Name", command[1])
        self.assertEqual(command[-1], "app-server")


class ClaudeTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / ".credentials.json"
        self.path.write_text(json.dumps({"claudeAiOauth": {"accessToken": "fake-token", "expiresAt": (time.time() + 3600) * 1000}}))
        self.original = self.path.read_bytes()
        self.patch = patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": self.directory.name})
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def test_request_headers_response_and_credentials_unchanged(self):
        opener = Mock()
        opener.open.return_value = io.BytesIO(json.dumps({"five_hour": {"utilization": 18}}).encode())
        with patch.object(core.request, "build_opener", return_value=opener):
            snapshot = core.fetch_claude()
        req = opener.open.call_args.args[0]
        self.assertEqual(req.full_url, "https://api.anthropic.com/api/oauth/usage")
        self.assertEqual(req.get_header("Authorization"), "Bearer fake-token")
        self.assertEqual(req.get_header("Anthropic-beta"), "oauth-2025-04-20")
        self.assertEqual(snapshot.windows[0].remaining, 82)
        self.assertEqual(self.path.read_bytes(), self.original)

    def test_expired_credentials_do_not_make_request(self):
        self.path.write_text(json.dumps({"claudeAiOauth": {"accessToken": "fake", "expiresAt": 1}}))
        with patch.object(core.request, "build_opener") as opener, self.assertRaisesRegex(core.UsageError, "expired"):
            core.fetch_claude()
        opener.assert_not_called()

    def test_missing_and_malformed_credentials(self):
        for contents in ["invalid", "null", "[]", '{"claudeAiOauth": null}']:
            self.path.write_text(contents)
            with self.subTest(contents=contents), self.assertRaises(core.UsageError):
                core.fetch_claude()
        self.path.unlink()
        with self.assertRaises(core.UsageError):
            core.fetch_claude()

    def test_rate_limit_retry_after_and_no_body_leak(self):
        opener = Mock()
        opener.open.side_effect = error.HTTPError("https://api.anthropic.com", 429, "SECRET", {"Retry-After": "1200"}, io.BytesIO(b"SECRET"))
        with patch.object(core.request, "build_opener", return_value=opener), self.assertRaises(core.RateLimited) as raised:
            core.fetch_claude()
        self.assertEqual(raised.exception.retry_after, 1200)
        self.assertNotIn("SECRET", str(raised.exception))

    def test_auth_failure_explains_login(self):
        opener = Mock()
        opener.open.side_effect = error.HTTPError("https://api.anthropic.com", 401, "SECRET", {}, io.BytesIO(b"SECRET"))
        with patch.object(core.request, "build_opener", return_value=opener), self.assertRaisesRegex(core.UsageError, "/login"):
            core.fetch_claude()

    def test_redirects_cannot_forward_bearer_token(self):
        self.assertIsNone(core.NoRedirect().redirect_request(None, None, 302, "", {}, "https://other.invalid"))


class PollingTests(unittest.TestCase):
    def test_preserves_last_good_data_after_failure_and_backs_off(self):
        fetch = Mock(side_effect=[core.demo_snapshot("Codex"), core.RateLimited(900)])
        state = ProviderState("Codex", fetch)
        state.refresh()
        first = state.snapshot
        state.refresh()  # Manual refresh cannot bypass the minimum interval.
        self.assertEqual(fetch.call_count, 1)
        state.next_check = 0
        before = time.monotonic()
        state.refresh()
        self.assertIs(state.snapshot, first)
        self.assertGreaterEqual(state.next_check, before + 900)
        self.assertIn("out of date", " ".join(state.lines()))

    def test_menu_does_not_wait_for_network_fetch(self):
        entered = threading.Event()
        release = threading.Event()
        def slow_fetch():
            entered.set()
            release.wait(2)
            return core.demo_snapshot("Claude")
        state = ProviderState("Claude", slow_fetch)
        worker = threading.Thread(target=state.refresh)
        worker.start()
        self.assertTrue(entered.wait(1))
        try:
            before = time.monotonic()
            self.assertIn("Claude", state.lines())
            self.assertLess(time.monotonic() - before, 0.2)
            state.refresh()  # Duplicate fetch must return immediately.
        finally:
            release.set()
            worker.join(2)

    def test_unexpected_error_is_sanitized(self):
        state = ProviderState("Claude", Mock(side_effect=RuntimeError("SECRET")))
        state.refresh()
        self.assertNotIn("SECRET", " ".join(state.lines()))


class CommandLineTests(unittest.TestCase):
    def test_demo_both_providers_no_gui_or_credentials(self):
        script = Path(__file__).resolve().parents[1] / "usage_tray.py"
        result = subprocess.run([sys.executable, str(script), "--once", "--demo"], capture_output=True, text=True, check=True)
        output = json.loads(result.stdout)
        self.assertEqual([row["provider"] for row in output], ["Codex", "Claude"])
        self.assertTrue(all("DEMO" in row["note"] for row in output))

    def test_failure_exit_status_and_provider_isolation(self):
        with patch("usage_tray.PROVIDERS", {"Codex": Mock(side_effect=core.UsageError("Sign in")), "Claude": lambda: core.demo_snapshot("Claude")}), patch.object(sys, "argv", ["usage_tray", "--once"]), patch("sys.stdout", new_callable=io.StringIO) as output:
            self.assertEqual(main(), 1)
            rows = json.loads(output.getvalue())
        self.assertIn("error", rows[0])
        self.assertEqual(rows[1]["provider"], "Claude")
        self.assertIn("windows", rows[1])


if __name__ == "__main__":
    unittest.main()
