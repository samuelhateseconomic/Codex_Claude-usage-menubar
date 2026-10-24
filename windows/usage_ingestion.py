"""Offline metadata scans with verified prefixes and explicit completeness.

Raw bytes/parsed payloads exist only during extraction. Results retain allowlisted
observations, counts, static diagnostics and opaque generation fingerprints.
No retained dataset or persistence is implied by a successful earlier scan.
"""
from collections import Counter
from dataclasses import dataclass
import hashlib
import json
import os
import stat
from pathlib import Path

from usage_observations import extract_claude, extract_codex


@dataclass(frozen=True)
class ScanIssue:
    code: str
    message: str
    source_id: str | None = None  # Opaque path identity, never raw source text.
    line: int | None = None
    count: int = 1
    excluded_tokens: int | None = None
    affects_completeness: bool = True


@dataclass(frozen=True)
class ScanResult:
    observations: tuple
    issues: tuple[ScanIssue, ...]
    roots_read: int
    files_discovered: int
    files_read: int

    @property
    def state(self):
        if not self.roots_read or (self.files_discovered and not self.files_read):
            return "failed"
        if any(issue.affects_completeness for issue in self.issues):
            return "partial"
        return "complete" if self.observations else "empty"

    @property
    def issue_counts(self):
        counts = Counter()
        for issue in self.issues:
            counts[issue.code] += issue.count
        return dict(sorted(counts.items()))


def _id(path):
    return hashlib.sha256(os.path.normcase(os.path.abspath(path)).encode("utf-8")).hexdigest()


def discover(roots):
    """mtime is deliberately not an event-time filter; baselines need full history."""
    files, issues, seen, roots_read = [], [], set(), 0
    for root in roots:
        root = Path(root)
        identity = _id(root)
        if identity in seen:
            continue
        seen.add(identity)
        try:
            try:
                root_stat = root.stat()
            except FileNotFoundError:
                issues.append(ScanIssue("missing_root", "Log folder not found; local coverage is unavailable.", identity))
                continue
            if not stat.S_ISDIR(root_stat.st_mode):
                issues.append(ScanIssue("unavailable_root", "Configured log root is not a directory.", identity))
                continue
            # Opening the enumeration, rather than is_dir alone, proves access.
            with os.scandir(root) as entries:
                next(entries, None)
            roots_read += 1
            errors = []
            for directory, subdirs, names in os.walk(root, followlinks=False, onerror=errors.append):
                links = [d for d in subdirs if (Path(directory) / d).is_symlink()]
                for name in links:
                    issues.append(ScanIssue("symlink_skipped", "A linked log folder was excluded from local coverage.", _id(Path(directory) / name)))
                subdirs[:] = sorted(d for d in subdirs if d not in links)
                for name in sorted(names):
                    path = Path(directory) / name
                    if path.suffix == ".jsonl":
                        if path.is_symlink():
                            issues.append(ScanIssue("symlink_skipped", "A linked log file was excluded from local coverage.", _id(path)))
                        else:
                            files.append(path)
            if errors:
                issues.append(ScanIssue("unreadable_directory", "Some log folders could not be enumerated.", identity, count=len(errors)))
        except OSError:
            issues.append(ScanIssue("unavailable_root", "A log root could not be read; check folder access.", identity))
    if not seen:
        issues.append(ScanIssue("no_roots", "No local log roots are configured."))
    unique = {_id(path): path for path in files}
    return tuple(unique[key] for key in sorted(unique)), issues, roots_read


class SourceChanged(Exception):
    pass


def _identity(stat):
    return stat.st_dev, stat.st_ino


def _read_prefix_once(path):
    """Verify the same initial-size bytes twice and the current path identity.

    Appends are allowed only outside the captured prefix. In-place mutation,
    truncation and replacement cause a bounded retry of the entire file.
    """
    with path.open("rb", buffering=0) as stream:
        before = os.fstat(stream.fileno())
        data = stream.read(before.st_size)
        if len(data) != before.st_size:
            raise SourceChanged()
        stream.seek(0)
        verified = stream.read(before.st_size)
        after = os.fstat(stream.fileno())
        current = path.stat()
        if (data != verified or after.st_size < before.st_size or current.st_size < before.st_size
                or _identity(before) != _identity(after) or _identity(before) != _identity(current)
                or current.st_size != after.st_size or current.st_mtime_ns != after.st_mtime_ns
                or (after.st_size == before.st_size and before.st_mtime_ns != after.st_mtime_ns)):
            raise SourceChanged()
        fingerprint = hashlib.sha256(repr((_identity(before), before.st_size)).encode())
        fingerprint.update(data)
        return data, fingerprint.hexdigest(), after.st_size > before.st_size


