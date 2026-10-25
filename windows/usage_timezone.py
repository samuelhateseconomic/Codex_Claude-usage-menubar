"""Named system timezone resolution at application boundaries, never fixed offsets."""
from dataclasses import dataclass
import threading
import warnings
from zoneinfo import ZoneInfo

AUTO_TIMEZONE = "auto"
_lock = threading.Lock()


@dataclass(frozen=True)
class TimezoneInfo:
    name: str
    source: str

    def data(self):
        return {"name": self.name, "source": self.source}


def resolve_timezone(preference):
    if preference != AUTO_TIMEZONE:
        ZoneInfo(preference)
        return TimezoneInfo(preference, "manual")
    try:
        from tzlocal import reload_localzone
        # Re-read OS settings for each new context; existing query contexts keep
        # their named zone. Do not expose OS paths/configuration in warnings.
        with _lock, warnings.catch_warnings():
            warnings.simplefilter("ignore")
            name = reload_localzone().key
        ZoneInfo(name)
        return TimezoneInfo(name, "system")
    except (ImportError, OSError, ValueError, LookupError, TypeError, AttributeError):
        return TimezoneInfo("UTC", "fallback")
