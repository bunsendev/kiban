const productionPanel = document.getElementById('production-run');
const productionForm = document.getElementById('production-run-form');
const productionState = document.getElementById('production-state');
const productionResult = document.getElementById('production-result');
const summaryPanel = document.getElementById('daily-summary');
const summaryForm = document.getElementById('daily-summary-form');
const summaryState = document.getElementById('daily-summary-state');
const projectionResult = document.getElementById('projection-result');
let productionBuild = null;
let productionPoll = null;

function productionMessage(value, kind = '') {
  productionState.textContent = value;
  productionState.className = kind;
}

function summaryMessage(value, kind = '') {
  summaryState.textContent = value;
  summaryState.className = kind;
}

function statusName(value) {
  return {
    QUEUED: '登録済み・開始待ち', RUNNING: '予測を計算中', SUCCEEDED: '正式予測が完了',
    PARTIAL: '一部失敗', FAILED: '予測に失敗', CANCELLED: '中止',
  }[value] || value;
}

function appendCells(row, values) {
  for (const value of values) {
    const cell = document.createElement('td');
    cell.textContent = value;
    row.appendChild(cell);
  }
}

function renderProduction(value) {
  productionResult.replaceChildren();
  projectionResult.replaceChildren();
  window.PortableShipmentDecision?.reset();
  if (!value) return;
  const box = document.createElement('div');
  box.className = 'production-status';
  const title = document.createElement('strong');
  title.textContent = statusName(value.run_status);
  box.appendChild(title);
  const detail = document.createElement('p');
  detail.textContent = `対象 ${value.eligible_series.length}系列／確認が必要 ${value.blocked_series.length}系列／モデル ${value.provider_id}/${value.model_name}`;
  box.appendChild(detail);
  if (value.runtime_resolutions?.length) {
    const runtime = document.createElement('ul');
    for (const resolution of value.runtime_resolutions) {
      const item = document.createElement('li');
      item.textContent = `${resolution.pilot_scope_version}：${resolution.selected_version}（${resolution.status}／設定SHA-256 ${resolution.selected_configuration_sha256}）`;
      runtime.appendChild(item);
    }
    box.appendChild(runtime);
  }
  if (value.blocked_series.length) {
    const text = document.createElement('p');
    text.textContent = `予測対象外：${value.blocked_series.join('、')}`;
    box.appendChild(text);
  }
  if (value.worker_error) {
    const text = document.createElement('p');
    text.className = 'error';
    text.textContent = value.worker_error;
    box.appendChild(text);
  }
  if (value.point_predictions?.length) {
    const grouped = new Map();
    for (const item of value.point_predictions) {
      if (!grouped.has(item.unique_id)) grouped.set(item.unique_id, []);
      grouped.get(item.unique_id).push(item);
    }
    const table = document.createElement('table');
    table.innerHTML = '<thead><tr><th>系列</th><th>7日予測</th><th>14日予測</th><th>期間</th></tr></thead>';
    const body = document.createElement('tbody');
    for (const [uid, items] of grouped) {
      items.sort((a, b) => a.horizon - b.horizon);
      const row = document.createElement('tr');
      appendCells(row, [
        uid,
        items.filter(item => item.horizon <= 7).reduce((sum, item) => sum + Number(item.yhat), 0).toFixed(2),
        items.reduce((sum, item) => sum + Number(item.yhat), 0).toFixed(2),
        `${items[0].target_date}〜${items[items.length - 1].target_date}`,
      ]);
      body.appendChild(row);
    }
    table.appendChild(body);
    box.appendChild(table);
  }
  productionResult.appendChild(box);
  summaryPanel.hidden = value.run_status !== 'SUCCEEDED';
  productionMessage(
    value.run_status === 'SUCCEEDED'
      ? '正式予測が完了しました。倉庫別の日次サマリーを作成できます。'
      : statusName(value.run_status),
    value.run_status === 'FAILED' ? 'error' : value.run_status === 'SUCCEEDED' ? 'success' : '',
  );
  if (['QUEUED', 'RUNNING'].includes(value.run_status)) schedulePoll();
}

async function loadProduction() {
  if (!productionBuild) return;
  try {
    const response = await fetch(`/api/formal-forecast/${encodeURIComponent(productionBuild)}/production-run`);
    const view = await response.json();
    if (!response.ok) throw new Error(view.detail || '正式予測の状態を確認できません。');
    if (view.queued) renderProduction(view.handoff);
  } catch (error) {
    productionMessage(error.message, 'error');
  }
}

function schedulePoll() {
  if (productionPoll) return;
  productionPoll = setTimeout(async () => {
    productionPoll = null;
    await loadProduction();
  }, 800);
}

async function showProduction(value) {
  if (productionPoll) {
    clearTimeout(productionPoll);
    productionPoll = null;
  }
  productionBuild = value?.build_id || null;
  productionPanel.hidden = !productionBuild;
  summaryPanel.hidden = true;
  productionResult.replaceChildren();
  projectionResult.replaceChildren();
  if (!productionBuild) return;
  if (!document.getElementById('production-actor').value) {
    document.getElementById('production-actor').value = document.getElementById('forecast-actor').value;
  }
  if (!document.getElementById('production-reason').value) {
    document.getElementById('production-reason').value = '確認済み日次buildから正式予測を更新';
  }
  await loadProduction();
}

