import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {renderLocal,drawLocalChart} from '../local-view.js';
import {formatCredits,formatEstimate} from '../format.js';
const f=JSON.parse(readFileSync(new URL('../../../docs/api/dashboard-projection.fixtures.json',import.meta.url)));
const legacy=JSON.parse(readFileSync(new URL('../../../docs/api/usage-hub-v1.fixtures.json',import.meta.url)));
const state={view:'overview',provider:'both',period:'month',metric:'value'};
const bundle=()=>({overview:structuredClone(f.overview),status:structuredClone(legacy.status)});

test('projected Overview keeps four uniform labels, three metrics, exact values and one capacity action',()=>{
  const b=bundle(),html=renderLocal(b,state);
  for(const title of ['ESTIMATED API VALUE','ESTIMATED APP CREDIT','RECORDED TOKENS','PROJECTS COUNTED'])assert.ok(html.includes(`<small>${title}</small>`));
  assert.doesNotMatch(html,/<small>Conversations/);assert.equal((html.match(/All live limits/g)??[]).length,1);
  assert.match(html,/data-value="credits"/);assert.match(html,/Today/);assert.match(html,/Last 7 days/);assert.match(html,/Month to date/);
  assert.match(html,/1 app credit = USD0.01/);assert.doesNotMatch(html,/Full-fee comparison unavailable|Zero baseline · local calendar days/);
  assert.match(html,/Five-hour capacity unavailable/);assert.doesNotMatch(html,/<progress/);
});
test('five-hour bars require duration evidence and retain boundaries, stale, cooldown and reset states',()=>{
  const b=bundle(),p=b.status.data.providers[0];
  p.state='stale';p.category='cooldown';p.snapshot={blocked:true,windows:[0,50,100].map(n=>({remaining_percent:n,duration_minutes:300,resets_at:'2026-10-23T00:00:00.000000Z'}))};
  let html=renderLocal(b,state);
  for(const n of [0,50,100]){assert.match(html,new RegExp(`${n}% left`));assert.ok(html.includes(`value="${n}"`));}
  assert.match(html,/awaiting refreshed limit/);assert.match(html,/Last successful reading · stale/);assert.match(html,/provider usage blocked/);assert.match(html,/cooldown/);
  p.snapshot.windows=[{remaining_percent:90,duration_minutes:10080,resets_at:null}];html=renderLocal(b,state);
  assert.doesNotMatch(html,/90% left/);assert.match(html,/Five-hour capacity unavailable/);
});
test('Explore has paired full-result pies, aligned history and dynamic category methodology below history',()=>{
  const b=bundle();b.list=structuredClone(f.list);b.facets=f.facets;b.analysis=f.analysis;b.navigation={previous:[],eventPrevious:[],analysisPrevious:[]};
  const html=renderLocal(b,{...state,view:'explore',provider:'codex',metric:'credits',table:'conversations',pageSize:50,sort:'value_desc',q:'',project:'',model:'',effort:''});
  assert.equal((html.match(/class="panel pie-panel"/g)??[]).length,2);assert.match(html,/Usage by project/);
  assert.doesNotMatch(html,/Both agents|usage-rate-row/);assert.match(html,/Unestimated tokens/);
  assert.ok(html.indexOf('Conversation history')<html.indexOf('Estimate methodology'));
  for(const value of ['Uncached input','Cache reads','Cache writes · 5 min','Cache writes · 1 hour','Output · includes reasoning','Aggregate rounding adjustment','Past speed is unknown','priced events only'])assert.ok(html.includes(value),value);
  assert.match(html,/5<\/td>|>5<\/td>/);assert.match(html,/7<\/td>|>7<\/td>/);
  assert.match(html,/USD0.01/);assert.doesNotMatch(html,/<details[^>]*\bopen/);
  const tiny=structuredClone(b);tiny.list.data.items[0].summary.value.amount_usd='0.000000000001';
  assert.match(renderLocal(tiny,{...state,view:'explore',provider:'codex',metric:'credits',table:'conversations',q:''}),/\$&lt;0\.01/);
  const single=structuredClone(b);single.overview.data.analysis.models.app_credits.slices=[{...single.overview.data.analysis.models.app_credits.slices[0],percent:'100'}];single.analysis=null;
  assert.match(renderLocal(single,{...state,view:'explore',provider:'codex',metric:'credits',table:'conversations',q:''}),/>100%/);
});
test('credit formatting preserves the larger credit bound and tiny nonzero values',()=>{
  assert.equal(formatCredits('99999999999999999999999999.9999999999',2),'100,000,000,000,000,000,000,000,000.00');
  assert.equal(formatEstimate('0.000000000001',2),'\u003c0.01');
  assert.equal(formatEstimate('0.0000000001',2,true),'\u003c0.01');
  assert.equal(formatEstimate('0',2,true),'0.00');
});
test('daily SVG keeps a zero baseline, flat column bases, calendar dates and exact credit titles',()=>{
  const b=bundle(),nodes=[];
  const node=(tag)=>({tag,attrs:{},children:[],setAttribute(k,v){this.attrs[k]=String(v);},append(...children){this.children.push(...children);},replaceChildren(){this.children=[];}});
  const chart=node('svg');chart.clientWidth=620;
  const document={querySelector:()=>chart,createElementNS:(_ns,tag)=>{const n=node(tag);nodes.push(n);return n;}};
  drawLocalChart(document,b,{...state,metric:'credits'});
  assert.equal(nodes.filter(n=>n.attrs.class==='zero-baseline').length,1);
  assert.equal(nodes.filter(n=>n.tag==='g').length,24);
  const columns=nodes.filter(n=>n.attrs.class==='daily-column');assert.equal(columns.length,1);
  assert.match(columns[0].attrs.d,/ Z$/);assert.doesNotMatch(columns[0].attrs.d,/ A/);
  assert.ok(nodes.some(n=>n.tag==='title'&&n.textContent.includes('app credits')));
  assert.ok(nodes.some(n=>n.tag==='text'&&n.textContent==='0'));
});

