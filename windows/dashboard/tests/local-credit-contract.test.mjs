import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {validateV1,usagePath,createLocalClient} from '../v1-client.js';
export const creditFixtures=JSON.parse(readFileSync(new URL('../../../docs/api/dashboard-projection.fixtures.json',import.meta.url)));

test('actual projected Python responses validate without converting exact quantities',()=>{
  for(const wire of Object.values(creditFixtures))assert.deepEqual(validateV1(wire.kind,wire),wire);
  assert.equal(creditFixtures.overview.data.summary.tokens.total_tokens,'192');
  assert.equal(creditFixtures.partial.data.summary.value.state,'partial');
  assert.equal(creditFixtures.unpriced.data.summary.app_credits.amount,null);
  assert.equal(creditFixtures.zero.data.analysis.models.usd.state,'zero');
});
test('credit projection rejects unit/policy/mapping changes, absent credit fields and oversized analysis',()=>{
  for(const mutate of [
    w=>w.projection.unit='codex_credit',w=>w.projection.usd_per_credit='1',
    w=>w.projection.credit_policy='other',w=>w.projection.primary_models.reverse(),
    w=>delete w.data.summary.app_credits,w=>delete w.data.analysis,
    w=>delete w.data.analysis_pagination,w=>w.data.analysis_pagination.page_size=9,
    w=>w.data.summary.app_credits.amount='100000000000000000000000000',
    w=>w.data.summary.app_credits.amount='0.00000000001',
    w=>w.data.analysis.projects.usd.slices[0].percent='100.000001',
    w=>w.data.analysis.projects.usd.slices=Array(13).fill(w.data.analysis.projects.usd.slices[0])
  ]){const wire=structuredClone(creditFixtures.overview);mutate(wire);assert.throws(()=>validateV1('overview',wire));}
});
test('projection selector and analysis paging remain on authenticated existing routes',async()=>{
  const p=new URL('http://localhost'+usagePath('overview',{query:{projection:'app_api_value_v1',provider:['codex']}}));
  assert.equal(p.searchParams.get('projection'),'app_api_value_v1');
  const a=new URL('http://localhost'+usagePath('analysis',{contextId:'frozen+context',cursor:'opaque+cursor'}));
  assert.equal(a.pathname,'/api/v1/usage/analysis');assert.equal(a.searchParams.get('page_size'),'8');assert.equal(a.searchParams.get('sort'),null);
  assert.throws(()=>usagePath('analysis',{pageSize:9}));
  const client=createLocalClient({fetchImpl:async()=>Response.json({...creditFixtures.overview,projection:undefined})});
  await assert.rejects(client.usage('overview',{query:{projection:'app_api_value_v1'}}));
});


test('optional daily-average projection preserves exact service decimals and rejects malformed bounds',()=>{
  const a=creditFixtures.overview.data.analysis.daily_average;assert.equal(a.tokens_per_day,'8.000000000000000000');assert.equal(a.calendar_days,24);
  for(const mutate of [a=>a.calendar_days=33,a=>a.usd_per_day='0.0000000000000000001',a=>a.tokens_per_day='-1',a=>a.rounding='unknown']){
    const wire=structuredClone(creditFixtures.overview);mutate(wire.data.analysis.daily_average);assert.throws(()=>validateV1('overview',wire));
  }
  const old=structuredClone(creditFixtures.overview);delete old.data.analysis.daily_average;assert.deepEqual(validateV1('overview',old),old);
});


test('explicit empty selections have a bounded, optional frozen wire contract',()=>{
  const wire=structuredClone(creditFixtures.overview);wire.applied_filters.empty_selection=['project_id','effort'];
  assert.deepEqual(validateV1('overview',wire),wire);
  for(const v of [[],['provider'],['model','effort','project_id','model']]){const w=structuredClone(wire);w.applied_filters.empty_selection=v;assert.throws(()=>validateV1('overview',w));}
  const url=new URL('http://localhost'+usagePath('overview',{query:{provider:['codex'],model:['one','two'],empty_selection:['project_id','effort']}}));
  assert.deepEqual(url.searchParams.getAll('model'),['one','two']);assert.deepEqual(url.searchParams.getAll('empty_selection'),['project_id','effort']);
});