productionForm.addEventListener('submit', async event => {
  event.preventDefault();
  if (!productionBuild) return;
  const button = document.getElementById('production-submit');
  button.disabled = true;
  productionMessage('正式予測Runへ登録しています。');
  try {
    const response = await fetch(`/api/formal-forecast/${encodeURIComponent(productionBuild)}/production-run`, {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        actor: document.getElementById('production-actor').value,
        reason: document.getElementById('production-reason').value,
        confirm_production_queue: document.getElementById('production-confirm').checked,
      }),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || '正式予測を登録できませんでした。');
    renderProduction(result);
    await window.PortableRuntimeAssignments?.refresh();
  } catch (error) {
    productionMessage(error.message, 'error');
  } finally {
    button.disabled = false;
  }
});

function renderSummary(result) {
  projectionResult.replaceChildren();
  const notice = document.createElement('p');
  notice.className = 'notice';
  notice.textContent = result.notice;
  projectionResult.appendChild(notice);
  const cards = document.createElement('div');
  cards.className = 'cards';
  const totals = [
    [result.warehouses.length, '計算済み倉庫'],
    [result.rows.filter(item => item.replenishment_candidate).length, '補充確認候補'],
    [result.rows.filter(item => item.risk_flags.includes('EXPIRY_RISK')).length, '賞味期限注意'],
    [result.blockers.length, '計算できない倉庫'],
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
  projectionResult.appendChild(cards);
  const warehouseTable = document.createElement('table');
  warehouseTable.innerHTML = '<thead><tr><th>倉庫</th><th>対象商品</th><th>現在庫</th><th>7日需要</th><th>14日需要</th><th>14日不足</th><th>期限注意</th><th>期限内消化困難</th></tr></thead>';
  const warehouseBody = document.createElement('tbody');
  for (const item of result.warehouses) {
    const row = document.createElement('tr');
    appendCells(row, [item.warehouse_id, item.series_count, item.current_inventory_cases,
      item.demand_7d_cases, item.demand_14d_cases, item.shortage_reference_cases,
      item.expiry_attention_cases, item.unconsumed_by_cutoff_cases]);
    warehouseBody.appendChild(row);
  }
  warehouseTable.appendChild(warehouseBody);
  projectionResult.appendChild(warehouseTable);
  const productTable = document.createElement('table');
  productTable.innerHTML = '<thead><tr><th>JAN</th><th>倉庫</th><th>現在庫</th><th>14日需要</th><th>14日不足</th><th>最初の不足日</th><th>賞味期限注意</th><th>確認</th></tr></thead>';
  const productBody = document.createElement('tbody');
  for (const item of result.rows) {
    const row = document.createElement('tr');
    appendCells(row, [item.jan, item.warehouse_id, item.current_inventory_cases,
      item.demand_14d_cases, item.shortage_reference_cases, item.first_shortage_date || 'なし',
      item.expiry_attention_cases,
      item.risk_flags.length ? item.risk_flags.join('・') : '大きな注意なし']);
    productBody.appendChild(row);
  }
  productTable.appendChild(productBody);
  projectionResult.appendChild(productTable);
  if (result.blockers.length || result.excluded_series.length) {
    const details = document.createElement('details');
    const heading = document.createElement('summary');
    heading.textContent = '計算対象外・確認が必要なデータ';
    details.appendChild(heading);
    const list = document.createElement('ul');
    for (const blocker of result.blockers) {
      const item = document.createElement('li');
      item.textContent = `${blocker.source_center || '倉庫不明'}：${blocker.code}`;
      list.appendChild(item);
    }
    for (const series of result.excluded_series) {
      const item = document.createElement('li');
      item.textContent = `予測対象外系列：${series}`;
      list.appendChild(item);
    }
    details.appendChild(list);
    projectionResult.appendChild(details);
  }
  window.PortableShipmentDecision.show(productionBuild, result);
}

summaryForm.addEventListener('submit', async event => {
  event.preventDefault();
  if (!productionBuild) return;
  const button = document.getElementById('projection-load');
  button.disabled = true;
  summaryMessage('複数倉庫の在庫・不足・賞味期限を集計しています。');
  try {
    const response = await fetch(`/api/formal-forecast/${encodeURIComponent(productionBuild)}/daily-summary`, {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        actor: document.getElementById('production-actor').value,
        reason: document.getElementById('production-reason').value,
        minimum_remaining_days: Number(document.getElementById('expiry-minimum-days').value),
        attention_days: Number(document.getElementById('expiry-attention-days').value),
        confirm_expiry_policy: document.getElementById('expiry-policy-confirm').checked,
      }),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || '日次業務サマリーを作成できませんでした。');
    renderSummary(result);
    summaryMessage('倉庫別の日次業務サマリーを作成しました。', result.status === 'BLOCKED' ? 'error' : 'success');
  } catch (error) {
    summaryMessage(error.message, 'error');
  } finally {
    button.disabled = false;
  }
});

window.PortableProduction = {show: showProduction};
