import {selectionValues} from './local-session.js';
import {renderPie,renderMethodology} from './local-analysis-view.js';
import {formatTokens,formatMoney,formatDifference,chartScale,formatEstimate,formatCredits,formatUsd,formatAverageTokens,formatAverageCredits} from './format.js';

export const escape=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const text=value=>escape(String(value??'').replace(/[\p{C}\u2028\u2029]/gu,c=>'\\'+(c.codePointAt(0)>0xffff?'U':'u')+c.codePointAt(0).toString(16).padStart(c.codePointAt(0)>0xffff?8:4,'0')));
export const button=(label,action,attrs='')=>`<button data-action="${action}" ${attrs}>${escape(label)}</button>`;
const date=(instant,zone)=>instant===null?'Not recorded':new Intl.DateTimeFormat('en-US',{timeZone:zone??'UTC',year:'numeric',month:'short',day:'numeric',hour:'numeric',minute:'2-digit',timeZoneName:'short'}).format(new Date(instant));
const usd=s=>s.value.amount_usd===null?(s.value.state==='empty'?'No recorded activity':'Unavailable'):`$${formatUsd(s.value.amount_usd)}${s.value.state==='partial'?' + unpriced':''}`;
const note='<p class="note">Local logs across unmatched accounts · API-equivalent estimates, not bills or realized savings. Reasoning is included in output. Prompts and responses are excluded.</p>';
const panel=(heading,body)=>`<section class="panel">${heading?`<h2>${text(heading)}</h2>`:''}${body}</section>`;
const periodSelector=state=>`<select id="period" aria-label="Report period">${[['month','Month to date'],['today','Today'],['week','Last 7 days']].map(([v,l])=>`<option value="${v}" ${state.period===v?'selected':''}>${l}</option>`).join('')}</select>`;
function heading(title){return `<div class="page-heading"><div><h1>${text(title)}</h1></div></div>`;}

