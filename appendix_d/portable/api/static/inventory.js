const formalForm=document.getElementById('formal-inventory-form');
const formalLocations=document.getElementById('formal-locations');
const formalState=document.getElementById('formal-state');
const formalResult=document.getElementById('formal-result');
const pipelinePanel=document.getElementById('formal-pipeline');
const pilotForm=document.getElementById('pilot-form');
const pilotLocations=document.getElementById('pilot-locations');
const pilotState=document.getElementById('pilot-state');
const pilotJobs=document.getElementById('pilot-jobs');
const forecastPanel=document.getElementById('formal-forecast');
const forecastForm=document.getElementById('formal-forecast-form');
const forecastIdentities=document.getElementById('forecast-identities');
const forecastState=document.getElementById('formal-forecast-state');
const forecastResult=document.getElementById('formal-forecast-result');
let formalAnalysisId=null;let formalHandoffId=null;let pipelineRegistration=null;
function formalMessage(value,kind=''){formalState.textContent=value;formalState.className=kind;}
function pilotMessage(value,kind=''){pilotState.textContent=value;pilotState.className=kind;}
function forecastMessage(value,kind=''){forecastState.textContent=value;forecastState.className=kind;}
function showHandoff(item){
  formalResult.replaceChildren();pipelinePanel.hidden=true;forecastPanel.hidden=true;formalHandoffId=null;if(!item)return;
  const summary=document.createElement('p');
  summary.textContent=item.status==='READY_FOR_FORMAL_INTAKE'
    ? `${item.files.length}倉庫、${item.files.reduce((sum,file)=>sum+file.accepted_row_count,0).toLocaleString()}行を正式取込用に検証しました。`
    : `${item.blockers.length.toLocaleString()}行に未解決項目があるため、正式取込へは渡しません。`;
  summary.className=item.status==='READY_FOR_FORMAL_INTAKE'?'success':'error';formalResult.appendChild(summary);
  if(item.status==='READY_FOR_FORMAL_INTAKE'){
    formalHandoffId=item.handoff_id;
    const link=document.createElement('a');link.textContent='正式取込パッケージを保存';link.id='formal-download';
    link.href=`/api/formal-inventory/${encodeURIComponent(item.handoff_id)}/download`;formalResult.appendChild(link);
    loadPipeline(item.handoff_id);
  }
}
async function renderFormalInventory(report){
  formalAnalysisId=report.analysis_id;formalLocations.replaceChildren();formalResult.replaceChildren();pipelinePanel.hidden=true;
  try{
    const response=await fetch(`/api/business-archives/${encodeURIComponent(report.analysis_id)}/formal-inventory`);
    const view=await response.json();if(!response.ok)throw new Error(view.detail||'最新在庫を確認できません。');
    for(const center of view.centers){
      const fieldset=document.createElement('fieldset');fieldset.dataset.center=center.source_center;
      const legend=document.createElement('legend');legend.textContent=`${center.source_center}（最新 ${center.latest_date}）`;fieldset.appendChild(legend);
      const code=document.createElement('input');code.placeholder='正式拠点コード';code.setAttribute('aria-label',`${center.source_center} 正式拠点コード`);code.required=true;
      const name=document.createElement('input');name.placeholder='正式拠点名';name.value=`${center.source_center}倉庫`;name.setAttribute('aria-label',`${center.source_center} 正式拠点名`);name.required=true;
      const snapshot=document.createElement('input');snapshot.type='time';snapshot.setAttribute('aria-label',`${center.source_center} 在庫基準時刻`);snapshot.required=true;
      fieldset.append(code,name,snapshot);formalLocations.appendChild(fieldset);
    }
    showHandoff(view.latest);formalMessage('正式拠点コードと在庫基準時刻を確認してください。');
  }catch(error){formalMessage(error.message,'error');}
}
formalForm.addEventListener('submit',async event=>{
  event.preventDefault();if(!formalAnalysisId)return;
  const submit=document.getElementById('formal-submit');submit.disabled=true;formalMessage('既存の正式在庫契約で全行を検証中です。');
  const locations=[...formalLocations.querySelectorAll('fieldset')].map(fieldset=>({
    source_center:fieldset.dataset.center,
    location_code:fieldset.querySelector('input[placeholder="正式拠点コード"]').value,
    location_name:fieldset.querySelector('input[placeholder="正式拠点名"]').value,
    snapshot_time:fieldset.querySelector('input[type="time"]').value
  }));
  try{
    const response=await fetch(`/api/business-archives/${encodeURIComponent(formalAnalysisId)}/formal-inventory`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({actor:document.getElementById('formal-actor').value,reason:document.getElementById('formal-reason').value,confirm_case:document.getElementById('formal-case').checked,locations})});
    const result=await response.json();if(!response.ok)throw new Error(result.detail||'正式取込用データを準備できませんでした。');
    showHandoff(result);formalMessage(result.notice,result.status==='READY_FOR_FORMAL_INTAKE'?'success':'error');
  }catch(error){formalMessage(error.message,'error');}finally{submit.disabled=false;}
});
async function loadPipeline(handoffId){
  try{
    const response=await fetch(`/api/formal-inventory/${encodeURIComponent(handoffId)}/pipeline`);
    const view=await response.json();if(!response.ok)throw new Error(view.detail||'正式在庫Workerの状態を確認できません。');
    pipelinePanel.hidden=false;pilotLocations.replaceChildren();
    for(const location of view.locations){
      const fieldset=document.createElement('fieldset');fieldset.dataset.center=location.source_center;
      const legend=document.createElement('legend');legend.textContent=`${location.source_center}：試験対象JAN（10〜20件）`;fieldset.appendChild(legend);
      const products=document.createElement('div');products.className='pilot-products';
      for(const [index,jan] of location.jans.entries()){
        const label=document.createElement('label');const box=document.createElement('input');box.type='checkbox';box.value=jan;box.checked=index<20;
        label.append(box,document.createTextNode(jan));products.appendChild(label);
      }
      fieldset.appendChild(products);pilotLocations.appendChild(fieldset);
    }
    renderPipeline(view.latest);pilotMessage(view.latest?'保存済みの正式在庫処理を表示しました。':'試験対象JANを確認してください。');
  }catch(error){pipelinePanel.hidden=false;pilotMessage(error.message,'error');}
}
function renderPipeline(value){
  pipelineRegistration=value;pilotJobs.replaceChildren();forecastPanel.hidden=true;if(!value)return;
  if(!document.getElementById('pilot-actor').value)document.getElementById('pilot-actor').value=value.approved_by||'';
  if(!document.getElementById('pilot-reason').value)document.getElementById('pilot-reason').value=value.approval_reason||'';
  for(const job of value.jobs){
    const li=document.createElement('li');
    li.textContent=`${job.source_center}：${job.status}／採用 ${job.accepted_row_count??0}行／隔離 ${job.quarantined_row_count??0}行／数量 ${job.normalized_quantity_cases??'確認中'} CASE／照合 ${job.reconciliation_matched?'一致':'未完了'}`;
    if(job.status==='APPROVAL_REQUIRED'&&job.reconciliation_matched&&job.quarantined_row_count===0){
      const button=document.createElement('button');button.type='button';button.textContent='照合結果を確認して正式承認';button.addEventListener('click',()=>approveJob(job));li.append(' ',button);
    }
    pilotJobs.appendChild(li);
  }
  if(value.status==='APPROVED'){
    pilotMessage('正式在庫Snapshotを承認しました。続けて出荷履歴と予測条件を確認してください。','success');
    loadFormalForecast(value.registration_id);
  }
}
pilotForm.addEventListener('submit',async event=>{
  event.preventDefault();if(!formalHandoffId)return;
  const selections=[...pilotLocations.querySelectorAll('fieldset')].map(fieldset=>({source_center:fieldset.dataset.center,jans:[...fieldset.querySelectorAll('input:checked')].map(input=>input.value)}));
  const button=document.getElementById('pilot-submit');button.disabled=true;pilotMessage('Unified Inboxと正式在庫Workerで検証中です。');
  try{
    const response=await fetch(`/api/formal-inventory/${encodeURIComponent(formalHandoffId)}/pipeline`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({actor:document.getElementById('pilot-actor').value,reason:document.getElementById('pilot-reason').value,confirm_pilot_scope:document.getElementById('pilot-confirm').checked,selections})});
    const result=await response.json();if(!response.ok)throw new Error(result.detail||'正式在庫Workerへ登録できませんでした。');
    renderPipeline(result);pilotMessage(result.notice,'success');
  }catch(error){pilotMessage(error.message,'error');}finally{button.disabled=false;}
});
async function approveJob(job){
  if(!pipelineRegistration||!window.confirm('隔離0件、原本数量と正規化数量の一致を確認しましたか？'))return;
  try{
    const response=await fetch(`/api/formal-inventory/pipeline/${encodeURIComponent(pipelineRegistration.registration_id)}/jobs/${encodeURIComponent(job.job_id)}/approve`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({actor:document.getElementById('pilot-actor').value,reason:document.getElementById('pilot-reason').value,expected_revision:job.decision_revision})});
    const result=await response.json();if(!response.ok)throw new Error(result.detail||'正式承認できませんでした。');renderPipeline(result);
  }catch(error){pilotMessage(error.message,'error');}
}
async function loadFormalForecast(registrationId){
  try{
    const response=await fetch(`/api/formal-inventory/pipeline/${encodeURIComponent(registrationId)}/forecast`);
    const view=await response.json();if(!response.ok)throw new Error(view.detail||'予測準備状態を確認できません。');
    forecastPanel.hidden=false;forecastIdentities.replaceChildren();
    const table=document.createElement('table');table.innerHTML='<thead><tr><th>元の倉庫</th><th>JAN / 商品ID</th><th>予測拠点</th></tr></thead>';
    const body=document.createElement('tbody');
    for(const item of view.identity_proposal){const row=document.createElement('tr');for(const value of [item.source_center,`${item.jan} / ${item.canonical_product_id}`,item.forecast_center_id]){const cell=document.createElement('td');cell.textContent=value;row.appendChild(cell);}body.appendChild(row);}
    table.appendChild(body);forecastIdentities.appendChild(table);
    if(!document.getElementById('forecast-actor').value)document.getElementById('forecast-actor').value=pipelineRegistration.approved_by||'';
    renderFormalForecast(view.latest);
    forecastMessage(view.latest?'保存済みの予測結果を表示しました。':'JAN・倉庫対応と出荷0日の扱いを確認してください。');
  }catch(error){forecastPanel.hidden=false;forecastMessage(error.message,'error');}
}
function renderFormalForecast(value){
  forecastResult.replaceChildren();if(!value)return;
  const box=document.createElement('div');box.className='forecast-summary';
  const heading=document.createElement('strong');heading.textContent=value.status==='BLOCKED'?'予測対象を準備できませんでした':'14日予測が完了しました';box.appendChild(heading);
  const summary=document.createElement('p');summary.textContent=`対象 ${value.eligible_series_count}系列／確認が必要 ${value.blocked_series_count}系列／学習期間 ${value.train_start}〜${value.train_end}`;box.appendChild(summary);
  if(value.series?.some(item=>item.blocking_reasons.length)){const list=document.createElement('ul');for(const item of value.series.filter(item=>item.blocking_reasons.length)){const li=document.createElement('li');li.textContent=`${item.jan}（${item.forecast_center_id}）：${item.blocking_reasons.join('、')}`;list.appendChild(li);}box.appendChild(list);}
  if(value.predictions?.length){const table=document.createElement('table');table.innerHTML='<thead><tr><th>系列</th><th>予測日</th><th>予測箱数</th><th>現在庫</th></tr></thead>';const body=document.createElement('tbody');for(const item of value.predictions){const row=document.createElement('tr');for(const content of [item.unique_id,item.target_date,Number(item.yhat).toFixed(2),item.current_inventory_cases]){const cell=document.createElement('td');cell.textContent=content;row.appendChild(cell);}body.appendChild(row);}table.appendChild(body);box.appendChild(table);const link=document.createElement('a');link.href=`/api/formal-forecast/${encodeURIComponent(value.build_id)}/download`;link.textContent='予測結果JSONを保存';box.appendChild(link);}
  forecastResult.appendChild(box);forecastMessage(value.notice,value.status==='BLOCKED'?'error':'success');
}
forecastForm.addEventListener('submit',async event=>{
  event.preventDefault();if(!pipelineRegistration)return;const button=document.getElementById('formal-forecast-submit');button.disabled=true;forecastMessage('出荷履歴を日次化し、14日予測を実行中です。');
  try{const response=await fetch(`/api/formal-inventory/pipeline/${encodeURIComponent(pipelineRegistration.registration_id)}/forecast`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({actor:document.getElementById('forecast-actor').value,reason:document.getElementById('forecast-reason').value,confirm_identity_bridge:document.getElementById('forecast-identity-confirm').checked,confirm_zero_policy:document.getElementById('forecast-zero-confirm').checked})});const result=await response.json();if(!response.ok)throw new Error(result.detail||'正式予測を実行できませんでした。');renderFormalForecast(result);}catch(error){forecastMessage(error.message,'error');}finally{button.disabled=false;}
});
window.PortableInventory={render:renderFormalInventory};
