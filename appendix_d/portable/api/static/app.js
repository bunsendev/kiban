const csv = document.getElementById('csv');
const run = document.getElementById('run');
const sample = document.getElementById('sample');
const state = document.getElementById('state');
function message(value, kind='') { state.textContent=value; state.className=kind; }
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
