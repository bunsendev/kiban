import assert from 'node:assert/strict';
import {analysis,waitJob} from '../../portable/api/static/field/progress.js';
class Element{constructor(tag){this.tag=tag;this.children=[];this.style={};this.value='';this.checked=false;this.textContent='';}append(n){this.children.push(n);n.parentElement=this;}setAttribute(){}addEventListener(){}replaceChildren(){this.children=[];}}
globalThis.document={createElement:tag=>new Element(tag)};
let opened=false;
const report={rows:{inventory:0,shipment:28},review:{pending_items:0},source_files:[{name:'daily.csv',kind:'shipment',center:'人工倉庫',date:'2026-10-13'}],input_history:{candidate_files:28,new_files:1,duplicate_files:0,inherited_files:27},issues:[],center_windows:[]};
globalThis.fetch=async url=>({ok:true,json:async()=>url.startsWith('/api/saved-forecasts')?{items:[],warehouses:[],total:0,unavailable_count:0}:url==='/api/field/jobs'?[{id:'job',status:'SUCCEEDED',analysis_id:'id',message:'完了'}]:url.startsWith('/api/business-archives/')?report:url.startsWith('/api/daily-runs/')?{status:'INVENTORY_CONFIRMATION_REQUIRED',next_action:'在庫確認',blockers:[]}:Promise.reject(new Error('Unexpected URL '+url))});
globalThis.localStorage={setItem(){}};
const ctx={root:new Element('main'),analysisId:'id',enter(){this.root=new Element('main');},open:async()=>{opened=true;},run:fn=>fn(),message(){},home(){}};
await waitJob(ctx,'job');assert(opened);
await analysis(ctx);
const texts=n=>n.textContent+' '+n.children.map(texts).join(' ');
assert(texts(ctx.root).includes('保存済みの予測を見る'));
assert(texts(ctx.root).includes('需要予測だけ'));
assert(texts(ctx.root).includes('daily.csv'));
assert(texts(ctx.root).includes('過去から参照 27'));
assert(texts(ctx.root).includes('需要予測のみを計算'));
console.log('PASS upload wait screen, cumulative source diagnostics and shipment-only forecast controls');
