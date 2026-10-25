"""Single process host for API, durable index writer, provider scheduler and optional tray."""
import http.client
import json
import os
import re
from pathlib import Path
import tempfile
import threading
import time
from urllib.parse import urlsplit

from usage_api import ApiService
from usage_config import application_directory,settings_path,load_settings
from usage_hub import create_server
from usage_index import UsageIndex,digest
from usage_jobs import JobController
from usage_runtime import RuntimeOwner,PollingRuntime,AlreadyRunning
from usage_service import QueryContext
from usage_time import resolve_range


class HubOwner:
    def __init__(self,*,index_path=None,config_path=None,owner_path=None,port=8765,fetchers=None):
        self.index_path=Path(index_path) if index_path is not None else application_directory()/'usage-hub.sqlite3'
        self.config_path=Path(config_path) if config_path is not None else settings_path()
        self.owner_path=Path(owner_path) if owner_path is not None else application_directory()/'runtime.lock'
        self.discovery=self.owner_path.with_suffix('.api.json')
        self.port=port;self.fetchers=fetchers or {};self.owner=None;self.server=None;self.thread=None;self.jobs=None
        self.runtime=PollingRuntime(self.fetchers)
        self.http_stopped=False

    @property
    def configuration_key(self):return digest(str(self.index_path.resolve()),str(self.config_path.resolve()))

    def start(self,*,start_jobs=True):
        if self.owner is not None:return self
        owner=RuntimeOwner(self.owner_path);owner.__enter__();self.owner=owner
        try:
            self.index=UsageIndex(self.index_path,config_path=self.config_path)
            self.jobs=JobController(self.index)
            self.service=ApiService(self.index,self.jobs,self.runtime,cache_snapshot=True)
            self.server=create_server(self.service,self.port)
            self.thread=threading.Thread(target=self.server.serve_forever,name='usage-api-http',daemon=True);self.thread.start()
            payload={'origin':self.origin,'control':self.server.sessions.control,'configuration_key':self.configuration_key}
            self.discovery.parent.mkdir(parents=True,exist_ok=True)
            with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=self.discovery.parent,prefix='.api-owner-',delete=False) as stream:
                temporary=Path(stream.name);json.dump(payload,stream);stream.flush();os.fsync(stream.fileno())
            os.chmod(temporary,0o600);os.replace(temporary,self.discovery)
            if start_jobs:self.jobs.start()
            self.runtime.start()
            return self
        except BaseException:
            self.close();raise

    @property
    def origin(self):return f'http://127.0.0.1:{self.server.server_port}'

    def launch_url(self,*,selected='both',status_page=False):
        return launch_destination(self.origin+('/service' if status_page else '/')+'#launch='+self.server.sessions.issue(),selected)

    def query_tray(self,period,snapshots,*,providers=('Codex','Claude')):
        snapshot=self.index.read_snapshot()
        now=time.time();zone=snapshot.settings.resolved_timezone
        context=QueryContext(tuple((p,resolve_range(period,now,snapshots.get(p),zone)) for p in providers),now,period,zone)
        return snapshot.query(context).result

    def close(self,timeout=30):
        deadline=time.monotonic()+timeout
        remaining=lambda:max(0,deadline-time.monotonic())
        if self.server is not None and not self.http_stopped:
            self.server.closing=True
            if self.thread is not None and self.thread.is_alive():self.server.shutdown()
            self.server.server_close()
            self.http_stopped=True
        if self.jobs is not None:
            self.jobs.stop.set();self.jobs.wake.set()
        providers_closed=self.runtime.close(timeout=remaining())
        jobs_closed=self.jobs is None or self.jobs.close(remaining())
        http_closed=self.server is None or self.server.wait_drained(remaining())
        if not providers_closed or not jobs_closed or not http_closed:return False
        self.server=None
        if self.thread is not None:self.thread.join(timeout=remaining())
        if self.jobs is not None:
            try:self.service.limits.flush()
            except Exception:pass
            if getattr(self,'service',None) is not None:self.service.queries.close()
        if self.owner is not None:
            try:
                data=json.loads(self.discovery.read_text(encoding='utf-8'))
                if data.get('configuration_key')==self.configuration_key:self.discovery.unlink()
            except (OSError,ValueError):pass
            self.owner.__exit__(None,None,None);self.owner=None
        return True

    def __enter__(self):return self.start()
    def __exit__(self,*_):self.close()


def reuse_owner(owner,timeout=5):
    """A native-only capability exchange; browser URLs receive 30-second grants."""
    deadline=time.monotonic()+timeout
    while True:
        try:
            if owner.discovery.stat().st_size>4096:raise ValueError()
            data=json.loads(owner.discovery.read_text(encoding='utf-8'))
            parsed=urlsplit(data['origin'])
            if parsed.scheme!='http' or parsed.hostname!='127.0.0.1' or parsed.path or parsed.query or parsed.fragment or not parsed.port:raise ValueError()
            if data['configuration_key']!=owner.configuration_key:raise AlreadyRunning('An owner is running with different index/settings paths; use its configuration.')
            connection=http.client.HTTPConnection('127.0.0.1',parsed.port,timeout=2)
            try:
                connection.request('POST','/api/v1/local/launch',body='{}',headers={'Content-Type':'application/json','X-Usage-Owner':data['control']})
                response=connection.getresponse();raw=response.read(16384)
                if response.status!=200:raise ValueError()
                return json.loads(raw)['data']['url']
            finally:connection.close()
        except AlreadyRunning:raise
        except (OSError,ValueError,KeyError,http.client.HTTPException):
            if time.monotonic()>=deadline:raise AlreadyRunning('Usage Tray already owns this installation, but no reusable API is available. Use its existing tray or quit it before starting the API owner.') from None
            time.sleep(.05)


def launch_destination(url,selected='both',*,status_page=False):
    if selected not in ('both','codex','claude'):raise ValueError('Invalid launch provider.')
    parsed=urlsplit(url)
    if parsed.scheme!='http' or parsed.hostname!='127.0.0.1' or not parsed.port or parsed.path not in ('/','/service') or parsed.query or parsed.username or parsed.password:
        raise ValueError('Invalid local launch destination.')
    from urllib.parse import parse_qs
    grant=parse_qs(parsed.fragment,strict_parsing=True)
    if set(grant)!={'launch'} or len(grant['launch'])!=1 or re.fullmatch(r'[A-Za-z0-9_-]{1,128}',grant['launch'][0]) is None:
        raise ValueError('Invalid local launch handoff.')
    path='/service' if status_page else parsed.path
    return parsed._replace(path=path,fragment=parsed.fragment+('&provider='+selected if selected!='both' else '')).geturl()
