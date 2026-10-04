const dailyPanel=document.getElementById('daily-auto-run');
const dailyStatus=document.getElementById('daily-run-status');
const dailyForm=document.getElementById('daily-run-form');
const dailyResult=document.getElementById('daily-run-result');
let dailyAnalysisId=null;
const dailyLabels={REVIEW_REQUIRED:'確認待ち',INVENTORY_CONFIRMATION_REQUIRED:'正式在庫の確認待ち',INVENTORY_BLOCKED:'正式在庫を隔離',READY_TO_ADVANCE:'予測まで実行可能',FORECAST_BLOCKED:'予測条件不足',COMPLETED:'予測完了'};
function renderDailyRun(value){
  dailyPanel.hidden=false;dailyAnalysisId=value.analysis_id;dailyResult.replaceChildren();
  dailyStatus.textContent=`${dailyLabels[value.status]||value.status}：${value.next_action}`;
  dailyStatus.className=value.status==='COMPLETED'?'success':(['INVENTORY_BLOCKED','FORECAST_BLOCKED'].includes(value.status)?'error':'');
  dailyForm.hidden=value.status!=='READY_TO_ADVANCE';
  if(value.status==='COMPLETED'){
    const p=document.createElement('p');p.textContent=`${value.eligible_series_count}系列の予測を保存しました。日次実行版 ${value.revision}`;
    const link=document.createElement('a');link.textContent='予測結果JSONを保存';link.href=`/api/formal-forecast/${encodeURIComponent(value.build_id)}/download`;dailyResult.append(p,link);
  }
  if(value.blockers?.length){const p=document.createElement('p');p.textContent=`停止理由 ${value.blockers.length}件。既存の確認欄で内容を確認してください。`;dailyResult.appendChild(p);}
}
async function refreshDailyRun(analysisId){
  if(!analysisId)return;
  try{const response=await fetch(`/api/daily-runs/${encodeURIComponent(analysisId)}`);const value=await response.json();if(!response.ok)throw new Error(value.detail||'日次実行を確認できません。');renderDailyRun(value);}
  catch(error){dailyPanel.hidden=false;dailyForm.hidden=true;dailyStatus.textContent=error.message;dailyStatus.className='error';}
}
dailyForm.addEventListener('submit',async event=>{
  event.preventDefault();if(!dailyAnalysisId)return;const button=document.getElementById('daily-run-submit');button.disabled=true;dailyStatus.textContent='正式在庫Worker、数量照合、出荷日次化、14日予測を順番に実行中です。';
  try{const payload={actor:document.getElementById('daily-run-actor').value,reason:document.getElementById('daily-run-reason').value,confirm_pilot_scope:document.getElementById('daily-confirm-scope').checked,confirm_quantity_reconciliation:document.getElementById('daily-confirm-quantity').checked,confirm_identity_bridge:document.getElementById('daily-confirm-identity').checked,confirm_zero_policy:document.getElementById('daily-confirm-zero').checked};const response=await fetch(`/api/daily-runs/${encodeURIComponent(dailyAnalysisId)}/advance`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});const value=await response.json();if(!response.ok)throw new Error(value.detail||'日次実行を進められませんでした。');renderDailyRun(value);}
  catch(error){dailyStatus.textContent=error.message;dailyStatus.className='error';}finally{button.disabled=false;}
});
document.addEventListener('portable-analysis-changed',event=>refreshDailyRun(event.detail.analysisId));
