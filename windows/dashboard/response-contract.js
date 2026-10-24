import {contractSchema} from './contract-schema.js';

export class ContractError extends Error {
  constructor(){super('The local service returned an unsupported response. Retry or update the application.');this.name='ContractError';this.code='invalid_response';}
}
const fail = () => {throw new ContractError();};
const own = (object,key) => Object.prototype.hasOwnProperty.call(object,key);
const supported=new Set(['$schema','$defs','title','description','$ref','anyOf','type','const','enum','properties','required','additionalProperties','items','minItems','maxItems','uniqueItems','minLength','maxLength','pattern','minimum','maximum']);

// Bounded validator for the keywords used by this candidate. This is not a
// general JSON Schema engine. Unknown assertion keywords fail closed.
export function validateSchema(schema,value,root=contractSchema,depth=0){
  if(depth>32)fail();
  for(const key of Object.keys(schema))if(!supported.has(key))fail();
  if(schema.$ref){
    if(!/^#\/\$defs\/[a-z_]+$/.test(schema.$ref))fail();
    const definition=root.$defs[schema.$ref.slice(8)];
    if(!definition)fail();
    return validateSchema(definition,value,root,depth+1);
  }
  if(schema.anyOf&&!schema.anyOf.some(candidate=>{try{validateSchema(candidate,value,root,depth+1);return true;}catch(error){if(!(error instanceof ContractError))throw error;return false;}}))fail();
  if(own(schema,'const')&&value!==schema.const)fail();
  if(schema.enum&&!schema.enum.includes(value))fail();
  if(schema.type){
    const type=Array.isArray(value)?'array':value===null?'null':typeof value;
    if(schema.type==='integer'?!Number.isSafeInteger(value):schema.type!==type)fail();
  }
  if(typeof value==='string'){
    const size=[...value].length;
    if(size<(schema.minLength??0)||size>(schema.maxLength??Infinity)||schema.pattern&&!new RegExp(schema.pattern,'u').test(value))fail();
  }
  if(typeof value==='number'&&(!Number.isFinite(value)||value<(schema.minimum??-Infinity)||value>(schema.maximum??Infinity)))fail();
  if(Array.isArray(value)){
    if(value.length<(schema.minItems??0)||value.length>(schema.maxItems??Infinity))fail();
    if(schema.uniqueItems&&new Set(value.map(item=>JSON.stringify(item))).size!==value.length)fail();
    if(schema.items)for(const item of value)validateSchema(schema.items,item,root,depth+1);
  }
  if(value&&typeof value==='object'&&!Array.isArray(value)){
    for(const key of schema.required??[])if(!own(value,key))fail();
    if(schema.properties)for(const key of Object.keys(value)){
      if(own(schema.properties,key))validateSchema(schema.properties[key],value[key],root,depth+1);
      else if(schema.additionalProperties===false)fail();
    }
  }
  return value;
}

// Semantic consistency guards reject malformed data; they do not calculate
// prices, sort results, or replace authoritative totals with browser sums.
function checkSemantics(value,key=''){
  if(!value||typeof value!=='object')return;
  if(key==='range'){
    if(!Number.isFinite(Date.parse(value.start_at))||!Number.isFinite(Date.parse(value.end_at))||Date.parse(value.start_at)>=Date.parse(value.end_at))fail();
    try{new Intl.DateTimeFormat('en',{timeZone:value.timezone});}catch{fail();}
  }
  if(key==='value'){
    const {state,amount_usd,priced_record_count:p,unpriced_record_count:u}=value;
    if(state==='complete'&&!(p>0&&u===0&&amount_usd!==null)||state==='partial'&&!(p>0&&u>0&&amount_usd!==null)||state==='unpriced'&&!(p===0&&u>0&&amount_usd===null)||state==='empty'&&!(p===0&&u===0&&amount_usd===null))fail();
  }
  if(key==='valuation'&&(value.state==='priced')!==(value.amount_usd!==null))fail();
  if(key==='plan_comparison'){
    if(value.state==='unavailable'&&(!value.reason||value.difference_usd!==null)||value.state!=='unavailable'&&(value.reason!==null||value.fee_usd===null||value.difference_usd===null))fail();
  }
  if(key==='coverage'&&value.index_status==='stale'&&value.last_successful_scan_at===null)fail();
  if(key==='job'){
    if(['succeeded','failed','superseded'].includes(value.state)!==(value.completed_at!==null))fail();
    if(value.state==='queued'&&value.started_at!==null||value.state==='running'&&value.started_at===null)fail();
    if(value.total_count!==null&&value.completed_count>value.total_count)fail();
  }
  for(const [child,item] of Object.entries(value)){
    if(typeof item==='string'&&/(?:_at)$/.test(child)){
      if(!Number.isFinite(Date.parse(item))||new Date(item).toISOString().slice(0,19)!==item.slice(0,19))fail();
    }
    if(typeof item==='string'&&['day','selected_day'].includes(child)&&(!Number.isFinite(Date.parse(item+'T00:00:00Z'))||new Date(item+'T00:00:00Z').toISOString().slice(0,10)!==item))fail();
    if(Array.isArray(item))item.forEach(entry=>checkSemantics(entry,child));else checkSemantics(item,child);
  }
}
export function validateResponse(kind,payload){
  if(!['overview','conversations','detail','events','facets','status','job_response','error'].includes(kind))fail();
  validateSchema(contractSchema.$defs[kind],payload);
  checkSemantics(payload);
  return structuredClone(payload);
}
