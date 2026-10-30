import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

class Element {
  constructor(tag){this.tag=tag;this.children=[];this.style={};this.value='';this.textContent='';this.listeners={};this.checked=false;}
  append(...nodes){this.children.push(...nodes);}
  appendChild(node){this.append(node);}
  replaceChildren(...nodes){this.children=[...nodes];}
  setAttribute(k,v){this[k]=v;}
  addEventListener(name,fn){this.listeners[name]=fn;}
  scrollIntoView(){} focus(){}
}
const nodes=new Map();
globalThis.document={createElement:tag=>new Element(tag),createTextNode:text=>({textContent:text,children:[]}),
  getElementById:id=>{if(!nodes.has(id))nodes.set(id,new Element('div'));return nodes.get(id);},
  addEventListener(){},dispatchEvent(){}};
const {createDetailedForecastMethods}=await import('../../portable/api/static/field/detailed-forecast-methods.js');
const flat=n=>[n,...n.children.flatMap(flat)];
const text=n=>(n.textContent||'')+' '+n.children.map(text).join(' ');
let q={id:'check-1',recorded_at:'2026-10-30T00:00:00Z',status:'WARNING',
  missing_day_count:5,missing_record_count:5,coverage_percent:82.14,normal_series:0,
  provisional_series:1,warehouses:['人工倉庫'],labels:{DATE_MISSING:'日付不足'},
  methods:{A:{enabled:false},B:{enabled:false,reason:'今後対応'},C:{enabled:true,reason:'暫定予測可能'}}};
let posted=[];
globalThis.fetch=async(url,options={})=>{
  let value;
  if(url.endsWith('/data-quality'))value=q;
  else if(url.includes('/issues?'))value={items:[],total:0};
  else if(url.endsWith('/advance')){posted.push(JSON.parse(options.body));value={analysis_id:'analysis-1',status:'PRODUCTION_RUNNING',next_action:'計算中',blockers:[]};}
  else throw new Error('Unexpected URL '+url);
  return {ok:true,json:async()=>value};
};
const controller=createDetailedForecastMethods({qualityRoot:document.getElementById('daily-data-quality'),
  methodRoot:document.getElementById('daily-forecast-method'),run:async fn=>fn(),reopen:async()=>{},home:async()=>{}});
const sandbox={document,fetch:globalThis.fetch,window:{},setTimeout:()=>1,console,
  CustomEvent:class {},testMethods:controller};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync('portable/api/static/daily-auto-run.js','utf8'),sandbox);
// Supply the real shared controller at the asynchronous module boundary.
vm.runInContext('dailyMethodsPromise=Promise.resolve(testMethods)',sandbox);
const blocked={analysis_id:'analysis-1',status:'FORECAST_BLOCKED',next_action:'履歴の不足を確認',
  blockers:[{source_center:'人工倉庫',jan:'人工JAN',reason_codes:['HISTORY_LESS_THAN_28_DAYS'],recognized_required_days:23}]};
await sandbox.renderDailyRun(blocked);
const form=document.getElementById('daily-run-form'),methodRoot=document.getElementById('daily-forecast-method');
assert.equal(form.hidden,false,'blocked normal forecast still exposes the retry/method form');
assert(text(methodRoot).includes('C')&&text(methodRoot).includes('欠損を残して暫定予測'));
assert.equal(controller.read('analysis-1').forecast_mode,'A');
const radios=flat(methodRoot).filter(n=>n.type==='radio');
assert.equal(radios.length,3);assert(radios[1].disabled&&!radios[2].disabled);
radios[0].checked=false;radios[2].checked=true;
for(const id of ['daily-run-actor','daily-run-reason'])document.getElementById(id).value='人工確認';
document.getElementById('forecast-batch-size').value='100';
for(const id of ['daily-confirm-scope','daily-confirm-quantity','daily-confirm-identity','daily-confirm-zero'])document.getElementById(id).checked=true;
await form.listeners.submit({preventDefault(){}});
assert.equal(posted.length,0,'C without consent must not submit any request');
assert(document.getElementById('daily-run-status').textContent.includes('同意'));
flat(methodRoot).find(n=>n.type==='checkbox').checked=true;
await form.listeners.submit({preventDefault(){}});
assert.equal(posted.length,1);assert.equal(posted[0].forecast_mode,'C');
assert.equal(posted[0].check_id,'check-1');assert(posted[0].confirm_provisional&&posted[0].request_id);
await controller.show('analysis-1');
assert.equal(controller.read('analysis-1').request_id,posted[0].request_id,'same check preserves selection/request');
q={...q,id:'check-2'};
await controller.show('analysis-1');
assert.equal(controller.read('analysis-1').forecast_mode,'A','changed input requires new explicit consent');
assert.throws(()=>controller.read('another-analysis'),/完了/);
q={...q,provisional_series:0,methods:{...q.methods,C:{enabled:false,reason:'確認済み実績がモデルの最小7日未満です'}}};
await sandbox.renderDailyRun(blocked);
assert(flat(methodRoot).find(n=>n.type==='radio'&&n.value==='C').disabled);
assert(text(document.getElementById('daily-run-result')).includes('最小7日未満'));
const page=fs.readFileSync('portable/api/static/index.html','utf8');
assert(page.includes('id="daily-forecast-method"')&&page.includes('id="daily-data-quality"'));
assert(!fs.readFileSync('portable/api/static/field/detailed-forecast-methods.js','utf8').includes('innerHTML'));
console.log('PASS detailed entry: visible C after normal block, explicit consent, complete payload, stale check reset and disabled reason');
