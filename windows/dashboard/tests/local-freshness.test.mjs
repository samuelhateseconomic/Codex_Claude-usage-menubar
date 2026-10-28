import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {watchLocalPublication} from '../local-freshness.js';
import {renderPublicationStatus,renderScanStatus,renderLocal} from '../local-view.js';
import {localDashboard} from './local-dom-harness.mjs';
const fixtures=JSON.parse(readFileSync(new URL('../../../docs/api/usage-hub-v1.fixtures.json',import.meta.url)));
const copy=structuredClone;

function clock(){
  let serial=0;const timers=new Map(),handlers={};
  const document={visibilityState:'visible',addEventListener:(k,f)=>{handlers[k]=f;},removeEventListener:k=>{delete handlers[k];}};
  const window={setTimeout:(fn,ms)=>{timers.set(++serial,{fn,ms});return serial;},clearTimeout:id=>timers.delete(id)};
  return {document,window,timers,handlers,async tick(){const [id,t]=timers.entries().next().value;timers.delete(id);await t.fn();}};
}

test('freshness observes status only, pauses hidden tabs and checks on return',async()=>{
  const c=clock(),received=[];let reads=0;
  const watch=watchLocalPublication({...c,client:{read:async kind=>{assert.equal(kind,'status');reads++;return fixtures.status;}},onStatus:s=>received.push(s),onFailure:()=>assert.fail('Unexpected error')});
  watch.restart();assert.equal(c.timers.size,1);assert.equal([...c.timers.values()][0].ms,30000);
  await c.tick();assert.equal(reads,1);assert.equal(received.length,1);assert.equal(c.timers.size,1);
  c.document.visibilityState='hidden';c.handlers.visibilitychange();assert.equal(c.timers.size,0);
  c.document.visibilityState='visible';c.handlers.visibilitychange();await Promise.resolve();await Promise.resolve();assert.equal(reads,2);
  watch.dispose();assert.equal(c.timers.size,0);assert.equal(c.handlers.visibilitychange,undefined);
});

test('slow/error status checks never overlap and obsolete or disposed replies cannot publish',async()=>{
  const c=clock();let resolve,reject,calls=0,updates=0,failures=0;
  const watch=watchLocalPublication({...c,client:{read:()=>{calls++;return new Promise((r,j)=>{resolve=r;reject=j;});}},onStatus:()=>updates++,onFailure:()=>failures++});
  watch.restart();const pending=c.tick();assert.equal(c.timers.size,0);assert.equal(calls,1);
  watch.restart();resolve(fixtures.status);await pending;assert.equal(updates,0);assert.equal(c.timers.size,1);
  const failed=c.tick();reject(new Error('PRIVATE_ERROR_SENTINEL'));await failed;assert.equal(failures,1);assert.equal(c.timers.size,1);
  const disposed=c.tick();watch.dispose();resolve(fixtures.status);await disposed;assert.equal(updates,0);assert.equal(c.timers.size,0);
});

test('freshness distinguishes scan time, captured view, newer publication and failed check',()=>{
  const view=copy(fixtures.overview),status=copy(fixtures.status);
  for(const k of ['usage_revision','pricing_version','configuration_version'])status.data[k]=view[k];
  status.data.last_import_completed_at='2026-10-24T12:00:00.000000Z';status.data.indexing=false;
  const bundle={overview:view,status},same=renderPublicationStatus(bundle,status);
  assert.match(renderScanStatus(bundle,status),/Last successful local scan:/);assert.match(renderScanStatus(bundle,status),/View captured through:/);assert.doesNotMatch(same,/Last successful local scan:/);assert.doesNotMatch(same,/New usage or settings available/);
  status.data.usage_revision=String(BigInt(view.usage_revision)+1n);
  const newer=renderPublicationStatus(bundle,status);assert.match(newer,/New usage or settings available/);assert.match(newer,/data-action="refresh-query"/);
  assert.match(renderPublicationStatus(bundle,status,true),/Could not check for newer usage/);
  // Overview retains exclusion warnings inside the collapsed Report Log.
  view.data.coverage[0].accounting_issues={counter_reset:1};
  const html=renderLocal({overview:view,status},{view:'overview',provider:'both',period:'month',metric:'value'});
  assert.ok(html.indexOf('some usage intervals could not be counted reliably')>html.indexOf('<summary>Report Log</summary>'));
});

