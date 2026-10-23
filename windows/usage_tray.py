"""Windows tray application for Codex and Claude subscription usage."""
from __future__ import annotations

import argparse
from datetime import datetime
import json
import threading
import time
import webbrowser

from usage_core import RateLimited, UsageError, demo_snapshot, fetch_claude, fetch_codex


PROVIDERS = {"Codex": fetch_codex, "Claude": fetch_claude}


class ProviderState:
    def __init__(self, provider, fetch):
        self.provider = provider
        self.fetch = fetch
        self.snapshot = None
        self.error = "Waiting for first refresh…"
        self.next_check = 0.0
        self.failures = 0
        self.lock = threading.Lock()
        self.fetch_lock = threading.Lock()

    def refresh(self, now=None):
        now = time.monotonic() if now is None else now
        if not self.fetch_lock.acquire(blocking=False):
            return
        try:
            if now < self.next_check:
                return
            try:
                snapshot = self.fetch()
                with self.lock:
                    self.snapshot = snapshot
                    self.error = ""
                    self.failures = 0
                    self.next_check = time.monotonic() + 300
            except Exception as exc:
                with self.lock:
                    self.failures = min(4, self.failures + 1)
                    self.error = str(exc) if isinstance(exc, UsageError) else "Unexpected provider error. Update the app or check your CLI installation."
                    delay = max(300 * 2 ** (self.failures - 1), exc.retry_after if isinstance(exc, RateLimited) else 0)
                    self.next_check = time.monotonic() + delay
        finally:
            self.fetch_lock.release()

    def lines(self):
        with self.lock:
            lines = [self.provider]
            if self.snapshot:
                lines += [window.text() for window in self.snapshot.windows]
                if self.snapshot.note:
                    lines.append(self.snapshot.note)
                checked = datetime.fromtimestamp(self.snapshot.checked_at).strftime("%H:%M:%S")
                lines.append(("Last successful check " if self.error else "Updated ") + checked)
            if self.error:
                lines.append(self.error)
                if self.snapshot:
                    lines.append("Showing previous data; it may be out of date.")
            return lines


def run_tray(demo=False, selected="both"):
    try:
        import pystray
        from PIL import Image, ImageDraw
    except ImportError:
        raise SystemExit("Tray dependencies missing. Run: python -m pip install -r requirements.txt") from None

    states = [ProviderState(name, (lambda p=name: demo_snapshot(p)) if demo else fetch)
              for name, fetch in PROVIDERS.items() if selected == "both" or name.lower() == selected]
    stop = threading.Event()
    wake = threading.Event()
    render_lock = threading.Lock()

    def menu_items():
        if demo:
            yield pystray.MenuItem("DEMO — sample usage", None, enabled=False)
        for state in states:
            for line in state.lines():
                yield pystray.MenuItem(line, None, enabled=False)
            yield pystray.Menu.SEPARATOR
        yield pystray.MenuItem("Refresh (five-minute minimum)", lambda icon, item: wake.set())
        yield pystray.MenuItem("Codex usage page", lambda icon, item: webbrowser.open("https://chatgpt.com/codex/settings/usage"))
        yield pystray.MenuItem("Claude usage page", lambda icon, item: webbrowser.open("https://claude.ai/settings/usage"))
        yield pystray.MenuItem("Quit", quit_app)

    def quit_app(icon, item):
        stop.set()
        wake.set()
        icon.stop()

    def image():
        img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.rounded_rectangle((2, 2, 61, 61), radius=14, fill="#17243b")
        for i, state in enumerate(states):
            with state.lock:
                windows = state.snapshot.windows if state.snapshot else []
                remaining = min((w.remaining for w in windows), default=0)
                color = "#8793a5" if state.error else ("#55dba6" if remaining > 50 else "#f1b858" if remaining > 20 else "#ff6978")
            y = 17 + i * 22
            draw.rounded_rectangle((11, y, 53, y + 12), radius=3, fill="#39445a")
            if remaining > 0:
                draw.rounded_rectangle((11, y, 11 + max(6, 42 * remaining / 100), y + 12), radius=3, fill=color)
            else:
                draw.ellipse((12, y + 2, 20, y + 10), fill=color)
        return img

    icon = pystray.Icon("UsageTray", image(), "Usage Tray" + (" — DEMO" if demo else ""), pystray.Menu(menu_items))

    def worker(state):
        while not stop.is_set():
            state.refresh()
            if stop.is_set():
                break
            with render_lock:
                icon.icon = image()
                icon.update_menu()
            # Each provider runs independently, so a slow CLI cannot block Claude.
            wake.wait(1)
            wake.clear()

    def setup(tray_icon):
        tray_icon.visible = True
        for state in states:
            threading.Thread(target=worker, args=(state,), daemon=True).start()

    icon.run(setup=setup)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", choices=("both", "codex", "claude"), default="both")
    parser.add_argument("--demo", action="store_true", help="Use clearly labeled sample data without reading credentials")
    parser.add_argument("--once", action="store_true", help="Print one usage snapshot as JSON, without a tray")
    args = parser.parse_args()
    if args.once:
        results = []
        failed = False
        for name, fetch in PROVIDERS.items():
            if args.provider not in ("both", name.lower()):
                continue
            try:
                snapshot = demo_snapshot(name) if args.demo else fetch()
                results.append(snapshot.to_dict())
            except Exception as exc:
                failed = True
                message = str(exc) if isinstance(exc, UsageError) else "Unexpected provider error; check your CLI installation."
                results.append({"provider": name, "error": message})
        print(json.dumps(results, indent=2, ensure_ascii=False))
        return 1 if failed else 0
    run_tray(args.demo, args.provider)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
