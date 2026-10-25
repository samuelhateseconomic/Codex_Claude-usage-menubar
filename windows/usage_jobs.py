"""Durable bounded job queue and JSON/index configuration recovery for one owner."""
import hashlib
import json
import threading
import time
import uuid

from usage_api_contract import ApiError, invalid
from usage_config import load_settings, settings_data, settings_from_data, save_settings
from usage_timezone import resolve_timezone
from usage_index import utc_now
from usage_privacy import metadata_label
from usage_index_db import transaction, IndexBusy, IndexRecoveryError


class JobController:
    def __init__(self, index, *, interval=300):
        self.index=index
        self.interval=max(300,interval)
        self.lock=threading.RLock()
        self.wake=threading.Event();self.stop=threading.Event();self.thread=None
        self.idle_hook=lambda:None
        self.next_scan=time.monotonic()+self.interval
        with self.index.connection() as connection,transaction(connection,True):
            connection.execute("UPDATE jobs SET status='failed',phase='complete',code='interrupted',completed=? WHERE dataset=? AND status='running'",(utc_now(),index.dataset_id))

    def _row(self, row):
        if row is None: raise ApiError(404,'job_not_found','Unknown operation ID.')
        return {'id':row['id'],'kind':row['kind'],'status':row['status'],'phase':row['phase'],'code':row['code'],
                'created_at':row['created'],'started_at':row['started'],'completed_at':row['completed'],
                'requested_configuration_version':row['configuration'],'counts':json.loads(row['counts']),
                'resulting_versions':None if row['result'] is None else json.loads(row['result'])}

    def get(self, identity):
        if len(identity)>128: raise invalid('job_id')
        with self.index.connection(True) as connection:
            return self._row(connection.execute('SELECT * FROM jobs WHERE dataset=? AND id=?',(self.index.dataset_id,identity)).fetchone())

    def latest(self):
        with self.index.connection(True) as connection:
            row=connection.execute('SELECT * FROM jobs WHERE dataset=? ORDER BY created DESC,id DESC LIMIT 1',(self.index.dataset_id,)).fetchone()
            return None if row is None else self._row(row)

    def active(self):
        with self.index.connection(True) as connection:
            return [row[0] for row in connection.execute("SELECT id FROM jobs WHERE dataset=? AND status IN ('queued','running') ORDER BY created,id",(self.index.dataset_id,))]

    def roots(self, settings=None, include_disabled=False):
        settings=load_settings(self.index.config_path) if settings is None else settings
        from usage_index import digest
        from usage_ingestion import _id
        result={digest(provider,_id(path)):(provider,path) for provider,roots in settings.roots().items() for path in roots}
        if include_disabled:
            with self.index.connection(True) as connection:
                for row in connection.execute('SELECT id,provider,path FROM roots WHERE dataset=?',(self.index.dataset_id,)):
                    result.setdefault(row['id'],(row['provider'],row['path']))
        return result

    @staticmethod
    def _key(kind, version, roots):
        return hashlib.sha256(json.dumps([kind,version,roots],sort_keys=True,separators=(',',':')).encode()).hexdigest()

    def _enqueue(self, connection, kind, settings, roots):
        key=self._key(kind,settings.version,roots)
        existing=connection.execute("SELECT * FROM jobs WHERE dataset=? AND request_key=? AND status IN ('queued','running')",(self.index.dataset_id,key)).fetchone()
        if existing is not None: return self._row(existing),False
        if connection.execute("SELECT count(*) FROM jobs WHERE dataset=? AND status IN ('queued','running')",(self.index.dataset_id,)).fetchone()[0]>=32:
            raise ApiError(429,'queue_full','The local work queue is full; retry after current work completes.')
        connection.execute("UPDATE jobs SET status='superseded',phase='complete',code='configuration_changed',completed=? WHERE dataset=? AND status='queued' AND configuration!=?",(utc_now(),self.index.dataset_id,settings.version))
        identity=uuid.uuid4().hex
        connection.execute('INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
            (identity,self.index.dataset_id,kind,key,settings.version,'queued','queued',None,utc_now(),None,None,'{}',None,json.dumps({'root_ids':roots})))
        return self._row(connection.execute('SELECT * FROM jobs WHERE id=?',(identity,)).fetchone()),True

    def submit(self, kind='import', root_ids=None):
        if kind not in ('import','reprice'): raise invalid('kind')
        if root_ids is not None and (not isinstance(root_ids,list) or not root_ids or len(root_ids)>128 or any(not isinstance(v,str) or len(v)>128 for v in root_ids)): raise invalid('root_ids')
        with self.lock:
            settings=load_settings(self.index.config_path)
            roots=None if root_ids is None else sorted(set(root_ids))
            if roots is not None and set(roots)-self.roots(settings).keys(): raise ApiError(404,'root_not_found','Unknown or disabled approved root ID.')
            key=self._key(kind,settings.version,roots)
            with self.index.connection(True) as connection:
                existing=connection.execute("SELECT * FROM jobs WHERE dataset=? AND request_key=? AND status IN ('queued','running')",(self.index.dataset_id,key)).fetchone()
                if existing is not None: return self._row(existing),False
            with self.index.connection() as connection,transaction(connection,True):
                result=self._enqueue(connection,kind,settings,roots)
            self.wake.set()
            return result

    def patch_settings(self, data):
        if not isinstance(data,dict) or set(data)!={'expected_configuration_version','changes'}: raise invalid()
        changes=data['changes']
        if not isinstance(changes,dict) or changes.keys()-{'plan_fees_usd','timezone','report_format','rate_overrides','enabled_root_ids'}: raise invalid('changes')
        if 'plan_fees_usd' in changes:
            fees=changes['plan_fees_usd']
            if not isinstance(fees,dict) or set(fees)!={'Codex','Claude'} or any(value is not None and not isinstance(value,str) for value in fees.values()):raise invalid('plan_fees_usd')
        if 'rate_overrides' in changes:
            rates=changes['rate_overrides']
            if not isinstance(rates,dict) or len(rates)>1000:raise invalid('rate_overrides')
            for name,values in rates.items():
                if not isinstance(name,str) or not 1<=len(name)<=1024 or not isinstance(values,dict) or any(not isinstance(value,str) for value in values.values()):raise invalid('rate_overrides')
        with self.lock:
            current=load_settings(self.index.config_path)
            if data['expected_configuration_version']!=current.version:
                raise ApiError(409,'configuration_changed','Settings changed; reload the current draft before saving.')
            draft=settings_data(current)
            for field,value in changes.items():
                if field=='enabled_root_ids':
                    if not isinstance(value,list) or len(value)>128 or any(not isinstance(v,str) for v in value): raise invalid(field)
                    approved=self.roots(current,include_disabled=True)
                    if set(value)-approved.keys(): raise ApiError(404,'root_not_found','Settings may select only currently approved root IDs.')
                    draft['log_roots']={provider:[str(path) for key,(p,path) in approved.items() if p==provider and key in value] for provider in ('Codex','Claude')}
                else: draft[field]=value
            try: updated=settings_from_data(draft)
            except (ValueError,TypeError,KeyError): raise invalid('changes') from None
            # Acquire the DB writer before touching JSON: a busy import returns a
            # retryable error without a partially accepted settings draft.
            with self.index.connection() as connection,transaction(connection,True):
                row=connection.execute('SELECT ready,configuration FROM datasets WHERE id=?',(self.index.dataset_id,)).fetchone()
                pending=not row['ready'] or row['configuration']!=updated.version
                jobs=[]
                if pending:
                    kind='import' if not row['ready'] or current.log_roots!=updated.log_roots else 'reprice'
                    job,_=self._enqueue(connection,kind,updated,None);jobs.append(job)
                if updated.version!=current.version:
                    save_settings(updated,self.index.config_path)
            self.wake.set()
            return {'configuration_version':updated.version,'settings':self.editable(updated),'jobs':jobs,'pending':pending}

    def editable(self, settings=None):
        settings=load_settings(self.index.config_path) if settings is None else settings
        data=settings_data(settings)
        data['timezone_info']=resolve_timezone(settings.timezone).data()
        data['system_timezone_info']=resolve_timezone('auto').data()
        data.pop('log_roots')
        data['approved_roots']=[{'id':key,'provider':provider.lower(),'label':metadata_label(str(path),'project'),'enabled':key in self.roots(settings)} for key,(provider,path) in sorted(self.roots(settings,include_disabled=True).items())]
        return data

    def recover_configuration(self):
        settings=load_settings(self.index.config_path)
        with self.index.connection(True) as connection:
            row=connection.execute('SELECT ready,configuration FROM datasets WHERE id=?',(self.index.dataset_id,)).fetchone()
            if row['ready'] and row['configuration']==settings.version: return
            active=None if not row['ready'] else connection.execute('SELECT payload FROM configurations WHERE dataset=? AND version=?',(self.index.dataset_id,row['configuration'])).fetchone()
        old=None if active is None else settings_from_data(json.loads(active[0]))
        self.submit('import' if old is None or old.log_roots!=settings.log_roots else 'reprice')

    def run_one(self):
        with self.lock,self.index.connection() as connection,transaction(connection,True):
            row=connection.execute("SELECT * FROM jobs WHERE dataset=? AND status='queued' ORDER BY created,id LIMIT 1",(self.index.dataset_id,)).fetchone()
            if row is None: return False
            connection.execute("UPDATE jobs SET status='running',phase='compute',started=? WHERE id=?",(utc_now(),row['id']))
        status,code,result='succeeded',None,None
        counts='{}'
        try:
            settings=load_settings(self.index.config_path)
            if settings.version!=row['configuration']:
                status,code='superseded','configuration_changed'
            else:
                roots=json.loads(row['payload'])['root_ids']
                cancel=lambda stage: (_ for _ in ()).throw(InterruptedError('Owner is stopping.')) if self.stop.is_set() else None
                def published(connection,versions,work_counts):
                    outcome='succeeded' if versions['configuration_version']==row['configuration'] else 'superseded'
                    reason=None if outcome=='succeeded' else 'configuration_changed'
                    connection.execute("UPDATE jobs SET status=?,phase='complete',code=?,completed=?,result=?,counts=? WHERE dataset=? AND id=?",(outcome,reason,utc_now(),json.dumps(versions),json.dumps(work_counts),self.index.dataset_id,row['id']))
                if row['kind']=='import': self.index.import_settings(root_ids=roots,fault=cancel,commit_hook=published)
                else: self.index.reprice(fault=cancel,commit_hook=published)
                with self.index.connection(True) as connection:
                    latest=connection.execute('SELECT counts FROM runs WHERE dataset=? ORDER BY started DESC,id DESC LIMIT 1',(self.index.dataset_id,)).fetchone()
                    counts='{}' if latest is None else latest[0]
                state=self.index.status()
                result={key:str(state[key]) for key in ('usage_revision','pricing_version','configuration_version')}
                if result['configuration_version']!=row['configuration']: status,code='superseded','configuration_changed'
        except Exception:
            status,code='failed','index_operation_failed'
            try:
                if load_settings(self.index.config_path).version!=row['configuration']: status,code='superseded','configuration_changed'
            except ValueError:
                code='configuration_unavailable'
        if self.stop.is_set() and status=='failed':code='interrupted'
        with self.lock,self.index.connection() as connection,transaction(connection,True):
            connection.execute("UPDATE jobs SET status=?,phase='complete',code=?,completed=?,result=?,counts=? WHERE id=? AND status='running'",(status,code,utc_now(),None if result is None else json.dumps(result),counts,row['id']))
            connection.execute("DELETE FROM jobs WHERE dataset=? AND status IN ('succeeded','failed','superseded') AND id NOT IN (SELECT id FROM jobs WHERE dataset=? AND status IN ('succeeded','failed','superseded') ORDER BY completed DESC,id DESC LIMIT 1000)",(self.index.dataset_id,self.index.dataset_id))
        if status=='superseded': self.recover_configuration()
        return True

    def _worker(self):
        while not self.stop.is_set():
            self.wake.clear()
            try:
                if self.run_one():
                    self.idle_hook();continue
                self.idle_hook()
                if time.monotonic()>=self.next_scan:
                    self.next_scan=time.monotonic()+self.interval;self.submit('import')
            except Exception:
                # Safe durable operation codes are stored by run_one; no payload logging.
                pass
            self.wake.wait(.25)

    def start(self):
        if self.thread is not None: return
        try:self.submit('import')
        except ValueError:pass  # Cached committed queries survive malformed current JSON settings.
        self.thread=threading.Thread(target=self._worker,name='usage-index-owner',daemon=True);self.thread.start()

    def close(self, timeout=30):
        self.stop.set();self.wake.set()
        if self.thread is not None: self.thread.join(timeout)
        return self.thread is None or not self.thread.is_alive()
