"""S11 persistence gates use synthetic JSONL, real SQLite, and owned subprocesses."""
from dataclasses import replace
from contextlib import closing
from datetime import datetime, timezone
from decimal import Decimal
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import usage_index as index
import usage_index_db as db
import usage_index_codec as codec
from usage_config import Settings, effective_settings, load_settings, save_settings
from usage_ingestion import ScanIssue
from usage_observations import PARSER_VERSION
from usage_reconciliation import reconcile_observations
from usage_service import QueryContext, UsageFilters, build_usage_result, collect_usage
from usage_time import resolve_range, RangeContext
from usage_valuation import Price, build_catalog, MAX_TOKENS
from usage_runtime import RuntimeOwner

NOW = datetime(2026, 10, 24, 20, tzinfo=timezone.utc).timestamp()
ROOT = Path(__file__).resolve().parents[1]


def context(providers=('Codex', 'Claude'), *, now=NOW, period='month', zone='UTC', demo=False, filters=None):
    return QueryContext(tuple((provider, resolve_range(period, now, timezone=zone)) for provider in providers),
                        now, period, zone, filters or UsageFilters(), demo)


def header(session='same-session', project='C:/fixture/project', model='fixture-model'):
    return [{'type': 'session_meta', 'timestamp': '2026-10-23T19:00:00Z', 'payload': {'id': session, 'cwd': project}},
            {'type': 'turn_context', 'payload': {'model': model, 'effort': 'high'}}]


def counter(value, second, *, day='2026-10-23', cached=0, output=0):
    return {'type': 'event_msg', 'timestamp': f'{day}T20:00:{second:02d}Z', 'payload': {
        'type': 'token_count', 'info': {'total_token_usage': {
            'input_tokens': value, 'output_tokens': output, 'cached_input_tokens': cached}}}}


def claude(session='claude-session', project='C:/fixture/project'):
    return {'type': 'assistant', 'timestamp': '2026-10-23T20:00:00Z', 'sessionId': session, 'cwd': project,
            'requestId': 'request-1', 'message': {'id': 'message-1', 'model': 'fixture-claude',
            'content': [{'type': 'text', 'text': 'PRIVATE_RESPONSE_SENTINEL'}],
            'usage': {'input_tokens': 10000, 'output_tokens': 20000, 'cache_read_input_tokens': 30000,
                      'cache_creation_input_tokens': 5000}}}


class IndexFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.codex = self.base / 'codex'
        self.claude = self.base / 'claude'
        self.codex.mkdir(); self.claude.mkdir()
        self.config = self.base / 'settings.json'
        self.path = self.base / 'index.sqlite3'
        self.settings = effective_settings(Settings(), codex_roots=[self.codex], claude_roots=[self.claude], timezone='UTC',
            prices={'fixture-model': Price(2, 10, '.1'), 'fixture-claude': Price(4, 20, '.2', 5, 8)})
        save_settings(self.settings, self.config)
        self.store = index.UsageIndex(self.path, config_path=self.config)

    def write(self, name='a.jsonl', events=None, *, session='same-session', project='C:/fixture/project', model='fixture-model'):
        path = self.codex / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('\n'.join(json.dumps(item) for item in header(session, project, model) + (events or [])) + '\n', encoding='utf-8')
        return path

    def result(self, ctx=None):
        return self.store.query(context() if ctx is None else ctx).result

    def rows(self, query, args=()):
        with self.store.connection(True) as connection:
            return [tuple(row) for row in connection.execute(query, args)]

    def change_settings(self, **kwargs):
        self.settings = effective_settings(self.settings, **kwargs)
        save_settings(self.settings, self.config)


