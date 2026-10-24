"""Windows tray application for Codex and Claude subscription usage."""
from __future__ import annotations

import argparse
from dataclasses import replace
from datetime import datetime
import json
from pathlib import Path
import threading
import time
import webbrowser
import os
import subprocess
import sys

from usage_core import RateLimited, UsageError, demo_snapshot, fetch_claude, fetch_codex
from usage_config import (SCHEMA_VERSION, SettingsError, application_directory, effective_settings,
                          load_settings, save_settings, settings_data, settings_path)
from usage_identity import APP_VERSION, build_identity
from usage_valuation import POLICY_VERSION, build_catalog
from usage_time import DEFAULT_TIMEZONE
from usage_observations import PARSER_VERSION
from usage_reconciliation import RECONCILIATION_VERSION
from usage_service import QUERY_VERSION, query_usage
from usage_reports import load_prices, render_text_report, report_directory, save_report


PROVIDERS = {"Codex": fetch_codex, "Claude": fetch_claude}


def open_local(path):
    if os.name == "nt":
        os.startfile(str(path))
    else:
        webbrowser.open(path.as_uri())


def open_report(path, format):
    if format == "html":
        open_local(path)
    elif os.name == "nt":
        # Pass the path as data, never interpolate it into PowerShell code.
        environment = dict(os.environ, USAGE_TRAY_REPORT=str(path))
        subprocess.Popen(
            ["powershell.exe", "-NoLogo", "-NoProfile", "-NoExit", "-Command",
             "Get-Content -LiteralPath $env:USAGE_TRAY_REPORT -Encoding UTF8"],
            env=environment, creationflags=subprocess.CREATE_NEW_CONSOLE,
        )
    else:
        print(path.read_text(encoding="utf-8"))


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


def run_tray(demo=False, selected="both", prices=None, report_format="text", plan_costs=None, timezone=DEFAULT_TIMEZONE, roots=None, settings_version=None):
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
    report_lock = threading.Lock()
    report_status = [""]

    def make_report(period):
        if not report_lock.acquire(blocking=False):
            return

        def generate():
            try:
                report_status[0] = "Building local usage report…"
                icon.update_menu()
                snapshots = {}
                for state in states:
                    with state.lock:
                        snapshots[state.provider] = state.snapshot
                report = query_usage(period, [s.provider for s in states], snapshots, prices=prices, demo=demo, plan_costs=plan_costs, timezone=timezone, roots=roots)
                report = replace(report, settings_version=settings_version)
                path = save_report(report, format=report_format)
                report_status[0] = "Report saved — select a report to refresh it"
                open_report(path, report_format)
            except Exception:
                report_status[0] = "Report failed — check local log and report-folder permissions"
            finally:
                report_lock.release()
                icon.update_menu()

        threading.Thread(target=generate, daemon=True).start()

    def open_reports(icon, item):
        try:
            directory = report_directory()
            directory.mkdir(parents=True, exist_ok=True)
            open_local(directory.resolve())
        except OSError:
            report_status[0] = "Cannot open the report folder — check folder permissions"
            icon.update_menu()

    def menu_items():
        if demo:
            yield pystray.MenuItem("DEMO — sample usage", None, enabled=False)
        for state in states:
            for line in state.lines():
                yield pystray.MenuItem(line, None, enabled=False)
            yield pystray.Menu.SEPARATOR
        yield pystray.MenuItem("This month: API value & plan comparison…", lambda icon, item: make_report("month"), enabled=lambda item: not report_lock.locked())
        yield pystray.MenuItem("Current session estimated API value…", lambda icon, item: make_report("session"), enabled=lambda item: not report_lock.locked())
        yield pystray.MenuItem("Today's estimated API value…", lambda icon, item: make_report("today"), enabled=lambda item: not report_lock.locked())
        yield pystray.MenuItem("Last 7 days estimated API value…", lambda icon, item: make_report("week"), enabled=lambda item: not report_lock.locked())
        yield pystray.MenuItem("Open saved reports folder…", open_reports)
        if report_status[0]:
            yield pystray.MenuItem(report_status[0], None, enabled=False)
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


