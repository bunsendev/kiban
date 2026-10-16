import {api,el,field,button,saveWithNotice} from './api.js';
export async function aiUsage(parent){
 const box=el('section','',parent);el('h3','モデル・料金・使用量',box);
 el('p','モデル変更は次のAI読取から反映します。保存済みの抽出結果は変わりません。CSV・端末内PDF読取にはAPI料金は発生しません。',box);
 const choice=el('select','',el('label','使用モデル',box));
 const rate=field(box,'円換算（1ドル当たり・想定為替）','number',false);rate.min='0.01';rate.step='0.01';
 const volume=field(box,'月間AI読取予定回数（通常は1ページで1回）','number',false);volume.min='1';volume.step='1';
 const budget=field(box,'月間予算の目安（円・通知のみ）','number',false);budget.min='1';budget.step='1';
 const prices=el('div','',box),summary=el('div','',box),message=el('p','',box);message.setAttribute('role','status');
 let loaded=false;
 const yen=value=>value==null?'未算出':`約${Number(value).toLocaleString('ja-JP',{maximumFractionDigits:1})}円`;
 async function refresh(){
  const v=await api('/api/ai-settings');
  if(!loaded){for(const m of v.models){const o=el('option',m.label,choice);o.value=m.id;}choice.value=v.settings.model;rate.value=v.settings.yen_per_usd;volume.value=v.settings.monthly_requests;budget.value=v.settings.monthly_budget_yen;loaded=true;}
  prices.replaceChildren();el('p',`料金確認日：${v.price_date} ／ 入力・出力100万トークン当たり（標準短文脈）`,prices);
  for(const m of v.models)el('p',`${m.label}：入力 $${m.input} ／ 出力 $${m.output}`,prices);
  summary.replaceChildren();el('h4',`${v.month} このPCの利用状況`,summary);
  el('p',`${v.calls}回 ／ 記録できた分の概算：${yen(v.yen)}（$${v.usd.toFixed(4)}）`,summary);
  el('p',`月末見込み：${yen(v.month_end_yen)}（今月の経過日数で日割り。使用量が変わると増減します）`,summary);
  el('p',`設定した月間回数での想定：${yen(v.planned_yen)} ／ ${v.estimate_basis.startsWith('assumed')?'実績なし：1回入力6000・出力5000トークンを仮定':`同じモデルの今月の文書読取${v.sample_count}回の平均で計算`}`,summary);
  el('p',`費用不明：${v.unknown_cost}回。通信失敗などの不明分は上記金額に含みません。請求額はOpenAIの利用明細で確認してください。`,summary);
  if(v.budget_warning)el('p','記録できた概算が予算の目安に達しました。自動停止はしません。',summary);
  const table=el('table','',summary),head=el('tr','',table);
  for(const title of ['モデル','回数／失敗','入力／出力トークン','うち推論','概算USD','平均時間'])el('th',title,head);
  for(const g of v.groups){const tr=el('tr','',table);for(const text of [g.model,`${g.calls}／${g.failed}`,`${g.input_tokens}／${g.output_tokens}`,g.reasoning_tokens,`$${g.usd.toFixed(4)}`,`${(g.elapsed_seconds/g.calls).toFixed(1)}秒`])el('td',String(text),tr);}
  el('p',v.scope,summary);el('p','再読取も課金対象です。高額モデルへの自動切替は行いません。モデルの利用権限・接続は読取時に確認します。',summary);
 }
 const save=button('モデル・費用設定を保存',async()=>{
  save.disabled=true;
  try{await saveWithNotice(()=>api('/api/ai-settings',{model:choice.value,yen_per_usd:Number(rate.value),monthly_requests:Number(volume.value),monthly_budget_yen:Number(budget.value)}),'モデル・費用設定を保存しました。次のAI読取から反映します。');await refresh();message.textContent='保存しました。';}
  catch(e){message.textContent=e.message||'保存できませんでした';}finally{save.disabled=false;}
 },box);
 button('使用量を更新',()=>refresh().catch(e=>{message.textContent=e.message;}),box,true);
 await refresh();
}
