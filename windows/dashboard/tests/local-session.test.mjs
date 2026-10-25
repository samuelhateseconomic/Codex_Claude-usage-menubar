import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createLocalSession,defaultSelection,observeLocalJob} from '../local-session.js';
import {LocalApiError} from '../v1-client.js';
import {localDashboard} from './local-dom-harness.mjs';
const fixtures=JSON.parse(readFileSync(new URL('../../../docs/api/usage-hub-v1.fixtures.json',import.meta.url)));
const copy=structuredClone;
const selection=extra=>({...defaultSelection(),view:'explore',metric:'value',table:'conversations',sort:'value_desc',pageSize:50,conversation:'',...extra});
function fakeApi(){
  let serial=0;const contexts=new Map(),calls=[];
  const api={calls,hook:null,authenticate:async()=>{},read:async kind=>copy(fixtures[kind]),usage:async(kind,args)=>{
    calls.push({kind,args:copy(args)});if(api.hook){const result=await api.hook(kind,args);if(result)return result;}
    let context=args.contextId?contexts.get(args.contextId):null;
    if(!context){
      context=copy(fixtures.overview);context.query_context_id='context-'+(++serial);
      if(args.baseContextId){const root=contexts.get(args.baseContextId);context.range=copy(root.range);}
      const q=args.query??{};context.applied_filters={provider:q.provider??['claude','codex'],project_id:q.project_id??[],model:q.model??[],effort:q.effort??[],q:q.q??'',selected_day:q.selected_day??null};
      if(q.period)context.range.preset=q.period;contexts.set(context.query_context_id,copy(context));
    }
    const wire=copy(fixtures[({detail:'conversation',projects:'projects'})[kind]??kind]);
    for(const key of ['dataset_id','mode','query_context_id','usage_revision','pricing_version','configuration_version','range','applied_filters'])wire[key]=copy(context[key]);
    return wire;
  }};return api;
}
test('production bundles reject related revision drift and retain the last complete query',async()=>{
  const api=fakeApi(),session=createLocalSession(api),accepted=await session.load(selection());
  api.hook=kind=>{if(kind==='facets'){const wire=copy(fixtures.facets);wire.usage_revision='999';return wire;}};
  await assert.rejects(session.load(selection({provider:'claude'}),{navigation:accepted.bundle.navigation}));
  assert.equal(session.accepted.overview.query_context_id,accepted.bundle.overview.query_context_id);
});
test('production requests capture inputs and discard obsolete success and error',async()=>{
  const api=fakeApi(),session=createLocalSession(api);let release;
  api.hook=()=>new Promise(resolve=>{release=resolve;});
  const s=selection(),old=session.load(s);s.provider='claude';api.hook=null;
  const newer=await session.load(selection({provider:'codex'}));release(copy(fixtures.overview));
  assert.equal((await old).state,'superseded');assert.deepEqual(session.accepted.overview.applied_filters.provider,['codex']);assert.equal(newer.state,'accepted');
  let reject;api.hook=()=>new Promise((_r,j)=>{reject=j;});const failed=session.load(selection());api.hook=null;await session.load(selection({provider:'claude'}));reject(new Error('late failure'));
  assert.equal((await failed).state,'superseded');assert.deepEqual(session.accepted.overview.applied_filters.provider,['claude']);
});
test('repeated production context conflicts stop after one whole-query retry',async()=>{
  const api=fakeApi(),session=createLocalSession(api),accepted=await session.load(selection());let conflicts=0;
  api.hook=()=>{conflicts++;throw new LocalApiError('revision_changed',409);};
  await assert.rejects(session.load(selection(),{navigation:accepted.bundle.navigation}),e=>e.code==='revision_changed');
  assert.equal(conflicts,2);assert.deepEqual(session.accepted,accepted.bundle);
});
test('failed production filter restores published controls and Retry keeps the requested selection',async()=>{
  const api=fakeApi(),app=await localDashboard(api);api.hook=()=>{throw new LocalApiError('index_unavailable',503);};
  await app.click('provider',{value:'claude'});assert.equal(app.app.snapshot.state.provider,'both');assert.match(app.html,/previous accepted result/);
  api.hook=null;await app.click('retry');assert.equal(app.app.snapshot.state.provider,'claude');assert.deepEqual(app.app.accepted.overview.applied_filters.provider,['claude']);app.app.dispose();
});
test('initial production failure has no invented summary and provides local status recovery',async()=>{
  const api=fakeApi();api.hook=()=>{throw new LocalApiError('index_unavailable',503);};
  const app=await localDashboard(api);assert.match(app.html,/Local usage unavailable/);assert.doesNotMatch(app.html,/ESTIMATED API VALUE|RECORDED TOKENS/);
  await app.click('status');assert.match(app.nodes.get('#notification').textContent,/Committed index/);app.app.dispose();
});
test('obsolete production DOM response cannot replace newer navigation or steal focus from a modal',async()=>{
  const api=fakeApi(),app=await localDashboard(api);let release;
  api.hook=()=>new Promise(resolve=>{release=resolve;});const old=app.click('provider',{value:'claude'});api.hook=null;
  app.nodes.get('#shortcuts').open=true;const before=app.focusLog.length;await app.nav('settings');release(copy(fixtures.overview));await old;
  assert.equal(app.app.snapshot.state.view,'settings');assert.match(app.html,/Draft changes publish/);assert.equal(app.focusLog.length,before);app.app.dispose();
});
test('settings and limits remain readable without a usage publication or implicit polling',async()=>{
  const api=fakeApi();api.hook=()=>{throw new Error('Usage route must not be called');};
  const session=createLocalSession(api);
  for(const view of ['settings','limits'])assert.equal((await session.load(selection({view}))).state,'accepted');
  assert.equal(api.calls.length,0);
});
test('job observation is bounded, terminal and obsolete-safe',async()=>{
  let calls=0;const api={job:async()=>{calls++;return copy(fixtures.job_queued);}};const id=fixtures.job_queued.data.id;
  assert.equal((await observeLocalJob(api,id,{signal:new AbortController().signal,attempts:2,wait:async()=>{}})).state,'pending');assert.equal(calls,2);
  const abort=new AbortController();calls=0;
  assert.equal((await observeLocalJob(api,id,{signal:abort.signal,onUpdate:()=>abort.abort(),wait:()=>{throw new Error('No wait after cancel');}})).state,'superseded');assert.equal(calls,1);
  const done=copy(fixtures.job_succeeded);done.data.id=id;assert.equal((await observeLocalJob({job:async()=>done},id,{signal:new AbortController().signal})).state,'succeeded');
});
test('completed production rescan with a failed follow-up does not claim a refreshed view',async()=>{
  const api=fakeApi();api.mutate=async()=>copy(fixtures.job_queued);const id=fixtures.job_queued.data.id;
  api.job=async()=>{const done=copy(fixtures.job_succeeded);done.data.id=id;api.hook=()=>{throw new LocalApiError('index_unavailable',503);};return done;};
  const app=await localDashboard(api);await app.click('refresh');
  assert.match(app.nodes.get('#notification').textContent,/could not refresh/);assert.doesNotMatch(app.nodes.get('#notification').textContent,/has been refreshed/);assert.match(app.html,/previous accepted result/);app.app.dispose();
});
test('preset changes clear the selected day and production toolbar coalesces pending rescans',async()=>{
  const api=fakeApi(),app=await localDashboard(api);await app.click('day',{value:'2026-10-23'});await app.change('period','today');assert.equal(app.app.snapshot.state.day,'');
  let release,calls=0;api.mutate=()=>{calls++;return new Promise(resolve=>{release=resolve;});};
  api.job=async()=>{const done=copy(fixtures.job_succeeded);done.data.id=fixtures.job_queued.data.id;return done;};
  const pending=app.click('refresh');await app.click('refresh');assert.equal(calls,1);release(copy(fixtures.job_queued));await pending;app.app.dispose();
});

