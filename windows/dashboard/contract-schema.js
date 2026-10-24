// Candidate only. S12 must agree/publish this wire contract before activation.
const text = (maxLength=512) => ({type:'string', maxLength});
const id = {type:'string', minLength:1, maxLength:512};
const ref = name => ({$ref:`#/$defs/${name}`});
const nullable = schema => ({anyOf:[schema,{type:'null'}]});
const list = (items,maxItems=100) => ({type:'array',items,maxItems});
const count = {type:'integer',minimum:0,maximum:Number.MAX_SAFE_INTEGER};
const choice = (...values) => ({enum:values});
const object = properties => ({type:'object',properties,required:Object.keys(properties),additionalProperties:false});
// Encode the int64 upper bound in the portable schema as well as client guards.
const tokenMax='9223372036854775807';
const bounded19=[...tokenMax].flatMap((digit,i)=>{
  const lower=i===0?1:0,upper=Number(digit)-1;
  return upper<lower?[]:[tokenMax.slice(0,i)+(lower===upper?lower:`[${lower}-${upper}]`)+(i<18?`[0-9]{${18-i}}`:'')];
});
const tokens = {type:'string',pattern:`^(0|[1-9][0-9]{0,17}|${bounded19.join('|')}|${tokenMax})$`,maxLength:19};
const money = {type:'string',pattern:'^(0|[1-9][0-9]{0,23})(\\.[0-9]{1,12})?$',maxLength:37};
const signedMoney = {type:'string',pattern:'^-?(0|[1-9][0-9]{0,23})(\\.[0-9]{1,12})?$',maxLength:38};
const instant = {type:'string',pattern:'^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\\.[0-9]{1,6})?Z$',maxLength:27};
const day = {type:'string',pattern:'^[0-9]{4}-[0-9]{2}-[0-9]{2}$',maxLength:10};
const providers = {type:'array',items:choice('codex','claude'),minItems:1,maxItems:2,uniqueItems:true};
const strings = (size=100) => ({...list(id,size),uniqueItems:true});
const defs = {tokens,money,signedMoney,instant,day,
  range:object({start_at:instant,end_at:instant,timezone:id,preset:choice('month','today','week')}),
  filters:object({providers,project_ids:strings(),models:strings(),efforts:strings(),search:text(200),selected_day:nullable(day)}),
  token_categories:object({uncached_input_tokens:tokens,output_tokens:tokens,cache_read_tokens:tokens,cache_write_5m_tokens:tokens,cache_write_1h_tokens:tokens,total_tokens:tokens}),
  value:object({state:choice('complete','partial','unpriced','empty'),amount_usd:nullable(money),priced_record_count:count,unpriced_record_count:count,priced_tokens:tokens,unpriced_tokens:tokens}),
  reasoning:object({known_tokens:tokens,known_record_count:count,unknown_record_count:count}),
  comparison:object({state:choice('available','partial','unavailable'),reason:nullable(id),fee_usd:nullable(money),difference_usd:nullable(signedMoney),qualifications:list(text())}),
  summary:object({tokens:ref('token_categories'),conversation_count:count,project_count:count,unknown_project_record_count:count,value:ref('value'),reasoning:ref('reasoning'),plan_comparison:ref('comparison')}),
  provider_coverage:object({provider:choice('codex','claude'),source_status:choice('complete','partial','failed','empty'),issue_codes:strings()}),
  coverage:object({scope:{const:'local_logs'},account_scope:{const:'all_local_accounts_unmatched'},index_status:choice('ready','stale','failed','indexing'),last_successful_scan_at:nullable(instant),missing_root_count:count,unreadable_file_count:count,skipped_interval_count:count,skipped_tokens:{type:'null'},issue_codes:strings(),providers:list(ref('provider_coverage'),2)}),
  project:object({project_id:id,display_path:text(4096)}),
  conversation:object({conversation_id:id,provider:choice('codex','claude'),provider_conversation_id:id,display_label:text(4096),projects:list(ref('project')),models:strings(),efforts:strings(),last_activity_at:instant,summary:ref('summary')}),
  page:object({next_cursor:nullable({...id,maxLength:4096}),page_size:{type:'integer',minimum:1,maximum:100}}),
  facet:object({id, label:text(4096),count,selected:{type:'boolean'}}),
  valuation:object({state:choice('priced','unpriced'),amount_usd:nullable(money),pricing_version:id,rate_id:nullable(id),tier:nullable(id),assumptions:list(text())}),
  event:object({event_id:id,conversation_id:id,provider:choice('codex','claude'),occurred_at:instant,model:id,effort:nullable(id),effort_source:nullable(text()),tokens:ref('token_categories'),reasoning_tokens:nullable(tokens),valuation:ref('valuation'),issue_codes:strings()}),
  job:object({job_id:id,kind:choice('index','reprice','settings'),state:choice('queued','running','succeeded','failed','superseded'),started_at:nullable(instant),completed_at:nullable(instant),phase:nullable(id),completed_count:count,total_count:nullable(count),issue_code:nullable(id),usage_revision:nullable(id),pricing_version:nullable(id),configuration_version:nullable(id)})
};
const envelope = {contract_version:{const:'1.0'},dataset_id:id,mode:choice('demo','local'),generated_at:instant,request_id:id};
const usage = {...envelope,query_context_id:id,usage_revision:id,pricing_version:id,configuration_version:id,range:ref('range'),applied_filters:ref('filters'),coverage:ref('coverage')};
// Client request objects before GET encoding; never JSON bodies for GET.
defs.query_selection=object({dataset_id:id,...defs.filters.properties,period:choice('month','today','week'),timezone:id});
defs.derived_selection=object({base_query_context_id:id,dataset_id:id,...defs.filters.properties});
defs.frozen_selection=object({query_context_id:id,cursor:nullable({...id,maxLength:4096}),sort:choice('value_desc','tokens_desc','last_activity_desc'),page_size:{type:'integer',minimum:1,maximum:100}});
defs.overview=object({...usage,summary:ref('summary'),days:list(object({day,summary:ref('summary')}),370),models:list(object({model:id,effort:nullable(id),provider:choice('codex','claude'),summary:ref('summary')})),projects:list(object({project:ref('project'),provider:choice('codex','claude'),summary:ref('summary')}))});
defs.conversations=object({...usage,summary:ref('summary'),items:list(ref('conversation')),page:ref('page')});
defs.detail=object({...usage,conversation:ref('conversation'),lifetime:object({first_activity_at:instant,last_activity_at:instant})});
defs.events=object({...usage,conversation_id:id,items:list(ref('event')),page:ref('page')});
defs.facets=object({...usage,projects:list(ref('facet')),models:list(ref('facet')),efforts:list(ref('facet'))});
defs.status=object({...envelope,build_version:id,usage_revision:nullable(id),pricing_version:nullable(id),configuration_version:id,index_status:choice('ready','stale','failed','indexing'),active_job_ids:strings()});
defs.job_response=object({...envelope,job:ref('job')});
defs.error=object({request_id:id,error:object({code:id,message:text(512),field_errors:list(object({field:id,code:id})),retry_at:nullable(instant)})});
// JSON Schema 2020-12 artifact is mirrored under docs/contracts; tests enforce equality.
export const contractSchema = {$schema:'https://json-schema.org/draft/2020-12/schema',
  title:'Usage Hub v1 frontend candidate',description:'Unagreed frontend preparation; not a published backend API.',
  $defs:defs,anyOf:['overview','conversations','detail','events','facets','status','job_response','error'].map(ref)};
