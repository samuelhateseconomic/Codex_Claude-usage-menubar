// Deterministic synthetic projections. Values come from the earlier reviewed
// alignment example; this is not another pricing or ingestion implementation.
import {readFileSync} from 'node:fs';
const alignment=JSON.parse(readFileSync(new URL('../../../docs/fixtures/usage-hub-database-alignment.json',import.meta.url),'utf8'));
const clone=x=>structuredClone(x);
const comparison={state:'unavailable',reason:'period_not_month_to_date',fee_usd:null,difference_usd:null,qualifications:[]};
const tokenKeys=['uncached_input_tokens','output_tokens','cache_read_tokens','cache_write_5m_tokens','cache_write_1h_tokens','total_tokens'];
const makeTokens=source=>Object.fromEntries(tokenKeys.map(key=>[key,source[key]]));
const zeros=()=>Object.fromEntries(tokenKeys.map(key=>[key,'0']));
const summary={tokens:clone(alignment.expected_projection.tokens),conversation_count:2,project_count:1,unknown_project_record_count:0,
  value:{state:'complete',amount_usd:'18.891000000000',priced_record_count:2,unpriced_record_count:0,priced_tokens:'2905000',unpriced_tokens:'0'},
  reasoning:{known_tokens:'1260000',known_record_count:1,unknown_record_count:1},plan_comparison:clone(comparison)};
const coverage={scope:'local_logs',account_scope:'all_local_accounts_unmatched',index_status:'ready',last_successful_scan_at:'2026-10-23T13:59:00Z',missing_root_count:0,unreadable_file_count:0,skipped_interval_count:0,skipped_tokens:null,issue_codes:[],providers:['codex','claude'].map(provider=>({provider,source_status:'complete',issue_codes:[]}))};
const envelope={contract_version:'1.0',dataset_id:alignment.dataset.dataset_id,mode:'demo',generated_at:'2026-10-23T14:00:00Z',request_id:'fixture-request-1'};
const base={...envelope,query_context_id:'fixture-context-1',usage_revision:alignment.versions.usage_revision,pricing_version:alignment.versions.pricing_version,configuration_version:alignment.versions.configuration_version,range:{...alignment.base_query.range,preset:'month'},applied_filters:{providers:['codex','claude'],project_ids:[],models:[],efforts:[],search:'',selected_day:null},coverage};
const conversations=alignment.events.map(event=>({conversation_id:event.conversation_id,provider:event.provider,provider_conversation_id:event.provider_conversation_id,display_label:'Same visible label',projects:clone(alignment.projects).map(p=>({project_id:p.project_id,display_path:p.display_path})),models:[event.model],efforts:[event.effort],last_activity_at:event.occurred_at,
  summary:{tokens:makeTokens(event.tokens),conversation_count:1,project_count:1,unknown_project_record_count:0,value:{state:'complete',amount_usd:event.valuation.amount_usd,priced_record_count:1,unpriced_record_count:0,priced_tokens:event.tokens.total_tokens,unpriced_tokens:'0'},reasoning:{known_tokens:event.tokens.reasoning_tokens??'0',known_record_count:event.tokens.reasoning_tokens===null?0:1,unknown_record_count:event.tokens.reasoning_tokens===null?1:0},plan_comparison:clone(comparison)}}));
