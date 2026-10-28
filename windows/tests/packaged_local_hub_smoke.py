"""Bounded S13 packaged real-launch compatibility using synthetic local metadata.

S14 still owns full native lifecycle, migration/restart and performance release
acceptance. This check opens no browser/tray and polls no provider accounts.
"""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import http.client
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlsplit, parse_qs, quote

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from usage_config import Settings, effective_settings, save_settings
from usage_process import ChildTree
from usage_valuation import Price
from usage_identity import APP_VERSION


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


@contextmanager
def synthetic_workspace(scratch, *, cleanup_timeout=10):
    # Job termination/process signaling can precede Windows releasing the last
    # file handle. Retry only our own temporary fixture; never suppress a
    # persistent failure or broaden process termination/file cleanup scope.
    scratch = Path(scratch).resolve(strict=True)
    temporary = tempfile.TemporaryDirectory(prefix='s13-packaged-', dir=scratch)
    owned = Path(temporary.name).resolve()
    require(owned.parent == scratch and owned.name.startswith('s13-packaged-'),
            'Refusing cleanup outside the owned fixture directory.')
    try:
        yield owned
    finally:
        deadline = time.monotonic() + cleanup_timeout
        while True:
            require(Path(temporary.name).resolve() == owned,
                    'Owned fixture cleanup target changed.')
            try:
                temporary.cleanup()
                break
            except PermissionError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(.05)


