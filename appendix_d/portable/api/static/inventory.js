const formalForm=document.getElementById('formal-inventory-form');
const formalLocations=document.getElementById('formal-locations');
const formalState=document.getElementById('formal-state');
const formalResult=document.getElementById('formal-result');
const pipelinePanel=document.getElementById('formal-pipeline');
const pilotForm=document.getElementById('pilot-form');
const pilotLocations=document.getElementById('pilot-locations');
const pilotState=document.getElementById('pilot-state');
const pilotJobs=document.getElementById('pilot-jobs');
let formalAnalysisId=null;let formalHandoffId=null;let pipelineRegistration=null;
function formalMessage(value,kind=''){formalState.textContent=value;formalState.className=kind;}
function pilotMessage(value,kind=''){pilotState.textContent=value;pilotState.className=kind;}
function showHandoff(item){
  formalResult.replaceChildren();pipelinePanel.hidden=true;formalHandoffId=null;if(!item)return;
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
  pipelineRegistration=value;pilotJobs.replaceChildren();if(!value)return;
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
  if(value.status==='APPROVED')pilotMessage('正式在庫Snapshotを承認しました。出荷日次入力の確定後に予測更新へ進めます。','success');
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
window.PortableInventory={render:renderFormalInventory};
