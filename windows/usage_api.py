"""Production API service: explicit routing, safe status/settings/jobs and no implicit polling."""
import time
from usage_api_contract import CONTRACT_VERSION, ApiError, invalid, envelope
from usage_api_query import QueryService
from usage_api_limits import LimitCache
from usage_identity import APP_VERSION, BUILD_ID
from usage_index_db import IndexUnavailable, IndexRecoveryError, IndexBusy
from usage_config import load_settings,SettingsError
from usage_timezone import resolve_timezone


class ApiService:
    contract_version=CONTRACT_VERSION
    def __init__(self,index,jobs,runtime,*,clock=time.time,cache_snapshot=False):
        if index.mode!='real':raise ValueError('Production v1 accepts only the explicit real index; use the separate labeled demo preview.')
        self.index,self.jobs,self.runtime,self.clock=index,jobs,runtime,clock
        self.queries=QueryService(index,clock=clock,cache_snapshot=cache_snapshot)
        self.limits=LimitCache(index,runtime,clock=clock)
        self.jobs.idle_hook=self.limits.flush

    def respond(self,kind,data): return envelope(self.index.dataset_id,self.index.mode,self.clock(),kind,data)

    def read(self,path,params):
        if path in ('/status','/settings','/limits') or path.startswith('/jobs/'):
            if params: raise invalid()
            if path=='/status':
                try:
                    state=self.index.status();configuration_state='pending' if state['configuration_pending'] else 'active'
                except SettingsError:
                    with self.index.connection(True) as connection:
                        row=connection.execute('SELECT * FROM datasets WHERE id=?',(self.index.dataset_id,)).fetchone()
                        state={'ready':bool(row['ready']),'freshness':row['freshness'],'usage_revision':row['revision'],'pricing_version':row['pricing'],'configuration_version':row['configuration'],'requested_configuration_version':None,'configuration_pending':True}
                    configuration_state='invalid'
                with self.index.connection(True) as connection:
                    scan=[{'provider':r[0].lower(),'roots_read':r[1],'files_discovered':r[2],'files_read':r[3]} for r in connection.execute('SELECT provider,roots_read,files_discovered,files_read FROM provider_scans WHERE dataset=?',(self.index.dataset_id,))]
                    imported=connection.execute("SELECT finished FROM runs WHERE dataset=? AND kind='import' AND status='succeeded' ORDER BY finished DESC LIMIT 1",(self.index.dataset_id,)).fetchone()
                active_jobs=self.jobs.active()
                data={'app_version':APP_VERSION,'build_id':BUILD_ID,'ready':state['ready'],'freshness':state['freshness'],
                      'usage_revision':str(state['usage_revision']),'pricing_version':state['pricing_version'],
                      'configuration_version':state['configuration_version'],'requested_configuration_version':state['requested_configuration_version'],
                      'configuration_pending':state['configuration_pending'],'configuration_state':configuration_state,'indexing':bool(active_jobs),'active_job_ids':active_jobs,
                      'source_scans':scan,'last_import_completed_at':None if imported is None else imported[0],'last_job':self.jobs.latest(),'providers':self.limits.read()}
                return self.respond('status',data)
            if path=='/settings':
                settings=load_settings(self.index.config_path)
                return self.respond('settings',{'configuration_version':settings.version,'settings':self.jobs.editable(settings),
                    'bounds':{'monthly_fee_max_usd':'1000000000','decimal_places':12,'search_characters':200,'page_size_max':100}})
            if path=='/limits':
                # Use the committed configuration, just like usage queries. A
                # saved-but-pending draft must not silently change display zones.
                settings=self.index.display_settings()
                return self.respond('limits',{'providers':self.limits.read(),
                    'timezone_info':resolve_timezone(settings.timezone).data()})
            identity=path.removeprefix('/jobs/')
            if '/' in identity: raise ApiError(404,'not_found','Unknown API route.')
            return self.respond('job',self.jobs.get(identity))
        if path not in ('/overview','/usage/conversations','/usage/projects','/usage/facets') and not path.startswith('/conversations/'):
            raise ApiError(404,'not_found','Unknown API route.')
        return self.queries.read(path,params)

    def mutate(self,method,path,data):
        if self.jobs.stop.is_set():raise ApiError(503,'owner_stopping','The local owner is stopping; retry after restart.')
        if method=='POST' and path=='/index/refresh':
            if not isinstance(data,dict) or data.keys()-{'root_ids'}: raise invalid()
            job,new=self.jobs.submit('import',data.get('root_ids'))
            return 202 if new else 200,self.respond('job',job)
        if method=='PATCH' and path=='/settings': return 200,self.respond('settings_saved',self.jobs.patch_settings(data))
        if method=='POST' and path=='/limits/refresh':
            status,data=self.limits.refresh(data)
            response=self.respond('limits_refresh',data)
            if status==429:
                retries=[p['next_eligible_at'] for p in data['providers'] if p['next_eligible_at']]
                response['error']={'code':'cooldown','message':'All selected providers are cooling down.','retry_at':min(retries) if retries else None}
            return status,response
        raise ApiError(404,'not_found','Unknown API route.')
