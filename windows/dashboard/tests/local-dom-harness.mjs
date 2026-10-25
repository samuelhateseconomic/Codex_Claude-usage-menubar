// Actual production handlers with a small synthetic DOM. Browser checks are separate.
import {mountLocalDashboard} from '../local-app.js';
export async function localDashboard(client,{hash='#view=explore'}={}){
  const handlers={},nodes=new Map(),timers=new Map(),focusLog=[],entries=[];let timer=0,index=-1;
  const location={hash,pathname:'/'};
  const make=id=>({id,dataset:{},attributes:{},textContent:'',value:'',open:false,setAttribute(k,v){this.attributes[k]=v;},removeAttribute(k){delete this.attributes[k];},focus(){document.activeElement=this;focusLog.push(id);},showModal(){this.open=true;},close(){this.open=false;},closest(){return null;}});
  for(const id of ['content','breadcrumb','mode','scope','capture','connection','notification','shortcuts'])nodes.set('#'+id,make(id));
  const document={activeElement:null,querySelector:s=>nodes.get(s)??null,querySelectorAll:()=>[],addEventListener:(k,f)=>{handlers[k]=f;}};
  const content=nodes.get('#content');
  Object.defineProperty(content,'innerHTML',{get(){return this.html;},set(html){this.html=html;for(const key of ['#search','#settings-result','#operation-status'])nodes.delete(key);if(html.includes('id="search"'))nodes.set('#search',Object.assign(make('search'),{value:html.match(/id="search"[^>]*value="([^"]*)"/)[1]}));if(html.includes('id="settings-result"'))nodes.set('#settings-result',make('settings-result'));if(html.includes('id="operation-status"'))nodes.set('#operation-status',Object.assign(make('operation-status'),{innerHTML:html.match(/id="operation-status"[^>]*>([\s\S]*?)<\/section>/)[1]}));}});
  content.insertAdjacentHTML=(_,html)=>{content.html=html+content.html;};
  const history={get state(){return entries[index]?.data??null;},replaceState(data,_,url){location.hash=url.startsWith('#')?url:url.includes('#')?'#'+url.split('#')[1]:'';if(index<0){entries.push({data:structuredClone(data),hash:location.hash});index=0;}else entries[index]={data:structuredClone(data),hash:location.hash};},pushState(data,_,url){entries.splice(index+1);entries.push({data:structuredClone(data),hash:url});index++;location.hash=url;}};
  const window={scrollY:0,scrollTo(_x,y){this.scrollY=y;},addEventListener:(k,f)=>{handlers[k]=f;},setTimeout:(fn,ms)=>{timers.set(++timer,{fn,ms});return timer;},clearTimeout:id=>timers.delete(id),navigator:{clipboard:{writeText:async()=>{}}}};
  const app=mountLocalDashboard({document,window,history,location,client});await app.ready;
  return {app,handlers,nodes,location,window,focusLog,entries,get html(){return content.html;},get historyState(){return history.state;},
    async click(action,extra={}){await handlers.click({target:{closest:s=>s==='[data-action]'?{dataset:{action,...extra}}:null}});},
    async nav(view){await handlers.click({target:{closest:s=>s==='[data-nav]'?{dataset:{nav:view}}:null},preventDefault(){}});},
    async change(id,value){await handlers.change({target:{id,value}});},
    async input(value){const input=nodes.get('#search');input.value=value;document.activeElement=input;await handlers.input({target:input});},
    async setting(key,value){await handlers.input({target:{id:'setting',dataset:{setting:key},value}});},
    async flush(){for(const [id,t]of [...timers])if(t.ms===250){timers.delete(id);await t.fn();}},
    async expireNotifications(){for(const [id,t]of [...timers])if(t.ms===6000){timers.delete(id);await t.fn();}},
    async browserBack(){if(index<=0)return;index--;location.hash=entries[index].hash;await handlers.popstate({state:structuredClone(entries[index].data)});}
  };
}