function exploreBundle(){
  const b=bundle();b.list=structuredClone(f.list);b.facets=f.facets;b.analysis=structuredClone(f.analysis);b.navigation={previous:[],eventPrevious:[],analysisPrevious:[]};return b;
}
const exploreState={...state,view:'explore',provider:'codex',metric:'value',table:'conversations',q:''};

test('methodology omits only zero unavailable write rows and keeps recorded or priced writes',()=>{
  const b=exploreBundle(),m=b.analysis.data.analysis.methodology;
  for(const c of m.categories.filter(c=>c.category.startsWith('cache_write_')))Object.assign(c,{tokens:'0',rate_usd_per_million:null,mixed_rates:false,unrounded_priced_usd:'0'});
  const before=JSON.stringify(b);
  let html=renderLocal(b,exploreState).split('<h3>Token breakdown</h3>')[1].split('</table>')[0];
  assert.doesNotMatch(html,/Cache writes/);assert.match(html,/Uncached input|Cache reads/);
  assert.equal(JSON.stringify(b),before,'presentation cannot mutate canonical values');
  Object.assign(m.categories.find(c=>c.category==='cache_write_5m_tokens'),{tokens:'5',unrounded_priced_usd:null});
  Object.assign(m.categories.find(c=>c.category==='cache_write_1h_tokens'),{tokens:'0',rate_usd_per_million:'0'});
  html=renderLocal(b,exploreState).split('<h3>Token breakdown</h3>')[1].split('</table>')[0];
  assert.match(html,/Cache writes · 5 min/);assert.match(html,/Cache writes · 1 hour/);assert.match(html,/Unavailable/);assert.match(html,/>0.00</);
});

test('calculation basis states the context assumption once and preserves contrary evidence',()=>{
  const b=exploreBundle();b.overview.data.summary.value.assumptions=['below_threshold_context_assumed','recorded_context_exceeds_assumed_threshold'];
  const basis=renderLocal(b,exploreState).split('<h3>Calculation basis</h3>')[1].split('</section>')[0];
  assert.equal((basis.match(/below.threshold context assumed/gi)??[]).length,1);
  assert.match(basis,/recorded context exceeds assumed threshold/);assert.match(basis,/USD amounts and rates display to two decimals/);
});

