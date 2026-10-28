"""Production API gates: real SQLite, synthetic roots, HTTP and owned processes."""
from contextlib import closing
from dataclasses import replace
from datetime import datetime,timezone
from decimal import Decimal
import http.client
import json
from pathlib import Path
import subprocess
import sys
import threading
import time
import unittest
from unittest.mock import patch
from urllib.parse import urlencode,quote

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from test_index import IndexFixture,counter,claude,NOW,context,ROOT
from usage_api import ApiService
from usage_api_contract import ApiError,validate_schema,strict_json
from usage_api_query import QueryService
from usage_api_runtime import HubOwner,reuse_owner
from usage_hub import create_server
from usage_jobs import JobController
from usage_runtime import PollingRuntime,AlreadyRunning
from usage_core import Snapshot,Window,UsageError
from usage_config import load_settings,settings_data,save_settings
from usage_index import UsageIndex
from usage_index_db import IndexBusy,IndexUnavailable,transaction


class ApiFixture(IndexFixture):
    def setUp(self):
        super().setUp()
        self.write(events=[counter(100,10),counter(200,20)])
        self.store.import_settings()
        self.jobs=JobController(self.store)
        self.runtime=PollingRuntime({})
        self.service=ApiService(self.store,self.jobs,self.runtime,clock=lambda:NOW)
        self.query=self.service.queries
        self.addCleanup(self.runtime.close)
        self.addCleanup(self.jobs.close)

    def overview(self,params=None):return self.query.read('/overview',params or {})
    def frozen(self,response,**extra):return {'query_context_id':[response['query_context_id']],**extra}
    def error(self,status,call):
        with self.assertRaises(ApiError) as captured:call()
        self.assertEqual(captured.exception.status,status)
        return captured.exception


