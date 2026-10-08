import {el,field,button} from './api.js';
import {masterChoice} from './document-master.js';

export const labels={source_detail_date:'商品名下の日付（意味未確認）',page:'原本ページ番号',note:'確認メモ',kind:'データの種類',jan:'JAN',product_code:'商品コード',product_name:'商品名',date:'出荷日',expiry:'賞味期限',quantity:'原本の数量',unit:'原本の単位',location:'倉庫',snapshot:'在庫基準日',case_factor:'1単位あたりの箱数（単独数量の場合）',case_quantity:'ケース数（現在／当出）',loose_quantity:'バラ数（現在／当出・空欄は未確認）',units_per_case:'1箱あたりのバラ数（換算を確認）'};
const text=v=>String(v??'').trim();
const numeric=(v,max,positive=false)=>text(v)!==''&&/^[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:e[+-]?[0-9]+)?$/i.test(text(v))&&Number.isFinite(Number(v))&&Number(v)>=0&&Number(v)<=max&&(!positive||Number(v)>0);
const validDate=v=>Number(v.slice(0,4))>=1&&/^\d{4}-\d{2}-\d{2}$/.test(v)&&!Number.isNaN(Date.parse(v+'T00:00:00Z'))&&new Date(v+'T00:00:00Z').toISOString().slice(0,10)===v;
export function rowProblems(row){
 const errors=[],warnings=[];
 const add=(key,message)=>errors.push({key,message});
 if(row.exclude){if(!text(row.reason))add('reason','除外理由が未入力');return {errors,warnings};}
 if(!['shipment','inventory'].includes(row.kind))add('kind','在庫／出荷が未選択');
 const jan=text(row.jan);
 if(!jan)add('jan','JANが未入力');
 else if(!/^(?:[0-9]{8}|[0-9]{13})$/.test(jan))add('jan','JANは8桁・13桁で確認');
 else {const d=[...jan].map(Number);let sum=d.at(-1);for(let i=d.length-2,weight=3;i>=0;i--,weight=4-weight)sum+=d[i]*weight;if(sum%10)add('jan','JANのチェック桁が不正');}
 for(const [key,label] of [['location','倉庫'],['unit','単位']])if(!text(row[key]))add(key,label+'が未入力');
 for(const [key,label] of (row.kind==='shipment'?[['date','出荷日']]:[['snapshot','在庫基準日'],['expiry','賞味期限']])){
  if(!text(row[key]))add(key,label+'が未入力');else if(!validDate(text(row[key])))add(key,label+'の形式・日付が不正');
 }
 const components=['case_quantity','loose_quantity'].some(k=>text(row[k])!=='');
 if(components){
  for(const [k,label] of [['case_quantity','ケース数'],['loose_quantity','バラ数']])if(!numeric(row[k],1e12))add(k,label+'を数値で確認（空欄≠0）');
  if(numeric(row.loose_quantity,1e12)&&Number(row.loose_quantity)>0&&!numeric(row.units_per_case,1e6,true))add('units_per_case','1箱あたりのバラ数を確認');
  if(!row.component_confirmed)add('component_confirmed','ケース・バラ欄の意味が未確認');
 }else{
  if(!numeric(row.quantity,1e12))add('quantity','数量を数値で確認（空欄≠0）');
  if(!numeric(row.case_factor,1e6,true))add('case_factor','箱への換算が未確認・不正');
 }
 for(const k of ['jan','product_code','product_name','location','unit'])if(text(row[k]).length>200)add(k,'入力は200文字以内');
 if(!text(row.product_name))warnings.push('商品名が未入力');
 if(text(row.unit)&&!['箱','CASE','ケース','くくり','パレット','バラ','個'].includes(text(row.unit)))warnings.push('原本の単位を確認：'+text(row.unit));
 if(text(row.note))warnings.push('読取メモあり：'+text(row.note));
 return {errors,warnings};
}
export function serializeControls(cs){return Object.fromEntries(Object.entries(cs).map(([k,n])=>[k,['exclude','component_confirmed'].includes(k)?n.checked:n.value]));}