const providers=state=>`<div class="filters" aria-label="Provider">${(state.view==='explore'?['codex','claude']:['both','codex','claude']).map(p=>button(p==='both'?'Both agents':p==='codex'?'Codex':'Claude','provider',`data-value="${p}" aria-pressed="${state.provider===p}"`)).join('')}</div>`;
const exactAmount=(amount,label='Exact API value')=>amount===null?'':`<details class="precision"><summary>${text(label)}</summary><p>USD ${text(amount)}</p></details>`;
function legacyCards(s,detail=false){return `<div class="cards ${detail?'detail-cards':''}"><section class="card"><small>${s.value.state==='partial'?'Priced subtotal':'Estimated API value'}</small><div class="metric">${s.value.amount_usd===null?(s.value.state==='empty'?'No activity':'Unavailable'):`<span class="currency">USD</span>${formatMoney(s.value.amount_usd,2)}`}</div>${exactAmount(s.value.amount_usd,s.value.state==='partial'?'Exact priced subtotal':'Exact API value')}</section><section class="card"><small>Recorded tokens</small><div class="metric" title="${escape(s.tokens.total_tokens)} exact tokens">${formatTokens(s.tokens.total_tokens)}</div></section>${detail?'':`<section class="card"><small>Conversations</small><div class="metric">${s.conversation_count.toLocaleString()}</div></section><section class="card"><small>Projects</small><div class="metric">${s.project_count.toLocaleString()}</div></section>`}</div>`;}
const readable=value=>String(value).replaceAll("_"," ");
function quality(bundle,s,collapsed=false){
  const issues=[],essential=[];
  if(s.value.state==='empty')issues.push('No recorded activity matches these filters. This does not establish zero account usage.');
  if(['partial','unpriced'].includes(s.value.state))issues.push(`Unpriced: ${s.value.unpriced_records} ${s.value.unpriced_records===1?'record':'records'} · ${formatTokens(s.value.unpriced_tokens)} tokens. ${s.value.state==='partial'?'The headline is the priced subtotal.':'API value is unavailable.'}`);
  if(bundle.overview?.data.freshness==='stale')issues.push('Retained local usage is stale. Missing or unreadable sources have not erased accepted history.');
  essential.push(...issues);
  if(s.value.assumptions.length){
    essential.push('Pricing uses assumptions; see Data details.');
    issues.push('Pricing assumptions: '+s.value.assumptions.map(readable).join(', '));
  }
  for(const c of bundle.overview?.data.coverage??[]){
    if(c.state!=='complete'){
      const warning=`${c.provider} ingestion coverage: ${c.state}. Excluded token amounts are unknown.`;
      essential.push(warning);issues.push(warning);
    }
    for(const [code,count]of Object.entries(c.ingestion_issues))issues.push(`${c.provider} report ingestion · ${readable(code)}: ${count}`);
    if(['counter_reset','cache_exceeds_input','partial_counter_metadata','baseline_reestablished','ambiguous_sequence','fork_boundary_conflict','unplaced_observation'].some(code=>c.accounting_issues[code]>0))essential.push(`${c.provider}: some usage intervals could not be counted reliably. Excluded token amounts are unknown; see Data details.`);
    for(const [code,count]of Object.entries(c.accounting_issues))issues.push(`${c.provider} report counter quality · ${readable(code)}: ${count}`);
  }
  if(s.app_credits)essential.push('1 app credit = USD0.01 · Standard API list-price equivalent · Primary models only. Estimates are not bills or remaining allowance.');
  if(s.value.assumptions.includes('below_threshold_context_assumed')||bundle.overview?.projection?.valuation_policy==='decimal12-below-threshold-v1')essential.push('Below-threshold context assumed · applicable catalog tiers; explicit rate overrides are preserved.');
  if(collapsed)return `<details class="banner quality-details"><summary>Report Log</summary>${[...new Set([...essential,...issues])].map(x=>`<p>${text(x)}</p>`).join('')}</details>`;
  return `${essential.length?`<section class="usage-qualifications" aria-label="Usage qualifications">${essential.map(x=>`<p>${text(x)}</p>`).join('')}</section>`:''}${issues.length?`<details class="banner quality-details"><summary>Data details</summary>${issues.map(x=>`<p>${text(x)}</p>`).join('')}</details>`:''}`;
}
export function renderPublicationStatus(bundle,latest=bundle.status,failed=false){
  const status=latest??bundle.status,s=status.data,view=bundle.overview;
  const changed=view&&['usage_revision','pricing_version','configuration_version'].some(key=>view[key]!==s[key]);
  const lines=[];
  if(changed)lines.push(`<p><strong>New usage or settings available.</strong> ${button('Update view','refresh-query')} Your current filters are kept.</p>`);
  if(s.indexing)lines.push('<p>Local scan or repricing in progress. The displayed usage remains a captured result.</p>');
  if(failed)lines.push('<p>Could not check for newer usage. The last accepted view is retained. Use Update view to retry.</p>');
  return lines.length?`<section class="${changed||failed?'banner':'publication-info'}" aria-label="Usage freshness">${lines.join('')}</section>`:'';
}
export function renderScanStatus(bundle,latest=bundle.status){
  const s=(latest??bundle.status).data,view=bundle.overview;
  const zone=view?.range.timezone??bundle.wire?.data.settings?.timezone_info?.name??bundle.wire?.data.timezone_info?.name??'UTC';
  return `<p class="note">Last successful local scan: ${text(date(s.last_import_completed_at,zone))}${view?` · View captured through: ${text(date(view.range.end_at,zone))}`:''}</p>`;
}
function statusBanner(bundle){
  const s=bundle.status.data,lines=[];
  if(s.configuration_pending)lines.push('Saved configuration is pending. Usage still reflects the last complete active configuration.');
  if(s.configuration_state==='invalid')lines.push('Current local configuration needs recovery. Retained committed usage remains displayed.');
  if(s.indexing)lines.push('Local indexing or repricing is in progress. Refresh after publication to capture the new revision.');
  if(s.last_job?.status==='failed')lines.push('The last local operation failed. The last committed usage is retained.');
  return lines.length?`<section class="banner" role="status">${lines.map(x=>`<p>${text(x)}</p>`).join('')}</section>`:'';
}
function comparisons(d){return `<div class="comparison" aria-label="Monthly fee comparisons">${[...d.comparisons,d.combined_comparison].map(c=>{
  const label=c.provider==='combined'?'Combined':c.provider==='codex'?'Codex':'Claude';
  const value=c.value_usd===null?'Unavailable':`$${formatMoney(c.value_usd,2)}`;
  const fee=c.fee_usd===null?'Unavailable':`$${formatMoney(c.fee_usd,2)}`;
  const difference=c.available?formatDifference(c.difference_usd,2):null;
  const position=c.available?(/[1-9]/.test(c.difference_usd.split(/[eE]/)[0])?(c.difference_usd.startsWith('-')?'Below':'Above'):'Equal to'):null;
  return `<section class="comparison-item"><h2>${text(label)}</h2><p>${c.pricing_state==='partial'?'Priced subtotal':'API value'} <strong>${value}</strong> − full monthly fee <strong>${fee}</strong>${c.available?` = <strong class="comparison-difference">${difference}</strong>`:''}</p><p>${c.available?`${position} the full monthly fee${c.pricing_state==='partial'?' · priced records only; unpriced usage is excluded':''}`:`Comparison unavailable · ${text(readable(c.reason??'unavailable'))}`}</p><details class="precision"><summary>Comparison details</summary>${c.available?`<p>Exact difference: USD ${text(c.difference_usd)}</p>`:''}<p>${c.qualifications.map(v=>text(readable(v))).join(' · ')}</p></details></section>`;
}).join('')}</div>`;}

