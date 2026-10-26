import {api,el,field,button,saveWithNotice} from './api.js';
import {serializeControls,labels} from './document-review-table.js';

export function sourceComparison(parent,doc){
 const dialog=el('dialog','',parent);dialog.className='document-source-dialog';
 const title=el('h3','原本ページとの比較',dialog);
 button('比較を閉じる',()=>dialog.close(),dialog,true);
 el('p','ページ単位の比較です。行位置の自動特定・正解判定ではありません。',dialog);
 const body=el('div','',dialog);body.className='document-source-grid';
 const image=el('img','',body);image.alt='原本ページ';
 const values=el('div','',body);
 return (index,row)=>{
  const page=Number(row.page);
  if(!Number.isInteger(page)||page<1||page>doc.page_count)throw new Error('原本ページ番号を確認してください');
  title.textContent=`${doc.name} ／ ${page}ページ ／ ${index+1}行目`;
  image.src=doc.mime==='application/pdf'?`/api/documents/${doc.id}/page/${page}`:`/api/documents/${doc.id}/original`;
  values.replaceChildren();const table=el('table','',values);
  const heading=el('tr','',table);for(const text of ['項目','読取時','現在の入力'])el('th',text,heading);
  for(const key of ['jan','product_name','location','snapshot','date','expiry','source_detail_date','case_quantity','loose_quantity','units_per_case']){
   const tr=el('tr','',table);el('th',labels[key]||key,tr);
   const original=doc.extraction.rows[index]||{};
   const rawKey=key==='case_quantity'?(original.kind==='shipment'?'source_outbound_case':'source_current_case'):key==='loose_quantity'?(original.kind==='shipment'?'source_outbound_loose':'source_current_loose'):key;
   const raw=original[rawKey]??original[key];
   el('td',raw===''||raw==null?'空欄':String(raw),tr);el('td',row[key]===''||row[key]==null?'空欄':String(row[key]),tr);
  }
  dialog.showModal();
 };
}

export async function reviewPolicy(ctx,parent,doc,table,plan,master,refresh){
 el('h3','単位・空欄のルール確認と次回からの再利用',parent);
 el('p','ボール＝ケース、バラ＝商品1個。入数・数量・日付・JANは変更しません。適用前に対象を確認します。',parent);
 el('p',`今回の単位ルール再利用：${Object.values(plan.applied_rules).reduce((a,b)=>a+b,0)}行。機械点検通過でも文書承認はまだ必要です。`,parent);
 const sourceDates=plan.rows.map(r=>r.kind==='inventory'?r.snapshot:r.date).filter(v=>/^\d{4}-\d{2}-\d{2}$/.test(v||'')).sort();
 const actor=field(parent,'単位ルールの確認者'),reason=field(parent,'単位ルールの確認理由');
 actor.value=doc.draft?.actor||'';reason.value='ボール＝ケース、バラ＝商品1個であることを確認';
 const effective=field(parent,'ルールの適用開始日','date');effective.value=sourceDates[0]||'';
 const remember=field(parent,'同じ帳票・倉庫・マスター版で次回もこの単位定義を使う','checkbox',false);
 remember.checked=true;
 const blanks=field(parent,'次回の一括読取も、この範囲の現在欄は空欄＝0・両欄空欄の在庫行は除外とする','checkbox',false);
 blanks.disabled=!plan.native||doc.extraction.blank_current_policy!=='CURRENT_BLANK_ZERO_EXCLUDE_EMPTY';
 blanks.checked=!!doc.extraction.blank_rule_versions?.length;
 el('p','空欄ルールを保存する場合は、先にこの原本の「現在」欄は空欄＝0を選び、印刷在庫表を読み直してください。次回再利用を選び、確認者・理由・適用開始日とプレビューを確認して保存します。',parent);
 const previewArea=el('div','',parent);previewArea.setAttribute('role','status');
 let preview=null;
 const snapshot=()=>table.edits.map(serializeControls);
 const prepare=button('対象と変更内容をプレビュー',()=>ctx.run(async()=>{
  preview=await api(`/api/documents/${doc.id}/review/preview`,{
   rows:snapshot(),revision:doc.extraction.revision,actor:actor.value,reason:reason.value,
   effective_date:effective.value,remember:remember.checked,blank_current_zero:blanks.checked,master_version:master.choice.value||''});
  previewArea.textContent=`対象 ${preview.target_count}行 ／ 適用しない ${preview.skipped_count}行。倉庫 ${preview.scope.warehouse} ／ 帳票 ${preview.scope.template} ／ マスター ${preview.scope.master_version||'未選択の範囲'} ／ ${preview.effective_date}以降。${preview.changes}。次回再利用：${preview.remember?'保存する':'今回のみ'}`;
  apply.disabled=false;
 }),parent,true);
 const apply=button('この範囲に適用して途中保存',()=>ctx.run(async()=>{
  if(!preview)throw new Error('先にプレビューしてください');
  await saveWithNotice(()=>api(`/api/documents/${doc.id}/review/apply`,{
   preview_id:preview.id,rows:snapshot(),confirmed:true}),
   '読取ルールを保存しました。今回の数量は変更せず、文書の正式承認はしていません。');
  await refresh();
 }),parent);apply.disabled=true;
 for(const n of [actor,reason,effective,remember,blanks])for(const event of ['input','change'])n.addEventListener(event,()=>{preview=null;apply.disabled=true;});
 prepare.disabled=!plan.native;
 if(!plan.native)el('p','AI・未対応帳票には保存ルールを流用しません。原本と個別に確認してください。',parent);
 const rules=el('details','',parent);el('summary','保存済み単位ルールを確認・無効化',rules);
 for(const rule of await api('/api/document-review/rules')){
  el('p',`${rule.active?'有効':'無効'}${rule.current?'・現行':'・旧版'}：${rule.scope.warehouse} ／ ${rule.effective_date}以降 ／ マスター ${rule.scope.master_version||'未選択'} ／ 現在欄の空欄 ${rule.blank_current_zero?'0（両欄空欄の在庫行は除外）':'未確認のまま'} ／ 確認者 ${rule.actor} ／ 版 ${rule.version.slice(0,8)}`,rules);
  if(rule.active)button('このルールの次回再利用を止める',()=>ctx.run(async()=>{
   await api(`/api/document-review/rules/${rule.version}/disable`,{actor:actor.value,reason:reason.value});
   await refresh();
  }),rules,true);
 }
}
