"""Synthetic privacy/hostile-metadata checks. Never reads real histories or login."""
from contextlib import redirect_stdout, redirect_stderr
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from html.parser import HTMLParser
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
from urllib import error

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import usage_core as core
import usage_diagnostics as diagnostics
import usage_reports as reports
import usage_service as service
import usage_tray as tray
from usage_privacy import display_text, metadata_label
from usage_runtime import ProviderState

NOW = datetime(2026, 10, 23, 20, tzinfo=timezone.utc).timestamp()
SECRET = "TRANSCRIPT-CREDENTIAL-SENTINEL-29481"
FULL_PATH = "C:/private-user/private-parent/private-project"
SESSION = "conversation-private-29481-abcdef"
TURN = "turn-private-29481-abcdef"
SCRIPT = Path(tray.__file__).resolve()


class Elements(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags, self.attributes = [], []
    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)
        self.attributes.extend(attrs)


class PrivacyTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.base = Path(self.directory.name)
        self.env = dict(os.environ, LOCALAPPDATA=str(self.base / "appdata"),
                        CODEX_HOME=str(self.base / "codex"), CLAUDE_CONFIG_DIR=str(self.base / "claude"))
        self.codex, self.claude = self.base / "codex-logs", self.base / "claude-logs"
        self.codex.mkdir(); self.claude.mkdir()
        self.roots = {"Codex": [self.codex], "Claude": [self.claude]}

    def write(self, root, entries):
        path = root / "fixture.jsonl"
        path.write_text("\n".join(json.dumps(e) for e in entries) + "\n", encoding="utf-8")
        return path

    def fixture(self):
        timestamp = datetime.fromtimestamp(NOW - 5, timezone.utc).isoformat()
        self.write(self.codex, [
            {"type": "session_meta", "timestamp": timestamp, "payload": {"id": SESSION, "cwd": FULL_PATH, "content": SECRET}},
            {"type": "turn_context", "payload": {"model": "gpt-5.4", "turn_id": TURN, "effort": "high", "prompt": SECRET}},
            {"type": "response_item", "payload": {"content": SECRET, "credentials": SECRET}},
            {"type": "event_msg", "timestamp": timestamp, "payload": {"type": "token_count", "content": SECRET,
                "credentials": {"accessToken": SECRET}, "info": {"total_token_usage": {
                    "input_tokens": 100, "output_tokens": 20, "cached_input_tokens": 10, "reasoning_output_tokens": 5,
                    "arbitrary": SECRET}}}}])
        self.write(self.claude, [
            {"type": "user", "uuid": TURN, "cwd": FULL_PATH, "message": {"content": [{"type": "text", "text": SECRET}]}},
            {"type": "assistant", "timestamp": timestamp, "sessionId": SESSION, "requestId": "request-fixture",
                "credentials": {"accessToken": SECRET}, "request": {"headers": {"Authorization": SECRET}, "messages": [SECRET]},
                "message": {"id": "message-fixture", "model": "claude-sonnet-4-6",
                    "content": [{"type": "text", "text": SECRET}, {"type": "thinking", "thinking": SECRET}],
                    "usage": {"input_tokens": 30, "output_tokens": 4, "cache_read_input_tokens": 2, "cache_creation_input_tokens": 0}}}])
        return service.query_usage("month", roots=self.roots, now=NOW)

    def cli(self, *arguments):
        return subprocess.run([sys.executable, str(SCRIPT), *map(str, arguments)], env=self.env,
                              capture_output=True, text=True, encoding="utf-8", timeout=20)

    def invoke(self, *arguments):
        out, err = io.StringIO(), io.StringIO()
        with patch.dict(os.environ, self.env), patch.object(sys, "argv", ["usage_tray", *map(str, arguments)]), redirect_stdout(out), redirect_stderr(err):
            try: code = tray.main()
            except SystemExit as exc: code = exc.code
        return code, out.getvalue(), err.getvalue()

    def test_extraction_reconciliation_summary_and_saved_exports_exclude_content(self):
        result = self.fixture()
        self.assertEqual(result.total.tokens.total, 156)
        self.assertNotIn(SECRET, repr(result))
        self.assertNotIn(SECRET, repr(asdict(result)))
        for format in ("html", "text"):
            with patch.dict(os.environ, self.env):
                for full in (False, True):
                    path = reports.save_report(result, self.base / f"{format}-{full}.{format}", format=format, include_metadata=full)
                    self.assertNotIn(SECRET, path.read_text(encoding="utf-8"))
        diagnostic = diagnostics.Operation("report").finish("success", "complete", "success", counts=diagnostics.report_counts(result))
        self.assertNotIn(SECRET, json.dumps(diagnostic))
        self.assertNotIn(FULL_PATH, json.dumps(diagnostic))
        self.assertNotIn(SESSION, json.dumps(diagnostic))
        self.assertEqual(diagnostic["counts"]["records"], 2)
        self.assertEqual(diagnostic["counts"]["files_read"], 2)

    def test_default_report_hides_full_paths_ids_but_explicit_metadata_export_preserves_them(self):
        result = self.fixture()
        before = repr(result)
        for renderer in (reports.render_text_report, reports.render_report):
            default, full = renderer(result), renderer(result, include_metadata=True)
            self.assertNotIn(FULL_PATH, default)
            self.assertNotIn(SESSION, default)
            self.assertNotIn(TURN, default)
            self.assertIn("private-project", default)
            self.assertIn(FULL_PATH, full)
            self.assertIn(SESSION, full)
        self.assertIn(TURN, reports.render_report(result, include_metadata=True))
        self.assertEqual(repr(result), before)
        self.assertNotEqual(metadata_label("C:/one/same", "project"), metadata_label("D:/two/same", "project"))

    def test_controls_bidi_osc_csi_surrogates_and_multiline_are_inert(self):
        hostile = "x\x1b]52;c;clipboard\x07\x1b[2J\x9b31m\r\n\t\b\u202e\u2066\u200b\u2028\u2029\ud800"
        safe = display_text(hostile)
        self.assertTrue(safe.isprintable())
        self.assertIn(r"\u001b", safe)
        self.assertIn(r"\u202e", safe)
        result = self.fixture()
        records = [replace(d.record, model=hostile, project=hostile, session=hostile, turn_id=hostile) for d in result.details]
        result = service.build_usage_result(records, result.context, notices=(hostile,))
        for renderer in (reports.render_text_report, reports.render_report):
            rendered = renderer(result, include_metadata=True)
            self.assertNotIn("\x1b", rendered)
            self.assertNotIn("\x9b", rendered)
            self.assertNotIn("\u202e", rendered)
            self.assertNotIn("\ud800", rendered)
            self.assertIn(r"\u001b", rendered)
        state = ProviderState("Codex", lambda: core.Snapshot("Codex", [core.Window(hostile, 5)], note=hostile))
        state.refresh()
        self.assertNotIn("\x1b", " ".join(state.lines()))
        self.assertEqual(state.snapshot.note, hostile)

    def test_html_injection_remains_text_with_no_active_elements(self):
        result = self.fixture()
        hostile = '<script>alert("x")</script><img src="https://invalid" onerror="x"><a href="javascript:x">'
        records = [replace(d.record, model=hostile, effort=hostile, project=hostile, session=hostile, turn_id=hostile) for d in result.details]
        result = service.build_usage_result(records, result.context, notices=(hostile,))
        rendered = reports.render_report(result, include_metadata=True)
        parsed = Elements(); parsed.feed(rendered)
        self.assertNotIn("script", parsed.tags)
        self.assertNotIn("img", parsed.tags)
        self.assertFalse(any(k.startswith("on") for k, v in parsed.attributes))
        self.assertFalse(any(v and v.startswith("javascript:") for k, v in parsed.attributes))
        self.assertIn("&lt;script&gt;", rendered)
        self.assertIn("default-src 'none'", rendered)

    def test_provider_snapshot_serialization_is_explicit_and_type_confusion_does_not_leak(self):
        @dataclass(frozen=True)
        class ExtraSnapshot(core.Snapshot):
            credential: str = SECRET
        snapshot = ExtraSnapshot("Codex", [core.Window("label\x1b[2J", 50)])
        self.assertNotIn(SECRET, json.dumps(snapshot.to_dict()))
        self.assertEqual(set(snapshot.to_dict()), {"provider", "checked_at", "note", "blocked", "windows"})
        payload = {"rateLimitsByLimitId": {"codex": {"limitName": {"prompt": SECRET}, "primary": {"usedPercent": 1}}}}
        self.assertNotIn(SECRET, repr(core.parse_codex(payload)))
        self.assertIn("codex", core.parse_codex(payload).windows[0].label)

    def test_diagnostic_export_rejects_unknown_fields_and_nested_payloads_without_overwriting(self):
        path = self.base / "diagnostic.json"
        data = diagnostics.Operation("report").finish("success", "complete", "success", counts={"records": 2})
        diagnostics.write_diagnostic(path, data)
        original = path.read_bytes()
        for mutation in ({"prompt": SECRET}, {"counts": {"prompt": SECRET}}, {"category": SECRET},
                         {"providers": [{"provider": "Codex", "category": "success", "payload": SECRET}]},
                         {"started_at": SECRET}, {"operation_id": SECRET}, {"build_id": SECRET}, {"next_action": SECRET}, {"counts": None}, {"diagnostic_schema_version": True}):
            with self.subTest(fields=list(mutation)), self.assertRaises((ValueError, TypeError)):
                diagnostics.write_diagnostic(path, dict(data, **mutation))
            self.assertEqual(path.read_bytes(), original)
        self.assertEqual(list(self.base.glob(".usage-diagnostic-*")), [])

    def test_diagnostic_write_failure_preserves_existing_export(self):
        path = self.base / "diagnostic.json"; path.write_text("keep")
        data = diagnostics.Operation("report").finish("failed", "save", "disk_full")
        with patch.object(diagnostics.os, "replace", side_effect=PermissionError(SECRET)), self.assertRaises(PermissionError):
            diagnostics.write_diagnostic(path, data)
        self.assertEqual(path.read_text(), "keep")
        self.assertEqual(list(self.base.glob(".usage-diagnostic-*")), [])

    def test_success_demo_operation_export_is_opt_in_and_unique(self):
        path = self.base / "operation.json"
        result = self.cli("--report", "month", "--demo", "--diagnostic-output", path)
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(path.read_text())
        self.assertEqual((data["status"], data["scope"], data["counts"]["records"]), ("success", "demo", 6))
        self.assertNotIn("demo-conversation", path.read_text())
        self.assertEqual(diagnostics.Operation("report").finish("success", "complete", "success")["counts"], {})
        self.assertNotEqual(data["operation_id"], diagnostics.Operation("report").operation_id)
        self.assertFalse((self.base / "appdata" / "UsageTray" / "diagnostics.json").exists())

    def test_query_save_and_open_failures_export_safe_category_phase_and_available_counts(self):
        path = self.base / "failure.json"
        for phase, attribute, failure, category in (("query", "query_usage", RuntimeError(SECRET), "unexpected_local"),
                ("save", "save_report", PermissionError(SECRET), "permission_denied"),
                ("open", "open_report", OSError(SECRET), "open_failed")):
            with self.subTest(phase=phase), patch.object(tray, attribute, side_effect=failure):
                code, out, err = self.invoke("--report", "month", "--demo", "--output", self.base / "report.txt",
                                             "--open-report", "--diagnostic-output", path)
            self.assertEqual(code, 1)
            data = json.loads(path.read_text())
            self.assertEqual((data["phase"], data["category"], data["status"]), (phase, category, "failed"))
            self.assertNotIn(SECRET, out + err + path.read_text())
            self.assertEqual(data["counts"].get("records"), None if phase == "query" else 6)
        self.assertTrue((self.base / "report.txt").exists())

    def test_standalone_diagnostics_explain_invalid_settings_without_scanning_or_mutating(self):
        config = self.base / "broken.json"; config.write_text(SECRET)
        with patch.object(tray, "query_usage", side_effect=AssertionError), patch.object(tray, "RuntimeOwner", side_effect=AssertionError):
            code, out, err = self.invoke("--diagnostics", "--config", config)
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(out)["operation"]["category"], "settings_invalid")
        self.assertNotIn(SECRET, out + err)
        self.assertNotIn(str(config), out)
        self.assertEqual(config.read_text(), SECRET)

    def test_partial_and_failed_source_exports_keep_counts_without_source_identifiers(self):
        self.fixture()
        with (self.codex / "fixture.jsonl").open("a") as stream: stream.write(SECRET + "\n")
        output = self.base / "partial.json"
        result = self.cli("--report", "month", "--codex-root", self.codex, "--claude-root", self.base / "missing", "--diagnostic-output", output)
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(output.read_text())
        self.assertEqual((data["status"], data["category"], data["scope"]), ("partial", "source_incomplete", "local"))
        self.assertGreaterEqual(data["counts"]["ingestion_issues"], 2)
        self.assertNotIn(str(self.codex), output.read_text())
        self.assertNotIn(SECRET, result.stdout + result.stderr + output.read_text())

    def test_once_provider_failure_export_contains_only_safe_recovery_categories(self):
        output = self.base / "provider.json"
        with patch.dict(tray.PROVIDERS, {"Codex": Mock(side_effect=RuntimeError(SECRET)), "Claude": lambda: core.demo_snapshot("Claude")}, clear=True):
            code, out, err = self.invoke("--once", "--diagnostic-output", output)
        data = json.loads(output.read_text())
        self.assertEqual(code, 1)
        self.assertEqual(data["providers"], [{"provider": "Codex", "category": "unexpected_local"}, {"provider": "Claude", "category": "success"}])
        self.assertNotIn(SECRET, out + err + output.read_text())

    def test_explicit_cli_metadata_and_diagnostic_path_collision_guards(self):
        self.fixture()
        output = self.base / "report.html"
        result = self.cli("--report", "month", "--report-format", "html", "--codex-root", self.codex, "--claude-root", self.claude, "--include-metadata", "--output", output)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(FULL_PATH, output.read_text(encoding="utf-8"))
        config = self.base / "settings.json"; config.write_text("keep")
        for args in (("--once", "--config", config, "--diagnostic-output", config),
                     ("--report", "month", "--output", output, "--diagnostic-output", output),
                     ("--once", "--diagnostic-output", self.base / "appdata/UsageTray/Reports/Generated/export.json"),
                     ("--diagnostics", "--config", config, "--output", config),
                     ("--include-metadata",), ("--diagnostic-output", self.base / "x")):
            self.assertEqual(self.cli(*args).returncode, 2)
        self.assertEqual(config.read_text(), "keep")

    def test_failed_diagnostic_destination_keeps_successful_report_and_safe_error(self):
        output = self.base / "report.txt"
        with patch.object(tray, "write_diagnostic", side_effect=OSError(SECRET)):
            code, out, err = self.invoke("--report", "month", "--demo", "--output", output, "--diagnostic-output", self.base / "operation.json")
        self.assertEqual(code, 1)
        self.assertTrue(output.exists())
        self.assertIn("Diagnostic export failed", err)
        self.assertNotIn(SECRET, out + err)

    def test_settings_and_runtime_ownership_failures_export_without_source_content(self):
        output = self.base / "operation.json"
        config = self.base / "broken.json"; config.write_text(SECRET)
        code, out, err = self.invoke("--report", "month", "--config", config, "--diagnostic-output", output)
        self.assertEqual(code, 2)
        data = json.loads(output.read_text())
        self.assertEqual((data["phase"], data["category"]), ("settings", "settings_invalid"))
        self.assertIn("--config", data["next_action"])
        with patch.object(tray.RuntimeOwner, "__enter__", side_effect=tray.AlreadyRunning("Already running.")):
            code, out, err = self.invoke("--once", "--diagnostic-output", output)
        self.assertEqual(code, 3)
        data = json.loads(output.read_text())
        self.assertEqual((data["phase"], data["category"]), ("ownership", "already_running"))
        self.assertNotIn(SECRET, out + err + output.read_text())

    def test_diagnostic_and_display_modules_have_no_gui_network_or_source_scan_imports(self):
        code = "import socket,sys;socket.socket=lambda *a,**k:(_ for _ in ()).throw(AssertionError());import usage_diagnostics,usage_privacy;assert not any(m in sys.modules for m in ('pystray','PIL','usage_core','usage_ingestion','usage_service'));print('headless')"
        result = subprocess.run([sys.executable, "-c", code], cwd=SCRIPT.parent, env=self.env, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("headless", result.stdout)

    def test_http_error_bodies_redirects_and_credentials_remain_private(self):
        credentials = self.base / ".credentials.json"
        credentials.write_text(json.dumps({"claudeAiOauth": {"accessToken": SECRET}}))
        original = credentials.read_bytes()
        for status, category in ((302, "network_error"), (401, "login_required"), (429, "cooldown"), (500, "network_error")):
            opener = Mock(); opener.open.side_effect = error.HTTPError("https://invalid/" + SECRET, status, SECRET, {}, io.BytesIO(SECRET.encode()))
            with patch.object(core, "claude_credentials_path", return_value=credentials), patch.object(core.request, "build_opener", return_value=opener), self.assertRaises(core.UsageError) as raised:
                core.fetch_claude()
            self.assertEqual(raised.exception.category, category)
            self.assertNotIn(SECRET, str(raised.exception))
            self.assertEqual(credentials.read_bytes(), original)
        self.assertIsNone(core.NoRedirect().redirect_request(None, None, 307, SECRET, {}, "https://invalid/" + SECRET))


if __name__ == "__main__":
    unittest.main()
