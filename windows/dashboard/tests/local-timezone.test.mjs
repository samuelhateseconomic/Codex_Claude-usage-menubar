import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {renderLocal} from '../local-view.js';
import {validateV1} from '../v1-client.js';
import {localDashboard} from './local-dom-harness.mjs';
const fixtures=JSON.parse(readFileSync(new URL('../../../docs/api/usage-hub-v1.fixtures.json',import.meta.url)));
const copy=structuredClone;
const state={view:'limits',provider:'both',period:'month'};

test('live-limit resets and refresh timestamps use the configured LA zone with PDT/PST',()=>{
  const wire=copy(fixtures.limits),p=wire.data.providers[0];
  wire.data.timezone_info={name:'America/Los_Angeles',source:'system'};
  p.state='available';p.last_attempt_at=p.last_success_at=p.next_eligible_at='2026-10-25T00:00:00.000000Z';
  p.snapshot={blocked:false,windows:[{label:'Summer',remaining_percent:50,resets_at:'2026-10-25T00:00:00.000000Z'},{label:'Winter',remaining_percent:75,resets_at:'2026-12-25T00:00:00.000000Z'}]};
  const html=renderLocal({wire,status:fixtures.status},state);
  assert.match(html,/America\/Los_Angeles · Automatic \(system timezone\)/);
  assert.match(html,/Oct 24, 2026, 5:00 PM PDT/);
  assert.match(html,/Dec 24, 2026, 4:00 PM PST/);
  assert.match(html,/Last attempt: Oct 24, 2026, 5:00 PM PDT/);
  assert.match(html,/Last success: Oct 24, 2026, 5:00 PM PDT/);
  assert.match(html,/Next eligible: Oct 24, 2026, 5:00 PM PDT/);
  assert.equal(p.last_attempt_at,'2026-10-25T00:00:00.000000Z');
  wire.data.timezone_info={name:'UTC',source:'fallback'};
  assert.match(renderLocal({wire,status:fixtures.status},state),/System timezone unavailable · UTC fallback/);
});

test('Automatic mode saves one authoritative preference and manual override remains editable',async()=>{
  let settings=copy(fixtures.settings),sent;
  const api={authenticate:async()=>{},read:async kind=>copy(kind==='settings'?settings:fixtures[kind]),
    mutate:async(kind,data)=>{
      sent=data;settings.data.settings.timezone=data.changes.timezone;
      return {data:{...copy(fixtures.settings_saved.data),jobs:[],pending:false}};
    }};
  const ui=await localDashboard(api,{hash:'#view=settings'});
  assert.match(ui.html,/Automatic — system timezone/);
  await ui.change('settings-timezone-mode','auto');
  assert.match(ui.html,/<option value="auto" selected>/);
  assert.match(ui.html,/America\/Los_Angeles · Automatic/);
  assert.doesNotMatch(ui.html,/id="settings-timezone" /);
  await ui.click('save-settings');assert.equal(sent.changes.timezone,'auto');
  assert.deepEqual(sent.changes.plan_fees_usd,fixtures.settings.data.settings.plan_fees_usd);
  await ui.change('settings-timezone-mode','manual');
  assert.match(ui.html,/id="settings-timezone" /);
  await ui.setting('timezone','Asia/Tokyo');await ui.click('save-settings');
  assert.equal(sent.changes.timezone,'Asia/Tokyo');
  ui.app.dispose();
});

test('timezone information is a strict allowlisted API contract',()=>{
  assert.doesNotThrow(()=>validateV1('limits',fixtures.limits));
  for(const bad of [{name:'UTC',source:'invented'},{name:'UTC',source:'system',raw_registry:'private'}]){
    const wire=copy(fixtures.limits);wire.data.timezone_info=bad;
    assert.throws(()=>validateV1('limits',wire));
  }
});
