r"""Reproduce accounting review findings without reading user histories.

Run from the repository: windows\.venv\Scripts\python.exe docs\review_accounting_probes.py
Prints observed versus expected results; does not alter application source files.
"""
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "windows"))
import usage_reports as reports


def main():
    now = datetime(2026, 10, 23, 20, tzinfo=timezone.utc).timestamp()

    def stamp(offset):
        return datetime.fromtimestamp(now + offset, timezone.utc).isoformat()

    def counter(value, offset):
        return {"type": "event_msg", "timestamp": stamp(offset), "payload": {
            "type": "token_count", "info": {"total_token_usage": {
                "input_tokens": value, "output_tokens": 0, "cached_input_tokens": 0}}}}

    def write(path, events):
        header = [
            {"type": "session_meta", "timestamp": stamp(-100), "payload": {"id": "same-session", "cwd": "fixture"}},
            {"type": "turn_context", "payload": {"model": "gpt-6.1-sol"}},
        ]
        path.write_text("\n".join(json.dumps(event) for event in header + events), encoding="utf-8")

    scratch = ROOT / "windows" / "build"
    scratch.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="review-probes-", dir=scratch) as directory:
        root = Path(directory)
        cases = [
            ("overlap-truncated-first", 200, {
                "a.jsonl": [counter(200, -10)],
                "b.jsonl": [counter(100, -20), counter(200, -10)]}),
            ("overlap-complete-first", 200, {
                "a.jsonl": [counter(100, -20), counter(200, -10)],
                "b.jsonl": [counter(200, -10)]}),
            ("reset-repeat-excluding-ambiguous-interval", 250, {
                "a.jsonl": [counter(100, -40), counter(200, -30), counter(50, -20), counter(100, -10)]}),
        ]
        for label, expected, files in cases:
            case_root = root / label
            case_root.mkdir()
            for name, events in files.items():
                write(case_root / name, events)
            notices = []
            observed = sum(record.tokens.total for record in reports.read_codex([case_root], notices))
            print(json.dumps({"case": label, "expected_tokens": expected, "observed_tokens": observed,
                              "matches_expected": observed == expected, "notices": notices}))


if __name__ == "__main__":
    main()
