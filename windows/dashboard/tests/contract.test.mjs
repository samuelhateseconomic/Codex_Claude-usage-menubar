import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {contractSchema} from '../contract-schema.js';
import {validateResponse, validateSchema, ContractError} from '../response-contract.js';
import {fixtureSet} from './v1-fixture-builder.mjs';
export const fixture=name=>structuredClone(fixtureSet.cases.find(item=>item.name===name).response);

test('published schema and fixtures exactly match the executable candidate',()=>{
  assert.deepEqual(JSON.parse(readFileSync(new URL('../../../docs/contracts/usage-hub-v1.candidate.schema.json',import.meta.url))),contractSchema);
  assert.deepEqual(JSON.parse(readFileSync(new URL('../../../docs/fixtures/usage-hub-v1-responses.json',import.meta.url))),fixtureSet);
  for(const item of fixtureSet.cases){
    const result=validateResponse(item.kind,item.response);assert.deepEqual(result,item.response,item.name);assert.notEqual(result,item.response);
    // Exercise the full JSON artifact as well as the per-endpoint runtime schema.
    const schema=JSON.parse(readFileSync(new URL('../../../docs/contracts/usage-hub-v1.candidate.schema.json',import.meta.url)));
    validateSchema(schema,item.response,schema);
  }
});
test('alignment totals and page-independent headline remain exact, including duplicate labels',()=>{
  const alignment=JSON.parse(readFileSync(new URL('../../../docs/fixtures/usage-hub-database-alignment.json',import.meta.url)));
  const overview=fixture('overview-complete'),first=fixture('conversation-page-1'),second=fixture('conversation-page-2');
  assert.deepEqual(overview.summary.tokens,alignment.expected_projection.tokens);
  assert.equal(overview.summary.value.amount_usd,alignment.expected_projection.value.amount_usd);
  assert.deepEqual(first.summary,second.summary);assert.equal(first.summary.conversation_count,2);assert.equal(first.items.length,1);
  assert.equal(first.items[0].display_label,second.items[0].display_label);assert.notEqual(first.items[0].conversation_id,second.items[0].conversation_id);
  assert.equal(first.items[0].summary.tokens.total_tokens,'2840000');assert.equal(second.items[0].summary.tokens.total_tokens,'65000');
  assert.equal(fixture('multi-project-detail').conversation.projects.length,2);
});
test('wire rejects numeric counters/money, int64 overflow, unknown fields and malformed coverage',()=>{
  const mutations=[
    data=>data.summary.tokens.total_tokens=2905000,
    data=>data.summary.tokens.total_tokens='9223372036854775808',
    data=>data.summary.tokens.total_tokens='01',
    data=>data.summary.value.amount_usd=18.891,
    data=>data.summary.value.amount_usd='1e3',
    data=>data.summary.value.amount_usd='1000000000000000000000000',
    data=>data.summary.value.state='priced',
    data=>data.summary.value.amount_usd=null,
    data=>delete data.coverage,
    data=>data.coverage.skipped_tokens='100',
    data=>data.applied_filters.providers=[],
    data=>data.applied_filters.providers=['codex','codex'],
    data=>data.applied_filters.search='x'.repeat(201),
    data=>data.range.end_at='2026-02-31T12:00:00Z',
    data=>data.range.timezone='Invalid/Zone',
    data=>data.prompt='never allowed',
    data=>data.summary.plan_comparison={state:'unavailable',reason:'fee_unavailable',fee_usd:null,difference_usd:'0',qualifications:[]}
  ];
  for(const mutate of mutations){const data=fixture('overview-complete');mutate(data);assert.throws(()=>validateResponse('overview',data),ContractError);}
  const largest=fixture('overview-large');assert.equal(validateResponse('overview',largest).summary.tokens.total_tokens,'9223372036854775807');
});
test('null, zero, unknown reasoning, stale and initial failure remain different',()=>{
  const partial=fixture('overview-partial'),unpriced=fixture('overview-unpriced'),empty=fixture('overview-empty'),zero=fixture('overview-zero');
  assert.equal(partial.summary.value.amount_usd,'18.891000000000');assert.equal(partial.summary.value.unpriced_tokens,'100');
  assert.equal(unpriced.summary.value.amount_usd,null);assert.equal(empty.summary.value.amount_usd,null);assert.equal(zero.summary.value.amount_usd,'0.000000000000');
  assert.equal(fixture('overview-unknown-fee').summary.plan_comparison.fee_usd,null);assert.equal(fixture('overview-zero-fee').summary.plan_comparison.fee_usd,'0.00');
  assert.equal(fixture('overview-complete').summary.reasoning.unknown_record_count,1);assert.equal(fixture('overview-known-zero-reasoning').summary.reasoning.unknown_record_count,0);
  assert.equal(fixture('overview-stale').coverage.providers[0].source_status,'failed');assert.notEqual(fixture('overview-stale').summary.value.amount_usd,null);
  assert.equal(fixture('status-initial-failure').usage_revision,null);
});
test('validator refuses unsupported assertions and invalid references',()=>{
  assert.throws(()=>validateSchema({not:{type:'null'}},null),ContractError);
  assert.throws(()=>validateSchema({$ref:'https://external.invalid/schema'},{}),ContractError);
  assert.throws(()=>validateSchema({$ref:'#/$defs/missing'},{}),ContractError);
});
test('machine-readable initial, derived and frozen request selections have distinct schemas',()=>{
  const filters=fixture('overview-complete').applied_filters;
  validateSchema(contractSchema.$defs.query_selection,{dataset_id:'fixture-demo-local',...filters,period:'month',timezone:'UTC'});
  validateSchema(contractSchema.$defs.derived_selection,{base_query_context_id:'parent',dataset_id:'fixture-demo-local',...filters});
  validateSchema(contractSchema.$defs.frozen_selection,{query_context_id:'parent',cursor:null,sort:'value_desc',page_size:50});
  assert.throws(()=>validateSchema(contractSchema.$defs.frozen_selection,{query_context_id:'parent',base_query_context_id:'conflict',cursor:null,sort:'value_desc',page_size:50}),ContractError);
});
