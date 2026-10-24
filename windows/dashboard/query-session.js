import {ApiError} from './api-client.js';
import {ContractError} from './response-contract.js';

const copy=value=>structuredClone(value);
const stable=value=>value&&typeof value==='object'?(Array.isArray(value)?value.map(stable):Object.fromEntries(Object.keys(value).sort().map(key=>[key,stable(value[key])]))):value;
const tuple=wire=>[wire.dataset_id,wire.mode,wire.query_context_id,wire.usage_revision,wire.pricing_version,wire.configuration_version,wire.range,wire.applied_filters];
const same=(left,right)=>JSON.stringify(stable(left))===JSON.stringify(stable(right));
const terminalJobs=new Set(['succeeded','failed','superseded']);
const isConflict=error=>error instanceof ApiError&&error.status===409&&['revision_changed','context_expired'].includes(error.code);
function matchesSelection(anchor,selection){
  if(!selection)return true;
  if(anchor.dataset_id!==selection.dataset_id||anchor.range.preset!==selection.period||anchor.range.timezone!==selection.timezone)return false;
  for(const key of ['providers','project_ids','models','efforts'])if(!same([...anchor.applied_filters[key]].sort(),[...selection[key]].sort()))return false;
  return anchor.applied_filters.search===selection.search&&anchor.applied_filters.selected_day===selection.selected_day;
}

// Pure request preparation and retained navigation state. UI history/storage is
// deliberately left to S13; no context secrets go to localStorage or URLs here.
export class QueryNavigation {
  constructor(query){this.query=copy(query);this.contextId=null;this.context=null;this.cursor=null;this.previous=[];this.sort='value_desc';this.pageSize=50;this.scrollY=0;this.conversationId=null;this.parent=null;}
  request({fresh=false,derive=false}={}){
    const args={sort:this.sort,pageSize:this.pageSize,cursor:fresh||derive?null:this.cursor};
    if(!fresh&&this.contextId){if(derive){args.query=copy(this.query);args.baseContextId=this.contextId;}else args.contextId=this.contextId;}
    else args.query=copy(this.query);
    return args;
  }
  accept(wire){
    if(wire.dataset_id!==this.query.dataset_id)throw new ContractError();
    const context=tuple(wire);
    if(this.context&&(!same(this.context.slice(0,2),context.slice(0,2))||!same(this.context.slice(3,7),context.slice(3,7))))throw new ContractError();
    this.context=copy(context);
    this.contextId=wire.query_context_id;
    Object.assign(this.query,copy(wire.applied_filters),{period:wire.range.preset,timezone:wire.range.timezone});
  }
  change(changes){
    const recapture=Object.keys(changes).some(key=>['period','timezone','dataset_id'].includes(key)&&changes[key]!==this.query[key]);
    Object.assign(this.query,copy(changes));this.resetPages();this.conversationId=null;this.parent=null;
    if(recapture){this.contextId=null;this.context=null;this.query.selected_day=null;}
    return this.request({derive:!recapture});
  }
  order(sort,pageSize=this.pageSize){this.sort=sort;this.pageSize=pageSize;this.resetPages();return this.request();}
  resetPages(){this.cursor=null;this.previous=[];}
  refresh(){this.contextId=null;this.context=null;this.resetPages();this.conversationId=null;this.parent=null;return this.request({fresh:true});}
  next(cursor){if(typeof cursor!=='string'||!cursor)throw new TypeError('No next page');this.previous.push(this.cursor);this.cursor=cursor;return this.request();}
  prev(){if(!this.previous.length)throw new TypeError('No previous page');this.cursor=this.previous.pop();return this.request();}
  detail(conversationId,scrollY){
    if(!this.contextId||typeof conversationId!=='string'||!conversationId||!Number.isFinite(scrollY)||scrollY<0)throw new TypeError('No parent query');
    this.scrollY=scrollY;this.parent=this.snapshot();this.conversationId=conversationId;return {...this.request(),cursor:null,conversationId};
  }
  back(){if(!this.parent)throw new TypeError('No parent list');const state=this.parent;Object.assign(this,copy(state));return {request:this.request(),scrollY:this.scrollY};}
  snapshot(){return copy({query:this.query,contextId:this.contextId,context:this.context,cursor:this.cursor,previous:this.previous,sort:this.sort,pageSize:this.pageSize,scrollY:this.scrollY,conversationId:this.conversationId,parent:null});}
}