def check(executable):
    require(os.name == 'nt', 'Packaged local hub checks require Windows.')
    scratch = Path(__file__).resolve().parents[1] / 'build'
    scratch.mkdir(exist_ok=True)
    with synthetic_workspace(scratch) as root:
        logs = root / 'codex' / 'sessions'
        logs.mkdir(parents=True)
        stamp = datetime.now(timezone.utc).isoformat()
        entries = [
            {'type':'session_meta','payload':{'id':'packaged-fixture','cwd':'C:/synthetic/project'}},
            {'type':'turn_context','payload':{'model':'packaged-model','effort':'high'}},
            {'type':'event_msg','timestamp':stamp,'payload':{'type':'token_count','info':{'total_token_usage':{
                'input_tokens':1010000,'output_tokens':1830000,'cached_input_tokens':1000000,'reasoning_output_tokens':1260000}}}},
            {'type':'response_item','payload':{'type':'message','content':'PACKAGED-PRIVATE-CONTENT-SENTINEL'}}]
        (logs/'fixture.jsonl').write_text('\n'.join(json.dumps(x) for x in entries)+'\n', encoding='utf-8')
        config = root/'settings.json'
        save_settings(effective_settings(Settings(), timezone='UTC', codex_roots=[logs], claude_roots=[],
            prices={'packaged-model':Price('2','10','0.1')}), config)
        env = dict(os.environ, LOCALAPPDATA=str(root/'appdata'), CODEX_HOME=str(root/'codex'),
                   CLAUDE_CONFIG_DIR=str(root/'claude'), TEMP=str(root), TMP=str(root))
        command = [str(executable), '--dashboard', '--no-browser', '--dashboard-port', '0', '--config', str(config)]
        tree = ChildTree()
        try:
            child = tree.start(command, env=env, cwd=root, stdin=subprocess.DEVNULL,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            discovery = root/'appdata'/'UsageTray'/'runtime.api.json'
            deadline = time.monotonic()+30
            while not discovery.exists() and child.poll() is None and time.monotonic()<deadline:
                time.sleep(.05)
            require(discovery.exists(), 'Packaged production owner did not start.')
            native = json.loads(discovery.read_text(encoding='utf-8'))
            origin = native['origin']
            parsed = urlsplit(origin)
            require(parsed.hostname=='127.0.0.1', 'Production listener is not loopback.')
            cookie = csrf = None
            def request(method, path, body=None, extra=None, auth=False):
                headers = dict(extra or {})
                if auth:
                    headers['Cookie'] = cookie
                    if method!='GET':
                        headers.setdefault('Origin', origin)
                        headers.setdefault('X-Usage-CSRF', csrf)
                if body is not None:
                    body=json.dumps(body);headers.setdefault('Content-Type','application/json')
                connection=http.client.HTTPConnection('127.0.0.1',parsed.port,timeout=8)
                try:
                    connection.request(method,path,body=body,headers=headers)
                    response=connection.getresponse();raw=response.read()
                    return response.status,dict(response.getheaders()),raw
                finally:
                    connection.close()
            def api(method,path,**kwargs):
                status,headers,raw=request(method,path,**kwargs)
                require('PACKAGED-PRIVATE-CONTENT-SENTINEL' not in raw.decode('utf-8','replace'), 'Transcript content reached the API.')
                return status,headers,json.loads(raw)
            status,headers,html=request('GET','/')
            require(status==200 and b'/local-app.js' in html and b'data-api-mode="v1"' in html, 'Packaged production shell is missing.')
            require('Set-Cookie' not in headers, 'Plain root granted a session.')
            require("style-src 'self'" in headers['Content-Security-Policy'] and "font-src 'self'" in headers['Content-Security-Policy'], 'Packaged CSP blocks local UI assets.')
            require(api('GET','/api/v1/overview')[0]==403, 'Unauthenticated private read succeeded.')
            code,_,launch=api('POST','/api/v1/local/launch',body={},extra={'X-Usage-Owner':native['control']})
            require(code==200, 'Packaged native handoff failed.')
            grant=parse_qs(urlsplit(launch['data']['url']).fragment)['launch'][0]
            code,headers,session=api('POST','/api/v1/session/bootstrap',body={'launch_token':grant},extra={'Origin':origin})
            require(code==200 and 'HttpOnly' in headers['Set-Cookie'] and 'SameSite=Strict' in headers['Set-Cookie'], 'Packaged session exchange failed.')
            cookie=headers['Set-Cookie'].split(';',1)[0];csrf=session['data']['csrf_token']
            for name in ('local-app.js','local-session.js','local-view.js','local-freshness.js','v1-client.js','v1-schema.js','format.js','style.css','assets/Geist.woff2','assets/GeistMono.woff2'):
                code,_,raw=request('GET','/'+name)
                require(code==200 and len(raw)>100, 'Packaged local asset unavailable: '+name)
                require(raw==(Path(__file__).resolve().parents[1]/'dashboard'/name).read_bytes(), 'Packaged asset differs from reviewed source: '+name)
            deadline=time.monotonic()+20
            while True:
                code,_,status=api('GET','/api/v1/status',auth=True)
                require(code==200, 'Packaged authenticated status failed.')
                if status['data']['ready']:break
                require(time.monotonic()<deadline and child.poll() is None, 'Packaged synthetic import did not publish.')
                time.sleep(.05)
            require(status['data']['app_version']==APP_VERSION, 'Packaged application identity differs.')
            code,_,overview=api('GET','/api/v1/overview?provider=codex',auth=True)
            require(code==200, 'Packaged overview failed.')
            summary=overview['data']['summary']
            require(summary['tokens']['total_tokens']=='2840000' and summary['tokens']['reasoning_tokens']=='1260000', 'Packaged exact token accounting differs.')
            from decimal import Decimal
            require(Decimal(summary['value']['amount_usd'])==Decimal('18.42'), 'Packaged exact API value differs.')
            context=overview['query_context_id']
            code,_,listing=api('GET','/api/v1/usage/conversations?query_context_id='+context,auth=True)
            require(code==200 and listing['data']['summary']==summary, 'Packaged list/headline reconciliation failed.')
            identity=quote(listing['data']['items'][0]['id'],safe='')
            code,_,detail=api('GET','/api/v1/conversations/'+identity+'?query_context_id='+context,auth=True)
            require(code==200 and detail['data']['summary']==summary, 'Packaged detail reconciliation failed.')
            pricing=detail['data']['pricing']
            require(pricing['total_record_count']==summary['record_count'] and not pricing['truncated'], 'Packaged rate preview scope differs.')
            code,_,events=api('GET','/api/v1/conversations/'+identity+'/events?query_context_id='+context,auth=True)
            require(code==200 and events['data']['summary']==summary, 'Packaged event explanation query failed.')
            for event in events['data']['items']:
                e=event['value']['explanation']
                require(e['state']=='available' and e['pricing_version']==overview['pricing_version'], 'Packaged pricing evidence differs.')
                require([c['rate_usd_per_million'] for c in e['categories']]==['2','10','0.1',None,None], 'Packaged applied rates differ.')
                require(sum(Decimal(c['unrounded_usd']) for c in e['categories'])+Decimal(e['rounding_adjustment_usd'])==Decimal(event['value']['amount_usd']), 'Packaged category charges fail exact reconciliation.')
            code,_,limits=api('GET','/api/v1/limits',auth=True)
            require(code==200 and all(p['phase']=='disabled' and p['snapshot'] is None for p in limits['data']['providers']), 'Dashboard-only launch unexpectedly enabled provider checks.')
            require(api('GET','/api/v1/session',auth=True)[2]['data']['csrf_token']==csrf, 'Packaged session resume failed.')
            require(api('GET','/api/v1/overview',extra={'Host':'hostile.example'},auth=True)[0]==403, 'Packaged hostile Host accepted.')
            require(api('POST','/api/v1/index/refresh',body={},extra={'Cookie':cookie,'Origin':origin})[0]==403, 'Packaged CSRF protection failed.')
            require(api('GET','/api/preview/query',auth=True)[0]==404, 'Production unexpectedly serves the preview API.')
            second=ChildTree()
            try:
                process=second.start(command,env=env,cwd=root,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
                require(process.wait(timeout=30)==0, 'Packaged repeated launch did not reuse owner.')
            finally:
                second.close()
            require(json.loads(discovery.read_text(encoding='utf-8'))==native, 'Repeated launch replaced the active owner.')
            require(api('GET','/api/v1/overview?query_context_id='+context,auth=True)[2]['data']['summary']==summary, 'Repeated launch invalidated the frozen query.')
        finally:
            tree.close()
    print('Packaged local hub: PASS (real launcher, synthetic 2,840,000 tokens / USD18.42, local assets, auth/resume, offline limits, detail and owner reuse)')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--exe',required=True,type=Path)
    args=parser.parse_args()
    check(args.exe.resolve(strict=True))


if __name__=='__main__':
    main()
