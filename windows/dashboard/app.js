import {formatTokens, chartScale, formatMoney, formatDifference} from './format.js';
const $ = (selector) => document.querySelector(selector);
const content = $('#content');
const escape = (value) => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
// Display-only projection. Attributes/filter/copy identities keep the exact source string.
const displayText = (value) => String(value ?? '').replace(/[\p{C}\u2028\u2029]/gu, c => {
  const point=c.codePointAt(0);
  return '\\'+(point>0xffff?'U':'u')+point.toString(16).padStart(point>0xffff?8:4,'0');
});
const displayLabel = (value) => escape(displayText(value));
const state = {view:'overview',provider:'both',period:'month',metric:'value',page:1,q:'',project:'',model:'',effort:'',day:'',conversation:'',table:'conversations'};
let data, publishedState, retryState, requestNumber = 0, controller, debounce, backLocation, rescanPending=false;
const scrollPositions = new Map();

const money = formatMoney;
const dollars = (summary) => summary.value.amount_usd === null ? 'Unavailable' : `$${money(summary.value.amount_usd)}${summary.value.state==='partial'?' + unpriced':''}`;
const date = (value, options={month:'short',day:'numeric'}) => new Intl.DateTimeFormat('en-US',{timeZone:data?.range.timezone || 'America/Los_Angeles',...options}).format(new Date(value*1000));
const button = (text, action, attributes='') => `<button data-action="${action}" ${attributes}>${escape(text)}</button>`;
function notify(text){$('#notification').textContent=text;clearTimeout(notify.timer);notify.timer=setTimeout(()=>{$('#notification').textContent='';},5000);}
function focusSearch(outcome){if(outcome!=='superseded'&&!$('#shortcuts').open)$('#search')?.focus();}

