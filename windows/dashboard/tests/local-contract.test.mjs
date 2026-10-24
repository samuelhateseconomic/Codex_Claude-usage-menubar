import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {v1Schema} from '../v1-schema.js';
import {validateV1,createLocalClient,usagePath} from '../v1-client.js';
import {renderLocal} from '../local-view.js';
export const fixtures=JSON.parse(readFileSync(new URL('../../../docs/api/usage-hub-v1.fixtures.json',import.meta.url)));

test('production validator uses the published S12 schema and all actual backend examples',()=>{
  assert.deepEqual(v1Schema,JSON.parse(readFileSync(new URL('../../../docs/api/usage-hub-v1.schema.json',import.meta.url))));
  for(const wire of Object.values(fixtures))assert.deepEqual(validateV1(wire.kind??'error',wire),wire);
});
test('production validation refuses candidate/demo, numeric money, overflow and malformed issue counts',()=>{
  for(const mutate of [w=>w.mode='demo',w=>w.data.summary.value.amount_usd=18.891,w=>w.data.summary.tokens.total_tokens='9223372036854775808',w=>w.data.coverage[0].ingestion_issues.bad='not a count']){
    const wire=structuredClone(fixtures.overview);mutate(wire);assert.throws(()=>validateV1('overview',wire));
  }
});
test('published request encoding uses events sort and exact opaque project/conversation IDs',()=>{
  const path=usagePath('events',{contextId:'frozen+context',conversationId:'opaque/id+',cursor:'opaque+cursor',pageSize:1});
  assert.match(path,/conversations\/opaque%2Fid%2B\/events/);
  const p=new URL('http://localhost'+path).searchParams;
  assert.equal(p.get('sort'),'events');assert.equal(p.get('query_context_id'),'frozen+context');assert.equal(p.get('cursor'),'opaque+cursor');
});
test('production authentication strips only the launch fragment before exchanging it and keeps CSRF in memory',async()=>{
  const calls=[],history={replaceState(...args){calls.push(['history',args[2]]);}};
  const session={...fixtures.status,kind:'session',data:{csrf_token:'synthetic-csrf',expires_in_seconds:3600}};
  const client=createLocalClient({fetchImpl:async(path,options)=>{calls.push([path,options]);return Response.json(path.endsWith('refresh')?fixtures.job_queued:session);}});
  await client.authenticate({location:{pathname:'/',hash:'#launch=synthetic&view=explore'},history});
  assert.deepEqual(calls[0],['history','/#view=explore']);
  assert.equal(calls[1][0],'/api/v1/session/bootstrap');
  assert.deepEqual(JSON.parse(calls[1][1].body),{launch_token:'synthetic'});
  await client.mutate('refresh',{});
  assert.equal(calls[2][1].headers['X-Usage-CSRF'],'synthetic-csrf');assert.equal(calls[2][1].credentials,'same-origin');
});
test('production reads validate data and fail safely without a preview request',async()=>{
  const calls=[],client=createLocalClient({fetchImpl:async path=>{calls.push(path);return Response.json({...fixtures.invalid_input,error:{...fixtures.invalid_input.error,message:'PRIVATE_ERROR'}},{status:422});}});
  await assert.rejects(client.usage('overview',{query:{period:'month'}}),e=>e.code==='invalid_input'&&!e.message.includes('PRIVATE_ERROR'));
  assert.equal(calls.length,1);assert.match(calls[0],/^\/api\/v1\/overview/);
});
test('production rendering distinguishes empty, partial, unpriced, zero, stale and failed operations',()=>{
  const state={view:'overview',period:'month',provider:'both',metric:'tokens'};
  const render=wire=>renderLocal({overview:wire,status:fixtures.status},state);
  assert.match(render(fixtures.empty),/No recorded activity matches/);
  assert.match(render(fixtures.partial),/Priced subtotal/);
  assert.match(render(fixtures.unpriced),/API value is unavailable/);
  assert.match(render(fixtures.priced_zero),/0\.000/);
  const stale=structuredClone(fixtures.overview);stale.data.freshness='stale';assert.match(render(stale),/Retained local usage is stale/);
  const status=structuredClone(fixtures.status);status.data.configuration_pending=true;status.data.last_job={status:'failed'};
  assert.match(renderLocal({overview:fixtures.overview,status},state),/last local operation failed/);
});
test('production source labels are inert and complete project identities remain attributes',()=>{
  const overview=structuredClone(fixtures.overview);overview.data.top_projects[0].label='<img src=x onerror=alert(1)>\u001b';
  const html=renderLocal({overview,status:fixtures.status},{view:'overview',provider:'both',period:'month',metric:'value'});
  assert.match(html,/&lt;img/);assert.match(html,/\\u001b/);assert.doesNotMatch(html,/<img src=x/);assert.ok(html.includes(overview.data.top_projects[0].id));
});
