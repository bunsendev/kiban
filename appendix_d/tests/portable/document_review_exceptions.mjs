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
