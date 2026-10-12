import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
class Element {constructor(tag){this.tag=tag;this.children=[];this.style={};this.textContent='';}appendChild(n){this.children.push(n);}}
const sandbox={document:{createElement:tag=>new Element(tag)}};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync('portable/api/static/forecast-blockers.js','utf8'),sandbox);
const root=new Element('main');
sandbox.renderForecastBlockers(root,{blockers:[{source_center:'人工倉庫',jan:'人工JAN',reason_codes:['HISTORY_LESS_THAN_28_DAYS','INVENTORY_SHIPMENT_AS_OF_MISMATCH'],observed_day_count:1,confirmed_zero_day_count:0,train_start:'2026-10-11',train_end:'2026-10-11',inventory_snapshot_date:'2026-10-12'},{reason_codes:['RECENT_SOURCE_DAYS_MISSING']}]});
const texts=n=>n.textContent+' '+n.children.map(texts).join(' ');
const result=texts(root);
for(const phrase of ['不足 27日','過去の出荷CSV','同じ基準日','2026-10-11','2026-10-12','欠測','IT担当者','入力だけでは解消しません'])assert(result.includes(phrase),phrase);
assert(!result.includes('表示された確認欄で修正してください'));
console.log('PASS blocker details, counts, date mismatch and next actions');

assert(fs.readFileSync('portable/api/static/daily-auto-run.js','utf8').startsWith(fs.readFileSync('portable/api/static/forecast-blockers.js','utf8')));
