"""Windows tray application for Codex and Claude subscription usage."""
from __future__ import annotations

import argparse
from dataclasses import replace
import json
from pathlib import Path
import threading
import webbrowser
import os
import platform
import subprocess
import sys

from usage_core import UsageError, demo_snapshot, fetch_claude, fetch_codex
from usage_failures import report_failure
from usage_privacy import display_text
from usage_diagnostics import Operation, report_counts, write_diagnostic
from usage_runtime import AlreadyRunning, PollingRuntime, ProviderState, RuntimeOwner
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
        if not webbrowser.open(path.as_uri()):
            raise OSError("No report viewer available.")


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


def run_tray(demo=False, selected="both", prices=None, report_format="text", plan_costs=None, timezone=DEFAULT_TIMEZONE, roots=None, settings_version=None,
             dashboard=False, dashboard_port=8765, shared_runtime=None, report_query=None,
             dashboard_opener=None, dashboard_unavailable=False):
    try:
        import pystray
        from PIL import Image, ImageDraw
    except ImportError:
        raise SystemExit("Tray dependencies missing. Run: python -m pip install -r requirements.txt") from None

    stop = shared_runtime.stop if shared_runtime is not None else threading.Event()
    changed = threading.Event()
    fetchers = {name: (lambda p=name: demo_snapshot(p)) if demo else (lambda f=fetch: f(cancel_event=stop))
                for name, fetch in PROVIDERS.items() if selected == "both" or name.lower() == selected}
    runtime = shared_runtime if shared_runtime is not None else PollingRuntime(fetchers, stop=stop, changed=changed.set)
    if shared_runtime is not None:
        for state in runtime.states:
            previous = state.changed
            state.changed = lambda previous=previous: (previous(), changed.set())
    states = runtime.states
    render_lock = threading.Lock()
    report_lock = threading.Lock()
    report_status = [""]
    report_threads = []
    dashboard_lock = threading.Lock()
    dashboard_owner = []
    dashboard_threads = []

    def open_dashboard(icon=None, item=None):
        if (not demo and dashboard_opener is None) or stop.is_set() or not dashboard_lock.acquire(blocking=False):
            return
        def open_preview():
            try:
                if stop.is_set():
                    return
                if dashboard_opener is not None:
                    url = dashboard_opener()
                elif not dashboard_owner:
                    from dashboard_main import start_preview
                    dashboard_owner.append(start_preview(port=dashboard_port, prices=prices,
                        fees=plan_costs, timezone=timezone, selected=selected, open_browser=False))
                if dashboard_opener is None:
                    url = dashboard_owner[0][2]
                if not stop.is_set() and not webbrowser.open(url):
                    report_status[0] = "Cannot open the browser - the local service remains running"
            except Exception:
                report_status[0] = "Dashboard unavailable - check the local port and timezone dependency"
            finally:
                if stop.is_set() and dashboard_owner:
                    server, thread, _ = dashboard_owner.pop()
                    server.shutdown()
                    server.server_close()
                    thread.join(timeout=2)
                dashboard_lock.release()
                changed.set()
        worker = threading.Thread(target=open_preview, daemon=True, name="usage-dashboard-open")
        dashboard_threads[:] = [t for t in dashboard_threads if t.is_alive()]
        dashboard_threads.append(worker)
        worker.start()

    def make_report(period):
        if not report_lock.acquire(blocking=False):
            return

        def generate():
            phase = "query"
            try:
                report_status[0] = "Building local usage report…"
                changed.set()
                snapshots = {}
                for state in states:
                    with state.lock:
                        snapshots[state.provider] = state.snapshot
                if report_query is not None:
                    report = report_query(period, snapshots)
                else:
                    report = query_usage(period, [s.provider for s in states], snapshots, prices=prices, demo=demo, plan_costs=plan_costs, timezone=timezone, roots=roots)
                    report = replace(report, settings_version=settings_version)
                if stop.is_set():
                    return
                phase = "save"
                path = save_report(report, format=report_format, text_view="summary")
                report_status[0] = "Report saved — select a report to refresh it"
                if not stop.is_set():
                    phase = "open"
                    open_report(path, report_format)
            except Exception as exc:
                failure = report_failure(exc, phase)
                report_status[0] = failure.category + ": " + failure.message
            finally:
                report_lock.release()
                changed.set()

        if stop.is_set():
            report_lock.release()
            return
        worker = threading.Thread(target=generate, daemon=True, name="usage-report")
        report_threads[:] = [thread for thread in report_threads if thread.is_alive()]
        report_threads.append(worker)
        worker.start()

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
        if demo:
            yield pystray.MenuItem("Open dashboard demo preview...", open_dashboard)
        elif dashboard_opener is not None:
            yield pystray.MenuItem("Open usage dashboard...", open_dashboard)
        elif dashboard_unavailable:
            yield pystray.MenuItem("Dashboard unavailable - save settings or check the local index", None, enabled=False)
        if shared_runtime is not None and not states:
            yield pystray.MenuItem("Live limits disabled - local usage remains available", None, enabled=False)
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
        yield pystray.MenuItem("Refresh (five-minute minimum)", lambda icon, item: runtime.refresh())
        yield pystray.MenuItem("Codex usage page", lambda icon, item: webbrowser.open("https://chatgpt.com/codex/settings/usage"))
        yield pystray.MenuItem("Claude usage page", lambda icon, item: webbrowser.open("https://claude.ai/settings/usage"))
        yield pystray.MenuItem("Quit", quit_app)

    def quit_app(icon, item):
        stop.set()
        runtime.refresh()
        changed.set()
        icon.stop()

    def image():
        img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.rounded_rectangle((2, 2, 61, 61), radius=14, fill="#17243b")
        for i, state in enumerate(states):
            with state.lock:
                windows = state.snapshot.windows if state.snapshot else []
                remaining = min((w.remaining for w in windows), default=0)
                color = "#8793a5" if state.error else "#ff6978" if state.snapshot and state.snapshot.blocked else ("#55dba6" if remaining > 50 else "#f1b858" if remaining > 20 else "#ff6978")
            y = 17 + i * 22
            draw.rounded_rectangle((11, y, 53, y + 12), radius=3, fill="#39445a")
            if remaining > 0:
                draw.rounded_rectangle((11, y, 11 + max(6, 42 * remaining / 100), y + 12), radius=3, fill=color)
            else:
                draw.ellipse((12, y + 2, 20, y + 10), fill=color)
        return img

    icon = pystray.Icon("UsageTray", image(), "Usage Tray" + (" — DEMO" if demo else ""), pystray.Menu(menu_items))

    def redraw():
        while not stop.is_set():
            changed.wait()
            changed.clear()
            if stop.is_set():
                break
            with render_lock:
                icon.icon = image()
                icon.update_menu()

    renderer = threading.Thread(target=redraw, daemon=True, name="usage-tray-render")

    def setup(tray_icon):
        tray_icon.visible = True
        renderer.start()
        runtime.start()
        if dashboard:
            open_dashboard(tray_icon)

    try:
        icon.run(setup=setup)
    finally:
        stop.set()
        changed.set()
        runtime.close(timeout=30)
        if renderer.is_alive():
            renderer.join(timeout=2)
        for worker in report_threads:
            worker.join(timeout=1)
        for worker in dashboard_threads:
            worker.join(timeout=2)
        if dashboard_lock.acquire(timeout=2):
            try:
                if dashboard_owner:
                    server, thread, _ = dashboard_owner.pop()
                    server.shutdown()
                    server.server_close()
                    thread.join(timeout=2)
            finally:
                dashboard_lock.release()


