import test from 'node:test';
import assert from 'node:assert/strict';
import {formatTokens, chartScale} from '../format.js';

test('exact integers below a million, compact millions and billions',()=>{
  const cases=[['0','0'],['999','999'],['1000','1,000'],['190000','190,000'],['999999','999,999'],
    ['1000000','1M'],['2840000','2.84M'],['5000000000','5B'],['12345678901','12.35B'],
    ['999995000','1B'],['9007199254740993','9007199.25B']];
  for(const [input,expected] of cases)assert.equal(formatTokens(input),expected);
  assert.equal(formatTokens(null),'Not recorded');
});
test('five-interval scales cover the largest column without negative baselines',()=>{
  assert.equal(chartScale(33.17),50);
  assert.equal(chartScale(4_740_000),5_000_000);
  assert.equal(chartScale(0),5);
  assert.equal(chartScale(.003),.005);
  for(const maximum of [.000001,.01,.5,1,14.75,190000,1e6,5e9]){
    const scale=chartScale(maximum);
    assert.ok(scale>=maximum);
    assert.ok(scale/5>0);
  }
});
