"""Explicit launcher for the local dashboard development preview."""
import threading
import webbrowser
import sys

from usage_hub import HubService, create_server


def start_preview(*, port=8765, prices=None, fees=None, selected="both", timezone="America/Los_Angeles", open_browser=True):
    # Keep real-history integration gated while S01-S09 are being refined in
    # parallel. Demo is an explicit choice, never a failed-connection fallback.
    service = HubService(demo=True, roots={}, prices=prices, fees=fees, timezone=timezone)
    service.refresh()
    server = create_server(service, port)
    thread = threading.Thread(target=server.serve_forever, name="usage-dashboard", daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}/"
    if selected in ("codex", "claude"):
        url += "#view=overview&provider=" + selected
    if open_browser:
        webbrowser.open(url)
    return server, thread, url


def run_preview(*, port=8765, prices=None, fees=None, selected="both", timezone="America/Los_Angeles", open_browser=True):
    server, thread, url = start_preview(port=port, prices=prices, fees=fees, selected=selected, timezone=timezone, open_browser=open_browser)
    try:
        if sys.stdout is not None:
            print(f"Usage Hub demo preview: {url}", flush=True)
            print("Sample data only. Ctrl+C stops this dashboard server.", flush=True)
        thread.join()
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        server.server_close()
    return 0
