"""Bound only app-generated reports, never source histories or explicit exports."""
from dataclasses import dataclass
from pathlib import Path
import re
import stat
import time

from usage_config import application_directory

MAX_REPORTS = 100
MAX_AGE_SECONDS = 30 * 86400
NAME = re.compile(r"usage-\d{8}-\d{6}-[A-Za-z0-9_-]{8}\.(?:txt|html)\Z")


@dataclass(frozen=True)
class RetentionResult:
    removed: int = 0
    failed: bool = False


def _reparse(info):
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & 0x400)


def generated_directory():
    base = application_directory().resolve()
    parent = base / "Reports"
    target = parent / "Generated"
    for folder in (parent, target):
        if folder.exists() and _reparse(folder.lstat()):
            raise OSError("Generated report directory must not be a link/junction.")
    if target.resolve() != base / "Reports" / "Generated":
        raise OSError("Generated report directory is outside the application folder.")
    return target


def prune_reports(keep=None, *, now=None):
    removed = 0
    try:
        root = generated_directory()
        now = time.time() if now is None else now
        candidates = []
        for path in root.iterdir():
            if not NAME.fullmatch(path.name):
                continue
            info = path.lstat()
            if not stat.S_ISREG(info.st_mode) or _reparse(info):
                continue
            # Nonrecursive, fixed generated folder; never follow a child link.
            if path.resolve().parent != root.resolve():
                continue
            candidates.append((info.st_mtime, path.name, path))
        candidates.sort(key=lambda item: (keep is not None and item[2] == Path(keep), item[0], item[1]), reverse=True)
        for index, (modified, _, path) in enumerate(candidates):
            if keep is not None and path == Path(keep):
                continue
            if index >= MAX_REPORTS or modified < now - MAX_AGE_SECONDS:
                path.unlink()
                removed += 1
        return RetentionResult(removed)
    except OSError:
        return RetentionResult(removed, True)
