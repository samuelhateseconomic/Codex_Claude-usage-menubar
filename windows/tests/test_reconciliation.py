import json
from itertools import permutations
from dataclasses import replace
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import usage_reports as reports
from usage_reconciliation import reconcile_observations


def counter(value, second):
    return {"type": "event_msg", "timestamp": f"2026-10-23T20:00:{second:02d}Z", "payload": {
        "type": "token_count", "info": {"total_token_usage": {
            "input_tokens": value, "output_tokens": 0, "cached_input_tokens": 0}}}}


def header():
    return [{"type": "session_meta", "timestamp": "2026-10-23T19:00:00Z",
             "payload": {"id": "same-session", "cwd": "fixture"}},
            {"type": "turn_context", "payload": {"model": "gpt-5.4"}}]


class AccountingFixtures(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def write(self, name, events):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(json.dumps(e) for e in header() + events), encoding="utf-8")
        return path


class AccountingRegressions(AccountingFixtures):
    def test_complete_and_truncated_copy_are_200_in_every_file_order_and_reimport(self):
        complete = self.write("full/a.jsonl", [counter(100, 10), counter(200, 20)])
        partial = self.write("partial/b.jsonl", [counter(200, 20)])
        for paths in ([partial, complete], [complete, partial], [partial, complete, partial]):
            with self.subTest(paths=[p.parent.name for p in paths]):
                with patch.object(reports, "log_files", return_value=iter(paths)):
                    records = reports.read_codex([self.root], [])
                self.assertEqual(sum(r.tokens.total for r in records), 200)
        for roots in ([partial.parent, complete.parent], [complete.parent, partial.parent]):
            self.assertEqual(sum(r.tokens.total for r in reports.read_codex(roots, [])), 200)

    def test_reset_retains_final_increment_when_numeric_total_repeats(self):
        self.write("reset.jsonl", [counter(100, 10), counter(200, 20), counter(50, 30), counter(100, 40)])
        notices = []
        records = reports.read_codex([self.root], notices)
        self.assertEqual([r.tokens.total for r in records], [100, 100, 50])
        self.assertEqual(sum(r.tokens.total for r in records), 250)
        self.assertTrue(any("reset" in n.lower() for n in notices))