class ImportGates(IndexFixture):
    def test_overlap_every_root_order_restart_and_unchanged_import(self):
        self.write('complete/a.jsonl', [counter(100, 10), counter(200, 20)])
        self.write('partial/b.jsonl', [counter(200, 20)])
        revision = self.store.import_settings()
        self.assertEqual(self.result().total.tokens.total, 200)
        first = self.rows('SELECT id,payload FROM events ORDER BY id')
        links = self.rows('SELECT * FROM event_sources ORDER BY event,observation')
        with patch.object(index, 'observations_from_prefix', side_effect=AssertionError('unchanged files must not parse')):
            self.assertEqual(self.store.import_settings(), revision)
        self.assertEqual(self.rows('SELECT id,payload FROM events ORDER BY id'), first)
        self.assertEqual(self.rows('SELECT * FROM event_sources ORDER BY event,observation'), links)
        self.store = index.UsageIndex(self.path, config_path=self.config)
        self.assertEqual(self.result().total.tokens.total, 200)
        for roots in ([self.codex/'partial', self.codex/'complete'], [self.codex/'complete', self.codex/'partial']):
            self.change_settings(codex_roots=roots)
            self.store.import_settings()
            self.assertEqual(self.result().total.tokens.total, 200)
        self.assertEqual(len(self.rows('SELECT * FROM observations')), 3)
        self.assertEqual(self.store.status()['last_run']['status'], 'succeeded')

    def test_reset_and_append_reconcile_unchanged_copy(self):
        full = self.write('full.jsonl', [counter(100, 10), counter(200, 20)])
        self.write('tail.jsonl', [counter(200, 20)])
        self.store.import_settings()
        with full.open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(counter(50, 30))+'\n'+json.dumps(counter(100, 40))+'\n')
        self.store.import_settings()
        self.assertEqual(self.result().total.tokens.total, 250)
        self.assertIn('counter_reset', {row[0] for row in self.rows("SELECT code FROM issues WHERE kind='accounting'")})
        self.assertEqual(self.store.import_settings(), self.store.status()['usage_revision'])
        self.assertEqual(self.result().total.tokens.total, 250)

    def test_replacement_and_truncation_are_new_generations(self):
        path = self.write(events=[counter(100, 10), counter(200, 20)])
        self.store.import_settings()
        before = self.rows('SELECT generation FROM files')
        self.write(events=[counter(75, 10)], session='replacement')
        self.store.import_settings()
        self.assertEqual(self.result().total.tokens.total, 75)
        self.assertNotEqual(before, self.rows('SELECT generation FROM files'))
        path.unlink()
        self.write(events=[counter(99, 15)], session='new-file')
        self.store.import_settings()
        self.assertEqual(self.result().total.tokens.total, 99)
        path.write_text('', encoding='utf-8')
        self.store.import_settings()
        self.assertEqual(self.result().total.value.state, 'empty')

    def test_unreadable_missing_disabled_and_explicit_removal(self):
        path = self.write(events=[counter(100, 10)])
        self.store.import_settings()
        with patch.object(index, 'verified_prefix', return_value=(None,None,[ScanIssue('unreadable_file','Read failed.')])):
            self.store.import_settings()
        self.assertEqual(self.result().total.tokens.total, 100)
        self.assertEqual(self.result().sources[0].state, 'stale')
        path.unlink()
        self.store.import_settings()
        self.assertEqual(self.result().total.tokens.total, 100)
        self.assertEqual(self.rows('SELECT status FROM files')[0][0], 'retained_missing')
        self.change_settings(codex_roots=[])
        self.store.import_settings()
        self.assertEqual(self.rows('SELECT status FROM files')[0][0], 'retained_disabled')
        file_id = self.rows('SELECT id FROM files')[0][0]
        self.store.remove_retained([file_id])
        self.assertEqual(self.result().total.value.state, 'empty')
        self.assertEqual(self.rows('SELECT status FROM files')[0][0], 'removed')
        self.assertFalse(self.rows("SELECT code FROM issues WHERE code LIKE 'retained_%'"))
        self.assertEqual(len(self.rows('SELECT * FROM observations')), 0)
        self.assertTrue(self.config.exists())
        self.assertFalse(path.exists())  # Test removed it; index never creates/deletes source history.

    def test_partial_corruption_keeps_prior_file_and_first_prefix_is_qualified(self):
        path = self.write(events=[counter(100, 10),counter(200,20)])
        self.store.import_settings()
        path.write_text(path.read_text(encoding='utf-8')+'{"unfinished":', encoding='utf-8')
        self.store.import_settings()
        self.assertEqual(self.result().total.tokens.total, 200)
        self.assertEqual(self.result().sources[0].state, 'stale')
        self.write('new.jsonl', [counter(50, 30)], session='new')
        with (self.codex/'new.jsonl').open('a',encoding='utf-8') as stream:
            stream.write('{bad line}\n'+json.dumps(counter(500,40))+'\n')
        self.store.import_settings()
        self.assertEqual(self.result().total.tokens.total, 250)
        self.assertIn('malformed_record', self.result().sources[0].issue_counts)
        self.assertIsNone(self.result().sources[0].issues[0].excluded_tokens)

    def test_first_failure_is_unavailable_never_zero_or_demo(self):
        self.write(events=[counter(100,10)])
        def fault(stage):
            if stage == 'facts': raise RuntimeError('synthetic failure')
        with self.assertRaises(RuntimeError): self.store.import_settings(fault=fault)
        with self.assertRaises(db.IndexUnavailable): self.result()
        self.assertEqual(self.store.status()['freshness'], 'unavailable')
        self.assertEqual(self.rows('SELECT * FROM observations'), [])
        self.assertEqual(self.rows('SELECT * FROM events'), [])

    def test_each_publication_stage_rolls_back_all_candidate_facts(self):
        path = self.write(events=[counter(100,10)])
        self.store.import_settings()
        original = self.rows('SELECT * FROM events')
        self.write(events=[counter(200,20)])
        for target in ('parsed','valued','facts','before_commit'):
            def fault(stage):
                if stage == target: raise RuntimeError('synthetic failure')
            with self.subTest(stage=target), self.assertRaises(RuntimeError):
                self.store.import_settings(fault=fault)
            self.assertEqual(self.rows('SELECT * FROM events'), original)
            self.assertEqual(self.result().total.tokens.total, 100)
            self.assertEqual(self.store.status()['last_run']['status'], 'failed')
        self.store.import_settings()
        self.assertEqual(self.result().total.tokens.total, 200)

    def test_real_and_demo_are_separate_and_foreign_keys_enforce_namespace(self):
        self.write(events=[counter(100,10)])
        self.store.import_settings()
        demo = index.UsageIndex(self.path, mode='demo', config_path=self.config)
        self.assertNotEqual(demo.dataset_id, self.store.dataset_id)
        with self.assertRaises(db.IndexUnavailable): demo.query(context(demo=True))
        with self.assertRaises(ValueError): self.store.query(context(demo=True))
        with self.store.connection() as connection:
            self.assertEqual(connection.execute('PRAGMA foreign_keys').fetchone()[0],1)
            event_id = self.rows('SELECT id FROM events')[0][0]
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute('INSERT INTO event_sources VALUES (?,?,?)',(demo.dataset_id,event_id,'no-observation'))

    def test_privacy_nested_metadata_and_content_never_enter_database_or_backup(self):
        events = [counter(100,10)]
        events[0]['payload']['content'] = 'PRIVATE_PROMPT_SENTINEL'
        path = self.write(events=events)
        extra = {'type':'turn_context','payload':{'cwd':{'private':'PRIVATE_NESTED_SENTINEL'},'model':{'private':'PRIVATE_MODEL_SENTINEL'}}}
        with path.open('a',encoding='utf-8') as stream:
            stream.write(json.dumps(extra)+'\n')
        (self.claude/'a.jsonl').write_text(json.dumps(claude())+'\n',encoding='utf-8')
        self.store.import_settings()
        with self.store.connection(True) as connection:
            dump = '\n'.join(connection.iterdump())
        backup = self.store.backup()
        for sentinel in ('PRIVATE_PROMPT_SENTINEL','PRIVATE_RESPONSE_SENTINEL','PRIVATE_NESTED_SENTINEL','PRIVATE_MODEL_SENTINEL'):
            self.assertNotIn(sentinel,dump)
            self.assertNotIn(sentinel.encode(),backup.read_bytes())
        self.assertEqual(self.result().total.tokens.total,65100)