const categoryLabels={uncached_input_tokens:'Input',output_tokens:'Output',cache_read_tokens:'Cache read',cache_write_5m_tokens:'Cache write 5m',cache_write_1h_tokens:'Cache write 1h'};
const displayUsd=value=>value===null?'Unavailable':`<span title="${escape(value)} exact USD">USD ${text(formatUsd(value))}</span>`;
function rateLine(e){
  if(e.state!=='available')return `Unavailable · ${text(readable(e.reason))}`;
  const rates=e.categories.filter((c,i)=>i<3||c.rate_usd_per_million!==null||c.tokens!=='0');
  return `${text(e.requested_model)} · ${text(readable(e.tier))} · ${rates.map(c=>`${categoryLabels[c.category]} ${c.rate_usd_per_million===null?'unavailable':'$'+text(formatUsd(c.rate_usd_per_million))}`).join(' / ')} · USD per 1M tokens${e.assumptions.length?' · assumptions apply':''}`;
}
function rateEvidence(e,amount,state){
  const source=e.custom?'Custom configuration':e.source??'Source not recorded';
  return `<div class="rate-evidence">${e.state==='available'?`<div class="rate-table-scroll"><table class="rate-table"><caption>Applied category charges · USD per 1M tokens</caption><thead><tr><th>Category</th><th>Exact tokens</th><th>Rate / 1M</th><th>USD value</th></tr></thead><tbody>${e.categories.filter(c=>!c.category.startsWith('cache_write_')||c.tokens!=='0'||c.rate_usd_per_million!==null).map(c=>`<tr><th scope="row">${categoryLabels[c.category]}</th><td class="number">${text(c.tokens)}</td><td class="number">${c.rate_usd_per_million===null?'Unconfigured':displayUsd(c.rate_usd_per_million)}</td><td class="number">${displayUsd(c.unrounded_usd)}</td></tr>`).join('')}</tbody></table></div><p class="note">Category charge = tokens × rate ÷ 1,000,000. Output includes reasoning once. USD amounts and rates display to two decimals; calculations retain full precision. Nonzero sub-cent amounts display as &lt;0.01. Hover USD values for exact amounts.</p>${e.rounding_adjustment_usd===null?'<p class="rate-warning">This usage is unpriced. Known category charges do not establish its total.</p>':`<p>Rounding adjustment: <span class="mono">${displayUsd(e.rounding_adjustment_usd)}</span></p><p class="note">Charges + adjustment = sum of event estimates. Each event is rounded half-even to 12 USD decimal places.</p>`}`:`<p class="rate-warning">${text(readable(e.reason))}. Applied rates could not be verified; no replacement rates are shown.</p>`}<p>${state==='unpriced'?'Estimated value unavailable':'Estimated API value'}: <strong class="mono">${displayUsd(amount)}</strong></p><p class="note">${text(e.requested_model)}${e.matched_model&&e.matched_model!==e.requested_model?` → ${text(e.matched_model)}`:''} · ${text(readable(e.tier??'tier unavailable'))}${e.model_mapping?` · ${text(readable(e.model_mapping))}`:''}</p>${e.assumptions.length?`<p class="rate-warning">Assumptions: ${e.assumptions.map(v=>text(readable(v))).join(' · ')}</p>`:''}<details class="rate-provenance"><summary>Pricing source & version</summary><p>${text(source)}${e.custom&&e.source&&e.source!=='custom configuration'?` · ${text(e.source)}`:''}${e.checked_date?` · checked ${text(e.checked_date)}`:''}</p><dl><dt>Pricing</dt><dd>${text(e.pricing_version)}</dd><dt>Catalog</dt><dd>${text(e.catalog_version)}</dd><dt>Overrides</dt><dd>${text(e.override_version)}</dd><dt>Policy</dt><dd>${text(e.policy_version)}</dd><dt>Rate</dt><dd>${text(e.rate_id??'Unavailable')}</dd></dl></details></div>`;
}
export function renderPricingBreakdown(pricing){
  if(!pricing.total_record_count)return '<p class="note rate-empty">No matched events to explain.</p>';
  const single=pricing.group_count===1;
  const label=single?rateLine(pricing.groups[0].explanation):`Mixed rates · ${pricing.group_count.toLocaleString()} groups · USD per 1M tokens`;
  return `<details class="usage-rates"><summary>Rates · ${label}</summary>${pricing.truncated?`<p class="rate-warning">Showing ${pricing.groups.length} of ${pricing.group_count} rate groups (${pricing.shown_record_count} of ${pricing.total_record_count} records). This preview does not add up to the full total. Open conversation details and page through accepted events for all rates.</p>`:''}${pricing.groups.map(g=>`<section class="rate-group">${!single?`<h3>${rateLine(g.explanation)}</h3>`:''}<p class="note">${g.record_count.toLocaleString()} ${g.record_count===1?'record':'records'} · ${formatTokens(g.tokens.total_tokens)} tokens${g.pricing_state==='unpriced'?' · unpriced':''}</p>${rateEvidence(g.explanation,g.amount_usd,g.pricing_state)}</section>`).join('')}</details>`;
}
export function renderEventPricing(value){
  return `<details class="usage-rates"><summary>Rates · ${rateLine(value.explanation)}</summary>${rateEvidence(value.explanation,value.amount_usd,value.state)}</details>`;
}

