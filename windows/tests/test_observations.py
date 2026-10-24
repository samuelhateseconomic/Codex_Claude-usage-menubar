"""Contracts for metadata evidence; these tests do not certify S02 accounting."""
from dataclasses import asdict, replace
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from usage_observations import (
    CanonicalEvent, Counter, SourceRef, extract_claude, extract_codex, group_observations,
)
from usage_records import Record, Tokens
import usage_reports as reports


STAMP = "2026-10-23T20:00:00Z"


def codex_usage(usage=None, **info):
    if usage is not None:
        info["total_token_usage"] = usage
    return {"type": "event_msg", "timestamp": STAMP, "payload": {"type": "token_count", "info": info}}


def codex_header():
    return [
        {"type": "session_meta", "timestamp": STAMP,
         "payload": {"id": "conversation", "cwd": "C:/fixture", "forked_from_thread_id": "parent"}},
        {"type": "turn_context", "payload": {"model": "gpt-5.4", "effort": "ultra", "turn_id": "turn-1"}},
    ]


def claude_usage(output=10):
    return {"type": "assistant", "timestamp": STAMP, "sessionId": "claude-conversation", "requestId": "request",
            "message": {"id": "message", "model": "claude-sonnet-4-6", "usage": {
                "input_tokens": 100, "output_tokens": output, "cache_read_input_tokens": 200,
                "cache_creation_input_tokens": 999,
                "cache_creation": {"ephemeral_5m_input_tokens": 30, "ephemeral_1h_input_tokens": 40}}}}


def numbered(entries):
    return enumerate(entries, 1)