class ValuationAndQueryGates(IndexFixture):
    def test_alignment_totals_and_shared_service_equivalence_for_all_filters(self):
        item=counter(1010000,10,output=1830000,cached=1000000)
        item['payload']['info']['total_token_usage']['reasoning_output_tokens']=1260000
        self.write(events=[item])
        (self.claude/'a.jsonl').write_text(json.dumps(claude())+'\n',encoding='utf-8')
        self.store.import_settings()
        both = self.result()
        self.assertEqual(both.total.tokens.total,2905000)
        self.assertEqual(both.total.value.amount_usd,Decimal('18.891'))
        self.assertEqual((both.total.reasoning.known_tokens,both.total.reasoning.unknown_records),(1260000,1))
        self.assertEqual(both.combined_comparison.difference_usd,Decimal('-21.109'))
        for providers in (('Codex',),('Claude',),('Codex','Claude')):
            for filters in (UsageFilters(),UsageFilters(search='fixture'),UsageFilters(efforts=('high',)),
                            UsageFilters(models=('fixture-model',)),UsageFilters(selected_day='2026-10-23')):
                ctx = context(providers,filters=filters)
                direct = collect_usage('month',providers,roots=self.settings.roots(),now=NOW,timezone='UTC',filters=filters).query(dict(self.settings.rate_overrides),dict(self.settings.plan_fees_usd))
                indexed = self.result(ctx)
                self.assertEqual(indexed.total,direct.total)
                self.assertEqual(indexed.groups,direct.groups)
                self.assertEqual(indexed.comparisons,direct.comparisons)
                self.assertEqual(indexed.details,direct.details)
                for dimension in ('day','model','project','conversation'):
                    self.assertEqual(sum(g.summary.tokens.total for g in indexed.groups_for(dimension)),indexed.total.tokens.total)

    def test_reprice_exact_stored_money_no_event_mutation_and_offline_read_no_repricing(self):
        self.write(events=[counter(100,10)])
        revision = self.store.import_settings()
        facts = self.rows('SELECT * FROM events')
        before = self.result().total.value.amount_usd
        self.change_settings(prices={'fixture-model':Price(3,10,'.1')})
        self.assertTrue(self.store.status()['configuration_pending'])
        # Previous publication uses its own configuration/catalog until activation.
        self.assertEqual(self.result().total.value.amount_usd,before)
        self.assertEqual(self.store.reprice(),revision)
        self.assertEqual(self.rows('SELECT * FROM events'),facts)
        self.assertEqual(self.result().total.value.amount_usd,Decimal('.0003'))
        self.assertFalse(self.store.status()['configuration_pending'])
        with patch('usage_service.value_event',side_effect=AssertionError('query must not reprice')), patch.object(index,'verified_prefix',side_effect=AssertionError('query must not scan')):
            self.assertEqual(self.result().total.value.amount_usd,Decimal('.0003'))
        self.assertTrue(all(type(row[0]) is str for row in self.rows('SELECT amount FROM valuations WHERE amount IS NOT NULL')))

    def test_reprice_fault_preserves_old_active_catalog_and_pending_settings(self):
        self.write(events=[counter(100,10)])
        self.store.import_settings()
        before = self.store.query(context())
        self.change_settings(prices={'fixture-model':Price(20,10,'.1')})
        with self.assertRaises(RuntimeError):
            self.store.reprice(fault=lambda stage: (_ for _ in ()).throw(RuntimeError('interrupted')) if stage=='before_commit' else None)
        after = self.store.query(context())
        self.assertEqual(before.pricing_version,after.pricing_version)
        self.assertEqual(before.result.total,after.result.total)
        self.assertTrue(self.store.status()['configuration_pending'])
        index.UsageIndex(self.path,config_path=self.config).reprice()
        self.assertEqual(self.result().total.value.amount_usd,Decimal('.002'))

    def test_empty_unpriced_partial_and_zero_are_distinct(self):
        self.store.import_settings()
        self.assertEqual(self.result().total.value.state,'empty')
        self.write(events=[counter(100,10)],model='unknown-model')
        self.store.import_settings()
        self.assertEqual(self.result().total.value.state,'unpriced')
        self.assertIsNone(self.result().total.value.amount_usd)
        self.write('zero.jsonl',[counter(25,10)],session='zero',model='zero-model')
        self.change_settings(prices={'zero-model':Price(0,0,0)})
        self.store.import_settings()
        self.assertEqual(self.result().total.value.state,'partial')
        self.assertEqual(self.result().total.value.amount_usd,Decimal(0))
        zero = self.result(context(filters=UsageFilters(models=('zero-model',))))
        self.assertEqual(zero.total.value.state,'complete')
        self.assertEqual(zero.total.value.amount_usd,Decimal(0))
        self.assertEqual(zero.combined_comparison.reason,'filtered_query')

    def test_old_event_time_retained_and_float_boundaries_lossless(self):
        self.write(events=[counter(100,10,day='2026-09-23'),counter(200,20)])
        self.store.import_settings()
        self.assertEqual(len(self.rows('SELECT * FROM events')),2)
        self.assertEqual(self.result().total.tokens.total,100)
        old_end = datetime(2026,9,24,tzinfo=timezone.utc).timestamp()
        self.assertEqual(self.result(context(now=old_end)).total.tokens.total,100)
        events = self.rows('SELECT payload FROM events ORDER BY occurred_us')
        event = codec.event_from(codec.loads(events[-1][0]))
        exact = event.record.timestamp
        before = context(now=exact)
        after = context(now=exact+.000001)
        self.assertEqual(self.result(before).total.tokens.total,0)
        self.assertEqual(self.result(after).total.tokens.total,100)
        for value in (exact,exact+.0000002,0.,-0.25):
            self.assertEqual(codec.epoch(codec.instant(value)),value)

    def test_overflow_aborts_without_replacing_accepted_history(self):
        self.write(events=[counter(100,10)])
        self.store.import_settings()
        self.write(events=[counter(MAX_TOKENS+1,10)])
        with self.assertRaises(ValueError): self.store.import_settings()
        self.assertEqual(self.result().total.tokens.total,100)
        self.write(events=[counter(MAX_TOKENS,10)])
        self.write('other.jsonl',[counter(1,10)],session='other')
        with self.assertRaises(ValueError): self.store.import_settings()
        self.assertEqual(self.result().total.tokens.total,100)

    def test_project_identity_normalization_without_resolving_metadata(self):
        self.write(events=[counter(100,10)],project='C:/Work/Project')
        self.write('other.jsonl',[counter(50,10)],session='other',project='c:\\work\\project')
        self.store.import_settings()
        self.assertEqual(len(self.rows("SELECT * FROM projects WHERE kind='path'")),1)
        self.assertEqual(self.result().total.project_count,1)
        self.assertEqual(self.result().total.tokens.total,150)


