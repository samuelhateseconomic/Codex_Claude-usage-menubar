import test from 'node:test';
import assert from 'node:assert/strict';
import {dashboard,fixture,settle} from './dashboard-harness.mjs';

test('failed filter restores the published query and Retry requests the failed selection',async()=>{
  const app=await dashboard();
  app.fail();
  await app.click('provider',{value:'claude'});
  assert.equal(new URLSearchParams(app.location.hash.slice(1)).get('provider'),null);
  assert.match(app.html,/previous query result/i);
  assert.match(app.html,/data-action="retry"/);
  assert.match(app.html,/18\.420/);
  await app.click('retry');
  assert.equal(new URLSearchParams(app.requestLog.at(-1).path.split('?')[1]).get('provider'),'claude');
  assert.equal(new URLSearchParams(app.location.hash.slice(1)).get('provider'),'claude');
  assert.doesNotMatch(app.html,/previous query result/i);
});

test('initial query failure has a focused read-only Retry and never fabricates zero',async()=>{
  const app=await dashboard({initialStatus:503,initialPayload:{error:'scan_unavailable'}});
  assert.match(app.html,/Usage is unavailable/);
  assert.equal(app.nodes.get('#connection').textContent,'Snapshot unavailable');
  assert.equal(app.nodes.get('#scope').textContent,'No snapshot loaded');
  assert.doesNotMatch(app.html,/18\.420|0 conversations/);
  await app.click('retry');
  assert.equal(app.requests,2);
  assert.ok(app.requestLog.every(r=>r.path.startsWith('/api/preview/query?')&&!r.options.method));
  assert.equal(app.document.activeElement?.id,'content');
  assert.equal(app.nodes.get('#content').attributes['aria-busy'],'false');
});

test('pending queries hide previous interactive rows; late results cannot publish or steal focus',async()=>{
  const app=await dashboard();
  const finish=app.defer();
  const old=app.click('provider',{value:'claude'});
  await settle();
  assert.match(app.html,/Reading matching usage/);
  assert.doesNotMatch(app.html,/<table|18\.420/);
  assert.equal(app.nodes.get('#content').attributes['aria-busy'],'true');
  const latest=fixture();latest.summary.value.amount_usd='7.001';
  app.respond(latest);
  await app.click('provider',{value:'codex'});
  const focusCount=app.focusLog.length;
  finish();await old;
  assert.match(app.html,/7\.001/);
  assert.equal(app.focusLog.length,focusCount);
  assert.equal(app.nodes.get('#content').attributes['aria-busy'],'false');
});

test('obsolete errors never replace a newer successful query',async()=>{
  const app=await dashboard(),finish=app.defer();
  const old=app.click('provider',{value:'claude'});
  await app.click('provider',{value:'codex'});
  finish({error:'old failure'},503);await old;
  assert.doesNotMatch(app.html,/previous query result|Usage is unavailable/);
  assert.equal(new URLSearchParams(app.location.hash.slice(1)).get('provider'),'codex');
});

test('revision refresh is bounded, preserves filters and retains the last published result on failure',async()=>{
  const app=await dashboard();
  app.respond({error:'revision_conflict'},409);
  app.respond({error:'revision_conflict'},409);
  // A third conflict retry is forbidden. The sentinel makes the old recursive code terminate.
  app.respond({error:'stop unbounded retry'},503);
  await app.click('provider',{value:'claude'});
  assert.equal(app.requests,3);
  const first=new URLSearchParams(app.requestLog[1].path.split('?')[1]);
  const second=new URLSearchParams(app.requestLog[2].path.split('?')[1]);
  assert.equal(first.get('revision'),'revision-1');
  assert.equal(second.get('revision'),null);
  assert.equal(second.get('provider'),'claude');
  assert.match(app.html,/18\.420/);
  assert.match(app.html,/previous query result/i);
});

test('a recovered revision publishes its new ID and the requested filters',async()=>{
  const app=await dashboard();
  app.respond({error:'revision_conflict'},409);
  const next=fixture();next.usage_revision='revision-2';app.respond(next);
  await app.click('provider',{value:'claude'});
  await app.click('page',{value:'2'});
  const query=new URLSearchParams(app.requestLog.at(-1).path.split('?')[1]);
  assert.equal(query.get('revision'),'revision-2');
  assert.equal(query.get('provider'),'claude');
});

test('query completion leaves focus inside an open modal',async()=>{
  const app=await dashboard(),finish=app.defer();
  const pending=app.click('provider',{value:'claude'});
  app.nodes.get('#shortcuts').open=true;
  app.nodes.get('#shortcuts').focus();
  finish();await pending;
  assert.equal(app.document.activeElement.id,'shortcuts');
});

test('successful rescan followed by a failed query does not announce a refreshed view',async()=>{
  const app=await dashboard();
  app.respond({state:'complete'});app.fail();
  await app.click('refresh');
  assert.match(app.html,/previous query result/i);
  assert.match(app.html,/18\.420/);
  assert.doesNotMatch(app.nodes.get('#notification').textContent,/snapshot refreshed/);
});

test('a superseded search shortcut cannot steal focus from newer navigation',async()=>{
  const app=await dashboard(),finish=app.defer();
  const search=app.click('search');
  await app.click('provider',{value:'claude'});
  const count=app.focusLog.length;
  finish();await search;
  assert.equal(app.focusLog.length,count);
  assert.equal(app.document.activeElement.id,'content');
});

test('repeated refresh actions share one pending rescan',async()=>{
  const app=await dashboard(),finish=app.defer();
  const refresh=app.click('refresh');
  await app.click('refresh');
  assert.equal(app.requestLog.filter(r=>r.path==='/api/preview/rescan').length,1);
  finish({state:'complete'});await refresh;
});

test('rendered summaries and signed fees consume exact strings at large magnitudes',async()=>{
  const value=fixture();
  value.summary.value.amount_usd='999999999999999999999999.999999999999';
  value.comparisons=[{provider:'Codex',fee_usd:'999999999.125',difference_usd:'-9007199254740993.123',state:'complete'}];
  const app=await dashboard({initialPayload:value});
  assert.match(app.html,/1,000,000,000,000,000,000,000,000\.000/);
  app.respond(value);await app.navigate('overview');
  assert.match(app.html,/999,999,999\.12 monthly fee/);
  assert.match(app.html,/−\$9,007,199,254,740,993\.123 vs fee/);
  assert.equal(value.summary.value.amount_usd,'999999999999999999999999.999999999999');
});
