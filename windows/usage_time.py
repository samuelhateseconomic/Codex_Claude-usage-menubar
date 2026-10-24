"""Captured named-zone ranges. UTC instants use start-inclusive/end-exclusive bounds."""
from dataclasses import dataclass
from datetime import datetime
import math
from zoneinfo import ZoneInfo

DEFAULT_TIMEZONE = "America/Los_Angeles"


@dataclass(frozen=True)
class RangeContext:
    start: float
    end: float
    timezone: str
    label: str
    boundary_policy: str = "utc-half-open-v1"

    def contains(self, instant):
        return self.start <= instant < self.end


def resolve_range(period, now, snapshot=None, timezone=DEFAULT_TIMEZONE):
    if isinstance(now, bool) or not isinstance(now, (int, float)) or not math.isfinite(now):
        raise ValueError("Range end must be a finite UTC timestamp.")
    zone = ZoneInfo(timezone)  # Invalid or unavailable zones fail explicitly.
    local = datetime.fromtimestamp(now, zone)
    if period in ("today", "month"):
        start = local.replace(hour=0, minute=0, second=0, microsecond=0, fold=0)
        if period == "month":
            start = start.replace(day=1)
        label = "Today" if period == "today" else "Month to date"
        return RangeContext(start.timestamp(), now, timezone, f"{label} ({timezone})")
    if period == "week":
        return RangeContext(now - 168 * 3600, now, timezone, "Last 7 days (trailing 168 hours)")
    if period != "session":
        raise ValueError("Unsupported report period.")
    if snapshot:
        for window in snapshot.windows:
            if (window.duration_minutes == 300 and window.resets_at
                    and math.isfinite(window.resets_at) and now < window.resets_at <= now + 18000):
                return RangeContext(window.resets_at - 18000, now, timezone,
                                    "Current 5-hour quota session (provider reset time)")
    return RangeContext(now - 18000, now, timezone,
                        "Last 5 hours (current quota-session boundary unavailable)")


def local_datetime(instant, timezone=DEFAULT_TIMEZONE):
    return datetime.fromtimestamp(instant, ZoneInfo(timezone))