class FrozenQueryGates(ApiFixture):
    def test_alignment_exact_wire_totals_and_all_endpoint_reconciliation(self):
        item=counter(1010000,10,cached=1000000,output=1830000)
        item['payload']['info']['total_token_usage']['reasoning_output_tokens']=1260000
        self.write(events=[item])
        (self.claude/'a.jsonl').write_text(json.dumps(claude())+'\n',encoding='utf-8')
        self.store.import_settings()
        response=self.overview()
        value=response['data']['summary']
        self.assertEqual(value['tokens']['total_tokens'],'2905000')
        self.assertEqual(Decimal(value['value']['amount_usd']),Decimal('18.891'))
        self.assertEqual(value['tokens']['reasoning_tokens'],'1260000')
        self.assertEqual(value['reasoning']['unknown_records'],1)
        self.assertEqual(Decimal(response['data']['combined_comparison']['difference_usd']),Decimal('-21.109'))
        params=self.frozen(response)
        listing=self.query.read('/usage/conversations',params)
        self.assertEqual(sum(int(row['summary']['tokens']['total_tokens']) for row in listing['data']['items']),2905000)
        self.assertEqual(listing['data']['summary'],value)
        for row in listing['data']['items']:
            detail=self.query.read('/conversations/'+row['id'],params)
            events=self.query.read('/conversations/'+row['id']+'/events',params)
            self.assertEqual(detail['data']['summary'],row['summary'])
            self.assertEqual(events['data']['summary'],row['summary'])
            self.assertEqual(sum(int(event['tokens']['total_tokens']) for event in events['data']['items']),int(row['summary']['tokens']['total_tokens']))
            self.assertTrue(all(event['occurred_at'].endswith('Z') for event in events['data']['items']))
        self.assertEqual(sum(int(row['summary']['tokens']['total_tokens']) for row in response['data']['days']),2905000)

    def test_cached_core_results_validate_publication_freshness_filters_and_read_failures(self):
        first=self.overview();params=self.frozen(first)
        # Reusing typed results must not cache mutable DTOs, skip snapshot reads,
        # or hide stale source state without a usage-revision change.
        first['data']['summary']['tokens']['total_tokens']='999'
        self.assertEqual(self.overview(params)['data']['summary']['tokens']['total_tokens'],'200')
        selected=self.overview({'base_query_context_id':[first['query_context_id']],'model':['absent']})
        self.assertEqual(selected['data']['summary']['value']['state'],'empty')
        with self.store.connection() as connection,transaction(connection,True):
            connection.execute("UPDATE datasets SET freshness='stale',code='interrupted' WHERE id=?",(self.store.dataset_id,))
        stale=self.overview(params)
        self.assertEqual(stale['usage_revision'],first['usage_revision'])
        self.assertEqual(stale['data']['freshness'],'stale')
        self.assertEqual(next(r for r in stale['data']['coverage'] if r['provider']=='codex')['state'],'stale')
        with patch.object(self.store,'read_snapshot',side_effect=IndexUnavailable('controlled read failure')):
            with self.assertRaises(IndexUnavailable):self.overview(params)
        self.write(events=[counter(300,30)]);self.store.import_settings()
        self.error(409,lambda:self.overview(params))
        self.assertEqual(self.overview()['data']['summary']['tokens']['total_tokens'],'300')
        # A fee-only publication invalidates old contexts without changing facts.
        before=self.overview();self.change_settings(codex_fee='21')
        self.store.reprice();self.error(409,lambda:self.overview(self.frozen(before)))
        current=self.overview()
        self.assertEqual(current['usage_revision'],before['usage_revision'])
        self.assertEqual(current['data']['summary'],before['data']['summary'])
        self.assertEqual(Decimal(next(r for r in current['data']['comparisons'] if r['provider']=='codex')['fee_usd']),Decimal('21'))

    def test_owner_reader_detects_external_commits_and_never_hides_read_failure(self):
        from usage_index_db import IndexRecoveryError
        cached=QueryService(self.store,clock=lambda:NOW,cache_snapshot=True)
        try:
            first=cached.read('/overview',{})
            params=self.frozen(first)
            # Both snapshot AND result reuse must invalidate after an external
            # commit, even if direct SQL neglected publication version updates.
            with self.store.connection() as connection,transaction(connection,True):
                row=connection.execute('SELECT id,payload FROM events LIMIT 1').fetchone()
                altered=json.loads(row['payload']);altered['record']['effort']='changed'
                connection.execute('UPDATE events SET payload=? WHERE id=?',(json.dumps(altered),row['id']))
            changed=cached.read('/overview',params)
            self.assertEqual({r['effort'] for r in changed['data']['models']},{'changed','high'})
            with self.store.connection() as connection,transaction(connection,True):
                connection.execute("UPDATE datasets SET freshness='stale',code='interrupted' WHERE id=?",(self.store.dataset_id,))
            changed=cached.read('/overview',params)
            self.assertEqual(changed['data']['freshness'],'stale')
            # External SQL changes invalidate the owner snapshot even if the
            # caller failed to advance publication versions. Corruption fails.
            with self.store.connection() as connection,transaction(connection,True):
                row=connection.execute('SELECT id,payload FROM events LIMIT 1').fetchone()
                damaged=json.loads(row['payload']);damaged['event_anchor']='damaged'
                connection.execute('UPDATE events SET payload=? WHERE id=?',(json.dumps(damaged),row['id']))
            with self.assertRaises(IndexRecoveryError):cached.read('/overview',params)
            self.assertIsNone(cached.reader.connection)
            # Recovery has to read storage again, not resurrect the cached view.
            with self.store.connection() as connection,transaction(connection,True):
                connection.execute('UPDATE events SET payload=? WHERE id=?',(row['payload'],row['id']))
            self.assertEqual(cached.read('/overview',params)['data']['summary']['tokens']['total_tokens'],'200')
            original=self.path.with_name('preserved.sqlite3')
            cached.close()
            self.path.rename(original)
            with self.assertRaises(OSError):cached.read('/overview',params)
            original.rename(self.path)
        finally:cached.close()
        self.assertIsNone(cached.reader.connection)

    def test_self_omitting_facets_preserve_all_other_active_filters(self):
        self.write('other.jsonl',[counter(50,10)],session='other',model='other-model',project='C:/other')
        self.store.import_settings()
        one=self.overview({'model':['fixture-model'],'effort':['high']})
        facets=self.query.read('/usage/facets',self.frozen(one))['data']
        self.assertEqual({r['value']:r['record_count'] for r in facets['models']},{'fixture-model':2,'other-model':1})
        self.assertEqual({r['value']:r['record_count'] for r in facets['efforts']},{'high':2})
        self.assertEqual(sum(r['record_count'] for r in facets['projects']),2)
        none=self.overview({'model':['fixture-model'],'effort':['absent']})
        facets=self.query.read('/usage/facets',self.frozen(none))['data']
        self.assertEqual({r['value']:r['record_count'] for r in facets['models']},{'fixture-model':0})
        self.assertEqual({r['value']:r['record_count'] for r in facets['efforts']},{'absent':0,'high':2})

    def test_clock_advance_keeps_range_context_across_facets_pages_and_detail(self):
        first=self.overview();params=self.frozen(first)
        self.query.clock=lambda:NOW+40*86400
        for path in ('/overview','/usage/conversations','/usage/projects','/usage/facets'):
            follow=self.query.read(path,params)
            self.assertEqual(follow['range'],first['range'])
            self.assertEqual(follow['query_context_id'],first['query_context_id'])
        derived=self.overview({'base_query_context_id':[first['query_context_id']],'provider':['codex'],'q':['fixture']})
        self.assertEqual(derived['range'],first['range'])
        self.assertNotEqual(derived['query_context_id'],first['query_context_id'])
        refreshed=self.overview()
        self.assertNotEqual(refreshed['range']['end_at'],first['range']['end_at'])
        self.assertEqual(refreshed['data']['summary']['value']['state'],'empty')

    def test_context_conflicts_stale_versions_and_restart_are_refreshable(self):
        first=self.overview()
        for params in ({'query_context_id':[first['query_context_id']],'provider':['codex']},
                       {'query_context_id':[first['query_context_id']],'period':['today']},
                       {'base_query_context_id':[first['query_context_id']],'timezone':['America/Los_Angeles']},
                       {'query_context_id':[first['query_context_id']],'base_query_context_id':[first['query_context_id']]}):
            self.error(422,lambda:self.overview(params))
        self.write(events=[counter(300,30)]);self.store.import_settings()
        self.assertEqual(self.error(409,lambda:self.overview(self.frozen(first))).code,'revision_changed')
        restarted=QueryService(self.store,clock=lambda:NOW)
        self.assertEqual(self.error(409,lambda:restarted.read('/overview',self.frozen(first))).code,'context_expired')

    def test_exact_key_cursor_ties_partial_zero_unpriced_and_full_headline(self):
        for i in range(5):self.write(str(i)+'.jsonl',[counter(100 if i<4 else 1000,10)],session='session-'+str(i),model='fixture-model' if i<4 else 'unknown')
        self.store.import_settings()
        first=self.query.read('/usage/conversations',{'page_size':['2']})
        expected=first['data']['summary']
        ids=[];response=first
        while True:
            ids.extend(row['id'] for row in response['data']['items'])
            self.assertEqual(response['data']['summary'],expected)
            cursor=response['data']['pagination']['next_cursor']
            if cursor is None:break
            response=self.query.read('/usage/conversations',self.frozen(first,page_size=['2'],cursor=[cursor]))
        self.assertEqual(len(ids),6);self.assertEqual(len(set(ids)),6)
        self.assertEqual(response['data']['items'][-1]['summary']['value']['state'],'unpriced')
        cursor=first['data']['pagination']['next_cursor']
        self.error(422,lambda:self.query.read('/usage/conversations',self.frozen(first,page_size=['3'],cursor=[cursor])))
        self.error(422,lambda:self.query.read('/usage/projects',self.frozen(first,page_size=['2'],cursor=[cursor])))
        self.error(422,lambda:self.query.read('/usage/conversations',self.frozen(first,page_size=['2'],cursor=[cursor[:-1]+('1' if cursor[-1]=='0' else '0')])))
        other=self.overview()
        self.error(409,lambda:self.query.read('/usage/conversations',self.frozen(other,page_size=['2'],cursor=[cursor])))
        # Equal priced values use stable IDs, not file/dictionary order.
        rows=self.query.read('/usage/conversations',self.frozen(first,page_size=['100']))['data']['items']
        tied=[r['id'] for r in rows if r['summary']['tokens']['total_tokens']=='100']
        self.assertEqual(tied,sorted(tied))

    def test_facet_omits_self_keeps_other_filters_and_selected_zero_matches(self):
        self.write('other.jsonl',[counter(50,10)],session='other',model='other-model',project='C:/other')
        self.store.import_settings()
        first=self.overview({'model':['fixture-model'],'effort':['not-recorded']})
        facets=self.query.read('/usage/facets',self.frozen(first))['data']
        self.assertTrue(any(row['value']=='not-recorded' and row['selected'] and row['record_count']==0 for row in facets['efforts']))
        # Omitting effort exposes the recorded effort under the selected model.
        self.assertTrue(any(row['value']=='high' and row['record_count']==2 for row in facets['efforts']))
        self.assertFalse(any(row['record_count'] for row in facets['models']))

    def test_normalized_project_ids_unknowns_and_multproject_conversation(self):
        self.write('alias.jsonl',[counter(50,10)],session='other',project='c:\\FIXTURE\\PROJECT')
        self.write('unknown.jsonl',[counter(25,10)],session='unknown',project=None)
        self.store.import_settings()
        response=self.query.read('/usage/projects',{})
        self.assertEqual(response['data']['summary']['project_count'],1)
        known=next(row for row in response['data']['items'] if row['summary']['project_count']==1)
        selected=self.overview({'project_id':[known['id']]})
        self.assertEqual(selected['data']['summary']['tokens']['total_tokens'],'250')
        self.assertFalse(selected['data']['combined_comparison']['available'])
        unknown=next(row for row in response['data']['items'] if row['summary']['project_count']==0)
        self.assertEqual(self.overview({'project_id':[unknown['id']]})['data']['summary']['tokens']['total_tokens'],'25')
        self.error(404,lambda:self.overview({'project_id':['foreign-dataset-id']}))

    def test_filters_and_request_bounds_are_strict_and_search_is_literal(self):
        for params in ({'provider':['']},{'provider':['both']},{'period':['custom']},{'timezone':['Missing/Zone']},
                       {'q':['x'*201]},{'page_size':['101']},{'page_size':['1.0']},{'sort':['arbitrary']},
                       {'provider':['codex']*65},{'model':['a','b']*33},{'q':['a','b']},{'unexpected':['x']},
                       {'cursor':['offset=10']},{'selected_day':['2026-09-01']},{'selected_day':['2026-10-32']}):
            self.error(422,lambda:self.overview(params))
        self.error(404,lambda:self.overview({'dataset_id':['other']}))
        self.assertEqual(self.overview({'q':['.* OR 1=1']})['data']['summary']['value']['state'],'empty')
        self.overview({'q':['ß'*200]})  # Length is checked before Unicode case folding.

    def test_lifetime_scope_is_distinct_from_empty_filtered_detail_and_events_are_chronological(self):
        first=self.query.read('/usage/conversations',{})
        identity=first['data']['items'][0]['id']
        empty=self.overview({'q':['nothing']})
        detail=self.query.read('/conversations/'+identity,self.frozen(empty))['data']
        self.assertEqual(detail['summary']['value']['state'],'empty')
        self.assertIsNotNone(detail['lifetime_first_at'])
        events=self.query.read('/conversations/'+identity+'/events',self.frozen(first,page_size=['1']))
        self.assertEqual(events['data']['pagination']['sort'],'events')
        next_page=self.query.read('/conversations/'+identity+'/events',self.frozen(first,page_size=['1'],cursor=[events['data']['pagination']['next_cursor']]))
        self.assertLess(events['data']['items'][0]['occurred_at'],next_page['data']['items'][0]['occurred_at'])
        self.error(404,lambda:self.query.read('/conversations/unknown',self.frozen(first)))

    def test_selected_local_day_uses_dst_intersection_and_excludes_exact_end(self):
        path=self.write(events=[])
        from test_index import header
        items=header()
        for stamp,value in [('2026-11-01T08:30:00Z',100),('2026-11-01T09:30:00Z',200),('2026-11-02T08:00:00Z',300)]:
            item=counter(value,10);item['timestamp']=stamp;items.append(item)
        path.write_text('\n'.join(json.dumps(e) for e in items)+'\n',encoding='utf-8')
        self.store.import_settings();self.query.clock=lambda:datetime(2026,11,2,8,tzinfo=timezone.utc).timestamp()
        response=self.overview({'timezone':['America/Los_Angeles'],'selected_day':['2026-11-01']})
        self.assertEqual(response['data']['summary']['tokens']['total_tokens'],'200')
        span=response['range'];epoch=lambda text:datetime.fromisoformat(text.replace('Z','+00:00')).timestamp()
        self.assertEqual(epoch(span['effective_end_at'])-epoch(span['effective_start_at']),25*3600)
        self.assertFalse(response['data']['combined_comparison']['available'])
        self.error(422,lambda:self.overview({'timezone':['America/Los_Angeles'],'selected_day':['2026-11-02']}))

    def test_conversation_spanning_projects_models_preserves_filtered_and_lifetime_metadata(self):
        first=claude(session='shared',project='C:/one')
        second=claude(session='shared',project='C:/two');second['message']['id']='message-2';second['requestId']='request-2'
        second['message']['model']='other-model';second['timestamp']='2026-10-23T20:00:01Z'
        (self.claude/'multi.jsonl').write_text(json.dumps(first)+'\n'+json.dumps(second)+'\n',encoding='utf-8')
        self.store.import_settings()
        with self.store.connection() as connection:
            connection.execute("UPDATE files SET parser='observations-v1' WHERE provider='Claude'")
        from usage_index import observations_from_prefix as extractor
        with patch('usage_index.observations_from_prefix',wraps=extractor) as parsed:
            self.store.import_settings()
            self.assertEqual(parsed.call_count,1)  # Old extraction cache is reparsed even at the same fingerprint.
        listing=self.query.read('/usage/conversations',{'provider':['claude']})
        row=listing['data']['items'][0]
        self.assertEqual(len(row['project_ids']),2);self.assertEqual(len(row['models']),2)
        self.assertEqual(row['summary']['tokens']['total_tokens'],'130000')
        filtered=self.overview({'base_query_context_id':[listing['query_context_id']],'project_id':[row['project_ids'][0]]})
        detail=self.query.read('/conversations/'+row['id'],self.frozen(filtered))['data']
        self.assertEqual(detail['summary']['tokens']['total_tokens'],'65000')
        self.assertEqual(detail['lifetime_first_at'],'2026-10-23T20:00:00.000000Z')
        self.assertEqual(detail['lifetime_last_at'],'2026-10-23T20:00:01.000000Z')
        self.assertEqual(len(detail['project_ids']),1)

    def test_provider_offline_never_breaks_usage_or_polls_on_read(self):
        with patch.object(self.runtime,'refresh',side_effect=AssertionError('read cannot refresh')),patch.object(self.store,'import_settings',side_effect=AssertionError('read cannot scan')):
            self.assertEqual(self.service.read('/overview',{})['data']['summary']['tokens']['total_tokens'],'200')
            self.assertEqual(self.service.read('/limits',{})['data']['providers'][0]['state'],'unavailable')


