from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import usage_reports as reports
import usage_tray
from usage_core import Snapshot, Window
from usage_time import local_datetime, resolve_range

ZONE = "America/Los_Angeles"


def utc(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


def message(when, identifier):
    return {"type": "assistant", "timestamp": when, "sessionId": "synthetic",
            "message": {"id": identifier, "model": "claude-sonnet-4-6", "usage": {
                "input_tokens": 10, "output_tokens": 0, "cache_read_input_tokens": 0,
                "cache_creation_input_tokens": 0}}}


class RangeTests(unittest.TestCase):
    def test_midnight_and_month_change_use_named_zone(self):
        before = resolve_range("month", utc("2026-11-01T06:59:59Z"), timezone=ZONE)
        after = resolve_range("month", utc("2026-11-01T07:00:00Z"), timezone=ZONE)
        self.assertEqual(before.start, utc("2026-10-01T07:00:00Z"))
        self.assertEqual(after.start, after.end)
        self.assertEqual(after.start, utc("2026-11-01T07:00:00Z"))
        today = resolve_range("today", utc("2026-10-24T06:59:59Z"), timezone=ZONE)
        self.assertEqual(today.start, utc("2026-10-23T07:00:00Z"))
        self.assertEqual(resolve_range("today", utc("2026-10-24T07:00:00Z"), timezone=ZONE).start,
                         utc("2026-10-24T07:00:00Z"))

    def test_spring_dst_day_has_23_hours(self):
        a = resolve_range("today", utc("2026-03-08T20:00:00Z"), timezone=ZONE)
        b = resolve_range("today", utc("2026-03-09T20:00:00Z"), timezone=ZONE)
        self.assertEqual(a.start, utc("2026-03-08T08:00:00Z"))
        self.assertEqual(b.start - a.start, 23 * 3600)

    def test_fall_dst_day_has_25_hours_and_both_folds_share_day(self):
        a = resolve_range("today", utc("2026-11-01T08:30:00Z"), timezone=ZONE)
        folded = resolve_range("today", utc("2026-11-01T09:30:00Z"), timezone=ZONE)
        b = resolve_range("today", utc("2026-11-02T20:00:00Z"), timezone=ZONE)
        self.assertEqual(a.start, utc("2026-11-01T07:00:00Z"))
        self.assertEqual(a.start, folded.start)
        self.assertEqual(b.start - a.start, 25 * 3600)
        self.assertEqual(local_datetime(a.end, ZONE).hour, local_datetime(folded.end, ZONE).hour)
        self.assertNotEqual(local_datetime(a.end, ZONE).utcoffset(), local_datetime(folded.end, ZONE).utcoffset())

    def test_last_seven_days_is_168_hours_across_both_dst_transitions(self):
        for now in (utc("2026-03-10T20:00:00Z"), utc("2026-11-03T20:00:00Z")):
            context = resolve_range("week", now, timezone=ZONE)
            self.assertEqual(context.end - context.start, 604800)
            self.assertIn("168", context.label)

    def test_boundaries_are_half_open(self):
        context = resolve_range("week", 1000000, timezone="UTC")
        self.assertTrue(context.contains(context.start))
        self.assertTrue(context.contains(context.end - 0.001))
        self.assertFalse(context.contains(context.start - 0.001))
        self.assertFalse(context.contains(context.end))

    def test_invalid_timezone_period_or_end_fails_explicitly(self):
        with self.assertRaises(ZoneInfoNotFoundError):
            resolve_range("today", 1000000, timezone="Not/A_Timezone")
        with self.assertRaises(ValueError):
            resolve_range("arbitrary", 1000000)
        for value in (float("nan"), float("inf"), True, "now"):
            with self.assertRaises(ValueError):
                resolve_range("today", value)

    def test_provider_specific_sessions_keep_distinct_starts_and_one_end(self):
        now = utc("2026-10-23T20:00:00Z")
        codex = Snapshot("Codex", [Window("5h", 20, now + 3600, 300)])
        claude = Snapshot("Claude", [Window("5h", 20, now + 7200, 300)])
        report = reports.collect_report("session", now=now, demo=True,
                                        snapshots={"Codex": codex, "Claude": claude}, timezone=ZONE)
        self.assertEqual(report.ranges["Codex"].start, now - 14400)
        self.assertEqual(report.ranges["Claude"].start, now - 10800)
        self.assertEqual({r.end for r in report.ranges.values()}, {now})
        self.assertEqual({r.timezone for r in report.ranges.values()}, {ZONE})

    def test_report_captures_clock_once_and_renderers_do_not_recompute_it(self):
        now = utc("2026-10-23T20:00:00Z")
        with patch.object(reports.time, "time", side_effect=[now, AssertionError("second clock")]) as clock:
            report = reports.collect_report("month", demo=True, timezone="UTC")
            reports.render_text_report(report)
            reports.render_report(report)
        self.assertEqual(clock.call_count, 1)
        self.assertEqual(report.end, now)
        self.assertEqual({r.end for r in report.ranges.values()}, {now})

    def test_real_collection_excludes_exact_end_and_preserves_daily_reconciliation(self):
        now = utc("2026-10-24T08:00:00Z")
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            entries = [message("2026-10-23T06:59:59Z", "prior"),
                       message("2026-10-23T07:00:00Z", "start"),
                       message("2026-10-24T06:59:59Z", "day-one"),
                       message("2026-10-24T07:00:00Z", "day-two"),
                       message("2026-10-24T08:00:00Z", "end"),
                       message("2026-10-24T08:00:01Z", "future")]
            (root / "fixture.jsonl").write_text("".join(json.dumps(e) + "\n" for e in entries), encoding="utf-8")
            report = reports.collect_report("month", providers=["Claude"], roots={"Claude": [root]}, now=now, timezone=ZONE)
            # Month includes the earlier day; exact end and future are excluded.
            self.assertEqual(sum(r.tokens.total for r in report.records), 40)
            days = {}
            for record in report.records:
                day = local_datetime(record.timestamp, report.timezone).date().isoformat()
                days[day] = days.get(day, 0) + record.tokens.total
            self.assertEqual(days, {"2026-10-22": 10, "2026-10-23": 20, "2026-10-24": 10})
            self.assertEqual(sum(days.values()), sum(r.tokens.total for r in report.records))
            today = reports.collect_report("today", providers=["Claude"], roots={"Claude": [root]}, now=now, timezone=ZONE)
            self.assertEqual(sum(r.tokens.total for r in today.records), 10)
            for render in (reports.render_text_report, reports.render_report):
                text = render(report)
                self.assertIn(ZONE, text)
                self.assertIn("end exclusive", text)
                self.assertIn("2026-10-22", text)

    def test_cli_zone_validation_and_tray_forwarding(self):
        with patch.object(sys, "argv", ["usage_tray.py", "--demo", "--timezone", "UTC"]), \
             patch.object(usage_tray, "run_tray") as tray:
            self.assertEqual(usage_tray.main(), 0)
            self.assertEqual(tray.call_args.args[-1], "UTC")
        process = subprocess.run([sys.executable, str(Path(usage_tray.__file__)), "--report", "today", "--demo", "--timezone", "Invalid/Zone"],
                                 capture_output=True, text=True)
        self.assertEqual(process.returncode, 2)
        self.assertIn("Unknown report timezone", process.stderr)
        self.assertNotIn("Traceback", process.stderr)


if __name__ == "__main__":
    unittest.main()