function urlState(){
  const params=new URLSearchParams();
  for(const [key,value] of Object.entries(state)) if(value && value!==({page:1,provider:'both',period:'month',metric:'value',table:'conversations'}[key])) params.set(key,String(value));
  return '#' + params.toString();
}
function fromLocation(){
  const raw=location.hash.slice(1);
  const params=new URLSearchParams(raw.includes('=')?raw:`view=${raw || 'overview'}`);
  Object.assign(state,{view:'overview',provider:'both',period:'month',metric:'value',page:1,q:'',project:'',model:'',effort:'',day:'',conversation:'',table:'conversations'});
  for(const key of Object.keys(state)) if(params.has(key)) state[key]=key==='page'?Number(params.get(key)):params.get(key);
  if(!['overview','explore','detail','limits','settings'].includes(state.view)) state.view='overview';
  if(!['value','tokens'].includes(state.metric)) state.metric='value';
}
async function navigate(changes, {replace=false, focus=true}={}){
  clearTimeout(debounce);
  scrollPositions.set(location.hash,window.scrollY);
  Object.assign(state,changes);
  history[replace?'replaceState':'pushState']({},'',urlState());
  const outcome=await load();
  if(focus&&outcome!=='superseded'&&!$('#shortcuts').open){window.scrollTo(0,0);content.focus({preventScroll:true});}
  return outcome;
}
function queryParams(includeRevision=true){
  const params=new URLSearchParams({provider:state.provider,period:state.period,page:String(state.page)});
  for(const key of ['q','project','model','effort','day','conversation']) if(state[key]) params.set(key,state[key]);
  if(includeRevision&&data?.usage_revision) params.set('revision',data.usage_revision);
  return params;
}
async function api(path, options={}){
  const response=await fetch(path,{...options,headers:{'X-Usage-Hub':'1'},credentials:'same-origin'});
  const payload=await response.json();
  if(!response.ok) throw Object.assign(new Error(payload.error || 'request_failed'),{status:response.status});
  return payload;
}
async function load({includeRevision=true}={}){
  const current=++requestNumber;
  const requestedState={...state};
  controller?.abort();controller=new AbortController();
  content.setAttribute('aria-busy','true');
  if(!data){$('#breadcrumb').textContent='Loading usage';$('#scope').textContent='No snapshot loaded';}
  content.innerHTML='<p class="loading">Reading matching usage…</p>';
  notify('Reading matching usage…');
  try{
    let result;
    try{result=await api('/api/preview/query?'+queryParams(includeRevision),{signal:controller.signal});}
    catch(error){
      if(current!==requestNumber)return 'superseded';
      // One fresh-revision retry per request. Keep the accepted result until a
      // replacement is actually available, including when this retry fails.
      if(error.status!==409||!includeRevision)throw error;
      result=await api('/api/preview/query?'+queryParams(false),{signal:controller.signal});
    }
    if(current!==requestNumber)return 'superseded';
    data=result;publishedState=requestedState;retryState=null;render();notify('Usage view updated.');
    return 'success';
  }catch(error){
    if(error.name==='AbortError'||current!==requestNumber)return 'superseded';
    retryState=requestedState;
    if(data&&publishedState){
      Object.assign(state,publishedState);history.replaceState({},'',urlState());render();
      content.insertAdjacentHTML('afterbegin',`<section class="banner" role="status"><p>Could not apply the requested filters or view. The previous query result is still displayed, with its original filters.</p>${button('Retry requested view','retry')}</section>`);
      notify('Could not update this view. The previous result and its filters are restored.');
    }else{
      $('#breadcrumb').textContent='Usage unavailable';$('#connection').textContent='Snapshot unavailable';$('#capture').textContent='No successful query';
      content.innerHTML=`<section class="panel"><h1>Usage is unavailable</h1><p>The local snapshot could not be read. Retry this query or check the dashboard terminal and approved source folders.</p>${button('Try again','retry')}</section>`;
      notify('Usage is unavailable. Retry this query.');
    }
    return 'failed';
  }finally{if(current===requestNumber)content.setAttribute('aria-busy','false');}
}
function providerFilters(){return `<div class="filters" aria-label="Provider">${['both','codex','claude'].map(p=>button(p==='both'?'Both agents':p==='codex'?'Codex':'Claude','provider',`data-value="${p}" aria-pressed="${state.provider===p}"`)).join('')}</div>`;}
function heading(title, subtitle, period=true){return `<div class="page-heading"><div><h1>${displayLabel(title)}</h1><p>${displayLabel(subtitle)}</p></div>${period?`<select id="period" aria-label="Report period">${[['month','Month to date'],['today','Today'],['week','Last 7 days']].map(([v,l])=>`<option value="${v}" ${state.period===v?'selected':''}>${l}</option>`).join('')}</select>`:''}</div>`;}
function cards(summary,detail=false){return `<div class="cards ${detail?'detail-cards':''}"><section class="card"><small>${summary.value.state==='partial'?'Priced subtotal':'Estimated API value'}</small><div class="metric">${summary.value.amount_usd===null?'Unavailable':`<span class="currency">USD</span>${money(summary.value.amount_usd)}`}</div></section><section class="card"><small>Recorded tokens</small><div class="metric" title="${escape(summary.tokens.total_tokens)} exact tokens">${formatTokens(summary.tokens.total_tokens)}</div></section>${detail?'':`<section class="card"><small>Conversations</small><div class="metric">${summary.conversation_count.toLocaleString()}</div></section><section class="card"><small>Projects</small><div class="metric">${summary.project_count.toLocaleString()}</div></section>`}</div>`;}
function quality(){
  const issues=[...data.issues];
  if(data.summary.value.state==='empty')issues.push('No recorded activity was found for these filters. This does not establish zero account usage.');
  if(['unpriced','partial'].includes(data.summary.value.state))issues.push(`${data.summary.value.unpriced_records} records / ${formatTokens(data.summary.value.unpriced_tokens)} tokens have no configured price.`);
  return issues.length?`<section class="banner" aria-label="Data quality">${issues.map(issue=>`<p>${displayLabel(issue)}</p>`).join('')}</section>`:'';
}
function comparisons(){
  if(!data.comparisons.length)return '<p class="note">Monthly fee comparison is available for unfiltered month-to-date usage.</p>';
  return `<div class="comparison">${data.comparisons.map(c=>`<span>${displayLabel(c.provider)} · ${c.fee_usd===null?'Monthly fee unavailable':`$${money(c.fee_usd,2)} monthly fee`} · <span class="number">${c.difference_usd===null?'comparison unavailable':`${formatDifference(c.difference_usd)} vs fee${c.state==='partial'?' (priced subtotal only)':''}`}</span></span>`).join('')}</div>`;
}
function capacity(){return `<h2>Capacity right now</h2><p class="note">Active CLI accounts · separate from report scope</p>${data.limits.map(limit=>`<div class="capacity-item"><p class="value ${limit.provider==='Claude'?'rust':'teal'}">${displayLabel(limit.provider)} &nbsp; ${limit.remaining===null||limit.remaining===undefined?'Unavailable':`${Math.round(limit.remaining)}% left`}</p><p class="note">${displayLabel(limit.note || limit.state)}</p></div>`).join('')}<div class="actions">${button('View reset times →','view','data-value="limits"')}</div>`;}
function overview(){return `${heading('Usage overview',data.dataset==='demo'?'Usage recorded on this computer · demo fixture v2':'Available local usage · all unmatched accounts')}${providerFilters()}${cards(data.summary)}${comparisons()}<p class="note">${data.dataset==='demo'?'Estimates at sample API rates':'Estimated API-equivalent value at configured rates'} · local logs across unmatched accounts · not a bill</p>${quality()}<div class="actions">${button('Explore matching records →','view','data-value="explore"')}${button('All live limits →','view','data-value="limits"')}${button('Clear filters','clear')}</div><div class="analysis"><section class="panel chart-panel"><h2>Daily usage</h2><div class="tabs" aria-label="Chart metric">${button('API value · USD','metric',`data-value="value" aria-pressed="${state.metric==='value'}"`)}${button('Recorded tokens','metric',`data-value="tokens" aria-pressed="${state.metric==='tokens'}"`)}</div><p class="note">Select a day to filter Explore · ${escape(data.range.timezone)}</p><p class="chart-unit">${state.metric==='tokens'?'Recorded tokens':'API value · USD'}</p><svg class="chart" id="chart" role="group" aria-label="Daily usage chart"></svg><p class="chart-caption">Zero-based scale adapts to metric and filters</p></section><section class="panel">${capacity()}</section><section class="panel"><h2>Where the value goes</h2><p class="note">MODEL / EFFORT &nbsp; · &nbsp; TOKENS · USD</p><div class="model-list">${data.models.map(m=>`<button class="model-row" data-action="model-group" data-model="${escape(m.model)}" data-effort="${escape(m.effort)}" data-provider="${m.provider.toLowerCase()}"><span>${displayLabel(m.model)} · ${displayLabel(m.effort)}</span><small class="mono">${formatTokens(m.tokens.total_tokens)}</small><small>${displayLabel(m.provider)}</small><span class="number">${escape(dollars(m))}</span></button>`).join('')||'<p class="empty">No matching model usage</p>'}</div></section><section class="panel"><h2>Projects in this query</h2>${data.projects.map(p=>`<button class="project-row" data-action="project" data-value="${escape(p.project)}"><span>${displayLabel(p.project.split(/[\\/]/).filter(Boolean).at(-1)||p.project)}</span><span class="number">${escape(dollars(p))}</span></button>`).join('')||'<p class="empty">No matching projects</p>'}<div class="actions">${button('Explore projects →','projects')}</div></section></div>${footerNote()}`;}
function footerNote(){return `<p class="note">${data.dataset==='demo'?'DEMO DATA · ':'Local metadata · '}${escape(data.pricing.tier_policy)} Reasoning is included in output.</p>`;}
function selector(key,label){return `<select id="${key}" aria-label="${label}"><option value="">${label}: all</option>${data.facets[key].map(v=>`<option value="${escape(v)}" ${state[key]===v?'selected':''}>${displayLabel(v)}</option>`).join('')}</select>`;}
function explore(){
  const rows=data.conversations.map(c=>`<tr><td><button data-action="detail" data-id="${c.id}">${displayLabel(c.project.split(/[\\/]/).filter(Boolean).at(-1)||c.project)} / ${displayLabel(c.session)}</button></td><td><small>${displayLabel(c.provider)}</small></td><td><small class="mono">${displayLabel(c.models.join(', '))}</small></td><td><small>${displayLabel(c.efforts.join(', '))}</small></td><td class="number" title="${c.tokens.total_tokens}">${formatTokens(c.tokens.total_tokens)}</td><td class="number teal">${escape(dollars(c))}</td><td class="number muted">${date(c.last_at)}</td></tr>`).join('');
  return `${heading('Explore usage','Locate projects and conversations in this snapshot')}${providerFilters()}<section class="panel search-panel"><input id="search" type="search" aria-label="Search project paths or conversation IDs" placeholder="Search project paths or conversation IDs…" value="${escape(state.q)}" maxlength="512"><div class="search-row">${selector('project','Project')}${selector('model','Model')}${selector('effort','Effort')}</div><div class="actions">${button('Clear filters','clear')}${state.day?button('Day: '+state.day+' ×','clear-day'):''}</div></section>${quality()}<p class="note"><span class="teal mono">${data.summary.conversation_count}</span> conversations · <span class="teal mono">${data.summary.project_count}</span> projects · USD <span class="teal mono">${money(data.summary.value.amount_usd)}</span></p><div class="tabs">${button('Conversations','table',`data-value="conversations" aria-pressed="${state.table==='conversations'}"`)}${button('Projects','table',`data-value="projects" aria-pressed="${state.table==='projects'}"`)}</div>${state.table==='projects'?`<section class="panel"><h2>Projects in this query</h2>${data.projects.map(p=>`<button class="project-row" data-action="project" data-value="${escape(p.project)}"><span>${displayLabel(p.project)}</span><span class="number">${formatTokens(p.tokens.total_tokens)} · ${escape(dollars(p))}</span></button>`).join('')||'<p class="empty">No matching projects</p>'}</section>`:`<div class="table-scroll"><table><thead><tr><th>Project / conversation</th><th>Agent</th><th>Model</th><th>Effort</th><th class="number">Tokens</th><th class="number">API value</th><th class="number">Last usage</th></tr></thead><tbody>${rows||'<tr><td colspan="7" class="empty">No matching conversations. Clear filters to explore this snapshot.</td></tr>'}</tbody></table><div class="pagination">${button('← Previous','page',`data-value="${data.page-1}" ${data.page<=1?'disabled':''}`)}${button('Next page →','page',`data-value="${data.page+1}" ${data.page>=data.page_count?'disabled':''}`)}<span class="note">Page ${data.page} of ${data.page_count}</span></div></div>`}${footerNote()}`;
}
function detail(){
  const c=data.detail;
  if(!c)return '<section class="panel"><h1>Conversation unavailable</h1><p>Return to matching results and choose a conversation.</p>'+button('Back to results','back')+'</section>';
  const labels={'uncached_input_tokens':'Uncached input','cache_read_tokens':'Cache reads','output_tokens':'Output · includes reasoning','cache_write_5m_tokens':'Cache writes · 5 minutes','cache_write_1h_tokens':'Cache writes · 1 hour'};
  return `<div class="actions">${button('← Back to results','back')}</div>${heading(c.project.split(/[\\/]/).filter(Boolean).at(-1)||c.project,`${c.provider} · ${c.models.join(', ')} · ${c.efforts.join(', ')}`,false)}${cards(c,true)}<section class="panel"><h2>Token breakdown · counted once</h2><dl class="breakdown">${Object.entries(labels).map(([k,l])=>`<dt>${l}</dt><dd title="${escape(c.tokens[k])} exact tokens">${formatTokens(c.tokens[k])}</dd>`).join('')}<dt>Reasoning · subset of output</dt><dd>${formatTokens(c.reasoning_tokens)}${c.reasoning_records<c.record_count?' · partial coverage':''}</dd></dl><p class="note">${escape(data.pricing.tier_policy)}</p></section><section class="panel metadata"><h2>Recorded conversation metadata</h2><p class="mono">${displayLabel(c.session)}</p><p>${displayLabel(c.project)}</p><p class="note">First ${date(c.first_at,{dateStyle:'medium',timeStyle:'short'})} · last ${date(c.last_at,{dateStyle:'medium',timeStyle:'short'})}</p>${button('Copy conversation ID','copy',`data-value="${escape(c.session)}"`)}</section><section class="panel"><h2>${c.record_count} accepted usage ${c.record_count===1?'event':'events'}</h2><div class="table-scroll"><table><thead><tr><th>Time</th><th>Model / effort</th><th class="number">Tokens</th><th class="number">API value</th></tr></thead><tbody>${c.events.map(e=>`<tr><td>${date(e.timestamp,{dateStyle:'short',timeStyle:'short'})}</td><td>${displayLabel(e.model)} / ${displayLabel(e.effort)}</td><td class="number">${formatTokens(e.tokens.total_tokens)}</td><td class="number teal">${escape(dollars(e))}</td></tr>`).join('')}</tbody></table></div><p class="note">Metadata only · prompts and responses are excluded.</p></section>${footerNote()}`;
}
function limits(){return `${heading('Live limits','See available capacity from the tray’s cached provider readings.',false)}<section class="panel"><h2>Live limits follow your active CLI accounts</h2><p class="note">Local reports may include other accounts. Quota percentages cannot be converted into token counts or dollars.</p></section><div class="analysis">${data.limits.map(limit=>`<section class="panel"><h2 class="${limit.provider==='Claude'?'rust':'teal'}">${displayLabel(limit.provider)}</h2><p class="note">${displayLabel(limit.state)} · ${displayLabel(limit.note || '')}</p>${limit.state==='demo'?`<h3>Sample remaining capacity</h3><p class="metric ${limit.provider==='Claude'?'rust':'teal'}">${limit.remaining}%</p><progress class="progress" value="${limit.remaining}" max="100" aria-label="${limit.provider} sample remaining capacity"></progress>`:(limit.snapshot?.windows||[]).map(w=>`<h3>${displayLabel(w.label)}</h3><p class="metric">${Math.round(w.remaining)}%</p><progress class="progress" value="${w.remaining}" max="100" aria-label="${displayLabel(w.label)} remaining"></progress><p class="note">${w.resets_at?`Resets ${date(w.resets_at,{dateStyle:'medium',timeStyle:'short'})}`:'Reset time unavailable'}</p>`).join('')}${limit.snapshot?`<p class="note">Last successful check ${date(limit.snapshot.checked_at,{dateStyle:'medium',timeStyle:'short'})}</p>`:''}<div class="actions">${button('View recorded usage →','provider-explore',`data-value="${limit.provider.toLowerCase()}"`)}</div></section>`).join('')}</div><p class="note">Navigation and local rescans do not poll providers. Tray refresh retains independent cooldown and backoff.</p>`;}
function settings(){return `${heading('Settings & data','Current configuration · read-only during the dashboard integration preview',false)}<section class="panel"><h2>Monthly plan fees · USD</h2>${Object.entries(data.settings.fees_usd).map(([p,v])=>`<div class="settings-row"><span>${escape(p)}</span><strong class="number">${v===null?'Unavailable':`$${money(v,2)} / month`}</strong></div>`).join('')}<p class="note">Fees come from the launch configuration. Persistent editing will connect to the core settings service; no browser-only settings are saved.</p></section><section class="panel metadata"><h2>Local connections</h2>${data.dataset==='demo'?'<p class="amber">Demo mode · no local logs or credentials were read.</p>':Object.entries(data.settings.roots).map(([p,roots])=>`<p>${escape(p)} · <span class="mono">${displayLabel(roots.join(' + '))}</span></p>`).join('')}<p class="note">Usage: available local logs across unmatched accounts. Limits: active CLI accounts. Browser chats, other devices, and missing local records are outside coverage.</p></section><section class="panel"><h2>Display & privacy</h2><p>Dark · Compact · ${escape(data.settings.timezone)}</p><p class="note">Exact token counts remain in the core. Display uses M and B, with thousands shown as comma-separated numbers.</p><div class="actions">${button('Keyboard shortcuts ?','help')}</div></section>${footerNote()}`;}
function render(){
  const labels={overview:'Usage overview',explore:'Explore usage',detail:'Conversation detail',limits:'Live limits',settings:'Settings & data'};
  $('#breadcrumb').textContent=labels[state.view];
  for(const link of document.querySelectorAll('[data-nav]')){
    const active=link.dataset.nav===(state.view==='detail'?'explore':state.view);
    link.href='#view='+link.dataset.nav;link.removeAttribute('aria-current');
    if(active)link.setAttribute('aria-current','page');
    link.querySelector('img').src='/assets/'+(link.dataset.nav==='overview'?(active?'overview':'overview-muted'):link.dataset.nav+(active?'-active':''))+'.svg';
  }
  $('#mode').textContent=data.dataset==='demo'?'DEMO DATA':'LOCAL DATA';
  $('#scope').textContent=data.dataset==='demo'?'Preview · sample data':'Preview · local metadata';
  $('#connection').textContent=data.dataset==='demo'?'2 sample providers':`${data.quality==='available'?'Local snapshot ready':data.quality==='stale'?'Previous snapshot · stale':'Partial local snapshot'}`;
  $('#capture').textContent='Captured '+date(data.captured_at,{hour:'2-digit',minute:'2-digit'});
  content.innerHTML=({overview,explore,detail,limits,settings}[state.view])();
  if(state.view==='overview')drawChart();
}
function svg(tag,attributes={},text){const node=document.createElementNS('http://www.w3.org/2000/svg',tag);for(const [key,value]of Object.entries(attributes))node.setAttribute(key,String(value));if(text!==undefined)node.textContent=text;return node;}
function drawChart(){
  const chart=$('#chart');if(!chart)return;
  const w=Math.max(280,chart.clientWidth||620),h=250,left=65,right=12,top=14,bottom=38,plotH=h-top-bottom;
  chart.replaceChildren();
  chart.setAttribute('viewBox',`0 0 ${w} ${h}`);
  const values=data.days.map(d=>state.metric==='tokens'?Number(d.tokens.total_tokens):d.value.amount_usd===null?null:Number(d.value.amount_usd));
  const axisMax=state.metric==='tokens'?Math.max(5,chartScale(Math.max(0,...values.map(v=>v??0)))):chartScale(Math.max(0,...values.map(v=>v??0)));
  for(let i=0;i<=5;i++){
    const y=top+plotH-i*plotH/5,value=axisMax*i/5;
    chart.append(svg('line',{x1:left,y1:y,x2:w-right,y2:y}));
    const usdDigits=value===0?0:Math.max(0,Math.min(12,-Math.floor(Math.log10(axisMax/5))));
    // Axis ticks describe approximate geometry; actual USD labels/tooltips use
    // the exact decimal-string formatter, never this numeric tick path.
    chart.append(svg('text',{x:left-10,y:y+4,'text-anchor':'end'},state.metric==='tokens'?formatTokens(BigInt(Math.round(value))):'$'+value.toLocaleString('en-US',{minimumFractionDigits:usdDigits,maximumFractionDigits:usdDigits})));
  }
  if(!data.days.length){chart.append(svg('text',{x:w/2,y:h/2,'text-anchor':'middle'},'No matching recorded activity'));return;}
  const width=(w-left-right)/data.days.length;
  data.days.forEach((day,i)=>{
    const value=values[i],height=value===null?0:plotH*value/axisMax;
    const label=`${day.day}: ${state.metric==='tokens'?`${formatTokens(day.tokens.total_tokens)} tokens (${day.tokens.total_tokens} exact)`:dollars(day)}. Open matching conversations.`;
    const group=svg('g',{role:'button',tabindex:0,'aria-label':label,'data-action':'day','data-value':day.day});
    group.append(svg('title',{},label));
    if(height>0)group.append(svg('rect',{x:left+i*width+width*.2,y:top+plotH-height,width:width*.6,height,rx:2}));
    group.append(svg('text',{x:left+(i+.5)*width,y:h-14,'text-anchor':'middle'},day.day.slice(-2).replace(/^0/,'')));
    chart.append(group);
  });
}
document.addEventListener('click',async event=>{
  const nav=event.target.closest('[data-nav]');
  if(nav){event.preventDefault();return navigate({view:nav.dataset.nav,conversation:''});}
  const target=event.target.closest('[data-action]');if(!target)return;
  const {action,value,id,model,effort,provider}=target.dataset;
  if(action==='help')return $('#shortcuts').showModal();
  if(action==='close-help')return $('#shortcuts').close();
  if(action==='retry')return navigate(retryState||{},{replace:true});
  if(action==='search'){const outcome=await navigate({view:'explore',conversation:''},{focus:false});focusSearch(outcome);return;}
  if(action==='copy'){try{await navigator.clipboard.writeText(value);notify('Conversation ID copied');}catch{notify('Copy unavailable. Select the conversation ID above to copy it.');}return;}
  if(action==='refresh'){
    if(rescanPending)return;
    clearTimeout(debounce);
    rescanPending=true;target.disabled=true;
    try{const result=await api('/api/preview/rescan',{method:'POST'});if(result.state==='complete'){const outcome=await load({includeRevision:false});if(outcome==='success')notify('Local snapshot refreshed');}else notify(result.state==='cooldown'?'Wait five seconds between local rescans.':'A local rescan is already running.');}
    catch{notify('Rescan failed. The previous snapshot is retained.');await load();}
    finally{rescanPending=false;target.disabled=false;}return;
  }
  if(action==='metric'){state.metric=value;publishedState={...state};history.replaceState({},'',urlState());render();return;}
  if(action==='provider')return navigate({provider:value,page:1,conversation:''});
  if(action==='provider-explore')return navigate({provider:value,view:'explore',page:1,conversation:''});
  if(action==='view')return navigate({view:value,conversation:''});
  if(action==='table')return navigate({table:value,conversation:''});
  if(action==='projects')return navigate({view:'explore',table:'projects',conversation:''});
  if(action==='project')return navigate({view:'explore',project:value,table:'conversations',page:1,conversation:''});
  if(action==='model-group')return navigate({view:'explore',model,effort,provider,page:1,conversation:''});
  if(action==='day')return navigate({view:'explore',day:value,page:1,conversation:''});
  if(action==='clear-day')return navigate({day:'',page:1});
  if(action==='clear')return navigate({project:'',model:'',effort:'',q:'',day:'',page:1,conversation:''});
  if(action==='page')return navigate({page:Number(value)});
  if(action==='detail'){backLocation=location.hash;return navigate({view:'detail',conversation:id});}
  if(action==='back'){if(backLocation){history.back();}else return navigate({view:'explore',conversation:''});}
});
document.addEventListener('change',event=>{if(['period','project','model','effort'].includes(event.target.id))navigate({[event.target.id]:event.target.value,page:1,conversation:''});});
document.addEventListener('input',event=>{if(event.target.id!=='search')return;const value=event.target.value;clearTimeout(debounce);debounce=setTimeout(async()=>{const focus=document.activeElement?.id==='search';const outcome=await navigate({q:value,page:1},{replace:true,focus:false});if(focus)focusSearch(outcome);},250);});
document.addEventListener('keydown',async event=>{
  if($('#shortcuts').open)return; // The native dialog owns Escape and focus while open.
  if(event.target.closest('input,textarea,select'))return;
  if(event.key==='/'&&!event.ctrlKey&&!event.metaKey){event.preventDefault();const outcome=await navigate({view:'explore',conversation:''},{focus:false});focusSearch(outcome);}
  if(event.key==='?'){event.preventDefault();if(!$('#shortcuts').open)$('#shortcuts').showModal();}
  if(event.key==='Escape'&&!$('#shortcuts').open&&state.view==='detail'){event.preventDefault();if(backLocation)history.back();else navigate({view:'explore',conversation:''});}
  if(['Enter',' '].includes(event.key)&&event.target.matches('g[role=button]')){event.preventDefault();event.target.dispatchEvent(new MouseEvent('click',{bubbles:true}));}
});
addEventListener('popstate',async()=>{clearTimeout(debounce);fromLocation();const outcome=await load();if(outcome!=='superseded'&&!$('#shortcuts').open){window.scrollTo(0,scrollPositions.get(location.hash)||0);content.focus({preventScroll:true});}});
addEventListener('resize',()=>{if(data&&state.view==='overview')drawChart();});
fromLocation();load();
