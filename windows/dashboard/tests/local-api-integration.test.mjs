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
test('projected initial Explore captures a clock cheaply and reuses its validated whole-query analysis',async()=>{
  const start=requestLog.length,app=await localDashboard(client);
  assert.equal(app.app.accepted.overview.data.summary.tokens.total_tokens,'2840000');
  assert.deepEqual(app.app.accepted.analysis.data.analysis,app.app.accepted.overview.data.analysis);
  const paths=requestLog.slice(start).map(r=>r.path);
  assert.ok(paths.some(p=>p.includes('/usage/projects?')&&p.includes('page_size=1')&&p.includes('projection=app_api_value_v1')));
  assert.ok(paths.every(p=>!p.includes('/usage/analysis?')));
  app.app.dispose();
});
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
  await app.click('load-more');const parent=app.app.accepted,identity=parent.list.data.items.at(-1).id;app.window.scrollY=450;
  await app.click('detail',{id:identity});assert.match(app.html,/Lifetime accepted usage/);
  await app.click('back');assert.equal(app.app.accepted.list.data.items.at(-1).id,identity);assert.equal(app.window.scrollY,450);
  await app.click('detail',{id:identity});await app.browserBack();assert.equal(app.app.snapshot.state.view,'explore');assert.equal(app.app.accepted.list.data.items.at(-1).id,identity);
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
  const before=await client.usage('overview',{query:{period:'month',projection:'app_api_value_v1'}});
  try{
    await app.setting('Claude','100');await app.click('save-settings');
    assert.equal((await client.read('settings')).data.settings.plan_fees_usd.Claude,'100');
    await app.nav('overview');
    const after=app.app.accepted.overview;
    assert.deepEqual(after.data.summary,before.data.summary);
    const comparison=after.data.comparisons.find(c=>c.provider==='claude');
    assert.equal(comparison.fee_usd,'100');assert.equal(comparison.available,false);assert.equal(comparison.difference_usd,null);
    const unfiltered=await client.usage('overview',{query:{period:'month'}});
    assert.equal(unfiltered.data.comparisons.find(c=>c.provider==='claude').difference_usd,'-99.529000000000');
    assert.equal(after.configuration_version,(await client.read('settings')).data.configuration_version);
  }finally{
    app.app.dispose();const current=await client.read('settings');
    const restored=await client.mutate('settings',{expected_configuration_version:current.data.configuration_version,changes:{plan_fees_usd:{Codex:'20.00',Claude:'20.00'}}});
    if(restored.data.jobs.length)assert.equal((await observeLocalJob(client,restored.data.jobs[0].id,{signal:new AbortController().signal,wait:()=>new Promise(r=>setTimeout(r,25))})).state,'succeeded');
  }
});

