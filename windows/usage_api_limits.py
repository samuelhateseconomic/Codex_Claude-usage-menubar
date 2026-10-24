"""Allowlisted cached active-account limits; reads never schedule provider work."""
from datetime import datetime, timezone
import json
import math
import threading
import time

from usage_api_contract import ApiError, invalid, utc, PROVIDERS
from usage_core import Snapshot, Window
from usage_index_db import transaction
from usage_privacy import display_text


class LimitCache:
    def __init__(self,index,runtime,*,clock=time.time):
        self.index,self.runtime,self.clock=index,runtime,clock
        self.lock=threading.RLock();self.pending=set();self.cached={};self.dirty=False
        with index.connection(True) as connection:
            for row in connection.execute('SELECT provider,payload FROM provider_cache'):
                self.cached[row['provider']]=json.loads(row['payload'])
        for payload in self.cached.values():
            if payload.get('snapshot'): payload['state']='stale'
            payload['phase']='disabled'
        for state in runtime.states:
            saved=self.cached.get(state.provider.lower())
            if saved and saved.get('snapshot'):
                data=saved['snapshot']
                epoch=lambda text:None if text is None else datetime.fromisoformat(text.replace('Z','+00:00')).timestamp()
                state.snapshot=Snapshot(state.provider,tuple(Window(w['label'],w['used_percent'],epoch(w['resets_at']),w['duration_minutes']) for w in data['windows']),epoch(saved['last_success_at']),blocked=data['blocked'])
                state.error='Cached provider data from the previous owner.';state.category='cached'
                retry=epoch(saved.get('next_eligible_at'))
                state.next_check=state.monotonic()+max(0,(retry or self.clock())-self.clock())
            previous=state.changed
            state.changed=lambda previous=previous:(previous(),self.changed())

    def changed(self):
        with self.lock:
            before=dict(self.cached)
            for state in self.runtime.states:
                view=state.view();key=state.provider.lower()
                old=self.cached.get(key,{})
                attempt=old.get('last_attempt_at')
                if view.phase=='refreshing' and old.get('phase')!='refreshing': attempt=utc(self.clock())
                if view.phase!='refreshing' and old.get('phase')=='refreshing': self.pending.discard(key)
                snapshot=None
                if view.snapshot:
                    windows=[]
                    for w in view.snapshot.windows:
                        if type(w.used) not in (int,float) or not math.isfinite(w.used): continue
                        windows.append({'label':display_text(w.label),'used_percent':w.used,'remaining_percent':w.remaining,
                                        'resets_at':utc(w.resets_at),'duration_minutes':w.duration_minutes})
                    snapshot={'windows':windows,'blocked':view.snapshot.blocked}
                self.cached[key]={'provider':key,'scope':'active_cli_account','state':'stale' if view.error and snapshot else 'available' if snapshot else 'unavailable',
                    'phase':view.phase,'category':view.category,'last_attempt_at':attempt,
                    'last_success_at':utc(view.snapshot.checked_at) if view.snapshot else old.get('last_success_at'),
                    'next_eligible_at':utc(math.ceil(view.retry_at)) if view.retry_at is not None else None,'snapshot':snapshot}
            self.dirty=self.dirty or before!=self.cached

    def read(self):
        self.changed()  # A memory-only projection, never a provider call.
        with self.lock:
            return [self.cached.get(key,{'provider':key,'scope':'active_cli_account','state':'unavailable','phase':'disabled','category':'not_configured',
                'last_attempt_at':None,'last_success_at':None,'next_eligible_at':None,'snapshot':None}) for key in PROVIDERS]

    def refresh(self, data):
        if not isinstance(data,dict) or set(data)!={'providers'}: raise invalid()
        chosen=data['providers']
        if not isinstance(chosen,list) or not chosen or len(chosen)>2 or any(p not in PROVIDERS for p in chosen) or len(set(chosen))!=len(chosen): raise invalid('providers')
        outcomes=[]
        with self.lock:
            states={state.provider.lower():(state,wake) for state,wake in zip(self.runtime.states,self.runtime.wakes)}
            for key in chosen:
                if key not in states: outcome='unavailable';retry=None
                else:
                    state,wake=states[key];view=state.view();retry=utc(view.retry_at)
                    if view.phase=='refreshing' or key in self.pending: outcome='in_progress'
                    elif view.retry_at is not None: outcome='cooldown'
                    else: outcome='accepted';self.pending.add(key);wake.set()
                outcomes.append({'provider':key,'state':outcome,'check_id':None,'next_eligible_at':retry})
        status=202 if any(o['state']=='accepted' for o in outcomes) else 429 if all(o['state']=='cooldown' for o in outcomes) else 200
        return status,{'providers':outcomes}

    def flush(self):
        with self.lock:
            if not self.dirty: return
            values=dict(self.cached)
        with self.index.connection() as connection,transaction(connection,True):
            for provider,payload in values.items(): connection.execute('INSERT OR REPLACE INTO provider_cache VALUES (?,?)',(provider,json.dumps(payload,ensure_ascii=True,allow_nan=False)))
        with self.lock:
            if values==self.cached: self.dirty=False