class ObservationTests(unittest.TestCase):
    def test_codex_retains_counter_context_ids_fork_and_source_evidence(self):
        event = codex_usage({"input_tokens": 300, "output_tokens": 20, "cached_input_tokens": 200,
                             "reasoning_output_tokens": 10},
                            last_token_usage={"input_tokens": 100, "output_tokens": 5, "cached_input_tokens": 50},
                            model_context_window=272000)
        event["payload"].update(message_id="message", request_id="request")
        observation, = extract_codex(numbered(codex_header() + [event]), "source-a", generation="fixture-generation")
        self.assertEqual(observation.conversation_id, "conversation")
        self.assertEqual(observation.identity_kind, "provider")
        self.assertEqual(observation.source, SourceRef("source-a", 3, "fixture-generation"))
        self.assertEqual(observation.session_source.line, 1)
        self.assertEqual(observation.context_source.line, 2)
        self.assertEqual((observation.model, observation.effort, observation.turn_id), ("gpt-5.4", "ultra", "turn-1"))
        self.assertEqual((observation.message_id, observation.request_id, observation.fork_parent_id), ("message", "request", "parent"))
        self.assertEqual(observation.cumulative.input.value, 300)  # Still inclusive provider input.
        self.assertEqual(observation.cumulative.cached.value, 200)
        self.assertEqual(observation.cumulative.reasoning.value, 10)
        self.assertEqual(observation.last_usage.input.value, 100)
        self.assertEqual(observation.context_window.value, 272000)  # Capacity is not request context.

    def test_missing_invalid_and_observed_zero_counters_remain_distinct(self):
        for raw in (None, True, False, -1, 1.5, "0", {"secret": "not retained"}):
            with self.subTest(raw=type(raw).__name__):
                observation, = extract_codex(numbered([codex_usage({"input_tokens": raw, "output_tokens": 0})]), "a")
                self.assertEqual(observation.cumulative.input, Counter(state="invalid"))
                self.assertEqual(observation.cumulative.output, Counter(0, "valid"))
                self.assertEqual(observation.cumulative.cached, Counter())
                self.assertNotIn("not retained", json.dumps(asdict(observation)))

    def test_missing_empty_and_invalid_counter_containers_are_preserved(self):
        events = [codex_usage(), codex_usage({}), codex_usage(total_token_usage=None)]
        observations = extract_codex(numbered(events), "a")
        self.assertEqual([o.cumulative.state for o in observations], ["missing", "valid", "invalid"])
        self.assertEqual([o.cumulative.input.state for o in observations], ["missing", "missing", "invalid"])
        missing_info = codex_usage()
        del missing_info["payload"]["info"]
        invalid_info = codex_usage()
        invalid_info["payload"]["info"] = "private payload"
        self.assertEqual(extract_codex(numbered([missing_info]), "a")[0].last_usage.state, "missing")
        self.assertEqual(extract_codex(numbered([invalid_info]), "a")[0].last_usage.state, "invalid")

    def test_invalid_time_and_identity_are_retained_without_stringifying_payloads(self):
        header = codex_header()
        header[0]["payload"]["id"] = {"secret": "do not stringify"}
        event = codex_usage({"input_tokens": 20})
        event["timestamp"] = "bad time"
        observation, = extract_codex(numbered(header + [event]), "a")
        self.assertIsNone(observation.conversation_id)
        self.assertEqual(observation.timestamp_state, "invalid")
        self.assertIsNone(observation.timestamp)
        self.assertIn("invalid_conversation_id", observation.issues)
        self.assertIn("invalid_timestamp", observation.issues)
        self.assertNotIn("do not stringify", json.dumps(asdict(observation)))

    def test_new_codex_context_resets_missing_effort_and_preserves_explicit_null(self):
        entries = codex_header() + [codex_usage({"input_tokens": 100})]
        entries += [{"type": "turn_context", "payload": {"model": "gpt-5.4"}}, codex_usage({"input_tokens": 200})]
        entries += [{"type": "turn_context", "payload": {"effort": None,
                    "collaboration_mode": {"settings": {"reasoning_effort": "high"}}}}, codex_usage({"input_tokens": 300})]
        observations = extract_codex(numbered(entries), "a")
        self.assertEqual([o.effort for o in observations], ["ultra", "unknown", "unknown"])
        self.assertIn("unavailable", observations[-1].effort_source)

    def test_claude_stream_updates_are_evidence_not_summed_or_merged_at_extraction(self):
        observations = extract_claude(numbered([claude_usage(10), claude_usage(40)]), "a", "fixture-label")
        self.assertEqual([o.message_usage.output.value for o in observations], [10, 40])
        self.assertEqual(observations[0].message_id, observations[1].message_id)
        self.assertEqual(observations[0].request_id, "request")
        self.assertEqual(observations[0].message_usage.legacy_write.value, 999)
        self.assertEqual(observations[0].message_usage.write5m.value, 30)
        self.assertEqual(observations[0].message_usage.write1h.value, 40)
        self.assertEqual(observations[0].project_kind, "source_label")

    def test_claude_legacy_ttl_is_not_silently_assigned_during_extraction(self):
        event = claude_usage()
        del event["message"]["usage"]["cache_creation"]
        observation, = extract_claude(numbered([event]), "a")
        self.assertEqual(observation.message_usage.legacy_write.value, 999)
        self.assertEqual(observation.message_usage.write5m.state, "missing")
        self.assertEqual(observation.message_usage.cache_details_state, "missing")

    def test_missing_claude_message_identity_is_kept_as_exclusion_evidence(self):
        event = claude_usage()
        del event["message"]["id"]
        observation, = extract_claude(numbered([event]), "a")
        self.assertIsNone(observation.message_id)
        self.assertIn("missing_message_id", observation.issues)
        self.assertEqual(observation.message_usage.output.value, 10)

    def test_inconsistent_reasoning_is_evidence_until_acceptance_validates_subset(self):
        event = codex_usage({"input_tokens": 100, "output_tokens": 20,
                             "reasoning_output_tokens": 30})
        observation, = extract_codex(numbered([event]), "a")
        self.assertEqual(observation.cumulative.reasoning.value, 30)
        self.assertEqual(observation.cumulative.output.value, 20)
        # Do not erase evidence or clamp it to an invented valid subset.
        missing = codex_usage({"input_tokens": 100, "output_tokens": 20})
        self.assertEqual(extract_codex(numbered([missing]), "a")[0].cumulative.reasoning.state, "missing")

    def test_claude_tool_results_preserve_turn_but_new_user_resets_it(self):
        entries = [{"type": "user", "uuid": "turn-one", "effort": "max", "message": {"content": "private"}},
                   claude_usage(),
                   {"type": "user", "message": {"content": [{"type": "tool_result", "content": "private"}]}},
                   claude_usage(), {"type": "user", "uuid": "turn-two", "message": {"content": "private"}},
                   claude_usage()]
        observations = extract_claude(numbered(entries), "a")
        self.assertEqual([o.effort for o in observations], ["max", "max", "unknown"])
        self.assertEqual([o.turn_id for o in observations], ["turn-one", "turn-one", "turn-two"])
        self.assertEqual([o.context_source.line for o in observations], [1, 1, 5])

    def test_extracted_objects_contain_no_transcript_credentials_or_arbitrary_payload(self):
        secret = "PRIVATE-CONTENT-SENTINEL"
        codex = codex_header() + [codex_usage({"input_tokens": 10})]
        codex[-1]["payload"].update(content=secret, credentials={"token": secret}, arbitrary={"text": secret})
        claude = claude_usage()
        claude["message"]["content"] = [{"text": secret, "thinking": secret}]
        claude["request"] = {"headers": {"Authorization": secret}, "messages": [{"content": secret}]}
        claude["credentials"] = {"accessToken": secret}
        observations = extract_codex(numbered(codex), "a") + extract_claude(numbered([claude]), "b")
        self.assertNotIn(secret, json.dumps([asdict(o) for o in observations]))
        self.assertNotIn(secret, repr(observations))

    def test_grouping_and_evidence_ids_do_not_depend_on_enumeration(self):
        entries = codex_header() + [codex_usage({"input_tokens": 100})]
        a = extract_codex(numbered(entries), "a")
        b = extract_codex(numbered(entries), "b")
        self.assertEqual(group_observations(a + b), group_observations(b + a))
        group, = group_observations(a + b)
        self.assertEqual(len(group.observations), 2)  # Deduplication is not extraction.
        self.assertNotEqual(a[0].source.observation_id, b[0].source.observation_id)
        weak_a = extract_codex(numbered([codex_usage({"input_tokens": 100})]), "root-a/same.jsonl")
        weak_b = extract_codex(numbered([codex_usage({"input_tokens": 100})]), "root-b/same.jsonl")
        self.assertEqual(len(group_observations(weak_a + weak_b)), 2)

    def test_file_seam_uses_physical_lines_and_keeps_existing_record_projection(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            header, context = codex_header()
            # This fixture tests line provenance and ordinary projection, not
            # a fork without inherited baseline (now correctly excluded).
            # Malformed metadata follows usage: S03 conservatively defers the
            # suffix after corruption rather than inventing missing context.
            del header["payload"]["forked_from_thread_id"]
            path = root / "fixture.jsonl"
            path.write_text("\n" + json.dumps(header) + "\n\n" + json.dumps(context) + "\n"
                            + json.dumps(codex_usage({"input_tokens": 100, "output_tokens": 20,
                                                     "cached_input_tokens": 30})) + "\nmalformed\n", encoding="utf-8")
            notices = []
            observation, = reports.read_observations("Codex", [root], notices)
            self.assertEqual(observation.source.line, 5)
            self.assertEqual(observation.context_source.line, 4)
            self.assertEqual(observation.session_source.line, 2)
            self.assertTrue(any("Malformed" in notice for notice in notices))
            record, = reports.read_codex([root], [])
            self.assertEqual(record.tokens, Tokens(70, 20, 30))
            self.assertIs(reports.Tokens, Tokens)
            self.assertIs(reports.Record, Record)

    def test_headless_extraction_and_contracts_do_not_import_gui_or_pricing(self):
        code = """
import sys
import usage_observations as observations
assert not {'usage_reports', 'usage_tray', 'usage_core', 'pystray', 'PIL'} & set(sys.modules)
assert observations.group_observations([]) == ()
"""
        result = subprocess.run([sys.executable, "-c", code], cwd=Path(__file__).resolve().parents[1],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)


class CanonicalContractTests(unittest.TestCase):
    def event(self):
        return CanonicalEvent("conversation-key", "initial-epoch", "provider-event-id", "codex_cumulative_delta",
                              Record("Codex", 1000, "session", "fixture", "model", Tokens(70, 20, 30),
                                     reasoning_tokens=10), (SourceRef("a", 3),))

    def test_event_identity_ignores_copy_provenance_but_distinguishes_epochs(self):
        event = self.event()
        copied = replace(event, sources=(SourceRef("b", 10), SourceRef("a", 3)))
        self.assertEqual(event.event_id, copied.event_id)
        self.assertNotEqual(event.event_id, replace(event, epoch_anchor="post-reset-epoch").event_id)
        self.assertEqual(event.record.tokens.total, 120)  # Reasoning is not added.

    def test_invalid_accepted_facts_and_missing_provenance_are_rejected(self):
        event = self.event()
        for changes in ({"sources": ()}, {"epoch_anchor": ""}, {"source_kind": "claude_message"},
                        {"record": replace(event.record, tokens=Tokens(-1))},
                        {"record": replace(event.record, reasoning_tokens=21)},
                        {"request_context_tokens": 100}, {"record": replace(event.record, timestamp=float("nan"))}):
            with self.subTest(changes=list(changes)), self.assertRaises(ValueError):
                replace(event, **changes)


if __name__ == "__main__":
    unittest.main()
