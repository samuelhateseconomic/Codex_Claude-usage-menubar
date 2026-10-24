import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from dataclasses import asdict
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import usage_ingestion as ingestion
import usage_reports as reports
from usage_reconciliation import reconcile_observations

NOW = 1792785600


def event(value=100, when=NOW - 1):
    from datetime import datetime, timezone
    return {"type": "event_msg", "timestamp": datetime.fromtimestamp(when, timezone.utc).isoformat(),
            "payload": {"type": "token_count", "info": {"total_token_usage": {
                "input_tokens": value, "output_tokens": 0, "cached_input_tokens": 0}}}}


def history(*events):
    return [{"type": "session_meta", "payload": {"id": "synthetic", "cwd": "synthetic-project"}},
            {"type": "turn_context", "payload": {"model": "gpt-5.4"}}, *events]


class IngestionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / "fixture.jsonl"

    def write(self, entries):
        self.path.write_text("".join(json.dumps(entry) + "\n" for entry in entries), encoding="utf-8")

    def scan(self):
        return ingestion.scan_observations("Codex", [self.root])

    def total(self, scan):
        return sum(e.record.tokens.total for e in reconcile_observations(scan.observations).events)

    def test_complete_empty_partial_failed_are_distinct(self):
        self.assertEqual(self.scan().state, "empty")
        self.write(history(event()))
        self.assertEqual(self.scan().state, "complete")
        self.assertEqual(self.total(self.scan()), 100)
        with self.path.open("ab") as stream:
            stream.write(b'{"unfinished":')
        partial = self.scan()
        self.assertEqual(partial.state, "partial")
        self.assertEqual(partial.issue_counts, {"incomplete_final_line": 1})
        self.assertEqual(self.total(partial), 100)
        failed = ingestion.scan_observations("Codex", [self.root / "missing"])
        self.assertEqual(failed.state, "failed")
        self.assertEqual(failed.issue_counts, {"missing_root": 1})
        self.assertEqual(failed.observations, ())

    def test_complete_malformed_and_incomplete_final_have_separate_counts(self):
        self.write(history(event()))
        with self.path.open("ab") as stream:
            stream.write(b'bad PRIVATE_SENTINEL\n[]\n{"unfinished":')
        scan = self.scan()
        self.assertEqual(scan.issue_counts, {"incomplete_final_line": 1, "malformed_record": 2})
        self.assertEqual([i.line for i in scan.issues], [4, 5, 6])
        self.assertTrue(all(i.excluded_tokens is None for i in scan.issues))
        self.assertNotIn("PRIVATE_SENTINEL", repr(asdict(scan)))

    def test_partial_append_is_accepted_once_after_line_completion(self):
        self.write(history(event()))
        serialized = json.dumps(event(200, NOW))
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(serialized[:30])
        before = self.scan()
        self.assertEqual(self.total(before), 100)
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(serialized[30:] + "\n")
        after = self.scan()
        self.assertEqual(after.state, "complete")
        self.assertEqual(self.total(after), 200)
        self.assertEqual(self.total(self.scan()), 200)
        self.assertEqual(reconcile_observations(before.observations).events[0].event_id,
                         reconcile_observations(after.observations).events[0].event_id)
        self.assertNotEqual(before.observations[0].source.generation, after.observations[0].source.generation)

    def test_complete_json_at_eof_without_lf_is_accepted(self):
        self.write(history())
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(event()))
        self.assertEqual(self.scan().issue_counts, {})
        self.assertEqual(self.total(self.scan()), 100)
        with self.path.open("ab") as stream:
            stream.write(b"\n")
        self.assertEqual(self.total(self.scan()), 100)

    def test_invalid_utf8_is_not_silently_replaced_in_model_or_id(self):
        self.path.write_bytes(b'{"type":"session_meta","payload":{"id":"\xff"}}\n')
        scan = self.scan()
        self.assertEqual(scan.issue_counts, {"malformed_record": 1})
        self.assertEqual(scan.observations, ())
        self.assertEqual(scan.state, "partial")

    def test_old_mtime_does_not_hide_relevant_events_or_baselines(self):
        self.write(history(event(100, NOW - 20000), event(200, NOW - 1)))
        os.utime(self.path, (1, 1))
        report = reports.collect_report("session", providers=["Codex"], roots={"Codex": [self.root]}, now=NOW)
        self.assertEqual(sum(r.tokens.total for r in report.records), 100)
        self.assertEqual(len(reports.read_codex([self.root], [], since=NOW - 18000)), 2)
        self.assertEqual(report.source_states, {"Codex": "complete"})
        self.assertEqual(list(reports.log_files([self.root], [], since=NOW)), [self.path])

    def test_missing_root_alongside_valid_root_is_partial(self):
        self.write(history(event()))
        scan = ingestion.scan_observations("Codex", [self.root, self.root / "missing"])
        self.assertEqual(scan.state, "partial")
        self.assertEqual(self.total(scan), 100)
        self.assertEqual(scan.issue_counts, {"missing_root": 1})
        self.assertEqual(ingestion.scan_observations("Codex", []).state, "failed")

    def test_root_access_failure_is_failed_not_empty(self):
        with patch.object(ingestion.os, "scandir", side_effect=PermissionError("PRIVATE_SENTINEL")):
            scan = self.scan()
        self.assertEqual(scan.state, "failed")
        self.assertEqual(scan.issue_counts, {"unavailable_root": 1})
        self.assertNotIn("PRIVATE_SENTINEL", repr(scan))

    def test_unreadable_file_is_failed_and_does_not_reuse_previous_success(self):
        self.write(history(event()))
        old = self.scan()
        original = Path.open
        def deny(path, *args, **kwargs):
            if path == self.path:
                raise PermissionError("PRIVATE_SENTINEL")
            return original(path, *args, **kwargs)
        with patch.object(Path, "open", deny):
            failed = self.scan()
            report = reports.collect_report("session", providers=["Codex"], roots={"Codex": [self.root]}, now=NOW)
        self.assertEqual(failed.state, "failed")
        self.assertEqual(failed.issue_counts, {"unreadable_file": 1})
        self.assertEqual(failed.observations, ())
        self.assertEqual(self.total(old), 100)
        self.assertEqual(report.records, [])
        for render in (reports.render_report, reports.render_text_report):
            text = render(report)
            self.assertIn("source scan: failed", text)
            self.assertNotIn("PRIVATE_SENTINEL", text)
            self.assertNotIn("DEMO", text)

    def test_one_unreadable_file_keeps_other_file_partial(self):
        self.write(history(event()))
        other = self.root / "unreadable.jsonl"
        other.write_text("{}\n", encoding="utf-8")
        original = ingestion.verified_prefix
        def read(path):
            if path == other:
                return None, None, [ingestion.ScanIssue("unreadable_file", "A log file could not be read.")]
            return original(path)
        with patch.object(ingestion, "verified_prefix", side_effect=read):
            scan = self.scan()
        self.assertEqual(scan.state, "partial")
        self.assertEqual((scan.files_read, scan.files_discovered), (1, 2))
        self.assertEqual(self.total(scan), 100)

    def test_truncation_during_read_retries_whole_generation(self):
        self.write(history(event(100), event(200, NOW)))
        original = ingestion.os.fstat
        calls = 0
        def truncate(descriptor):
            nonlocal calls
            value = original(descriptor)
            calls += 1
            if calls == 1:
                self.write(history(event(50)))
            return value
        with patch.object(ingestion.os, "fstat", side_effect=truncate):
            scan = self.scan()
        self.assertEqual(self.total(scan), 50)
        self.assertEqual(scan.state, "complete")
        self.assertEqual(scan.issue_counts, {"source_changed_retried": 1})
        self.assertTrue(all(o.source.generation for o in scan.observations))

    def test_replacement_identity_mismatch_retries_before_acceptance(self):
        self.write(history(event(100)))
        original = Path.stat
        calls = 0
        def replaced(path, *args, **kwargs):
            nonlocal calls
            value = original(path, *args, **kwargs)
            calls += 1
            if calls == 1:
                return SimpleNamespace(st_dev=value.st_dev, st_ino=value.st_ino + 1,
                                       st_size=value.st_size, st_mtime_ns=value.st_mtime_ns)
            return value
        with patch.object(Path, "stat", replaced):
            data, generation, issues = ingestion.verified_prefix(self.path)
        self.assertTrue(data and generation)
        self.assertEqual([i.code for i in issues], ["source_changed_retried"])

    def test_same_size_in_place_mutation_does_not_mix_metadata(self):
        self.write(history(event(100)))
        original = ingestion.os.fstat
        calls = 0
        def mutate(descriptor):
            nonlocal calls
            value = original(descriptor)
            calls += 1
            if calls == 1:
                self.write(history(event(900)))  # Same byte length, different metadata/counters.
                os.utime(self.path, ns=(value.st_atime_ns, value.st_mtime_ns + 10000000))
            return value
        with patch.object(ingestion.os, "fstat", side_effect=mutate):
            scan = self.scan()
        self.assertEqual(scan.issue_counts, {"source_changed_retried": 1})
        self.assertEqual(self.total(scan), 900)
        self.assertEqual(scan.state, "complete")

    def test_subfolder_enumeration_failure_stays_partial(self):
        self.write(history(event()))
        def walk(root, followlinks, onerror):
            onerror(PermissionError("PRIVATE_SENTINEL"))
            yield str(root), [], [self.path.name]
        with patch.object(ingestion.os, "walk", side_effect=walk):
            scan = self.scan()
        self.assertEqual(scan.state, "partial")
        self.assertEqual(self.total(scan), 100)
        self.assertEqual(scan.issue_counts, {"unreadable_directory": 1})
        self.assertNotIn("PRIVATE_SENTINEL", repr(scan))

    def test_overlapping_roots_do_not_duplicate_observations(self):
        nested = self.root / "nested"
        nested.mkdir()
        self.path = nested / "fixture.jsonl"
        self.write(history(event()))
        scan = ingestion.scan_observations("Codex", [self.root, nested, self.root])
        self.assertEqual(len(scan.observations), 1)
        self.assertEqual(scan.files_read, 1)
        self.assertEqual(self.total(scan), 100)

    def test_repeated_replacement_or_mutation_fails_without_mixed_observations(self):
        self.write(history(event()))
        with patch.object(ingestion, "_read_prefix_once", side_effect=ingestion.SourceChanged):
            scan = self.scan()
        self.assertEqual(scan.state, "failed")
        self.assertEqual(scan.observations, ())
        self.assertEqual(scan.issue_counts, {"unstable_file": 1})

    def test_append_during_read_accepts_only_verified_initial_prefix(self):
        self.write(history(event()))
        original = ingestion.os.fstat
        calls = 0
        def append(descriptor):
            nonlocal calls
            value = original(descriptor)
            calls += 1
            if calls == 1:
                with self.path.open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps(event(200, NOW)) + "\n")
            return value
        with patch.object(ingestion.os, "fstat", side_effect=append):
            scan = self.scan()
        self.assertEqual(scan.state, "partial")
        self.assertEqual(self.total(scan), 100)
        self.assertEqual(scan.issue_counts, {"append_deferred": 1})
        self.assertEqual(self.total(self.scan()), 200)

    def test_missing_invalid_counters_and_timestamps_are_not_observed_zero(self):
        a, b = event(), event(200, NOW)
        del a["payload"]["info"]["total_token_usage"]["output_tokens"]
        b["payload"]["info"]["total_token_usage"]["input_tokens"] = None
        b["timestamp"] = "not-a-timestamp"
        self.write(history(a, b))
        scan = self.scan()
        self.assertEqual(scan.state, "partial")
        self.assertEqual(scan.issue_counts, {"invalid_counter_metadata": 1, "invalid_timestamp": 1,
                                            "missing_counter_metadata": 1})
        self.assertTrue(all(i.excluded_tokens is None for i in scan.issues))
        self.assertEqual(self.total(scan), 0)

    def test_missing_claude_message_id_is_structured(self):
        self.write([{"type": "assistant", "timestamp": "2026-10-23T20:00:00Z", "sessionId": "c",
                     "message": {"model": "claude-sonnet-4-6", "usage": {"input_tokens": 1,
                      "output_tokens": 1, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}}}])
        scan = ingestion.scan_observations("Claude", [self.root])
        self.assertEqual(scan.issue_counts, {"missing_message_id": 1})
        self.assertEqual(scan.state, "partial")
        self.assertEqual(reconcile_observations(scan.observations).events, ())

    def test_generation_stable_on_repeat_changes_on_replacement(self):
        self.write(history(event()))
        first = self.scan()
        self.assertEqual(first.observations, self.scan().observations)
        replacement = self.root / "replacement.tmp"
        replacement.write_bytes(self.path.read_bytes())
        replacement.replace(self.path)
        second = self.scan()
        self.assertNotEqual(first.observations[0].source.generation, second.observations[0].source.generation)
        self.assertEqual(reconcile_observations(first.observations).events[0].event_id,
                         reconcile_observations(second.observations).events[0].event_id)

    def test_malformed_context_defers_suffix_then_repair_restores_it(self):
        self.write(history(event()))
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write('broken context PRIVATE_SENTINEL\n' + json.dumps(event(200, NOW)) + '\n')
        scan = self.scan()
        self.assertEqual(self.total(scan), 100)
        self.assertEqual(scan.issue_counts, {"malformed_record": 1, "untrusted_suffix": 1})
        self.assertNotIn("PRIVATE_SENTINEL", repr(scan))
        self.write(history(event(), event(200, NOW)))
        self.assertEqual(self.total(self.scan()), 200)
        self.assertEqual(self.scan().state, "complete")

    def test_claude_missing_write_category_has_separate_counter_quality(self):
        self.write([{"type": "assistant", "timestamp": "2026-10-23T20:00:00Z", "sessionId": "c",
                     "message": {"id": "m", "model": "claude-sonnet-4-6", "usage": {"input_tokens": 1,
                      "output_tokens": 1, "cache_read_input_tokens": 0}}}])
        scan = ingestion.scan_observations("Claude", [self.root])
        self.assertEqual(scan.issue_counts, {"missing_counter_metadata": 1})
        self.assertEqual(scan.state, "partial")
        self.assertEqual(reconcile_observations(scan.observations).events, ())

    def test_utf8_bom_blank_prefix_and_crlf_preserve_physical_lines(self):
        text = "\r\n" + "\r\n".join(json.dumps(e) for e in history(event())) + "\r\n"
        self.path.write_bytes(text.encode("utf-8-sig"))
        scan = self.scan()
        self.assertEqual(scan.state, "complete")
        self.assertEqual(self.total(scan), 100)
        self.assertEqual(scan.observations[0].source.line, 4)

    def test_prefix_byte_verification_detects_mutation_with_restored_mtime(self):
        self.write(history(event(100)))
        original = Path.open
        saved = self.path.stat()
        changed = False
        owner = self
        class MutatingReader:
            def __init__(self, stream):
                self.stream = stream
            def __enter__(self):
                return self
            def __exit__(self, *args):
                self.stream.close()
            def fileno(self):
                return self.stream.fileno()
            def seek(self, offset):
                return self.stream.seek(offset)
            def read(self, size):
                nonlocal changed
                data = self.stream.read(size)
                if not changed:
                    changed = True
                    with original(owner.path, "wb") as writer:
                        writer.write("".join(json.dumps(e) + "\n" for e in history(event(900))).encode("utf-8"))
                    os.utime(owner.path, ns=(saved.st_atime_ns, saved.st_mtime_ns))
                return data
        def open_file(path, *args, **kwargs):
            stream = original(path, *args, **kwargs)
            return MutatingReader(stream) if path == self.path and args[0] == "rb" else stream
        with patch.object(Path, "open", open_file):
            scan = self.scan()
        self.assertEqual(scan.issue_counts, {"source_changed_retried": 1})
        self.assertEqual(scan.state, "complete")
        self.assertEqual(self.total(scan), 900)

    def test_headless_import_does_not_import_provider_or_gui(self):
        process = subprocess.run([sys.executable, "-c", "import sys; import usage_ingestion; "
                                  "assert not {'usage_core','usage_tray','PIL','pystray'} & sys.modules.keys()"],
                                 cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True)
        self.assertEqual(process.returncode, 0, process.stderr)


if __name__ == "__main__":
    unittest.main()
