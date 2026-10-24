import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
const source=readFileSync(new URL('../api-bootstrap.js',import.meta.url),'utf8').replace(/^\uFEFF/,'');
async function run({hash='',session={csrf_token:'synthetic-csrf'},status={ready:true,indexing:false,freshness:'current'},sessionOK=true,statusOK=true,fail=false}={}) {
  const trace=[];
  const state={textContent:'Open this local service through Usage Tray.'};
  const context={URLSearchParams,location:{hash,pathname:'/'},
    history:{replaceState:(...args)=>trace.push({type:'history',url:args[2]})},
    document:{getElementById:()=>state},
    fetch:async(url,options)=>{
      trace.push({type:'fetch',url,options});
      if(fail)throw new Error('synthetic network failure');
      return {ok:url.endsWith('status')?statusOK:sessionOK,json:async()=>({data:url.endsWith('status')?status:session})};
    }};
  Object.defineProperty(context,'localStorage',{get(){throw new Error('no durable browser secrets');}});
  Object.defineProperty(context,'sessionStorage',{get(){throw new Error('no browser secret storage');}});
  await vm.runInNewContext(source,context);
  return {trace,text:state.textContent};
}
test('launch fragment is removed before exchange and cookie stays browser-managed',async()=>{
  const result=await run({hash:'#launch=synthetic-launch'});
  assert.deepEqual(result.trace[0],{type:'history',url:'/'});
  const exchange=result.trace[1];
  assert.equal(exchange.url,'/api/v1/session/bootstrap');
  assert.equal(exchange.options.credentials,'same-origin');
  assert.equal(JSON.parse(exchange.options.body).launch_token,'synthetic-launch');
  assert.equal(result.text,'Local usage service is ready.');
});
test('reload resumes an existing session without creating a launch grant',async()=>{
  const result=await run();
  assert.equal(result.trace[1].url,'/api/v1/session');
  assert.equal(result.trace[1].options.credentials,'same-origin');
  assert.equal(result.text,'Local usage service is ready.');
});
test('first-run and failed indexing states are distinct',async()=>{
  assert.match((await run({status:{ready:false,indexing:true}})).text,/being indexed/);
  const failed=await run({status:{ready:false,indexing:false}});
  assert.match(failed.text,/unavailable/);assert.doesNotMatch(failed.text,/being indexed/);
});
test('retained state is labeled and failed authentication never announces readiness',async()=>{
  assert.match((await run({status:{ready:true,freshness:'stale'}})).text,/retained or stale/);
  for(const options of [{sessionOK:false},{statusOK:false},{session:{csrf_token:''}},{fail:true}]) {
    const result=await run(options);assert.match(result.text,/expired or failed/);assert.doesNotMatch(result.text,/is ready/);
  }
});