const overview={...clone(base),summary:clone(summary),days:[{day:'2026-10-23',summary:clone(summary)}],models:conversations.map(c=>({model:c.models[0],effort:c.efforts[0],provider:c.provider,summary:clone(c.summary)})),projects:conversations.map(c=>({project:clone(c.projects[0]),provider:c.provider,summary:clone(c.summary)}))};
const cases=[];
const add=(name,kind,response,extra={})=>cases.push({name,kind,...extra,response:clone(response)});
add('overview-complete','overview',overview);
const page={next_cursor:'opaque:next/+?=cursor',page_size:1};
add('conversation-page-1','conversations',{...clone(base),summary:clone(summary),items:[conversations[0]],page});
add('conversation-page-2','conversations',{...clone(base),summary:clone(summary),items:[conversations[1]],page:{...page,next_cursor:null}});
add('detail','detail',{...clone(base),conversation:conversations[0],lifetime:{first_activity_at:'2026-09-01T12:00:00Z',last_activity_at:conversations[0].last_activity_at}});
add('events','events',{...clone(base),conversation_id:conversations[0].conversation_id,items:[{event_id:alignment.events[0].event_id,conversation_id:conversations[0].conversation_id,provider:'codex',occurred_at:alignment.events[0].occurred_at,model:alignment.events[0].model,effort:'high',effort_source:'fixture explicit metadata',tokens:makeTokens(alignment.events[0].tokens),reasoning_tokens:'1260000',valuation:{...clone(alignment.events[0].valuation),pricing_version:base.pricing_version},issue_codes:[]}],page:{...page,next_cursor:null}});
add('facets','facets',{...clone(base),projects:[{id:'fixture-project',label:'C:/synthetic/usage-project',count:2,selected:false}],models:conversations.map(c=>({id:c.models[0],label:c.models[0],count:1,selected:false})),efforts:[{id:'high',label:'high',count:2,selected:false}]});
for(const name of ['empty','partial','unpriced','zero','stale','failed-retained','large','unknown-fee','zero-fee','known-zero-reasoning']){
  const response=clone(overview);
  if(['empty','partial','unpriced','zero','large'].includes(name)){response.days=[];response.models=[];response.projects=[];}
  if(name==='empty')response.summary={...clone(summary),tokens:zeros(),conversation_count:0,project_count:0,value:{state:'empty',amount_usd:null,priced_record_count:0,unpriced_record_count:0,priced_tokens:'0',unpriced_tokens:'0'},reasoning:{known_tokens:'0',known_record_count:0,unknown_record_count:0}};
  if(name==='partial'){response.summary.tokens.uncached_input_tokens='20100';response.summary.tokens.total_tokens='2905100';Object.assign(response.summary.value,{state:'partial',unpriced_record_count:1,unpriced_tokens:'100'});response.summary.reasoning.unknown_record_count=2;response.summary.conversation_count=3;}
  if(name==='unpriced')response.summary={...clone(summary),tokens:{...zeros(),uncached_input_tokens:'100',total_tokens:'100'},conversation_count:1,project_count:0,value:{state:'unpriced',amount_usd:null,priced_record_count:0,unpriced_record_count:1,priced_tokens:'0',unpriced_tokens:'100'},reasoning:{known_tokens:'0',known_record_count:0,unknown_record_count:1}};
  if(name==='zero')response.summary.value.amount_usd='0.000000000000';
  if(['stale','failed-retained'].includes(name)){response.mode='local';response.coverage.index_status=name==='stale'?'stale':'failed';response.coverage.unreadable_file_count=1;response.coverage.providers[0].source_status='failed';response.coverage.providers[0].issue_codes=['read_failed'];response.coverage.issue_codes=['read_failed'];}
  if(name==='large'){response.summary.tokens={...zeros(),output_tokens:'9223372036854775807',total_tokens:'9223372036854775807'};response.summary.value.priced_tokens='9223372036854775807';response.summary.value.amount_usd='999999999999999999999999.999999999999';}
  if(name==='unknown-fee')response.summary.plan_comparison={state:'unavailable',reason:'fee_unavailable',fee_usd:null,difference_usd:null,qualifications:['Not an actual bill']};
  if(name==='zero-fee')response.summary.plan_comparison={state:'available',reason:null,fee_usd:'0.00',difference_usd:'18.891000000000',qualifications:['Not an actual bill']};
  if(name==='known-zero-reasoning')response.summary.reasoning={known_tokens:'0',known_record_count:2,unknown_record_count:0};
  add('overview-'+name,'overview',response);
}
const multi=clone(conversations[0]);multi.projects.push({project_id:'different/project?=',display_path:'C:/synthetic/second'});multi.summary.project_count=2;
add('multi-project-detail','detail',{...clone(base),conversation:multi,lifetime:{first_activity_at:'2026-09-01T12:00:00Z',last_activity_at:multi.last_activity_at}});
add('status-initial-failure','status',{...clone(envelope),build_version:'fixture-build',usage_revision:null,pricing_version:null,configuration_version:base.configuration_version,index_status:'failed',active_job_ids:[]});
for(const state of ['queued','running','succeeded','failed','superseded'])add('job-'+state,'job_response',{...clone(envelope),job:{job_id:'fixture-job',kind:'index',state,started_at:state==='queued'?null:'2026-10-23T13:00:00Z',completed_at:['succeeded','failed','superseded'].includes(state)?'2026-10-23T14:00:00Z':null,phase:state==='queued'?null:'import',completed_count:state==='queued'?0:1,total_count:2,issue_code:state==='failed'?'read_failed':null,usage_revision:state==='succeeded'?base.usage_revision:null,pricing_version:state==='succeeded'?base.pricing_version:null,configuration_version:base.configuration_version}});
for(const [status,code]of [[409,'revision_changed'],[409,'context_expired'],[422,'invalid_input'],[429,'cooldown'],[401,'unauthorized'],[404,'not_found']])add('error-'+code,'error',{request_id:'fixture-error',error:{code,message:'Safe synthetic operation message',field_errors:status===422?[{field:'q',code:'too_long'}]:[],retry_at:status===429?'2026-10-23T14:05:00Z':null}},{http_status:status});
export const fixtureSet={candidate_version:'frontend-preparation-1',purpose:'Synthetic candidate responses, not implemented API output',cases};
