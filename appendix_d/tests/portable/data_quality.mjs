import assert from 'node:assert/strict';
import fs from 'node:fs';
class Element {
  constructor(tag){this.tag=tag;this.children=[];this.value='';this.textContent='';this.style={};}
  append(...nodes){this.children.push(...nodes);}
  appendChild(node){this.append(node);}
  replaceChildren(...nodes){this.children=[...nodes];}
  setAttribute(k,v){this[k]=v;}
}
globalThis.document={createElement:tag=>new Element(tag),createTextNode:text=>({textContent:text,children:[]})};
const {qualityPanel,methodFields}=await import('../../portable/api/static/field/data-quality.js');
const find=(root,fn)=>[...(fn(root)?[root]:[]),...root.children.flatMap(n=>find(n,fn))];
const text=root=>root.textContent+' '+root.children.map(text).join(' ');
const q={id:'fresh-check',recorded_at:'2026-10-27T00:00:00Z',required_start:'2026-09-16',
  required_end:'2026-10-13',missing_day_count:5,missing_record_count:5,
  coverage_percent:82.14,normal_series:0,provisional_series:1,status:'WARNING',
  warehouses:['神戸'],labels:{DATE_MISSING:'日付不足'},
  methods:{A:{enabled:false},B:{enabled:false,reason:'今後対応'},C:{enabled:true,reason:'暫定予測'}}};
const root=new Element('main');
const mode=methodFields(root,q);
assert.equal(mode().forecast_mode,'A');assert.equal(mode().check_id,'fresh-check');
const radios=find(root,n=>n.type==='radio');assert.equal(radios.length,3);
assert(radios[1].disabled);radios[0].checked=false;radios[2].checked=true;
assert.throws(mode,/同意/);
find(root,n=>n.type==='checkbox')[0].checked=true;
const request=mode();assert.equal(request.forecast_mode,'C');assert(request.confirm_provisional);
assert.equal(mode().request_id,request.request_id,'retries keep the request identity');
const disabled=new Element('main');methodFields(disabled,{...q,methods:{...q.methods,C:{enabled:false,reason:'モデル非対応'}}});
assert(find(disabled,n=>n.type==='radio'&&n.value==='C')[0].disabled);
let requested=[];
globalThis.fetch=async url=>{
  requested.push(String(url));let value;
  if(String(url).endsWith('/data-quality'))value=q;
  else if(String(url).includes('/issues?'))value={items:[{date:'2026-10-05',warehouse:'神戸',products:2,codes:['DATE_MISSING'],state:'UNRESOLVED',impacts:['対応モデルなら暫定予測可能']}],total:1};
  else throw new Error('Unexpected URL');
  return {ok:true,json:async()=>value};
};
const ctx={run:async fn=>fn(),home:async()=>{},open:async()=>{}};
const screen=new Element('main');await qualityPanel(ctx,screen,'analysis');
for(const label of ['不足 5日・5レコード','82.14%','日付不足','追加する','再検証','2026-10-05','予測への影響','対応モデルなら暫定予測可能'])assert(text(screen).includes(label),label);
assert(requested.some(u=>u.includes('group=true')&&u.includes('limit=50')));
assert(!fs.readFileSync('portable/api/static/field/data-quality.js','utf8').includes('innerHTML'));
assert(fs.readFileSync('portable/api/static/field/results.js','utf8').includes('v.provisional'));
console.log('PASS quality summary, bounded filters, method defaults, disabled B/C, explicit consent and idempotent request');
