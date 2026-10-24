import {LocalApiError} from './v1-client.js';

const copy=structuredClone;
const stable=v=>JSON.stringify(v&&typeof v==='object'?Array.isArray(v)?v.map(x=>JSON.parse(stable(x))):Object.fromEntries(Object.keys(v).sort().map(k=>[k,JSON.parse(stable(v[k]))])):v);
const same=(a,b)=>stable(a)===stable(b);
const tuple=w=>[w.dataset_id,w.mode,w.query_context_id,w.usage_revision,w.pricing_version,w.configuration_version,w.range,w.applied_filters];
const metadata=w=>Object.fromEntries(['dataset_id','mode','query_context_id','usage_revision','pricing_version','configuration_version','range','applied_filters'].map(k=>[k,copy(w[k])]));
export const defaultSelection=()=>({period:'month',timezone:null,provider:'both',project:'',model:'',effort:'',q:'',day:''});
export function selectionQuery(s){
  return {period:s.period,...(s.timezone?{timezone:s.timezone}:{}),provider:s.provider==='both'?['claude','codex']:[s.provider],project_id:s.project?[s.project]:[],model:s.model?[s.model]:[],effort:s.effort?[s.effort]:[],q:s.q.trim(),selected_day:s.day||null};
}
const filtered=s=>Boolean(s.provider!=='both'||s.project||s.model||s.effort||s.q.trim()||s.day);
export function coherent(anchor,...others){if(others.some(w=>!same(tuple(w),tuple(anchor))))throw new LocalApiError();}