class ReconciliationEdges(AccountingFixtures):
    def result(self, provider="Codex"):
        return reconcile_observations(reports.read_observations(provider, [self.root], []))

    def tokens(self, result):
        return sum(e.record.tokens.total for e in result.events)

    def codes(self, result):
        return {issue.code for issue in result.issues}

    def test_partial_reset_copies_preserve_epochs_and_ids_in_reversed_order(self):
        full = self.write("full.jsonl", [counter(100, 10), counter(200, 20), counter(50, 30), counter(100, 40)])
        tail = self.write("tail.jsonl", [counter(50, 30), counter(100, 40)])
        all_observations = reports.read_observations("Codex", [self.root], [])
        expected = reconcile_observations(all_observations)
        reversed_result = reconcile_observations(reversed(all_observations))
        self.assertEqual(self.tokens(expected), 250)
        self.assertEqual([e.event_id for e in expected.events], [e.event_id for e in reversed_result.events])
        self.assertNotEqual(expected.events[0].epoch_anchor, expected.events[-1].epoch_anchor)
        self.assertTrue(any(ref.source_id == str(tail.resolve()) for ref in expected.events[-1].sources))
        self.assertTrue(any(ref.source_id == str(full.resolve()) for ref in expected.events[-1].sources))

    def test_multiple_resets_and_copied_suffixes_have_invariant_ids_and_totals(self):
        self.write("full.jsonl", [counter(v, t) for v, t in [(100, 5), (200, 10), (50, 15),
                    (100, 20), (150, 25), (20, 30), (50, 35)]])
        self.write("tail.jsonl", [counter(150, 25), counter(20, 30), counter(50, 35)])
        self.write("partial.jsonl", [counter(50, 15), counter(100, 20)])
        observations = reports.read_observations("Codex", [self.root], [])
        by_source = {}
        for o in observations:
            by_source.setdefault(o.source.source_id, []).append(o)
        expected_ids = [e.event_id for e in self.result().events]
        for order in permutations(by_source):
            result = reconcile_observations([o for source in order for o in by_source[source]])
            self.assertEqual(self.tokens(result), 330)  # 100+100 + 50+50 + 30; reset transitions excluded.
            self.assertEqual([e.event_id for e in result.events], expected_ids)

    def test_reconciliation_import_is_independent_of_gui_pricing_and_provider_adapters(self):
        import subprocess
        code = "import sys; import usage_reconciliation; assert not {'usage_reports', 'usage_tray', 'usage_core', 'pystray', 'PIL'} & set(sys.modules)"
        result = subprocess.run([sys.executable, "-c", code], cwd=Path(__file__).resolve().parents[1],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_tied_zero_notification_metadata_is_qualified_without_relabeling(self):
        path = self.write("a.jsonl", [counter(100, 10)])
        entries = [json.loads(line) for line in path.read_text().splitlines()]
        entries[1]["payload"]["effort"] = "medium"
        entries += [{"type": "turn_context", "payload": {"model": "gpt-5.4", "effort": "high"}}, counter(100, 10)]
        path.write_text("\n".join(map(json.dumps, entries)))
        result = self.result()
        self.assertEqual(self.tokens(result), 100)
        self.assertEqual(result.events[0].record.effort, "unknown")
        self.assertIn("metadata_conflict", self.codes(result))

    def test_unplaced_counter_and_missing_fork_time_are_visible_exclusions(self):
        event = counter(100, 10)
        event["timestamp"] = None
        self.write("a.jsonl", [event, counter(200, 20)])
        result = self.result()
        self.assertEqual(result.events, ())
        self.assertIn("unplaced_observation", self.codes(result))
        from usage_observations import extract_codex
        entries = header()
        del entries[0]["timestamp"]
        entries[0]["payload"]["forked_from_id"] = "parent"
        result = reconcile_observations(extract_codex(enumerate(entries + [counter(100, 10)], 1), "fixture"))
        self.assertEqual(result.events, ())
        self.assertIn("fork_boundary_conflict", self.codes(result))

    def test_zero_notifications_do_not_relabel_usage_or_change_later_epoch_ids(self):
        events = [counter(100, 10), counter(200, 20), counter(50, 30), counter(100, 40)]
        path = self.write("a.jsonl", events)
        before = self.result()
        events.insert(2, counter(200, 25))
        self.write("a.jsonl", events)
        after = self.result()
        self.assertEqual([e.event_id for e in before.events], [e.event_id for e in after.events])
        self.assertEqual(self.tokens(after), 250)

    def test_equal_timestamps_use_source_sequence_instead_of_numeric_sort(self):
        self.write("full.jsonl", [counter(100, 10), counter(200, 10), counter(50, 10), counter(100, 20)])
        self.write("partial.jsonl", [counter(200, 10), counter(50, 10), counter(100, 20)])
        result = self.result()
        self.assertEqual([e.record.tokens.total for e in result.events], [100, 100, 50])
        self.assertEqual(self.tokens(result), 250)

    def test_unordered_equal_time_points_exclude_ambiguity_then_resume(self):
        self.write("a.jsonl", [counter(100, 10)])
        self.write("b.jsonl", [counter(200, 10), counter(300, 20), counter(350, 30)])
        result = self.result()
        self.assertEqual(self.tokens(result), 50)
        self.assertIn("ambiguous_sequence", self.codes(result))
        self.assertIn("baseline_reestablished", self.codes(result))
        self.assertTrue(all(issue.excluded_tokens is None for issue in result.issues))

    def test_same_clock_repeated_point_cycle_is_excluded_without_guessing(self):
        self.write("a.jsonl", [counter(100, 10), counter(200, 10), counter(50, 10), counter(100, 10),
                              counter(200, 20), counter(250, 30)])
        result = self.result()
        self.assertEqual(self.tokens(result), 50)
        self.assertIn("ambiguous_sequence", self.codes(result))

    def test_source_clock_reversal_is_a_visible_exclusion(self):
        self.write("a.jsonl", [counter(200, 20), counter(300, 10)])
        result = self.result()
        self.assertEqual(result.events, ())
        self.assertIn("source_order_conflict", self.codes(result))

    def test_fork_copies_use_inherited_baseline_not_child_origin(self):
        entries = header()
        entries[0]["timestamp"] = "2026-10-23T20:00:20Z"
        entries[0]["payload"]["forked_from_id"] = "parent"
        complete = self.root / "a.jsonl"
        partial = self.root / "b.jsonl"
        complete.write_text("\n".join(map(json.dumps, entries + [counter(100, 10), counter(200, 30), counter(250, 40)])))
        partial.write_text("\n".join(map(json.dumps, entries + [counter(200, 30), counter(250, 40)])))
        result = self.result()
        self.assertEqual([e.record.tokens.total for e in result.events], [100, 50])

    def test_fork_without_inherited_history_seeds_before_counting(self):
        entries = header()
        entries[0]["payload"]["forked_from_id"] = "parent"
        (self.root / "a.jsonl").write_text("\n".join(map(json.dumps, entries + [counter(200, 30), counter(250, 40)])))
        result = self.result()
        self.assertEqual(self.tokens(result), 50)
        self.assertIn("baseline_reestablished", self.codes(result))

    def test_missing_category_is_a_gap_not_zero_and_does_not_create_false_reset(self):
        missing = counter(150, 20)
        del missing["payload"]["info"]["total_token_usage"]["cached_input_tokens"]
        self.write("a.jsonl", [counter(100, 10), missing, counter(200, 30), counter(250, 40)])
        result = self.result()
        self.assertEqual(self.tokens(result), 150)
        self.assertIn("partial_counter_metadata", self.codes(result))
        self.assertNotIn("counter_reset", self.codes(result))

    def test_invalid_cache_increment_is_excluded_but_later_valid_delta_survives(self):
        events = [counter(100, 10), counter(150, 20), counter(200, 30)]
        for e, cached in zip(events, [20, 100, 120]):
            e["payload"]["info"]["total_token_usage"]["cached_input_tokens"] = cached
        self.write("a.jsonl", events)
        result = self.result()
        self.assertEqual(self.tokens(result), 150)
        self.assertIn("cache_exceeds_input", self.codes(result))
        self.assertEqual(result.events[-1].record.tokens, reports.Tokens(30, 0, 20))

    def test_conflicting_copy_model_stays_unpriced_instead_of_filename_winner(self):
        self.write("a.jsonl", [counter(100, 10)])
        path = self.write("b.jsonl", [counter(100, 10)])
        entries = [json.loads(line) for line in path.read_text().splitlines()]
        entries[1]["payload"]["model"] = "other-model"
        path.write_text("\n".join(map(json.dumps, entries)))
        result = self.result()
        self.assertEqual(self.tokens(result), 100)
        self.assertEqual(result.events[0].record.model, "unknown")
        self.assertIsNone(reports.estimate(result.events[0].record))
        self.assertIn("metadata_conflict", self.codes(result))

    def test_same_source_position_conflict_is_not_silently_overwritten(self):
        self.write("a.jsonl", [counter(100, 10)])
        observations = reports.read_observations("Codex", [self.root], [])
        conflicting = replace(observations[0], model="different")
        result = reconcile_observations(observations + [conflicting])
        self.assertEqual(result.events, ())
        self.assertIn("source_observation_conflict", self.codes(result))

    def test_mixed_cumulative_and_last_only_do_not_double_charge(self):
        last = counter(50, 15)
        info = last["payload"]["info"]
        info["last_token_usage"] = info.pop("total_token_usage")
        self.write("a.jsonl", [counter(100, 10), last, counter(200, 20)])
        result = self.result()
        self.assertEqual(self.tokens(result), 200)
        self.assertIn("mixed_last_usage_excluded", self.codes(result))

    def test_last_only_copies_and_strong_request_updates(self):
        events = []
        for value, second in [(100, 10), (150, 20)]:
            e = counter(value, second)
            info = e["payload"]["info"]
            info["last_token_usage"] = info.pop("total_token_usage")
            e["payload"]["request_id"] = "same-request"
            events.append(e)
        self.write("a.jsonl", events)
        self.write("b.jsonl", events)
        result = self.result()
        self.assertEqual(self.tokens(result), 150)
        self.assertIn("last_usage_fallback", self.codes(result))

    def test_weak_last_only_same_time_conflict_excluded(self):
        events = [counter(100, 10), counter(200, 10)]
        for e in events:
            info = e["payload"]["info"]
            info["last_token_usage"] = info.pop("total_token_usage")
        self.write("a.jsonl", events)
        result = self.result()
        self.assertEqual(result.events, ())
        self.assertIn("ambiguous_last_usage", self.codes(result))

    def test_reconciled_counts_reach_both_existing_renderers(self):
        self.write("a.jsonl", [counter(100, 10), counter(200, 20), counter(50, 30), counter(100, 40)])
        records = reports.read_codex([self.root], [])
        report = reports.Report(records, {"Codex": (0, "fixture")}, 9999999999)
        for renderer in (reports.render_text_report, reports.render_report):
            self.assertIn("250", renderer(report))
        self.assertAlmostEqual(sum(reports.estimate(r) for r in records), 0.000625)


def claude(output, second):
    return {"type": "assistant", "timestamp": f"2026-10-23T20:00:{second:02d}Z", "sessionId": "claude-session",
            "requestId": "request", "cwd": "fixture", "message": {"id": "message", "model": "claude-sonnet-4-6",
            "usage": {"input_tokens": 100, "output_tokens": output, "cache_read_input_tokens": 200,
                      "cache_creation_input_tokens": 700,
                      "cache_creation": {"ephemeral_5m_input_tokens": 300, "ephemeral_1h_input_tokens": 400}}}}


class ClaudeReconciliation(unittest.TestCase):
    def reconcile(self, files):
        from usage_observations import extract_claude
        observations = []
        for source, entries in files.items():
            observations.extend(extract_claude(enumerate(entries, 1), source))
        return reconcile_observations(observations)

    def test_stream_copies_merge_maxima_and_explicit_effort_independent_of_file_order(self):
        first, final = claude(10, 10), claude(40, 20)
        first["message"]["output_config"] = {"effort": "high"}
        a = self.reconcile({"partial": [final], "full": [first, final]})
        b = self.reconcile({"full": [first, final], "partial": [final]})
        self.assertEqual(a.events, b.events)
        self.assertEqual(a.events[0].record.tokens, reports.Tokens(100, 40, 200, 300, 400))
        self.assertEqual(a.events[0].record.effort, "high")
        self.assertEqual(len(a.events[0].sources), 3)

    def test_legacy_then_detailed_writes_are_not_counted_in_both_ttls(self):
        first, final = claude(10, 10), claude(40, 20)
        del first["message"]["usage"]["cache_creation"]
        result = self.reconcile({"a": [first, final]})
        self.assertEqual(result.events[0].record.tokens, reports.Tokens(100, 40, 200, 300, 400))
        self.assertNotIn("legacy_cache_ttl_assumed", {i.code for i in result.issues})

    def test_conflicting_write_representations_are_excluded(self):
        event = claude(10, 10)
        event["message"]["usage"]["cache_creation_input_tokens"] = 900
        result = self.reconcile({"a": [event]})
        self.assertEqual(result.events, ())
        self.assertIn("cache_representation_conflict", {i.code for i in result.issues})

    def test_missing_request_copy_enriches_only_unambiguous_identity(self):
        known, missing = claude(10, 10), claude(40, 20)
        del missing["requestId"]
        result = self.reconcile({"a": [known], "b": [missing]})
        self.assertEqual(len(result.events), 1)
        self.assertEqual(result.events[0].record.tokens.output, 40)
        other = claude(20, 15)
        other["requestId"] = "other-request"
        result = self.reconcile({"a": [known, other], "b": [missing]})
        self.assertEqual(len(result.events), 2)
        self.assertEqual(sum(e.record.tokens.output for e in result.events), 30)
        self.assertIn("ambiguous_request_identity", {i.code for i in result.issues})

    def test_invalid_and_missing_metadata_do_not_become_zero_usage(self):
        event = claude(10, 10)
        event["message"]["usage"]["input_tokens"] = None
        result = self.reconcile({"a": [event]})
        self.assertEqual(result.events, ())
        self.assertIn("partial_counter_metadata", {i.code for i in result.issues})

    def test_conflicting_explicit_effort_is_qualified_unknown(self):
        a, b = claude(10, 10), claude(40, 20)
        a["effort"], b["effort"] = "high", "low"
        result = self.reconcile({"a": [a, b]})
        self.assertEqual(result.events[0].record.effort, "unknown")
        self.assertIn("metadata_conflict", result.events[0].quality)


if __name__ == "__main__":
    unittest.main()
