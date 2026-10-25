import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {renderLocal} from '../local-view.js';
import {formatMoney,formatDifference} from '../format.js';
const fixtures=JSON.parse(readFileSync(new URL('../../../docs/api/usage-hub-v1.fixtures.json',import.meta.url)));
const state={view:'overview',provider:'both',period:'month',metric:'value'};
const render=overview=>renderLocal({overview,status:fixtures.status},state);
const comparison=c=>{const wire=structuredClone(fixtures.overview);wire.data.comparisons=[{...wire.data.comparisons[0],...c}];return render(wire);};

test('two-decimal headlines and explicit provider comparisons preserve exact USD evidence',()=>{
  const wire=structuredClone(fixtures.overview);wire.data.summary.value.amount_usd='16.224690800000';
  const html=render(wire);
  assert.match(html,/<span class="currency">USD<\/span>16\.22/);
  assert.match(html,/<summary>Exact API value<\/summary><p>USD 16\.224690800000/);
  for(const [fee,difference,display]of [['20.00','-3.775309200000','−$3.78'],['100.00','-83.775309200000','−$83.78']]){
    const row=comparison({value_usd:'16.224690800000',fee_usd:fee,difference_usd:difference});
    assert.ok(row.includes(`<h2>Claude</h2><p>API value <strong>$16.22</strong> − full monthly fee <strong>$${fee}</strong> = <strong class="comparison-difference">${display}</strong>`));
    assert.match(row,/Below the full monthly fee/);assert.ok(row.includes(`Exact difference: USD ${difference}`));
  }
  assert.equal(wire.data.summary.value.amount_usd,'16.224690800000');
});

test('USD cent rounding retains sign, ties, grouping and sub-cent evidence without changing default detail precision',()=>{
  for(const [amount,expected]of [['-3.7753092','−$3.78'],['-83.7753092','−$83.78'],['9007199254740993.125','+$9,007,199,254,740,993.12'],['0','+$0.00'],['-0.000000000001','−$0.00'],['1.005','+$1.00'],['1.015','+$1.02']])assert.equal(formatDifference(amount,2),expected);
  assert.equal(formatMoney('0.000000000001',12),'0.000000000001');
  assert.equal(formatMoney('16.2246908'),'16.225');
  const wire=structuredClone(fixtures.priced_zero);wire.data.summary.value.amount_usd='0.000000000001';
  assert.match(render(wire),/USD 0\.000000000001/);
  assert.match(comparison({difference_usd:'0'}),/Equal to the full monthly fee/);
  assert.match(comparison({difference_usd:'0.001'}),/Above the full monthly fee/);
  assert.match(comparison({difference_usd:'-0.001'}),/Below the full monthly fee/);
});

test('ineligible comparisons never show an equation or a derived difference',()=>{
  for(const reason of ['period_not_month_to_date','metadata_filter','fee_unavailable','no_priced_usage']){
    const html=comparison({available:false,reason,difference_usd:null});
    const row=html.match(/<section class="comparison-item"><h2>Claude<\/h2>([\s\S]*?)<\/section>/)[1];
    assert.match(row,/Comparison unavailable/);assert.ok(row.includes(reason.replaceAll('_',' ')));
    assert.doesNotMatch(row,/comparison-difference|Exact difference|Below|Above| = /);
  }
  assert.match(comparison({fee_usd:'0.00',value_usd:'0.00',difference_usd:'0'}),/full monthly fee <strong>\$0\.00/);
  assert.match(comparison({fee_usd:null,available:false,difference_usd:null}),/full monthly fee <strong>Unavailable/);
});

test('closed data details retain visible empty, partial, unpriced, stale and incomplete coverage qualifications',()=>{
  for(const [name,essential]of [['empty','No recorded activity matches'],['partial','Unpriced:'],['unpriced','API value is unavailable']]){
    const html=render(fixtures[name]);
    assert.ok(html.indexOf(essential)<html.indexOf('<details class="banner quality-details">'));
    assert.doesNotMatch(html,/<details[^>]*\bopen(?:[ >])/);
  }
  const wire=structuredClone(fixtures.partial);wire.data.freshness='stale';wire.data.coverage[0].state='partial';
  const html=render(wire),visible=html.split('<details class="banner quality-details">')[0];
  assert.match(visible,/Retained local usage is stale/);assert.match(visible,/Excluded token amounts are unknown/);
  assert.match(visible,/Pricing uses assumptions/);assert.match(html,/<summary>Data details<\/summary>/);
  assert.match(html,/report counter quality/);
  assert.match(render(fixtures.priced_zero),/<span class="currency">USD<\/span>0\.00/);
  assert.match(comparison({pricing_state:'partial'}),/priced records only; unpriced usage is excluded/);
  const status=structuredClone(fixtures.status);status.data.last_job={status:'failed'};
  const failed=renderLocal({overview:wire,status},state);
  assert.ok(failed.indexOf('last local operation failed')<failed.indexOf('<details class="banner quality-details">'));
});

test('live-limit fills match remaining labels including boundaries, stale and unavailable states',()=>{
  const wire=structuredClone(fixtures.limits),p=wire.data.providers[0];
  p.state='available';p.snapshot={blocked:false,windows:[0,50,100].map(n=>({label:`Window ${n}`,remaining_percent:n,used_percent:100-n,resets_at:'2026-10-25T00:00:00.000000Z',duration_minutes:300}))};
  const show=()=>renderLocal({wire,status:fixtures.status},{...state,view:'limits'});
  const html=show();
  for(const n of [0,50,100]){assert.ok(html.includes(`${n}% remaining`));assert.ok(html.includes(`value="${n}" aria-label="codex Window ${n} remaining capacity"`));}
  assert.match(html,/Filled bar shows remaining capacity/);assert.match(html,/resets .* UTC/);
  p.state='stale';assert.match(show(),/last successful reading, not a current check/);
  p.snapshot.windows=[];assert.match(show(),/Remaining capacity unavailable/);assert.doesNotMatch(show(),/<progress/);
  p.state='unavailable';p.category='login_required';p.snapshot=null;
  const unavailable=show();assert.doesNotMatch(unavailable,/<progress|0% remaining/);assert.match(unavailable,/login required/);assert.match(unavailable,/Remaining capacity unavailable/);
});

test('quality details and exact money escape untrusted metadata',()=>{
  const wire=structuredClone(fixtures.partial);wire.data.summary.value.assumptions=['<img src=x onerror=alert(1)>'];
  const html=render(wire);assert.match(html,/&lt;img/);assert.doesNotMatch(html,/<img src=x/);
});
