const decisionPanel = document.getElementById('shipment-decision');
const decisionForm = document.getElementById('shipment-decision-form');
const decisionState = document.getElementById('shipment-decision-state');
const decisionResult = document.getElementById('shipment-decision-result');
let decisionBuild = null;
let decisionSummary = null;

function decisionMessage(value, kind = '') {
  decisionState.textContent = value;
  decisionState.className = kind;
}

function decisionCells(row, values) {
  for (const value of values) {
    const cell = document.createElement('td');
    cell.textContent = value;
    row.appendChild(cell);
  }
}

function csvRows(text) {
  return text.replace(/^\uFEFF/, '').split(/\r?\n/).slice(1)
    .filter(line => line.trim()).map(line => line.split(',').map(value => value.trim()));
}

function loadCsvFile(inputId, targetId) {
  document.getElementById(inputId).addEventListener('change', async event => {
    const file = event.target.files[0];
    if (file) document.getElementById(targetId).value = await file.text();
  });
}

function resetDecision() {
  decisionBuild = null;
  decisionSummary = null;
  decisionPanel.hidden = true;
  decisionResult.replaceChildren();
}

function showDecision(buildId, summary) {
  decisionBuild = buildId;
  decisionSummary = summary;
  decisionPanel.hidden = false;
  decisionResult.replaceChildren();
  const uniqueJans = [...new Set(summary.rows.map(item => item.jan))].sort();
  document.getElementById('decision-inventory-csv').value =
    `JAN,現在庫（箱）\n${uniqueJans.map(jan => `${jan},`).join('\n')}`;
  document.getElementById('decision-production-csv').value =
    '予定ID,版,JAN,完成予定日時,数量（箱）\n';
  const snapshot = new Date(summary.calculation_at);
  snapshot.setMinutes(snapshot.getMinutes() - snapshot.getTimezoneOffset());
  document.getElementById('decision-snapshot-at').value = snapshot.toISOString().slice(0, 16);
}

function renderDecision(result) {
  decisionResult.replaceChildren();
  const notice = document.createElement('p');
  notice.className = 'notice';
  notice.textContent = result.notice;
  decisionResult.appendChild(notice);
  const cards = document.createElement('div');
  cards.className = 'cards';
  const totals = [
    [result.recommendations.length, '計算済み商品・倉庫'],
    [result.recommendations.filter(item => Number(item.recommended_shipment_cases) > 0).length,
      '出荷候補'],
    [result.recommendations.reduce((sum, item) => sum + Number(item.unmet_cases), 0).toFixed(2),
      '未充足（箱）'],
    [result.blockers.length + result.source_blockers.length, '確認が必要'],
  ];
  for (const [value, label] of totals) {
    const card = document.createElement('div');
    const strong = document.createElement('strong');
    strong.textContent = value;
    const span = document.createElement('span');
    span.textContent = label;
    card.append(strong, span);
    cards.appendChild(card);
  }
  decisionResult.appendChild(cards);
  const table = document.createElement('table');
  table.innerHTML = '<thead><tr><th>JAN</th><th>倉庫</th><th>到着予定</th><th>到着時点在庫</th><th>必要補充</th><th>工場出荷可能</th><th>推奨出荷</th><th>未充足</th><th>理由・リスク</th></tr></thead>';
  const body = document.createElement('tbody');
  for (const item of result.recommendations) {
    const row = document.createElement('tr');
    decisionCells(row, [item.jan, item.warehouse_id, item.arrival_at,
      item.arrival_time_inventory_cases, item.required_replenishment_cases,
      item.factory_available_before_cases, item.recommended_shipment_cases,
      item.unmet_cases, `${item.reason}${item.risk_flags.length ? `／${item.risk_flags.join('・')}` : ''}`]);
    body.appendChild(row);
  }
  table.appendChild(body);
  decisionResult.appendChild(table);
  const blockers = [...result.source_blockers, ...result.blockers];
  if (blockers.length) {
    const details = document.createElement('details');
    const heading = document.createElement('summary');
    heading.textContent = '計算対象外・確認が必要な入力';
    details.appendChild(heading);
    const list = document.createElement('ul');
    for (const blocker of blockers) {
      const item = document.createElement('li');
      item.textContent = `${blocker.jan || blocker.source_center || '対象不明'}／${blocker.warehouse_id || ''}：${blocker.code}`;
      list.appendChild(item);
    }
    details.appendChild(list);
    decisionResult.appendChild(details);
  }
}

