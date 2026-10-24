"""Bounded offline executable check; never reads local histories or credentials.

Run manually with the project interpreter and --exe windows/dist/UsageTray.exe.
"""
import argparse
from http.cookiejar import CookieJar
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import time
from urllib.request import HTTPCookieProcessor, Request, build_opener


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--exe',required=True,type=Path)
    args=parser.parse_args()
    scratch = Path(__file__).resolve().parents[1]/"build"
    scratch.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="integration-packaged-", dir=scratch) as directory:
        return check(args, Path(directory))


def check(args, fixture):
    environment = dict(os.environ, LOCALAPPDATA=str(fixture/"appdata"),
                       CODEX_HOME=str(fixture/"codex"), CLAUDE_CONFIG_DIR=str(fixture/"claude"))
    with socket.socket() as reservation:
        reservation.bind(('127.0.0.1',0))
        port=reservation.getsockname()[1]
    process=subprocess.Popen([str(args.exe.resolve()),'--dashboard','--demo','--no-browser',
                              '--dashboard-port',str(port)],env=environment,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    try:
        opener=build_opener(HTTPCookieProcessor(CookieJar()))
        origin=f'http://127.0.0.1:{port}'
        deadline=time.monotonic()+25
        while True:
            try:
                with opener.open(origin+'/',timeout=1) as response:
                    assert response.status==200
                    assert b'Usage Hub' in response.read()
                break
            except OSError:
                if process.poll() is not None or time.monotonic()>deadline:
                    raise RuntimeError('Packaged dashboard did not become ready') from None
                time.sleep(.2)
        with opener.open(Request(origin+'/api/preview/query',headers={'X-Usage-Hub':'1'}),timeout=5) as response:
            dto=json.load(response)
        assert dto['dataset']=='demo'
        assert dto['summary']['tokens']['total_tokens']=='8920000'
        assert dto['summary']['value']['amount_usd']=='49.506'
        assert dto['range']['timezone']=='America/Los_Angeles'
        assert dto['summary']['conversation_count']==12
        for asset in ('app.js','format.js','style.css','assets/overview.svg','assets/Geist.woff2','assets/GeistMono.woff2'):
            with opener.open(origin+'/'+asset,timeout=5) as response:
                assert response.status==200 and len(response.read())>100, asset
        print('Packaged dashboard: PASS (demo query, exact totals, named timezone, bundled UI/icons/fonts)')
    finally:
        if os.name=='nt' and process.poll() is None:
            # PyInstaller one-file mode owns a child process. Bound cleanup to
            # this exact Popen tree; terminating only its bootloader can orphan
            # the dashboard server.
            subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],capture_output=True,timeout=5,
                           creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        elif process.poll() is None:
            process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
    scratch=Path(__file__).resolve().parents[1]/'build'
    scratch.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='dashboard-smoke-',dir=scratch) as directory:
        target=Path(directory)/'report.txt'
        report=subprocess.run([str(args.exe.resolve()),'--report','month','--demo','--output',str(target)],
            env=environment,timeout=25,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        assert report.returncode==0
        text=target.read_text(encoding='utf-8')
        assert '108,000' in text and '0.2658' in text and 'DEMO' in text
    print('Packaged terminal report: PASS (existing offline month demo preserved)')
    def invoke(*arguments):
        return subprocess.run([str(args.exe.resolve()), *map(str,arguments)], env=environment,
                              timeout=25, capture_output=True,
                              creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    version = fixture/'version.json'
    assert invoke('--version','--output',version).returncode == 0
    identity=json.loads(version.read_text(encoding='utf-8'))
    assert identity['app_version']=='0.8.0'
    import hashlib
    assert identity['build_id']=='exe-sha256:'+hashlib.sha256(args.exe.read_bytes()).hexdigest()
    report_path, diagnostic_path = fixture/'report.txt', fixture/'operation.json'
    assert invoke('--report','month','--demo','--output',report_path,
                  '--diagnostic-output',diagnostic_path).returncode == 0
    operation=json.loads(diagnostic_path.read_text(encoding='utf-8'))
    assert operation['scope']=='demo' and operation['status']=='success'
    assert operation['build_id']==identity['build_id']
    assert '108,000' in report_path.read_text(encoding='utf-8')
    configuration=fixture/'configuration.json'
    assert invoke('--diagnostics','--output',configuration).returncode == 0
    assert json.loads(configuration.read_text(encoding='utf-8'))['operation']['scope']=='configuration'
    blocked=fixture/'must-not-write.json'
    for mode in (('--diagnostic-output',blocked),('--diagnostics',)):
        assert invoke('--dashboard','--demo',*mode).returncode == 2
    assert not blocked.exists()
    print('Packaged S08 integration: PASS (executable identity, report diagnostics, offline configuration, rejected mixed modes)')



if __name__=='__main__':
    main()