class JobGates(ApiFixture):
    def test_duplicate_refresh_coalesces_and_status_survives_restart(self):
        first,new=self.jobs.submit();second,again=self.jobs.submit()
        self.assertTrue(new);self.assertFalse(again);self.assertEqual(first['id'],second['id'])
        self.assertEqual(first['status'],'queued')
        self.assertTrue(self.jobs.run_one())
        finished=self.jobs.get(first['id'])
        self.assertEqual(finished['status'],'succeeded')
        self.assertEqual(finished['resulting_versions']['usage_revision'],str(self.store.status()['usage_revision']))
        self.assertEqual(finished['counts']['files_reused'],1)
        self.assertEqual(JobController(self.store).get(first['id'])['status'],'succeeded')
        status=self.service.read('/status',{})['data']
        self.assertEqual(status['last_job']['id'],first['id'])
        self.assertEqual(status['last_job']['status'],'succeeded')
        self.assertTrue(status['last_import_completed_at'].endswith('Z'))

    def test_interrupted_job_and_superseded_configuration_have_durable_outcomes(self):
        first,_=self.jobs.submit()
        with self.store.connection() as connection:connection.execute("UPDATE jobs SET status='running' WHERE id=?",(first['id'],))
        restarted=JobController(self.store)
        self.assertEqual(restarted.get(first['id'])['code'],'interrupted')
        queued,_=restarted.submit('reprice')
        self.change_settings(codex_fee='30')
        restarted.run_one()
        self.assertEqual(restarted.get(queued['id'])['status'],'superseded')
        self.assertTrue(restarted.active())
        restarted.run_one()
        self.assertEqual(self.store.status()['configuration_version'],self.settings.version)

    def test_settings_version_validation_pending_and_reprice_do_not_mutate_facts(self):
        version=load_settings(self.config).version
        before=self.rows('SELECT id,payload FROM events ORDER BY id')
        saved=self.jobs.patch_settings({'expected_configuration_version':version,'changes':{'plan_fees_usd':{'Codex':'30','Claude':'20'}}})
        self.assertTrue(saved['pending']);self.assertEqual(saved['jobs'][0]['kind'],'reprice')
        self.assertTrue(self.store.status()['configuration_pending'])
        self.assertEqual(self.service.read('/overview',{})['configuration_version'],version)
        self.jobs.run_one()
        self.assertFalse(self.store.status()['configuration_pending'])
        self.assertEqual(before,self.rows('SELECT id,payload FROM events ORDER BY id'))
        self.error(409,lambda:self.jobs.patch_settings({'expected_configuration_version':version,'changes':{'timezone':'UTC'}}))
        self.error(422,lambda:self.jobs.patch_settings({'expected_configuration_version':saved['configuration_version'],'changes':{'credential':'bad'}}))
        repeated=self.jobs.patch_settings({'expected_configuration_version':saved['configuration_version'],'changes':{'plan_fees_usd':{'Codex':'30','Claude':'20'}}})
        self.assertEqual(repeated['jobs'],[])

    def test_api_money_inputs_require_decimal_strings_and_invalid_drafts_leave_json_unchanged(self):
        version=load_settings(self.config).version;before=self.config.read_bytes()
        for changes in ({'plan_fees_usd':{'Codex':20,'Claude':'20'}},
                        {'rate_overrides':{'model':{'input':1,'output':'2','cached':'0'}}},
                        {'plan_fees_usd':{'Codex':'-1','Claude':'20'}},
                        {'rate_overrides':{'model':{'input':'NaN','output':'2','cached':'0'}}}):
            self.error(422,lambda:self.jobs.patch_settings({'expected_configuration_version':version,'changes':changes}))
            self.assertEqual(before,self.config.read_bytes())
        saved=self.jobs.patch_settings({'expected_configuration_version':version,'changes':{'plan_fees_usd':{'Codex':None,'Claude':'0'}}})
        self.jobs.run_one()
        self.assertEqual(saved['settings']['plan_fees_usd'],{'Codex':None,'Claude':'0'})

    def test_busy_writer_rejects_settings_before_json_save_and_duplicate_job_still_coalesces(self):
        first,_=self.jobs.submit()
        before=self.config.read_bytes()
        with self.store.connection() as connection,transaction(connection,True):
            same,new=self.jobs.submit();self.assertFalse(new);self.assertEqual(same['id'],first['id'])
            with self.assertRaises(IndexBusy):self.jobs.patch_settings({'expected_configuration_version':load_settings(self.config).version,'changes':{'timezone':'America/Los_Angeles'}})
        self.assertEqual(before,self.config.read_bytes())

    def test_subset_refresh_keeps_unchanged_overlap_and_unselected_roots(self):
        first_root=self.codex/'first';second_root=self.codex/'second'
        self.write('first/a.jsonl',[counter(100,10),counter(200,20)])
        self.write('second/b.jsonl',[counter(200,20)])
        (self.codex/'a.jsonl').unlink()
        self.change_settings(codex_roots=[first_root,second_root]);self.store.import_settings()
        approved=self.jobs.roots()
        chosen=next(key for key,(_,path) in approved.items() if Path(path)==first_root)
        self.write('first/a.jsonl',[counter(100,10),counter(200,20),counter(300,30)])
        job,_=self.jobs.submit(root_ids=[chosen]);self.jobs.run_one()
        self.assertEqual(self.jobs.get(job['id'])['status'],'succeeded')
        self.assertEqual(self.overview()['data']['summary']['tokens']['total_tokens'],'300')
        self.assertEqual(self.rows('SELECT status FROM files WHERE path=?',(str((second_root/'b.jsonl').resolve()),)),[('accepted',)])
        self.error(404,lambda:self.jobs.submit(root_ids=['C:/arbitrary-path']))

    def test_disabled_approved_roots_can_be_reenabled_and_arbitrary_paths_cannot(self):
        keys=list(self.jobs.roots())
        version=load_settings(self.config).version
        saved=self.jobs.patch_settings({'expected_configuration_version':version,'changes':{'enabled_root_ids':[]}})
        self.jobs.run_one()
        self.assertFalse(any(root['enabled'] for root in self.jobs.editable()['approved_roots']))
        restored=self.jobs.patch_settings({'expected_configuration_version':saved['configuration_version'],'changes':{'enabled_root_ids':keys}})
        self.jobs.run_one()
        self.assertTrue(all(root['enabled'] for root in self.jobs.editable()['approved_roots']))
        self.assertEqual(self.overview()['data']['summary']['tokens']['total_tokens'],'200')

    def test_failure_is_safe_retains_previous_publication_and_does_not_retry_immediately(self):
        job,_=self.jobs.submit()
        with patch.object(self.store,'import_settings',side_effect=OSError('PRIVATE_JOB_SENTINEL')):self.jobs.run_one()
        result=self.jobs.get(job['id'])
        self.assertEqual(result['status'],'failed');self.assertNotIn('PRIVATE_JOB_SENTINEL',json.dumps(result))
        self.assertFalse(self.jobs.active());self.assertEqual(self.overview()['data']['summary']['tokens']['total_tokens'],'200')

    def test_process_exit_after_publication_retains_successful_job_and_new_tuple(self):
        self.write(events=[counter(300,30)])
        job,_=self.jobs.submit()
        code='import sys,os\nsys.path.insert(0,sys.argv[1])\nfrom usage_index import UsageIndex\nfrom usage_jobs import JobController\nx=UsageIndex(sys.argv[2],config_path=sys.argv[3])\nj=JobController(x)\noriginal=x.import_settings\ndef killed(**kwargs):\n    original(**kwargs)\n    os._exit(17)\nx.import_settings=killed\nj.run_one()'
        child=subprocess.run([sys.executable,'-c',code,str(ROOT),str(self.path),str(self.config)],capture_output=True,text=True,timeout=15,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        self.assertEqual(child.returncode,17,child.stderr)
        restarted=JobController(self.store)
        self.assertEqual(restarted.get(job['id'])['status'],'succeeded')
        self.assertEqual(restarted.get(job['id'])['resulting_versions']['usage_revision'],str(self.store.status()['usage_revision']))
        self.assertEqual(self.overview()['data']['summary']['tokens']['total_tokens'],'300')

    def test_json_saved_before_job_commit_recovers_without_resetting_history(self):
        self.change_settings(codex_fee='35')
        self.assertTrue(self.store.status()['configuration_pending'])
        restarted=JobController(self.store);restarted.recover_configuration();restarted.run_one()
        self.assertFalse(self.store.status()['configuration_pending'])
        self.assertEqual(self.overview()['data']['summary']['tokens']['total_tokens'],'200')


class HttpFixture(ApiFixture):
    def setUp(self):
        super().setUp()
        self.server=create_server(self.service,0)
        self.origin='http://127.0.0.1:'+str(self.server.server_port)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.addCleanup(self.stop_server)
        self.cookie=None;self.csrf=None

    def stop_server(self):self.server.shutdown();self.server.server_close();self.thread.join(timeout=2)
    def request(self,method,path,body=None,headers=None,authenticated=False):
        values={} if headers is None else dict(headers)
        if authenticated:
            values.setdefault('Cookie',self.cookie)
            if method!='GET':values.setdefault('Origin',self.origin);values.setdefault('X-Usage-CSRF',self.csrf)
        if body is not None and not isinstance(body,(str,bytes)):
            body=json.dumps(body);values.setdefault('Content-Type','application/json')
        connection=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=5)
        try:
            connection.request(method,path,body=body,headers=values)
            response=connection.getresponse();raw=response.read()
            return response.status,dict(response.getheaders()),json.loads(raw) if 'application/json' in response.getheader('Content-Type','') else raw
        finally:connection.close()
    def login(self):
        grant=self.server.sessions.issue()
        status,headers,body=self.request('POST','/api/v1/session/bootstrap',{'launch_token':grant},{'Origin':self.origin})
        self.assertEqual(status,200)
        self.cookie=headers['Set-Cookie'].split(';',1)[0];self.csrf=body['data']['csrf_token']
        return grant,headers