def verified_prefix(path):
    path = Path(path)
    for attempt in range(2):
        try:
            data, generation, appended = _read_prefix_once(path)
            issues = []
            if attempt:
                issues.append(ScanIssue("source_changed_retried", "A changed log generation was reread consistently.", _id(path), affects_completeness=False))
            if appended:
                issues.append(ScanIssue("append_deferred", "A log grew during the scan; only its verified initial prefix was accepted.", _id(path)))
            return data, generation, issues
        except SourceChanged:
            continue
        except OSError:
            return None, None, [ScanIssue("unreadable_file", "A log file could not be read; check file access and retry.", _id(path))]
    return None, None, [ScanIssue("unstable_file", "A log kept changing or was replaced; no mixed generation was accepted. Retry the scan.", _id(path))]


def parsed_entries(data, path, issues, conservative=False):
    # Split on physical LF only; JSON strings cannot contain literal LF.
    parts = data.split(b"\n")
    unsafe_suffix = False
    for index, raw in enumerate(parts, 1):
        if not raw.strip():
            continue
        final = index == len(parts) and not data.endswith(b"\n")
        try:
            decoded = raw.decode("utf-8-sig" if index == 1 else "utf-8")
            if not decoded.strip():
                continue
            entry = json.loads(decoded)
            if not isinstance(entry, dict):
                raise ValueError()
        except (ValueError, UnicodeError, RecursionError):
            if final:
                issues.append(ScanIssue("incomplete_final_line", "Malformed or incomplete records: an unfinished final line was deferred until complete.", _id(path), index))
            else:
                issues.append(ScanIssue("malformed_record", "Malformed complete record skipped; excluded token amount is unknown.", _id(path), index))
            unsafe_suffix = True
            continue
        if conservative and unsafe_suffix:
            issues.append(ScanIssue("untrusted_suffix", "Records after malformed metadata were deferred; repair the source and rescan. Excluded tokens are unknown.", _id(path), index))
            continue
        yield index, entry


def observations_from_prefix(provider, path, data, generation):
    """Extract one verified prefix; raw bytes are never returned or retained."""
    if provider not in ("Codex", "Claude"):
        raise ValueError("Unsupported observation provider")
    path = Path(path)
    issues = []
    entries = parsed_entries(data, path, issues, conservative=True)
    if provider == "Codex":
        extracted = extract_codex(entries, str(path.resolve()), generation)
    else:
        extracted = extract_claude(entries, str(path.resolve()), path.parent.name, generation)
    for observation in extracted:
        for code in sorted(set(observation.issues)):
            issues.append(ScanIssue(code, "Usage metadata is unavailable or invalid (" + code + ").", _id(path), observation.source.line))
        cumulative = observation.cumulative
        has_cumulative = cumulative.state == "invalid" or any(
            c.state != "missing" for c in (cumulative.input, cumulative.output, cumulative.cached))
        counters = (observation.message_usage if provider == "Claude" else
                    cumulative if has_cumulative else observation.last_usage)
        core = (counters.input, counters.output, counters.cached)
        if provider == "Claude":
            detailed = counters.cache_details_state == "valid" and any(
                c.state != "missing" for c in (counters.write5m, counters.write1h))
            core += (counters.write5m, counters.write1h) if detailed else (counters.legacy_write,)
            if counters.cache_details_state == "invalid":
                issues.append(ScanIssue("invalid_cache_metadata", "Claude cache-write details are invalid; their amount is unknown.", _id(path), observation.source.line))
        for state, code in (("missing", "missing_counter_metadata"), ("invalid", "invalid_counter_metadata")):
            if any(counter.state == state for counter in core):
                issues.append(ScanIssue(code, "Required token counter metadata is " + state + "; excluded amounts stay unknown.", _id(path), observation.source.line))
    return tuple(extracted), tuple(issues)


def scan_observations(provider, roots):
    if provider not in ("Codex", "Claude"):
        raise ValueError("Unsupported observation provider")
    paths, issues, roots_read = discover(roots)
    observations, files_read = [], 0
    for path in paths:
        data, generation, file_issues = verified_prefix(path)
        issues.extend(file_issues)
        if data is None:
            continue
        files_read += 1
        extracted, extracted_issues = observations_from_prefix(provider, path, data, generation)
        observations.extend(extracted)
        issues.extend(extracted_issues)
    return ScanResult(tuple(observations), tuple(issues), roots_read, len(paths), files_read)
