import test from 'node:test';
import assert from 'node:assert/strict';
import {fixtureSet} from './v1-fixture-builder.mjs';
import {buildUsageRequest,createV1Client,createPreviewClient,usageViewModel,ApiError} from '../api-client.js';
import {ContractError} from '../response-contract.js';
const fixture=name=>structuredClone(fixtureSet.cases.find(item=>item.name===name).response);
export const query=()=>({dataset_id:'fixture-demo-local',providers:['codex','claude'],project_ids:[],models:[],efforts:[],search:'',selected_day:null,period:'month',timezone:'America/Los_Angeles'});
const response=(payload,status=200)=>new Response(JSON.stringify(payload),{status,headers:{'content-type':'application/json; charset=utf-8'}});
test('GET query encoding preserves opaque IDs and repeated selection without context conflicts',()=>{
  const input={...query(),project_ids:['id/?=&','second'],models:['m &+'],efforts:['high'],search:'literal a?b'};
  const url=new URL(buildUsageRequest('conversations',{query:input}),'http://local.invalid');
  assert.deepEqual(url.searchParams.getAll('provider'),['codex','claude']);assert.deepEqual(url.searchParams.getAll('project_id'),input.project_ids);
  assert.equal(url.searchParams.get('q'),'literal a?b');assert.equal(url.searchParams.get('page_size'),'50');assert.equal(url.searchParams.get('sort'),'value_desc');
  const frozen=new URL(buildUsageRequest('events',{contextId:'ctx/+?',conversationId:'conv/?=&',cursor:'next/+?='}),'http://local.invalid');
  assert.equal(frozen.pathname,'/api/v1/conversations/conv%2F%3F%3D%26/events');assert.equal(frozen.searchParams.get('cursor'),'next/+?=');assert.equal(frozen.searchParams.get('sort'),'occurred_at_asc');assert.equal(frozen.searchParams.has('period'),false);
  const derived=new URL(buildUsageRequest('overview',{query:input,baseContextId:'base'}),'http://local.invalid');
  assert.equal(derived.searchParams.get('base_query_context_id'),'base');assert.equal(derived.searchParams.has('period'),false);assert.equal(derived.searchParams.has('timezone'),false);
});
test('invalid context, selection and request bounds fail before fetch',()=>{
  for(const args of [{query:query(),contextId:'ctx'},{contextId:'ctx',baseContextId:'base'},{query:query(),pageSize:101},{query:{...query(),providers:[]}},{query:{...query(),search:'x'.repeat(201)}},{query:{...query(),search:' trim '}},{query:{...query(),period:'year'}},{query:{...query(),timezone:'Invalid/Zone'}},{query:{...query(),unknown:'field'}}])assert.throws(()=>buildUsageRequest('overview',args));
  assert.throws(()=>buildUsageRequest('unknown',{query:query()}));assert.throws(()=>buildUsageRequest('detail',{contextId:'ctx',conversationId:''}));
});
test('v1 transport validates exact wire data, uses same-origin GET and never falls back to preview',async()=>{
  const calls=[],signal=new AbortController().signal;
  const client=createV1Client({expectedMode:'demo',fetchImpl:async(path,options)=>{calls.push({path,options});return response(fixture('overview-large'));}});
  const wire=await client.usage('overview',{query:query()},signal);
  assert.equal(wire.summary.tokens.total_tokens,'9223372036854775807');assert.equal(wire.summary.value.amount_usd,'999999999999999999999999.999999999999');
  assert.equal(calls[0].options.credentials,'same-origin');assert.equal(calls[0].options.method,'GET');assert.equal(calls[0].options.signal,signal);assert.equal(calls.length,1);
  const vm=usageViewModel('overview',wire);vm.summary.tokens.total_tokens='0';assert.equal(wire.summary.tokens.total_tokens,'9223372036854775807');
  const live=createV1Client({fetchImpl:async()=>response(fixture('overview-complete'))});await assert.rejects(live.usage('overview',{query:query()}),ContractError);
});
test('errors retain safe codes/retry metadata without displaying server text',async()=>{
  for(const item of fixtureSet.cases.filter(item=>item.kind==='error')){
    const payload=structuredClone(item.response);payload.error.message='SECRET SQL /credential/path\u001b[2J';
    const client=createV1Client({fetchImpl:async()=>response(payload,item.http_status)});
    await assert.rejects(client.usage('overview',{query:query()}),error=>{assert.ok(error instanceof ApiError);assert.equal(error.status,item.http_status);assert.equal(error.code,payload.error.code);assert.equal(error.retryAt,payload.error.retry_at);assert.doesNotMatch(error.message,/SECRET|credential/);return true;});
  }
});
test('transport rejects oversized, invalid JSON/content and preserves abort/network failures',async()=>{
  const cases=[()=>new Response('<html>broken</html>'),()=>new Response('{',{headers:{'content-type':'application/json'}}),()=>new Response('{}',{headers:{'content-type':'application/json','content-length':'3000000'}}),()=>new Response(' '.repeat(2097153),{headers:{'content-type':'application/json'}}),()=>response({error:'not v1'},500)];
  for(const make of cases){const client=createV1Client({fetchImpl:async()=>make()});await assert.rejects(client.status(),ContractError);}
  const aborted=new DOMException('Aborted','AbortError');await assert.rejects(createV1Client({fetchImpl:async()=>{throw aborted;}}).status(),error=>error===aborted);
});
test('explicit preview adapter retains its own routes and authorization marker',async()=>{
  const calls=[];const client=createPreviewClient({fetchImpl:async(path,options)=>{calls.push({path,options});return response({dataset:'demo'});}});
  assert.deepEqual(await client.query(new URLSearchParams({provider:'both'})),{dataset:'demo'});await client.rescan();
  assert.equal(calls[0].path,'/api/preview/query?provider=both');assert.equal(calls[0].options.headers['X-Usage-Hub'],'1');assert.equal(calls[1].options.method,'POST');
});
test('view model keeps freshness and accounting state independent without reordering rows',()=>{
  const vm=usageViewModel('overview',fixture('overview-stale'));assert.equal(vm.freshness.state,'stale');assert.equal(vm.summary.value.state,'complete');assert.equal(vm.coverage.providers[0].source_status,'failed');
  const page=usageViewModel('conversations',fixture('conversation-page-1'));assert.equal(page.body.items[0].conversation_id,'fixture-conversation-codex');assert.equal(page.summary.conversation_count,2);
  assert.equal(usageViewModel('detail',fixture('multi-project-detail')).body.conversation.projects.length,2);
});
test('detail/events never substitute another frozen context or conversation',async()=>{
  const client=createV1Client({expectedMode:'demo',fetchImpl:async path=>response(fixture(path.includes('/events')?'events':'detail'))});
  await assert.rejects(client.usage('detail',{contextId:'different-context',conversationId:'fixture-conversation-codex'}),ContractError);
  await assert.rejects(client.usage('detail',{contextId:'fixture-context-1',conversationId:'wrong-id'}),ContractError);
  await assert.rejects(client.usage('events',{contextId:'fixture-context-1',conversationId:'wrong-id'}),ContractError);
});