def version_info(prices=None):
    catalog = build_catalog(prices)
    return {"app_version": APP_VERSION, "build_id": build_identity(), "parser_version": PARSER_VERSION,
            "reconciliation_version": RECONCILIATION_VERSION, "query_version": QUERY_VERSION,
            "valuation_policy": POLICY_VERSION, "catalog_version": catalog.catalog_version,
            "override_version": catalog.override_version, "pricing_version": catalog.version,
            "settings_schema_version": SCHEMA_VERSION}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", choices=("both", "codex", "claude"), default="both")
    parser.add_argument("--demo", action="store_true", help="Use clearly labeled sample data without reading credentials")
    parser.add_argument("--once", action="store_true", help="Print one usage snapshot as JSON, without a tray")
    parser.add_argument("--report", choices=("session", "today", "week", "month"), help="Estimate API-equivalent value from local tokens; month also compares plan fees")
    parser.add_argument("--report-format", choices=("text", "html"), default=None, help="Report display format (saved preference or terminal text)")
    parser.add_argument("--output", type=Path, help="Destination for --report or JSON --version/--diagnostics/--show-settings")
    parser.add_argument("--open-report", action="store_true", help="Open the report in a terminal (or browser for HTML)")
    parser.add_argument("--prices", type=Path, help="JSON file of exact-model USD prices per million tokens")
    parser.add_argument("--codex-plan-usd", default=None, help="Codex monthly subscription price in USD (saved value or 20)")
    parser.add_argument("--claude-plan-usd", default=None, help="Claude monthly subscription price in USD (saved value or 20)")
    parser.add_argument("--timezone", default=None, help="IANA timezone (saved preference or America/Los_Angeles)")
    parser.add_argument("--config", type=Path, help="Settings JSON (default: local application-data UsageTray/settings.json)")
    parser.add_argument("--save-settings", action="store_true", help="Atomically persist effective settings; alone, exit without launching the tray")
    parser.add_argument("--show-settings", action="store_true", help="Print effective settings JSON, including configured root paths, and exit")
    parser.add_argument("--diagnostics", action="store_true", help="Print effective version/quality identities without reading logs or polling providers")
    parser.add_argument("--version", action="store_true", help="Print application/build and bundled computation identities, even with invalid settings")
    parser.add_argument("--codex-root", action="append", type=Path, help="Absolute Codex log directory; repeat to replace that provider's root list")
    parser.add_argument("--claude-root", action="append", type=Path, help="Absolute Claude log directory; repeat to replace that provider's root list")
    args = parser.parse_args()
    if args.once and args.report:
        parser.error("--once and --report cannot be used together")
    if args.open_report and not args.report:
        parser.error("--open-report requires --report")
    if args.output and not any((args.report, args.version, args.diagnostics, args.show_settings)):
        parser.error("--output requires --report, --version, --diagnostics or --show-settings")
    if sum(bool(value) for value in (args.version, args.diagnostics, args.show_settings, args.report, args.once)) > 1:
        parser.error("Choose one of --version, --diagnostics, --show-settings, --report or --once")
    def emit_json(payload):
        encoded = json.dumps(payload, indent=2, ensure_ascii=True) + "\n"
        if args.output:
            try:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(encoded, encoding="utf-8")
            except OSError:
                parser.exit(1, "Cannot write diagnostic output. Check destination permissions.\n")
        elif sys.stdout is not None:
            print(encoded, end="")
        else:
            parser.error("Use --output with JSON commands in the windowed executable")

    if args.version:
        if args.save_settings:
            parser.error("--version cannot save settings")
        emit_json(version_info())
        return 0
    config_path = settings_path() if args.config is None else args.config
    try:
        settings = load_settings(config_path)
        saved_version = settings.version if config_path.exists() else None
        # Until the first explicit save, retain the legacy automatic price file.
        price_path = args.prices
        if price_path is None and args.config is None and not config_path.exists():
            candidate = application_directory() / "prices.json"
            if candidate.is_file():
                price_path = candidate
        try:
            prices = load_prices(price_path) if price_path is not None else None
        except (OSError, ValueError, RecursionError):
            raise SettingsError("Cannot load prices. Check the file and the pricing format in windows/README.md.") from None
        settings = effective_settings(settings, codex_fee=args.codex_plan_usd, claude_fee=args.claude_plan_usd,
            timezone=args.timezone, report_format=args.report_format, codex_roots=args.codex_root,
            claude_roots=args.claude_root, prices=prices)
        if args.save_settings:
            save_settings(settings, config_path)
            saved_version = settings.version
    except SettingsError as exc:
        parser.error(str(exc))
    if args.show_settings:
        emit_json(settings_data(settings))
        return 0
    if args.diagnostics:
        info = version_info(dict(settings.rate_overrides))
        info.update(settings_version=settings.version, settings_file_state="present" if saved_version else "absent",
                    effective_settings_saved=settings.version == saved_version,
                    timezone=settings.timezone, report_format=settings.report_format,
                    root_modes={p: "environment_defaults" if roots is None else "explicit" for p, roots in settings.log_roots},
                    explicit_root_counts={p: len(roots) for p, roots in settings.log_roots if roots is not None})
        emit_json(info)
        return 0
    if args.save_settings and not (args.report or args.once):
        if sys.stdout is not None:
            print("Settings saved. Restart the tray to use them.")
        return 0
    prices = dict(settings.rate_overrides)
    plan_costs = dict(settings.plan_fees_usd)
    roots = settings.roots()
    args.timezone, args.report_format = settings.timezone, settings.report_format
    if args.report:
        providers = [p for p in PROVIDERS if args.provider in ("both", p.lower())]
        try:
            report = query_usage(args.report, providers, prices=prices, demo=args.demo, plan_costs=plan_costs, timezone=args.timezone, roots=roots)
            report = replace(report, settings_version=settings.version)
            if args.report_format == "text" and not args.output and not args.open_report and sys.stdout is not None:
                print(render_text_report(report))
                return 0
            path = save_report(report, args.output, format=args.report_format)
        except (OSError, ValueError):
            parser.exit(1, "Cannot create the report. Check local log and output-folder permissions.\n")
        if sys.stdout is not None:
            print(str(path))
        if args.open_report or (sys.stdout is None and not args.output):
            open_report(path, args.report_format)
        return 0
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
    run_tray(args.demo, args.provider, prices, args.report_format, plan_costs, args.timezone,
             roots=roots, settings_version=settings.version)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
