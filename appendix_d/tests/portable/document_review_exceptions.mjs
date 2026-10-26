import assert from 'node:assert/strict';
import './document_review_table.mjs';
import {reviewTable,serializeControls} from '../../portable/api/static/field/document-review-table.js';
const host=document.createElement('main');
const all=n=>[n,...n.children.flatMap(all)];
const valid={kind:'inventory',jan:'4901234567894',product_name:'人工',product_code:'P',
 quantity:'10',case_factor:'1',unit:'箱',location:'人工倉庫',snapshot:'2026-10-13',expiry:'2027-01-01',page:'1'};
let compared;
const table=reviewTable({run:fn=>fn(),message:()=>{}},host,[valid,{...valid,jan:''}],
 {choice:{value:''}}, {classifications:[{status:'READY',causes:[]},{status:'HOLD',causes:['商品識別']}],
 causes:{商品識別:1},onSource:(i,row)=>{compared={i,row};}});
const rows=all(host).find(n=>n.tagName==='tbody').children;
assert.equal(rows[0].hidden,true);
assert.equal(rows[1].hidden,false);
assert(all(host).some(n=>n.textContent?.includes('機械点検通過 1行')));
assert(!all(host).some(n=>n.textContent==='表示中のボール・バラの意味を確認済みにする'));
table.edits[0].quantity.value='99';table.update();
assert.equal(rows[0].hidden,false);
assert(all(host).some(n=>n.textContent==='編集後の原本確認'));
all(host).find(n=>n.textContent==='この行の原本ページと比較').onclick();
assert.equal(compared.i,0);assert.equal(compared.row.quantity,'99');
assert.equal(serializeControls(table.edits[0]).component_rule_version,'');
console.log('PASS exception-first counts, edited-row guard and source comparison callback');

// Screenshot regression: successful extraction with no exceptions must remain visible.
const cleanHost=document.createElement('main');
const clean=reviewTable({run:fn=>fn(),message:()=>{}},cleanHost,
 [valid,{...valid,exclude:true,reason:'人工対象外'}],{choice:{value:''}},
 {classifications:[{status:'READY',causes:[]},{status:'EXCLUDED',causes:[]}],causes:{}});
const cleanRows=all(cleanHost).find(n=>n.tagName==='tbody').children;
const cleanFilter=all(cleanHost).find(n=>n.attributes?.['aria-label']==='表示する行');
assert.equal(cleanFilter.value,'ready');assert.equal(cleanRows[0].hidden,false);assert.equal(cleanRows[1].hidden,true);
cleanFilter.value='exceptions';clean.update();
assert(cleanRows.every(r=>r.hidden));
assert(all(cleanHost).some(n=>n.textContent?.includes('抽出は完了しています')));
all(cleanHost).find(n=>n.textContent==='機械点検通過の明細を表示').onclick();
assert.equal(cleanRows[0].hidden,false);
const search=all(cleanHost).find(n=>n.type==='search');search.value='NO-MATCH';clean.update();
assert(cleanRows.every(r=>r.hidden));
assert(all(cleanHost).some(n=>n.textContent?.includes('検索・表示条件に一致する行がありません')));
all(cleanHost).find(n=>n.textContent==='検索・絞り込みを解除してすべて表示').onclick();
assert(cleanRows.every(r=>!r.hidden));assert.equal(clean.edits[1].exclude.checked,true);
const noneHost=document.createElement('main');
reviewTable({run:fn=>fn(),message:()=>{}},noneHost,[],{choice:{value:''}},{classifications:[],causes:{}});
assert(all(noneHost).some(n=>n.textContent?.includes('抽出された明細がありません')));
const excludedHost=document.createElement('main');
reviewTable({run:fn=>fn(),message:()=>{}},excludedHost,[{...valid,exclude:true,reason:'人工対象外'}],{choice:{value:''}},
 {classifications:[{status:'EXCLUDED',causes:[]}],causes:{}});
assert(all(excludedHost).some(n=>n.textContent?.includes('すべて除外予定')));
all(excludedHost).find(n=>n.textContent==='除外予定の明細を表示').onclick();
assert.equal(all(excludedHost).find(n=>n.tagName==='tbody').children[0].hidden,false);
console.log('PASS successful extraction default visibility, explicit empty states, filters reset without approval or exclusion changes');

// Ready rows summarize the actual controls. Opening details is not approval and
// editing a normal value must bring the row back to exception review.
const simpleHost=document.createElement('main');
const simple=reviewTable({run:fn=>fn(),message:()=>{}},simpleHost,[valid],{choice:{value:''}},
 {classifications:[{status:'READY',causes:[]}],causes:{}});
const compact=all(simpleHost).find(n=>n.className==='document-normal-cell');
const editRow=all(simpleHost).find(n=>n.tagName==='tbody').children[0];
const originalJSON=JSON.stringify(serializeControls(simple.edits[0]));
assert.equal(compact.hidden,false);assert.equal(editRow.children[0].hidden,true);
assert(all(compact).some(n=>n.textContent?.includes('数量 10 箱')));
all(compact).find(n=>n.textContent==='この明細の詳細を開く').onclick();
assert.equal(compact.hidden,true);assert.equal(editRow.children[0].hidden,false);
assert.equal(JSON.stringify(serializeControls(simple.edits[0])),originalJSON);
simple.edits[0].quantity.value='77';simple.update();
assert.equal(compact.hidden,true);
assert.equal(editRow.hidden,false);
assert(all(simpleHost).some(n=>n.textContent==='編集後の原本確認'));
console.log('PASS compact normal rows, unchanged details opening and edited-row exception visibility');
