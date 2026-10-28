"""Opt-in offline credit calculation; no dashboard, provider polling or settings writes."""
import argparse
import json
from pathlib import Path
import sqlite3
import sys
import time

from usage_config import load_settings
from usage_credits import APP_UNIT, NATIVE_UNIT
from usage_credit_contract import credit_result_data
from usage_index import UsageIndex
from usage_service import QueryContext, UsageFilters, query_usage
from usage_time import resolve_range
from usage_timezone import resolve_timezone
from usage_terminal import render_credit_summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--index', help='Read an existing committed real-data index; no import or migration')
    source.add_argument('--config', help='Explicit settings file selecting source roots/rates; read-only scan')
    source.add_argument('--demo', action='store_true', help='Explicit synthetic example; no personal data')
    source.add_argument('--scan', action='store_true', help='Read only the explicitly supplied provider roots')
    parser.add_argument('--codex-root', action='append', default=[])
    parser.add_argument('--claude-root', action='append', default=[])
    parser.add_argument('--provider', choices=('both', 'codex', 'claude'), default='both')
    parser.add_argument('--period', choices=('today', 'week', 'month'), default='month')
    parser.add_argument('--timezone', help='Named zone or auto; defaults to selected settings/system')
    parser.add_argument('--unit', choices=('app', 'codex'), default='app')
    parser.add_argument('--native-speed-scenario', choices=('standard', 'fast', 'ultrafast'),
                        help='Explicit native estimate assumption; absent means strict unknown-speed coverage')
    parser.add_argument('--search', default='', help='Local metadata filter; never exported')
    parser.add_argument('--format', choices=('text', 'json'), default='text')
    args = parser.parse_args(argv)
    if (args.codex_root or args.claude_root) and not args.scan:
        parser.error('Provider roots require --scan.')
    if args.scan and not (args.codex_root or args.claude_root):
        parser.error('--scan requires at least one explicit provider root.')
    if args.unit == 'app' and args.native_speed_scenario:
        parser.error('Native speed scenarios apply only to --unit codex.')
    providers = ('Codex', 'Claude') if args.provider == 'both' else (args.provider.title(),)
    try:
        now = time.time()
        if args.config and not Path(args.config).is_file():
            raise ValueError('Explicit configuration must exist.')
        snapshot = UsageIndex.read_existing_snapshot(args.index) if args.index else None
        settings = snapshot.settings if snapshot else load_settings(args.config) if args.config else None
        timezone_info = resolve_timezone(args.timezone or (settings.timezone if settings else 'auto'))
        zone = timezone_info.name
        filters = UsageFilters(search=args.search)
        policy = dict(unit=APP_UNIT if args.unit == 'app' else NATIVE_UNIT, speed_assumption=args.native_speed_scenario)
        if snapshot:
            context = QueryContext(tuple((p, resolve_range(args.period, now, timezone=zone)) for p in providers),
                                   now, args.period, zone, filters)
            result = snapshot.query_credits(context, **policy)
        else:
            roots = settings.roots() if settings else {'Codex': args.codex_root, 'Claude': args.claude_root}
            result = query_usage(args.period, providers, roots=roots, now=now, demo=args.demo, timezone=zone,
                filters=filters, prices=dict(settings.rate_overrides) if settings else None,
                plan_costs=dict(settings.plan_fees_usd) if settings else None).credits(**policy)
        data = credit_result_data(result)
        data['timezone_source'] = timezone_info.source
    except (ValueError, OSError, sqlite3.Error):
        print('Credit calculation unavailable. Preserve the selected index/settings; check source configuration and supported schema. No data was changed.', file=sys.stderr)
        return 1
    if args.format == 'json':
        print(json.dumps(data, ensure_ascii=True, sort_keys=True, allow_nan=False))
    else:
        print(render_credit_summary(result, timezone_source=timezone_info.source))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
