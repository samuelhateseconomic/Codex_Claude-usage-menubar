"""Explicit read-only, metadata-only local-history release check. Writes JSON to stdout."""
import argparse
from collections import Counter
from decimal import localcontext
import json
import os
from pathlib import Path
import platform
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from usage_config import default_roots
from usage_ingestion import discover
from usage_privacy import display_text
from usage_service import DIMENSIONS, query_usage
from usage_valuation import ARITHMETIC

CATEGORIES = ('input', 'output', 'cached', 'write5m', 'write1h')


def token_data(tokens):
    return {name: str(getattr(tokens, name)) for name in (*CATEGORIES, 'total')}


def reconcile_summary(result):
    """Independent partition/category/value checks; no private identifiers in output."""
    def matches(summary, details):
        with localcontext(ARITHMETIC):
            amounts = [d.valuation.amount_usd for d in details if d.valuation.amount_usd is not None]
            amount = sum(amounts) if amounts else None
        return (all(getattr(summary.tokens, name) == sum(getattr(d.record.tokens, name) for d in details)
                    for name in CATEGORIES)
                and summary.tokens.total == sum(getattr(summary.tokens, name) for name in CATEGORIES)
                and summary.record_count == len(details) and summary.value.amount_usd == amount
                and all(d.record.reasoning_tokens is None or 0 <= d.record.reasoning_tokens <= d.record.tokens.output for d in details))

    checks = {'total_details': matches(result.total, result.details)}
    details = {d.detail_id: d for d in result.details}
    checks['unique_details'] = len(details) == len(result.details)
    for dimension in DIMENSIONS:
        groups = result.groups_for(dimension)
        ids = [key for group in groups for key in group.detail_ids]
        checks[dimension] = (len(ids) == len(details) and set(ids) == set(details)
                             and all(matches(group.summary, [details[key] for key in group.detail_ids]) for group in groups))
    return checks


def project_audit(result, inventory, seconds):
    checks = reconcile_summary(result)
    models = []
    groups = result.groups_for('model')
    for group in groups[:200]:
        provider, name = group.key
        models.append(dict(provider=provider, model=display_text(name[:200]), label_truncated=len(name)>200,
                           pricing_state=group.summary.value.state, records=group.summary.record_count,
                           tokens=str(group.summary.tokens.total)))
    return dict(schema=1, scope='available local unmatched-account month-to-date; not complete account verification',
        configuration='environment-default history roots; bundled rates; no persisted settings or provider polling',
        app_version=result.app_version, build_id=result.build_id, pricing_version=result.catalog.version,
        machine=dict(os=platform.system(), release=platform.release(), architecture=platform.machine(),
                     python=platform.python_version(), logical_cpus=os.cpu_count()),
        timezone=result.context.timezone, captured_at_utc=result.context.captured_at,
        inventory=inventory, scan_and_query_seconds=round(seconds, 6),
        records=result.total.record_count, conversations=result.total.conversation_count,
        tokens=token_data(result.total.tokens), pricing_state=result.total.value.state,
        priced_tokens=str(result.total.value.priced_tokens), unpriced_tokens=str(result.total.value.unpriced_tokens),
        assumed_records=result.total.value.assumed_records, models=models, model_labels_omitted=max(0,len(groups)-200),
        providers=[dict(provider=s.provider, state=s.state, roots_read=s.roots_read,
                        files_discovered=s.files_discovered, files_read=s.files_read,
                        ingestion_issue_counts=s.issue_counts,
                        accounting_issue_counts=dict(sorted(Counter(i.code for i in s.accounting_issues).items()))) for s in result.sources],
        reconciliation=checks, passed=all(checks.values()))


def audit_local(roots=None, now=None):
    roots = default_roots() if roots is None else roots
    inventory = []
    for provider in ('Codex','Claude'):
        files, issues, roots_read = discover(roots.get(provider, []))
        size, failed = 0, 0
        for path in files:
            try:
                size += path.stat().st_size
            except OSError:
                failed += 1
        inventory.append(dict(provider=provider, discovered_files=len(files), observed_bytes=size,
            stat_failures=failed, discovery_issues=sum(i.count for i in issues), roots_read=roots_read))
    # Inventory is a separate measurement, not a frozen revision of actively changing histories.
    captured = time.time() if now is None else now
    started = time.perf_counter()
    result = query_usage('month', roots=roots, now=captured, timezone='America/Los_Angeles')
    return project_audit(result, inventory, time.perf_counter()-started)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--read-local-history', action='store_true', help='Explicitly read environment-default local JSONL histories, without polling or credential access')
    args=parser.parse_args()
    if not args.read_local_history:
        parser.error('Use --read-local-history to explicitly select this read-only check.')
    try:
        data=audit_local()
    except Exception:
        print('Read-only history check failed; no raw error, source path or history content was exported.', file=sys.stderr)
        return 1
    print(json.dumps(data, indent=2, ensure_ascii=True))
    return 0 if data['passed'] else 1


if __name__=='__main__':
    raise SystemExit(main())
