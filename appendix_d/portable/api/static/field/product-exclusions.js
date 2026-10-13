import {api,el,field,button,saveWithNotice} from './api.js';
export async function exclusionsPanel(ctx,parent,refreshDocuments,master){
 const box=el('details','',parent);el('summary','対象外商品の登録・解除',box);
 el('p','JSON・CSV・PDF・PNG・JPEG（10 MB以内）から読み取り、原本と一覧を確認して登録します。CSVはJAN、商品名、理由の見出しに対応します。原本と除外履歴は残します。',box);
 const file=field(box,'対象外商品リスト','file',false);file.accept='.json,.csv,.pdf,.png,.jpg,.jpeg';
 const consent=field(box,'画像・手書きPDFをOpenAIへ送信することに同意する（API料金が発生）','checkbox',false);
 const actor=field(box,'設定の確認者','text',false),preview=el('div','',box),list=el('div','',box);
 let result=null,edits=[];
 const partial=field(box,'全明細を読めていない場合、選択した確認済み商品だけ登録する','checkbox',false);
 const confirmed=field(box,'選択した商品のJAN・対象外指定を原本と照合した','checkbox',false);
 async function refresh(){list.replaceChildren();for(const row of await api('/api/product-exclusions')){
  const line=el('div',`${row.exclude?'対象外':'解除済み'}：${row.product_name} ／ ${row.jan} ／ ${row.reason}`,list);
  if(row.exclude)button('対象へ戻す',()=>ctx.run(async()=>{if(!actor.value)throw new Error('確認者を入力してください');await saveWithNotice(()=>api('/api/product-exclusions',{actor:actor.value,products:[{...row,exclude:false,reason:'担当者が対象外設定を解除'}]}),'対象外設定を解除しました。');await refresh();await refreshDocuments();}),line,true);
 }}
 button('ファイルから候補を読み取る',()=>ctx.run(async()=>{
  const f=file.files[0];if(!f||f.size>10*1024*1024)throw new Error('10 MB以内の対応ファイルを選んでください');
  result=null;edits=[];preview.replaceChildren();confirmed.checked=false;partial.checked=false;
  const headers={'X-File-Name':encodeURIComponent(f.name),'X-AI-Consent':String(consent.checked)};
  if(master?.choice.value)headers['X-Master-Version']=master.choice.value;
  const r=await fetch('/api/product-exclusions/preview',{method:'POST',headers,body:f});const v=await r.json();if(!r.ok)throw new Error(v.detail||'読み取れませんでした');result=v;
  el('p',`${v.source_name}：${v.products.length}候補 ／ ${v.method==='ai'?'AI読取':'端末内読取'}。まだ登録していません。${v.complete?'':'未取得の明細があります。'}`,preview);
  const table=el('table','',preview);const head=el('tr','',table);for(const label of ['登録する','JAN','商品名','対象外／解除','理由・注意'])el('th',label,head);
  for(const row of v.products){const tr=el('tr','',table),choose=field(el('td','',tr),'選択','checkbox',false);choose.checked=!row.issue;
   const jan=field(el('td','',tr),'13桁JAN','text',false);jan.value=row.jan;
   const name=field(el('td','',tr),'商品名','text',false);name.value=row.product_name;
   el('td',row.exclude?'対象外':'解除',tr);const cell=el('td','',tr),reason=field(cell,'理由','text',false);reason.value=row.reason;el('p',row.issue||'',cell);
   edits.push({choose,jan,name,reason,exclude:row.exclude});
  }
 }),box);
 button('確認した商品設定を登録',()=>ctx.run(async()=>{
  if(!result||!confirmed.checked||!actor.value)throw new Error('読み取り、確認者、原本照合を確認してください');
  if(!result.complete&&!partial.checked)throw new Error('未取得部分を確認し、部分登録への同意を選んでください');
  const products=edits.filter(x=>x.choose.checked).map(x=>({jan:x.jan.value.trim(),product_name:x.name.value,reason:x.reason.value,exclude:x.exclude}));
  if(!products.length)throw new Error('登録する商品を選んでください');
  await saveWithNotice(()=>api('/api/product-exclusions',{actor:actor.value,products,source_sha256:result.source_sha256,confirmed:confirmed.checked,allow_partial:partial.checked}),'対象外商品設定を保存しました。');
  result=null;edits=[];preview.replaceChildren();confirmed.checked=false;await refresh();await refreshDocuments();
 }),box);
 await refresh();
}
