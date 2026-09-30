const csv = document.getElementById('csv');
const run = document.getElementById('run');
const sample = document.getElementById('sample');
const state = document.getElementById('state');
const businessZip = document.getElementById('business-zip');
const analyze = document.getElementById('analyze');
const businessState = document.getElementById('business-state');
const backtest = document.getElementById('backtest');
let currentAnalysis = null;
const reasonLabels=window.PortableReview.reasonLabels;
function message(value, kind='') { state.textContent=value; state.className=kind; }
function businessMessage(value, kind='') { businessState.textContent=value; businessState.className=kind; }
businessZip.addEventListener('change', () => {
  const file=businessZip.files[0];
  document.getElementById('business-selected').textContent=file ? `${file.name} (${file.size} bytes)` : '未選択';
  analyze.disabled=!file; currentAnalysis=null; document.getElementById('analysis-result').hidden=true;
  businessMessage(file ? '分析の準備ができました。' : 'ZIPを選択してください。');
});
function showAnalysis(report) {
  currentAnalysis=report.analysis_id; document.getElementById('analysis-result').hidden=false;
  document.getElementById('auto-count').textContent=report.rows.auto_confirmed.toLocaleString();
  document.getElementById('review-count').textContent=report.rows.review_required.toLocaleString();
  document.getElementById('quarantine-count').textContent=report.rows.quarantined.toLocaleString();
  document.getElementById('analysis-detail').textContent=`出荷 ${report.rows.shipment.toLocaleString()}行、在庫 ${report.rows.inventory.toLocaleString()}行、在庫と出荷で一致した商品 ${report.products.inventory_codes_matched_to_shipment_jan}件。`;
  const reasons=document.getElementById('analysis-reasons'); reasons.replaceChildren();
  for (const [code,count] of Object.entries(report.reasons)) { const li=document.createElement('li'); li.textContent=`${reasonLabels[code]||code}: ${count.toLocaleString()}件`; reasons.appendChild(li); }
  window.PortableReview.render(report,async updated=>{showAnalysis(updated);businessMessage('担当者判断を保存し、確定済みデータを再集計しました。','success');await refreshAnalyses();});
  backtest.disabled=!report.center_windows.length || report.center_windows.some(item=>!item.backtest_ready);
  document.getElementById('backtest-state').textContent=backtest.disabled ? '直近35日のファイル不足により参考評価を開始できません。' : '自動判定OKと担当者が確定した出荷データで28日学習・7日評価を実行できます。';
}
analyze.addEventListener('click', async () => {
  const file=businessZip.files[0]; if (!file) return;
  analyze.disabled=true; backtest.disabled=true; businessMessage('全ファイルを分析中です。数分かかる場合があります。');
  try {
    const response=await fetch('/api/business-archives',{method:'POST',headers:{'Content-Type':'application/zip'},body:await file.arrayBuffer()});
    const result=await response.json(); if(!response.ok) throw new Error(result.detail||'分析に失敗しました。');
    showAnalysis(result); businessMessage('分析が完了しました。確認待ちと隔離件数を確認してください。','success'); await refreshAnalyses();
  } catch(error) { businessMessage(error.message,'error'); }
  finally { analyze.disabled=!businessZip.files[0]; }
});
backtest.addEventListener('click', async () => {
  if(!currentAnalysis) return; backtest.disabled=true; document.getElementById('backtest-state').textContent='参考評価を実行中です。';
  try {
    const response=await fetch(`/api/business-archives/${encodeURIComponent(currentAnalysis)}/backtest`,{method:'POST'});
    const result=await response.json(); if(!response.ok) throw new Error(result.detail||'参考評価に失敗しました。');
    const root=document.getElementById('backtest-result'); root.replaceChildren();
    for(const item of result.centers){ const p=document.createElement('p'); p.textContent=`${item.center}: ${item.series}系列、MAE ${item.mae}、WAPE ${item.wape===null?'算出不可':(item.wape*100).toFixed(2)+'%'}`; root.appendChild(p); }
    document.getElementById('backtest-state').textContent=result.notice;
  } catch(error) { document.getElementById('backtest-state').textContent=error.message; }
  finally { backtest.disabled=false; }
});
async function refreshAnalyses() {
  const list=document.getElementById('analysis-history'); list.replaceChildren();
  try {
    const response=await fetch('/api/business-archives'); const records=await response.json();
    for(const item of records){ const li=document.createElement('li'); const button=document.createElement('button');
      const pending=item.review?.pending_rows??(item.rows.review_required+item.rows.quarantined);
      button.textContent=`${item.review?.status||item.status}　OK ${item.rows.auto_confirmed.toLocaleString()}　未確認 ${pending.toLocaleString()}`;
      button.addEventListener('click',async()=>{const detail=await fetch(`/api/business-archives/${encodeURIComponent(item.analysis_id)}`);if(detail.ok)showAnalysis(await detail.json());});
      li.appendChild(button);list.appendChild(li); }
  } catch { const li=document.createElement('li'); li.textContent='過去の分析を読み込めません。'; list.appendChild(li); }
}
document.getElementById('analysis-reload').addEventListener('click',refreshAnalyses);
csv.addEventListener('change', () => {
  const file=csv.files[0];
  document.getElementById('selected').textContent=file ? `${file.name} (${file.size} bytes)` : '未選択';
  run.disabled=!file;
  message(file ? '読み込み準備ができました。' : 'CSVを選択してください。');
});
function show(record) {
  if (!record.predictions) return;
  document.getElementById('result-section').hidden=false;
  document.getElementById('meta').textContent=`実行ID: ${record.run_id}　入力SHA-256: ${record.input_sha256}　結果SHA-256: ${record.result_sha256}`;
  const body=document.getElementById('result'); body.replaceChildren();
  for (const row of record.predictions) {
    const tr=document.createElement('tr');
    for (const value of [row.unique_id,row.target_date,row.horizon,row.yhat]) {
      const td=document.createElement('td'); td.textContent=String(value); tr.appendChild(td);
    }
    body.appendChild(tr);
  }
  document.getElementById('download').href=`/api/runs/${encodeURIComponent(record.run_id)}/download`;
}
async function refresh() {
  try {
    const response=await fetch('/api/runs');
    const records=await response.json();
    const list=document.getElementById('history'); list.replaceChildren();
    for (const item of records) {
      const li=document.createElement('li');
      const button=document.createElement('button'); button.textContent=`${item.started_at}　${item.status}　${item.run_id}`;
      button.addEventListener('click', async () => {
        const detail=await fetch(`/api/runs/${encodeURIComponent(item.run_id)}`);
        if (detail.ok) show(await detail.json()); else message('保存結果を確認できません。','error');
      });
      li.appendChild(button); list.appendChild(li);
    }
  } catch { message('履歴を読み込めません。','error'); }
}
async function submit(data) {
  run.disabled=true; sample.disabled=true; message('処理中です。画面を閉じずにお待ちください。');
  try {
    const response=await fetch('/api/runs', {method:'POST', headers:{'Content-Type':'text/csv'}, body:data});
    const result=await response.json();
    if (!response.ok) throw new Error(result.detail || '処理に失敗しました。');
    show(result); message('予測が完了し、PC内に保存しました。','success'); await refresh();
  } catch (error) { message(error.message,'error'); }
  finally { run.disabled=!csv.files[0]; sample.disabled=false; }
}
run.addEventListener('click', async () => {
  const file=csv.files[0]; if (!file) return;
  await submit(await file.arrayBuffer());
});
sample.addEventListener('click', async () => {
  try {
    const response=await fetch('/api/sample.csv');
    if (!response.ok) throw new Error('付属CSVを読み込めません。');
    await submit(await response.arrayBuffer());
  } catch (error) { message(error.message,'error'); }
});
document.getElementById('reload').addEventListener('click',refresh);
refresh();
refreshAnalyses();