test('methodology USD rows, rates and totals are rounded for display only, including tiny adjustments',()=>{
  const b=exploreBundle(),m=b.analysis.data.analysis.methodology;
  Object.assign(m.categories[0],{rate_usd_per_million:'2.000000000000',mixed_rates:false,unrounded_priced_usd:'16.224690800000000000'});
  m.rounding_adjustment_usd='-0.000000000000000001';b.overview.data.summary.value.amount_usd='16.224690800000';
  const html=renderLocal(b,exploreState).split('<h2>Estimate methodology</h2>')[1];
  assert.match(html,/title="2.000000000000 exact USD">2.00</);assert.match(html,/title="16.224690800000000000 exact USD">16.22</);
  assert.match(html,/title="16.224690800000 exact USD">16.22</);assert.match(html,/title="-0.000000000000000001 exact USD">−&lt;0.01</);
  assert.doesNotMatch(html,/>16.224690800000/);assert.match(html,/displayed rows may not sum/);
});


test('Explore daily average follows filtered days and metrics, including zero days and pricing gaps',()=>{
  const b=bundle();Object.assign(b.overview.range,{start_at:'2026-10-01T00:00:00Z',end_at:'2026-10-04T00:00:00Z'});
  const day=(date,tokens,value,credits)=>{const summary=structuredClone(b.overview.data.summary);summary.tokens.total_tokens=tokens;summary.value.amount_usd=value;summary.app_credits.amount=credits;return {day:date,summary};};
  b.overview.data.days=[day('2026-10-01','6','0.06','6'),day('2026-10-03','12','0.12','12')];
  b.overview.data.analysis.daily_average={tokens_per_day:'6.000000000000000000',usd_per_day:'0.060000000000000000',app_credits_per_day:'6.000000000000000000'};
  function draw(metric='tokens',view='explore'){
    const node=tag=>({tag,attrs:{},children:[],setAttribute(k,v){this.attrs[k]=String(v);},append(...children){this.children.push(...children);},replaceChildren(){this.children=[];}});
    const chart=node('svg');chart.clientWidth=620;const nodes=[];
    drawLocalChart({querySelector:()=>chart,createElementNS:(_ns,tag)=>{const n=node(tag);nodes.push(n);return n;}},b,{...state,view,metric});
    return {nodes,line:nodes.find(n=>n.attrs.class==='average-line'),baseline:Number(nodes.find(n=>n.attrs.class==='zero-baseline').attrs.y1)};
  }
  let r=draw();assert.equal(r.nodes.filter(n=>n.attrs.role==='button').length,3,'exclusive midnight excludes an extra calendar day');
  assert.match(r.line.attrs['aria-label'],/3 selected calendar days/);
  const axis=r.nodes.find(n=>n.attrs.class==='average-axis-value');assert.equal(axis.textContent,'6.00');assert.equal(Number(axis.attrs.y),Number(r.line.attrs.y1)+4);assert.ok(axis.children[0].textContent.includes('6.000000000000000000'));
  // Expected token average is (6 + 0 + 12) / 3 = 6, on an axis maximum of 25.
  assert.ok(Math.abs(Number(r.line.attrs.y1)-(r.baseline-(280-14-38)*6/25))<1e-10);
  assert.equal(draw('credits').line.attrs.y1,r.line.attrs.y1);assert.match(draw('value').line.attrs['aria-label'],/API value · USD/);
  b.overview.applied_filters.selected_day='2026-10-01';b.overview.data.days=b.overview.data.days.slice(0,1);
  r=draw();assert.match(r.line.attrs['aria-label'],/1 selected calendar days/);assert.ok(Number(r.line.attrs.y1)<r.baseline);
  b.overview.data.summary.value.state='partial';assert.match(draw('value').line.attrs['aria-label'],/priced subtotal/);
  b.overview.data.summary.value.amount_usd=null;b.overview.data.summary.value.state='unpriced';assert.equal(draw('value').line,undefined);assert.ok(draw('tokens').line);
  b.overview.data.summary.value.amount_usd='0';b.overview.data.summary.value.state='complete';b.overview.data.days[0].summary.value.amount_usd='0';b.overview.data.analysis.daily_average.usd_per_day='0.000000000000000000';
  assert.equal(Number(draw('value').line.attrs.y1),draw('value').baseline);
  b.overview.data.summary.record_count=0;assert.equal(draw().line,undefined);assert.equal(draw('tokens','overview').line,undefined);
});


