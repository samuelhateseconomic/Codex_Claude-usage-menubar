import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime, timezone
from dataclasses import replace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from usage_core import Snapshot, Window
import usage_reports as reports


NOW = datetime(2026, 10, 23, 20, tzinfo=timezone.utc).timestamp()


def iso(seconds):
    return datetime.fromtimestamp(seconds, timezone.utc).isoformat()


class ReportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.codex = self.base / "sessions"
        self.claude = self.base / "projects"
        self.codex.mkdir()
        self.claude.mkdir()
        self.roots = {"Codex": [self.codex], "Claude": [self.claude]}

    def write(self, root, name, entries):
        path = root / name
        path.write_text("\n".join(json.dumps(e) for e in entries) + "\n", encoding="utf-8")
        return path

    def codex_event(self, when, inp, out, cached, reasoning=0):
        return {"timestamp": iso(when), "type": "event_msg", "payload": {"type": "token_count", "info": {
            "total_token_usage": {"input_tokens": inp, "output_tokens": out, "cached_input_tokens": cached, "reasoning_output_tokens": reasoning}}}}

    def codex_header(self, model="gpt-5.2-codex", session="s1"):
        return [{"type": "session_meta", "timestamp": iso(NOW - 10000), "payload": {"id": session, "cwd": "C:/project"}},
                {"type": "turn_context", "payload": {"model": model}}]

    def claude_event(self, when=NOW - 10, msg="m1", output=100):
        return {"type": "assistant", "timestamp": iso(when), "sessionId": "c1", "requestId": "r1", "cwd": "C:/project",
                "message": {"id": msg, "model": "claude-sonnet-4-6", "content": [{"text": "PRIVATE PROMPT CONTENT"}],
                "usage": {"input_tokens": 1000, "output_tokens": output, "cache_read_input_tokens": 2000,
                          "cache_creation_input_tokens": 700,
                          "cache_creation": {"ephemeral_5m_input_tokens": 300, "ephemeral_1h_input_tokens": 400}}}}

    def test_codex_deltas_baseline_repeats_and_reasoning_subset(self):
        entries = self.codex_header() + [self.codex_event(NOW - 9000, 1000, 100, 500),
                   self.codex_event(NOW - 10, 3000, 400, 1500, reasoning=200),
                   self.codex_event(NOW - 5, 3000, 400, 1500, reasoning=200)]
        self.write(self.codex, "rollout.jsonl", entries)
        report = reports.collect_report("session", roots=self.roots, now=NOW,
                                        snapshots={"Codex": Snapshot("Codex", [Window("5h", 20, NOW + 10000, 300)])})
        codex = [r for r in report.records if r.provider == "Codex"]
        self.assertEqual(len(codex), 1)
        self.assertEqual(codex[0].tokens, reports.Tokens(1000, 300, 1000))
        self.assertAlmostEqual(reports.estimate(codex[0]), (1000 * 1.75 + 300 * 14 + 1000 * .175) / 1e6)

    def test_codex_model_switch_prices_deltas_under_each_model(self):
        entries = self.codex_header("gpt-5") + [self.codex_event(NOW - 30, 1000, 100, 0),
                   {"type": "turn_context", "payload": {"model": "gpt-5.4"}},
                   self.codex_event(NOW - 10, 3000, 400, 500)]
        self.write(self.codex, "rollout.jsonl", entries)
        records = reports.read_codex([self.codex], [])
        self.assertEqual([r.model for r in records], ["gpt-5", "gpt-5.4"])
        self.assertEqual(records[1].tokens, reports.Tokens(1500, 300, 500))

    def test_effort_switches_inside_one_codex_conversation_follow_each_turn(self):
        entries = self.codex_header()
        for index, (effort, output, reasoning) in enumerate([("medium", 100, 20), ("high", 300, 100), ("ultra", 600, 250)]):
            entries += [{"type": "turn_context", "payload": {"model": "gpt-5.2-codex", "effort": effort, "turn_id": f"turn-{index}"}},
                        self.codex_event(NOW - 30 + index * 10, (index + 1) * 1000, output, 0, reasoning)]
        self.write(self.codex, "mixed-effort.jsonl", entries)
        records = reports.read_codex([self.codex], [])
        self.assertEqual([r.effort for r in records], ["medium", "high", "ultra"])
        self.assertEqual([r.turn_id for r in records], ["turn-0", "turn-1", "turn-2"])
        self.assertEqual([r.tokens.output for r in records], [100, 200, 300])
        self.assertEqual([r.reasoning_tokens for r in records], [20, 80, 150])
        self.assertTrue(all(r.effort_source == "Codex turn_context.effort" for r in records))
        total_cost = sum(reports.estimate(r) for r in records)
        self.assertAlmostEqual(total_cost, (3000 * 1.75 + 600 * 14) / 1e6)
        self.assertEqual(reports.estimate(records[0]), reports.estimate(replace(records[0], effort="ultra")))
        report = reports.collect_report(roots=self.roots, now=NOW)
        html = reports.render_report(report)
        for effort in ("medium", "high", "ultra"):
            self.assertIn(f"Codex / gpt-5.2-codex / {effort}", html)
        self.assertIn("Turn and usage-event history", html)
        self.assertIn("turn-2", html)
        self.assertIn("Reasoning (subset)", html)

    def test_codex_missing_or_null_effort_does_not_inherit_last_turn(self):
        entries = self.codex_header()
        settings = [{"effort": "ultra"}, {}, {"effort": None, "collaboration_mode": {"settings": {"reasoning_effort": "high"}}},
                    {"collaboration_mode": {"settings": {"reasoning_effort": "medium"}}}]
        for i, setting in enumerate(settings):
            entries += [{"type": "turn_context", "payload": {"model": "gpt-5.2-codex", **setting}},
                        self.codex_event(NOW - 40 + i * 10, (i + 1) * 1000, (i + 1) * 100, 0)]
        self.write(self.codex, "missing-effort.jsonl", entries)
        records = reports.read_codex([self.codex], [])
        self.assertEqual([r.effort for r in records], ["ultra", "unknown", "unknown", "medium"])
        self.assertEqual(records[-1].effort_source, "Codex collaboration settings.reasoning_effort")
        html = reports.render_report(reports.collect_report(roots=self.roots, now=NOW))
        self.assertIn("Effort was not recorded for 2 usage records", html)

    def test_repeated_counters_after_effort_change_do_not_relabel_previous_usage(self):
        entries = self.codex_header()
        entries += [{"type": "turn_context", "payload": {"model": "gpt-5", "effort": "medium"}}, self.codex_event(NOW - 20, 1000, 100, 0),
                    {"type": "turn_context", "payload": {"model": "gpt-5", "effort": "ultra"}}, self.codex_event(NOW - 10, 1000, 100, 0)]
        self.write(self.codex, "repeated.jsonl", entries)
        records = reports.read_codex([self.codex], [])
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].effort, "medium")

    def test_wire_effort_values_are_distinct_including_custom_values(self):
        for value in ["none", "minimal", "medium", "high", "xhigh", "max", "ultra", "persistent", "future-value"]:
            with self.subTest(value=value):
                self.assertEqual(reports.recorded_effort(("turn", {"effort": value}))[0], value)
        self.assertEqual(reports.recorded_effort(("turn", {"effort": 80}))[0], "unknown")
        self.assertIsNone(reports.recorded_effort(("turn", {"maxThinkingTokens": 10000})))

    def test_reasoning_counter_gaps_do_not_assign_old_reasoning_to_new_effort(self):
        entries = self.codex_header()
        first = self.codex_event(NOW - 40, 1000, 100, 0, 20)
        missing = self.codex_event(NOW - 30, 2000, 200, 0)
        del missing["payload"]["info"]["total_token_usage"]["reasoning_output_tokens"]
        entries += [first, missing, self.codex_event(NOW - 20, 3000, 300, 0, 50), self.codex_event(NOW - 10, 4000, 400, 0, 80)]
        self.write(self.codex, "reasoning-gap.jsonl", entries)
        records = reports.read_codex([self.codex], [])
        self.assertEqual([r.reasoning_tokens for r in records], [20, None, None, 30])
        self.assertEqual(sum(r.tokens.output for r in records), 400)
        self.assertEqual(reports.reasoning_count({"reasoning_output_tokens": 200}, 100), None)

    def test_codex_last_usage_effort_and_reasoning_without_cumulative_counters(self):
        entries = self.codex_header()
        entries += [{"type": "turn_context", "payload": {"model": "gpt-5.4", "effort": "ultra"}},
                    {"type": "event_msg", "timestamp": iso(NOW - 10), "payload": {"type": "token_count", "info": {
                        "last_token_usage": {"input_tokens": 1000, "cached_input_tokens": 500, "output_tokens": 100, "reasoning_output_tokens": 60}}}}]
        self.write(self.codex, "last-only.jsonl", entries)
        record = reports.read_codex([self.codex], [])[0]
        self.assertEqual(record.effort, "ultra")
        self.assertEqual(record.reasoning_tokens, 60)
        self.assertEqual(record.tokens.total, 1100)

    def test_copied_codex_and_claude_logs_are_not_double_counted(self):
        entries = self.codex_header() + [self.codex_event(NOW - 10, 3000, 400, 1500)]
        self.write(self.codex, "one.jsonl", entries)
        self.write(self.codex, "copy.jsonl", entries)
        self.write(self.claude, "one.jsonl", [self.claude_event()])
        self.write(self.claude, "copy.jsonl", [self.claude_event()])
        report = reports.collect_report(roots=self.roots, now=NOW)
        self.assertEqual(len(report.records), 2)

    def test_claude_streaming_maxima_and_separate_cache_creation(self):
        self.write(self.claude, "conversation.jsonl", [self.claude_event(output=10), self.claude_event(NOW - 5, output=100)])
        records = reports.read_claude([self.claude], [])
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].tokens, reports.Tokens(1000, 100, 2000, 300, 400))
        self.assertEqual(records[0].tokens.total, 3800)
        self.assertAlmostEqual(reports.estimate(records[0]), (3000 + 1500 + 600 + 1125 + 2400) / 1e6)

    def test_claude_legacy_cache_and_dated_model(self):
        entry = self.claude_event()
        entry["message"]["model"] = "claude-sonnet-4-6-20261001"
        del entry["message"]["usage"]["cache_creation"]
        self.write(self.claude, "conversation.jsonl", [entry])
        record = reports.read_claude([self.claude], [])[0]
        self.assertEqual(record.tokens.write5m, 700)
        self.assertIsNotNone(reports.estimate(record))
        self.assertIsNone(reports.price_for("gpt-5.4-unknown-premium"))

    def test_claude_explicit_message_effort_and_stream_updates(self):
        first = self.claude_event(output=10)
        first["message"]["output_config"] = {"effort": "high"}
        final = self.claude_event(NOW - 5, output=100)
        self.write(self.claude, "effort.jsonl", [first, final])
        records = reports.read_claude([self.claude], [])
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].effort, "high")
        self.assertEqual(records[0].effort_source, "Claude output_config.effort")
        self.assertIsNone(records[0].reasoning_tokens)

    def test_claude_turn_metadata_covers_tool_results_then_resets_on_new_prompt(self):
        entries = [
            {"type": "user", "uuid": "u1", "effortValue": "medium", "message": {"content": "PRIVATE PROMPT"}},
            self.claude_event(msg="m1"),
            {"type": "user", "message": {"content": [{"type": "tool_result", "content": "PRIVATE RESULT"}]}},
            self.claude_event(msg="m2"),
            {"type": "user", "uuid": "u2", "message": {"content": "NEXT PRIVATE PROMPT"}},
            self.claude_event(msg="m3"),
        ]
        self.write(self.claude, "turns.jsonl", entries)
        records = reports.read_claude([self.claude], [])
        self.assertEqual([r.effort for r in records], ["medium", "medium", "unknown"])
        self.assertEqual([r.turn_id for r in records], ["u1", "u1", "u2"])

    def test_claude_thinking_budget_is_not_an_effort_label(self):
        entry = self.claude_event()
        entry["thinkingMetadata"] = {"level": "high", "maxThinkingTokens": 10000}
        self.write(self.claude, "thinking.jsonl", [entry])
        record = reports.read_claude([self.claude], [])[0]
        self.assertEqual(record.effort, "unknown")
        self.assertIsNone(record.reasoning_tokens)

    def test_effort_metadata_is_escaped_in_html(self):
        entry = self.claude_event()
        entry["effort"] = "<script>bad()</script>"
        self.write(self.claude, "escaped-effort.jsonl", [entry])
        html = reports.render_report(reports.collect_report(roots=self.roots, now=NOW))
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;bad()&lt;/script&gt;", html)

    def test_unknown_model_counts_tokens_and_marks_incomplete_dollar_subtotal(self):
        self.write(self.codex, "rollout.jsonl", self.codex_header("future-model") + [self.codex_event(NOW - 10, 1000, 100, 0)])
        report = reports.collect_report(roots=self.roots, now=NOW)
        self.assertIsNone(reports.estimate(report.records[0]))
        html = reports.render_report(report)
        self.assertIn("1,100", html)
        self.assertIn("unpriced usage", html)
        self.assertIn("dollar subtotal incomplete", html)

    def test_long_context_price_threshold(self):
        record = reports.Record("Codex", NOW, "s", "p", "gpt-5.4", reports.Tokens(250000, 1000, 30000))
        self.assertAlmostEqual(reports.estimate(record), (250000 * 5 + 1000 * 22.5 + 30000 * .5) / 1e6)

    def test_provider_session_boundaries_and_trailing_fallback(self):
        snapshot = Snapshot("Claude", [Window("Session (5h)", 20, NOW + 3600, 300)])
        start, label = reports.period_bounds("session", NOW, snapshot)
        self.assertEqual(start, NOW - 14400)
        self.assertIn("provider", label)
        start, label = reports.period_bounds("session", NOW)
        self.assertEqual(start, NOW - 18000)
        self.assertIn("unavailable", label)
        old = Snapshot("Claude", [Window("Session", 20, NOW - 1, 300)])
        self.assertEqual(reports.period_bounds("session", NOW, old)[0], NOW - 18000)

    def test_period_excludes_old_and_future_records(self):
        self.write(self.claude, "conversation.jsonl", [self.claude_event(NOW - 20000, "old"),
                    self.claude_event(NOW - 10, "current"), self.claude_event(NOW + 10, "future")])
        report = reports.collect_report(roots=self.roots, now=NOW)
        self.assertEqual(len(report.records), 1)
        self.assertEqual(reports.period_bounds("week", NOW)[0], NOW - 604800)
        start, _ = reports.period_bounds("today", NOW)
        self.assertEqual(datetime.fromtimestamp(start).hour, 0)

    def test_bad_lines_and_reset_counters_surface_coverage_notices(self):
        entries = self.codex_header() + [self.codex_event(NOW - 20, 1000, 100, 0), self.codex_event(NOW - 10, 50, 10, 0)]
        path = self.write(self.codex, "broken.jsonl", entries)
        with path.open("a") as stream:
            stream.write('{"unfinished":')
        report = reports.collect_report(roots=self.roots, now=NOW)
        self.assertEqual(len(report.records), 1)
        self.assertTrue(any("counter reset" in n for n in report.notices))
        self.assertTrue(any("incomplete records" in n for n in report.notices))

    def test_fork_history_is_only_a_counter_baseline(self):
        entries = self.codex_header(session="fork")
        entries[0]["payload"]["forked_from_id"] = "parent"
        entries[0]["timestamp"] = iso(NOW - 20)
        entries += [self.codex_event(NOW - 100, 1000, 100, 500), self.codex_event(NOW - 10, 3000, 400, 1500)]
        self.write(self.codex, "fork.jsonl", entries)
        records = reports.read_codex([self.codex], [])
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].tokens, reports.Tokens(1000, 300, 1000))

    def test_html_escapes_names_and_omits_conversation_text(self):
        entry = self.claude_event()
        entry["cwd"] = '<script>alert("x")</script>'
        self.write(self.claude, "conversation.jsonl", [entry])
        html = reports.render_report(reports.collect_report(roots=self.roots, now=NOW))
        self.assertNotIn('<script>', html)
        self.assertIn('&lt;script&gt;', html)
        self.assertNotIn('PRIVATE PROMPT CONTENT', html)
        self.assertIn('not subscription charges', html)

    def test_demo_does_not_read_any_logs_and_labels_sample_data(self):
        with patch.object(reports, "read_codex", side_effect=AssertionError), patch.object(reports, "read_claude", side_effect=AssertionError):
            report = reports.collect_report(now=NOW, demo=True)
        self.assertEqual(len(report.records), 6)
        self.assertEqual({r.effort for r in report.records}, {"medium", "high", "ultra"})
        self.assertIn("DEMO", reports.render_report(report))

    def test_missing_logs_do_not_claim_zero_account_usage(self):
        report = reports.collect_report(roots={"Codex": [self.base / "missing"]}, providers=["Codex"], now=NOW)
        self.assertEqual(report.records, [])
        self.assertIn("does not establish zero account usage", reports.render_report(report))

    def test_custom_prices_validation_and_exact_model_override(self):
        path = self.base / "prices.json"
        path.write_text(json.dumps({"custom": {"input": 2, "output": 3, "cached": .5}}))
        prices = reports.load_prices(path)
        record = reports.Record("Codex", NOW, "s", "p", "custom", reports.Tokens(1000000, 1000000, 1000000))
        self.assertEqual(reports.estimate(record, prices), 5.5)
        for invalid in [{"custom": {"input": -1, "output": 3, "cached": 0}}, {"custom": {"input": True, "output": 3, "cached": 0}}, {"custom": {"input": 2}}, []]:
            path.write_text(json.dumps(invalid))
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                reports.load_prices(path)

    def test_cli_report_end_to_end_offline(self):
        self.write(self.claude, "conversation.jsonl", [self.claude_event(time.time() - 5)])
        output = self.base / "report.html"
        script = Path(__file__).resolve().parents[1] / "usage_tray.py"
        environment = dict(os.environ, CLAUDE_CONFIG_DIR=str(self.base), CODEX_HOME=str(self.base / "no-codex"), LOCALAPPDATA=str(self.base / "appdata"))
        result = subprocess.run([sys.executable, str(script), "--report", "session", "--output", str(output)], capture_output=True, text=True, env=environment, check=True)
        self.assertEqual(Path(result.stdout.strip()), output)
        self.assertIn("3,800", output.read_text())
        self.assertNotIn("PRIVATE PROMPT CONTENT", output.read_text())


if __name__ == "__main__":
    unittest.main()