def version_info(prices=None):
    catalog = build_catalog(prices)
    return {"app_version": APP_VERSION, "build_id": build_identity(), "python_version": platform.python_version(), "parser_version": PARSER_VERSION,
            "reconciliation_version": RECONCILIATION_VERSION, "query_version": QUERY_VERSION,
            "valuation_policy": POLICY_VERSION, "catalog_version": catalog.catalog_version,
            "override_version": catalog.override_version, "pricing_version": catalog.version,
            "settings_schema_version": SCHEMA_VERSION}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", choices=("both", "codex", "claude"), default="both")
    parser.add_argument("--demo", action="store_true", help="Use clearly labeled sample data without reading credentials")
    parser.add_argument("--once", action="store_true", help="Print one usage snapshot as JSON, without a tray")
    parser.add_argument("--dashboard", action="store_true", help="Explicitly open the local dashboard; --demo selects the isolated preview")
    parser.add_argument("--dashboard-port", type=int, default=8765, help="Loopback dashboard port (default: 8765)")
    parser.add_argument("--no-browser", action="store_true", help="Serve the dashboard without opening a browser")
    parser.add_argument("--report", choices=("session", "today", "week", "month"), help="Estimate API-equivalent value from local tokens; month also compares plan fees")
    parser.add_argument("--report-format", choices=("text", "html"), default=None, help="Report display format (saved preference or terminal text)")
    terminal_mode = parser.add_mutually_exclusive_group()
    terminal_mode.add_argument("--details", choices=("provider", "model", "model_effort", "effort", "project", "conversation", "day"), help="Show one ranked terminal grouping")
    terminal_mode.add_argument("--audit", action="store_true", help="Full legacy terminal report with exact counts, rates and issue notes")
    parser.add_argument("--page", type=int, default=None, help="Detail page, starting at 1")
    parser.add_argument("--page-size", type=int, default=None, help="Groups per detail page (1..50; default 10)")
    parser.add_argument("--width", type=int, default=None, help="Compact/detail terminal width (40..160; default 80)")
    parser.add_argument("--output", type=Path, help="Destination for --report or JSON --version/--diagnostics/--show-settings")
    parser.add_argument("--include-metadata", action="store_true", help="Explicit report export of full project paths and conversation/turn IDs; review before sharing")
    parser.add_argument("--diagnostic-output", type=Path, help="Explicit redacted operation JSON export for --report or --once, including failures")
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
    if args.dashboard:
        if any((args.once, args.report, args.output, args.open_report, args.version, args.diagnostics,
                args.show_settings, args.save_settings, args.include_metadata, args.diagnostic_output,
                args.report_format, args.codex_root, args.claude_root)):
            parser.error("--dashboard cannot be combined with report, export, settings commands or source-root options")
        if not args.demo and any((args.prices, args.codex_plan_usd is not None,
                                  args.claude_plan_usd is not None, args.timezone is not None)):
            parser.error("Real dashboard uses saved settings; save fee, price and timezone changes separately before launch")
        if not 0 <= args.dashboard_port <= 65535:
            parser.error("--dashboard-port must be between 0 and 65535")
    elif args.no_browser or args.dashboard_port != 8765:
        parser.error("--no-browser and --dashboard-port require --dashboard")
    if args.once and args.report:
        parser.error("--once and --report cannot be used together")
    if args.open_report and not args.report:
        parser.error("--open-report requires --report")
    if args.output and not any((args.report, args.version, args.diagnostics, args.show_settings)):
        parser.error("--output requires --report, --version, --diagnostics or --show-settings")
    if sum(bool(value) for value in (args.version, args.diagnostics, args.show_settings, args.report, args.once)) > 1:
        parser.error("Choose one of --version, --diagnostics, --show-settings, --report or --once")
    if args.include_metadata and not args.report:
        parser.error("--include-metadata requires --report")
    if args.diagnostic_output and not (args.report or args.once):
        parser.error("--diagnostic-output requires --report or --once")
    terminal_options = bool(args.details or args.audit or args.page is not None or args.page_size is not None or args.width is not None)
    if terminal_options and not args.report:
        parser.error("Terminal view options require --report")
    if (args.page is not None or args.page_size is not None) and not args.details:
        parser.error("--page and --page-size require --details")
    if args.page is not None and args.page < 1:
        parser.error("--page must be at least 1")
    if args.page_size is not None and not 1 <= args.page_size <= 50:
        parser.error("--page-size must be 1..50")
    if args.width is not None and not 40 <= args.width <= 160:
        parser.error("--width must be 40..160")
    if args.audit and args.width is not None:
        parser.error("--width applies to compact/detail views; omit it with --audit")
    config_path = settings_path() if args.config is None else args.config
    if args.dashboard and not args.demo:
        from usage_hub_launch import run_host
        try:
            return run_host(config_path=config_path, port=args.dashboard_port,
                            open_browser=not args.no_browser, selected=args.provider,
                            tray=sys.stdout is None and not args.no_browser)
        except AlreadyRunning as error:
            parser.exit(3, str(error) + "\n")
        except Exception:
            parser.exit(1, "Cannot start the real dashboard. Preserve index/settings files and check the local port, assets and permissions.\n")
    diagnostic_targets = [args.diagnostic_output] + ([args.output] if args.diagnostics else [])
    for destination in (path for path in diagnostic_targets if path is not None):
        target = destination.resolve()
        protected = [config_path, application_directory() / "prices.json", args.prices]
        if destination == args.diagnostic_output:
            protected.append(args.output)
        if any(path is not None and target == path.resolve() for path in protected):
            parser.error("Diagnostic output must differ from settings, prices and report output")
        if target.is_relative_to((application_directory() / "Reports" / "Generated").resolve()):
            parser.error("Choose a diagnostic output outside the reserved Generated report folder")
    operation = Operation("report" if args.report else "provider_check" if args.once else "settings")

    def complete(code, phase, category, result=None, providers=()):
        if args.diagnostic_output:
            counts = report_counts(result) if result is not None else None
            partial = category == "source_incomplete"
            data = operation.finish("failed" if code else "partial" if partial else "success",
                                    phase, category, counts=counts, providers=providers, scope="demo" if args.demo else "local")
            try:
                write_diagnostic(args.diagnostic_output, data)
            except OSError:
                if sys.stderr is not None:
                    sys.stderr.write("Diagnostic export failed: check destination access and free space.\n")
                return code or 1
        return code

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
    try:
        settings = load_settings(config_path)
        loaded_version = settings.version
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
        if terminal_options and settings.report_format != "text":
            parser.error("Terminal view options require --report-format text")
        if args.save_settings:
            try:
                with RuntimeOwner():
                    if load_settings(config_path).version != loaded_version:
                        raise SettingsError("Settings changed before save. Reload and retry; no settings were replaced.")
                    save_settings(settings, config_path)
            except AlreadyRunning:
                complete(3, "ownership", "already_running")
                parser.exit(3, "An active Usage Tray/API owner controls settings. Use its settings API or quit it before saving from the CLI.\n")
            saved_version = settings.version
    except SettingsError as exc:
        if args.diagnostics:
            info = version_info()
            info["operation"] = operation.finish("failed", "settings", "settings_invalid", scope="configuration")
            emit_json(info)
            return 2
        complete(2, "settings", "settings_invalid")
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
        info["operation"] = operation.finish("success", "settings", "success", scope="configuration")
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
    if args.dashboard and (sys.stdout is not None or args.no_browser):
        from dashboard_main import run_preview
        try:
            return run_preview(port=args.dashboard_port, prices=prices, fees=plan_costs,
                timezone=args.timezone, selected=args.provider, open_browser=not args.no_browser)
        except Exception:
            parser.exit(1, "Cannot start the dashboard. Check the port, packaged assets and timezone dependency.\n")
    text_options = dict(view="details" if args.details else "audit" if args.audit else "summary",
                        width=args.width or 80, dimension=args.details or "model", page=args.page or 1,
                        page_size=args.page_size or 10)
    if args.report:
        providers = [p for p in PROVIDERS if args.provider in ("both", p.lower())]
        phase = "query"
        report = None
        try:
            report = query_usage(args.report, providers, prices=prices, demo=args.demo, plan_costs=plan_costs, timezone=args.timezone, roots=roots)
            report = replace(report, settings_version=settings.version)
            source_category = "source_incomplete" if any(source.state in ("partial", "failed") for source in report.sources) else "success"
            phase = "render"
            if args.report_format == "text" and not args.output and not args.open_report and sys.stdout is not None:
                print(render_text_report(report, include_metadata=args.include_metadata, **text_options))
                return complete(0, "complete", source_category, report)
            phase = "save"
            path = save_report(report, args.output, format=args.report_format, include_metadata=args.include_metadata,
                               text_view=text_options["view"], width=text_options["width"], dimension=text_options["dimension"],
                               page=text_options["page"], page_size=text_options["page_size"])
        except Exception as exc:
            failure = report_failure(exc, phase)
            complete(1, phase, failure.category, report)
            parser.exit(1, failure.category + ": " + failure.message + "\n")
        if sys.stdout is not None:
            print(display_text(path))
        if args.open_report or (sys.stdout is None and not args.output):
            try:
                open_report(path, args.report_format)
            except Exception as exc:
                failure = report_failure(exc, "open")
                complete(1, "open", failure.category, report)
                parser.exit(1, failure.category + ": " + failure.message + "\n")
        return complete(0, "complete", source_category, report)
    if args.once and args.demo:
        print(json.dumps([demo_snapshot(name).to_dict() for name in PROVIDERS if args.provider in ("both", name.lower())], indent=2, ensure_ascii=True))
        return complete(0, "complete", "success")
    if not args.once and not args.demo:
        # Shared persisted settings have one owner. Temporary legacy CLI
        # overrides retain their previous tray/report behavior, without mixing
        # those values into a separately configured production API.
        if settings.version == loaded_version:
            from usage_hub_launch import run_host
            try:
                return run_host(config_path=config_path, port=0, tray=True,
                                live_limits=True, selected=args.provider, report_format=args.report_format)
            except AlreadyRunning as error:
                parser.exit(3, str(error) + "\n")
            except Exception:
                if sys.stderr is not None:
                    sys.stderr.write("Local hub unavailable; continuing with the terminal/tray core. Preserve the index and check its settings/permissions.\n")
        args.dashboard_unavailable = True
    owner = RuntimeOwner()
    try:
        owner.__enter__()
    except AlreadyRunning as exc:
        complete(3, "ownership", "already_running")
        parser.exit(3, str(exc) + "\n")
    except OSError:
        complete(1, "ownership", "permission_denied")
        parser.exit(1, "Cannot acquire runtime ownership. Check application-data folder permissions.\n")
    try:
        return run_live(args, prices, plan_costs, roots, settings.version, complete=complete)
    finally:
        owner.__exit__(None, None, None)


def run_live(args, prices, plan_costs, roots, settings_version, complete=None):
    if args.once:
        results = []
        failed = False
        categories = []
        for name, fetch in PROVIDERS.items():
            if args.provider not in ("both", name.lower()):
                continue
            try:
                snapshot = demo_snapshot(name) if args.demo else fetch()
                results.append(snapshot.to_dict())
                categories.append((name, "blocked" if snapshot.blocked else "success"))
            except Exception as exc:
                failed = True
                message = str(exc) if isinstance(exc, UsageError) else "Unexpected provider error; check your CLI installation."
                category = exc.category if isinstance(exc, UsageError) else "unexpected_local"
                categories.append((name, category))
                results.append({"provider": name, "error": display_text(message), "category": category})
        print(json.dumps(results, indent=2, ensure_ascii=True))
        code = 1 if failed else 0
        return complete(code, "poll", "provider_error" if failed else "success", providers=categories) if complete else code
    run_tray(args.demo, args.provider, prices, args.report_format, plan_costs, args.timezone,
             roots=roots, settings_version=settings_version,
             dashboard=args.dashboard, dashboard_port=args.dashboard_port,
             dashboard_unavailable=getattr(args, "dashboard_unavailable", False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
