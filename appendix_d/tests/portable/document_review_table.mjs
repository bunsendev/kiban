import assert from 'node:assert/strict';
import {rowProblems,reviewTable,serializeControls} from '../../portable/api/static/field/document-review-table.js';
import {inventoryCheckPanel} from '../../portable/api/static/field/document-inventory-checks.js';
const valid={kind:'inventory',jan:'4901234567894',product_name:'テスト商品',product_code:'P1',quantity:'0',unit:'箱',case_factor:'1',location:'テスト倉庫',snapshot:'2026-10-07',expiry:'2026-12-31',page:'1'};
assert.equal(rowProblems(valid).errors.length,0);
assert(rowProblems({...valid,jan:''}).errors.some(e=>e.key==='jan'));
assert(rowProblems({...valid,jan:'4901234567895'}).errors.some(e=>e.message.includes('チェック桁')));
assert(rowProblems({...valid,expiry:'2026-02-30'}).errors.some(e=>e.key==='expiry'));
assert(rowProblems({...valid,expiry:'0000-01-01'}).errors.some(e=>e.key==='expiry'));
assert(rowProblems({...valid,quantity:''}).errors.some(e=>e.key==='quantity'));
assert(rowProblems({...valid,quantity:'0x20'}).errors.some(e=>e.key==='quantity'));
assert(rowProblems({...valid,case_factor:'0'}).errors.some(e=>e.key==='case_factor'));
assert.equal(rowProblems({...valid,kind:'shipment',date:'2026-10-07',snapshot:'',expiry:''}).errors.length,0);
const component={...valid,case_quantity:'0',loose_quantity:'0',component_confirmed:true,quantity:'',case_factor:''};
assert.equal(rowProblems(component).errors.length,0);
assert(rowProblems({...component,loose_quantity:''}).errors.some(e=>e.key==='loose_quantity'));
assert(rowProblems({...component,loose_quantity:'2',units_per_case:''}).errors.some(e=>e.key==='units_per_case'));
assert(rowProblems({...component,component_confirmed:false}).errors.some(e=>e.key==='component_confirmed'));
assert.equal(rowProblems({...valid,exclude:true,reason:'原本に該当なし',jan:''}).errors.length,0);
assert(rowProblems({...valid,exclude:true,reason:''}).errors.some(e=>e.key==='reason'));
assert(rowProblems({...valid,unit:'g'}).warnings.some(e=>e.includes('単位')));
class Element extends EventTarget {
 constructor(tag){super();this.tagName=tag;this.children=[];this.style={};this.value='';this.checked=false;this.hidden=false;this.attributes={};}
 append(n){this.children.push(n);n.parentElement=this;}
 setAttribute(k,v){this.attributes[k]=v;}
 removeAttribute(k){delete this.attributes[k];}
 replaceChildren(){this.children=[];}
 scrollIntoView(){}
}
globalThis.document={createElement:tag=>new Element(tag)};
const checkHost=new Element('main');
inventoryCheckPanel(checkHost,{inventory_checks:{inventory_rows:2,match:1,mismatch:1,unverifiable:0,unchecked:0,basis:'読取時',assumption:'診断用',field_issues:[],repeated_buckets:[],movement_rows:[{page:'2',jan:'4901234567894',status:'mismatch',difference:-20}]}});
assert.equal(checkHost.children.length,1);
const messages=n=>[n.textContent||'',...n.children.flatMap(messages)];
assert(messages(checkHost).some(s=>s.includes('不一致 1行')));
assert(messages(checkHost).some(s=>s.includes('2ページ')&&s.includes('-20')));
const oldHost=new Element('main');inventoryCheckPanel(oldHost,{});assert.equal(oldHost.children.length,0);
const all=n=>[n,...n.children.flatMap(all)],host=new Element('main');
const table=reviewTable({run:fn=>fn(),message:()=>{}},host,[valid,{...valid,jan:'',expiry:'',location:''}],{choice:{value:''}});
const rows=all(host).filter(n=>n.tagName==='tbody')[0].children;
assert.equal(rows.length,2);assert.equal(rows[0].hidden,false);assert.equal(rows[1].hidden,false);
assert.equal(table.edits.length,2);
assert.equal(table.edits[1].jan.attributes['aria-invalid'],'true');
assert(all(host).some(n=>n.textContent?.includes('JANが未入力')));
const filter=all(host).find(n=>n.tagName==='select'&&n.children.some(c=>c.value==='errors'));
filter.value='errors';filter.dispatchEvent(new Event('change'));
assert.equal(rows[0].hidden,true);assert.equal(rows[1].hidden,false);
table.edits[1].jan.value=valid.jan;table.edits[1].expiry.value=valid.expiry;table.edits[1].location.value=valid.location;table.update();
assert.equal(rows[1].hidden,true);assert.equal(table.edits[1].jan.attributes['aria-invalid'],undefined);
const search=all(host).find(n=>n.type==='search');filter.value='all';search.value='NO-MATCH';table.update();assert(rows.every(r=>r.hidden));
assert.equal(serializeControls(table.edits[0]).quantity,'0');
all(host).find(n=>n.textContent==='原本から明細を追加する').onclick();
assert.equal(table.edits.length,3);assert(rows.every(r=>!r.hidden));
console.log('PASS: JAN/date/quantity checks, blank vs zero, component confirmation, exclusion, visible table errors, filter/search/edit/new row');

const batchHost=new Element('main');
const batchTable=reviewTable({run:fn=>fn(),message:()=>{}},batchHost,[
 {...valid,case_quantity:'12',loose_quantity:'',units_per_case:'20',component_confirmed:false},
 {...valid,kind:'shipment',case_quantity:'3',loose_quantity:'',component_confirmed:false}
],{choice:{value:''}});
all(batchHost).find(n=>n.textContent==='表示中の在庫の空欄を0にする').onclick();
assert.equal(batchTable.edits[0].loose_quantity.value,'0');
assert.equal(batchTable.edits[1].loose_quantity.value,'');
all(batchHost).find(n=>n.textContent==='表示中のボール・バラの意味を確認済みにする').onclick();
assert.equal(batchTable.edits[0].component_confirmed.checked,true);
assert.equal(batchTable.edits[0].product_name.tagName,'textarea');
console.log('PASS: explicit batch inventory zero preserves shipment blanks and batch confirmation');

const exclusionHost=new Element('main');
reviewTable({run:fn=>fn(),message:()=>{}},exclusionHost,[{...valid,exclude:true,reason:'人工対象外',registered_exclusion:true}],{choice:{value:''}});
const excludedRow=all(exclusionHost).find(n=>n.tagName==='tbody').children[0];
assert.equal(excludedRow.hidden,true);
const excludedFilter=all(exclusionHost).find(n=>n.tagName==='select'&&n.children.some(c=>c.value==='excluded'));
excludedFilter.value='excluded';excludedFilter.dispatchEvent(new Event('change'));
assert.equal(excludedRow.hidden,false);
console.log('PASS default target-only filter and excluded-list visibility');