function requestPayload() {
  const factoryId = document.getElementById('decision-factory-id').value.trim();
  const version = document.getElementById('decision-policy-version').value.trim();
  const snapshotAt = new Date(document.getElementById('decision-snapshot-at').value).toISOString();
  const inventoryRows = csvRows(document.getElementById('decision-inventory-csv').value);
  if (inventoryRows.some(row => row.length !== 2 || !row[0] || !row[1])) {
    throw new Error('工場在庫CSVのJANと現在庫（箱）をすべて入力してください。');
  }
  const productionRows = csvRows(document.getElementById('decision-production-csv').value);
  if (productionRows.some(row => row.length !== 5 || row.some(value => !value))) {
    throw new Error('生産予定CSVは5列すべて入力してください。');
  }
  const warehouses = decisionSummary.warehouses.map(item => item.warehouse_id);
  return {
    actor: document.getElementById('production-actor').value,
    reason: document.getElementById('production-reason').value,
    confirm_decision_inputs: document.getElementById('decision-confirm').checked,
    routes: warehouses.map(warehouseId => ({
      policy_id: `${version}-route-${warehouseId}`,
      policy_version: `${version}-route-${warehouseId}`,
      location_master_version: `${version}-locations`, factory_location_id: factoryId,
      warehouse_location_id: warehouseId,
      minimum_hours: Number(document.getElementById('decision-min-hours').value),
      standard_hours: Number(document.getElementById('decision-standard-hours').value),
      maximum_hours: Number(document.getElementById('decision-max-hours').value),
      recommendation_basis: document.getElementById('decision-basis').value,
      effective_from: decisionSummary.calculation_at.slice(0, 10), effective_to: null,
    })),
    safety_stock_policies: warehouses.map(warehouseId => ({
      policy_version: `${version}-safety-${warehouseId}`, warehouse_id: warehouseId,
      coverage_days: Number(document.getElementById('decision-safety-days').value),
      shipment_unit_cases: document.getElementById('decision-unit-cases').value,
    })),
    factory_supplies: inventoryRows.map(row => ({
      snapshot_id: `${version}-factory-snapshot`, snapshot_at: snapshotAt,
      factory_id: factoryId, jan: row[0], inventory_cases: row[1],
    })),
    production_plans: productionRows.map(row => ({
      plan_id: row[0], plan_version: row[1], factory_id: factoryId,
      jan: row[2], completion_at: new Date(row[3]).toISOString(), quantity_cases: row[4],
    })),
  };
}

decisionForm.addEventListener('submit', async event => {
  event.preventDefault();
  if (!decisionBuild || !decisionSummary) return;
  const button = document.getElementById('decision-submit');
  button.disabled = true;
  decisionMessage('到着時点在庫と工場出荷可能量を計算しています。');
  try {
    const endpoint = `/api/formal-forecast/${encodeURIComponent(decisionBuild)}/daily-summary/${encodeURIComponent(decisionSummary.request_key)}/shipment-recommendation`;
    const response = await fetch(endpoint, {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(requestPayload()),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || '推奨出荷量を計算できませんでした。');
    renderDecision(result);
    decisionMessage('推奨出荷量の試算を作成しました。', 'success');
  } catch (error) {
    decisionMessage(error.message, 'error');
  } finally {
    button.disabled = false;
  }
});

loadCsvFile('decision-inventory-file', 'decision-inventory-csv');
loadCsvFile('decision-production-file', 'decision-production-csv');
window.PortableShipmentDecision = {reset: resetDecision, show: showDecision};
