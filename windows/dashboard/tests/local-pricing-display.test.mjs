import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {renderLocal,renderPricingBreakdown,renderEventPricing} from '../local-view.js';
const f=JSON.parse(readFileSync(new URL('../../../docs/api/usage-hub-v1.fixtures.json',import.meta.url)));
const state={view:'explore',provider:'both',period:'month',metric:'value',table:'conversations',sort:'value_desc',pageSize:50,q:'',project:'',model:'',effort:''};
const bundle={overview:f.overview,status:f.status,list:f.conversations,facets:f.facets,detail:f.conversation,events:f.events,navigation:{previous:[],eventPrevious:[]}};

test('rates sit below usage rows and start closed with explicit USD per-million units',()=>{
  const html=renderLocal(bundle,state);
  assert.match(html,/<tr class="usage-rate-row"><td colspan="6"><details class="usage-rates">/);
  assert.match(html,/Input \$2 \/ Output \$10 \/ Cache read \$0.1 · USD per 1M tokens/);
  assert.doesNotMatch(html,/<details class="usage-rates" open/);
  assert.match(html,/Category charge = tokens × rate ÷ 1,000,000/);
  assert.match(html,/Output includes reasoning once/);
  const detail=renderLocal(bundle,{...state,view:'detail'});
  assert.match(detail,/Applied pricing/);
  assert.match(detail,/<td colspan="4"><details class="usage-rates">/);
  const projects=renderLocal({...bundle,list:f.projects},{...state,table:'projects'});
  assert.match(projects,/Mixed rates/);
  for(const [,inner] of projects.matchAll(/<button\b[^>]*>([\s\S]*?)<\/button>/g))assert.doesNotMatch(inner,/<details/);
});

test('18-place charges and adjustments display exactly without binary math or cent loss',()=>{
  const value=structuredClone(f.events.data.items[0].value);
  value.explanation.categories[0].unrounded_usd='0.000000000000000001';
  value.explanation.rounding_adjustment_usd='-0.000000000000000001';
  value.amount_usd='999999999999999999999999.999999999999';
  const html=renderEventPricing(value);
  assert.match(html,/0.000000000000000001/);
  assert.match(html,/USD -0.000000000000000001/);
  assert.match(html,/USD 999999999999999999999999.999999999999/);
  assert.match(html,/half-even to 12 USD decimal places/);
});

test('unknown, unused missing rates, explicit zero and assumptions remain distinct',()=>{
  const unknown=renderEventPricing(f.events_unpriced.data.items[0].value);
  assert.match(unknown,/Rates · Unavailable · model rate unavailable/);
  assert.match(unknown,/Estimated value unavailable/);
  assert.doesNotMatch(unknown,/<table/);
  const zero=renderEventPricing(f.events_zero.data.items[0].value);
  assert.match(zero,/Input \$0/);assert.match(zero,/Estimated API value: <strong class="mono">USD 0/);
  assert.match(zero,/Unconfigured/); // Inactive write rates are not configured zeroes.
  const missing=structuredClone(f.events_claude.data.items[0].value);
  missing.state='unpriced';missing.amount_usd=null;missing.explanation.rounding_adjustment_usd=null;
  Object.assign(missing.explanation.categories[3],{rate_usd_per_million:null,unrounded_usd:null});
  const html=renderEventPricing(missing);
  assert.match(html,/Cache write 5m unavailable/);
  assert.match(html,/Known category charges do not establish its total/);
  assert.match(html,/legacy cache ttl assumed/);
  assert.match(html,/Pricing source & version/);
});

test('mixed and truncated previews disclose their scope without claiming a complete sum',()=>{
  const pricing=structuredClone(f.projects.data.items[0].pricing);
  const html=renderPricingBreakdown({...pricing,group_count:12,total_record_count:20,truncated:true});
  assert.match(html,/Mixed rates · 12 groups/);
  assert.match(html,/Showing 2 of 12 rate groups \(2 of 20 records\)/);
  assert.match(html,/preview does not add up to the full total/);
  assert.match(html,/page through accepted events for all rates/);
  assert.match(renderPricingBreakdown({total_record_count:0}),/No matched events to explain/);
});

test('untrusted pricing metadata is inert text, never a link or executable markup',()=>{
  const value=structuredClone(f.events.data.items[0].value),e=value.explanation;
  e.requested_model='<img src=x onerror=alert(1)>';
  e.source='javascript:PRIVATE_SOURCE\u001b';e.custom=false;
  e.assumptions=['<script>PRIVATE</script>'];e.rate_id='</dd><script>PRIVATE</script>';
  const html=renderEventPricing(value);
  assert.doesNotMatch(html,/<img|<script|href=|\u001b/);
  assert.match(html,/&lt;img/);assert.match(html,/javascript:PRIVATE_SOURCE\\u001b/);
});
