import {validateResponse, validateSchema, ContractError} from './response-contract.js';
import {contractSchema} from './contract-schema.js';

const MAX_BYTES=2*1024*1024;
const paths={overview:'/overview',conversations:'/usage/conversations',facets:'/usage/facets',detail:'/conversations/',events:'/conversations/'};
const own=(value,key)=>Object.prototype.hasOwnProperty.call(value,key);
const checkId=value=>validateSchema({type:'string',minLength:1,maxLength:512},value);
const safeMessages={revision_changed:'Usage changed. Refresh this view.',context_expired:'This view expired. Refresh it.',
  unauthorized:'Open the dashboard again from the application.',forbidden:'Open the dashboard again from the application.',
  invalid_input:'Check the selected filters.',not_found:'This item is no longer available.',cooldown:'Wait before trying this operation again.'};
export class ApiError extends Error {
  constructor(status,code,requestId=null,retryAt=null){super(own(safeMessages,code)?safeMessages[code]:'The local service could not complete the request. Retry this view.');this.name='ApiError';Object.assign(this,{status,code,requestId,retryAt});}
}

export function buildUsageRequest(kind,{query=null,contextId=null,baseContextId=null,cursor=null,sort='value_desc',pageSize=50,conversationId=null}={}){
  const hasContext=contextId!==null,hasBase=baseContextId!==null,hasQuery=query!==null;
  if(!own(paths,kind)||hasContext&&hasBase||hasContext&&hasQuery||!hasContext&&!hasQuery)throw new TypeError('Invalid query context selection');
  if(!['value_desc','tokens_desc','last_activity_desc'].includes(sort)||!Number.isInteger(pageSize)||pageSize<1||pageSize>100)throw new TypeError('Invalid list selection');
  const params=new URLSearchParams();
  if(hasContext){checkId(contextId);params.set('query_context_id',contextId);}
  else{
    validateSchema(contractSchema.$defs.query_selection,query);
    if(query.search!==query.search.trim())throw new TypeError('Search must be normalized');
    params.set('dataset_id',query.dataset_id);
    for(const [key,wire] of [['providers','provider'],['project_ids','project_id'],['models','model'],['efforts','effort']])for(const value of query[key])params.append(wire,value);
    if(query.search)params.set('q',query.search);
    if(query.selected_day!==null)params.set('selected_day',query.selected_day);
    if(hasBase){checkId(baseContextId);params.set('base_query_context_id',baseContextId);}
    else{
      if(!['today','week','month'].includes(query.period))throw new TypeError('Invalid period');
      checkId(query.timezone);
      try{new Intl.DateTimeFormat('en',{timeZone:query.timezone});}catch{throw new TypeError('Invalid timezone');}
      params.set('period',query.period);params.set('timezone',query.timezone);
    }
  }
  if(['conversations','events'].includes(kind)){
    params.set('sort',kind==='events'?'occurred_at_asc':sort);params.set('page_size',String(pageSize));
    if(cursor!==null){validateSchema({type:'string',minLength:1,maxLength:4096},cursor);params.set('cursor',cursor);}
  }else if(cursor!==null)throw new TypeError('Cursor requires a paged endpoint');
  let path=paths[kind];
  if(['detail','events'].includes(kind)){checkId(conversationId);path+=encodeURIComponent(conversationId);if(kind==='events')path+='/events';}
  return '/api/v1'+path+'?'+params.toString();
}

// Read-only candidate transport. No mutation/bootstrap/CSRF policy is invented.
// The caller supplies same-origin fetch; production activation is an S12/S13 gate.
export function createV1Client({fetchImpl=globalThis.fetch,expectedMode='local'}={}){
  if(!['local','demo'].includes(expectedMode))throw new TypeError('Explicit local or demo scope required');
  async function read(path,kind,signal){
    const response=await fetchImpl(path,{method:'GET',credentials:'same-origin',headers:{Accept:'application/json'},signal});
    if(!/^application\/json(?:\s*;|$)/i.test(response.headers?.get('content-type')??''))throw new ContractError();
    const declared=Number(response.headers?.get('content-length'));
    if(declared>MAX_BYTES)throw new ContractError();
    // Streaming bounds prevent an oversized local response from being retained.
    let raw='';
    if(response.body?.getReader){
      const reader=response.body.getReader(),decoder=new TextDecoder('utf-8',{fatal:true});let bytes=0;
      try{for(;;){const {done,value}=await reader.read();if(done)break;bytes+=value.byteLength;if(bytes>MAX_BYTES)throw new ContractError();raw+=decoder.decode(value,{stream:true});}raw+=decoder.decode();}
      catch(error){await reader.cancel().catch(()=>{});if(error.name==='AbortError'||error instanceof ContractError)throw error;throw new ContractError();}
      finally{reader.releaseLock();}
    }else{
      raw=await response.text();if(new TextEncoder().encode(raw).length>MAX_BYTES)throw new ContractError();
    }
    let payload;try{payload=JSON.parse(raw);}catch{throw new ContractError();}
    if(!response.ok){
      const safe=validateResponse('error',payload);
      throw new ApiError(response.status,safe.error.code,safe.request_id,safe.error.retry_at);
    }
    const result=validateResponse(kind,payload);
    if(result.mode!==expectedMode)throw new ContractError();
    return result;
  }
  return Object.freeze({
    async usage(kind,request={},signal){
      const result=await read(buildUsageRequest(kind,request),kind,signal);
      if(request.contextId&&result.query_context_id!==request.contextId||request.query&&result.dataset_id!==request.query.dataset_id)throw new ContractError();
      if(kind==='detail'&&result.conversation.conversation_id!==request.conversationId)throw new ContractError();
      if(kind==='events'&&(result.conversation_id!==request.conversationId||result.items.some(event=>event.conversation_id!==request.conversationId||event.valuation.pricing_version!==result.pricing_version)))throw new ContractError();
      return result;
    },
    status:signal=>read('/api/v1/status','status',signal),
    job:(jobId,signal)=>{checkId(jobId);return read('/api/v1/jobs/'+encodeURIComponent(jobId),'job_response',signal);}
  });
}

// Explicit compatibility boundary for today's demo; never a v1 error fallback.
export function createPreviewClient({fetchImpl=globalThis.fetch}={}){
  const send=async(path,options={})=>{
    const response=await fetchImpl(path,{...options,headers:{'X-Usage-Hub':'1'},credentials:'same-origin'});
    const payload=await response.json();
    if(!response.ok)throw new ApiError(response.status,'preview_request_failed');
    return payload;
  };
  return Object.freeze({query:(params,signal)=>send('/api/preview/query?'+params.toString(),{signal}),rescan:()=>send('/api/preview/rescan',{method:'POST'})});
}

// View model is intentionally distinct from preview DTOs. No repricing,
// aggregation, sorting or display-label identity occurs at this boundary.
export function usageViewModel(kind,payload){
  const wire=validateResponse(kind,payload);
  if(!['overview','conversations','detail','events','facets'].includes(kind))throw new TypeError('Usage response required');
  return {
    context:{datasetId:wire.dataset_id,mode:wire.mode,id:wire.query_context_id,usageRevision:wire.usage_revision,pricingVersion:wire.pricing_version,configurationVersion:wire.configuration_version,range:wire.range,filters:wire.applied_filters},
    freshness:{state:wire.coverage.index_status,lastSuccessfulScanAt:wire.coverage.last_successful_scan_at},
    coverage:wire.coverage,
    summary:wire.summary??wire.conversation?.summary??null,
    body:wire
  };
}
