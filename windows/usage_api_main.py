"""Explicit production local API entry point; dashboard integration follows S13."""
import argparse
from pathlib import Path
import threading
import webbrowser

from usage_api_runtime import HubOwner,reuse_owner
from usage_runtime import AlreadyRunning


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port',type=int,default=8765)
    parser.add_argument('--config',type=Path)
    parser.add_argument('--index',type=Path)
    parser.add_argument('--open',action='store_true',help='Explicitly open the authenticated local service status page')
    parser.add_argument('--tray',action='store_true',help='Host the existing tray in this same process (requires --live-limits)')
    parser.add_argument('--live-limits',action='store_true',help='Explicitly enable the existing CLI provider checks')
    args=parser.parse_args()
    if not 0<=args.port<=65535:parser.error('--port must be 0..65535')
    if args.tray and not args.live_limits:parser.error('--tray requires --live-limits; the default API host is offline')
    stop=threading.Event();fetchers={}
    if args.live_limits:
        from usage_core import fetch_codex,fetch_claude
        fetchers={'Codex':lambda:fetch_codex(cancel_event=stop),'Claude':lambda:fetch_claude(cancel_event=stop)}
    owner=HubOwner(index_path=args.index,config_path=args.config,port=args.port,fetchers=fetchers)
    # Provider cancellation and the shared runtime use one stop signal.
    owner.runtime.stop=stop
    for state in owner.runtime.states:state.stop=stop
    try:
        owner.start()
    except AlreadyRunning:
        try:url=reuse_owner(owner)
        except AlreadyRunning as error:parser.exit(3,str(error)+'\n')
        if args.open:webbrowser.open(url)
        print('Reusing the existing local API owner. No second writer or provider scheduler was started.')
        return 0
    except Exception:
        parser.exit(1,'Cannot start the local API. Preserve existing index/settings files and check ownership, permissions and port availability.\n')
    if args.open:webbrowser.open(owner.launch_url())
    print('Usage Hub local API: '+owner.origin+' (authenticated; use --open for an explicit launch)')
    try:
        if args.tray:
            from usage_tray import run_tray
            run_tray(shared_runtime=owner.runtime,report_query=owner.query_tray)
        else:
            owner.thread.join()
    except KeyboardInterrupt:pass
    finally:
        while not owner.close(timeout=1):pass  # Keep ownership until rollback/shutdown finishes.
    return 0


if __name__=='__main__':raise SystemExit(main())
