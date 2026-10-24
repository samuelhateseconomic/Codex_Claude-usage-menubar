"""Native launch/lifetime bridge for the shared production hub and existing tray."""
import sys
import threading
import webbrowser

from usage_api_runtime import HubOwner, reuse_owner, launch_destination
from usage_runtime import AlreadyRunning


def _notice(message):
    if sys.stdout is not None:
        print(message, flush=True)


def run_host(*, config_path=None, index_path=None, port=8765, open_browser=False,
             tray=False, live_limits=False, selected='both', status_page=False,
             report_format='text', owner_path=None):
    """Run one owner, or hand an explicit launch to the existing owner.

    Hosting/provider choices apply to a new owner only. Reuse never silently
    changes provider polling, settings, or the lifetime of the running owner.
    """
    if selected not in ('both', 'codex', 'claude'):
        raise ValueError('Invalid launch provider.')
    stop = threading.Event()
    fetchers = {}
    if live_limits:
        from usage_core import fetch_codex, fetch_claude
        fetchers = {name: (lambda fetch=fetch: fetch(cancel_event=stop))
                    for name, fetch in (('Codex', fetch_codex), ('Claude', fetch_claude))
                    if selected in ('both', name.lower())}
    owner = HubOwner(index_path=index_path, config_path=config_path,
                     owner_path=owner_path, port=port, fetchers=fetchers)
    owner.runtime.stop = stop
    for state in owner.runtime.states:
        state.stop = stop
    try:
        owner.start()
    except AlreadyRunning:
        url = launch_destination(reuse_owner(owner), selected, status_page=status_page)
        if open_browser and not webbrowser.open(url):
            _notice('Browser could not be opened. Use the existing tray dashboard action.')
        _notice('Reusing the existing local API owner. No second writer or provider scheduler was started.')
        return 0
    try:
        if open_browser and not webbrowser.open(owner.launch_url(selected=selected, status_page=status_page)):
            _notice('Browser could not be opened. The local service remains running.')
        _notice('Usage Hub local API: ' + owner.origin + ' (authenticated; open explicitly from the application)')
        if tray:
            from usage_tray import run_tray
            providers = tuple(p for p in ('Codex', 'Claude') if selected in ('both', p.lower()))
            run_tray(selected=selected, report_format=report_format,
                     shared_runtime=owner.runtime,
                     report_query=lambda period, snapshots: owner.query_tray(period, snapshots, providers=providers),
                     dashboard_opener=lambda: owner.launch_url(selected=selected))
        else:
            owner.thread.join()
    except KeyboardInterrupt:
        pass
    finally:
        # Never release the OS owner while a provider or publication is alive.
        while not owner.close(timeout=1):
            pass
    return 0