class RecoveryAndConcurrencyGates(IndexFixture):
    def test_consistent_backup_restore_contains_wal_and_configuration(self):
        self.write(events=[counter(100,10)])
        self.store.import_settings()
        backup = self.store.backup()
        destination = self.base/'restored.sqlite3'
        restored_config = self.base/'restored-settings.json'
        index.restore_backup(backup,destination,config_destination=restored_config)
        restored = index.UsageIndex(destination,config_path=restored_config)
        self.assertEqual(restored.dataset_id,self.store.dataset_id)
        self.assertEqual(restored.query(context()).result.total,self.result().total)
        self.assertEqual(load_settings(restored_config).version,self.settings.version)
        with self.assertRaises(ValueError): index.restore_backup(backup,self.path)
        for _ in range(4): self.store.backup()
        self.assertEqual(len(list(backup.parent.glob('*.sqlite3'))),3)
        self.assertEqual(len(list(backup.parent.glob('*.settings.json'))),3)

    def test_readers_see_old_publication_during_writer_transaction(self):
        self.write(events=[counter(100,10)])
        self.store.import_settings()
        self.write(events=[counter(200,20)])
        seen=[]
        def read_during(stage):
            if stage=='facts': seen.append(self.result().total.tokens.total)
        self.store.import_settings(fault=read_during)
        self.assertEqual(seen,[100])
        self.assertEqual(self.result().total.tokens.total,200)
        with self.store.connection() as connection:
            self.assertEqual(connection.execute('PRAGMA journal_mode').fetchone()[0],'wal')
            self.assertEqual(connection.execute('PRAGMA busy_timeout').fetchone()[0],250)

    def test_cross_process_owner_rejects_second_writer_but_offline_read_works(self):
        self.write(events=[counter(100,10)])
        self.store.import_settings()
        marker = self.base/'owner-ready'
        code = "from pathlib import Path; import sys; sys.path.insert(0,sys.argv[1]); from usage_runtime import RuntimeOwner; owner=RuntimeOwner(Path(sys.argv[2])); owner.__enter__(); Path(sys.argv[3]).write_text('ready'); sys.stdin.readline(); owner.__exit__()"
        child = subprocess.Popen([sys.executable,'-u','-c',code,str(ROOT),str(self.store.owner_path),str(marker)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        try:
            deadline=time.monotonic()+10
            while not marker.exists() and child.poll() is None and time.monotonic()<deadline:
                time.sleep(.025)
            self.assertTrue(marker.exists(),'synthetic owner failed to become ready within ten seconds')
            with self.assertRaises(db.IndexBusy): self.store.import_settings()
            self.assertEqual(self.result().total.tokens.total,100)
        finally:
            try:
                child.communicate('\n',timeout=10)
            except subprocess.TimeoutExpired:
                child.kill(); child.communicate(timeout=5)

    def test_process_crash_rolls_back_facts_and_recovers_durable_run(self):
        self.write(events=[counter(100,10)])
        self.store.import_settings()
        self.write(events=[counter(200,20)])
        code = "import sys,os; sys.path.insert(0,sys.argv[1]); from usage_index import UsageIndex; x=UsageIndex(sys.argv[2],config_path=sys.argv[3]); x.import_settings(fault=lambda stage: os._exit(17) if stage=='facts' else None)"
        child = subprocess.run([sys.executable,'-c',code,str(ROOT),str(self.path),str(self.config)],capture_output=True,text=True,timeout=15,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        self.assertEqual(child.returncode,17,child.stderr)
        self.assertEqual(self.result().total.tokens.total,100)
        recovered = index.UsageIndex(self.path,config_path=self.config)
        self.assertEqual(recovered.status()['last_run']['code'],'interrupted')
        self.assertEqual(recovered.status()['freshness'],'stale')
        recovered.import_settings()
        self.assertEqual(recovered.query(context()).result.total.tokens.total,200)

    def test_invalid_existing_empty_corrupt_newer_and_checksum_mismatch_preserved(self):
        for kind in ('empty','corrupt','newer','checksum'):
            path = self.base/(kind+'.sqlite3')
            if kind=='empty': path.write_bytes(b'')
            elif kind=='corrupt': path.write_bytes(b'not sqlite PRIVATE_SENTINEL')
            else:
                index.UsageIndex(path,config_path=self.config)
                with closing(db.connect(path)) as connection:
                    connection.execute('PRAGMA user_version=99' if kind=='newer' else "UPDATE migrations SET checksum='wrong' WHERE version=1")
            original=path.read_bytes()
            with self.subTest(kind=kind), self.assertRaises(db.IndexRecoveryError):
                index.UsageIndex(path,config_path=self.config)
            self.assertEqual(path.read_bytes(),original)

    def test_migration_backup_and_failed_upgrade_leave_old_schema_intact(self):
        # Actual schema-1 fixture created from released migration statements.
        path = self.base/'old.sqlite3'
        connection=sqlite3.connect(path,isolation_level=None)
        connection.execute('BEGIN')
        for statement in db.MIGRATIONS[0]: connection.execute(statement)
        connection.execute('INSERT INTO migrations VALUES (1,?)',(db.checksum(db.MIGRATIONS[0]),))
        connection.execute("INSERT INTO metadata VALUES ('installation','fixture-installation')")
        connection.execute(f'PRAGMA application_id={db.APPLICATION_ID}')
        connection.execute('PRAGMA user_version=1'); connection.commit(); connection.close()
        broken=(db.MIGRATIONS[0],('CREATE TABLE partial_upgrade (x INTEGER)','THIS IS NOT SQL'))
        with patch.object(db,'MIGRATIONS',broken), self.assertRaises(db.IndexRecoveryError):
            index.UsageIndex(path,config_path=self.config)
        with closing(db.connect(path)) as connection:
            self.assertEqual(connection.execute('PRAGMA user_version').fetchone()[0],1)
            self.assertFalse(connection.execute("SELECT 1 FROM sqlite_master WHERE name='partial_upgrade'").fetchone())
        self.assertTrue(list((path.parent/'index-backups').glob('*.sqlite3')))
        migrated=index.UsageIndex(path,config_path=self.config)
        with migrated.connection(True) as connection:
            self.assertEqual(db.verify(connection),db.SCHEMA_VERSION)

    def test_corrupt_settings_preserved_and_projection_change_during_import_aborts(self):
        self.write(events=[counter(100,10)])
        self.store.import_settings()
        original=self.config.read_bytes()
        self.config.write_text('{invalid',encoding='utf-8')
        with self.assertRaises(ValueError): self.store.import_settings()
        self.assertEqual(self.config.read_text(encoding='utf-8'),'{invalid')
        self.assertEqual(self.result().total.tokens.total,100)
        self.config.write_bytes(original)
        def changed(stage):
            if stage=='parsed': self.change_settings(codex_fee='30')
        with self.assertRaises(ValueError): self.store.import_settings(fault=changed)
        self.assertEqual(self.result(context(('Codex',))).combined_comparison.fee_usd,Decimal(20))
        self.assertTrue(self.store.status()['configuration_pending'])
        self.store.reprice()
        self.assertEqual(self.result(context(('Codex',))).combined_comparison.fee_usd,Decimal(30))


class AdditionalIndexGates(IndexFixture):
    def test_failed_first_source_read_is_unavailable_and_demo_cannot_import_real(self):
        self.write(events=[counter(100,10)])
        with patch.object(index, 'verified_prefix', return_value=(None,None,[ScanIssue('unreadable_file','Read failed.')])):
            with self.assertRaises(db.IndexUnavailable): self.store.import_settings()
        self.assertFalse(self.store.status()['ready'])
        with self.assertRaises(db.IndexUnavailable): self.result()
        demo=index.UsageIndex(self.path,mode='demo',config_path=self.config)
        with self.assertRaises(ValueError): demo.import_settings()
        self.assertFalse(demo.status()['ready'])

    def test_root_changes_cannot_activate_through_reprice(self):
        self.write(events=[counter(100,10)])
        self.store.import_settings()
        self.change_settings(codex_roots=[])
        with self.assertRaises(ValueError): self.store.reprice()
        self.assertTrue(self.store.status()['configuration_pending'])
        self.assertEqual(self.result().total.tokens.total,100)
        self.store.import_settings()
        self.assertFalse(self.store.status()['configuration_pending'])
        self.assertEqual(self.result().sources[0].state,'stale')

    def test_fork_equal_clock_and_reprice_keep_epoch_facts(self):
        entries=header()
        entries[0]['timestamp']='2026-10-23T20:00:20Z'
        entries[0]['payload']['forked_from_id']='parent'
        path=self.codex/'fork.jsonl'
        path.write_text('\n'.join(json.dumps(e) for e in entries+[counter(100,10),counter(200,30),counter(250,40)])+'\n',encoding='utf-8')
        self.store.import_settings()
        self.assertEqual(self.result().total.tokens.total,150)
        self.write('clock.jsonl',[counter(100,10),counter(200,10),counter(50,10),counter(100,20)],session='clock')
        revision=self.store.import_settings()
        self.assertEqual(self.result().total.tokens.total,400)
        self.change_settings(prices={'fixture-model':Price(4,10,'.1')})
        self.assertEqual(self.store.reprice(),revision)
        self.assertEqual(self.result().total.tokens.total,400)

    def test_missing_source_quality_changes_revision_without_changing_tokens(self):
        path=self.write(events=[counter(100,10)])
        revision=self.store.import_settings()
        path.unlink()
        next_revision=self.store.import_settings()
        self.assertGreater(next_revision,revision)
        self.assertEqual(self.result().total.tokens.total,100)
        self.assertEqual(self.store.import_settings(),next_revision)

    def test_unknown_project_does_not_inflate_known_count(self):
        self.write(events=[counter(100,10)],project=None)
        self.store.import_settings()
        result=self.result()
        self.assertEqual(result.total.project_count,0)
        self.assertEqual(result.details[0].summary.project_count,0)
        self.assertEqual(result.groups_for('project')[0].summary.project_count,0)
        self.assertEqual(result.total.tokens.total,100)
        self.assertEqual(self.rows('SELECT kind FROM projects'),[('unknown',)])

    def test_exact_money_sort_rounding_and_reasoning_subset_survive_storage(self):
        for name,model,fee in [('ten','ten','10000000'),('two','two','2000000'),('tie','tie','0.0000005')]:
            self.write(name+'.jsonl',[counter(1,10)],session=name,model=model)
        self.write('unpriced.jsonl',[counter(1,10)],session='unpriced',model='unpriced')
        self.change_settings(prices={'ten':Price('10000000',0,0),'two':Price('2000000',0,0),'tie':Price('0.0000005',0,0)})
        self.store.import_settings()
        ranked=self.result().groups_for('model','value_desc')
        self.assertEqual([g.key[1] for g in ranked],['ten','two','tie','unpriced'])
        self.assertEqual(ranked[2].summary.value.amount_usd,Decimal('0.000000000000'))
        self.assertEqual(self.result().total.value.amount_usd,Decimal(12))
        self.assertEqual(self.result().total.value.state,'partial')
        # The record validator rejects reasoning outside output at the storage boundary.
        event=codec.event_from(codec.loads(self.rows('SELECT payload FROM events LIMIT 1')[0][0]))
        with self.assertRaises(ValueError): codec.record_data(replace(event.record,reasoning_tokens=1))

    def test_metadata_bounds_and_shared_persisted_value_guard(self):
        self.write(events=[counter(100,10)])
        self.store.import_settings()
        publication=self.store.query(context())
        event=publication.result.details[0].event
        value=publication.result.details[0].valuation
        with self.assertRaises(ValueError): codec.record_data(replace(event.record,model={'private':'not text'}))
        with self.assertRaises(ValueError): codec.record_data(replace(event.record,project='x'*32768))
        for values in ({},{event.event_id:replace(value,pricing_version='wrong')},
                       {event.event_id:replace(value,record=replace(event.record,model='other'))}):
            with self.assertRaises(ValueError): build_usage_result([event],context(),publication.result.catalog,valuations=values)

    def test_named_zone_dst_boundary_and_retained_coverage(self):
        # LA's fall-back local day has 25 hours. Both repeated 01:30 instants survive.
        path=self.write(events=[])
        items=header()
        for stamp,value in [('2026-11-01T08:30:00Z',100),('2026-11-01T09:30:00Z',200),('2026-11-02T08:00:00Z',300)]:
            item=counter(value,10);item['timestamp']=stamp;items.append(item)
        path.write_text('\n'.join(json.dumps(e) for e in items)+'\n',encoding='utf-8')
        self.store.import_settings()
        end=datetime(2026,11,2,8,tzinfo=timezone.utc).timestamp()
        # Exact local next-midnight end excludes the next day's third observation.
        ctx=context(now=end,zone='America/Los_Angeles',filters=UsageFilters(selected_day='2026-11-01'))
        result=self.result(ctx)
        self.assertEqual(result.total.tokens.total,200)
        self.assertEqual(len(result.details),2)
        self.assertEqual(result.context,ctx)

    def test_both_cache_write_ttls_survive_restart_with_exact_value(self):
        item=claude()
        item['message']['usage']['cache_creation']={'ephemeral_5m_input_tokens':5000,'ephemeral_1h_input_tokens':7000}
        item['message']['usage']['cache_creation_input_tokens']=12000
        (self.claude/'ttl.jsonl').write_text(json.dumps(item)+'\n',encoding='utf-8')
        self.store.import_settings()
        self.store=index.UsageIndex(self.path,config_path=self.config)
        result=self.result()
        self.assertEqual((result.total.tokens.input,result.total.tokens.output,result.total.tokens.cached,
                          result.total.tokens.write5m,result.total.tokens.write1h),(10000,20000,30000,5000,7000))
        self.assertEqual(result.total.tokens.total,72000)
        self.assertEqual(result.total.value.amount_usd,Decimal('.527'))
        self.assertEqual(result.total.reasoning.unknown_records,1)
        self.assertEqual(result.total.reasoning.known_tokens,None)

    def test_missing_roots_report_actual_scan_counts_and_incomplete_values_fail_closed(self):
        self.write(events=[counter(100,10)])
        self.change_settings(claude_roots=[self.base/'absent'])
        self.store.import_settings()
        sources={source.provider:source for source in self.result().sources}
        self.assertEqual((sources['Codex'].roots_read,sources['Codex'].files_discovered,sources['Codex'].files_read),(1,1,1))
        self.assertEqual((sources['Claude'].roots_read,sources['Claude'].state),(0,'failed'))
        with self.store.connection() as connection:
            connection.execute('DELETE FROM valuations WHERE dataset=?',(self.store.dataset_id,))
        with self.assertRaises(db.IndexRecoveryError): self.result()

    def test_failed_first_migration_does_not_leave_successful_schema(self):
        path=self.base/'failed-initial.sqlite3'
        broken=(db.MIGRATIONS[0]+('THIS IS NOT SQL',),db.MIGRATIONS[1])
        with patch.object(db,'MIGRATIONS',broken),self.assertRaises(db.IndexRecoveryError):
            index.UsageIndex(path,config_path=self.config)
        with closing(sqlite3.connect(path)) as connection:
            self.assertEqual(connection.execute('PRAGMA user_version').fetchone()[0],0)
            self.assertFalse(connection.execute("SELECT 1 FROM sqlite_master WHERE type='table'").fetchone())
        with self.assertRaises(db.IndexRecoveryError): index.UsageIndex(path,config_path=self.config)


if __name__=='__main__': unittest.main()