test('settings rejection stays visible after the notification expires and retains the draft',async()=>{
  const api=fakeApi();api.mutate=async()=>{throw new LocalApiError('session_required',403);};
  const app=await localDashboard(api,{hash:'#view=settings'});
  await app.setting('Claude','100');await app.click('save-settings');
  await app.expireNotifications();
  assert.equal(app.nodes.get('#notification').textContent,'');
  assert.match(app.nodes.get('#operation-status')?.innerHTML??'',/not confirmed/);
  assert.match(app.nodes.get('#operation-status')?.innerHTML??'',/Open the dashboard again through Usage Tray/);
  await app.nav('overview');await app.nav('settings');
  assert.match(app.html,/value="100"/);assert.match(app.html,/not confirmed/);app.app.dispose();
});

test('reopened settings exposes the pending job and a user can recheck publication',async()=>{
  const api=fakeApi(),queued=copy(fixtures.job_queued.data);
  queued.kind='reprice';queued.requested_configuration_version=fixtures.settings.data.configuration_version;
  const pending=copy(fixtures.status);
  Object.assign(pending.data,{configuration_pending:true,configuration_state:'pending',requested_configuration_version:queued.requested_configuration_version,last_job:queued});
  let applied=false,calls=0;
  api.read=async kind=>copy(kind==='status'&&!applied?pending:fixtures[kind]);
  api.job=async()=>{calls++;applied=true;const done=copy(fixtures.job_succeeded);done.data.id=queued.id;return done;};
  const app=await localDashboard(api,{hash:'#view=settings'});
  assert.match(app.html,/Check progress/);
  await app.click('check-job');assert.equal(calls,1);
  assert.match(app.html,/Settings applied/);assert.equal(app.app.accepted.status.data.configuration_pending,false);app.app.dispose();
});

