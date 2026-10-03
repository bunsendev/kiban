const outcomePanel = document.getElementById('decision-outcomes');
const outcomeForm = document.getElementById('decision-outcome-form');
const outcomeState = document.getElementById('decision-outcome-state');
const outcomeResult = document.getElementById('decision-outcome-result');
let outcomeContext = null;

function outcomeEndpoint(suffix = '') {
  const {buildId, summary, result} = outcomeContext;
  const base = `/api/formal-forecast/${encodeURIComponent(buildId)}`
    + `/daily-summary/${encodeURIComponent(summary.request_key)}`
    + `/shipment-recommendation/${encodeURIComponent(result.request_key)}/outcomes`;
  return `${base}${suffix}`;
}

function outcomeValue(value) {
  return value === null || value === undefined ? '—' : value;
}

function appendOutcomeCells(row, values) {
  for (const value of values) {
    const cell = document.createElement('td');
    cell.textContent = outcomeValue(value);
    row.appendChild(cell);
  }
}

function renderOutcomes(value) {
  outcomeResult.replaceChildren();
  const summary = document.createElement('p');
  summary.textContent = `実績あり ${value.actual_count}件／未取得 ${value.missing_actual_count}件。${value.notice}`;
  outcomeResult.appendChild(summary);
  const metrics = document.createElement('ul');
  metrics.innerHTML = `<li>需要予測 MAE：${outcomeValue(value.forecast_metrics.mae_cases)}箱</li>`
    + `<li>需要予測 WAPE：${outcomeValue(value.forecast_metrics.wape)}</li>`
    + `<li>需要予測 Bias：${outcomeValue(value.forecast_metrics.bias)}</li>`
    + `<li>欠品：${outcomeValue(value.business_kpis.stockout_cases)}箱（取得 ${value.kpi_coverage.stockout_cases}件）</li>`
    + `<li>期限切れ：${outcomeValue(value.business_kpis.expired_cases)}箱（取得 ${value.kpi_coverage.expired_cases}件）</li>`
    + `<li>倉庫間移動：${outcomeValue(value.business_kpis.interwarehouse_transfer_cases)}箱（取得 ${value.kpi_coverage.interwarehouse_transfer_cases}件）</li>`;
  outcomeResult.appendChild(metrics);
  const table = document.createElement('table');
  table.innerHTML = '<thead><tr><th>JAN</th><th>倉庫</th><th>System予測需要</th><th>System推奨</th><th>担当者判断</th><th>実出荷</th><th>実需要</th><th>欠品</th><th>期限切れ</th><th>倉庫間移動</th></tr></thead>';
  const body = document.createElement('tbody');
  for (const item of value.rows) {
    const row = document.createElement('tr');
    appendOutcomeCells(row, [item.jan, item.warehouse_id,
      item.system_forecast_arrival_demand_cases, item.system_recommended_shipment_cases,
      item.operator_quantity_cases, item.actual_shipped_cases,
      item.actual_demand_until_arrival_cases, item.stockout_cases,
      item.expired_cases, item.interwarehouse_transfer_cases]);
    body.appendChild(row);
  }
  table.appendChild(body);
  outcomeResult.appendChild(table);
  window.PortableLearningReviews?.refresh();
}

function resetOutcomes() {
  outcomePanel.hidden = true;
  outcomeResult.replaceChildren();
  outcomeContext = null;
}

async function loadOutcomes(buildId, summary, result) {
  outcomeContext = {buildId, summary, result};
  outcomePanel.hidden = false;
  document.getElementById('decision-outcome-template').href = outcomeEndpoint('/template');
  const now = new Date();
  now.setMinutes(now.getMinutes() - now.getTimezoneOffset());
  document.getElementById('decision-outcome-known-at').value = now.toISOString().slice(0, 16);
  try {
    const response = await fetch(outcomeEndpoint());
    const value = await response.json();
    if (!response.ok) throw new Error(value.detail || '後日実績を取得できませんでした。');
    renderOutcomes(value);
  } catch (error) {
    outcomeState.textContent = error.message;
    outcomeState.className = 'error';
  }
}

outcomeForm.addEventListener('submit', async event => {
  event.preventDefault();
  const file = document.getElementById('decision-outcome-file').files[0];
  if (!file || !outcomeContext) return;
  const button = document.getElementById('decision-outcome-submit');
  button.disabled = true;
  outcomeState.textContent = '後日実績を検証して保存しています。';
  outcomeState.className = '';
  try {
    const response = await fetch(outcomeEndpoint(), {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        csv_base64: bytesToBase64(await file.arrayBuffer()),
        source_version: document.getElementById('decision-outcome-source-version').value,
        known_at: new Date(document.getElementById('decision-outcome-known-at').value).toISOString(),
        confirm_actual_outcomes: document.getElementById('decision-outcome-confirm').checked,
      }),
    });
    const value = await response.json();
    if (!response.ok) throw new Error(value.detail || '後日実績を保存できませんでした。');
    renderOutcomes(value);
    outcomeState.textContent = '後日実績を追記しました。空欄は未取得のまま保持しています。';
    outcomeState.className = 'success';
  } catch (error) {
    outcomeState.textContent = error.message;
    outcomeState.className = 'error';
  } finally {
    button.disabled = false;
  }
});

window.PortableShipmentOutcomes = {load: loadOutcomes, reset: resetOutcomes};