function projectRows(rows,withRates=false){return rows.map(p=>`<div class="project-usage"><button class="project-row" data-action="project" data-value="${escape(p.id)}"><span>${text(p.label)}</span><span class="number">${formatTokens(p.summary.tokens.total_tokens)} · ${escape(usd(p.summary))}</span></button>${withRates?renderPricingBreakdown(p.pricing):''}</div>`).join('')||'<p class="empty">No matching projects</p>';}
function overviewProjectRows(rows){
  return rows.map(p=>{
    const name=String(p.label).replace(/[\\/]+$/,'').split(/[\\/]/).pop()||p.label;
    return `<div class="project-usage overview-project"><div class="overview-project-row"><div class="project-heading"><button class="project-name" data-action="project" data-value="${escape(p.id)}">${text(name)}</button><details class="project-path"><summary aria-label="${text('Show full path for '+name)}" title="Show full path"><span aria-hidden="true">ⓘ</span></summary><p class="project-full-path mono">${text(p.label)}</p></details></div><span class="number project-values">${formatTokens(p.summary.tokens.total_tokens)} · ${escape(usd(p.summary))}</span></div></div>`;
  }).join('')||'<p class="empty">No matching projects</p>';
}
function cards(s,detail=false,explore=false){
  if(!s.app_credits)return legacyCards(s,detail);
  const metric=(label,value,note='',extra='')=>`<section class="card"><small>${label}</small><div class="metric">${value}</div>${note?`<p class="note">${note}</p>`:''}${extra}</section>`;
  const price=metric('ESTIMATED API VALUE',s.value.amount_usd===null?(s.value.state==='empty'?'No activity':'Unavailable'):`<span class="currency">USD</span>${escape(formatEstimate(s.value.amount_usd))}`,s.value.state==='partial'?'Priced subtotal':'',exactAmount(s.value.amount_usd));
  const credit=metric('ESTIMATED APP CREDIT',s.app_credits.amount===null?'Unavailable':escape(formatEstimate(s.app_credits.amount,2,true)),'',s.app_credits.amount===null?'':`<details class="precision"><summary>Exact app credits</summary><p>${text(s.app_credits.amount)} app credits</p></details>`);
  const token=metric(explore?'TOTAL TOKENS':'RECORDED TOKENS',`<span title="${escape(s.tokens.total_tokens)} exact tokens">${formatTokens(s.tokens.total_tokens)}</span>`,explore?'All recorded categories':'');
  return `<div class="cards ${explore?'explore-cards':''}">${explore?token+price+credit:price+credit+token+metric(detail?'UNESTIMATED TOKENS':'PROJECTS COUNTED',detail?formatTokens(s.value.unpriced_tokens):s.project_count.toLocaleString())}</div>`;
}
const metricName=s=>s.metric==='tokens'?'Recorded tokens':s.metric==='credits'?'App credits':'API value · USD';
const metricTabs=s=>`<div class="tabs" aria-label="Analysis metric">${[['value','API value · USD'],['credits','App Credit'],['tokens','Recorded tokens']].map(([v,l])=>button(l,'metric',`data-value="${v}" aria-pressed="${s.metric===v}"`)).join('')}</div>`;
function dailyChart(bundle,state,tabs=true){return `<section class="panel chart-panel ${state.view==='explore'?'full-chart':''}"><h2>Daily usage</h2>${tabs?metricTabs(state):''}<p class="chart-unit">${metricName(state)}</p><svg class="chart" id="chart" role="group" aria-label="Daily usage chart"></svg></section>`;}
export function renderCapacityStatus(items,zone,now){
  return `<h2>Capacity right now · 5 hours</h2><p class="note">Active CLI accounts · cached status independent of report dates</p>${items.map(p=>{
    const windows=(p.snapshot?.windows??[]).filter(w=>w.duration_minutes===300);
    return `<div class="capacity-item ${p.provider==='claude'?'claude-capacity':''}"><p class="value">${text(p.provider==='codex'?'Codex':'Claude')} · ${text(p.state)}</p>${windows.length?windows.map(w=>`<p class="capacity-remaining mono">${w.remaining_percent.toLocaleString('en-US',{maximumFractionDigits:2})}% left</p><progress class="progress" max="100" value="${w.remaining_percent}" aria-label="${text(p.provider)} five-hour remaining capacity"></progress><p class="note">${w.resets_at&&Date.parse(w.resets_at)<=Date.parse(now)?'Reset time reached · awaiting refreshed limit':'Resets '+text(date(w.resets_at,zone))}</p>`).join(''):'<p class="note">Five-hour capacity unavailable · no five-hour duration evidence.</p>'}<p class="note">${text(readable(p.category))} · ${text(p.phase)}${p.snapshot?.blocked?' · provider usage blocked':''}<br>Last success: ${text(date(p.last_success_at,zone))}${p.next_eligible_at?'<br>Next eligible: '+text(date(p.next_eligible_at,zone)):''}</p>${p.state==='stale'?'<p class="rate-warning">Last successful reading · stale</p>':''}</div>`;
  }).join('')}${button('All live limits →','view','data-value="limits"')}`;
}
function overview(bundle,state){
  const d=bundle.overview.data;
  const fees=bundle.overview.projection?'':comparisons(d);
  return `${heading('Usage overview','',state)}<div class="overview-filters">${providers(state)}${periodSelector(state)}</div>${cards(d.summary)}${fees}${quality(bundle,d.summary,true)}<div class="actions">${button('Explore matching records →','explore-matching')}${button('Clear filters','clear')}</div><div class="analysis">${dailyChart(bundle,state)}<section class="panel" id="capacity-current">${renderCapacityStatus(bundle.status.data.providers,bundle.overview.range.timezone,bundle.status.generated_at)}</section>${panel('Where the value goes',`<div class="model-list">${d.models.map(m=>`<button class="model-row" data-action="model-group" data-model="${escape(m.model)}" data-effort="${escape(m.effort)}" data-provider="${escape(m.provider)}"><span>${text(m.model)} · ${text(m.effort)}</span><small class="mono">${formatTokens(m.summary.tokens.total_tokens)}</small><small>${text(m.provider)}</small><span class="number">${escape(usd(m.summary))}</span></button>`).join('')||'<p class="empty">No matching model usage</p>'}</div>`)}${panel('Projects in this query',overviewProjectRows(d.top_projects)+button('Explore all projects →','projects'))}</div>`;
}
function selector(key,label,options,value){return `<select id="${key}" aria-label="${label}"><option value="">${label}: all</option>${options.map(o=>`<option value="${escape(o.value)}" ${value===o.value?'selected':''}>${text(o.label)} (${o.record_count})</option>`).join('')}</select>`;}
function multiSelector(key,label,options,value){
  const selected=selectionValues(value),all=value===''||value===undefined;
  const caption=all?'All':selected.length?selected.length+' selected':'None';
  return `<details id="${key}" class="multi-filter" data-filter-menu="${key}"><summary>${label}: ${caption}</summary><div class="filter-menu" role="group" aria-label="${label}"><label class="filter-all"><input type="checkbox" data-filter-all ${all?'checked':''}>Select all</label><div class="filter-options">${options.map(o=>`<label><input type="checkbox" data-filter-option value="${escape(o.value)}" ${all||selected.includes(o.value)?'checked':''}><span>${text(o.label)} <small>(${o.record_count})</small></span></label>`).join('')||'<p class="note">No matching choices.</p>'}</div>${button('Apply','apply-filter')}</div></details>`;
}
function pager(p,navigation,events=false){return `<div class="pagination">${button('← Previous'+(events?' events':''),events?'event-prev':'prev',(events?navigation.eventPrevious:navigation.previous).length?'':'disabled')}${button('Next'+(events?' events':' page')+' →',events?'event-next':'next',p.next_cursor?'':'disabled')}<span class="note">${p.matched_count.toLocaleString()} matching ${events?'events':'rows'} · ${p.page_size} per page</span></div>`;}
function legacyExplore(bundle,state){
  const d=bundle.list.data,f=bundle.facets.data;
  const rows=d.items.map(c=>`<tr><td><button data-action="detail" data-id="${escape(c.id)}">${text(c.label)}</button><p class="note">${c.project_ids.map(id=>text(f.projects.find(p=>p.value===id)?.label??id)).join(' · ')}</p></td><td>${text(c.models.join(', '))}</td><td>${text(c.efforts.join(', '))}</td><td class="number" title="${escape(c.summary.tokens.total_tokens)} exact tokens">${formatTokens(c.summary.tokens.total_tokens)}</td><td class="number teal">${escape(usd(c.summary))}</td><td>${text(date(c.last_activity_at,bundle.overview.range.timezone))}</td></tr><tr class="usage-rate-row"><td colspan="6">${renderPricingBreakdown(c.pricing)}</td></tr>`).join('');
  return `${heading('Explore usage','Full-query totals remain independent of the displayed page',state)}${providers(state)}<section class="panel search-panel"><input id="search" type="search" aria-label="Search usage metadata" placeholder="Search project, conversation, or model metadata…" value="${escape(state.q)}" maxlength="200"><div class="search-row">${selector('project','Project',f.projects,state.project)}${selector('model','Model',f.models,state.model)}${selector('effort','Effort',f.efforts,state.effort)}<select id="sort" aria-label="Sort matching rows">${[['value_desc','API value'],['tokens_desc','Tokens'],['last_activity_desc','Last activity']].map(([v,l])=>`<option value="${v}" ${state.sort===v?'selected':''}>${l}</option>`).join('')}</select><select id="pageSize" aria-label="Rows per page">${[1,25,50,100].map(n=>`<option value="${n}" ${state.pageSize===n?'selected':''}>${n} per page</option>`).join('')}</select></div><div class="actions">${button('Clear filters','clear')}${state.day?button('Day: '+state.day+' ×','clear-day'):''}</div></section>${cards(d.summary)}${quality(bundle,d.summary,true)}<div class="tabs">${button('Conversations','table',`data-value="conversations" aria-pressed="${state.table==='conversations'}"`)}${button('Projects','table',`data-value="projects" aria-pressed="${state.table==='projects'}"`)}</div>${state.table==='projects'?panel('Projects in this query',projectRows(d.items,true)+pager(d.pagination,bundle.navigation)):`<div class="table-scroll"><table><thead><tr><th>Projects / conversation</th><th>Models</th><th>Efforts</th><th class="number">Tokens</th><th class="number">API value</th><th>Last matched usage</th></tr></thead><tbody>${rows||'<tr><td colspan="6" class="empty">No matching conversations. Clear filters to explore retained usage.</td></tr>'}</tbody></table>${pager(d.pagination,bundle.navigation)}</div>`}`;
}
function historyMore(d,nav){
  const shown=Math.min(nav.historyVisible??10,d.items.length),offset=(nav.previous?.length??0)*50,total=d.pagination.matched_count;
  return `<div class="pagination history-controls">${shown<d.items.length?button('Load more','load-more'):''}${(nav.historyVisible??10)>10?button('Load less','load-less'):''}${button('← Previous page','prev',nav.previous?.length?'':'disabled')}${button('Next page →','next',d.pagination.next_cursor?'':'disabled')}<span class="note">${total?`Showing ${offset+1}–${offset+shown}`:'Showing 0'} of ${total.toLocaleString()} matching conversations · page ${(nav.previous?.length??0)+1}</span></div>`;
}
function explore(bundle,state){
  if(!bundle.overview.data.analysis)return legacyExplore(bundle,state);
  const d=bundle.list.data,f=bundle.facets.data,a=bundle.analysis?.data.analysis??bundle.overview.data.analysis;
  const metric=state.metric==='tokens'?'tokens':state.metric==='credits'?'app_credits':'usd';
  const helpers={text,escape,button,renderPricingBreakdown};
  const rows=d.items.slice(0,bundle.navigation.historyVisible??10).map(c=>`<tr><td><button data-action="detail" data-id="${escape(c.id)}">${text(c.label)}</button><p class="note">${c.project_ids.map(id=>text(f.projects.find(p=>p.value===id)?.label??id)).join(' · ')}</p></td><td>${text(c.models.join(', '))}<p class="note">${text(c.efforts.join(', '))}</p></td><td class="number" title="${escape(c.summary.app_credits.amount??'Unavailable')} exact app credits">${escape(c.summary.app_credits.amount===null?'Unavailable':formatEstimate(c.summary.app_credits.amount,3,true))}</td><td class="number teal" title="USD ${escape(c.summary.value.amount_usd??'Unavailable')}">${escape(usd(c.summary))}</td><td class="number" title="${escape(c.summary.tokens.total_tokens)} exact tokens">${formatTokens(c.summary.tokens.total_tokens)}</td><td class="number amber" title="${escape(c.summary.value.unpriced_tokens)} exact unestimated tokens">${formatTokens(c.summary.value.unpriced_tokens)}</td></tr>`).join('');
  return `${heading('Explore usage','',state)}${providers(state)}<section class="panel search-panel"><input id="search" type="search" aria-label="Search usage metadata" placeholder="Search project, conversation, or model metadata…" value="${escape(state.q)}" maxlength="200"><div class="search-row">${periodSelector(state)}${multiSelector('project','Project',f.projects,state.project)}${multiSelector('model','Model',f.models,state.model)}${multiSelector('effort','Effort',f.efforts,state.effort)}</div><div class="actions">${button('Reset Explore','clear')}${state.day?button('Day: '+state.day+' ×','clear-day'):''}</div><p class="note">${text(state.provider)} selected · ${d.summary.conversation_count} matching conversations · ${d.summary.project_count} projects · filters isolated to Explore</p></section>${cards(d.summary,false,true)}${quality(bundle,d.summary,true)}${metricTabs(state)}<div class="pie-grid">${renderPie('Model share · '+metricName(state),a.models[metric],state,helpers)}${renderPie('Usage by project',a.projects[metric],state,helpers,true)}</div>${dailyChart(bundle,state,false)}<section class="panel history-panel"><div class="history-heading"><h2 id="history-heading" tabindex="-1">Conversation history</h2><select id="sort" aria-label="Sort matching rows">${[['value_desc','API value'],['tokens_desc','Tokens'],['last_activity_desc','Last activity']].map(([v,l])=>`<option value="${v}" ${state.sort===v?'selected':''}>${l}</option>`).join('')}</select></div><div class="tabs">${button('Conversations','table',`data-value="conversations" aria-pressed="${state.table==='conversations'}"`)}${button('Projects','table',`data-value="projects" aria-pressed="${state.table==='projects'}"`)}</div>${state.table==='projects'?projectRows(d.items)+pager(d.pagination,bundle.navigation):`<div class="table-scroll"><table class="history-table"><thead><tr><th>Project / chat</th><th>Model</th><th class="number">App credit</th><th class="number">API value · USD</th><th class="number">Tokens</th><th class="number">Unestimated tokens</th></tr></thead><tbody>${rows||'<tr><td colspan="6" class="empty">No matching conversations. Reset Explore to broaden this app’s query.</td></tr>'}</tbody></table>${historyMore(d,bundle.navigation)}</div>`}</section>${renderMethodology(bundle,helpers)}`;
}
function detail(bundle,state){
  const d=bundle.detail.data,e=bundle.events.data,s=d.summary,zone=bundle.overview.range.timezone;
  const labels={uncached_input_tokens:'Uncached input',output_tokens:'Output · includes reasoning',cache_read_tokens:'Cache reads',cache_write_5m_tokens:'Cache writes · 5 minutes',cache_write_1h_tokens:'Cache writes · 1 hour'};
  return `<div class="actions">${button('← Back to results','back')}</div>${heading(d.label,'Matched usage in the retained query · lifetime dates are separate',state,false)}${cards(s,true)}${quality(bundle,s)}${panel('Applied pricing',renderPricingBreakdown(d.pricing))}${panel('Token breakdown · counted once',`<dl class="breakdown">${Object.entries(labels).map(([k,l])=>`<dt>${l}</dt><dd title="${escape(s.tokens[k])} exact tokens">${formatTokens(s.tokens[k])}</dd>`).join('')}<dt>Reasoning · subset of output</dt><dd>${formatTokens(s.tokens.reasoning_tokens)}${s.reasoning.unknown_records?' · partial / unknown coverage':''}</dd></dl>`)}${panel('Recorded metadata',`<p class="mono">${text(d.id)}</p><p>${text(d.models.join(', '))} · ${text(d.efforts.join(', '))}</p><p class="note">Matched projects: ${d.project_ids.map(text).join(' · ')||'None in the selected query'}</p><p class="note">Lifetime accepted usage: ${text(date(d.lifetime_first_at,zone))} – ${text(date(d.lifetime_last_at,zone))}</p>${button('Copy conversation ID','copy',`data-value="${escape(d.id)}"`)}`)}${panel(`${s.record_count} matched accepted events`,`<div class="table-scroll"><table><thead><tr><th>Time / agent</th><th>Model / effort evidence</th><th class="number">Tokens</th><th class="number">API value / assumptions</th></tr></thead><tbody>${e.items.map(x=>`<tr><td>${text(date(x.occurred_at,zone))}<p class="note">${text(x.provider)}</p></td><td>${text(x.model)} / ${text(x.effort)}<p class="note">${text(x.effort_source)}</p></td><td class="number" title="${escape(x.tokens.total_tokens)} exact tokens">${formatTokens(x.tokens.total_tokens)}</td><td class="number">${escape(usd(x))}<p class="note">${text(x.value.unpriced_reason??x.value.tier??'')} · ${text(x.value.assumptions.map(readable).join(', '))}</p></td></tr><tr class="usage-rate-row"><td colspan="4">${renderEventPricing(x.value)}</td></tr>`).join('')||'<tr><td colspan="4" class="empty">No accepted events match the selected filters.</td></tr>'}</tbody></table>${pager(e.pagination,bundle.navigation,true)}</div><p class="note">Metadata only. The headline covers all matched events, independently of this page.</p>`)}`;
}
function limits(bundle,state){const zone=bundle.wire.data.timezone_info.name;return `${heading('Live limits','Cached state of active CLI accounts · independent of report dates',state,false)}${bundle.wire.data.timezone_info.source==='fallback'?'<p class="note">'+timezoneLabel(bundle.wire.data.timezone_info)+'</p>':''}${bundle.wire.data.providers.map(p=>panel(p.provider,`<p>${text(p.state)} · ${text(readable(p.category))} · ${text(p.phase)}</p>${p.state==='stale'?'<p class="banner">Retained limit snapshot · this is the last successful reading, not a current check.</p>':''}${!p.snapshot?.windows.length?'<p class="note">Remaining capacity unavailable. No limit reading is available for this active CLI account.</p>':''}${p.snapshot?.blocked?'<p class="banner">Ordinary provider usage is currently blocked.</p>':''}${(p.snapshot?.windows??[]).map(w=>`<h3>${text(w.label)}</h3><p class="metric">${new Intl.NumberFormat('en-US',{maximumFractionDigits:2}).format(w.remaining_percent)}% remaining</p><progress class="progress" max="100" value="${w.remaining_percent}" aria-label="${text(p.provider)} ${text(w.label)} remaining capacity"></progress><p class="note">Filled bar shows remaining capacity · resets ${text(date(w.resets_at,zone))}</p>`).join('')}<p class="note">Last attempt: ${text(date(p.last_attempt_at,zone))}<br>Last success: ${text(date(p.last_success_at,zone))}<br>Next eligible: ${text(date(p.next_eligible_at,zone))}</p>${button('View recorded usage →','provider-explore',`data-value="${escape(p.provider)}"`)}`)).join('')}`;}