test('period controls leave titles and live in their requested page rows',()=>{
  const overview=renderLocal(bundle(),{...state,period:'week'});
  assert.match(overview,/<div class="overview-filters"><div class="filters"[\s\S]*id="period"/);
  assert.doesNotMatch(overview.split('</div></div>')[0],/id="period"/);
  const explore=renderLocal(exploreBundle(),exploreState),filters=explore.split('class="panel search-panel"')[1].split('</section>')[0];
  assert.match(filters,/id="period"/);assert.doesNotMatch(explore,/class="chart-caption"|Dashed line: daily average/);
});


test('requested clutter is removed while labels, chart units, actions and timezone recovery remain',()=>{
  const b=exploreBundle(),html=renderLocal(b,exploreState),filters=html.split('class="panel search-panel"')[1].split('</section>')[0];
  assert.doesNotMatch(filters,/Primary model|id="sort"|data-action="metric"/);
  for(const key of ['project','model','effort'])assert.match(filters,new RegExp('id="'+key+'" class="multi-filter"'));
  assert.equal((filters.match(/data-filter-all/g)??[]).length,3);assert.equal((filters.match(/Select all/g)??[]).length,3);
  assert.doesNotMatch(html,/Explore query only|Priced-subtotal denominator|Primary-model scope does not establish agent attribution/);
  assert.match(html,/class="chart-unit"/);assert.match(html,/class="history-heading"[\s\S]*id="sort"/);
  const selected=renderLocal(b,{...exploreState,project:[],model:['one','two']});assert.match(selected,/>Project: None<|<summary>Project: None/);assert.match(selected,/>Model: 2 selected</);
  const settings=structuredClone(legacy.settings);settings.data.settings.timezone='auto';settings.data.settings.timezone_info={name:'America/Los_Angeles',source:'system'};settings.data.settings.system_timezone_info=settings.data.settings.timezone_info;
  const settingsHtml=renderLocal({wire:settings,status:legacy.status},{view:'settings'});
  assert.equal((settingsHtml.match(/America\/Los_Angeles · Automatic \(system timezone\)/g)??[]).length,1);
  assert.doesNotMatch(settingsHtml,/Blank fee means|Maximum USD|Used only for eligible|Use this computer’s timezone automatically/);
  assert.match(settingsHtml,/class="timezone-heading"[\s\S]*id="settings-timezone-mode"/);assert.match(settingsHtml,/id="settings-result"/);
  const limits=structuredClone(legacy.limits);limits.data.timezone_info={name:'America/Los_Angeles',source:'system'};
  const limitHtml=renderLocal({wire:limits,status:legacy.status},{view:'limits'});
  assert.doesNotMatch(limitHtml,/America\/Los_Angeles · Automatic|Quota windows cannot|Local logs across unmatched accounts/);
  limits.data.timezone_info={name:'UTC',source:'fallback'};assert.match(renderLocal({wire:limits,status:legacy.status},{view:'limits'}),/UTC fallback/);
});


test('Overview shortens only displayed project paths and preserves distinct IDs, totals and escaped full labels',()=>{
  const b=bundle(),row=b.overview.data.top_projects[0];
  b.overview.data.top_projects=[
    {...structuredClone(row),id:'first-project',label:'C:\\Windows\\a long parent\\Techna_Internet\\'},
    {...structuredClone(row),id:'second-project',label:'/other/location/Techna_Internet/'},
    {...structuredClone(row),id:'third-project',label:'/tmp/<img src=x onerror=alert(1)>\u001b'},
    {...structuredClone(row),id:'root-project',label:'/'},
  ];
  const before=structuredClone(b),html=renderLocal(b,state);
  assert.equal((html.match(/class="project-name"[^>]*>Techna_Internet<\/button>/g)??[]).length,2);
  for(const id of ['first-project','second-project','third-project','root-project'])assert.ok(html.includes(`data-value="${id}"`));
  assert.equal((html.match(/class="project-path"/g)??[]).length,4);assert.doesNotMatch(html,/<details class="project-path" open/);
  assert.match(html,/aria-label="Show full path for Techna_Internet"/);assert.ok(html.includes('C:\\Windows\\a long parent\\Techna_Internet\\'));
  assert.match(html,/&lt;img src=x onerror=alert\(1\)&gt;/);assert.doesNotMatch(html,/<img src=x/);
  assert.match(html,/class="project-name"[^>]*>\/<\/button>/);assert.deepEqual(b,before);
  assert.equal((html.match(/class="number project-values"/g)??[]).length,4);
});