test('a settings job beyond the observation bound remains recheckable after navigation',async t=>{
  t.mock.timers.enable({apis:['setTimeout']});
  const api=fakeApi(),queued=copy(fixtures.job_queued);queued.data.kind='reprice';
  const saved=copy(fixtures.settings_saved);saved.data.jobs=[queued.data];saved.data.pending=true;
  api.mutate=async()=>saved;let done=false,calls=0;
  api.job=async()=>{calls++;if(!done)return copy(queued);const completed=copy(fixtures.job_succeeded);completed.data.id=queued.data.id;return completed;};
  const app=await localDashboard(api,{hash:'#view=settings'});t.after(()=>app.app.dispose());
  await app.setting('Claude','100');const saving=app.click('save-settings');
  for(let i=0;i<31;i++){await new Promise(setImmediate);t.mock.timers.tick(1000);}
  await saving;assert.equal(calls,30);
  assert.match(app.nodes.get('#operation-status').innerHTML,/still running/);
  await app.nav('overview');assert.match(app.html,/Check progress/);
  done=true;await app.click('check-job');assert.equal(calls,31);
  assert.match(app.nodes.get('#operation-status').innerHTML,/Settings applied/);
  assert.equal(app.app.snapshot.state.view,'overview');
});

test('a fee save can finish after navigating away without restoring an obsolete Settings page',async()=>{
  const api=fakeApi(),saved=copy(fixtures.settings_saved);let release;
  api.mutate=()=>new Promise(resolve=>{release=resolve;});
  api.job=async()=>{const done=copy(fixtures.job_succeeded);done.data.id=saved.data.jobs[0].id;return done;};
  const app=await localDashboard(api,{hash:'#view=settings'});
  await app.setting('Claude','100');const saving=app.click('save-settings');
  await app.nav('overview');release(saved);await saving;
  assert.equal(app.app.snapshot.state.view,'overview');
  assert.match(app.nodes.get('#operation-status').innerHTML,/Settings applied/);app.app.dispose();
});

test('a failed settings publication remains explicit after notification expiry and navigation',async()=>{
  const api=fakeApi(),saved=copy(fixtures.settings_saved);
  api.mutate=async()=>saved;
  api.job=async()=>{const failed=copy(fixtures.job_queued);failed.data.id=saved.data.jobs[0].id;failed.data.status='failed';return failed;};
  const app=await localDashboard(api,{hash:'#view=settings'});
  await app.setting('Claude','100');await app.click('save-settings');await app.expireNotifications();
  assert.match(app.nodes.get('#operation-status').innerHTML,/could not be applied \(failed\)/);
  await app.nav('overview');assert.match(app.html,/Previous committed usage is retained/);
  assert.doesNotMatch(app.html,/Settings applied/);app.app.dispose();
});

test('a retained draft keeps its original expected version across navigation after an external edit',async()=>{
  const api=fakeApi(),settings=copy(fixtures.settings),original=settings.data.configuration_version,calls=[];
  api.read=async kind=>copy(kind==='settings'?settings:fixtures[kind]);
  api.mutate=async(kind,body)=>{calls.push(body);throw new LocalApiError('configuration_changed',409);};
  const app=await localDashboard(api,{hash:'#view=settings'});
  await app.setting('Claude','100');settings.data.configuration_version='new-external-version';
  await app.nav('overview');await app.nav('settings');await app.click('save-settings');
  assert.equal(calls[0].expected_configuration_version,original);
  assert.equal(calls[0].changes.plan_fees_usd.Claude,'100');
  await app.click('reload-settings');await app.setting('Claude','100');await app.click('save-settings');
  assert.equal(calls[1].expected_configuration_version,'new-external-version');app.app.dispose();
});