test('history expands and contracts by ten, caps at fifty and pages without changing totals',async()=>{
  child.stdin.write('history\n');assert.equal(JSON.parse((await iterator.next()).value).ok,true);
  const app=await localDashboard(client),shown=()=>Math.min(app.app.accepted.navigation.historyVisible,app.app.accepted.list.data.items.length);
  const first=app.app.accepted,context=first.overview.query_context_id,total=first.overview.data.summary;
  assert.equal(shown(),10);assert.equal(first.list.data.items.length,50);assert.equal(first.list.data.pagination.page_size,50);assert.doesNotMatch(app.html,/id="pageSize"/);
  const start=requestLog.length;
  for(const n of [20,30,40,50]){await app.click('load-more');assert.equal(shown(),n);}
  await app.click('load-more');assert.equal(shown(),50);assert.doesNotMatch(app.html,/data-action="load-more"/);assert.match(app.html,/data-action="load-less"/);
  for(const n of [40,30,20,10]){await app.click('load-less');assert.equal(shown(),n);}
  await app.click('load-less');assert.equal(shown(),10);assert.doesNotMatch(app.html,/data-action="load-less"/);
  assert.equal(requestLog.length,start,'local expansion never reads or rescans');
  for(let i=0;i<4;i++)await app.click('load-more');
  const firstIds=app.app.accepted.list.data.items.map(c=>c.id);
  await app.click('next');assert.equal(shown(),10);assert.equal(app.app.accepted.navigation.previous.length,1);assert.equal(app.app.accepted.list.data.items.length,50);
  const secondIds=app.app.accepted.list.data.items.map(c=>c.id);assert.ok(secondIds.every(id=>!firstIds.includes(id)));assert.match(app.html,/Showing 51–60/);
  await app.click('next');assert.equal(shown(),10);assert.equal(app.app.accepted.list.data.items.length,23);
  await app.click('load-more');await app.click('load-more');assert.equal(shown(),23);assert.match(app.html,/Showing 101–123/);assert.match(app.html,/data-action="next" disabled/);
  assert.equal(new Set([...firstIds,...secondIds,...app.app.accepted.list.data.items.map(c=>c.id)]).size,123);
  await app.click('prev');assert.equal(shown(),10);assert.deepEqual(app.app.accepted.list.data.items.map(c=>c.id),secondIds);
  await app.click('load-more');const id=app.app.accepted.list.data.items[19].id;app.window.scrollY=600;
  await app.click('detail',{id});await app.click('back');assert.equal(shown(),20);assert.equal(app.app.accepted.navigation.previous.length,1);assert.equal(app.window.scrollY,600);
  await app.nav('overview');await app.nav('explore');assert.equal(shown(),20);assert.equal(app.window.scrollY,600);
  await app.click('metric',{value:'tokens'});assert.equal(shown(),20);assert.equal(app.app.accepted.overview.query_context_id,context);assert.deepEqual(app.app.accepted.overview.data.summary,total);
  await app.change('sort','last_activity_desc');assert.equal(shown(),10);assert.equal(app.app.accepted.navigation.cursor,null);
  await app.click('provider',{value:'claude'});assert.equal(app.app.accepted.navigation.historyVisible,10);assert.equal(app.app.accepted.navigation.cursor,null);
  app.app.dispose();
});

test('failed Next retains the accepted history page and Retry loads the next page once',async()=>{
  let failing=false;
  const proxy={...client,usage:async(kind,args,...rest)=>{if(failing&&kind==='conversations'&&args.cursor)throw new Error('fixture next-page failure');return client.usage(kind,args,...rest);}};
  const app=await localDashboard(proxy);await app.click('load-more');const first=app.app.accepted;
  failing=true;await app.click('next');assert.deepEqual(app.app.accepted.list,first.list);assert.deepEqual(app.app.accepted.overview,first.overview);assert.equal(app.app.accepted.navigation.historyVisible,20);
  assert.match(app.html,/previous accepted result/);failing=false;await app.click('retry');
  assert.equal(app.app.accepted.navigation.historyVisible,10);assert.equal(app.app.accepted.navigation.previous.length,1);assert.equal(app.app.accepted.list.data.items.length,50);assert.equal(new Set(app.app.accepted.list.data.items.map(c=>c.id)).size,50);
  app.app.dispose();
});

test('repeated Next is coalesced and expiry restarts a coherent first ten',async()=>{
  let pause=false,release,started,signalStart,expired=false,nextCalls=0;
  const proxy={...client,usage:async(kind,args,...rest)=>{
    if(kind==='conversations'&&args.cursor){nextCalls++;if(expired){expired=false;throw new LocalApiError('context_expired',409);}if(pause){signalStart();await new Promise(resolve=>release=resolve);}}
    return client.usage(kind,args,...rest);
  }};
  const app=await localDashboard(proxy);app.window.scrollY=800;
  started=new Promise(resolve=>signalStart=resolve);pause=true;const pending=app.click('next');await started;
  await app.click('next');pause=false;release();await pending;
  assert.equal(nextCalls,1);assert.equal(app.app.accepted.navigation.previous.length,1);assert.equal(app.app.accepted.navigation.historyVisible,10);
  expired=true;await app.click('next');assert.equal(app.app.accepted.navigation.historyVisible,10);
  assert.equal(app.app.accepted.navigation.cursor,null);assert.deepEqual(app.app.accepted.navigation.previous,[]);assert.match(app.nodes.get('#notification').textContent,/complete query was refreshed/);
  app.app.dispose();
});