export function reviewTable(ctx,parent,sourceRows,master){
 const section=el('section','',parent);section.className='document-review';
 el('h3','読み取り結果の確認一覧',section);
 el('p','赤枠は不足・形式エラーです。入力OKでも誤読はあり得ます。数量・単位・日付・倉庫を原本と照合してください。変更は保存するまで確定しません。',section);
 const totals=el('p','',section);totals.className='document-review-counts';totals.setAttribute('role','status');
 const toolbar=el('div','',section);toolbar.className='document-review-tools';
 const search=field(toolbar,'商品名・コード・JAN・倉庫を検索','search',false);
 const filter=el('select','',el('label','表示する行',toolbar));filter.setAttribute('aria-label','表示する行');
 for(const [v,label] of [['all','すべて'],['errors','不足・形式エラーのみ'],['warnings','読取メモ・商品名の確認が必要'],['excluded','除外予定のみ']]){const o=el('option',label,filter);o.value=v;}
 filter.value='all';
 const wrap=el('div','',section);wrap.className='document-review-scroll';wrap.tabIndex=0;wrap.setAttribute('aria-label','読み取り結果の一覧（横・縦にスクロールできます）');
 const table=el('table','',wrap);table.className='document-review-table';el('caption','原本と照合しながら一覧で修正できます。入力OKは業務上正しいことの保証ではありません。',table);
 const header=el('tr','',el('thead','',table));
 for(const label of ['行・確認状況','商品名・コード','JAN・候補','数量・単位・換算','種類・日付','倉庫','原本・メモ','除外'])el('th',label,header).setAttribute('scope','col');
 const body=el('tbody','',table), entries=[],edits=[];
 function update(){
  let errorCount=0,warningCount=0,excludedCount=0,visible=0;
  for(const entry of entries){
   const row=serializeControls(entry.controls),p=rowProblems(row);entry.problems=p;
   const hasComponents=['case_quantity','loose_quantity'].some(k=>text(row[k])!=='');
   entry.single.hidden=hasComponents;
   if(p.errors.length)errorCount++;if(row.exclude)excludedCount++;else if(p.warnings.length)warningCount++;
   for(const n of Object.values(entry.controls))n.removeAttribute('aria-invalid');
   for(const e of p.errors)entry.controls[e.key]?.setAttribute('aria-invalid','true');
   entry.state.replaceChildren();
   const badge=el('strong',row.exclude?(p.errors.length?'除外理由を確認':'除外予定'):p.errors.length?'不足・要修正':'入力OK・原本照合が必要',entry.state);
   badge.className=p.errors.length?'review-badge error':row.exclude?'review-badge excluded':'review-badge pending';
   for(const e of p.errors)el('div',e.message,entry.state).className='review-problem';
   for(const warning of p.warnings)el('div',warning,entry.state).className='review-warning';
   entry.dateGroups.date.hidden=row.kind==='inventory';entry.dateGroups.snapshot.hidden=row.kind==='shipment';entry.dateGroups.expiry.hidden=row.kind==='shipment';
   const needle=search.value.trim().toLowerCase();
   const matches=!needle||['product_name','product_code','jan','location','note'].some(k=>text(row[k]).toLowerCase().includes(needle));
   const category=filter.value==='all'||filter.value==='errors'&&p.errors.length||filter.value==='warnings'&&!row.exclude&&p.warnings.length||filter.value==='excluded'&&row.exclude;
   entry.tr.hidden=!(matches&&category);if(!entry.tr.hidden)visible++;
  }
  totals.textContent=`全${entries.length}行 ／ 不足・形式エラー ${errorCount}行 ／ 読取メモ・商品名の確認 ${warningCount}行 ／ 除外予定 ${excludedCount}行 ／ 表示 ${visible}行`;
 }
 function addRow(row={},i=entries.length,refresh=true){
  const tr=el('tr','',body),controls={},dateGroups={};
  const first=el('td','',tr);el('b',`${i+1}行目`,first);const state=el('div','',first);
  const product=el('td','',tr),jan=el('td','',tr),quantity=el('td','',tr),dates=el('td','',tr),location=el('td','',tr),origin=el('td','',tr),exclude=el('td','',tr);
  function input(key,host){
   let n;
   if(key==='kind'){
    n=el('select','',el('label',labels[key],host));for(const [v,t] of [['unknown','選択してください'],['inventory','倉庫在庫'],['shipment','出荷実績']]){const o=el('option',t,n);o.value=v;}
   }else n=field(host,labels[key],['date','expiry','snapshot'].includes(key)?'date':'text',false);
   n.value=key==='kind'?(['shipment','inventory'].includes(row.kind)?row.kind:'unknown'):(row[key]??'');n.setAttribute('aria-label',`${i+1}行目 ${labels[key]}`);controls[key]=n;
   if(['date','expiry','snapshot'].includes(key)){
    dateGroups[key]=n.parentElement;
    if(text(row[key])&&!validDate(text(row[key])))el('small',`読取値：${row[key]}（年・日付を確認）`,n.parentElement);
   }
   return n;
  }
  input('product_name',product);input('product_code',product);input('jan',jan);
  const single=el('div','',quantity);single.className='document-quantity-grid';for(const k of ['quantity','unit','case_factor'])input(k,single);
  const components=el('div','',quantity);components.className='document-quantity-grid';for(const k of ['case_quantity','loose_quantity','units_per_case'])input(k,components);
  controls.component_confirmed=field(quantity,'ケース・バラの列の意味と空欄を確認した（空欄は必要なら明示的に0を入力）','checkbox',false);controls.component_confirmed.checked=row.component_confirmed===true;
  input('kind',dates);for(const k of ['date','snapshot','expiry'])input(k,dates);
  input('source_detail_date',dates);
  input('location',location);input('page',origin);input('note',origin);
  masterChoice(ctx,jan,controls,master);
  controls.exclude=field(exclude,'この行を除外する','checkbox',false);controls.exclude.checked=row.exclude===true;
  controls.reason=field(exclude,'除外理由','text',false);controls.reason.value=row.reason??'';
  entries.push({tr,controls,state,dateGroups,single});edits.push(controls);
  tr.addEventListener('input',update);tr.addEventListener('change',update);
  if(refresh)update();return tr;
 }
 sourceRows.forEach((row,i)=>addRow(row,i,false));
 search.addEventListener('input',update);filter.addEventListener('change',update);update();
 button('原本から明細を追加する',()=>{search.value='';filter.value='all';const tr=addRow();tr.scrollIntoView({block:'nearest'});},section,true);
 return {edits,update};
}
