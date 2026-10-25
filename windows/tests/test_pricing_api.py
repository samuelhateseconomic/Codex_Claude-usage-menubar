"""Real index/query checks for applied pricing evidence, isolated synthetic roots."""
from decimal import Decimal as D
import json
from unittest.mock import patch

from test_api import ApiFixture
from test_index import counter, claude
from usage_valuation import Price


class AppliedPricingApiTests(ApiFixture):
    def test_event_pages_reconcile_full_group_and_matching_summary(self):
        overview=self.overview();params=self.frozen(overview,page_size=['1'])
        listing=self.query.read('/usage/conversations',params)
        row=listing['data']['items'][0]
        route='/conversations/'+row['id']
        detail=self.query.read(route,params)
        self.assertEqual(row['pricing'],detail['data']['pricing'])
        self.assertEqual(row['pricing']['total_record_count'],2)
        self.assertEqual(row['pricing']['groups'][0]['tokens'],row['summary']['tokens'])
        page=self.query.read(route+'/events',params)
        self.assertEqual(page['data']['summary'],row['summary'])
        items=list(page['data']['items'])
        while page['data']['pagination']['next_cursor']:
            page=self.query.read(route+'/events',{**params,'cursor':[page['data']['pagination']['next_cursor']]})
            items.extend(page['data']['items'])
        self.assertEqual(len(items),2)
        self.assertEqual(sum(D(item['value']['amount_usd']) for item in items),D(row['summary']['value']['amount_usd']))
        for item in items:
            v=item['value'];e=v['explanation']
            self.assertEqual(e['pricing_version'],overview['pricing_version'])
            self.assertEqual(e['source'],'custom configuration')
            self.assertTrue(e['custom'])
            self.assertEqual(e['rate_unit_tokens'],'1000000')
            self.assertEqual(sum(D(c['unrounded_usd']) for c in e['categories'])+D(e['rounding_adjustment_usd']),D(v['amount_usd']))
        e=row['pricing']['groups'][0]['explanation']
        self.assertEqual(sum(D(c['unrounded_usd']) for c in e['categories'])+D(e['rounding_adjustment_usd']),D(row['summary']['value']['amount_usd']))

    def test_repricing_freezes_explanations_until_publication_and_rejects_old_context(self):
        before=self.overview();params=self.frozen(before)
        row=self.query.read('/usage/conversations',params)['data']['items'][0]
        route='/conversations/'+row['id']+'/events'
        old=self.query.read(route,params)
        self.change_settings(prices={'fixture-model':Price('100','200','300')})
        pending=self.query.read(route,params)
        self.assertEqual(pending['data'],old['data'])
        self.assertEqual(pending['pricing_version'],old['pricing_version'])
        self.store.reprice()
        self.assertEqual(self.error(409,lambda:self.query.read(route,params)).code,'revision_changed')
        new=self.query.read(route,{})
        self.assertNotEqual(new['pricing_version'],old['pricing_version'])
        for left,right in zip(old['data']['items'],new['data']['items']):
            self.assertEqual(left['id'],right['id'])
            self.assertEqual(left['tokens'],right['tokens'])
            self.assertEqual(right['value']['explanation']['categories'][0]['rate_usd_per_million'],'100')
            self.assertNotEqual(left['value']['amount_usd'],right['value']['amount_usd'])
        # Changing the running bundled registry cannot alter an already stored catalog.
        with patch('usage_valuation.PRICES',{}):
            self.assertEqual(self.query.read(route,{})['data'],new['data'])

    def test_mixed_partial_rates_empty_matches_cache_writes_and_privacy(self):
        self.write(events=[counter(100,10),{'type':'turn_context','payload':{'model':'unknown-model','effort':'high'}},counter(150,20)])
        (self.claude/'a.jsonl').write_text(json.dumps(claude())+'\n',encoding='utf-8')
        self.store.import_settings()
        overview=self.overview();params=self.frozen(overview)
        rows=self.query.read('/usage/conversations',params)['data']['items']
        codex=next(row for row in rows if len(row['models'])==2)
        self.assertEqual(codex['summary']['value']['state'],'partial')
        self.assertEqual(codex['pricing']['group_count'],2)
        self.assertEqual({g['explanation']['state'] for g in codex['pricing']['groups']},{'available','unavailable'})
        self.assertFalse(codex['pricing']['truncated'])
        unknown=next(g for g in codex['pricing']['groups'] if g['pricing_state']=='unpriced')
        self.assertIsNone(unknown['amount_usd'])
        self.assertEqual(unknown['explanation']['reason'],'model_rate_unavailable')
        filtered=self.overview({'q':['no-matched-records']})
        empty=self.query.read('/conversations/'+codex['id'],self.frozen(filtered))
        self.assertEqual(empty['data']['pricing'],{'group_count':0,'total_record_count':0,'shown_record_count':0,'truncated':False,'groups':[]})
        claude_row=next(row for row in rows if len(row['models'])==1)
        events=self.query.read('/conversations/'+claude_row['id']+'/events',params)
        e=events['data']['items'][0]['value']['explanation']
        self.assertEqual(e['categories'][3]['rate_usd_per_million'],'5')
        self.assertEqual(D(e['categories'][3]['unrounded_usd']),D('.025'))
        self.assertIn('legacy_cache_ttl_assumed',e['assumptions'])
        self.assertNotIn('PRIVATE_RESPONSE_SENTINEL',json.dumps([rows,events]))

    def test_truncated_mixed_preview_keeps_full_totals_and_all_event_pages(self):
        self.change_settings(prices={f'mixed-{i}':Price(str(i+1),'0','0') for i in range(10)})
        events=[]
        for i in range(10):
            events.extend([{'type':'turn_context','payload':{'model':f'mixed-{i}','effort':'high'}},counter((i+1)*100,i+10)])
        self.write(events=events)
        self.store.import_settings()
        overview=self.overview();params=self.frozen(overview,page_size=['3'])
        row=self.query.read('/usage/conversations',params)['data']['items'][0]
        self.assertEqual(row['summary']['tokens']['total_tokens'],'1000')
        self.assertEqual(D(row['summary']['value']['amount_usd']),D('.0055'))
        preview=row['pricing']
        self.assertEqual((preview['group_count'],len(preview['groups']),preview['total_record_count'],preview['shown_record_count'],preview['truncated']),(10,8,10,8,True))
        route='/conversations/'+row['id']
        self.assertEqual(self.query.read(route,params)['data']['pricing'],preview)
        page=self.query.read(route+'/events',params);items=list(page['data']['items'])
        while page['data']['pagination']['next_cursor']:
            page=self.query.read(route+'/events',{**params,'cursor':[page['data']['pagination']['next_cursor']]})
            items.extend(page['data']['items'])
            self.assertEqual(page['data']['summary'],row['summary'])
        self.assertEqual(len(items),10)
        self.assertEqual(sum(D(i['value']['amount_usd']) for i in items),D('.0055'))
        selected=self.overview({'model':['mixed-9']})
        detail=self.query.read(route,self.frozen(selected))['data']
        self.assertEqual(detail['pricing']['group_count'],1)
        self.assertFalse(detail['pricing']['truncated'])
        self.assertEqual(detail['summary']['tokens']['total_tokens'],'100')
        self.assertEqual(D(detail['summary']['value']['amount_usd']),D('.001'))
