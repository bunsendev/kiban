/* Local admin UI: render all external values as text. */
const labels = {dimension:'集計軸',value:'集計値',product:'商品',unit:'単位',count:'回数',quantity:'数量',before:'導入前',after:'導入後',reduction_percent:'数量削減率（%）'};
const el = id => document.getElementById(id);
async function request(url, options) {
  const response = await fetch(url, options), data = await response.json();
  if (!response.ok) throw new Error(data.detail || '処理できませんでした');
  return data;
}
function table(parent, rows) {
  if (!rows.length) { const p = document.createElement('p'); p.textContent = '該当する確認済みデータなし'; parent.append(p); return; }
  const t = document.createElement('table'), head = t.createTHead().insertRow();
  Object.keys(rows[0]).forEach(k => { const th = document.createElement('th'); th.textContent = labels[k] || k; head.append(th); });
  const body = t.createTBody(); rows.forEach(r => { const tr = body.insertRow(); Object.values(r).forEach(v => { tr.insertCell().textContent = v === null ? '算出不可' : String(v); }); }); parent.append(t);
}
function details(parent, title, value) {
  const d = document.createElement('details'), s = document.createElement('summary'), p = document.createElement('pre');
  s.textContent = title; p.textContent = JSON.stringify(value, null, 2); d.append(s, p); parent.append(d);
}
function action(id, handler) { el(id).onclick = async () => { el(id).disabled = true; try { await handler(); el('message').textContent = '処理が完了しました'; } catch(e) { el('message').textContent = e.message; } finally { el(id).disabled = false; } }; }
action('upload', async () => { const f = el('file').files[0]; if (!f) throw new Error('CSVを選んでください'); await request('/api/warehouse-transfers', {method:'POST', headers:{'X-Bunsen-Reviewer':encodeURIComponent(el('reviewer').value)}, body:f}); alert('分類済み伝票を保存しました'); });
action('show', async () => {
  const r = await request('/api/warehouse-transfers?' + new URLSearchParams({start:el('start').value,end:el('end').value}));
  const p = el('report'); p.replaceChildren();
  table(p,[{移動回数:r.transfer_count,要確認行:r.unresolved_count,通常出荷行:r.customer_shipment_rows,観測日数:r.observed_dates,取扱商品数:r.observed_products}]);
  table(p,r.aggregates); details(p,'在庫増減（既存在庫には未適用）',r.inventory_deltas); details(p,'元伝票・原本SHA・分類根拠',r.events);
});
action('compare', async () => {
  const r = await request('/api/warehouse-transfers/comparison?' + new URLSearchParams({before_start:el('bs').value,before_end:el('be').value,after_start:el('as').value,after_end:el('ae').value,coverage_confirmed:el('coverage').checked}));
  const p = el('comparison'); p.replaceChildren(); table(p,[{導入前回数:r.before.transfer_count,導入後回数:r.after.transfer_count,回数削減率:r.count_reduction_percent}]); table(p,r.quantities); details(p,'期間・観測日・商品数・通常出荷量・要確認件数',r);
});
