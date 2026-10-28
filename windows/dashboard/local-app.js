import {createLocalClient} from './v1-client.js';
import {createLocalSession,defaultSelection,observeLocalJob} from './local-session.js';
import {renderLocal,renderChrome,drawLocalChart,renderOperationFeedback,renderPublicationStatus,renderScanStatus,renderCapacityStatus,button,escape} from './local-view.js';
import {watchLocalPublication} from './local-freshness.js';

const defaults=()=>({...defaultSelection(),view:'overview',metric:'value',table:'conversations',sort:'value_desc',pageSize:10,conversation:''});
export function readLocation(location){
  const p=new URLSearchParams(location.hash.slice(1)),s=defaults();
  for(const key of Object.keys(s))if(p.has(key))s[key]=key==='pageSize'?Number(p.get(key)):p.get(key);
  for(const [key,values]of Object.entries({view:['overview','explore','detail','settings','limits'],provider:['both','codex','claude'],period:['today','week','month'],metric:['value','credits','tokens'],table:['conversations','projects'],sort:['value_desc','tokens_desc','last_activity_desc'],pageSize:[1,10,25,50,100]}))if(!values.includes(s[key]))s[key]=defaults()[key];
  if(['overview','explore'].includes(s.view)&&!p.has('period'))s.period='week';
  if(s.view==='explore'&&s.provider==='both')s.provider='codex';
  if(s.view==='explore'&&!p.has('metric'))s.metric='credits';
  for(const key of ['project','model','effort'])if(p.get(key)?.startsWith('[')){
    try{const values=JSON.parse(p.get(key));if(!Array.isArray(values)||values.length>64||values.some(v=>typeof v!=='string'||!v||v.length>(key==='effort'?80:1024)))throw new Error();s[key]=[...new Set(values)].sort();}catch{s[key]='';}
  }
  s.q=s.q.slice(0,200);return s;
}
const pageDefault=view=>({...defaults(),view,period:['overview','explore'].includes(view)?'week':'month',provider:view==='explore'?'codex':'both',metric:view==='explore'?'credits':'value'});
const hash=(s,pages={})=>{const p=new URLSearchParams();for(const [k,v]of Object.entries(s))if(v!==null&&v!==''&&(k==='view'?v!=='overview':v!==pageDefault(s.view)[k]))p.set(k,Array.isArray(v)?JSON.stringify(v):String(v));for(const [page,entry]of Object.entries(pages))if(page!==s.view)for(const [k,v]of Object.entries(entry.state))if(k!=='view'&&k!=='conversation'&&v!==null&&v!==''&&v!==pageDefault(page)[k])p.set(page+'.'+k,Array.isArray(v)?JSON.stringify(v):String(v));return '#'+p;};
function pagesFromLocation(location){const p=new URLSearchParams(location.hash.slice(1)),pages={};for(const view of ['overview','explore']){const q=new URLSearchParams({view});let found=false;for(const k of Object.keys(defaults()))if(p.has(view+'.'+k)&&k!=='view'){q.set(k,p.get(view+'.'+k));found=true;}if(found)pages[view]={state:readLocation({hash:'#'+q}),navigation:null,scroll:0};}return pages;}

