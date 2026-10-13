import {api,el,field,button,saveWithNotice} from './api.js';
export async function exclusionsPanel(ctx,parent,refreshDocuments){
 const box=el('details','',parent);el('summary','対象外商品の登録・解除',box);
 el('p','13桁JANで登録します。対象外は通常の修正一覧から外し、原本と除外履歴は残します。承認済みデータは変更しません。',box);
 const file=field(box,'対象外商品設定（JSON）','file',false);file.accept='.json';
 const actor=field(box,'設定の確認者','text',false),list=el('div','',box);
 async function refresh(){list.replaceChildren();for(const row of await api('/api/product-exclusions')){
  const line=el('div',`${row.exclude?'対象外':'解除済み'}：${row.product_name} ／ ${row.jan} ／ ${row.reason}`,list);
  if(row.exclude)button('対象へ戻す',()=>ctx.run(async()=>{if(!actor.value)throw new Error('確認者を入力してください');await saveWithNotice(()=>api('/api/product-exclusions',{actor:actor.value,products:[{...row,exclude:false,reason:'担当者が対象外設定を解除'}]}),'対象外設定を解除しました。');await refresh();await refreshDocuments();}),line,true);
 }}
 button('設定ファイルを登録',()=>ctx.run(async()=>{const f=file.files[0];if(!f||f.size>1024*1024)throw new Error('1 MB以内の設定JSONを選んでください');await saveWithNotice(async()=>{const r=await fetch('/api/product-exclusions/import',{method:'POST',body:f});const v=await r.json();if(!r.ok)throw new Error(v.detail);return v;},'対象外商品を登録しました。');await refresh();await refreshDocuments();}),box);
 await refresh();
}
