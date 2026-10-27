import {api, el, field, button, saveWithNotice} from './api.js';

export async function qualitySettings(parent, token=''){
  const root=el('section','',parent);el('h2','データ受信予定・休業日・商品取扱期間',root);
  el('p','日常の担当者操作では変更不要です。IT担当者が原本の仕様と営業日を確認して設定します。出荷の商品行省略と在庫の空欄0は別ルールです。',root);
  const current=await api('/api/data-quality/rules');
  el('p',`設定版：${current.id}／${current.known_at||'全暦日稼働の初期仮定'}`,root);
  if(!token){
    el('p','変更はWindows管理者として起動したログ送信の管理者設定画面から行ってください。ここでは現在の設定を確認できます。',root);
    el('pre',JSON.stringify(current.rules,null,2),root);return;
  }
  const actor=field(root,'設定者'),reason=field(root,'設定理由');
  const label=el('label','品質設定JSON（warehouse/from/to/weekdays/closed_dates/products等）',root);
  const json=el('textarea','',label);json.rows=18;json.style.width='100%';
  json.value=JSON.stringify(current.rules,null,2);
  el('p','weekdaysは月曜0〜日曜6。productsはjan/from/toの取扱期間。receipt_due_timeは日本時間HH:MM。absence_means_zeroは日次出荷ファイル内の商品行省略だけに適用し、未受信・在庫省略は0にしません。abnormal_change_casesは在庫変動を確認する正のボール数です。',root);
  const example=el('details','',root);el('summary','書式例（実際の業務条件へ修正してください）',example);
  el('pre',JSON.stringify({warehouses:[{warehouse:'倉庫名',from:'2026-01-01',to:null,
    weekdays:[0,1,2,3,4,5,6],closed_dates:[],products:[],absence_means_zero:false,
    receipt_due_time:'23:59',abnormal_change_cases:null}]},null,2),example);
  const status=el('p','',root);status.setAttribute('role','status');
  button('確認した設定を新しい版で保存',async()=>{
    try{
      await saveWithNotice(async()=>{
        const response=await fetch('/api/data-quality/rules',{method:'POST',headers:{
          'Content-Type':'application/json','X-Feedback-Admin':token},body:JSON.stringify({
          expected_version:current.id,actor:actor.value,reason:reason.value,rules:JSON.parse(json.value)})});
        const value=await response.json();if(!response.ok)throw new Error(value.detail||'保存できません');
        status.textContent=`保存しました：${value.id}。現場画面で再検証してください。`;current.id=value.id;
      },'品質設定を新しい版で保存しました。現場画面で再検証してください。');
    }catch(e){status.textContent=e.message;}
  },root);
}
