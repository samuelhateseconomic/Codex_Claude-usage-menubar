import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {validateV1} from '../v1-client.js';
const fixtures=JSON.parse(readFileSync(new URL('../../../docs/api/usage-hub-v1.fixtures.json',import.meta.url)));

test('applied pricing remains exact with known, cache-write, unpriced and zero-rate fixtures',()=>{
  for(const name of ['events','events_claude','events_unpriced','events_zero']){
    const wire=fixtures[name];assert.deepEqual(validateV1('events',wire),wire);
  }
  const known=fixtures.events.data.items[0].value.explanation;
  assert.equal(known.rate_unit_tokens,'1000000');assert.equal(known.currency,'USD');
  assert.equal(known.pricing_version,fixtures.events.pricing_version);
  assert.equal(known.categories.length,5);
  assert.equal(fixtures.events_claude.data.items[0].value.explanation.categories[3].rate_usd_per_million,'5');
  assert.equal(fixtures.events_unpriced.data.items[0].value.explanation.state,'unavailable');
  assert.equal(fixtures.events_unpriced.data.items[0].value.amount_usd,null);
  assert.ok(fixtures.events_zero.data.items[0].value.explanation.categories.every(c=>c.rate_usd_per_million==='0'||c.rate_usd_per_million===null&&c.tokens==='0'));
});

test('client rejects malformed pricing evidence rather than displaying invented rates',()=>{
  for(const change of [
    e=>e.categories[0].rate_usd_per_million=2,
    e=>e.categories[0].rate_usd_per_million='1000000000.000000000001',
    e=>e.categories[0].unrounded_usd='-1',
    e=>e.categories[0].unrounded_usd='0.0000000000000000001',
    e=>e.categories[0].tokens='9223372036854775808',
    e=>e.categories[0].category='output_tokens',
    e=>e.rate_unit_tokens='1',
    e=>e.pricing_version='another-publication',
    e=>delete e.source,
    e=>e.state='unavailable',
    e=>e.prompt='PRIVATE_SENTINEL',
  ]){
    const wire=structuredClone(fixtures.events);change(wire.data.items[0].value.explanation);
    assert.throws(()=>validateV1('events',wire));
  }
});

test('bounded group metadata accounts for displayed rows without implying full coverage',()=>{
  const wire=fixtures.conversation;
  assert.deepEqual(validateV1('conversation',wire),wire);
  for(const change of [
    p=>p.groups=Array(9).fill(p.groups[0]),
    p=>p.shown_record_count++,
    p=>p.group_count=0,
    p=>p.truncated=true,
  ]){
    const copy=structuredClone(wire);change(copy.data.pricing);
    assert.throws(()=>validateV1('conversation',copy));
  }
});
