import {before,after,test} from 'node:test';
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {createInterface} from 'node:readline';
import {fileURLToPath} from 'node:url';
import {createLocalClient,LocalApiError} from '../v1-client.js';
import {createLocalSession,defaultSelection,observeLocalJob} from '../local-session.js';
import {localDashboard} from './local-dom-harness.mjs';

let child,client,origin,cookie='',csrf,lines,iterator,requestLog=[],errors='';
before(async()=>{
  child=spawn(fileURLToPath(new URL('../../.venv/Scripts/python.exe',import.meta.url)),['-u',fileURLToPath(new URL('./local-fixture-server.py',import.meta.url))],{stdio:['pipe','pipe','pipe'],windowsHide:true});
  child.stderr.on('data',b=>{errors+=b;});
  lines=createInterface({input:child.stdout});iterator=lines[Symbol.asyncIterator]();
  const line=await Promise.race([iterator.next(),new Promise((_,reject)=>{const t=setTimeout(()=>reject(new Error('Synthetic API startup timed out: '+errors)),20000);t.unref();})]);
  assert.equal(line.done,false,errors);const ready=JSON.parse(line.value);origin=ready.origin;
  client=createLocalClient({fetchImpl:async(path,options)=>{
    requestLog.push({path,options});const headers={...options.headers};if(cookie)headers.Cookie=cookie;if(options.method!=='GET')headers.Origin=origin;
    const response=await fetch(origin+path,{...options,headers});const set=response.headers.get('set-cookie');if(set)cookie=set.split(';')[0];return response;
  }});
  const session=await client.authenticate({location:{pathname:'/',hash:'#launch='+ready.launch},history:{replaceState(){}}});csrf=session.data.csrf_token;
});
after(async()=>{
  if(!child)return;
  child.stdin.end('quit\n');await Promise.race([new Promise(resolve=>child.once('exit',resolve)),new Promise(resolve=>{const t=setTimeout(()=>{child.kill();resolve();},10000);t.unref();})]);lines?.close();
});
const selection=(extra={})=>({...defaultSelection(),view:'explore',metric:'value',table:'conversations',sort:'value_desc',pageSize:1,conversation:'',...extra});
test('real local API client and loader reconcile provider → summary → cursor → conversation → retained parent',async()=>{
  const session=createLocalSession(client),s=selection();
  let {bundle}=await session.load(s);assert.equal(bundle.overview.data.summary.tokens.total_tokens,'2905000');assert.equal(bundle.overview.data.summary.value.amount_usd,'18.891000000000');
  const end=bundle.overview.range.end_at,context=bundle.overview.query_context_id;
  assert.equal(bundle.list.data.items.length,1);assert.ok(bundle.list.data.pagination.next_cursor);
  const parent=structuredClone(bundle.navigation);parent.previous.push(parent.cursor);parent.cursor=bundle.list.data.pagination.next_cursor;
  ({bundle}=await session.load(s,{navigation:parent}));const second=bundle.list.data.items[0];
  assert.equal(bundle.overview.query_context_id,context);assert.equal(bundle.list.data.summary.tokens.total_tokens,'2905000');
  const detail=await session.load({...s,view:'detail',conversation:second.id},{navigation:bundle.navigation});
  assert.deepEqual(detail.bundle.detail.data.summary,detail.bundle.events.data.summary);assert.equal(detail.bundle.detail.data.summary.tokens.total_tokens,second.summary.tokens.total_tokens);
  const restored=await session.load(s,{navigation:bundle.navigation});assert.equal(restored.bundle.list.data.items[0].id,second.id);
  const claude=await session.load(selection({provider:'claude'}),{navigation:bundle.navigation});assert.equal(claude.bundle.overview.data.summary.tokens.total_tokens,'65000');assert.equal(claude.bundle.overview.range.end_at,end);
  const cleared=await session.load(s,{navigation:claude.bundle.navigation});assert.equal(cleared.bundle.overview.data.summary.tokens.total_tokens,'2905000');assert.equal(cleared.bundle.overview.range.end_at,end);
});
test('real derived project/day clear returns to all usage without shifting the frozen clock',async()=>{
  const session=createLocalSession(client),s=selection(),all=await session.load(s),id=all.bundle.facets.data.projects[0].value;
  const filtered=await session.load({...s,project:id,day:'2026-10-23'},{navigation:all.bundle.navigation});
  const cleared=await session.load(s,{navigation:filtered.bundle.navigation});
  assert.deepEqual(cleared.bundle.overview.applied_filters.project_id,[]);assert.equal(cleared.bundle.overview.applied_filters.selected_day,null);assert.equal(cleared.bundle.overview.range.end_at,all.bundle.overview.range.end_at);
});
test('production DOM handlers preserve cursor, parent scroll, browser Back and cancelled search',async()=>{
  const app=await localDashboard(client);await app.change('pageSize','1');
  await app.click('next');const parent=app.app.accepted,identity=parent.list.data.items[0].id;app.window.scrollY=450;
  await app.click('detail',{id:identity});assert.match(app.html,/Lifetime accepted usage/);
  await app.click('back');assert.equal(app.app.accepted.list.data.items[0].id,identity);assert.equal(app.window.scrollY,450);
  await app.click('detail',{id:identity});await app.browserBack();assert.equal(app.app.snapshot.state.view,'explore');assert.equal(app.app.accepted.list.data.items[0].id,identity);
  await app.input('not-submitted');await app.click('clear');await app.flush();assert.equal(app.app.snapshot.state.q,'');assert.doesNotMatch(app.location.hash,/not-submitted/);
  app.app.dispose();
});
test('production DOM provider selection and empty state use server totals and exact identities',async()=>{
  const app=await localDashboard(client);await app.click('provider',{value:'claude'});assert.match(app.html,/65,000/);assert.equal(app.app.accepted.overview.applied_filters.provider[0],'claude');
  await app.input('no-synthetic-match');await app.flush();assert.match(app.html,/No recorded activity matches/);assert.match(app.html,/No matching conversations/);assert.doesNotMatch(app.html,/DEMO DATA/);app.app.dispose();
});
test('production event cursor controls preserve the full matched conversation headline',async()=>{
  const app=await localDashboard(client);await app.change('pageSize','1');const id=app.app.accepted.list.data.items[0].id;
  await app.click('detail',{id});const first=app.app.accepted;
  assert.equal(first.detail.data.summary.tokens.total_tokens,'2840000');assert.ok(first.events.data.pagination.next_cursor);
  const eventId=first.events.data.items[0].id;await app.click('event-next');
  assert.notEqual(app.app.accepted.events.data.items[0].id,eventId);assert.equal(app.app.accepted.detail.data.summary.tokens.total_tokens,'2840000');
  await app.click('event-prev');assert.equal(app.app.accepted.events.data.items[0].id,eventId);app.app.dispose();
});
test('settings draft cancels, retains concurrent-conflict edits and never saves through GET',async()=>{
  const calls=[];const proxy={...client,mutate:async(...args)=>{calls.push(args);return client.mutate(args[0],{...args[1],expected_configuration_version:'stale-version'});}};
  const app=await localDashboard(proxy,{hash:'#view=settings'});await app.setting('Codex','31.125');await app.click('save-settings');
  assert.match(app.nodes.get('#settings-result').textContent,/draft is retained/);
  assert.match(app.nodes.get('#settings-result').textContent,/Settings changed elsewhere/);
  await app.click('save-settings');assert.equal(calls[1][1].changes.plan_fees_usd.Codex,'31.125');
  await app.click('cancel-settings');assert.match(app.html,/value="20\.00"/);app.app.dispose();
});
test('actual settings publication invalidates old contexts; one full refresh clears old cursor',async()=>{
  const session=createLocalSession(client),s=selection(),old=await session.load(s);const saved=await client.read('settings');
  const changed=await client.mutate('settings',{expected_configuration_version:saved.data.configuration_version,changes:{plan_fees_usd:{Codex:'21',Claude:'20'}}});
  assert.equal(changed.data.pending,true);
  const job=changed.data.jobs[0];const done=await observeLocalJob(client,job.id,{signal:new AbortController().signal,wait:()=>new Promise(r=>setTimeout(r,25))});assert.equal(done.state,'succeeded');
  const nav=old.bundle.navigation;nav.cursor=old.bundle.list.data.pagination.next_cursor;nav.previous=[null];
  const refreshed=await session.load(s,{navigation:nav});assert.equal(refreshed.refreshed,true);assert.equal(refreshed.bundle.navigation.cursor,null);assert.deepEqual(refreshed.bundle.navigation.previous,[]);assert.notEqual(refreshed.bundle.overview.configuration_version,old.bundle.overview.configuration_version);
  assert.ok(requestLog.every(r=>!r.path.includes('/preview')));assert.ok(csrf); // No provider call is configured in the real test runtime.
});

test('production Settings saves fee100 and Overview uses the published fee without changing usage',async()=>{
  const app=await localDashboard(client,{hash:'#view=settings'});
  const before=await client.usage('overview',{query:{period:'month'}});
  try{
    await app.setting('Claude','100');await app.click('save-settings');
    assert.equal((await client.read('settings')).data.settings.plan_fees_usd.Claude,'100');
    await app.nav('overview');
    const after=app.app.accepted.overview;
    assert.deepEqual(after.data.summary,before.data.summary);
    const comparison=after.data.comparisons.find(c=>c.provider==='claude');
    assert.equal(comparison.fee_usd,'100');assert.equal(comparison.difference_usd,'-99.529000000000');
    assert.equal(after.configuration_version,(await client.read('settings')).data.configuration_version);
  }finally{
    app.app.dispose();const current=await client.read('settings');
    const restored=await client.mutate('settings',{expected_configuration_version:current.data.configuration_version,changes:{plan_fees_usd:{Codex:'20.00',Claude:'20.00'}}});
    if(restored.data.jobs.length)assert.equal((await observeLocalJob(client,restored.data.jobs[0].id,{signal:new AbortController().signal,wait:()=>new Promise(r=>setTimeout(r,25))})).state,'succeeded');
  }
});
