const reviewReasonLabels={
  JAN_12_DIGITS:'12桁JAN',
  EXPIRY_MISSING:'賞味期限なし',
  INVENTORY_ROW_INVALID:'在庫の商品コード・数量が不正',
  INVENTORY_CODE_UNMATCHED:'出荷JANと一致しない在庫商品',
  SHIPMENT_ROW_INVALID:'出荷日・JAN・数量が不正',
  HEADER_MISSING:'必要な列が不足'
};
const actionLabels={MAP_JAN:'13桁JANへ対応付け',ACCEPT_MISSING_EXPIRY:'賞味期限なしを確認済みにする',EXCLUDE:'今回の予測対象から除外'};
function element(tag,text='',className=''){
  const node=document.createElement(tag); node.textContent=text; if(className)node.className=className; return node;
}
function availableActions(issue){
  if(['JAN_12_DIGITS','INVENTORY_CODE_UNMATCHED'].includes(issue.reason))return ['MAP_JAN','EXCLUDE'];
  if(issue.reason==='EXPIRY_MISSING')return ['ACCEPT_MISSING_EXPIRY','EXCLUDE'];
  return ['EXCLUDE'];
}
function decisionText(decision){
  if(!decision)return '';
  const jan=decision.corrected_jan?` → ${decision.corrected_jan}`:'';
  const source=decision.source==='REMEMBERED_RULE'?'保存済み判断を自動適用':'担当者が確定';
  const note=decision.note?`　メモ: ${decision.note}`:'';
  return `${source}: ${actionLabels[decision.action]||decision.action}${jan}${note}`;
}
async function renderHistory(analysisId){
  const root=document.getElementById('decision-history');root.replaceChildren();
  try{
    const response=await fetch(`/api/business-archives/${encodeURIComponent(analysisId)}/decision-history`);
    if(!response.ok)throw new Error();
    const records=await response.json();
    if(!records.length){root.appendChild(element('li','まだ判断履歴はありません。'));return;}
    for(const item of [...records].reverse()){
      const jan=item.corrected_jan?` → ${item.corrected_jan}`:'';const note=item.note?`／${item.note}`:'';
      root.appendChild(element('li',`${item.decided_at}　${reviewReasonLabels[item.reason]||item.reason}　${actionLabels[item.action]||item.action}${jan}${note}`));
    }
  }catch{root.appendChild(element('li','判断履歴を読み込めません。','error'));}
}
function decisionForm(report,issue,onUpdated){
  const form=element('form','','decision-form');
  const select=document.createElement('select'); select.setAttribute('aria-label','判断');
  for(const action of availableActions(issue)){const option=document.createElement('option');option.value=action;option.textContent=actionLabels[action];select.appendChild(option);}
  const jan=document.createElement('input'); jan.placeholder='確認済み13桁JAN'; jan.inputMode='numeric'; jan.maxLength=13; jan.setAttribute('aria-label','確認済み13桁JAN');
  const rememberLabel=element('label','','remember'); const remember=document.createElement('input'); remember.type='checkbox'; rememberLabel.append(remember,document.createTextNode('同じ値を次回も使用'));
  const note=document.createElement('input'); note.placeholder='判断メモ（任意）'; note.maxLength=500; note.setAttribute('aria-label','判断メモ');
  const submit=element('button','判断を保存'); submit.type='submit';
  const status=element('p','','decision-status'); status.setAttribute('role','status');
  function sync(){const mapping=select.value==='MAP_JAN';jan.hidden=!mapping;remember.hidden=!mapping;rememberLabel.hidden=!mapping;}
  select.addEventListener('change',sync);sync();
  form.append(select,jan,rememberLabel,note,submit,status);
  form.addEventListener('submit',async event=>{
    event.preventDefault();submit.disabled=true;status.textContent='保存中です。';
    try{
      const response=await fetch(`/api/business-archives/${encodeURIComponent(report.analysis_id)}/issues/${encodeURIComponent(issue.issue_id)}`,{
        method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:select.value,corrected_jan:jan.value,note:note.value,remember:remember.checked})
      });
      const result=await response.json();if(!response.ok)throw new Error(result.detail||'判断を保存できませんでした。');
      await onUpdated(result);
    }catch(error){status.textContent=error.message;status.className='decision-status error';submit.disabled=false;}
  });
  return form;
}
async function renderReview(report,onUpdated){
  const state=document.getElementById('review-state');const root=document.getElementById('review-items');root.replaceChildren();
  const review=report.review||{pending_items:0,pending_rows:0,resolved_items:0,resolved_rows:0};
  renderHistory(report.analysis_id);
  state.textContent=`未確認 ${review.pending_items}項目・${review.pending_rows.toLocaleString()}行／確定済み ${review.resolved_items}項目・${review.resolved_rows.toLocaleString()}行`;
  if(!report.issues?.length){root.appendChild(element('p','確認が必要なデータはありません。','success'));return;}
  for(const issue of report.issues){
    const card=element('article','','issue-card');
    card.appendChild(element('h4',`${reviewReasonLabels[issue.reason]||issue.reason}（${issue.count.toLocaleString()}行）`));
    card.appendChild(element('p',`元の値: ${issue.source_value||'空欄'}${issue.label?`　${issue.label}`:''}`,'source-value'));
    if(issue.missing_expiry_count)card.appendChild(element('p',`うち賞味期限なし: ${issue.missing_expiry_count.toLocaleString()}行`));
    if(issue.decision){
      card.appendChild(element('p',decisionText(issue.decision),'decision-done'));
      const details=document.createElement('details');details.appendChild(element('summary','判断を変更'));details.appendChild(decisionForm(report,issue,onUpdated));card.appendChild(details);
    }else{card.appendChild(decisionForm(report,issue,onUpdated));}
    root.appendChild(card);
  }
}
window.PortableReview={reasonLabels:reviewReasonLabels,render:renderReview};