const timezoneLabel=info=>info.source==='fallback'?'System timezone unavailable · UTC fallback. Choose a manual timezone in Settings.':`${text(info.name)} · ${info.source==='system'?'Automatic (system timezone)':'Manual timezone'}`;
function settings(bundle,state,draft){
  const d=bundle.wire.data,s=d.settings,values=draft??{Codex:s.plan_fees_usd.Codex??'',Claude:s.plan_fees_usd.Claude??'',timezone:s.timezone};
  return `${heading('Settings & data','',state,false)}<div class="fee-grid">${['Codex','Claude'].map(p=>panel(p+' monthly plan fee',`<label class="fee-input-label">USD per calendar month<input id="fee-${p}" class="fee-input mono" data-setting="${p}" inputmode="decimal" maxlength="40" aria-label="${p} monthly fee in USD" value="${escape(values[p])}"></label>`)).join('')}</div>${panel('Report timezone',`<div class="timezone-heading"><p>${timezoneLabel(values.timezone==='auto'?s.system_timezone_info:{name:values.timezone,source:'manual'})}</p><label class="settings-row"><select id="settings-timezone-mode" aria-label="Timezone mode"><option value="auto" ${values.timezone==='auto'?'selected':''}>Automatic — system timezone</option><option value="manual" ${values.timezone!=='auto'?'selected':''}>Choose manually</option></select></label></div>${values.timezone==='auto'?'':`<label class="settings-row">Named timezone <input id="settings-timezone" data-setting="timezone" aria-label="Settings timezone" value="${escape(values.timezone)}" maxlength="100" placeholder="America/Los_Angeles"></label><p class="note">Use an IANA name, such as America/Los_Angeles or UTC.</p>`}`)}<div class="actions">${button('Save settings','save-settings')}${button('Cancel draft','cancel-settings')}${button('Reload settings','reload-settings')}</div><p id="settings-result" class="note" role="status"></p>${panel('Local data and live limits',`<p>Usage uses available local logs across unmatched accounts. Live limits use active CLI accounts. Fees remain in USD; app credits never represent remaining allowance.</p><p class="note">Root approval, flat rate overrides and report preferences remain native configuration controls. Existing values are preserved when fees/timezone are saved.</p>${s.approved_roots.map(r=>`<p class="note">${text(r.provider)} · ${text(r.label)} · ${r.enabled?'Enabled':'Disabled; retained history is preserved'}</p>`).join('')||'<p>No approved roots are configured.</p>'}`)}`;
}
export function renderOperationFeedback(operation){return operation?`<p>${text(operation.message)}</p>${operation.checkable?button('Check progress','check-job'):''}`:'';}
export function renderLocal(bundle,state,{draft=null,operation=null,derived=false}={}){return `<section id="operation-status" class="banner" role="status" ${operation?'':'hidden'}>${renderOperationFeedback(operation)}</section>`+statusBanner(bundle)+(derived?`<div class="actions">${button('← Back to Overview','back')}<span class="note">Derived Explore query · ${text(state.provider)} · Overview filters are kept</span></div>`:'')+({overview,explore,detail,limits,settings}[state.view])(bundle,state,draft)+(state.view==='limits'?'':note);}
export function renderChrome(document,bundle,state){
  document.querySelector('#breadcrumb').textContent=({overview:'Usage overview',explore:'Explore usage',detail:'Conversation detail',limits:'Live limits',settings:'Settings & data'})[state.view];
  document.querySelector('#mode').textContent='LOCAL DATA';document.querySelector('#scope').textContent='Local metadata · unmatched accounts';
  document.querySelector('#connection').textContent=bundle.overview?(bundle.overview.data.freshness==='stale'?'Retained usage · stale':'Committed local usage'):'Local service';
  const range=bundle.overview?.range;
  document.querySelector('#capture').textContent=range?'Frozen through '+date(range.end_at,range.timezone)+' · '+range.timezone:'Cached service state';
  for(const link of document.querySelectorAll('[data-nav]')){
    const active=link.dataset.nav===(state.view==='detail'?'explore':state.view);link.removeAttribute('aria-current');
    if(active)link.setAttribute('aria-current','page');
    link.querySelector('img').src='/assets/'+(link.dataset.nav==='overview'?(active?'overview':'overview-muted'):link.dataset.nav+(active?'-active':''))+'.svg';
  }
}
export function drawLocalChart(document,bundle,state){
  const chart=document.querySelector('#chart');if(!chart)return;
  const svg=(tag,attrs={},value)=>{const n=document.createElementNS('http://www.w3.org/2000/svg',tag);for(const [k,v]of Object.entries(attrs))n.setAttribute(k,v);if(value!==undefined)n.textContent=value;return n;};
  const wire=bundle.overview,recorded=new Map(wire.data.days.map(d=>[d.day,d]));
  const parts=instant=>Object.fromEntries(new Intl.DateTimeFormat('en-US',{timeZone:wire.range.timezone,year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(new Date(instant)).map(p=>[p.type,p.value]));
  const localDay=instant=>{const p=parts(instant);return `${p.year}-${p.month}-${p.day}`;};
  const days=[],end=localDay(state.view==='explore'?new Date(Date.parse(wire.range.end_at)-1).toISOString():wire.range.end_at),calendar=new Date(localDay(wire.range.start_at)+'T00:00:00Z');
  for(let i=0;i<32;i++){const day=calendar.toISOString().slice(0,10);if(day>end)break;days.push(recorded.get(day)??{day,summary:null});calendar.setUTCDate(calendar.getUTCDate()+1);}
  const average=wire.data.analysis?.daily_average,averageValue=average?.[state.metric==='tokens'?'tokens_per_day':state.metric==='credits'?'app_credits_per_day':'usd_per_day'];
  const averageText=averageValue==null?null:state.metric==='tokens'?formatAverageTokens(averageValue):state.metric==='credits'?formatAverageCredits(averageValue):'$'+formatUsd(averageValue);
  const w=Math.max(280,chart.clientWidth||620),h=state.view==='explore'?280:250,left=state.view==='explore'?Math.max(80,(averageText?.length??0)*7+18):65,right=12,top=14,bottom=38,plot=h-top-bottom;
  chart.replaceChildren();chart.setAttribute('viewBox',`0 0 ${w} ${h}`);
  // Number conversion is solely for approximate SVG geometry/axis ticks.
  // Exact labels/headlines remain server integer/decimal strings.
  const values=days.map(d=>!d.summary?0:state.metric==='tokens'?Number(d.summary.tokens.total_tokens):state.metric==='credits'?(d.summary.app_credits?.amount==null?null:Number(d.summary.app_credits.amount)):d.summary.value.amount_usd===null?null:Number(d.summary.value.amount_usd));
  const maximum=chartScale(Math.max(0,...values.map(v=>v??0)));
  for(let i=0;i<=5;i++){
    const y=top+plot-i*plot/5,value=maximum*i/5,digits=value===0?0:Math.max(0,Math.min(16,-Math.floor(Math.log10(maximum/5))));
    chart.append(svg('line',{x1:left,y1:y,x2:w-right,y2:y,...(i===0?{'class':'zero-baseline'}:{})}));chart.append(svg('text',{x:left-10,y:y+4,'text-anchor':'end'},state.metric==='tokens'?formatTokens(BigInt(Math.round(value))):(state.metric==='credits'?'':'$')+value.toLocaleString('en-US',{minimumFractionDigits:digits,maximumFractionDigits:digits})));
  }
  if(!days.length){chart.append(svg('text',{x:w/2,y:h/2,'text-anchor':'middle'},'No matching recorded activity'));return;}
  const width=(w-left-right)/days.length;
  const averageDays=days.map((d,i)=>({day:d.day,value:values[i]})).filter(d=>!wire.applied_filters.selected_day||d.day===wire.applied_filters.selected_day);
  const averageAvailable=state.view==='explore'&&wire.data.summary.record_count>0&&averageDays.length&&(state.metric==='tokens'||wire.data.summary.value.amount_usd!==null);
  const averageLabel='Daily average'+(state.metric!=='tokens'&&wire.data.summary.value.state==='partial'?' · priced subtotal':'');
  days.forEach((d,i)=>{
    const value=values[i],height=value===null?0:plot*value/maximum,label=`${d.day}: ${!d.summary?'No matched records':state.metric==='tokens'?`${formatTokens(d.summary.tokens.total_tokens)} tokens (${d.summary.tokens.total_tokens} exact)`:state.metric==='credits'?`${d.summary.app_credits?.amount??'Unavailable'} app credits`:`USD ${formatUsd(d.summary.value.amount_usd)}${d.summary.value.state==='partial'?' · priced subtotal':''}`}. Open matching conversations.`;
    const g=svg('g',{role:'button',tabindex:0,'aria-label':label,'data-action':'day','data-value':d.day});g.append(svg('title',{},label));
    // A full-height transparent hit area keeps zero/unpriced days clickable.
    g.append(svg('rect',{x:left+i*width+width*.1,y:top,width:width*.8,height:plot,'fill-opacity':0}));
    if(height>0){const x=left+i*width+width*.2,y=top+plot-height,bw=width*.6,r=Math.min(4,height,bw/2);g.append(svg('path',{d:`M${x},${top+plot} V${y+r} Q${x},${y} ${x+r},${y} H${x+bw-r} Q${x+bw},${y} ${x+bw},${y+r} V${top+plot} Z`,'class':'daily-column'}));}
    if(d.day===state.day)g.setAttribute('class','selected');
    const step=Math.ceil(days.length/Math.max(1,Math.floor((w-left-right)/27)));
    if(i%step===0||i===days.length-1)g.append(svg('text',{x:left+(i+.5)*width,y:h-14,'text-anchor':'middle'},d.day.slice(-2).replace(/^0/,'')));chart.append(g);
  });
  if(averageAvailable){
    const ratio=averageValue!=null?Number(averageValue)/maximum:averageDays.reduce((sum,d)=>sum+(d.value??0)/maximum,0)/averageDays.length,y=top+plot-plot*ratio;
    const description=averageLabel+' · '+metricName(state)+' · mean across '+averageDays.length+' selected calendar days, including days without matched records. Unpriced amounts are excluded.';
    const line=svg('line',{x1:left,y1:y,x2:w-right,y2:y,'class':'average-line','aria-label':description});line.append(svg('title',{},description));chart.append(line);
    chart.append(svg('text',{x:left+6,y:Math.max(top+12,y-6),'class':'average-label'},averageLabel));
    if(averageText!==null){
      const label=svg('text',{x:left-10,y:y+4,'text-anchor':'end','class':'average-axis-value','aria-label':averageLabel+': '+averageText+' '+metricName(state)},averageText);
      label.append(svg('title',{},averageValue+' '+metricName(state)+' per day · rounded half-even to 18 decimal places by the service'));
      chart.append(svg('rect',{x:0,y:Math.max(0,y-9),width:left-4,height:18,'class':'average-axis-background'}));chart.append(label);
    }
  }
}
