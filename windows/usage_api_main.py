"""Explicit production local API entry point; the native tray launcher opens the dashboard."""
import argparse
from pathlib import Path

from usage_hub_launch import run_host
from usage_runtime import AlreadyRunning


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--config', type=Path)
    parser.add_argument('--index', type=Path)
    parser.add_argument('--open', action='store_true', help='Explicitly open the authenticated local service status page')
    parser.add_argument('--tray', action='store_true', help='Host the tray in this process; live checks require --live-limits')
    parser.add_argument('--live-limits', action='store_true', help='Explicitly enable the existing CLI provider checks')
    args = parser.parse_args()
    if not 0 <= args.port <= 65535:
        parser.error('--port must be 0..65535')
    try:
        return run_host(config_path=args.config, index_path=args.index, port=args.port,
                        open_browser=args.open, tray=args.tray, live_limits=args.live_limits, status_page=True)
    except AlreadyRunning as error:
        parser.exit(3, str(error) + '\n')
    except Exception:
        parser.exit(1, 'Cannot start the local API. Preserve existing index/settings files and check ownership, permissions and port availability.\n')


if __name__ == '__main__':
    raise SystemExit(main())
