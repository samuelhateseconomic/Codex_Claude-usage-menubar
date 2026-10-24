"""Provider scheduling and installation ownership, independent of GUI/reports."""
from dataclasses import dataclass, replace
from datetime import datetime
import os
from pathlib import Path
import threading
import time

from usage_config import application_directory
from usage_core import RateLimited, Snapshot, UsageError

MIN_INTERVAL = 300


@dataclass(frozen=True)
class ProviderView:
    provider: str
    snapshot: Snapshot | None
    category: str
    error: str
    phase: str
    failures: int
    retry_at: float | None  # Derived UTC display time, never a persisted monotonic deadline.


class ProviderState:
    def __init__(self, provider, fetch, *, stop=None, changed=None, monotonic=None, wall_time=None):
        self.provider, self.fetch = provider, fetch
        self.snapshot = None
        self.error = "Waiting for first refresh…"
        self.category = "waiting"
        self.next_check = 0.0
        self.failures = 0
        self.refreshing = False
        self.lock = threading.Lock()
        self.fetch_lock = threading.Lock()
        self.stop = stop if stop is not None else threading.Event()
        self.changed = changed or (lambda: None)
        self.monotonic = monotonic or time.monotonic
        self.wall_time = wall_time or time.time

    def view(self):
        with self.lock:
            remaining = max(0, self.next_check - self.monotonic())
            phase = "stopped" if self.stop.is_set() else "refreshing" if self.refreshing else "cooldown" if remaining else "due"
            return ProviderView(self.provider, self.snapshot, self.category, self.error, phase,
                                self.failures, self.wall_time() + remaining if remaining else None)

    def delay(self):
        with self.lock:
            return max(0, self.next_check - self.monotonic())

    def refresh(self, now=None):
        if self.stop.is_set() or not self.fetch_lock.acquire(blocking=False):
            return False
        try:
            with self.lock:
                if self.stop.is_set() or (self.monotonic() if now is None else now) < self.next_check:
                    return False
                self.refreshing = True
            self.changed()
            try:
                snapshot = self.fetch()
                if not isinstance(snapshot, Snapshot) or snapshot.provider != self.provider:
                    raise UsageError("Provider returned an unsupported snapshot.", category="unsupported_response")
                # Snapshot is frozen, but legacy adapters use a mutable windows list.
                snapshot = replace(snapshot, windows=tuple(snapshot.windows))
                with self.lock:
                    if not self.stop.is_set():
                        self.snapshot = snapshot
                        self.error = ""
                        self.category = "blocked" if snapshot.blocked else "success"
                        self.failures = 0
                        self.next_check = self.monotonic() + MIN_INTERVAL
            except Exception as exc:
                with self.lock:
                    if not self.stop.is_set():
                        self.failures = min(4, self.failures + 1)
                        self.category = exc.category if isinstance(exc, UsageError) else "unexpected_local"
                        self.error = str(exc) if isinstance(exc, UsageError) else "Unexpected provider error. Update the app or check your CLI installation."
                        delay = max(MIN_INTERVAL * 2 ** (self.failures - 1), exc.retry_after if isinstance(exc, RateLimited) else 0)
                        self.next_check = self.monotonic() + delay
            finally:
                with self.lock:
                    self.refreshing = False
                self.changed()
            return True
        finally:
            self.fetch_lock.release()

    def lines(self):
        view = self.view()
        lines = [view.provider]
        if view.snapshot:
            lines += [window.text() for window in view.snapshot.windows]
            if view.snapshot.note:
                lines.append(view.snapshot.note)
            checked = datetime.fromtimestamp(view.snapshot.checked_at).strftime("%H:%M:%S")
            lines.append(("Last successful check " if view.error else "Updated ") + checked)
        if view.category == "blocked":
            lines.append("blocked: provider reports included usage is blocked.")
        if view.error:
            lines.append(f"{view.category}: {view.error}")
            if view.snapshot:
                lines.append("Showing previous data; it may be out of date.")
        if view.phase == "refreshing":
            lines.append("Checking provider…")
        elif view.retry_at is not None:
            try:
                retry = datetime.fromtimestamp(view.retry_at).strftime("%H:%M:%S")
            except (ValueError, OverflowError, OSError):
                retry = "outside the supported display range"
            lines.append("Next eligible check " + retry + " (cooldown)")
        return lines


class PollingRuntime:
    """One worker and wake signal per provider; changed is a notification only."""
    def __init__(self, fetchers, *, stop=None, changed=None):
        self.stop = stop if stop is not None else threading.Event()
        self.states = tuple(ProviderState(p, fetch, stop=self.stop, changed=changed) for p, fetch in fetchers.items())
        self.wakes = tuple(threading.Event() for _ in self.states)
        self.threads = []
        self.lifecycle_lock = threading.Lock()
        self.started = False

    def _worker(self, state, wake):
        while not self.stop.is_set():
            # Clear before checking eligibility: a concurrent wake remains set
            # for this provider rather than being consumed by another worker.
            wake.clear()
            state.refresh()
            if self.stop.is_set():
                break
            wake.wait(min(86400, state.delay()))

    def start(self):
        with self.lifecycle_lock:
            if self.started or self.stop.is_set():
                return
            self.started = True
            for state, wake in zip(self.states, self.wakes):
                worker = threading.Thread(target=self._worker, args=(state, wake), daemon=True, name="usage-" + state.provider)
                self.threads.append(worker)
                worker.start()

    def refresh(self):
        for wake in self.wakes:
            wake.set()  # Eligibility and per-provider locks still apply.

    def close(self, timeout=30):
        self.stop.set()
        self.refresh()
        deadline = time.monotonic() + timeout
        for worker in self.threads:
            if worker is not threading.current_thread():
                worker.join(max(0, deadline - time.monotonic()))
        return not any(worker.is_alive() for worker in self.threads)


class AlreadyRunning(Exception):
    pass


class RuntimeOwner:
    """OS-owned byte lock per local application-data installation, no PID killing.

    The file is deliberately never deleted: unlinking a lock file can admit a
    second owner through a new file identity while the first handle is locked.
    """
    def __init__(self, path=None):
        self.path = application_directory() / "runtime.lock" if path is None else Path(path)
        self.stream = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        stream = self.path.open("a+b")
        try:
            stream.seek(0, os.SEEK_END)
            if stream.tell() == 0:
                stream.write(b"0")
                stream.flush()
            stream.seek(0)
            deadline = time.monotonic() + .25
            while True:
                try:
                    if os.name == "nt":
                        import msvcrt
                        msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise
                    time.sleep(.025)
        except OSError:
            stream.close()
            raise AlreadyRunning("Usage Tray is already running for this application-data folder. Use its tray menu or quit it before restarting.") from None
        self.stream = stream
        return self

    def __exit__(self, *_):
        if self.stream is not None:
            # Closing releases the lock on normal exit; the OS does the same on crash.
            self.stream.close()
            self.stream = None