// Browser navigation owns snapshots. This loader only publishes complete,
// coherent bundles, preserving the last accepted result when a request fails.
export function createLocalSession(client){
  let sequence=0,abort,accepted=null;
  return {
    cancel(){sequence++;abort?.abort();},
    get accepted(){return accepted?copy(accepted):null;},
    async load(state,{navigation=null,fresh=false}={}){
      const current=++sequence;abort?.abort();abort=new AbortController();
      state=copy(state);navigation=navigation?copy(navigation):null;
      let active=abort;
      const obsolete=()=>current!==sequence;
      for(let attempt=0;attempt<2;attempt++){
        try{
          if(['limits','settings'].includes(state.view)){
            const [wire,status]=await Promise.all([client.read(state.view,active.signal),client.read('status',active.signal)]);
            if(obsolete())return {state:'superseded'};
            if(wire.dataset_id!==status.dataset_id)throw new LocalApiError();
            const bundle={view:state.view,wire,status,navigation};accepted=copy(bundle);return {state:'accepted',bundle};
          }
          const selection=Object.fromEntries(Object.keys(defaultSelection()).map(k=>[k,state[k]??defaultSelection()[k]]));
          let root=!fresh&&!attempt?navigation?.root:null;
          if(root&&(root.range.preset!==selection.period||selection.timezone&&root.range.timezone!==selection.timezone))root=null;
          let initial;
          if(!root){initial=await client.usage('overview',{query:{period:selection.period,...(selection.timezone?{timezone:selection.timezone}:{})}},active.signal);root=metadata(initial);}
          if(obsolete())return {state:'superseded'};
          let overview;
          if(!fresh&&!attempt&&navigation?.context&&same(navigation.selection,selection))overview=await client.usage('overview',{contextId:navigation.context.query_context_id},active.signal);
          else if(filtered(selection))overview=await client.usage('overview',{baseContextId:root.query_context_id,query:selectionQuery(selection)},active.signal);
          else overview=initial??await client.usage('overview',{contextId:root.query_context_id},active.signal);
          // A derived selection may change filters/effective day bounds, never
          // the base clock or publication under which it was requested.
          for(const k of ['dataset_id','mode','usage_revision','pricing_version','configuration_version'])if(overview[k]!==root[k])throw new LocalApiError();
          for(const k of ['preset','timezone','start_at','end_at'])if(overview.range[k]!==root.range[k])throw new LocalApiError();
          const expected=selectionQuery(selection),applied=overview.applied_filters;
          for(const k of ['provider','project_id','model','effort'])if(!same([...expected[k]].sort(),[...applied[k]].sort()))throw new LocalApiError();
          if(applied.selected_day!==expected.selected_day)throw new LocalApiError();
          // The service owns Unicode case folding. Retain original input for
          // editing; compare ASCII directly without inventing a second search engine.
          if(/^[\x00-\x7f]*$/.test(expected.q)&&applied.q!==expected.q.toLowerCase())throw new LocalApiError();
          const reuse=!fresh&&!attempt&&same(navigation?.selection,selection)&&navigation?.context?.query_context_id===overview.query_context_id;
          const nav={root,context:metadata(overview),selection,cursor:reuse?navigation.cursor??null:null,previous:reuse?navigation.previous??[]:[],eventsCursor:reuse?navigation.eventsCursor??null:null,eventPrevious:reuse?navigation.eventPrevious??[]:[],sort:state.sort??'value_desc',pageSize:state.pageSize??50};
          const args={contextId:overview.query_context_id,pageSize:nav.pageSize,sort:nav.sort};
          let list,facets,detail,events;
          if(state.view==='explore') [list,facets]=await Promise.all([client.usage(state.table==='projects'?'projects':'conversations',{...args,cursor:nav.cursor},active.signal),client.usage('facets',args,active.signal)]);
          if(state.view==='detail') [detail,events]=await Promise.all([client.usage('detail',{...args,conversationId:state.conversation},active.signal),client.usage('events',{...args,conversationId:state.conversation,cursor:nav.eventsCursor},active.signal)]);
          coherent(overview,...[list,facets,detail,events].filter(Boolean));
          if(detail&&!same(detail.data.summary,events.data.summary))throw new LocalApiError();
          if(list&&!same(overview.data.summary,list.data.summary))throw new LocalApiError();
          const status=await client.read('status',active.signal);
          if(status.dataset_id!==overview.dataset_id)throw new LocalApiError();
          if(obsolete())return {state:'superseded'};
          const bundle={view:state.view,overview,list,facets,detail,events,status,navigation:nav};
          accepted=copy(bundle);return {state:'accepted',bundle:copy(bundle),refreshed:attempt>0||fresh};
        }catch(error){
          active.abort();
          if(obsolete()||error.name==='AbortError')return {state:'superseded'};
          if(attempt===0&&error.status===409&&['context_expired','revision_changed'].includes(error.code)){
            active=new AbortController();abort=active;continue;
          }
          throw error;
        }
      }
    }
  };
}

export async function observeLocalJob(client,id,{signal,onUpdate=()=>{},attempts=30,wait=(ms,signal)=>new Promise((resolve,reject)=>{
  if(signal.aborted)return reject(new DOMException('Aborted','AbortError'));
  const cancel=()=>{clearTimeout(timer);reject(new DOMException('Aborted','AbortError'));};
  const timer=setTimeout(()=>{signal.removeEventListener('abort',cancel);resolve();},ms);signal.addEventListener('abort',cancel,{once:true});
})}={}){
  if(!Number.isInteger(attempts)||attempts<1||attempts>30)throw new TypeError('Invalid observation bound');
  let identity;
  for(let i=0;i<attempts;i++){
    if(signal.aborted)return {state:'superseded'};
    const wire=await client.job(id,signal);
    if(signal.aborted)return {state:'superseded'};
    const tuple=[wire.dataset_id,wire.mode,wire.data.id,wire.data.kind];
    if(wire.data.id!==id||identity&&!same(identity,tuple))throw new LocalApiError();identity=tuple;
    onUpdate(wire.data);
    if(signal.aborted)return {state:'superseded'};
    if(['succeeded','failed','superseded'].includes(wire.data.status))return {state:wire.data.status,job:wire.data};
    if(i+1<attempts)await wait(1000,signal);
  }
  return {state:'pending'};
}
