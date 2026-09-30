const formalForm=document.getElementById('formal-inventory-form');
const formalLocations=document.getElementById('formal-locations');
const formalState=document.getElementById('formal-state');
const formalResult=document.getElementById('formal-result');
let formalAnalysisId=null;
function formalMessage(value,kind=''){formalState.textContent=value;formalState.className=kind;}
function showHandoff(item){
  formalResult.replaceChildren();if(!item)return;
  const summary=document.createElement('p');
  summary.textContent=item.status==='READY_FOR_FORMAL_INTAKE'
    ? `${item.files.length}倉庫、${item.files.reduce((sum,file)=>sum+file.accepted_row_count,0).toLocaleString()}行を正式取込用に検証しました。`
    : `${item.blockers.length.toLocaleString()}行に未解決項目があるため、正式取込へは渡しません。`;
  summary.className=item.status==='READY_FOR_FORMAL_INTAKE'?'success':'error';formalResult.appendChild(summary);
  if(item.status==='READY_FOR_FORMAL_INTAKE'){
    const link=document.createElement('a');link.textContent='正式取込パッケージを保存';link.id='formal-download';
    link.href=`/api/formal-inventory/${encodeURIComponent(item.handoff_id)}/download`;formalResult.appendChild(link);
  }
}
async function renderFormalInventory(report){
  formalAnalysisId=report.analysis_id;formalLocations.replaceChildren();formalResult.replaceChildren();
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
window.PortableInventory={render:renderFormalInventory};