export function mountLocalDashboard({document=globalThis.document,window=globalThis.window,location=globalThis.location,history=globalThis.history,client=createLocalClient()}={}){
  const $=s=>document.querySelector(s),content=$('#content'),session=createLocalSession(client,{projected:true});
  let state=readLocation(location),bundle=null,navigation=null,parent=null,published=null,retry=null,sequence=0,debounce,draft=null,draftVersion=null,jobAbort=null,operation=0,operationBusy=false,notificationTimer,feedback=null;
  let latestStatus=null,statusFailed=false;
  let pages=pagesFromLocation(location);
  const url=()=>hash(state,pages);
  const publication=()=>{const node=$('#publication-status');if(node&&bundle)node.innerHTML=renderPublicationStatus(bundle,latestStatus,statusFailed);const footer=$('#scan-status');if(footer&&bundle)footer.innerHTML=renderScanStatus(bundle,latestStatus);};
  const freshness=watchLocalPublication({client,document,window,onStatus:status=>{
    if(!bundle||status.dataset_id!==bundle.status.dataset_id){statusFailed=true;publication();return;}
    const changed=JSON.stringify(latestStatus?.data.providers)!==JSON.stringify(status.data.providers);
    latestStatus=status;statusFailed=false;publication();
    const capacity=$('#capacity-current');
    if(changed&&capacity&&state.view==='overview'&&!capacity.contains?.(document.activeElement))capacity.innerHTML=renderCapacityStatus(status.data.providers,bundle.overview.range.timezone,status.generated_at);
  },onFailure:()=>{statusFailed=true;publication();}});
  const snapshot=()=>({usageHub:1,state:structuredClone(state),navigation:structuredClone(navigation),parent:structuredClone(parent),pages:structuredClone(pages),scroll:window.scrollY});
  const notify=message=>{$('#notification').textContent=message;window.clearTimeout(notificationTimer);notificationTimer=window.setTimeout(()=>{$('#notification').textContent='';},6000);};
  function syncOperationControls(){for(const node of document.querySelectorAll('[data-action="refresh"], [data-action="save-settings"], [data-action="check-job"], [data-setting], #settings-timezone-mode'))node.disabled=operationBusy;}
  // Operation feedback survives transient notifications and view changes. A
  // reopened page recovers pending work from the owner's durable status.
  function setFeedback(state,message,extra={}){
    feedback={...feedback,state,message,checkable:false,...extra};
    const node=$('#operation-status');if(node){node.hidden=false;node.innerHTML=renderOperationFeedback(feedback);syncOperationControls();}
  }
  function recoverFeedback(){
    const s=bundle.status.data,j=s.last_job;
    if(!operationBusy&&!s.configuration_pending&&j?.status==='succeeded'&&feedback?.kind==='settings'&&feedback.jobId===j.id&&
       ['pending','unconfirmed','applying'].includes(feedback.state)&&j.resulting_versions?.configuration_version===s.configuration_version&&
       (!bundle.overview||bundle.overview.configuration_version===s.configuration_version)){
      setFeedback('applied','Settings applied. This view uses the active configuration.');return;
    }
    if(operationBusy||!s.configuration_pending||!j||j.requested_configuration_version!==s.requested_configuration_version)return;
    const checkable=['queued','running'].includes(j.status);
    setFeedback(checkable?'pending':'failed',checkable?'Settings saved; application is pending. Previous committed usage remains active.':
      'Saved settings have not been applied. Previous committed usage remains active. Open Settings and Save settings to retry.',{kind:'settings',jobId:j.id,checkable});
  }
  function render(){renderChrome(document,bundle,state);content.innerHTML=renderLocal(bundle,state,{draft,operation:feedback,derived:state.view==='explore'&&parent?.state.view==='overview'});syncOperationControls();publication();for(const menu of document.querySelectorAll('[data-filter-menu]')){const all=menu.querySelector('[data-filter-all]'),boxes=[...menu.querySelectorAll('[data-filter-option]')];all.indeterminate=!all.checked&&boxes.some(n=>n.checked);}if(['overview','explore'].includes(state.view))drawLocalChart(document,bundle,state);}
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
      bundle=result.bundle;navigation=bundle.navigation;latestStatus=bundle.status;statusFailed=false;freshness.restart();recoverFeedback();
      if(result.refreshed){parent=null;notify('The complete query was refreshed. Pagination restarted at the first page.');}
      retry=null;render();published=snapshot();history.replaceState(published,'',url());
      if(focusView)focus({scroll:result.refreshed?0:restore?.scroll??0,conversation:restore?.conversation});
      return 'accepted';
    }catch(error){
      if(current!==sequence||error.name==='AbortError')return 'superseded';
      retry=requested;
      if(published&&bundle){
        ({state,navigation,parent,pages}=structuredClone(published));render();history.replaceState(snapshot(),'',url());
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
    if(published)history.replaceState(snapshot(),'',url());
    const old=state;
    const switching=changes.view&&changes.view!==old.view;
    if(['overview','explore'].includes(old.view))pages[old.view]={state:structuredClone(old),navigation:structuredClone(navigation),scroll:window.scrollY};
    let targetRestore=null;
    if(switching&&['overview','explore'].includes(changes.view)&&!options.restore&&!options.derived){
      targetRestore=pages[changes.view];state={...(targetRestore?.state??pageDefault(changes.view)),...changes};navigation=structuredClone(targetRestore?.navigation??null);parent=null;
    }else state={...state,...changes};
    if(state.view==='explore'&&state.provider==='both')state.provider=pages.explore?.state.provider==='claude'?'claude':'codex';
    if(options.restore){navigation=structuredClone(options.restore.navigation);parent=structuredClone(options.restore.parent);pages=structuredClone(options.restore.pages??pages);}
    else if(navigation&&!targetRestore){
      navigation=structuredClone(navigation);
      if(old.table!==state.table||old.sort!==state.sort||old.pageSize!==state.pageSize||old.view!==state.view&&state.view!=='detail'){navigation.cursor=null;navigation.previous=[];navigation.historyVisible=10;}
      if(old.conversation!==state.conversation){navigation.eventsCursor=null;navigation.eventPrevious=[];}
    }
    if(options.fresh)navigation=null;
    history[options.replace?'replaceState':'pushState'](snapshot(),'',url());
    return load({fresh:options.fresh,restore:options.restore??targetRestore,focusView:options.focus!==false});
  }
  function drilldown(changes){
    const saved=snapshot();
    if(state.view==='overview')parent={...saved,parent:null};
    const provider=changes.provider??(state.provider==='both'?(pages.explore?.state.provider??'codex'):state.provider);
    notify('Explore scope: '+provider+' · primary model only. Overview filters are kept.');
    return navigate({...changes,provider,view:'explore',conversation:''},{derived:true});
  }
  async function checkJob(id){
    jobAbort?.abort();jobAbort=new AbortController();const active=jobAbort;
    const kind=feedback?.kind??'refresh',label=kind==='settings'?'Settings':'Local operation';
    try{
      const result=await observeLocalJob(client,id,{signal:active.signal,onUpdate:j=>{
        setFeedback('applying',`${label}: ${j.status} · ${j.phase}. Previous committed usage remains active until publication.`,{kind,jobId:id});
      }});
      if(active.signal.aborted)return;
      if(result.state==='succeeded'){
        if(kind==='settings'){
          for(const entry of Object.values(pages)){entry.navigation=null;entry.state.timezone=null;}
          navigation=null;state.timezone=null;
        }
        // Publication is complete; capture all report widgets together.
        setFeedback('refreshing',`${label} applied. Refreshing the complete view…`);
        const outcome=await navigate({},{fresh:true,replace:true});
        if(outcome==='accepted'){
          if(kind==='settings'&&bundle.status.data.configuration_pending){
            setFeedback('pending','The operation completed; a newer saved configuration is pending. Refresh the view to check its status.');
          }else setFeedback('applied',kind==='settings'?'Settings applied. The complete view has been refreshed.':'Local operation completed. The complete view has been refreshed.');
          notify(feedback.message);
        }else if(outcome==='failed'){
          setFeedback('unconfirmed',`${label} applied, but this view could not refresh. Previous results are retained. Use Refresh view to retry.`);notify(feedback.message);
        }else if(outcome==='superseded'){
          setFeedback('applied',`${label} applied. Navigation changed while refreshing; use Refresh view to capture the latest usage.`);
        }
      }else{
        setFeedback(result.state,result.state==='pending'?`${label}${kind==='settings'?' saved;':' is'} still running. Check progress to resume observation.`:
          `${label} could not be applied (${result.state}). Previous committed usage is retained. ${kind==='settings'?'Reload Settings before retrying Save settings.':'Retry Rescan local logs.'}`,{jobId:id,checkable:result.state==='pending'});
        notify(feedback.message);
      }
    }catch(e){if(!active.signal.aborted){setFeedback('unconfirmed',`${label} progress could not be confirmed. ${e.message} Check progress to retry.`,{jobId:id,checkable:true});notify(feedback.message);}}
  }
  async function operationAction(kind,body){
    if(operationBusy)return;
    operationBusy=true;syncOperationControls();const current=++operation;
    setFeedback('saving',kind==='settings'?'Saving settings…':'Requesting local rescan…',{kind,jobId:null});
    try{
      const response=await client.mutate(kind,body);
      if(current!==operation)return;
      if(kind==='settings'){
        draft=null;draftVersion=null;
        if(state.view==='settings'&&bundle?.wire){bundle.wire.data.configuration_version=response.data.configuration_version;bundle.wire.data.settings=response.data.settings;render();}
        const job=response.data.jobs.find(j=>['queued','running'].includes(j.status));
        setFeedback(response.data.pending?'applying':'applied',response.data.pending?'Settings saved. Applying them to usage comparisons…':'Settings applied.');
        notify(response.data.pending?'Settings saved; computation is pending.':'Settings saved.');
        if(job)await checkJob(job.id);else await navigate({},{fresh:true,replace:true});
      }else await checkJob(response.data.id);
    }catch(error){
      // Preserve the typed draft and loaded expected version on conflicts.
      if(current===operation){
        setFeedback('unconfirmed',kind==='settings'?`Settings update was not confirmed. ${error.message} Your draft is retained. Reload settings to check saved values before retrying.`:`Rescan was not confirmed. ${error.message}`);
        notify(error.message);if(state.view==='settings')$('#settings-result').textContent=error.message+' Your draft is retained.';
      }
    }finally{if(current===operation){operationBusy=false;syncOperationControls();}}
  }
  const beginDraft=()=>{
    if(!draft){draftVersion=bundle.wire.data.configuration_version;draft={Codex:bundle.wire.data.settings.plan_fees_usd.Codex??'',Claude:bundle.wire.data.settings.plan_fees_usd.Claude??'',timezone:bundle.wire.data.settings.timezone};}
    return draft;
  };
  async function back(){
    if(parent){const saved=structuredClone(parent),id=state.conversation;return navigate(saved.state,{replace:true,restore:{...saved,conversation:id}});}
    return navigate({view:'explore',conversation:''},{replace:true});
  }
  document.addEventListener('click',async event=>{
    for(const menu of document.querySelectorAll('[data-filter-menu][open], .project-path[open]'))if(!menu.contains(event.target))menu.open=false;
    const nav=event.target.closest('[data-nav]');
    if(nav){event.preventDefault();return navigate({view:nav.dataset.nav,conversation:''});}
    const target=event.target.closest('[data-action]');if(!target||target.disabled)return;
    const {action,value,id,model,effort,provider}=target.dataset;
    if(action==='apply-filter'){
      const menu=target.closest('[data-filter-menu]'),key=menu.dataset.filterMenu;
      if(!['project','model','effort'].includes(key)||content.getAttribute('aria-busy')==='true')return;
      const boxes=[...menu.querySelectorAll('[data-filter-option]')],selected=boxes.filter(n=>n.checked).map(n=>n.value);
      const all=menu.querySelector('[data-filter-all]').checked;
      if(!all&&selected.length>64){notify('Choose up to 64 values, or use Select all.');return;}
      const outcome=await navigate({[key]:all?'':selected.sort(),conversation:''},{focus:false});
      if(outcome==='accepted')$(`#${key} summary`)?.focus();return;
    }
    if(action==='help')return $('#shortcuts').showModal();
    if(action==='close-help')return $('#shortcuts').close();
    if(action==='copy'){try{await window.navigator.clipboard.writeText(value);notify('Conversation ID copied.');}catch{notify('Select the displayed ID to copy it.');}return;}
    if(action==='status'){
      try{const s=await client.read('status');notify(s.data.ready?`Committed index: ${s.data.freshness}${s.data.indexing?' · work in progress':''}`:s.data.indexing?'Initial indexing is in progress. Retry when complete.':'No committed usage is available. Check approved local sources and settings.');}catch(e){notify(e.message);}return;
    }
    if(action==='retry'){if(retry){({state,navigation,parent,pages}=structuredClone(retry));return load();}return load();}
    if(action==='refresh')return operationAction('refresh',{});
    if(action==='check-job'){
      if(operationBusy||!feedback?.jobId)return;
      operationBusy=true;syncOperationControls();
      try{await checkJob(feedback.jobId);}finally{operationBusy=false;syncOperationControls();}return;
    }
    if(action==='refresh-query')return navigate({},{fresh:true,replace:true});
    if(action==='metric'){
      if(!bundle?.overview)return;
      state.metric=value;render();published=snapshot();history.replaceState(published,'',url());return;
    }
    if(action==='search'){const outcome=await navigate({view:'explore',conversation:''},{focus:false});if(outcome==='accepted'&&!$('#shortcuts').open)$('#search')?.focus();return;}
    if(action==='provider')return navigate({provider:value,conversation:'',view:state.view==='detail'?'explore':state.view});
    if(action==='provider-explore')return drilldown({provider:value});
    if(action==='view')return navigate({view:value,conversation:''});
    if(action==='table')return navigate({table:value,conversation:''});
    if(action==='projects')return drilldown({table:'projects'});
    if(action==='explore-matching')return drilldown({});
    if(action==='project')return drilldown({table:'conversations',project:value});
    if(action==='model-group')return drilldown({model,effort,provider});
    if(action==='day')return state.view==='overview'?drilldown({day:value}):navigate({day:value,conversation:''});
    if(action==='clear-day')return navigate({day:'',conversation:''});
    if(action==='clear')return navigate({provider:state.view==='overview'?'both':'codex',project:'',model:'',effort:'',q:'',day:'',conversation:'',view:state.view==='detail'?'explore':state.view});
    if(['rates-next','rates-prev'].includes(action)){
      if(!navigation||!bundle.analysis)return;
      const next=structuredClone(navigation);
      next.analysisExpanded=true;
      if(action==='rates-next'){const cursor=bundle.analysis.data.pagination.next_cursor;if(!cursor)return;next.analysisPrevious.push(next.analysisCursor);next.analysisCursor=cursor;}
      else{if(!next.analysisPrevious.length)return;next.analysisCursor=next.analysisPrevious.pop();}
      return navigate({},{restore:{...snapshot(),navigation:next,scroll:window.scrollY},focus:false});
    }
    if(['load-more','load-less'].includes(action)){
      if(state.view!=='explore'||state.table==='projects'||!navigation||content.getAttribute('aria-busy')==='true')return;
      const visible=navigation.historyVisible??10,limit=Math.min(50,bundle.list.data.items.length);
      if(action==='load-more'?visible>=limit:visible<=10)return;
      const scroll=window.scrollY;
      navigation={...navigation,historyVisible:action==='load-more'?Math.min(50,visible+10):Math.max(10,visible-10)};
      bundle={...bundle,navigation:structuredClone(navigation)};render();published=snapshot();history.replaceState(published,'',url());
      window.scrollTo(0,scroll);($(`[data-action="${action}"]`)??$(`[data-action="${action==='load-more'?'load-less':'load-more'}"]`))?.focus({preventScroll:true});
      return;
    }
    if(['next','prev','event-next','event-prev'].includes(action)){
      if(!navigation||content.getAttribute('aria-busy')==='true')return;
      const events=action.startsWith('event-'),stack=events?'eventPrevious':'previous',cursor=events?'eventsCursor':'cursor',next=(events?bundle.events:bundle.list)?.data.pagination.next_cursor;
      if(action.endsWith('next')){if(!next)return;navigation[stack].push(navigation[cursor]);navigation[cursor]=next;}
      else {if(!navigation[stack].length)return;navigation[cursor]=navigation[stack].pop();}
      // Keep the outgoing page in its own history entry.
      const progressive=!events&&state.view==='explore'&&state.table!=='projects';
      if(progressive)navigation.historyVisible=10;
      const updated=structuredClone(navigation);navigation=structuredClone(published.navigation);
      const scroll=progressive?Math.max(0,window.scrollY+($('#history-heading')?.getBoundingClientRect?.().top??-window.scrollY)-20):0;
      const outcome=await navigate({},{restore:{...snapshot(),navigation:updated,scroll},focus:!progressive});
      if(progressive&&outcome==='accepted'){window.scrollTo(0,scroll);$('#history-heading')?.focus({preventScroll:true});}
      return outcome;
    }
    if(action==='detail'){parent=snapshot();return navigate({view:'detail',conversation:id});}
    if(action==='back')return back();
    if(action==='cancel-settings'){draft=null;draftVersion=null;if(!operationBusy&&!feedback?.jobId)feedback=null;render();notify('Draft cancelled.');return;}
    if(action==='reload-settings'){draft=null;draftVersion=null;if(!operationBusy&&!feedback?.jobId)feedback=null;return navigate({},{replace:true});}
    if(action==='save-settings'){
      const d=beginDraft();return operationAction('settings',{expected_configuration_version:draftVersion,changes:{plan_fees_usd:{Codex:d.Codex.trim()===''?null:d.Codex.trim(),Claude:d.Claude.trim()===''?null:d.Claude.trim()},timezone:d.timezone.trim()}});
    }
  });
  document.addEventListener('change',event=>{
    const filterMenu=event.target.closest?.('[data-filter-menu]');
    if(filterMenu){
      const boxes=[...filterMenu.querySelectorAll('[data-filter-option]')],all=filterMenu.querySelector('[data-filter-all]');
      if(event.target.hasAttribute('data-filter-all'))for(const box of boxes)box.checked=all.checked;
      else{all.checked=boxes.length>0&&boxes.every(n=>n.checked);all.indeterminate=boxes.some(n=>n.checked)&&!all.checked;}
      return;
    }
    if(event.target.id==='settings-timezone-mode'){
      const d=beginDraft();d.timezone=event.target.value==='auto'?'auto':bundle.wire.data.settings.timezone_info.name;
      render();($('#settings-timezone')??$('#settings-timezone-mode'))?.focus();return;
    }
    if(['period','project','model','effort','sort','pageSize'].includes(event.target.id))return navigate({[event.target.id]:event.target.id==='pageSize'?Number(event.target.value):event.target.value,conversation:'',...(event.target.id==='period'?{day:''}:{})});
  });
  document.addEventListener('input',event=>{
    if(event.target.dataset?.setting){beginDraft()[event.target.dataset.setting]=event.target.value;$('#settings-result').textContent='Unsaved changes. Choose Save settings to apply them to comparisons.';return;}
    if(event.target.id!=='search')return;
    const q=event.target.value;cancelSearch();debounce=window.setTimeout(async()=>{
      const focused=document.activeElement?.id==='search',outcome=await navigate({q,conversation:''},{replace:true,focus:false});
      if(focused&&outcome==='accepted'&&!$('#shortcuts').open)$('#search')?.focus();
    },250);
  });
  document.addEventListener('keydown',async event=>{
    if(event.key==='Escape'){const menu=event.target.closest('[data-filter-menu], .project-path');if(menu){menu.open=false;menu.querySelector('summary').focus();return;}}
    if($('#shortcuts').open||event.target.closest('input,textarea,select'))return;
    if(event.key==='/'&&!event.ctrlKey&&!event.metaKey){event.preventDefault();const outcome=await navigate({view:'explore',conversation:''},{focus:false});if(outcome==='accepted')$('#search')?.focus();}
    if(event.key==='?'){event.preventDefault();$('#shortcuts').showModal();}
    if(event.key==='Escape'&&state.view==='detail'){event.preventDefault();return back();}
    if(['Enter',' '].includes(event.key)&&event.target.matches('g[role=button]')){event.preventDefault();event.target.dispatchEvent(new window.MouseEvent('click',{bubbles:true}));}
  });
  window.addEventListener('popstate',async event=>{
    cancelSearch();const saved=event.state?.usageHub===1?event.state:null;
    state=saved?structuredClone(saved.state):readLocation(location);navigation=saved?structuredClone(saved.navigation):null;parent=saved?structuredClone(saved.parent):null;pages=saved?structuredClone(saved.pages??{}):pagesFromLocation(location);
    await load({restore:saved});
  });
  window.addEventListener('resize',()=>{if(bundle?.overview&&['overview','explore'].includes(state.view))drawLocalChart(document,bundle,state);});
  const ready=(async()=>{
    try{
      await client.authenticate({location,history});state=readLocation(location);
      const saved=history.state?.usageHub===1?history.state:null;
      if(saved&&hash(saved.state)===hash(state)){pages=structuredClone(saved.pages??pages);parent=structuredClone(saved.parent);}
      return await load({restore:saved,focusView:false});
    }catch(error){content.setAttribute('aria-busy','false');content.innerHTML=`<section class="panel"><h1>Open Usage Hub through the application</h1><p>${escape(error.message)}</p><p>This page requires an authenticated local launch. Reopen the dashboard from Usage Tray.</p></section>`;return 'failed';}
  })();
  return {ready,navigate,get snapshot(){return snapshot();},get accepted(){return bundle?structuredClone(bundle):null;},dispose(){freshness.dispose();cancelSearch();session.cancel();jobAbort?.abort();operation++;sequence++;}};
}

if(globalThis.document&&globalThis.window)mountLocalDashboard();