class HttpBoundaryGates(HttpFixture):
    def test_plain_root_never_grants_private_reads_and_launch_is_single_use(self):
        status,headers,_=self.request('GET','/')
        self.assertEqual(status,200);self.assertNotIn('Set-Cookie',headers)
        self.assertEqual(self.request('GET','/api/v1/overview')[0],403)
        grant,headers=self.login()
        self.assertIn('HttpOnly',headers['Set-Cookie']);self.assertIn('SameSite=Strict',headers['Set-Cookie'])
        self.assertEqual(self.request('GET','/api/v1/overview',authenticated=True)[0],200)
        self.assertEqual(self.request('POST','/api/v1/session/bootstrap',{'launch_token':grant},{'Origin':self.origin})[0],403)
        self.assertNotIn('Access-Control-Allow-Origin',headers)

    def test_host_origin_fetch_metadata_csrf_and_unauthenticated_boundaries(self):
        self.login()
        for headers in ({'Host':'evil.example'},{'Host':'localhost:'+str(self.server.server_port)},
                        {'Origin':'https://evil.example'},{'Sec-Fetch-Site':'cross-site'},{'Sec-Fetch-Site':'same-site'}):
            self.assertEqual(self.request('GET','/api/v1/overview',headers=headers,authenticated=True)[0],403)
        for headers in ({'X-Usage-CSRF':'bad'},{'Origin':'https://evil.example'}):
            self.assertEqual(self.request('POST','/api/v1/index/refresh',{},headers,True)[0],403)
        self.assertEqual(self.request('POST','/api/v1/index/refresh',{},headers={'Cookie':self.cookie,'X-Usage-CSRF':self.csrf})[0],403)
        self.assertEqual(self.request('OPTIONS','/api/v1/status',headers={'Origin':'https://evil.example'})[0],403)
        self.assertEqual(self.request('POST','/api/v1/local/launch',{},authenticated=True)[0],403)

    def test_http_input_errors_are_bounded_safe_and_jobs_return_accepted_or_coalesced(self):
        self.login()
        for path in ('/api/v1/overview?provider=','/api/v1/overview?page_size=999','/api/v1/overview?timezone=PRIVATE_SENTINEL','/api/v1/overview?q=a&q=b'):
            status,headers,body=self.request('GET',path,authenticated=True)
            self.assertEqual(status,422);self.assertEqual(body['error']['code'],'invalid_input');self.assertNotIn('PRIVATE_SENTINEL',json.dumps(body))
        self.assertEqual(self.request('POST','/api/v1/index/refresh',{'path':'C:/private'},authenticated=True)[0],422)
        first=self.request('POST','/api/v1/index/refresh',{},authenticated=True)
        second=self.request('POST','/api/v1/index/refresh',{},authenticated=True)
        self.assertEqual((first[0],second[0]),(202,200));self.assertEqual(first[2]['data']['id'],second[2]['data']['id'])
        for raw in ('{"x":1,"x":2}','{"root_ids":NaN}'):
            self.assertEqual(self.request('POST','/api/v1/index/refresh',raw,{'Content-Type':'application/json'},True)[0],422)
        self.assertEqual(self.request('POST','/api/v1/index/refresh','{}',{'Content-Type':'text/plain'},True)[0],422)
        self.assertEqual(self.request('GET','/api/preview/query',authenticated=True)[0],404)

    def test_expiring_grants_sessions_and_response_privacy_headers(self):
        self.server.sessions.monotonic=lambda:0
        token=self.server.sessions.issue();self.server.sessions.monotonic=lambda:31
        self.assertEqual(self.request('POST','/api/v1/session/bootstrap',{'launch_token':token},{'Origin':self.origin})[0],403)
        self.server.sessions.monotonic=lambda:100;self.login()
        self.server.sessions.monotonic=lambda:3701
        self.assertEqual(self.request('GET','/api/v1/settings',authenticated=True)[0],403)
        status,headers,_=self.request('GET','/')
        self.assertEqual(headers['Referrer-Policy'],'no-referrer');self.assertEqual(headers['Cache-Control'],'no-store')
        self.assertIn("frame-ancestors 'none'",headers['Content-Security-Policy'])

    def test_encoded_conversation_ids_and_malformed_url_encodings(self):
        self.login()
        response=self.request('GET','/api/v1/usage/conversations',authenticated=True)[2]
        identity=response['data']['items'][0]['id']
        path='/api/v1/conversations/'+quote(identity,safe='')+'?query_context_id='+response['query_context_id']
        status,_,detail=self.request('GET',path,authenticated=True)
        self.assertEqual(status,200);self.assertEqual(detail['data']['id'],identity)
        for path in ('/api/v1/overview?q=%ZZ','/api/v1/overview?q=%ff','/api/v1/overview#ignored'):
            self.assertEqual(self.request('GET',path,authenticated=True)[0],422)

    def test_multitab_handoffs_reuse_session_and_reload_resumes_without_new_grant(self):
        self.login();cookie,csrf=self.cookie,self.csrf
        grant=self.server.sessions.issue()
        status,headers,body=self.request('POST','/api/v1/session/bootstrap',{'launch_token':grant},{'Origin':self.origin,'Cookie':cookie})
        self.assertEqual(status,200);self.assertEqual(headers['Set-Cookie'].split(';',1)[0],cookie)
        self.assertEqual(body['data']['csrf_token'],csrf)
        resumed=self.request('GET','/api/v1/session',authenticated=True)
        self.assertEqual(resumed[0],200);self.assertEqual(resumed[2]['data']['csrf_token'],csrf)
        self.assertNotIn('Set-Cookie',resumed[1])
        self.assertEqual(self.request('GET','/api/v1/session')[0],403)
        self.assertEqual(self.request('GET','/api/v1/session',headers={'Origin':'https://evil.example'},authenticated=True)[0],403)
        self.assertEqual(self.request('POST','/api/v1/index/refresh',{},authenticated=True)[0],202)

    def test_duplicate_host_and_oversized_body_rejected(self):
        connection=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=5)
        try:
            connection.putrequest('GET','/api/v1/status');connection.putheader('Host','evil.example');connection.endheaders()
            response=connection.getresponse();response.read();self.assertEqual(response.status,403)
        finally:connection.close()
        self.login()
        headers={'Origin':self.origin,'Cookie':self.cookie,'X-Usage-CSRF':self.csrf,'Content-Type':'application/json','Content-Length':'1048577'}
        self.assertEqual(self.request('POST','/api/v1/index/refresh',b'',headers)[0],422)


