"""Preserved preview privacy boundaries, integrated with the completed S08 core."""
from dataclasses import asdict, replace
from html import escape
from html.parser import HTMLParser
import http.client
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from contextlib import redirect_stderr
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import usage_core as core
import usage_reports as reports
from usage_hub import HubService, create_server
from privacy_cases import (NOW, SECRET, log_entries, malformed_metadata_leaks,
                           live_label_has_controls, public_outputs, read_fixture, report_for)


class Elements(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags = []
        self.attributes = []

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)
        self.attributes.extend(attrs)


class PrivacyBoundaryTests(unittest.TestCase):
    def test_normal_source_content_never_enters_records_reports_or_preview_detail(self):
        for provider in ("Codex", "Claude"):
            with self.subTest(provider=provider):
                with patch.object(core, "fetch_codex", side_effect=AssertionError("network forbidden")), \
                     patch.object(core, "fetch_claude", side_effect=AssertionError("network forbidden")):
                    records, notices = read_fixture(provider, log_entries(provider))
                    self.assertEqual(len(records), 1)  # Not a vacuous no-record pass.
                    for output in public_outputs(records, notices):
                        self.assertNotIn(SECRET, output)
                    with tempfile.TemporaryDirectory(prefix="usage-export-") as directory:
                        for kind in ("text", "html"):
                            path = reports.save_report(report_for(records), Path(directory) / kind, kind)
                            self.assertNotIn(SECRET, path.read_text(encoding="utf-8"))

    def test_html_escapes_every_source_metadata_slot_and_notices(self):
        records, _ = read_fixture("Codex", log_entries("Codex"))
        hostile = '\"><img src=x onerror="fixture()"><script>fixture()</script>&\''
        record = replace(records[0], project=hostile, session=hostile, model=hostile,
                         effort=hostile, effort_source=hostile, turn_id=hostile)
        before = asdict(record)
        html = reports.render_report(report_for([record], [hostile]))
        parsed = Elements()
        parsed.feed(html)
        self.assertNotIn("img", parsed.tags)
        self.assertNotIn("script", parsed.tags)
        self.assertFalse(any(key.startswith("on") for key, _ in parsed.attributes))
        self.assertIn(escape(hostile, quote=True), html)
        self.assertEqual(asdict(record), before)  # Display escaping cannot change identity.

    def test_terminal_report_neutralizes_c0_c1_and_bidi_metadata(self):
        records, _ = read_fixture("Codex", log_entries("Codex"))
        hostile = "Fixture\x1b[2J\x9d52;c;fixture\x07\r\b\x00\u202e"
        record = replace(records[0], project=hostile, session=hostile, model=hostile, effort=hostile)
        before = asdict(record)
        output = reports.render_text_report(report_for([record], [hostile]))
        self.assertFalse(any(not c.isprintable() for c in output.replace("\n", "")))
        self.assertIn("Fixture", output)
        self.assertEqual(asdict(record), before)

    def test_failed_scan_retains_safe_actionable_diagnostic(self):
        service = HubService(roots={}, clock=lambda: NOW)
        with patch("usage_hub.read_codex", side_effect=PermissionError(SECRET)):
            self.assertEqual(service.refresh()["state"], "failed")
        self.assertNotIn(SECRET, service.scan_error)
        self.assertIn("log-folder access", service.scan_error)


class ResolvedPrivacyRegressions(unittest.TestCase):
    def test_legacy_codex_rejects_nested_invalid_metadata_without_exposure(self):
        self.assertEqual(malformed_metadata_leaks("Codex"), [])

    def test_legacy_claude_rejects_nested_invalid_metadata_without_exposure(self):
        self.assertEqual(malformed_metadata_leaks("Claude"), [])

    def test_live_codex_label_neutralizes_terminal_controls(self):
        self.assertFalse(live_label_has_controls())


class PreviewDiagnosticTests(unittest.TestCase):
    def test_query_exception_is_redacted_and_requests_are_not_logged(self):
        service = HubService(demo=True, clock=lambda: NOW)
        service.refresh()
        server = create_server(service, port=0)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
            self.addCleanup(connection.close)
            logged = io.StringIO()
            with redirect_stderr(logged):
                connection.request("GET", "/")
                response = connection.getresponse()
                cookie = response.getheader("Set-Cookie").split(";", 1)[0]
                response.read()
                for exception, status, code in ((RuntimeError(SECRET), 503, "scan_unavailable"),
                                                 (Exception(SECRET), 500, "local_query_failed")):
                    with patch.object(service, "query", side_effect=exception):
                        connection.request("GET", "/api/preview/query?q=" + SECRET,
                                           headers={"Cookie": cookie, "X-Usage-Hub": "1"})
                        response = connection.getresponse()
                        body = response.read().decode()
                        self.assertEqual(response.status, status)
                        self.assertEqual(json.loads(body), {"error": code})
                        self.assertNotIn(SECRET, body)
                        self.assertNotIn(cookie, body)
                        self.assertEqual(response.getheader("Cache-Control"), "no-store")
            self.assertEqual(logged.getvalue(), "")
        finally:
            server.shutdown()
            server.server_close()
            worker.join(3)


if __name__ == "__main__":
    unittest.main()
