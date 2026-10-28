"""Actual executable: legacy USD publication -> confirmed context scenario, offline.

App credits are checked over the authenticated dashboard projection and against
the same committed headless publication. Native credits remain headless.
"""
import argparse
from datetime import datetime, timezone, timedelta
from decimal import Decimal, localcontext
import json
from pathlib import Path
import sys
from unittest.mock import patch

sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parent)]
from packaged_hub_release import PackagedHost
from packaged_local_hub_smoke import require, synthetic_workspace
from usage_config import Settings, effective_settings, save_settings
from usage_index import UsageIndex
from usage_service import QueryContext
from usage_time import resolve_range
from usage_credits import NATIVE_UNIT
from usage_valuation import ARITHMETIC, build_catalog, LEGACY_CONTEXT, POLICY_VERSION


def check(executable):
    with synthetic_workspace(Path(__file__).resolve().parents[1]/'build') as root:
        host = PackagedHost(executable, root)
        logs = root/'sources'; empty = root/'empty'
        logs.mkdir(); empty.mkdir(); host.app.mkdir(parents=True)
        stamp = datetime.now(timezone.utc) - timedelta(seconds=1)
        rows = [{'type':'session_meta','payload':{'id':'credit-foundation-fixture','cwd':'C:/fixture'}},
                {'type':'turn_context','payload':{'model':'gpt-6.1-sol'}},
                {'type':'event_msg','timestamp':stamp.isoformat(),'payload':{'type':'token_count','info':{
                    'total_token_usage':{'input_tokens':280000,'output_tokens':1000,'cached_input_tokens':0,
                                         'reasoning_output_tokens':300}}}},
                {'type':'response_item','payload':{'content':'PRIVATE_CREDIT_CONTENT_SENTINEL'}}]
        (logs/'usage.jsonl').write_text('\n'.join(map(json.dumps, rows))+'\n', encoding='utf-8')
        save_settings(effective_settings(Settings(), codex_roots=[logs], claude_roots=[empty], timezone='UTC'), host.config)
        with patch('usage_index.build_catalog', return_value=build_catalog(context_policy=LEGACY_CONTEXT)):
            store = UsageIndex(host.index, config_path=host.config)
            store.import_settings()
        before = store.read_snapshot()
        require(before.valuations[0][1].amount_usd == Decimal('1.135'), 'Legacy fixture was not seeded.')
        facts = before.events
        try:
            host.start(); host.ready()
            overview = host.query()
            value = overview['data']['summary']['value']
            require(Decimal(value['amount_usd']) == Decimal('.570'), 'Executable ignored the confirmed context policy.')
            require('below_threshold_context_assumed' in value['assumptions'], 'Executable lost the scenario qualification.')
            require(overview['data']['summary']['tokens']['total_tokens'] == '281000', 'Executable changed token facts.')
            listing = host.query('/usage/conversations', overview['query_context_id'])
            row = listing['data']['items'][0]
            detail = host.query('/conversations/'+row['id'], overview['query_context_id'])
            require(detail['data']['summary'] == row['summary'], 'Existing USD API detail does not reconcile.')
            projected,_=host.api('GET','/overview?projection=app_api_value_v1')
            require(projected['projection']['primary_model_policy']=='desktop-primary-models-v1','Primary policy missing.')
            for dimension in ('project_id','model','effort'):
                none,_=host.api('GET','/overview?projection=app_api_value_v1&empty_selection='+dimension)
                require(none['applied_filters']['empty_selection']==[dimension],'Packaged empty selection is not frozen.')
                require(none['data']['summary']['value']['state']=='empty' and none['data']['summary']['tokens']['total_tokens']=='0','Deselect all broadened packaged usage.')
                facets=host.query('/usage/facets',none['query_context_id'])
                require(all(facets['data'][key] for key in ('projects','models','efforts')),'Packaged empty selection cannot recover choices.')

            require(Decimal(projected['data']['summary']['app_credits']['amount'])==Decimal('57'),'Packaged credit HTTP normalization differs.')
            require(not projected['data']['combined_comparison']['available'],'Primary-filtered fee comparison must be unavailable.')
            analysis=host.query('/usage/analysis',projected['query_context_id'])
            require(analysis['data']['summary']==projected['data']['summary'],'Packaged analysis summary differs.')
            average=projected['data']['analysis']['daily_average']
            require(average==analysis['data']['analysis']['daily_average'],'Packaged daily averages differ across frozen endpoints.')
            require(average['rounding']=='half_even_18_decimal_places' and 1<=average['calendar_days']<=31,'Packaged average basis is missing.')
            with localcontext(ARITHMETIC):
                require(Decimal(average['usd_per_day'])==(Decimal('.570')/average['calendar_days']).quantize(Decimal('.000000000000000001')),'Packaged average does not derive from authoritative USD.')

            require(analysis['data']['analysis']['models']['app_credits']['slices'][0]['percent']=='100','Packaged share denominator differs.')
            details=host.query('/conversations/'+row['id'],projected['query_context_id'])
            require(details['data']['summary']==projected['data']['summary'],'Packaged credit detail differs.')
            for asset in ('local-app.js','local-session.js','local-view.js','local-analysis-view.js','local-freshness.js','v1-client.js','v1-schema.js','format.js','style.css'):
                code,_,raw=host.request('GET','/'+asset,auth=False)
                require(code==200 and raw==(Path(__file__).resolve().parents[1]/'dashboard'/asset).read_bytes(),'Candidate assets differ from browser-tested source: '+asset)
            host.close(); host.start(); host.ready()
            require(Decimal(host.query()['data']['summary']['value']['amount_usd']) == Decimal('.570'), 'Restart changed valuation.')
        finally:
            host.close()
        snapshot = UsageIndex.read_existing_snapshot(host.index)
        require(snapshot.events == facts, 'Normal executable publication changed canonical events.')
        require(snapshot.catalog.policy_version == POLICY_VERSION, 'Policy identity was not published.')
        now = datetime.now(timezone.utc).timestamp()
        context = QueryContext((('Codex', resolve_range('month', now, timezone='UTC')),), now, 'month', 'UTC')
        app = snapshot.query_credits(context)
        require(app.total.amount == Decimal('57'), 'App normalization differs from committed executable USD.')
        require(snapshot.query_credits(context, unit=NATIVE_UNIT).total.state == 'unpriced', 'Unknown speed was inferred.')
        require(snapshot.query_credits(context, unit=NATIVE_UNIT, speed_assumption='standard').total.amount == Decimal('14.25'), 'Native headless scenario differs.')
        report = root/'report.txt'
        require(host.invoke('--report', 'month', '--audit', '--output', report) == 0, 'Packaged terminal failed.')
        text = report.read_text(encoding='utf-8')
        require('$0.5700' in text and '281,000' in text and 'Below-threshold context assumed' in text, 'Terminal policy/qualification differs.')
        require('PRIVATE_CREDIT_CONTENT_SENTINEL' not in text, 'Private source content escaped.')
    print('Packaged calculation/dashboard: PASS (legacy USD1.135 -> USD0.570, 281000 unchanged tokens, authenticated app57/analysis/detail, browser-tested assets, restart/terminal; headless native14.25 scenario)')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--exe', required=True, type=Path)
    check(parser.parse_args().exe.resolve(strict=True))
