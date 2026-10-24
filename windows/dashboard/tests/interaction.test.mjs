import test from 'node:test';
import assert from 'node:assert/strict';
import {dashboard} from './dashboard-harness.mjs';

test('Clear filters cancels a search that has not yet been submitted',async()=>{
  const app=await dashboard();
  await app.input('portfolio');
  await app.click('clear');
  await app.flushSearch();
  assert.equal(new URLSearchParams(app.location.hash.slice(1)).get('q'),null);
  assert.equal(app.nodes.get('#search').value,'');
  assert.equal(app.requests,2); // Initial query and the explicit clear only.
});

test('leaving Explore cancels its pending search',async()=>{
  const app=await dashboard();
  await app.input('portfolio');
  await app.navigate();
  await app.flushSearch();
  const params=new URLSearchParams(app.location.hash.slice(1));
  assert.equal(params.get('view'),'limits');
  assert.equal(params.get('q'),null);
  assert.equal(app.requests,2);
});

test('global navigation shortcuts do not run behind an open modal',async()=>{
  const app=await dashboard();
  app.nodes.get('#shortcuts').open=true;
  const before=app.location.hash;
  await app.handlers.keydown({key:'/',target:{closest:()=>null},preventDefault(){}});
  assert.equal(app.location.hash,before);
  assert.equal(app.requests,1);
});
