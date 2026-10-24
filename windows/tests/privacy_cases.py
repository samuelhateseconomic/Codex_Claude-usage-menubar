"""Synthetic privacy fixtures shared by regression tests and the pre-S08 probe.

No real histories, credentials, provider requests, or GUI dependencies.
"""
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile

import usage_reports as reports
from usage_core import parse_codex
from usage_hub import Dataset, HubService, identifier

NOW = datetime(2026, 10, 24, 20, tzinfo=timezone.utc).timestamp()
STAMP = datetime.fromtimestamp(NOW - 60, timezone.utc).isoformat()
SECRET = "SYNTHETIC-PRIVATE-CONTENT-DO-NOT-RETAIN"


def log_entries(provider):
    private = {"content": SECRET, "credentials": {"accessToken": SECRET},
               "request": {"headers": {"Authorization": SECRET}}, "arbitrary": SECRET}
    if provider == "Codex":
        return [
            {"type": "session_meta", "timestamp": STAMP,
             "payload": {"id": "fixture-codex", "cwd": "C:/synthetic-project", **private}},
            {"type": "turn_context", "payload": {"model": "gpt-5.4", "turn_id": "fixture-turn",
                                                   "effort": "high", **private}},
            {"type": "event_msg", "timestamp": STAMP, "payload": {"type": "token_count",
             "info": {"total_token_usage": {"input_tokens": 100, "output_tokens": 20,
                                             "cached_input_tokens": 30}}, **private}},
        ]
    return [
        {"type": "user", "uuid": "fixture-turn", "effort": "high",
         "message": {"content": SECRET}, **private},
        {"type": "assistant", "timestamp": STAMP, "sessionId": "fixture-claude",
         "requestId": "fixture-request", "cwd": "C:/synthetic-project", **private,
         "message": {"id": "fixture-message", "model": "claude-sonnet-4-6",
                     "content": [{"text": SECRET, "thinking": SECRET}],
                     "usage": {"input_tokens": 100, "output_tokens": 20}}},
    ]


def read_fixture(provider, entries):
    with tempfile.TemporaryDirectory(prefix="usage-privacy-") as directory:
        path = Path(directory) / "fixture.jsonl"
        path.write_text("\n".join(json.dumps(e) for e in entries) + "\n", encoding="utf-8")
        notices = []
        reader = reports.read_codex if provider == "Codex" else reports.read_claude
        records = reader([Path(directory)], notices)
        return records, notices


def report_for(records, notices=()):
    return reports.Report(records, {p: (NOW - 3600, "Synthetic fixture")
                                   for p in sorted({r.provider for r in records})}, NOW, list(notices))


def public_outputs(records, notices=()):
    """Exercise existing report and development DTO boundaries, not proposed APIs."""
    report = report_for(records, notices)
    service = HubService(roots={}, clock=lambda: NOW)
    service.dataset = Dataset("synthetic-privacy", NOW, tuple(records), tuple(notices))
    outputs = [json.dumps([asdict(r) for r in records]), reports.render_report(report),
               reports.render_text_report(report), json.dumps(service.query({}))]
    for record in records:
        outputs.append(json.dumps(service.query({"conversation": identifier(record.provider, record.session)})))
    return outputs


def malformed_metadata_leaks(provider):
    # Nested content in a malformed metadata field must not be coerced into text.
    fields = (["session", "project", "model", "turn_id"] if provider == "Codex"
              else ["session", "model", "turn_id"])
    leaks = []
    for field in fields:
        entries = deepcopy(log_entries(provider))
        invalid = {"content": SECRET}
        if provider == "Codex":
            target, key = ((entries[0]["payload"], "id") if field == "session" else
                           (entries[0]["payload"], "cwd") if field == "project" else
                           (entries[1]["payload"], "model") if field == "model" else
                           (entries[1]["payload"], "turn_id"))
        else:
            target, key = ((entries[1], "sessionId") if field == "session" else
                           (entries[1]["message"], "model") if field == "model" else
                           (entries[0], "uuid"))
        target[key] = invalid
        records, notices = read_fixture(provider, entries)
        if any(SECRET in output for output in public_outputs(records, notices)):
            leaks.append(field)
    return leaks


def live_label_has_controls():
    payload = {"rateLimitsByLimitId": {"fixture": {"limitName": "Fixture\x1b[2J\x9d52;c;fixture\x07",
               "primary": {"usedPercent": 20, "windowDurationMins": 300}}}}
    window, = parse_codex(payload).windows
    return any(not c.isprintable() for c in window.text())


def known_gap_results():
    return {
        "legacy_codex_invalid_metadata": malformed_metadata_leaks("Codex"),
        "legacy_claude_invalid_metadata": malformed_metadata_leaks("Claude"),
        "live_codex_terminal_controls": ["limit_label"] if live_label_has_controls() else [],
    }
