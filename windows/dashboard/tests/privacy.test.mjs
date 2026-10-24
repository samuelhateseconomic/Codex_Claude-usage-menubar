import test from 'node:test';
import assert from 'node:assert/strict';
import {dashboard, fixture} from './dashboard-harness.mjs';

test('source labels render inert markup and visible controls while filter identities stay exact', async()=>{
  const hostile='label\u202e\u001b'+'"><script>fixture()</script>';
  const data=fixture();
  data.facets={project:[hostile],model:[hostile],effort:[hostile]};
  data.conversations=[{id:'a'.repeat(32),project:hostile,session:hostile,provider:'Codex',models:[hostile],efforts:[hostile],
    tokens:{total_tokens:'190000'},value:{state:'complete',amount_usd:'1'},last_at:1792800000}];
  const app=await dashboard({initialPayload:data});
  assert.ok(app.html.includes(`value="${hostile.replaceAll('"','&quot;').replaceAll('<','&lt;').replaceAll('>','&gt;')}"`));
  assert.ok(app.html.includes(String.raw`label\u202e\u001b&quot;&gt;&lt;script&gt;fixture()&lt;/script&gt;</option>`));
  assert.ok(app.html.includes(String.raw`label\u202e\u001b&quot;&gt;&lt;script&gt;fixture()&lt;/script&gt;</button>`));
  assert.doesNotMatch(app.html,/<script>/);
});

test('null fees remain unavailable without a fabricated currency amount',async()=>{
  const data=fixture();
  data.settings.fees_usd={Codex:null,Claude:'0'};
  const app=await dashboard({initialPayload:data});
  app.respond(data);
  await app.navigate('settings');
  assert.ok(app.html.includes('>Unavailable</strong>'));
  assert.ok(app.html.includes('$0.00 / month'));
  assert.ok(!app.html.includes('$Unavailable'));
});
