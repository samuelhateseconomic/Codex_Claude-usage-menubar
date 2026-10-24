import test from 'node:test';
import assert from 'node:assert/strict';
import {formatTokens, chartScale, formatMoney, formatDifference} from '../format.js';

test('exact integers below a million, compact millions and billions',()=>{
  const cases=[['0','0'],['999','999'],['1000','1,000'],['190000','190,000'],['999999','999,999'],
    ['1000000','1M'],['2840000','2.84M'],['5000000000','5B'],['12345678901','12.35B'],
    ['999995000','1B'],['9007199254740993','9007199.25B']];
  for(const [input,expected] of cases)assert.equal(formatTokens(input),expected);
  assert.equal(formatTokens(null),'Not recorded');
});
test('USD strings retain exact large amounts, fixed precision and grouping',()=>{
  const cases=[['0','0.000'],['18.42','18.420'],['190000.1','190,000.100'],
    ['9007199254740993.123','9,007,199,254,740,993.123'],
    ['999999999999999999999999.999999999999','1,000,000,000,000,000,000,000,000.000'],
    ['-9007199254740993.123','-9,007,199,254,740,993.123']];
  for(const [value,expected] of cases)assert.equal(formatMoney(value),expected);
  assert.equal(formatMoney('1000000000.123456789012',12),'1,000,000,000.123456789012');
  assert.equal(formatMoney('20',2),'20.00');
  assert.equal(formatMoney('1E-8',12),'0.000000010000'); // Existing preview Decimal fee strings.
  assert.equal(formatMoney('1e3'),'1,000.000');
  assert.equal(formatMoney('-1.23455E+1'),'-12.346');
});
test('USD display uses half-even ties, carry and symmetric negative rounding',()=>{
  for(const [value,expected] of [['1.2345','1.234'],['1.2355','1.236'],['1.234500000001','1.235'],
    ['9.9995','10.000'],['-1.2345','-1.234'],['-1.2355','-1.236'],['-0.0005','0.000'],['-0.000500000001','-0.001']]){
    assert.equal(formatMoney(value),expected);
  }
  assert.equal(formatMoney('2.5',0),'2');
  assert.equal(formatMoney('3.5',0),'4');
});
test('invalid or absent USD input is unavailable rather than an observed zero',()=>{
  for(const value of [null,undefined,NaN,Infinity,18.42,'','1e99','1e-99','NaN',' 20','1,000','1.1234567890123',
    '1000000000000000000000000','<script>','--1'])assert.equal(formatMoney(value),'Unavailable');
  for(const digits of [-1,13,1.5])assert.throws(()=>formatMoney('1',digits),RangeError);
});
test('signed differences never convert exact decimal magnitudes to Number',()=>{
  assert.equal(formatDifference('-9007199254740993.123'),'−$9,007,199,254,740,993.123');
  assert.equal(formatDifference('9007199254740993.123'),'+$9,007,199,254,740,993.123');
  assert.equal(formatDifference('-0.0004'),'−$0.000');
  assert.equal(formatDifference('-0.0000'),'+$0.000');
  assert.equal(formatDifference('-0E+1'),'+$0.000');
  assert.equal(formatDifference('-1E-12'),'−$0.000');
  assert.equal(formatDifference('0'),'+$0.000');
  assert.equal(formatDifference(null),'comparison unavailable');
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
