"""Safe categorized report outcomes; never display exception/source contents."""
from dataclasses import dataclass
import errno


@dataclass(frozen=True)
class ReportFailure:
    category: str
    phase: str
    message: str


def report_failure(exc, phase):
    if phase == "open":
        return ReportFailure("open_failed", phase, "Report saved, but could not open its viewer. Open the saved file directly.")
    if isinstance(exc, PermissionError):
        return ReportFailure("permission_denied", phase, "Report failed: check access to the local log and report folders.")
    if isinstance(exc, OSError):
        if exc.errno == errno.ENOSPC:
            return ReportFailure("disk_full", phase, "Report failed: free disk space and try again.")
        return ReportFailure("io_error", phase, "Report failed: a local file could not be read or written. Check folder availability.")
    if isinstance(exc, (ValueError, TypeError, OverflowError)):
        return ReportFailure("invalid_data", phase, "Report failed: unsupported local data or calculation bounds. Run diagnostics and check configuration.")
    return ReportFailure("unexpected_local", phase, "Report failed unexpectedly. Run diagnostics and check your app version.")
