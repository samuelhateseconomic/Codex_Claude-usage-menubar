import {createLocalClient} from './v1-client.js';
import {createLocalSession,defaultSelection,observeLocalJob} from './local-session.js';
import {renderLocal,renderChrome,drawLocalChart,button,escape} from './local-view.js';

const defaults=()=>({...defaultSelection(),view:'overview',metric:'value',table:'conversations',sort:'value_desc',pageSize:50,conversation:''});
export function readLocation(location){
  const p=new URLSearchParams(location.hash.slice(1)),s=defaults();
  for(const key of Object.keys(s))if(p.has(key))s[key]=key==='pageSize'?Number(p.get(key)):p.get(key);
  for(const [key,values]of Object.entries({view:['overview','explore','detail','settings','limits'],provider:['both','codex','claude'],period:['today','week','month'],metric:['value','tokens'],table:['conversations','projects'],sort:['value_desc','tokens_desc','last_activity_desc'],pageSize:[1,25,50,100]}))if(!values.includes(s[key]))s[key]=defaults()[key];
  s.q=s.q.slice(0,200);return s;
}
const hash=s=>{const p=new URLSearchParams();for(const [k,v]of Object.entries(s))if(v!==null&&v!==''&&v!==defaults()[k])p.set(k,String(v));return '#'+p;};

