"""Headless v1 queries over one S11 snapshot; frozen contexts and exact-key cursors."""
from collections import OrderedDict, defaultdict, Counter
from dataclasses import dataclass, replace
from datetime import date, datetime, time as day_time, timedelta
import base64
import hashlib
import hmac
import json
import secrets
import threading
import time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from usage_api_contract import ApiError, invalid, envelope, summary, comparison, tokens, money, utc, PROVIDERS, pricing_explanation, pricing_breakdown
from usage_service import QueryContext, UsageFilters, summarize_details, _conversation_id
from usage_time import resolve_range
from usage_pricing_explanation import explain_event, explain_values

FILTERS = ('provider','project_id','model','effort','q','selected_day')
SCALARS = ('dataset_id','period','timezone','q','selected_day','sort','page_size','cursor','query_context_id','base_query_context_id')
ALLOWED = set(SCALARS) | {'provider','project_id','model','effort'}
SORTS = ('value_desc','tokens_desc','last_activity_desc')


@dataclass(frozen=True)
class FrozenQuery:
    id: str
    versions: tuple
    captured: float
    period: str
    timezone: str
    filters: tuple
    expires: float

    @property
    def applied(self):
        return {key:list(value) if isinstance(value,tuple) else value.casefold() if key=='q' else value for key,value in self.filters}


class CommittedReader:
    """One owner-controlled read connection and bounded immutable publication.

    SQLite data_version is meaningful across reads of the SAME connection. Every
    external commit (including jobs, failures and manual SQL) invalidates reuse.
    Never compare data_version across newly opened connections or use file mtime
    as publication identity. The lock owns all use of the shared connection.
    """
    def __init__(self,index):
        self.index=index
        self.lock=threading.RLock()
        self.connection=None
        self.identity=self.version=self.snapshot=None
        self.generation=0

    def close(self):
        with self.lock:
            if self.connection is not None:self.connection.close()
            self.connection=None
            self.identity=self.version=self.snapshot=None

    def read(self):
        from usage_index_db import connect
        with self.lock:
            try:
                info=self.index.path.stat()
                identity=(info.st_dev,info.st_ino)
                if identity!=self.identity:self.close()
                if self.connection is None:
                    self.connection=connect(self.index.path,True,check_same_thread=False)
                    self.identity=identity
                version=self.connection.execute('PRAGMA data_version').fetchone()[0]
                if self.snapshot is not None and version==self.version:return self.snapshot,self.generation
                # No read transaction is held across requests. The snapshot's
                # transaction follows this version read; a racing commit can
                # only force another decode next time, never mask that commit.
                self.snapshot=None
                snapshot=self.index.read_snapshot(_connection=self.connection)
                self.generation+=1
                if len(snapshot.events)<=10000:
                    self.snapshot=snapshot
                    self.version=version
                return snapshot,self.generation
            except BaseException:
                self.close()
                raise