function api(){
  let serial=0,revision=fixtures.overview.usage_revision;const contexts=new Map();
  return {publish(){revision=String(BigInt(revision)+1n);},authenticate:async()=>{},read:async kind=>{
    const wire=copy(fixtures[kind]);if(kind==='status')wire.data.usage_revision=revision;return wire;
  },usage:async(kind,args)=>{
    let context=contexts.get(args.contextId);
    if(!context){context=copy(fixtures.overview);context.query_context_id='new-context-'+(++serial);context.usage_revision=revision;
      const q=args.query??{};if(args.baseContextId)context.range=copy(contexts.get(args.baseContextId).range);
      context.applied_filters={provider:q.provider??['claude','codex'],project_id:q.project_id??[],model:q.model??[],effort:q.effort??[],q:q.q??'',selected_day:q.selected_day??null};contexts.set(context.query_context_id,copy(context));}
    const wire=copy(fixtures[kind]);for(const key of ['dataset_id','mode','query_context_id','usage_revision','pricing_version','configuration_version','range','applied_filters'])wire[key]=copy(context[key]);return wire;
  }};
}

test('production freshness does not replace results or drafts; Update view preserves filters and captures a coherent publication',async()=>{
  const client=api(),app=await localDashboard(client,{hash:'#view=explore&provider=codex&q=portfolio'});
  const before=app.app.accepted;client.publish();
  // Visibility return runs the same status-only check as the timer.
  await app.handlers.visibilitychange();await Promise.resolve();await Promise.resolve();
  assert.match(app.nodes.get('#publication-status').innerHTML,/New usage or settings available/);
  assert.equal(app.app.accepted.overview.query_context_id,before.overview.query_context_id);
  await app.click('refresh-query');
  const after=app.app.accepted;assert.notEqual(after.overview.query_context_id,before.overview.query_context_id);
  assert.equal(after.overview.usage_revision,after.list.usage_revision);assert.equal(after.overview.usage_revision,after.facets.usage_revision);
  assert.equal(app.app.snapshot.state.provider,'codex');assert.equal(app.app.snapshot.state.q,'portfolio');
  assert.doesNotMatch(app.nodes.get('#publication-status').innerHTML,/New usage or settings available/);
  await app.nav('settings');await app.setting('Claude','100');
  const html=app.html;client.publish();await app.handlers.visibilitychange();await Promise.resolve();await Promise.resolve();
  assert.equal(app.html,html);assert.equal(app.nodes.get('#settings-result').textContent,'Unsaved changes. Choose Save settings to apply them to comparisons.');
  app.app.dispose();
});

// The settings DTO nests resolved timezone under settings, unlike limits.
test('scan footer uses each page resolved timezone, including Settings and DST',()=>{
  const status=copy(fixtures.status);status.data.last_import_completed_at='2026-10-24T12:00:00.000000Z';
  const info={name:'America/Los_Angeles'};
  const overview=copy(fixtures.overview);overview.range.timezone=info.name;
  for(const b of [{status,overview},{status,wire:{data:{timezone_info:info}}},{status,wire:{data:{settings:{timezone_info:info}}}}]){
    const html=renderScanStatus(b);assert.match(html,/5:00 AM PDT/);assert.doesNotMatch(html,/UTC/);
  }
  const settings={status,wire:{data:{settings:{timezone_info:info}}}};
  status.data.last_import_completed_at='2026-12-24T12:00:00.000000Z';assert.match(renderScanStatus(settings),/4:00 AM PST/);
  settings.wire.data.settings.timezone_info.name='UTC';assert.match(renderScanStatus(settings),/12:00 PM UTC/);
  status.data.last_import_completed_at=null;assert.match(renderScanStatus(settings),/Not recorded/);
});
