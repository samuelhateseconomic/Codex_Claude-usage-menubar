import test from 'node:test';
import assert from 'node:assert/strict';
import {fixtureSet} from './v1-fixture-builder.mjs';
import {QueryNavigation,createQuerySession,createJobObserver} from '../query-session.js';
import {ApiError,buildUsageRequest,createV1Client} from '../api-client.js';
import {ContractError} from '../response-contract.js';
const fixture=name=>structuredClone(fixtureSet.cases.find(item=>item.name===name).response);
const query=()=>({dataset_id:'fixture-demo-local',providers:['codex','claude'],project_ids:[],models:[],efforts:[],search:'',selected_day:null,period:'month',timezone:'America/Los_Angeles'});
const pending=()=>{let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no;});return {promise,resolve,reject};};
const settle=()=>new Promise(setImmediate);
const conflict=()=>new ApiError(409,'revision_changed');

test('frozen filters derive from the existing range; preset/timezone refresh clears context and cursors',()=>{
  const nav=new QueryNavigation(query());nav.accept(fixture('overview-complete'));
  nav.next('opaque-next');const derived=nav.change({providers:['claude'],search:'fixture'});
  assert.equal(derived.baseContextId,'fixture-context-1');assert.equal(derived.cursor,null);assert.deepEqual(derived.query.providers,['claude']);assert.equal(nav.previous.length,0);
  const url=new URL(buildUsageRequest('overview',derived),'http://local.invalid');assert.equal(url.searchParams.has('period'),false);
  const response=fixture('overview-complete');response.query_context_id='derived';response.applied_filters.providers=['claude'];response.applied_filters.search='fixture';nav.accept(response);
  assert.equal(nav.request().contextId,'derived');assert.equal(nav.context[3],response.usage_revision);
  const today=nav.change({period:'today'});assert.equal(today.query.period,'today');assert.equal(today.contextId,undefined);assert.equal(nav.context,null);
  nav.accept({...response,range:{...response.range,preset:'today'}});nav.next('next-again');
  const refreshed=nav.refresh();assert.equal(refreshed.query.search,'fixture');assert.equal(refreshed.cursor,null);assert.equal(nav.contextId,null);
});
test('opaque cursor stack, full parent context and scroll survive detail and Back',()=>{
  const nav=new QueryNavigation(query());nav.accept(fixture('conversation-page-1'));
  nav.next('first/+?');nav.next('second');assert.equal(nav.prev().cursor,'first/+?');
  const detail=nav.detail('id/?=&',713);assert.equal(detail.contextId,'fixture-context-1');assert.equal(detail.cursor,null);assert.equal(detail.conversationId,'id/?=&');
  const restored=nav.back();assert.equal(restored.request.cursor,'first/+?');assert.equal(restored.scrollY,713);assert.equal(nav.previous.length,1);assert.equal(nav.conversationId,null);
  assert.equal(nav.order('tokens_desc',10).cursor,null);assert.equal(nav.request().contextId,'fixture-context-1');assert.equal(nav.pageSize,10);
  assert.throws(()=>nav.prev(),TypeError);
});
test('acceptance refuses new datasets, revisions and clock drift under a retained frozen context',()=>{
  const nav=new QueryNavigation(query());const first=fixture('overview-complete');nav.accept(first);
  for(const mutate of [data=>data.dataset_id='other',data=>data.range.end_at='2026-10-23T15:00:00Z',data=>data.usage_revision='new',data=>data.pricing_version='new',data=>data.mode='local']){
    const changed=structuredClone(first);mutate(changed);assert.throws(()=>nav.accept(changed),ContractError);
  }
});
test('bundle publishes only after context-matched related widgets and keeps accepted data on mismatch',async()=>{
  const held=pending(),calls=[];
  const client={usage:async(kind,args,signal)=>{calls.push({kind,args,signal});if(kind==='overview')return fixture('overview-complete');if(kind==='facets')return held.promise;return fixture('conversation-page-1');}};
  const session=createQuerySession(client),loading=session.load({request:{query:query()},related:['facets','conversations']});
  await settle();assert.equal(session.accepted,null);assert.equal(calls[1].args.contextId,'fixture-context-1');assert.equal(calls[1].args.query,undefined);
  held.resolve(fixture('facets'));assert.equal((await loading).state,'accepted');assert.equal(session.accepted.related.conversations.summary.conversation_count,2);
  client.usage=async kind=>{const response=fixture(kind==='overview'?'overview-complete':'facets');if(kind==='facets')response.pricing_version='mismatch';return response;};
  await assert.rejects(session.load({request:{query:query()},related:['facets']}),ContractError);
  assert.equal(session.accepted.related.facets.pricing_version,'fixture-prices-1');
  const copy=session.accepted;copy.anchor.summary.tokens.total_tokens='0';assert.equal(session.accepted.anchor.summary.tokens.total_tokens,'2905000');
});
test('equivalent response key order is accepted; explicit context substitution is rejected',async()=>{
  const session=createQuerySession({usage:async kind=>{const result=fixture(kind==='overview'?'overview-complete':'facets');if(kind==='facets')result.range=Object.fromEntries(Object.entries(result.range).reverse());return result;}});
  assert.equal((await session.load({request:{contextId:'fixture-context-1'},selection:query(),related:['facets']})).state,'accepted');
  await assert.rejects(session.load({request:{contextId:'wrong'},selection:query()}),ContractError);
});
test('superseded query success and error cannot publish over a newer selection',async()=>{
  for(const rejectOld of [false,true]){
    const old=pending();let count=0;const signals=[];
    const session=createQuerySession({usage:async(_kind,_args,signal)=>{signals.push(signal);if(++count===1)return old.promise;const result=fixture('overview-zero');result.query_context_id='new';return result;}});
    const previous=session.load({request:{query:query()}});await settle();
    assert.equal((await session.load({request:{query:query()}})).state,'accepted');assert.equal(signals[0].aborted,true);
    if(rejectOld)old.reject(new Error('late failure'));else old.resolve(fixture('overview-complete'));
    assert.equal((await previous).state,'superseded');assert.equal(session.accepted.anchor.query_context_id,'new');
  }
});
test('pending operations capture selection inputs before the caller changes them',async()=>{
  const held=pending(),selection=query(),related=[];
  const session=createQuerySession({usage:async()=>held.promise});
  const loading=session.load({request:{query:selection},selection,related});selection.providers=['claude'];related.push('facets');
  held.resolve(fixture('overview-complete'));assert.equal((await loading).state,'accepted');assert.deepEqual(Object.keys(session.accepted.related),[]);
});
test('revision conflict retries the whole bundle once, without cursor or stale context',async()=>{
  const calls=[];let failures=0;
  const client={usage:async(kind,args)=>{calls.push({kind,args});if(kind==='facets'&&failures++===0)throw conflict();const result=fixture(kind==='overview'?'overview-complete':'facets');if(calls.length>2)result.query_context_id='fresh';return result;}};
  const session=createQuerySession(client);const result=await session.load({request:{contextId:'fixture-context-1',cursor:'old',sort:'tokens_desc',pageSize:10},selection:query(),related:['facets']});
  assert.equal(result.refreshed,true);assert.equal(calls.length,4);assert.equal(calls[2].args.contextId,undefined);assert.equal(calls[2].args.cursor,null);assert.equal(calls[2].args.sort,'tokens_desc');assert.deepEqual(calls[2].args.query,query());
  assert.equal(session.accepted.anchor.query_context_id,'fresh');assert.equal(session.accepted.related.facets.query_context_id,'fresh');
});
test('repeated conflict and ordinary failures stop, retain prior bundle and do not rescan',async()=>{
  let error=null,count=0;const client={usage:async()=>{count++;if(error)throw error;return fixture('overview-complete');}};
  const session=createQuerySession(client);await session.load({request:{query:query()}});
  error=conflict();await assert.rejects(session.load({request:{query:query()}}),ApiError);assert.equal(count,3);assert.notEqual(session.accepted,null);
  for(const failure of [new ApiError(422,'invalid_input'),new ApiError(401,'unauthorized'),new ApiError(429,'cooldown'),new ApiError(409,'configuration_changed')]){
    const before=count;error=failure;await assert.rejects(session.load({request:{query:query()}}),e=>e===failure);assert.equal(count,before+1);
  }
});
test('late related widget after cancellation cannot publish',async()=>{
  const held=pending();const session=createQuerySession({usage:async kind=>kind==='overview'?fixture('overview-complete'):held.promise});
  const loading=session.load({request:{query:query()},related:['facets']});await settle();session.cancel();held.resolve(fixture('facets'));
  assert.equal((await loading).state,'superseded');assert.equal(session.accepted,null);
});
test('wrong applied filters and silent frozen clock advances cannot be accepted',async()=>{
  let mutate=()=>{};
  const session=createQuerySession({usage:async()=>{const data=fixture('overview-complete');mutate(data);return data;}});
  await session.load({request:{query:query()}});
  mutate=data=>data.applied_filters.providers=['claude'];
  await assert.rejects(session.load({request:{query:query()}}),ContractError);
  mutate=data=>data.range.end_at='2026-10-23T15:00:00Z';
  await assert.rejects(session.load({request:{contextId:'fixture-context-1'},selection:query()}),ContractError);
  assert.equal(session.accepted.anchor.range.end_at,'2026-10-23T14:00:00Z');
});
test('fixture transport and navigation complete list → cursor → detail/events → Back',async()=>{
  const calls=[];
  const client=createV1Client({expectedMode:'demo',fetchImpl:async(path)=>{
    calls.push(new URL(path,'http://fixture.invalid'));
    const url=calls.at(-1);let name;
    if(url.pathname==='/api/v1/usage/conversations')name=url.searchParams.has('cursor')?'conversation-page-2':'conversation-page-1';
    else if(url.pathname.endsWith('/events'))name='events';else if(url.pathname.startsWith('/api/v1/conversations/'))name='detail';else name='facets';
    return new Response(JSON.stringify(fixture(name)),{headers:{'content-type':'application/json'}});
  }});
  const nav=new QueryNavigation(query()),session=createQuerySession(client);
  const first=await session.load({kind:'conversations',request:nav.request(),selection:nav.query,related:['facets']});nav.accept(first.bundle.anchor);
  assert.equal(first.bundle.anchor.summary.tokens.total_tokens,'2905000');
  const second=await session.load({kind:'conversations',request:nav.next(first.bundle.anchor.page.next_cursor),selection:nav.query});nav.accept(second.bundle.anchor);
  const parentId=nav.contextId,returnCursor=nav.cursor;
  const detail=await client.usage('detail',nav.detail('fixture-conversation-codex',437));
  assert.equal(detail.summary,undefined);assert.equal(detail.conversation.summary.tokens.total_tokens,'2840000');assert.equal(detail.lifetime.first_activity_at,'2026-09-01T12:00:00Z');
  const events=await client.usage('events',{contextId:parentId,conversationId:'fixture-conversation-codex'});assert.equal(events.items[0].reasoning_tokens,'1260000');
  const back=nav.back();const restored=await session.load({kind:'conversations',request:back.request,selection:nav.query});
  assert.equal(restored.bundle.anchor.summary.tokens.total_tokens,'2905000');assert.equal(back.scrollY,437);assert.equal(nav.cursor,returnCursor);
  assert.equal(calls[2].searchParams.has('period'),false);assert.equal(calls.at(-1).searchParams.get('cursor'),returnCursor);
  assert.ok(calls.every(url=>url.pathname.startsWith('/api/v1/')));
});
test('job observer stops at terminal states and returns pending after its bounded attempts',async()=>{
  for(const terminal of ['succeeded','failed','superseded']){
    const updates=[],waits=[];let count=0;
    const observer=createJobObserver({job:async()=>fixture('job-'+(++count===1?'running':terminal))},{wait:async ms=>waits.push(ms)});
    assert.equal((await observer.watch('fixture-job',{onUpdate:response=>updates.push(response.job.state)})).state,terminal);
    assert.deepEqual(updates,['running',terminal]);assert.deepEqual(waits,[1000]);
  }
  let count=0;const observer=createJobObserver({job:async()=>{count++;return fixture('job-queued');}},{wait:async()=>{}});
  assert.equal((await observer.watch('fixture-job',{maxAttempts:2})).state,'pending');assert.equal(count,2);
  await assert.rejects(observer.watch('fixture-job',{maxAttempts:100}),TypeError);
});
test('superseded job responses cannot update callbacks; mismatched job identities fail',async()=>{
  const old=pending(),updates=[];let count=0;
  const observer=createJobObserver({job:async()=>++count===1?old.promise:fixture('job-succeeded')},{wait:async()=>{}});
  const previous=observer.watch('fixture-job',{onUpdate:response=>updates.push('old-'+response.job.state)});await settle();
  assert.equal((await observer.watch('fixture-job',{onUpdate:response=>updates.push(response.job.state)})).state,'succeeded');old.resolve(fixture('job-running'));
  assert.equal((await previous).state,'superseded');assert.deepEqual(updates,['succeeded']);
  const mismatch=createJobObserver({job:async()=>fixture('job-running')});await assert.rejects(mismatch.watch('other-id'),ContractError);
});
test('stopping an observer from its callback causes no further request or wait',async()=>{
  let count=0,waits=0;const observer=createJobObserver({job:async()=>{count++;return fixture('job-running');}},{wait:async()=>{waits++;}});
  assert.equal((await observer.watch('fixture-job',{onUpdate:()=>observer.stop()})).state,'superseded');assert.equal(count,1);assert.equal(waits,0);
});