class QueryService:
    def __init__(self, index, *, clock=time.time, monotonic=time.monotonic, secret=None, cache_snapshot=False):
        self.index, self.clock, self.monotonic = index, clock, monotonic
        self.secret = secret or secrets.token_bytes(32)
        self.contexts = OrderedDict()
        self.lock = threading.RLock()
        self.result_lock = threading.RLock()
        self.results = OrderedDict()
        self.result_publication = None
        self.reader = CommittedReader(index) if cache_snapshot else None

    def close(self):
        if self.reader is not None:self.reader.close()
        with self.result_lock:
            self.results.clear()
            self.result_publication=None

    def _result(self, snapshot, context, snapshot_token=None):
        # Validate the current SQLite publication and resolve the frozen
        # context before reaching here. Never serve a cache as a read fallback.
        # Reuse only immutable core summaries, not mutable wire responses.
        publication = (snapshot.versions, snapshot.freshness, snapshot.sources, snapshot_token)
        with self.result_lock:
            if publication != self.result_publication:
                self.results.clear()
                self.result_publication = publication
            result = self.results.get(context)
            if result is None:
                result = snapshot.query(context).result
                if len(result.details) <= 20000:
                    self.results[context] = result
                    while len(self.results) > 8 or sum(len(r.details) for r in self.results.values()) > 20000:
                        self.results.popitem(last=False)
            else:
                self.results.move_to_end(context)
            return result

    def _normalize(self, params, snapshot, base=None):
        if params.keys()-ALLOWED: raise invalid()
        if any(not isinstance(values,list) or not values or any(not isinstance(v,str) or len(v)>32767 for v in values) for values in params.values()): raise invalid()
        if any(len(params.get(key,[]))>1 for key in SCALARS): raise invalid()
        if 'sort' in params and params['sort'][0] not in (*SORTS,'events'): raise invalid('sort')
        if 'page_size' in params:
            value=params['page_size'][0]
            if not value.isascii() or not value.isdecimal() or not 1<=int(value)<=100: raise invalid('page_size')
        if params.get('dataset_id',[snapshot.dataset_id])[0] != snapshot.dataset_id:
            raise ApiError(404,'dataset_not_found','Unknown dataset.')
        defaults={'provider':('claude','codex'),'project_id':(),'model':(),'effort':(),'q':'','selected_day':None}
        filters=dict(base.filters) if base else defaults.copy()
        for key in FILTERS:
            if key not in params: continue
            values=params[key]
            if key in ('q','selected_day'):
                value=values[0]
                if key=='q':
                    if len(value.strip())>200: raise invalid(key)
                    value=value.strip()
                else:
                    try:
                        if date.fromisoformat(value).isoformat()!=value: raise ValueError()
                    except ValueError: raise invalid(key) from None
                filters[key]=value
            else:
                if len(values)>64 or any(not value or len(value)>1024 for value in values): raise invalid(key)
                filters[key]=tuple(sorted(set(values)))
        if not filters['provider'] or set(filters['provider'])-PROVIDERS.keys(): raise invalid('provider')
        projects={row[0] for row in snapshot.projects}
        if set(filters['project_id'])-projects: raise ApiError(404,'project_not_found','Unknown project ID in this dataset.')
        period=params.get('period',[base.period if base else 'month'])[0]
        zone=params.get('timezone',[base.timezone if base else snapshot.settings.timezone])[0]
        if period not in ('today','week','month'): raise invalid('period')
        try: ZoneInfo(zone)
        except (ZoneInfoNotFoundError,ValueError): raise invalid('timezone') from None
        if base and (period!=base.period or zone!=base.timezone): raise invalid('base_query_context_id')
        return filters,period,zone

    def resolve(self, params, snapshot):
        existing=params.get('query_context_id')
        derived=params.get('base_query_context_id')
        if existing and derived: raise invalid('query_context_id')
        if existing or derived:
            values=existing or derived
            if len(values)!=1 or len(values[0])>128: raise invalid('query_context_id')
            with self.lock:
                frozen=self.contexts.get(values[0])
            if frozen is None or frozen.expires<=self.monotonic():
                raise ApiError(409,'context_expired','Query context expired; refresh related views together.')
            if frozen.versions!=snapshot.versions:
                raise ApiError(409,'revision_changed','Committed usage or configuration changed; refresh related views together.')
            filters,period,zone=self._normalize(params,snapshot,frozen)
            if existing:
                expected=dict(frozen.filters)
                if {**filters,'q':filters['q'].casefold()}!={**expected,'q':expected['q'].casefold()}: raise invalid('query_context_id')
                return frozen
            captured=frozen.captured
        else:
            filters,period,zone=self._normalize(params,snapshot)
            # Freeze to the documented microsecond wire precision.
            captured=datetime.fromtimestamp(self.clock(),ZoneInfo('UTC')).timestamp()
        frozen=FrozenQuery(secrets.token_urlsafe(24),snapshot.versions,captured,period,zone,
                           tuple((key,filters[key]) for key in FILTERS),self.monotonic()+1800)
        self.context(snapshot,frozen)  # Validate selected-day intersection before issuing a context.
        with self.lock:
            self.contexts[frozen.id]=frozen
            while len(self.contexts)>1024: self.contexts.popitem(last=False)
        return frozen

    def context(self, snapshot, frozen, *, changes=None, conversation=None):
        filters=dict(frozen.filters)
        if changes: filters.update(changes)
        providers=tuple(PROVIDERS[p] for p in filters['provider'])
        ranges=tuple((p,resolve_range(frozen.period,frozen.captured,timezone=frozen.timezone)) for p in providers)
        if filters['selected_day']:
            chosen=date.fromisoformat(filters['selected_day']);zone=ZoneInfo(frozen.timezone)
            start=datetime.combine(chosen,day_time(),zone).timestamp()
            end=datetime.combine(chosen+timedelta(days=1),day_time(),zone).timestamp()
            base=ranges[0][1]
            if end<=base.start or start>base.end or (start==base.end and base.start!=base.end): raise invalid('selected_day')
        core_ids=()
        if conversation is not None:
            ids=dict(snapshot.conversation_ids)
            core_ids=tuple({_conversation_id(event) for event in snapshot.events if ids[event.event_id]==conversation})
            if not core_ids: raise ApiError(404,'conversation_not_found','Unknown conversation ID in this dataset.')
        selected=UsageFilters(project_ids=filters['project_id'],models=filters['model'],efforts=filters['effort'],
                              search=filters['q'],selected_day=filters['selected_day'],conversation_ids=core_ids)
        return QueryContext(ranges,frozen.captured,frozen.period,frozen.timezone,selected,snapshot.mode=='demo')

    def _metadata(self, frozen, context):
        r=context.ranges[0][1]
        effective_start,effective_end=r.start,r.end
        if context.filters.selected_day:
            chosen=date.fromisoformat(context.filters.selected_day);zone=ZoneInfo(context.timezone)
            effective_start=max(r.start,datetime.combine(chosen,day_time(),zone).timestamp())
            effective_end=min(r.end,datetime.combine(chosen+timedelta(days=1),day_time(),zone).timestamp())
        return {'query_context_id':frozen.id,'usage_revision':str(frozen.versions[1]),
                'pricing_version':frozen.versions[2],'configuration_version':frozen.versions[3],
                'range':{'preset':frozen.period,'timezone':frozen.timezone,'start_at':utc(r.start),'end_at':utc(r.end),
                         'effective_start_at':utc(effective_start),'effective_end_at':utc(effective_end)},
                'applied_filters':frozen.applied}

    def _groups(self, result, snapshot, dimension):
        membership=dict(snapshot.conversation_ids if dimension=='conversations' else snapshot.event_project_ids)
        labels={row[0]:row[-1] for row in (snapshot.conversations if dimension=='conversations' else snapshot.projects)}
        buckets=defaultdict(list)
        for detail in result.details: buckets[membership[detail.detail_id]].append(detail)
        projects=dict(snapshot.event_project_ids)
        rows=[]
        for key,members in buckets.items():
            value=summarize_details(members,dict(snapshot.project_ids))
            rows.append({'id':key,'label':labels[key],'summary':value,'members':tuple(members),
                'last_activity':max(d.record.timestamp for d in members),'project_ids':sorted({projects[d.detail_id] for d in members}),
                'models':sorted({d.record.model for d in members}),'efforts':sorted({d.record.effort for d in members})})
        return rows

    @staticmethod
    def sort_key(row, sort):
        if sort=='events': return (row['timestamp'],row['id'])
        if sort=='tokens_desc': return (-row['summary'].tokens.total,row['id'])
        if sort=='last_activity_desc': return (-row['last_activity'],row['id'])
        value=row['summary'].value.amount_usd
        return (value is None,value.copy_negate() if value is not None else 0,row['id'])

    @staticmethod
    def row_dto(row, snapshot):
        return {'id':row['id'],'label':row['label'],'summary':summary(row['summary']),
                'last_activity_at':utc(row['last_activity']),'project_ids':row['project_ids'],
                'models':row['models'],'efforts':row['efforts'],
                'pricing':pricing_breakdown(explain_values((d.valuation for d in row['members']),snapshot.catalog))}

    def _cursor(self, data):
        raw=json.dumps(data,sort_keys=True,separators=(',',':')).encode()
        encoded=base64.urlsafe_b64encode(raw).decode().rstrip('=')
        signature=hmac.new(self.secret,encoded.encode(),hashlib.sha256).hexdigest()
        return encoded+'.'+signature

    def _cursor_data(self, value):
        try:
            if len(value)>4096: raise ValueError()
            encoded,signature=value.split('.')
            if not hmac.compare_digest(signature,hmac.new(self.secret,encoded.encode(),hashlib.sha256).hexdigest()): raise ValueError()
            return json.loads(base64.urlsafe_b64decode(encoded+'='*((-len(encoded))%4)))
        except (ValueError,UnicodeError,TypeError): raise invalid('cursor') from None

    def page(self, rows, params, frozen, endpoint, *, event=False):
        sort=params.get('sort',['events' if event else 'value_desc'])[0]
        if sort not in (('events',) if event else SORTS): raise invalid('sort')
        size=params.get('page_size',['50'])[0]
        if not size.isascii() or not size.isdecimal() or not 1<=int(size)<=100: raise invalid('page_size')
        size=int(size)
        ordered=sorted(rows,key=lambda row:self.sort_key(row,sort))
        start=0
        def exact_key(row): return [str(value) if not isinstance(value,bool) else value for value in self.sort_key(row,sort)]
        if 'cursor' in params:
            data=self._cursor_data(params['cursor'][0])
            if data.get('context')!=frozen.id: raise ApiError(409,'cursor_context_changed','Cursor belongs to another query; restart pagination.')
            if (data.get('endpoint'),data.get('sort'),data.get('size'))!=(endpoint,sort,size): raise invalid('cursor')
            positions=[i for i,row in enumerate(ordered) if exact_key(row)==data.get('last')]
            if len(positions)!=1: raise invalid('cursor')
            start=positions[0]+1
        page=ordered[start:start+size]
        cursor=self._cursor({'context':frozen.id,'endpoint':endpoint,'sort':sort,'size':size,'last':exact_key(page[-1])}) if page and start+size<len(ordered) else None
        return page,{'page_size':size,'sort':sort,'next_cursor':cursor,'matched_count':len(rows)}

    def read(self, path, params):
        paginated=path in ('/usage/conversations','/usage/projects') or path.endswith('/events')
        if 'cursor' in params and not paginated: raise invalid('cursor')
        if params.get('sort')==['events'] and not path.endswith('/events'): raise invalid('sort')
        if self.reader is None:
            snapshot,snapshot_token=self.index.read_snapshot(),None
        else:
            snapshot,snapshot_token=self.reader.read()
        frozen=self.resolve(params,snapshot)
        context=self.context(snapshot,frozen)
        result=self._result(snapshot,context,snapshot_token)
        if path=='/overview':
            conversations=self._groups(result,snapshot,'conversations')
            projects=self._groups(result,snapshot,'projects')
            coverage=[{'provider':s.provider.lower(),'state':s.state,'ingestion_issues':s.issue_counts,
                       'accounting_issues':dict(Counter(i.code for i in s.accounting_issues))} for s in result.sources]
            model_rows=[{'provider':g.key[0].lower(),'model':g.key[1],'effort':g.key[2],'summary':summary(g.summary)} for g in result.groups_for('model_effort','value_desc')]
            if len(model_rows)>1000: raise ApiError(503,'query_budget','Query exceeds the supported response work budget.')
            data={'scope':context.scope,'summary':summary(result.total),'freshness':snapshot.freshness,'coverage':coverage,
                  'comparisons':[comparison(c) for c in result.comparisons],'combined_comparison':comparison(result.combined_comparison),
                  'days':[{'day':g.key[0],'summary':summary(g.summary)} for g in result.groups_for('day')],
                  'providers':[{'provider':g.key[0].lower(),'summary':summary(g.summary)} for g in result.groups_for('provider')],
                  'models':model_rows,'top_projects':[self.row_dto(row,snapshot) for row in sorted(projects,key=lambda r:self.sort_key(r,'value_desc'))[:10]],
                  'recent_conversations':[self.row_dto(row,snapshot) for row in sorted(conversations,key=lambda r:self.sort_key(r,'last_activity_desc'))[:10]]}
            kind='overview'
        elif path in ('/usage/conversations','/usage/projects'):
            rows,pagination=self.page(self._groups(result,snapshot,'conversations' if path.endswith('conversations') else 'projects'),params,frozen,path)
            data={'summary':summary(result.total),'items':[self.row_dto(row,snapshot) for row in rows],'pagination':pagination};kind='list'
        elif path=='/usage/facets':
            data={}
            for field,dimension in (('project_id','projects'),('model','models'),('effort','efforts')):
                # Self-omission only changes a query with an active filter.
                # Reuse this request's immutable authoritative result otherwise.
                facet=self._result(snapshot,self.context(snapshot,frozen,changes={field:()}),snapshot_token) if dict(frozen.filters)[field] else result
                membership=dict(snapshot.event_project_ids)
                buckets=defaultdict(set)
                for detail in facet.details:
                    key=membership[detail.detail_id] if field=='project_id' else getattr(detail.record,field)
                    buckets[key].add(detail.detail_id)
                for selected in dict(frozen.filters)[field]: buckets[selected]
                if len(buckets)>1000: raise ApiError(503,'query_budget','Facet exceeds the supported response work budget.')
                labels={row[0]:row[-1] for row in snapshot.projects}
                data[dimension]=[{'value':key,'label':labels.get(key,key),'record_count':len(ids),'selected':key in dict(frozen.filters)[field]} for key,ids in sorted(buckets.items())]
            kind='facets'
        elif path.startswith('/conversations/'):
            parts=path.split('/');conversation=parts[2]
            if len(parts)>4 or (len(parts)==4 and parts[3]!='events'): raise ApiError(404,'not_found','Unknown API route.')
            scoped=self._result(snapshot,self.context(snapshot,frozen,conversation=conversation),snapshot_token)
            all_ids=dict(snapshot.conversation_ids)
            lifetime=[event for event in snapshot.events if all_ids[event.event_id]==conversation]
            label=next(row[-1] for row in snapshot.conversations if row[0]==conversation)
            if len(parts)==3:
                data={'id':conversation,'label':label,'summary':summary(scoped.total),
                      'lifetime_first_at':utc(min(e.record.timestamp for e in lifetime)),'lifetime_last_at':utc(max(e.record.timestamp for e in lifetime)),
                      'lifetime_scope':'all_retained_accepted_usage','project_ids':sorted({dict(snapshot.event_project_ids)[d.detail_id] for d in scoped.details}),
                      'models':sorted({d.record.model for d in scoped.details}),'efforts':sorted({d.record.effort for d in scoped.details}),
                      'pricing':pricing_breakdown(explain_values((d.valuation for d in scoped.details),snapshot.catalog))};kind='conversation'
            else:
                rows=[{'id':detail.detail_id,'timestamp':detail.record.timestamp,'detail':detail} for detail in scoped.details]
                page,pagination=self.page(rows,params,frozen,path,event=True)
                items=[]
                for row in page:
                    d=row['detail'];v=d.valuation
                    items.append({'id':d.detail_id,'occurred_at':utc(d.record.timestamp),'provider':d.record.provider.lower(),
                        'project_id':dict(snapshot.event_project_ids)[d.detail_id],'model':d.record.model,'effort':d.record.effort,
                        'effort_source':d.record.effort_source,'tokens':tokens(d.record.tokens,d.record.reasoning_tokens),
                        'value':{'state':v.state,'amount_usd':money(v.amount_usd),'unpriced_reason':v.unpriced_reason,'rate_id':v.rate_id,
                                 'tier':v.tier,'assumptions':list(v.assumptions),'request_context_tokens':None if v.request_context_tokens is None else str(v.request_context_tokens),
                                 'request_context_source':v.request_context_source,'pricing_version':v.pricing_version,'policy_version':v.policy_version,
                                 'explanation':pricing_explanation(v,explain_event(v,snapshot.catalog))}})
                data={'summary':summary(scoped.total),'items':items,'pagination':pagination};kind='events'
        else:
            raise ApiError(404,'not_found','Unknown API route.')
        response=envelope(snapshot.dataset_id,snapshot.mode,self.clock(),kind,data)
        response.update(self._metadata(frozen,context))
        return response
