import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import * as format from '../format.js';

// Actual app handlers, synthetic DOM/network/timers. Not a browser/focus certificate.
const source=readFileSync(new URL('../app.js',import.meta.url),'utf8');
const moduleImport=source.split('\n')[0].trim();
assert.match(moduleImport,/^import \{.*\} from '\.\/format.js';$/);
export const settle=()=>new Promise(setImmediate);
export function fixture(){
  return {dataset:'demo',usage_revision:'revision-1',range:{timezone:'UTC'},captured_at:1792800000,issues:[],
    summary:{tokens:{total_tokens:'190000'},value:{state:'priced',amount_usd:'18.420'},conversation_count:0,project_count:0},
    facets:{project:[],model:[],effort:[]},conversations:[],projects:[],models:[],days:[],
    comparisons:[],limits:[],pricing:{tier_policy:'Synthetic'},settings:{fees_usd:{},timezone:'UTC'},page:1,page_count:1};
}
export async function dashboard({initialStatus=200,initialPayload=fixture()}={}){
  const handlers={},timers=new Map(),nodes=new Map(),requests=[],responses=[],focusLog=[];
  let timerId=0;
  const location={hash:'#view=explore'};
  const node=(id)=>({id,dataset:{},textContent:'',attributes:{},setAttribute(k,v){this.attributes[k]=v;},removeAttribute(k){delete this.attributes[k];},
    focus(){document.activeElement=this;focusLog.push(id);},closest(){return null;},matches(){return false;}});
  for(const id of ['content','breadcrumb','mode','scope','connection','capture','notification','shortcuts'])nodes.set('#'+id,node(id));
  const document={activeElement:null,querySelector:s=>nodes.get(s)??null,querySelectorAll:()=>[],
    addEventListener:(name,handler)=>{handlers[name]=handler;}};
  const content=nodes.get('#content');
  Object.defineProperty(content,'innerHTML',{get(){return this.html;},set(html){
    this.html=html;nodes.delete('#search');
    if(html.includes('id="search"'))nodes.set('#search',Object.assign(node('search'),{
      value:html.match(/id="search"[^>]*value="([^"]*)"/)[1]
    }));
  }});
  content.insertAdjacentHTML=(_where,html)=>{content.html=html+content.html;};
  const response=(payload,status=200)=>({ok:status>=200&&status<300,status,json:async()=>structuredClone(payload)});
  responses.push(()=>response(initialPayload,initialStatus));
  const context=vm.createContext({...format,document,location,URLSearchParams,AbortController,Intl,console,
    window:{scrollY:0,scrollTo(){}},
    history:{pushState(_a,_b,url){location.hash=url;},replaceState(_a,_b,url){location.hash=url;}},
    addEventListener:(name,handler)=>{handlers[name]=handler;},
    setTimeout:(fn,delay)=>{timers.set(++timerId,{fn,delay});return timerId;},clearTimeout:id=>timers.delete(id),
    fetch:async(path,options)=>{requests.push({path,options});return responses.length?responses.shift()():response(fixture());}
  });
  vm.runInContext(source.slice(source.indexOf('\n')+1),context);
  await settle();
  return {
    location,handlers,document,nodes,focusLog,requestLog:requests,get requests(){return requests.length;},
    get html(){return content.html;},
    respond(payload,status=200){responses.push(()=>response(payload,status));},
    fail(){responses.push(()=>Promise.reject(new Error('synthetic network failure')));},
    defer(){let finish;const promise=new Promise(resolve=>{finish=(payload=fixture(),status=200)=>resolve(response(payload,status));});responses.push(()=>promise);return finish;},
    async input(value){const input=nodes.get('#search');input.value=value;document.activeElement=input;await handlers.input({target:input});},
    async click(action,extra={}){await handlers.click({target:{closest:selector=>selector==='[data-action]'?{dataset:{action,...extra}}:null}});},
    async navigate(view='limits'){await handlers.click({target:{closest:selector=>selector==='[data-nav]'?{dataset:{nav:view}}:null},preventDefault(){}});},
    async flushSearch(){for(const [id,timer]of [...timers])if(timer.delay===250){timers.delete(id);await timer.fn();}}
  };
}
