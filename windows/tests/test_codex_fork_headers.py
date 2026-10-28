"""Desktop child rollouts replay parent headers; outer identity must survive."""
from collections import Counter
from dataclasses import asdict, replace
from itertools import permutations
import json
from unittest.mock import patch

from test_api import ApiFixture
from test_index import header, counter
from usage_observations import extract_codex
from usage_reconciliation import reconcile_observations


def parent():
    return header(session='portfolio-parent') + [counter(100, 10), counter(200, 20), counter(300, 50)]


def child(identity='research-child', initial=100, final=150, second=25):
    outer = {'type':'session_meta','timestamp':'2026-10-23T20:00:15Z',
             'payload':{'id':identity,'cwd':'C:/fixture/child','forked_from_id':'portfolio-parent',
                        'source':{'subagent':{'parent_thread_id':'portfolio-parent'}},
                        'instructions':'PRIVATE_REPLAY_SENTINEL'}}
    replay = header(session='portfolio-parent')
    replay[0]['timestamp'] = outer['timestamp']
    return [outer, *replay, counter(initial, second), counter(final, second+10)]


class DesktopForkGates(ApiFixture):
    def test_outer_fork_identity_project_boundary_and_provenance_survive_replayed_headers(self):
        entries=child()
        observations=extract_codex(enumerate(entries,1),'child-file')
        self.assertEqual({o.conversation_id for o in observations},{'research-child'})
        self.assertEqual({o.fork_parent_id for o in observations},{'portfolio-parent'})
        self.assertEqual({o.project for o in observations},{'C:/fixture/child'})
        self.assertEqual({o.session_source.line for o in observations},{1})
        self.assertEqual(len({o.session_created_at for o in observations}),1)
        self.assertNotIn('PRIVATE_REPLAY_SENTINEL',json.dumps([asdict(o) for o in observations]))
        # Nested/repeated inherited headers cannot erase the outer fork marker.
        extra=header(session='grandparent')[0]
        entries.insert(2,extra)
        self.assertEqual({o.conversation_id for o in extract_codex(enumerate(entries,1),'nested')},{'research-child'})

    def test_parent_children_and_overlapping_copy_reconcile_in_every_file_order(self):
        groups=[extract_codex(enumerate(entries,1),source) for source,entries in [
            ('parent',parent()),('child',child()),('child-copy',child()),
            ('child-two',child('second-child',200,260,26))]]
        for order in permutations(groups):
            result=reconcile_observations(o for group in order for o in group)
            by_session=Counter()
            for event in result.events:by_session[event.record.session]+=event.record.tokens.total
            self.assertEqual(dict(by_session),{'portfolio-parent':300,'research-child':50,'second-child':60})
            self.assertNotIn('counter_reset',{i.code for i in result.issues})
            self.assertNotIn('cache_exceeds_input',{i.code for i in result.issues})
        # The first post-fork observation has no proven zero baseline.
        self.assertIn('baseline_reestablished',{i.code for i in result.issues})

    def test_index_reparses_cached_old_attribution_then_summary_detail_and_append_agree(self):
        self.write(events=[counter(100,10),counter(200,20),counter(300,50)],session='portfolio-parent')
        path=self.codex/'child.jsonl'
        path.write_text('\n'.join(map(json.dumps,child()))+'\n',encoding='utf-8')
        actual=extract_codex
        def legacy(entries,*args,**kwargs):
            return tuple(replace(o,conversation_id='portfolio-parent',fork_parent_id=None)
                         for o in actual(entries,*args,**kwargs))
        with patch('usage_ingestion.extract_codex',side_effect=legacy),patch('usage_index.PARSER_CACHE_VERSION','observations-v1:project-context-2'):
            self.store.import_settings()
        old=self.overview()
        self.assertEqual(old['data']['summary']['conversation_count'],1)
        # Unchanged source bytes must be re-extracted when the parser cache changes.
        self.store.import_settings()
        current=self.overview()
        self.assertEqual(current['data']['summary']['tokens']['total_tokens'],'350')
        self.assertEqual(current['data']['summary']['conversation_count'],2)
        self.assertNotEqual(current['usage_revision'],old['usage_revision'])
        self.error(409,lambda:self.overview(self.frozen(old)))
        params=self.frozen(current)
        listing=self.query.read('/usage/conversations',params)['data']['items']
        self.assertEqual({r['label']:int(r['summary']['tokens']['total_tokens']) for r in listing},
                         {'portfolio-parent':300,'research-child':50})
        for row in listing:
            detail=self.query.read('/conversations/'+row['id'],params)
            events=self.query.read('/conversations/'+row['id']+'/events',params)
            self.assertEqual(row['summary'],detail['data']['summary'])
            self.assertEqual(row['summary'],events['data']['summary'])
        self.assertEqual(sum(int(d['summary']['tokens']['total_tokens']) for d in current['data']['days']),350)
        self.store.import_settings()
        self.assertEqual(self.overview()['usage_revision'],current['usage_revision'])
        with path.open('a',encoding='utf-8') as stream:stream.write(json.dumps(counter(190,45))+'\n')
        self.store.import_settings()
        self.assertEqual(self.overview()['data']['summary']['tokens']['total_tokens'],'390')
        self.assertEqual(self.overview({'provider':['codex']})['data']['summary']['tokens']['total_tokens'],'390')
        with patch('usage_index.verified_prefix',return_value=(None,None,[])):
            self.store.import_settings()
        self.assertEqual(self.overview()['data']['summary']['tokens']['total_tokens'],'390')