class OwnerAndLimitGates(ApiFixture):
    def test_owner_reuse_multiclient_same_writer_and_relaunch_after_quit(self):
        owner_path=self.base/'runtime.lock'
        owner=HubOwner(index_path=self.path,config_path=self.config,owner_path=owner_path,port=0)
        try:
            owner.start(start_jobs=False)
            second=HubOwner(index_path=self.path,config_path=self.config,owner_path=owner_path,port=0)
            with self.assertRaises(AlreadyRunning):second.start(start_jobs=False)
            url=reuse_owner(second,timeout=.5)
            self.assertTrue(url.startswith(owner.origin+'/#launch='));self.assertFalse(second.runtime.started)
            self.assertEqual(owner.index.dataset_id,self.store.dataset_id)
        finally:self.assertTrue(owner.close())
        self.assertFalse(owner.discovery.exists())
        next_owner=HubOwner(index_path=self.path,config_path=self.config,owner_path=owner_path,port=0)
        try:next_owner.start(start_jobs=False)
        finally:self.assertTrue(next_owner.close())

    def test_explicit_cli_is_offline_reuses_owner_and_rejects_competing_settings_save(self):
        import os
        appdata=self.base/'cli-appdata'
        env=os.environ.copy();env['LOCALAPPDATA']=str(appdata)
        entry=ROOT/'usage_api_main.py'
        command=[sys.executable,'-u',str(entry),'--port','0','--index',str(self.path),'--config',str(self.config)]
        child=subprocess.Popen(command,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,env=env,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        try:
            discovery=appdata/'UsageTray'/'runtime.api.json'
            deadline=time.monotonic()+10
            while not discovery.exists() and child.poll() is None and time.monotonic()<deadline:time.sleep(.025)
            self.assertTrue(discovery.exists(),'Explicit API CLI did not start within ten seconds.')
            reused=subprocess.run(command,capture_output=True,text=True,timeout=15,env=env,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            self.assertEqual(reused.returncode,0,reused.stderr)
            self.assertIn('Reusing the existing local API owner',reused.stdout)
            before=self.config.read_bytes()
            saved=subprocess.run([sys.executable,str(ROOT/'usage_tray.py'),'--save-settings','--config',str(self.config),'--codex-plan-usd','99'],capture_output=True,text=True,timeout=10,env=env,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            self.assertEqual(saved.returncode,3);self.assertEqual(before,self.config.read_bytes())
            self.assertNotIn('launch=',reused.stdout)
        finally:
            child.terminate()
            try:child.communicate(timeout=10)
            except subprocess.TimeoutExpired:child.kill();child.communicate(timeout=5)

    def test_simulated_tray_reuses_owner_runtime_and_committed_report_query(self):
        import types
        import usage_tray as tray
        saved=threading.Event()
        class Item:
            def __init__(self,text,action=None,**kwargs):self.text,self.action=text,action
        class Menu:
            SEPARATOR=object()
            def __init__(self,items):self.items=items
        class Icon:
            def __init__(self,*args):self.menu=args[3]
            def update_menu(self):pass
            def stop(self):pass
            def run(self,setup):
                setup(self)
                next(item for item in self.menu.items() if isinstance(item,Item) and item.text.startswith('This month')).action(self,None)
                if not saved.wait(5):raise AssertionError('Committed tray report was not produced.')
                next(item for item in self.menu.items() if isinstance(item,Item) and item.text=='Quit').action(self,None)
        fake=types.SimpleNamespace(Icon=Icon,Menu=Menu,MenuItem=Item)
        owner=HubOwner(index_path=self.path,config_path=self.config,owner_path=self.base/'tray.lock',port=0)
        try:
            owner.start(start_jobs=False)
            with patch.dict(sys.modules,{'pystray':fake}),patch.object(tray,'PollingRuntime',side_effect=AssertionError('no second scheduler')),patch.object(tray,'query_usage',side_effect=AssertionError('use committed index')),patch.object(tray,'save_report',side_effect=lambda report,**kwargs:(self.assertEqual(report.total.tokens.total,200),self.base/'report.txt')[1]),patch.object(tray,'open_report',side_effect=lambda *args:saved.set()):
                tray.run_tray(shared_runtime=owner.runtime,report_query=owner.query_tray)
            self.assertTrue(owner.runtime.started)
            self.assertTrue(owner.runtime.stop.is_set())
        finally:owner.close()

    def test_actual_second_process_uses_native_handoff_without_another_owner(self):
        marker=self.base/'owner-ready'
        owner_path=self.base/'process.lock'
        code="import sys;from pathlib import Path;sys.path.insert(0,sys.argv[1]);from usage_api_runtime import HubOwner;x=HubOwner(index_path=Path(sys.argv[2]),config_path=Path(sys.argv[3]),owner_path=Path(sys.argv[4]),port=0);x.start(start_jobs=False);Path(sys.argv[5]).write_text('ready');sys.stdin.readline();x.close()"
        child=subprocess.Popen([sys.executable,'-u','-c',code,str(ROOT),str(self.path),str(self.config),str(owner_path),str(marker)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        try:
            deadline=time.monotonic()+10
            while not marker.exists() and child.poll() is None and time.monotonic()<deadline:time.sleep(.025)
            self.assertTrue(marker.exists(),'Synthetic owner did not start within ten seconds.')
            second=HubOwner(index_path=self.path,config_path=self.config,owner_path=owner_path,port=0)
            with self.assertRaises(AlreadyRunning):second.start(start_jobs=False)
            self.assertIn('/#launch=',reuse_owner(second,timeout=1))
        finally:
            try:child.communicate('\n',timeout=10)
            except subprocess.TimeoutExpired:child.kill();child.communicate(timeout=5)
        self.assertEqual(child.returncode,0)

    def test_provider_cooldown_inprogress_mixed_results_and_cached_snapshot_persistence(self):
        started=threading.Event();release=threading.Event();calls=[]
        def fetch():
            calls.append(1);started.set();release.wait(5)
            return Snapshot('Codex',[Window('primary',25,NOW+100,300)],checked_at=NOW)
        runtime=PollingRuntime({'Codex':fetch})
        service=ApiService(self.store,self.jobs,runtime,clock=lambda:NOW)
        try:
            code,data=service.limits.refresh({'providers':['codex','claude']})
            self.assertEqual(code,202);self.assertEqual([row['state'] for row in data['providers']],['accepted','unavailable'])
            self.assertEqual(service.limits.refresh({'providers':['codex']})[1]['providers'][0]['state'],'in_progress')
            runtime.start();self.assertTrue(started.wait(2))
            self.assertEqual(service.limits.refresh({'providers':['codex']})[0],200)
            release.set()
            deadline=time.monotonic()+3
            while runtime.states[0].view().phase=='refreshing' and time.monotonic()<deadline:time.sleep(.025)
            self.assertEqual(service.limits.refresh({'providers':['codex']})[0],429)
            self.assertEqual(service.limits.read()[0]['snapshot']['windows'][0]['used_percent'],25)
            service.limits.flush()
            restored=ApiService(self.store,self.jobs,PollingRuntime({}),clock=lambda:NOW)
            self.assertEqual(restored.limits.read()[0]['state'],'stale')
            self.assertEqual(restored.limits.read()[0]['scope'],'active_cli_account')
            self.assertEqual(len(calls),1)
        finally:release.set();runtime.close()

    def test_malformed_current_settings_leave_committed_usage_queryable(self):
        self.config.write_text('{bad',encoding='utf-8')
        owner=HubOwner(index_path=self.path,config_path=self.config,owner_path=self.base/'bad-settings.lock',port=0)
        try:
            owner.start()
            self.assertEqual(owner.service.read('/overview',{})['data']['summary']['tokens']['total_tokens'],'200')
            self.assertEqual(self.config.read_text(encoding='utf-8'),'{bad')
        finally:owner.close()


class ContractAndRecoveryGates(ApiFixture):
    def test_actual_and_checked_in_fixtures_validate_and_numeric_corruption_is_rejected(self):
        import copy
        from api_fixture_responses import responses
        root=ROOT.parent/'docs'/'api'
        schema=json.loads((root/'usage-hub-v1.schema.json').read_text(encoding='utf-8'))
        examples=responses(self)
        checked=json.loads((root/'usage-hub-v1.fixtures.json').read_text(encoding='utf-8'))
        self.assertEqual(set(examples),set(checked))
        for data in (*examples.values(),*checked.values()):validate_schema(data,schema)
        expected={'overview':('2905000','18.891'),'overview_codex':('2840000','18.42'),'overview_claude':('65000','.471')}
        for name,(token_value,money_value) in expected.items():
            value=examples[name]['data']['summary']
            self.assertEqual(value['tokens']['total_tokens'],token_value)
            self.assertEqual(Decimal(value['value']['amount_usd']),Decimal(money_value))
        self.assertEqual(examples['partial']['data']['summary']['value']['state'],'partial')
        self.assertEqual(examples['unpriced']['data']['summary']['value']['amount_usd'],None)
        self.assertEqual(examples['empty']['data']['summary']['value']['state'],'empty')
        self.assertEqual(Decimal(examples['priced_zero']['data']['summary']['value']['amount_usd']),Decimal(0))
        for field,bad in [('tokens',2905000),('value',18.891)]:
            changed=copy.deepcopy(examples['overview'])
            changed['data']['summary'][field]['total_tokens' if field=='tokens' else 'amount_usd']=bad
            with self.assertRaises(ValueError):validate_schema(changed,schema)
        changed=copy.deepcopy(examples['overview']);changed['data']['raw_provider_payload']={'content':'PRIVATE_SENTINEL'}
        with self.assertRaises(ValueError):validate_schema(changed,schema)
        encoded=json.dumps(examples)
        for forbidden in ('PRIVATE_RESPONSE_SENTINEL','PRIVATE_PROMPT_SENTINEL','launch_token','csrf_token','log_roots'):
            self.assertNotIn(forbidden,encoded)

    def test_openapi_references_resolve_and_declares_cookie_csrf_and_all_first_release_routes(self):
        root=ROOT.parent/'docs'/'api'
        spec=json.loads((root/'usage-hub-v1.openapi.json').read_text(encoding='utf-8'))
        schema=json.loads((root/'usage-hub-v1.schema.json').read_text(encoding='utf-8'))
        self.assertEqual(spec['openapi'],'3.1.0')
        self.assertEqual(len(spec['paths']),15)
        self.assertIn('/usage/analysis',spec['paths'])
        def walk(value):
            if isinstance(value,dict):
                if '$ref' in value:
                    path,fragment=value['$ref'].split('#')
                    self.assertEqual(path,'./usage-hub-v1.schema.json')
                    target=schema
                    for key in fragment.removeprefix('/').split('/'):target=target[key]
                for item in value.values():walk(item)
            elif isinstance(value,list):
                for item in value:walk(item)
        walk(spec)
        self.assertEqual(spec['paths']['/index/refresh']['post']['security'],[{'localSession':[],'csrf':[]}])
        self.assertEqual(spec['paths']['/session/bootstrap']['post']['security'],[])

    def test_malformed_settings_status_and_usage_survive_without_credential_polling(self):
        self.config.write_text('{bad',encoding='utf-8')
        status=self.service.read('/status',{})
        self.assertEqual(status['data']['configuration_state'],'invalid')
        self.assertEqual(self.service.read('/overview',{})['data']['summary']['tokens']['total_tokens'],'200')
        self.assertFalse(self.runtime.started)

    def test_failed_provider_check_keeps_each_window_and_last_successful_snapshot(self):
        calls=[]
        def good():calls.append(1);return Snapshot('Codex',[Window('primary',25,NOW+100,300),Window('weekly',50,None,10080)],checked_at=NOW)
        runtime=PollingRuntime({'Codex':good})
        service=ApiService(self.store,self.jobs,runtime,clock=lambda:NOW)
        try:
            state=runtime.states[0];state.refresh()
            first=service.limits.read()[0]
            state.next_check=0
            def fail():raise UsageError('Safe provider failure.',category='network_error')
            state.fetch=fail;state.refresh()
            after=service.limits.read()[0]
            self.assertEqual(after['state'],'stale');self.assertEqual(after['snapshot'],first['snapshot'])
            self.assertEqual(after['last_success_at'],first['last_success_at'])
            self.assertEqual(len(after['snapshot']['windows']),2)
            self.assertEqual(after['category'],'network_error')
            self.assertEqual(service.read('/overview',{})['data']['summary']['tokens']['total_tokens'],'200')
        finally:runtime.close()

    def test_native_capability_and_shutdown_never_release_ownership_while_work_is_alive(self):
        owner=HubOwner(index_path=self.path,config_path=self.config,owner_path=self.base/'shutdown.lock',port=0)
        owner.start(start_jobs=False)
        try:
            with patch.object(owner.jobs,'close',return_value=False):
                self.assertFalse(owner.close(timeout=0));self.assertIsNotNone(owner.owner)
                contender=HubOwner(index_path=self.path,config_path=self.config,owner_path=owner.owner_path,port=0)
                with self.assertRaises(AlreadyRunning):contender.start(start_jobs=False)
        finally:self.assertTrue(owner.close())

    def test_production_service_cannot_expose_real_limit_cache_through_demo_namespace(self):
        demo=UsageIndex(self.path,mode='demo',config_path=self.config)
        with self.assertRaises(ValueError):ApiService(demo,JobController(demo),PollingRuntime({}))

    def test_snapshot_work_budget_fails_explicitly_without_modifying_publication(self):
        from usage_index_db import IndexQueryBudget
        before=self.store.status()['usage_revision']
        with self.assertRaises(IndexQueryBudget):self.store.read_snapshot(max_events=1)
        with self.assertRaises(IndexQueryBudget):self.store.read_snapshot(max_bytes=1)
        self.assertEqual(self.store.status()['usage_revision'],before)
        self.assertEqual(self.overview()['data']['summary']['tokens']['total_tokens'],'200')

    def test_initial_unavailable_import_job_is_failed_not_successful_zero(self):
        other=self.base/'empty-index.sqlite3'
        self.change_settings(codex_roots=[self.base/'missing'],claude_roots=[])
        store=UsageIndex(other,config_path=self.config);jobs=JobController(store)
        try:
            job,_=jobs.submit();jobs.run_one()
            self.assertEqual(jobs.get(job['id'])['status'],'failed')
            self.assertFalse(store.status()['ready'])
            self.assertEqual(jobs.active(),[])
        finally:jobs.close()


if __name__=='__main__':unittest.main()
