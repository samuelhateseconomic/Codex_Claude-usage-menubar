"""S14 offline release acceptance of the actual executable, using synthetic roots.

No browser, tray clicks, provider checks, real histories or credentials. Native
menu playback is a separate manual check. Measurements are fixture-specific.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime, timezone, timedelta
from decimal import Decimal
import http.client
import json
import os
from pathlib import Path
import platform
import sqlite3
import subprocess
import sys
import time
from urllib.parse import urlsplit, parse_qs

sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parent)]
from packaged_local_hub_smoke import require, synthetic_workspace
from usage_config import Settings, effective_settings, save_settings, load_settings
from usage_index_db import SCHEMA_VERSION
from usage_index import UsageIndex, restore_backup
from usage_process import ChildTree

SENTINEL = 'S14-PRIVATE-TRANSCRIPT-NEVER-PERSIST'


def seed_v2(path, config):
    # This owned synthetic database is populated by the authoritative writer.
    # Migration 3 added only these two tables. Remove those additions from the
    # fixture to reproduce the exact checksummed schema-2 shape WITH committed
    # facts; no user database is downgraded and no product rollback is offered.
    store=UsageIndex(path,config_path=config)
    store.import_settings()
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute('DROP TABLE jobs')
        connection.execute('DROP TABLE provider_cache')
        connection.execute('DELETE FROM migrations WHERE version=3')
        connection.execute('PRAGMA user_version=2')
        from usage_index_db import verify
        require(verify(connection,allow_older=True)==2,'Invalid populated schema-2 fixture.')
    return store.dataset_id


def unsupported_copy(backup, index, config):
    """New explicit fixture paths only; never mutate a just-terminated DB/WAL."""
    restore_backup(backup,index,config_destination=config)
    with closing(sqlite3.connect(index)) as connection, connection:
        connection.execute('PRAGMA user_version=99')


def fixture(root):
    logs = root / 'sources'
    logs.mkdir()
    # Keep the fixture safely inside today's local month even near midnight.
    stamp = datetime.now(timezone.utc) - timedelta(microseconds=500)
    for file in range(40):
        rows = [{'type':'session_meta','payload':{'id':'release-'+str(file),'cwd':'C:/synthetic/project-'+str(file % 5)}},
                {'type':'turn_context','payload':{'model':'release-model','effort':'high'}},
                {'type':'response_item','payload':{'type':'message','content':SENTINEL}}]
        for number in range(1, 101):
            rows.append(counter(number * 1000, stamp + timedelta(microseconds=number)))
        (logs / (str(file)+'.jsonl')).write_text('\n'.join(map(json.dumps,rows))+'\n', encoding='utf-8')
    return logs, stamp


def counter(value, stamp):
    return {'type':'event_msg','timestamp':stamp.isoformat(),'payload':{'type':'token_count','info':{
        'total_token_usage':{'input_tokens':value,'output_tokens':0,'cached_input_tokens':0}}}}


class PackagedHost:
    def __init__(self, executable, root):
        self.executable = executable
        self.root = root
        self.app = root / 'appdata' / 'UsageTray'
        self.config = self.app / 'settings.json'
        self.index = self.app / 'usage-hub.sqlite3'
        self.discovery = self.app / 'runtime.api.json'
        self.env = dict(os.environ, LOCALAPPDATA=str(root/'appdata'), CODEX_HOME=str(root/'no-codex'),
                        CLAUDE_CONFIG_DIR=str(root/'no-claude'), TEMP=str(root), TMP=str(root))
        self.command = [str(executable),'--dashboard','--no-browser','--dashboard-port','0']
        self.tree = None
        self.cookie = self.csrf = None

    def invoke(self, *arguments):
        tree = ChildTree()
        try:
            process = tree.start([str(self.executable), *map(str, arguments)], env=self.env, cwd=self.root,
                                 stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return process.wait(timeout=30)
        finally:
            tree.close()

    def start(self):
        previous = self.discovery.read_bytes() if self.discovery.exists() else None
        self.cookie = self.csrf = None
        self.tree = ChildTree()
        self.child = self.tree.start(self.command, env=self.env, cwd=self.root,
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        deadline = time.monotonic()+45
        while True:
            if self.discovery.exists():
                raw = self.discovery.read_bytes()
                if raw != previous:
                    self.native = json.loads(raw)
                    self.origin = self.native['origin']
                    self.port = urlsplit(self.origin).port
                    break
            require(self.child.poll() is None and time.monotonic()<deadline, 'Packaged owner failed to start/recover.')
            time.sleep(.05)
        require(urlsplit(self.origin).hostname=='127.0.0.1', 'Non-loopback listener.')
        self.bootstrap()

    def close(self):
        if self.tree is not None:
            self.tree.close()
            self.tree = None

    def request(self, method, path, body=None, *, headers=None, auth=True):
        supplied = dict(headers or {})
        if auth and self.cookie:
            supplied.setdefault('Cookie', self.cookie)
            if method != 'GET':
                supplied.setdefault('Origin', self.origin)
                supplied.setdefault('X-Usage-CSRF', self.csrf)
        if body is not None:
            supplied.setdefault('Content-Type', 'application/json')
            body = json.dumps(body)
        connection = http.client.HTTPConnection('127.0.0.1', self.port, timeout=45)
        try:
            connection.request(method, path, body=body, headers=supplied)
            response = connection.getresponse()
            raw = response.read()
            require(SENTINEL.encode() not in raw, 'Transcript content reached packaged HTTP output.')
            return response.status, dict(response.getheaders()), raw
        finally:
            connection.close()

    def api(self, method, path, body=None, *, expected=200, **options):
        status, headers, raw = self.request(method, '/api/v1'+path, body, **options)
        require(status==expected, f'Packaged request {method} {path.split("?")[0]} returned {status}; expected {expected}.')
        return json.loads(raw), headers

    def grant(self):
        data,_ = self.api('POST','/local/launch',{},headers={'X-Usage-Owner':self.native['control']},auth=False)
        return parse_qs(urlsplit(data['data']['url']).fragment)['launch'][0]

    def bootstrap(self):
        grant = self.grant()
        session,headers = self.api('POST','/session/bootstrap',{'launch_token':grant},headers={'Origin':self.origin},auth=False)
        self.cookie = headers['Set-Cookie'].split(';',1)[0]
        self.csrf = session['data']['csrf_token']
        return grant

    def ready(self):
        deadline = time.monotonic()+120
        while True:
            state,_ = self.api('GET','/status')
            if (state['data']['ready'] and not state['data']['indexing'] and state['data']['configuration_state']=='active'
                    and (state['data']['last_job'] or {}).get('status')=='succeeded'):
                return state
            require(self.child.poll() is None and time.monotonic()<deadline, 'Packaged import/recovery timed out.')
            time.sleep(.05)

    def query(self, path='/overview', context=None):
        return self.api('GET',path+('?query_context_id='+context if context else ''))[0]


def security(host):
    status,headers,html = host.request('GET','/',auth=False)
    require(status==200 and b'data-api-mode="v1"' in html and b'/local-app.js' in html, 'Real local shell unavailable.')
    require('Set-Cookie' not in headers and 'Access-Control-Allow-Origin' not in headers, 'Anonymous shell grants authority.')
    require("default-src 'none'" in headers['Content-Security-Policy'] and 'unsafe-inline' not in headers['Content-Security-Policy'], 'Unsafe CSP.')
    for asset in ('local-app.js','local-session.js','local-view.js','v1-client.js','v1-schema.js','format.js','style.css',
                  'assets/overview.svg','assets/explore.svg','assets/limits.svg','assets/settings.svg','assets/Geist.woff2','assets/GeistMono.woff2'):
        code,_,raw = host.request('GET','/'+asset,auth=False)
        require(code==200 and len(raw)>100, 'Missing packaged local asset: '+asset)
    for path in ('/api/preview/query','/index.html','/%2e%2e/AGENTS.md'):
        require(host.request('GET',path)[0]==404, 'Real/demo or asset boundary failed.')
    host.api('GET','/overview',expected=403,auth=False)
    host.api('GET','/status',expected=403,headers={'Host':'hostile.invalid'})
    host.api('GET','/status',expected=403,headers={'Origin':'https://hostile.invalid'})
    host.api('POST','/local/launch',{},expected=403,auth=False)
    host.api('POST','/index/refresh',{},expected=403,headers={'Cookie':host.cookie,'Origin':host.origin},auth=False)
    host.api('POST','/index/refresh',{},expected=403,headers={'X-Usage-CSRF':'incorrect'})
    grant = host.grant()
    host.api('POST','/session/bootstrap',{'launch_token':grant},expected=403,auth=False)
    # Two tabs sharing the cookie must preserve each other's CSRF token.
    session,headers = host.api('POST','/session/bootstrap',{'launch_token':grant})
    require(headers['Set-Cookie'].split(';',1)[0]==host.cookie and session['data']['csrf_token']==host.csrf, 'Second tab invalidated the first session.')
    host.api('POST','/session/bootstrap',{'launch_token':grant},expected=403)
    first_cookie,first_csrf = host.cookie,host.csrf
    host.bootstrap()  # Separate cookie jar, as another browser profile.
    host.api('GET','/session',headers={'Cookie':first_cookie})
    host.api('GET','/session')
    require(first_csrf!=host.csrf, 'Independent profiles share a session secret.')
    # Expiry checked after useful release work, without waiting idle here.
    return host.grant(), time.monotonic()


def measure(host):
    samples=[]
    for _ in range(3):
        begin=time.perf_counter();overview=host.query();host.api('GET','/status')
        overview_seconds=time.perf_counter()-begin
        summary=overview['data']['summary']
        require(summary['tokens']['total_tokens']=='4000000' and Decimal(summary['value']['amount_usd'])==Decimal('8'), 'Benchmark accounting differs.')
        context=overview['query_context_id']
        begin=time.perf_counter();same=host.query(context=context)
        with ThreadPoolExecutor(max_workers=2) as workers:
            listing=workers.submit(host.query,'/usage/conversations',context)
            facets=workers.submit(host.query,'/usage/facets',context)
            listing=listing.result();facets=facets.result()
        host.api('GET','/status')
        explore_seconds=time.perf_counter()-begin
        require(same['data']['summary']==listing['data']['summary']==summary, 'Explore full summary differs.')
        require(listing['data']['pagination']['matched_count']==40 and sum(r['record_count'] for r in facets['data']['projects'])==4000, 'Benchmark scope differs.')
        samples.append({'overview_http_bundle_seconds':round(overview_seconds,6),'explore_http_bundle_seconds':round(explore_seconds,6)})
    return samples, overview


def check(executable, measurements=None):
    require(os.name=='nt','This release check requires Windows.')
    scratch=Path(__file__).resolve().parents[1]/'build'
    scratch.mkdir(exist_ok=True)
    with synthetic_workspace(scratch) as root:
        logs,stamp=fixture(root)
        fixture_bytes=sum(p.stat().st_size for p in logs.glob('*.jsonl'))
        host=PackagedHost(executable,root)
        from usage_valuation import Price
        settings=effective_settings(Settings(),timezone='America/Los_Angeles',codex_roots=[logs],claude_roots=[],
            prices={'release-model':Price('2','10','.1')})
        save_settings(settings,host.config)
        original_dataset=seed_v2(host.index,host.config)
        try:
            host.start();host.ready()
            print('Packaged first launch / schema migration: PASS',flush=True)
            backups=list((host.app/'index-backups').glob('*.sqlite3'))
            require(len(backups)==1,'Pre-migration backup missing.')
            backup=backups[0]
            with closing(sqlite3.connect(backup)) as connection:
                require(connection.execute('PRAGMA user_version').fetchone()[0]==2,'Backup did not preserve old schema.')
                require(connection.execute('SELECT count(*),sum(total) FROM events').fetchone()==(4000,4000000),'Pre-upgrade backup lost committed facts.')
            with closing(sqlite3.connect(host.index)) as connection:
                require(connection.execute('PRAGMA user_version').fetchone()[0]==SCHEMA_VERSION,'Packaged migration missing.')
                require(connection.execute('SELECT id FROM datasets').fetchone()[0]==original_dataset,'Migration replaced installation identity.')
            expiry,issued=security(host)
            samples,overview=measure(host)
            result={'fixture':{'files':40,'accepted_events':4000,'tokens':'4000000','amount_usd':'8.000000000000','source_bytes':fixture_bytes},
                    'machine':{'platform':platform.platform(),'python_harness':platform.python_version(),'logical_cpus':os.cpu_count()},
                    'samples':samples,'target_seconds':2,'all_http_bundles_under_target':all(max(s.values())<2 for s in samples)}
            if measurements is not None:
                measurements.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
            print('Packaged timing: '+json.dumps(result,separators=(',',':')),flush=True)
            require(overview['range']['timezone']=='America/Los_Angeles','Bundled named timezone failed.')
            old_context=overview['query_context_id'];old_cookie=host.cookie;old_native=host.native
            # A second actual executable must retain the same writer/profile.
            require(host.invoke(*host.command[1:])==0,'Second executable launch failed.')
            require(json.loads(host.discovery.read_text())==old_native,'Second launch replaced owner.')
            require(host.query(context=old_context)['data']['summary']==overview['data']['summary'],'Reuse changed the frozen result.')
            # JSON remains authoritative across a compute job and restart.
            saved,_=host.api('PATCH','/settings',{'expected_configuration_version':settings.version,'changes':{'plan_fees_usd':{'Codex':'21','Claude':'20'}}})
            require(saved['data']['jobs'],'Fee change did not schedule publication.')
            host.ready()
            host.api('GET','/overview?query_context_id='+old_context,expected=409)
            current=host.query()
            require(current['data']['summary']==overview['data']['summary'],'Fee-only change altered usage facts/value.')
            # Expire a real packaged grant. Never extend session lifetime in a test.
            while time.monotonic()-issued<30.2:
                time.sleep(.1)
            host.api('POST','/session/bootstrap',{'launch_token':expiry},expected=403)
            # Observe a real durable running job and kill only our owned tree.
            with (logs/'0.jsonl').open('a',encoding='utf-8') as stream:
                stream.write(json.dumps(counter(101000,stamp+timedelta(microseconds=101)))+'\n')
            job,_=host.api('POST','/index/refresh',{},expected=202)
            identity=job['data']['id'];deadline=time.monotonic()+10
            while True:
                work,_=host.api('GET','/jobs/'+identity)
                require(work['data']['status'] not in ('succeeded','failed','superseded'),'Could not interrupt the running fixture job.')
                with closing(sqlite3.connect(host.index,timeout=1)) as connection:
                    running=connection.execute("SELECT count(*) FROM runs WHERE status='running'").fetchone()[0]
                if work['data']['status']=='running' and running:break
                require(time.monotonic()<deadline,'Running fixture job was not observed.')
                time.sleep(.01)
            retained_revision=current['usage_revision']
            host.close()
            with closing(sqlite3.connect(host.index)) as connection:
                require(str(connection.execute('SELECT revision FROM datasets').fetchone()[0])==retained_revision,'Interrupted publication advanced revision.')
                require(connection.execute('SELECT sum(total) FROM events').fetchone()[0]==4000000,'Interrupted publication changed committed facts.')
            host.start();host.ready()
            require(host.native['control']!=old_native['control'],'Restart reused an old native capability.')
            host.api('GET','/status',headers={'Cookie':old_cookie},expected=403)
            host.api('GET','/overview?query_context_id='+old_context,expected=409)
            interrupted,_=host.api('GET','/jobs/'+identity)
            require(interrupted['data']['status']=='failed' and interrupted['data']['code']=='interrupted','Crash job was not recovered honestly.')
            print('Packaged interrupted job / restart: PASS',flush=True)
            recovered=host.query()
            require(recovered['data']['summary']['tokens']['total_tokens']=='4001000' and Decimal(recovered['data']['summary']['value']['amount_usd'])==Decimal('8.002'),'Restart did not publish the complete new facts.')
            require(str(dict(load_settings(host.config).plan_fees_usd)['Codex'])=='21','Saved fee lost on restart.')
            # Invalid requested JSON must retain the last committed offline view.
            host.close();valid=host.config.read_bytes();host.config.write_text('{invalid '+SENTINEL,encoding='utf-8')
            host.start();state,_=host.api('GET','/status')
            require(state['data']['configuration_state']=='invalid','Invalid requested settings were hidden.')
            require(host.query()['data']['summary']==recovered['data']['summary'],'Invalid settings erased the accepted publication.')
            host.api('GET','/settings',expected=503)
            diagnostic=root/'safe-diagnostic.json'
            require(host.invoke('--diagnostics','--output',diagnostic)==2,'Invalid-settings diagnostic exit differs.')
            safe=diagnostic.read_text(encoding='utf-8')
            require(all(secret not in safe for secret in (SENTINEL,host.csrf,host.cookie,host.native['control'],str(logs))),'Private content reached diagnostics.')
            host.close();host.config.write_bytes(valid)
            print('Packaged invalid-settings retention / diagnostics: PASS',flush=True)
            # Test unsupported startup independently of the deliberately killed
            # WAL fixture. Editing its just-terminated file races Windows/SQLite
            # teardown on some runtimes; no I/O error should be ignored/retried.
            unsupported=PackagedHost(executable,root/'unsupported')
            unsupported.root.mkdir()
            unsupported_copy(backup,unsupported.index,unsupported.config)
            require(unsupported.invoke(*unsupported.command[1:])==1,'Unsupported index was silently rebuilt or accepted.')
            with closing(sqlite3.connect(unsupported.index)) as connection:
                require(connection.execute('PRAGMA user_version').fetchone()[0]==99 and
                        connection.execute('SELECT sum(total) FROM events').fetchone()[0]==4000000,
                        'Failed optional startup changed the preserved index.')
            report=root/'terminal.txt'
            require(unsupported.invoke('--report','month','--audit','--output',report)==0,'Core terminal fallback failed with unsupported optional DB.')
            text=report.read_text(encoding='utf-8')
            require('4,001,000' in text,'Core terminal fallback exact audit total missing.')
            require(SENTINEL not in text,'Transcript entered terminal report.')
            # Restore to new paths only, then let the executable migrate that copy.
            restored=PackagedHost(executable,root/'restored');restored.root.mkdir()
            restore_backup(backup,restored.index,config_destination=restored.config)
            try:
                restored.start();restored.ready()
                require(restored.query()['data']['summary']['tokens']['total_tokens']=='4001000','Restored/migrated executable lost usage.')
            finally:restored.close()
            # Inspect all persistent app artifacts (never sources or extraction).
            for file in host.app.rglob('*'):
                if file.is_file() and file.name!='settings.json':
                    require(SENTINEL.encode() not in file.read_bytes(),'Private content persisted in an application artifact.')
        finally:host.close()
    print('Packaged hub release: PASS (offline local assets/auth, multi-session/reuse, grant expiry, schema-2 upgrade/backup/restore, interrupted job/restart, invalid settings, safe diagnostics and terminal fallback)')
    print(json.dumps(result,separators=(',',':')))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--exe',required=True,type=Path)
    parser.add_argument('--measurements',type=Path)
    args=parser.parse_args()
    check(args.exe.resolve(strict=True),args.measurements)


if __name__=='__main__':main()