export function mountLocalDashboard({document=globalThis.document,window=globalThis.window,location=globalThis.location,history=globalThis.history,client=createLocalClient()}={}){
  const $=s=>document.querySelector(s),content=$('#content'),session=createLocalSession(client);
  let state=readLocation(location),bundle=null,navigation=null,parent=null,published=null,retry=null,sequence=0,debounce,draft=null,jobAbort=null,operation=0,operationBusy=false,notificationTimer;
  const snapshot=()=>({usageHub:1,state:structuredClone(state),navigation:structuredClone(navigation),parent:structuredClone(parent),scroll:window.scrollY});
  const notify=message=>{$('#notification').textContent=message;window.clearTimeout(notificationTimer);notificationTimer=window.setTimeout(()=>{$('#notification').textContent='';},6000);};
  function syncOperationControls(){for(const node of document.querySelectorAll('[data-action="refresh"], [data-action="save-settings"]'))node.disabled=operationBusy;}
  function render(){renderChrome(document,bundle,state);content.innerHTML=renderLocal(bundle,state,{draft});syncOperationControls();if(state.view==='overview')drawLocalChart(document,bundle,state);}
  function cancelSearch(){window.clearTimeout(debounce);}
  function focus({scroll=0,conversation=null}={}){
    if($('#shortcuts').open)return;
    const opener=conversation?[...document.querySelectorAll('[data-id]')].find(n=>n.dataset.id===conversation):null;
    (opener??content).focus({preventScroll:true});window.scrollTo(0,scroll);
  }
  async function load({fresh=false,restore=null,focusView=true}={}){
    const current=++sequence,requested=snapshot();
    content.setAttribute('aria-busy','true');
    content.innerHTML='<p class="loading" role="status">Reading committed local usage…</p>';
    try{
      const result=await session.load(state,{navigation,fresh});
      if(current!==sequence||result.state==='superseded')return 'superseded';
      bundle=result.bundle;navigation=bundle.navigation;
      if(result.refreshed){parent=null;notify('The complete query was refreshed. Pagination restarted at the first page.');}
      retry=null;render();published=snapshot();history.replaceState(published,'',hash(state));
      if(focusView)focus({scroll:result.refreshed?0:restore?.scroll??0,conversation:restore?.conversation});
      return 'accepted';
    }catch(error){
      if(current!==sequence||error.name==='AbortError')return 'superseded';
      retry=requested;
      if(published&&bundle){
        ({state,navigation,parent}=structuredClone(published));render();history.replaceState(snapshot(),'',hash(state));
        content.insertAdjacentHTML('afterbegin',`<section class="banner" role="alert"><p>The requested view could not be loaded. The previous accepted result and its original filters are retained.</p><p>${escape(error.message)}</p>${button('Retry requested view','retry')}</section>`);
      }else{
        $('#breadcrumb').textContent='Local usage unavailable';$('#connection').textContent='No accepted usage query';$('#capture').textContent='No snapshot displayed';
        content.innerHTML=`<section class="panel"><h1>Local usage unavailable</h1><p>${escape(error.message)}</p><p>No sample data has been substituted. Check indexing status or reopen through the application.</p>${button('Retry query','retry')}${button('Check service status','status')}</section>`;
      }
      notify('Could not load the requested view.');return 'failed';
    }finally{if(current===sequence)content.setAttribute('aria-busy','false');}
  }
  async function navigate(changes={},options={}){
    cancelSearch();
    if(published)history.replaceState(snapshot(),'',hash(state));
    const old=state;state={...state,...changes};
    if(options.restore){navigation=structuredClone(options.restore.navigation);parent=structuredClone(options.restore.parent);}
    else if(navigation){
      navigation=structuredClone(navigation);
      if(old.table!==state.table||old.sort!==state.sort||old.pageSize!==state.pageSize||old.view!==state.view&&state.view!=='detail'){navigation.cursor=null;navigation.previous=[];}
      if(old.conversation!==state.conversation){navigation.eventsCursor=null;navigation.eventPrevious=[];}
    }
    if(options.fresh)navigation=null;
    history[options.replace?'replaceState':'pushState'](snapshot(),'',hash(state));
    return load({fresh:options.fresh,restore:options.restore,focusView:options.focus!==false});
  }
  async function checkJob(id){
    jobAbort?.abort();jobAbort=new AbortController();const active=jobAbort;
    try{
      const result=await observeLocalJob(client,id,{signal:active.signal,onUpdate:j=>notify(`Local ${j.kind}: ${j.status} · ${j.phase}`)});
      if(active.signal.aborted)return;
      if(result.state==='succeeded'){
        // Publication is complete; capture all report widgets together.
        const outcome=await navigate({},{fresh:true,replace:true});
        if(outcome==='accepted')notify('Local operation completed. The complete view has been refreshed.');
        else if(outcome==='failed')notify('Local operation completed, but this view could not refresh. Previous results are retained.');
      }else notify(result.state==='pending'?'The operation is still running. Check service status or refresh later.':`Local operation ${result.state}. Previous committed usage is retained.`);
    }catch(e){if(!active.signal.aborted)notify(e.message);}
  }
  async function operationAction(kind,body){
    if(operationBusy)return;
    operationBusy=true;syncOperationControls();const current=++operation;
    try{
      const response=await client.mutate(kind,body);
      if(current!==operation)return;
      if(kind==='settings'){
        draft=null;
        if(state.view==='settings'&&bundle?.wire){bundle.wire.data.configuration_version=response.data.configuration_version;bundle.wire.data.settings=response.data.settings;render();}
        const job=response.data.jobs.find(j=>['queued','running'].includes(j.status));
        notify(response.data.pending?'Settings saved; computation is pending.':'Settings saved.');
        if(job)await checkJob(job.id);else await navigate({},{fresh:true,replace:true});
      }else await checkJob(response.data.id);
    }catch(error){
      // Preserve the typed draft and loaded expected version on conflicts.
      if(current===operation){notify(error.message);if(state.view==='settings')$('#settings-result').textContent=error.message+' Your draft is retained.';}
    }finally{if(current===operation){operationBusy=false;syncOperationControls();}}
  }
  const beginDraft=()=>draft??(draft={Codex:bundle.wire.data.settings.plan_fees_usd.Codex??'',Claude:bundle.wire.data.settings.plan_fees_usd.Claude??'',timezone:bundle.wire.data.settings.timezone});
  async function back(){
    if(parent){const saved=structuredClone(parent),id=state.conversation;return navigate(saved.state,{replace:true,restore:{...saved,conversation:id}});}
    return navigate({view:'explore',conversation:''},{replace:true});
  }
  document.addEventListener('click',async event=>{
    const nav=event.target.closest('[data-nav]');
    if(nav){event.preventDefault();return navigate({view:nav.dataset.nav,conversation:''});}
    const target=event.target.closest('[data-action]');if(!target||target.disabled)return;
    const {action,value,id,model,effort,provider}=target.dataset;
    if(action==='help')return $('#shortcuts').showModal();
    if(action==='close-help')return $('#shortcuts').close();
    if(action==='copy'){try{await window.navigator.clipboard.writeText(value);notify('Conversation ID copied.');}catch{notify('Select the displayed ID to copy it.');}return;}
    if(action==='status'){
      try{const s=await client.read('status');notify(s.data.ready?`Committed index: ${s.data.freshness}${s.data.indexing?' · work in progress':''}`:s.data.indexing?'Initial indexing is in progress. Retry when complete.':'No committed usage is available. Check approved local sources and settings.');}catch(e){notify(e.message);}return;
    }
    if(action==='retry'){if(retry){({state,navigation,parent}=structuredClone(retry));return load();}return load();}
    if(action==='refresh')return operationAction('refresh',{});
    if(action==='refresh-query')return navigate({},{fresh:true,replace:true});
    if(action==='metric'){
      if(!bundle?.overview)return;
      state.metric=value;render();published=snapshot();history.replaceState(published,'',hash(state));return;
    }
    if(action==='search'){const outcome=await navigate({view:'explore',conversation:''},{focus:false});if(outcome==='accepted'&&!$('#shortcuts').open)$('#search')?.focus();return;}
    if(action==='provider')return navigate({provider:value,conversation:'',view:state.view==='detail'?'explore':state.view});
    if(action==='provider-explore')return navigate({provider:value,view:'explore',conversation:''});
    if(action==='view')return navigate({view:value,conversation:''});
    if(action==='table')return navigate({table:value,conversation:''});
    if(action==='projects')return navigate({view:'explore',table:'projects',conversation:''});
    if(action==='project')return navigate({view:'explore',table:'conversations',project:value,conversation:''});
    if(action==='model-group')return navigate({view:'explore',model,effort,provider,conversation:''});
    if(action==='day')return navigate({view:'explore',day:value,conversation:''});
    if(action==='clear-day')return navigate({day:'',conversation:''});
    if(action==='clear')return navigate({provider:'both',project:'',model:'',effort:'',q:'',day:'',conversation:'',view:state.view==='detail'?'explore':state.view});
    if(['next','prev','event-next','event-prev'].includes(action)){
      if(!navigation)return;
      const events=action.startsWith('event-'),stack=events?'eventPrevious':'previous',cursor=events?'eventsCursor':'cursor',next=(events?bundle.events:bundle.list)?.data.pagination.next_cursor;
      if(action.endsWith('next')){if(!next)return;navigation[stack].push(navigation[cursor]);navigation[cursor]=next;}
      else {if(!navigation[stack].length)return;navigation[cursor]=navigation[stack].pop();}
      // Keep the outgoing page in its own history entry.
      const updated=structuredClone(navigation);navigation=structuredClone(published.navigation);
      return navigate({},{restore:{...snapshot(),navigation:updated,scroll:0},focus:true});
    }
    if(action==='detail'){parent=snapshot();return navigate({view:'detail',conversation:id});}
    if(action==='back')return back();
    if(action==='cancel-settings'){draft=null;render();notify('Draft cancelled.');return;}
    if(action==='reload-settings'){draft=null;return navigate({},{replace:true});}
    if(action==='save-settings'){
      const d=beginDraft();return operationAction('settings',{expected_configuration_version:bundle.wire.data.configuration_version,changes:{plan_fees_usd:{Codex:d.Codex.trim()===''?null:d.Codex.trim(),Claude:d.Claude.trim()===''?null:d.Claude.trim()},timezone:d.timezone.trim()}});
    }
  });
  document.addEventListener('change',event=>{
    if(['period','project','model','effort','sort','pageSize'].includes(event.target.id))return navigate({[event.target.id]:event.target.id==='pageSize'?Number(event.target.value):event.target.value,conversation:'',...(event.target.id==='period'?{day:''}:{})});
  });
  document.addEventListener('input',event=>{
    if(event.target.dataset?.setting){beginDraft()[event.target.dataset.setting]=event.target.value;return;}
    if(event.target.id!=='search')return;
    const q=event.target.value;cancelSearch();debounce=window.setTimeout(async()=>{
      const focused=document.activeElement?.id==='search',outcome=await navigate({q,conversation:''},{replace:true,focus:false});
      if(focused&&outcome==='accepted'&&!$('#shortcuts').open)$('#search')?.focus();
    },250);
  });
  document.addEventListener('keydown',async event=>{
    if($('#shortcuts').open||event.target.closest('input,textarea,select'))return;
    if(event.key==='/'&&!event.ctrlKey&&!event.metaKey){event.preventDefault();const outcome=await navigate({view:'explore',conversation:''},{focus:false});if(outcome==='accepted')$('#search')?.focus();}
    if(event.key==='?'){event.preventDefault();$('#shortcuts').showModal();}
    if(event.key==='Escape'&&state.view==='detail'){event.preventDefault();return back();}
    if(['Enter',' '].includes(event.key)&&event.target.matches('g[role=button]')){event.preventDefault();event.target.dispatchEvent(new window.MouseEvent('click',{bubbles:true}));}
  });
  window.addEventListener('popstate',async event=>{
    cancelSearch();const saved=event.state?.usageHub===1?event.state:null;
    state=saved?structuredClone(saved.state):readLocation(location);navigation=saved?structuredClone(saved.navigation):null;parent=saved?structuredClone(saved.parent):null;
    await load({restore:saved});
  });
  window.addEventListener('resize',()=>{if(bundle?.overview&&state.view==='overview')drawLocalChart(document,bundle,state);});
  const ready=(async()=>{
    try{
      await client.authenticate({location,history});state=readLocation(location);
      const saved=history.state?.usageHub===1?history.state:null;
      if(saved&&hash(saved.state)===hash(state)){navigation=structuredClone(saved.navigation);parent=structuredClone(saved.parent);}
      return await load({restore:saved,focusView:false});
    }catch(error){content.setAttribute('aria-busy','false');content.innerHTML=`<section class="panel"><h1>Open Usage Hub through the application</h1><p>${escape(error.message)}</p><p>This page requires an authenticated local launch. Reopen the dashboard from Usage Tray.</p></section>`;return 'failed';}
  })();
  return {ready,navigate,get snapshot(){return snapshot();},get accepted(){return bundle?structuredClone(bundle):null;},dispose(){cancelSearch();session.cancel();jobAbort?.abort();operation++;sequence++;}};
}

if(globalThis.document&&globalThis.window)mountLocalDashboard();
