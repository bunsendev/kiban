import assert from 'node:assert/strict';
class Element {
 constructor(tag){this.tagName=tag;this.children=[];this.value='';this.style={};}
 append(n){this.children.push(n);}
 replaceChildren(){this.children=[];}
 setAttribute(k,v){this[k]=v;}
}
globalThis.document={createElement:tag=>new Element(tag)};
const notices=[];globalThis.window={alert:message=>notices.push(message)};
let setting={model:'gpt-4.1-mini',yen_per_usd:150,monthly_requests:240,monthly_budget_yen:5000};
let failure=false;
globalThis.fetch=async(url,options={})=>{
 assert.equal(url,'/api/ai-settings');
 if(options.method==='POST'){
  if(failure)return {ok:false,json:async()=>({detail:'設定を確認してください'})};
  setting=JSON.parse(options.body);
 }
 return {ok:true,json:async()=>({settings:setting,models:[{id:'gpt-4.1-mini',label:'mini',input:.4,output:1.6},{id:'gpt-6-luna',label:'luna',input:.1,output:.5}],price_date:'2026-10-13',month:'2026-10',calls:1,usd:.01,yen:1.5,month_end_yen:3,planned_yen:374.4,estimate_basis:'assumed_6000_input_5000_output',unknown_cost:1,groups:[],scope:'このPC'})};
};
const {aiUsage}=await import('../../portable/api/static/field/ai-usage.js');
const root=new Element('div');await aiUsage(root);
const all=n=>[n,...n.children.flatMap(all)];
const select=all(root).find(n=>n.tagName==='select');assert(select);assert.equal(select.children.length,2);
select.value='gpt-6-luna';
const save=all(root).find(n=>n.textContent==='モデル・費用設定を保存');
await save.onclick();assert.equal(setting.model,'gpt-6-luna');assert.equal(save.disabled,false);assert.equal(notices.length,1);
assert(all(root).some(n=>n.textContent?.includes('費用不明：1回')));
assert(all(root).some(n=>n.textContent?.includes('実績なし')));
failure=true;await save.onclick();assert.equal(save.disabled,false);assert.equal(notices.length,2);
console.log('PASS model dropdown, persistence request, assumed estimate, unknown cost, save success/failure');
