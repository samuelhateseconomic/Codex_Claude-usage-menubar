"""B3-01: real SQLite publications and exact opt-in desktop projections."""
from decimal import Decimal, localcontext
import copy
import json
from pathlib import Path
from unittest.mock import patch

from test_api import ApiFixture
from test_index import counter, claude, NOW
from usage_api_contract import validate_schema
from usage_api_query import QueryService
from usage_valuation import Price, ARITHMETIC
from usage_dashboard_projection import PROJECTION

D = Decimal
ROOT = Path(__file__).resolve().parents[2]


class DashboardProjectionGates(ApiFixture):
    def setUp(self):
        super().setUp()
        self.change_settings(prices={'gpt-6.1-sol': Price('2', '10', '.1'),
                                     'claude-opus-5-5': Price('4', '20', '.2', '5', '8')})
        self.write('primary.jsonl', [counter(100, 10, cached=40, output=20)], session='primary', model='gpt-6.1-sol')
        c = claude(); c['message']['model'] = 'claude-opus-5-5'
        c['message']['usage'] = {'input_tokens': 10, 'output_tokens': 20, 'cache_read_input_tokens': 30,
                                 'cache_creation_input_tokens': 12,
                                 'cache_creation': {'ephemeral_5m_input_tokens': 5, 'ephemeral_1h_input_tokens': 7}}
        (self.claude/'a.jsonl').write_text(json.dumps(c)+'\n', encoding='utf-8')
        self.store.import_settings()

    def projected(self, **params):
        return self.overview({'projection': [PROJECTION], **params})

    def validate(self, wire):
        validate_schema(wire, json.loads((ROOT/'docs/api/usage-hub-v1.schema.json').read_text()))

    def test_explicit_empty_dimensions_are_frozen_and_do_not_erase_history(self):
        from usage_api_contract import ApiError
        baseline=self.projected(provider=['codex'])
        project=self.query.read('/usage/facets',self.frozen(baseline))['data']['projects'][0]['value']
        for dimension in ('project_id','model','effort'):
            wire=self.projected(provider=['codex'],empty_selection=[dimension])
            self.assertEqual(wire['applied_filters']['empty_selection'],[dimension])
            self.assertEqual(wire['data']['summary']['value']['state'],'empty')
            self.assertEqual(wire['data']['summary']['tokens']['total_tokens'],'0')
            self.assertIsNone(wire['data']['analysis']['daily_average']['usd_per_day'])
            self.assertEqual(wire['data']['analysis']['projects']['tokens']['slices'],[])
            self.validate(wire)
            args=self.frozen(wire)
            self.assertEqual(self.query.read('/usage/conversations',args)['data']['items'],[])
            self.assertEqual(self.query.read('/usage/analysis',args)['data']['summary'],wire['data']['summary'])
            facets=self.query.read('/usage/facets',args)['data']
            for key in ('projects','models','efforts'):self.assertTrue(facets[key],key)
            repeated=self.query.read('/overview',args)
            self.assertEqual(repeated['applied_filters'],wire['applied_filters'])
        cleared=self.projected(provider=['codex'])
        self.assertNotIn('empty_selection',cleared['applied_filters'])
        self.assertEqual(cleared['data']['summary'],baseline['data']['summary'])
        selected=self.projected(provider=['codex'],project_id=[project],model=['gpt-6.1-sol','unknown-model'],effort=['unknown','high'])
        # Any value within a dimension, all dimensions together; unknown values never add records.
        ordinary=self.projected(provider=['codex'],project_id=[project],model=['gpt-6.1-sol'],effort=['unknown','high'])
        self.assertEqual(selected['data']['summary'],ordinary['data']['summary'])
        for invalid in (['provider'],['bogus'],['model']*4):
            with self.assertRaises(ApiError):self.projected(empty_selection=invalid)

    def test_daily_average_exact_full_query_filter_and_analysis_agreement(self):
        new=self.projected();a=new['data']['analysis']['daily_average']
        self.assertEqual(a['calendar_days'],24)
        self.assertEqual(a['tokens_per_day'],'8.000000000000000000')
        self.assertEqual(a['usd_per_day'],'0.000035458333333333')
        self.assertEqual(a['app_credits_per_day'],'0.003545833333333333')
        self.assertEqual(self.query.read('/usage/analysis',self.frozen(new))['data']['analysis']['daily_average'],a)
        selected=self.projected(selected_day=['2026-10-23'])['data']['analysis']['daily_average']
        self.assertEqual(selected['calendar_days'],1);self.assertEqual(selected['tokens_per_day'],'192.000000000000000000')
        self.assertEqual(selected['usd_per_day'],'0.000851000000000000')
        provider=self.projected(provider=['codex'])['data']['analysis']['daily_average']
        self.assertEqual(provider['tokens_per_day'],'5.000000000000000000')
        self.validate(new)

    def test_daily_average_keeps_empty_unpriced_partial_and_zero_distinct(self):
        self.change_settings(prices={'claude-opus-5-5':Price('4','20','.2')});self.store.reprice()
        partial=self.projected();a=partial['data']['analysis']['daily_average']
        self.assertEqual(partial['data']['summary']['value']['state'],'partial')
        self.assertEqual(a['usd_per_day'],'0.000013500000000000');self.assertEqual(a['tokens_per_day'],'8.000000000000000000')
        unpriced=self.projected(provider=['claude'])['data']['analysis']['daily_average']
        self.assertIsNone(unpriced['usd_per_day']);self.assertIsNotNone(unpriced['tokens_per_day'])
        empty=self.projected(q=['no-such-match'])['data']['analysis']['daily_average']
        self.assertIsNone(empty['tokens_per_day']);self.assertIsNone(empty['app_credits_per_day'])
        self.change_settings(prices={'gpt-6.1-sol':Price(0,0,0)});self.store.reprice()
        zero=self.projected(provider=['codex'])['data']['analysis']['daily_average']
        self.assertEqual(zero['usd_per_day'],'0.000000000000000000')
        self.change_settings(prices={'gpt-6.1-sol':Price('0.00000005',0,0)});self.store.reprice()
        tiny=self.projected(provider=['codex'])['data']['analysis']['daily_average']
        self.assertEqual(tiny['usd_per_day'],'0.000000000000125000')

    def test_daily_average_calendar_bounds_midnight_and_dst(self):
        from datetime import datetime, timezone
        self.query.clock=lambda:datetime(2026,11,1,20,tzinfo=timezone.utc).timestamp()
        week=self.projected(period=['week'],timezone=['America/Los_Angeles'])['data']['analysis']['daily_average']
        self.assertEqual(week['calendar_days'],8)
        today=self.projected(period=['today'],timezone=['America/Los_Angeles'])['data']['analysis']['daily_average']
        self.assertEqual(today['calendar_days'],1)
        self.query.clock=lambda:datetime(2026,11,2,8,tzinfo=timezone.utc).timestamp()
        midnight=self.projected(period=['today'],timezone=['America/Los_Angeles'])['data']['analysis']['daily_average']
        self.assertEqual(midnight['calendar_days'],0);self.assertIsNone(midnight['tokens_per_day'])

    def test_default_compatibility_and_exact_all_endpoint_reconciliation(self):
        old = self.overview(); new = self.projected()
        self.assertNotIn('projection', old)
        self.assertNotIn('app_credits', old['data']['summary'])
        self.assertGreater(int(old['data']['summary']['tokens']['total_tokens']), int(new['data']['summary']['tokens']['total_tokens']))
        self.assertEqual(new['data']['summary']['tokens']['total_tokens'], '192')
        self.assertFalse(new['data']['combined_comparison']['available'])
        params = self.frozen(new)
        listing = self.query.read('/usage/conversations', params)
        self.assertEqual(listing['data']['summary'], new['data']['summary'])
        amounts = []
        for row in listing['data']['items']:
            amounts.append(D(row['summary']['app_credits']['amount']))
            detail = self.query.read('/conversations/'+row['id'], params)
            events = self.query.read('/conversations/'+row['id']+'/events', params)
            self.assertEqual(detail['data']['summary'], row['summary'])
            self.assertEqual(events['data']['summary'], row['summary'])
            self.assertEqual(sum(D(e['value']['app_credits']['amount']) for e in events['data']['items']), amounts[-1])
            self.validate(detail); self.validate(events)
        self.assertEqual(sum(amounts), D(new['data']['summary']['app_credits']['amount']))
        self.assertEqual(sum(D(r['summary']['app_credits']['amount']) for r in new['data']['days']), sum(amounts))
        for wire in (new, listing, self.query.read('/usage/facets', params), self.query.read('/usage/analysis', params)):
            self.validate(wire)

    def test_provider_model_pairs_prevent_cross_product_and_mixed_conversation_leaks(self):
        self.write('wrong-provider.jsonl', [counter(900, 10)], session='wrong-provider', model='claude-opus-5-5')
        self.write('mixed.jsonl', [counter(100, 10), {'type':'turn_context','payload':{'model':'other-model','effort':'high'}}, counter(200, 20)], session='mixed', model='gpt-6.1-sol')
        self.store.import_settings()
        new = self.projected(); self.assertEqual(new['data']['summary']['tokens']['total_tokens'], '292')
        listing = self.query.read('/usage/conversations', self.frozen(new))
        mixed = next(r for r in listing['data']['items'] if r['models'] == ['gpt-6.1-sol'] and r['summary']['tokens']['total_tokens'] == '100')
        detail = self.query.read('/conversations/'+mixed['id'], self.frozen(new))
        self.assertEqual(detail['data']['summary']['tokens']['total_tokens'], '100')
        self.assertEqual(self.projected(provider=['codex'])['data']['summary']['tokens']['total_tokens'], '220')
        self.assertEqual(self.projected(model=['other-model'])['data']['summary']['value']['state'], 'empty')

    def test_full_query_other_slices_and_partial_zero_unpriced_denominators(self):
        for i in range(15):
            self.write(f'p{i}.jsonl', [counter(100+i, 10)], session=f'p{i}', project=f'C:/p{i}', model='gpt-6.1-sol')
        self.store.import_settings(); new = self.projected()
        a = new['data']['analysis']
        for metric, dist in a['projects'].items():
            self.assertEqual(dist['group_count'], 16)
            self.assertEqual(len(dist['slices']), 12)
            self.assertTrue(dist['slices'][-1]['other'])
            self.assertEqual(sum(D(s['percent']) for s in dist['slices']), D(100))
            self.assertEqual(sum(int(s['summary']['tokens']['total_tokens']) for s in dist['slices']), int(new['data']['summary']['tokens']['total_tokens']))
        self.assertEqual(self.query.read('/usage/conversations', self.frozen(new, page_size=['1']))['data']['summary'], new['data']['summary'])
        self.change_settings(prices={'gpt-6.1-sol': Price('2', '10', '.1')})
        # Missing write rates leave Claude's ordinary tokens recorded/unpriced.
        self.change_settings(prices={'claude-opus-5-5': Price('4', '20', '.2')})
        self.store.reprice(); partial = self.projected()
        self.assertEqual(partial['data']['summary']['value']['state'], 'partial')
        self.assertEqual(partial['data']['analysis']['projects']['usd']['denominator'], 'priced_subtotal')
        self.assertEqual(self.projected(provider=['claude'])['data']['analysis']['models']['usd']['state'], 'unavailable')
        self.change_settings(prices={'gpt-6.1-sol': Price(0,0,0)})
        self.store.reprice(); zero = self.projected(provider=['codex'])
        self.assertEqual(zero['data']['analysis']['models']['usd']['state'], 'zero')
        self.assertIsNone(zero['data']['analysis']['models']['usd']['slices'][0]['percent'])
        empty = self.projected(q=['no-such-match'])
        self.assertEqual(empty['data']['summary']['value']['state'], 'empty')
        self.assertEqual(empty['data']['analysis']['projects']['usd']['slices'], [])
        for wire in (partial, zero, empty): self.validate(wire)

    def test_nonzero_cache_writes_reasoning_and_rounding_reconcile(self):
        new = self.projected(); s = new['data']['summary']; m = new['data']['analysis']['methodology']
        counts = {c['category']: c['tokens'] for c in m['categories']}
        self.assertEqual(counts['cache_write_5m_tokens'], '5')
        self.assertEqual(counts['cache_write_1h_tokens'], '7')
        self.assertIsNone(s['tokens']['reasoning_tokens'])
        with localcontext(ARITHMETIC):
            total = sum(D(c['unrounded_priced_usd']) for c in m['categories']) + D(m['rounding_adjustment_usd'])
            self.assertEqual(total, D(s['value']['amount_usd']))
            self.assertEqual(total/D('.01'), D(s['app_credits']['amount']))
        self.assertEqual(m['contribution_basis'], 'priced_events_only')

    def test_projection_bounds_frozen_identity_failure_restart_and_reprice(self):
        new = self.projected(); params = self.frozen(new)
        legacy = self.overview()
        for bad in ({'projection':['unknown']}, {'projection':[PROJECTION, PROJECTION]}, self.frozen(legacy, projection=[PROJECTION]), self.frozen(legacy, base_query_context_id=[new['query_context_id']])):
            self.error(422, lambda: self.overview(bad))
        self.query.clock = lambda: NOW+86400
        self.assertEqual(self.overview(params)['range'], new['range'])
        with patch('usage_api_query.PRIMARY_MODELS', (('Codex','changed-model'),)):
            self.assertEqual(self.overview(params)['projection'], new['projection'])
        restarted = QueryService(self.store,clock=lambda:NOW)
        self.assertEqual(self.error(409,lambda:restarted.read('/overview',params)).code,'context_expired')
        with patch.object(self.store,'read_snapshot',side_effect=OSError('synthetic')):
            with self.assertRaises(OSError): self.overview(params)
        self.error(422,lambda:self.query.read('/usage/analysis',self.frozen(new,page_size=['9'])))
        self.error(422,lambda:self.query.read('/usage/analysis',self.frozen(legacy)))
        self.change_settings(codex_fee='21');self.store.reprice()
        self.error(409,lambda:self.overview(params))
        current=self.projected()
        self.assertEqual(current['data']['summary'],new['data']['summary'])

    def test_rate_group_paging_is_complete_and_cursors_bound_to_context(self):
        # Explicit effort evidence yields separate provenance groups through
        # differing preserved context assumptions, rather than invented rates.
        from dataclasses import replace
        from usage_pricing_explanation import explain_values
        snap=self.store.read_snapshot(); result=snap.query(self.query.context(snap,self.query.resolve({'projection':[PROJECTION]},snap))).result
        values=[replace(result.details[0].valuation, assumptions=(f'synthetic_{i}',)) for i in range(19)]
        all_records=0
        for offset in (0,8,16):
            page=explain_values(values,snap.catalog,offset=offset)
            self.assertEqual(page.group_count,19); self.assertLessEqual(len(page.groups),8)
            all_records+=page.shown_record_count
        self.assertEqual(all_records,19)
        new=self.projected()
        page=self.query.read('/usage/analysis',self.frozen(new,page_size=['1']))
        cursor=page['data']['pagination']['next_cursor']; self.assertIsNotNone(cursor)
        following=self.query.read('/usage/analysis',self.frozen(new,page_size=['1'],cursor=[cursor]))
        self.assertEqual(following['data']['summary'],new['data']['summary']);self.validate(following)
        other=self.projected()
        self.error(409,lambda:self.query.read('/usage/analysis',self.frozen(other,page_size=['1'],cursor=[cursor])))
        self.error(422,lambda:self.query.read('/usage/analysis',self.frozen(new,page_size=['1'],cursor=[cursor+'x'])))

    def test_tiny_rounding_and_missing_provenance_preserve_priced_counts(self):
        from dataclasses import replace
        from usage_dashboard_projection import methodology
        self.change_settings(prices={'gpt-6.1-sol':Price('.0000005',0,0)})
        self.write('primary.jsonl',[counter(1,10),counter(2,20),counter(3,30)],session='tiny',model='gpt-6.1-sol')
        self.store.import_settings()
        new=self.projected(provider=['codex']);s=new['data']['summary'];m=new['data']['analysis']['methodology']
        self.assertEqual(s['tokens']['total_tokens'],'3');self.assertEqual(D(s['app_credits']['amount']),D(0))
        self.assertEqual(D(m['categories'][0]['unrounded_priced_usd']),D('.0000000000015'))
        self.assertEqual(D(m['rounding_adjustment_usd']),D('-.0000000000015'))
        snap=self.store.read_snapshot();frozen=self.query.resolve(self.frozen(new),snap)
        result=snap.query(self.query.context(snap,frozen)).result
        missing=methodology(result,replace(snap,catalog=None))
        self.assertIsNone(missing['rounding_adjustment_usd'])
        self.assertIsNone(missing['categories'][0]['unrounded_priced_usd'])
        self.assertEqual(missing['categories'][0]['priced_tokens'],'3')
        self.assertEqual(missing['pricing']['groups'][0]['explanation']['reason'],'pricing_provenance_unavailable')

    def test_overview_embeds_complete_first_rate_page_and_signed_continuation(self):
        from dataclasses import replace
        self.write('rates.jsonl',[counter(i,i+10) for i in range(1,20)],session='many-rate-groups',model='gpt-6.1-sol')
        self.store.import_settings();snapshot=self.store.read_snapshot()
        # Explicit synthetic provenance differences on the same accepted facts.
        # No stored events/rates are changed by this fixture projection.
        changed=replace(snapshot,valuations=tuple((key,replace(value,assumptions=(f'synthetic_{i}',))) for i,(key,value) in enumerate(snapshot.valuations)))
        with patch.object(self.store,'read_snapshot',return_value=changed):
            first=self.projected(provider=['codex']);self.validate(first)
            pagination=first['data']['analysis_pagination']
            self.assertEqual(pagination['matched_count'],20)
            groups=list(first['data']['analysis']['methodology']['pricing']['groups'])
            while pagination['next_cursor']:
                page=self.query.read('/usage/analysis',self.frozen(first,cursor=[pagination['next_cursor']]))
                self.validate(page);self.assertEqual(page['data']['summary'],first['data']['summary'])
                groups.extend(page['data']['analysis']['methodology']['pricing']['groups']);pagination=page['data']['pagination']
            self.assertEqual(len(groups),20)
            self.assertEqual(len({tuple(g['explanation']['assumptions']) for g in groups}),20)
            self.assertEqual(sum(g['record_count'] for g in groups),20)