// Fetch one anchor, then related widgets under that exact context. Publish only
// complete bundles. A newer operation wins even if fetch ignores AbortSignal.
export function createQuerySession(client){
  let sequence=0,controller,lastAccepted=null;
  return {
    get accepted(){return lastAccepted===null?null:copy(lastAccepted);},
    cancel(){sequence++;controller?.abort();},
    async load({kind='overview',request,selection=request.query,related=[]}){
      if(!['overview','conversations'].includes(kind)||new Set(related).size!==related.length||related.some(item=>!['facets','conversations'].includes(item)))throw new TypeError('Unsupported bundle');
      selection=selection===undefined?undefined:copy(selection);related=[...related];
      const current=++sequence;controller?.abort();let active=new AbortController();controller=active;
      const original=copy(request);let args=copy(original);
      for(let attempt=0;attempt<2;attempt++){
        try{
          const anchor=await client.usage(kind,args,active.signal);
          if(current!==sequence)return {state:'superseded'};
          if(args.contextId&&anchor.query_context_id!==args.contextId||!matchesSelection(anchor,selection))throw new ContractError();
          const previous=lastAccepted?.anchor,base=args.contextId??args.baseContextId;
          if(previous&&base===previous.query_context_id){
            if(!same(tuple(previous).slice(0,2),tuple(anchor).slice(0,2))||!same(tuple(previous).slice(3,7),tuple(anchor).slice(3,7)))throw new ContractError();
          }
          const responses=await Promise.all(related.map(endpoint=>client.usage(endpoint,{contextId:anchor.query_context_id,sort:args.sort,pageSize:args.pageSize},active.signal)));
          if(current!==sequence)return {state:'superseded'};
          if(responses.some(wire=>!same(tuple(anchor),tuple(wire))))throw new ContractError();
          const bundle={anchor,related:Object.fromEntries(related.map((endpoint,i)=>[endpoint,responses[i]]))};
          lastAccepted=copy(bundle);return {state:'accepted',bundle:copy(bundle),refreshed:attempt>0};
        }catch(error){
          if(current!==sequence||error.name==='AbortError')return {state:'superseded'};
          if(attempt===0&&isConflict(error)&&selection){
            active.abort();active=new AbortController();controller=active;
            args={query:copy(selection),cursor:null,sort:original.sort,pageSize:original.pageSize};
            continue;
          }
          active.abort();
          throw error;
        }
      }
    }
  };
}

// Explicit, bounded job observation. No job is created and no provider polled.
export function createJobObserver(client,{wait=(ms,signal)=>new Promise((resolve,reject)=>{
  if(signal.aborted){reject(new DOMException('Aborted','AbortError'));return;}
  const cancel=()=>{clearTimeout(timer);reject(new DOMException('Aborted','AbortError'));};
  const timer=setTimeout(()=>{signal.removeEventListener('abort',cancel);resolve();},ms);signal.addEventListener('abort',cancel,{once:true});
})}={}){
  let sequence=0,controller;
  return {
    stop(){sequence++;controller?.abort();},
    async watch(jobId,{onUpdate=()=>{},maxAttempts=30,intervalMs=1000}={}){
      if(!Number.isInteger(maxAttempts)||maxAttempts<1||maxAttempts>60||!Number.isInteger(intervalMs)||intervalMs<250||intervalMs>10000)throw new TypeError('Invalid polling bounds');
      const current=++sequence;controller?.abort();const active=new AbortController();controller=active;
      let identity=null;
      try{
        for(let attempt=0;attempt<maxAttempts;attempt++){
          const response=await client.job(jobId,active.signal);
          if(current!==sequence)return {state:'superseded'};
          if(response.job.job_id!==jobId)throw new ContractError();
          const received=[response.dataset_id,response.mode,response.job.kind];
          if(identity&&!same(identity,received))throw new ContractError();identity=received;
          onUpdate(copy(response));
          if(current!==sequence)return {state:'superseded'};
          if(terminalJobs.has(response.job.state))return {state:response.job.state,response};
          if(attempt+1<maxAttempts)await wait(intervalMs,active.signal);
        }
        return {state:'pending',jobId};
      }catch(error){if(current!==sequence||error.name==='AbortError')return {state:'superseded'};throw error;}
    }
  };
}
