import {v1Schema} from './v1-schema.js';

export class LocalApiError extends Error {
  constructor(code='invalid_response',status=0){
    const messages={session_required:'Open the dashboard again through Usage Tray.',launch_expired:'The launch expired. Open the dashboard again through Usage Tray.',configuration_changed:'Settings changed elsewhere. Reload settings before saving again.',revision_changed:'Usage changed. Refresh the complete view.',context_expired:'This view expired. Refresh the complete view.',invalid_input:'Check the selected filters or settings.',index_unavailable:'No committed usage is available. Check local indexing status.',not_found:'This item is unavailable.'};
    super(Object.hasOwn(messages,code)?messages[code]:'The local service could not complete this request. Retry or reopen through the application.');
    this.name='LocalApiError';this.code=code;this.status=status;
  }
}
const fail=()=>{throw new LocalApiError();};
const keywords=new Set(['$schema','$id','$defs','title','description','$ref','anyOf','type','const','enum','properties','required','additionalProperties','items','minItems','maxItems','minLength','maxLength','pattern','minimum','maximum']);
// Only the published contract's bounded vocabulary; no third-party schema engine.
export function validateV1(kind,value){
  function visit(spec,item,depth=0){
    if(depth>32||!spec||Object.keys(spec).some(k=>!keywords.has(k)))fail();
    if(spec.$ref){if(!/^#\/\$defs\/[a-z_]+$/.test(spec.$ref))fail();return visit(v1Schema.$defs[spec.$ref.slice(8)],item,depth+1);}
    if(spec.anyOf&&!spec.anyOf.some(s=>{try{visit(s,item,depth+1);return true;}catch{return false;}}))fail();
    if(Object.hasOwn(spec,'const')&&spec.const!==item||spec.enum&&!spec.enum.includes(item))fail();
    const type=Array.isArray(item)?'array':item===null?'null':typeof item;
    if(spec.type&&(spec.type==='integer'?!Number.isSafeInteger(item):spec.type!==type))fail();
    if(type==='number'&&(!Number.isFinite(item)||item<(spec.minimum??-Infinity)||item>(spec.maximum??Infinity)))fail();
    if(type==='string'&&([...item].length<(spec.minLength??0)||[...item].length>(spec.maxLength??Infinity)||spec.pattern&&!new RegExp(spec.pattern,'u').test(item)))fail();
    if(type==='array'){if(item.length<(spec.minItems??0)||item.length>(spec.maxItems??Infinity))fail();for(const x of item)visit(spec.items??{},x,depth+1);}
    if(type==='object'){
      if((spec.required??[]).some(k=>!Object.hasOwn(item,k)))fail();
      for(const [key,x]of Object.entries(item)){
        if(Object.hasOwn(spec.properties??{},key))visit(spec.properties[key],x,depth+1);
        else if(spec.additionalProperties===false)fail();
        else if(spec.additionalProperties&&typeof spec.additionalProperties==='object')visit(spec.additionalProperties,x,depth+1);
      }
    }
  }
  visit(v1Schema.$defs[kind],value);
  if(kind!=='error'&&value.mode!=='real')fail(); // Demo has its own explicit entry point.
  function semantics(item,key=''){
    if(!item||typeof item!=='object')return;
    if(key==='tokens')for(const value of Object.values(item))if(value!==null&&BigInt(value)>9223372036854775807n)fail();
    for(const [k,v]of Object.entries(item)){
      if(v!==null&&typeof v==='string'&&k.endsWith('_at')&&!Number.isFinite(Date.parse(v)))fail();
      if(typeof v==='object')semantics(v,k);
    }
  }
  semantics(value);return structuredClone(value);
}

const route={overview:'/overview',conversations:'/usage/conversations',projects:'/usage/projects',facets:'/usage/facets',detail:'/conversations/',events:'/conversations/'};
const responseKind={conversations:'list',projects:'list',detail:'conversation'};
export function usagePath(kind,{contextId,baseContextId,query={},cursor=null,pageSize=50,sort='value_desc',conversationId}={}){
  if(!Object.hasOwn(route,kind)||contextId&&baseContextId||!Number.isInteger(pageSize)||pageSize<1||pageSize>100||!['value_desc','tokens_desc','last_activity_desc'].includes(sort))throw new TypeError('Invalid query');
  const p=new URLSearchParams();
  if(contextId)p.set('query_context_id',contextId);
  else{
    if(baseContextId)p.set('base_query_context_id',baseContextId);
    else{p.set('period',query.period??'month');if(query.timezone)p.set('timezone',query.timezone);}
    if(query.dataset_id)p.set('dataset_id',query.dataset_id);
    for(const key of ['provider','project_id','model','effort'])for(const v of query[key]??[])p.append(key,v);
    if(query.q)p.set('q',query.q.trim());if(query.selected_day)p.set('selected_day',query.selected_day);
  }
  if(['conversations','projects','events'].includes(kind)){p.set('page_size',String(pageSize));p.set('sort',kind==='events'?'events':sort);if(cursor)p.set('cursor',cursor);}
  let path=route[kind];
  if(['detail','events'].includes(kind)){
    if(typeof conversationId!=='string'||!conversationId||conversationId.length>1024)throw new TypeError('Missing conversation');
    path+=encodeURIComponent(conversationId)+(kind==='events'?'/events':'');
  }
  return '/api/v1'+path+'?'+p;
}
export function createLocalClient({fetchImpl=globalThis.fetch}={}){
  let csrf=null;
  async function send(path,kind,{signal,method='GET',body}={}){
    const headers={Accept:'application/json'};
    if(body!==undefined){headers['Content-Type']='application/json';if(csrf)headers['X-Usage-CSRF']=csrf;}
    const r=await fetchImpl('/api/v1'+path,{method,credentials:'same-origin',headers,signal,...(body===undefined?{}:{body:JSON.stringify(body)})});
    if(!/^application\/json(?:\s*;|$)/i.test(r.headers.get('content-type')??'')||Number(r.headers.get('content-length'))>8*1024*1024)fail();
    let raw='';
    if(r.body?.getReader){
      const reader=r.body.getReader(),decoder=new TextDecoder('utf-8',{fatal:true});let bytes=0;
      try{for(;;){const {done,value}=await reader.read();if(done)break;bytes+=value.byteLength;if(bytes>8*1024*1024)fail();raw+=decoder.decode(value,{stream:true});}raw+=decoder.decode();}
      catch(e){await reader.cancel().catch(()=>{});throw e;}finally{reader.releaseLock();}
    }else{raw=await r.text();if(new TextEncoder().encode(raw).length>8*1024*1024)fail();}
    let payload;try{payload=JSON.parse(raw);}catch{fail();}
    if(!r.ok){
      // Limits cooldown also includes operation results, rather than the error-only envelope.
      const error=r.status===429&&kind==='limits_refresh'?validateV1(kind,payload):validateV1('error',payload);
      throw new LocalApiError(error.error.code,r.status);
    }
    return validateV1(kind,payload);
  }
  return Object.freeze({
    async authenticate({location,history}){
      const p=new URLSearchParams(location.hash.slice(1)),launch=p.get('launch');
      if(launch){p.delete('launch');history.replaceState(null,'',location.pathname+(p.size?'#'+p:''));}
      const response=await send(launch?'/session/bootstrap':'/session','session',launch?{method:'POST',body:{launch_token:launch}}:{});
      csrf=response.data.csrf_token;return response;
    },
    async usage(kind,args,signal){
      const wire=await send(usagePath(kind,args).slice(7),responseKind[kind]??kind,{signal});
      if(args.contextId&&wire.query_context_id!==args.contextId||kind==='detail'&&wire.data.id!==args.conversationId)fail();
      if(kind==='events'&&wire.data.items.some(e=>e.value.pricing_version!==wire.pricing_version))fail();
      return wire;
    },
    read:(kind,signal)=>{if(!['status','settings','limits'].includes(kind))throw new TypeError('Unsupported read');return send('/'+kind,kind,{signal});},
    job:(id,signal)=>send('/jobs/'+encodeURIComponent(id),'job',{signal}),
    mutate:(kind,body,signal)=>{
      if(!csrf)throw new LocalApiError('session_required',403);
      const actions={refresh:['/index/refresh','job','POST'],settings:['/settings','settings_saved','PATCH'],limits:['/limits/refresh','limits_refresh','POST']};
      if(!Object.hasOwn(actions,kind))throw new TypeError('Unsupported mutation');
      const [path,response,method]=actions[kind];return send(path,response,{method,body,signal});
    }
  });
}
