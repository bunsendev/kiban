const shipmentReviewPanel = document.getElementById('decision-review');
const shipmentReviewForm = document.getElementById('decision-review-form');
const shipmentReviewState = document.getElementById('decision-review-state');
const shipmentReviewHistory = document.getElementById('decision-review-history');
let shipmentReviewContext = null;
let shipmentReviewData = null;
let shipmentReviewTarget = null;

function shipmentReviewKey(item) {
  return `${item.jan}::${item.warehouse_id}`;
}

function shipmentReviewEndpoint() {
  const {buildId, summary, result} = shipmentReviewContext;
  return `/api/formal-forecast/${encodeURIComponent(buildId)}`
    + `/daily-summary/${encodeURIComponent(summary.request_key)}`
    + `/shipment-recommendation/${encodeURIComponent(result.request_key)}/review`;
}

function appendShipmentReviewCells(row, values) {
  for (const value of values) {
    const cell = document.createElement('td');
    cell.textContent = value;
    row.appendChild(cell);
  }
}

function resetShipmentReview() {
  shipmentReviewPanel.hidden = true;
  shipmentReviewHistory.replaceChildren();
  shipmentReviewContext = null;
  shipmentReviewData = null;
  shipmentReviewTarget = null;
}

async function loadShipmentReview(buildId, summary, result) {
  shipmentReviewContext = {buildId, summary, result};
  shipmentReviewPanel.hidden = false;
  try {
    const response = await fetch(shipmentReviewEndpoint());
    const value = await response.json();
    if (!response.ok) throw new Error(value.detail || '判断履歴を取得できませんでした。');
    shipmentReviewData = value;
    renderShipmentReview(value);
  } catch (error) {
    shipmentReviewState.textContent = error.message;
    shipmentReviewState.className = 'error';
  }
}

function selectShipmentReview(item) {
  shipmentReviewTarget = item;
  const latest = shipmentReviewData?.latest?.[shipmentReviewKey(item)];
  document.getElementById('decision-review-target').textContent =
    `${item.jan}／${item.warehouse_id}　推奨 ${item.recommended_shipment_cases}箱`
    + `${latest ? `　保存済み判断：${latest.operator_decision}（版${latest.revision}）` : ''}`;
  document.getElementById('decision-review-action').value = 'ACCEPTED';
  document.getElementById('decision-review-quantity').value = item.recommended_shipment_cases;
  document.getElementById('decision-review-reason').value = '';
  document.getElementById('decision-review-comment').value = '';
  document.getElementById('decision-review-confirm').checked = false;
  shipmentReviewState.textContent = '';
  shipmentReviewPanel.scrollIntoView({behavior: 'smooth', block: 'start'});
}

function renderShipmentReview(value) {
  shipmentReviewHistory.replaceChildren();
  const summary = document.createElement('p');
  summary.textContent = `確認済み ${Object.keys(value.latest).length}件／判断履歴 ${value.history.length}件。${value.notice}`;
  shipmentReviewHistory.appendChild(summary);
  if (value.history.length) {
    const table = document.createElement('table');
    table.innerHTML = '<thead><tr><th>JAN</th><th>倉庫</th><th>版</th><th>判断</th><th>推奨</th><th>判断後</th><th>理由</th><th>確認者</th></tr></thead>';
    const body = document.createElement('tbody');
    for (const item of value.history) {
      const row = document.createElement('tr');
      appendShipmentReviewCells(row, [item.jan, item.warehouse_id, item.revision,
        item.operator_decision, item.system_quantity_cases,
        item.operator_quantity_cases ?? '—', item.reason_code ?? '—', item.actor]);
      body.appendChild(row);
    }
    table.appendChild(body);
    shipmentReviewHistory.appendChild(table);
  }
  if (value.improvement_candidates.length) {
    const details = document.createElement('details');
    const heading = document.createElement('summary');
    heading.textContent = `設定改善候補 ${value.improvement_candidates.length}件を確認`;
    details.appendChild(heading);
    const list = document.createElement('ul');
    for (const item of value.improvement_candidates) {
      const entry = document.createElement('li');
      entry.textContent = `${item.operator_decision}／${item.reason_code}：${item.count}件`
        + `${item.average_delta_cases === null ? '' : `、平均差 ${item.average_delta_cases}箱`}`
        + '（自動反映なし）';
      list.appendChild(entry);
    }
    details.appendChild(list);
    shipmentReviewHistory.appendChild(details);
  }
}

document.getElementById('decision-review-action').addEventListener('change', event => {
  if (!shipmentReviewTarget) return;
  const quantity = document.getElementById('decision-review-quantity');
  if (event.target.value === 'ACCEPTED') {
    quantity.value = shipmentReviewTarget.recommended_shipment_cases;
  }
  if (event.target.value === 'NO_ACTION') quantity.value = '0';
  if (event.target.value === 'REJECTED') quantity.value = '';
});

shipmentReviewForm.addEventListener('submit', async event => {
  event.preventDefault();
  if (!shipmentReviewTarget || !shipmentReviewData) {
    shipmentReviewState.textContent = '先に試算表の「判断を入力」を押してください。';
    shipmentReviewState.className = 'error';
    return;
  }
  const button = document.getElementById('decision-review-submit');
  button.disabled = true;
  shipmentReviewState.textContent = '担当者判断を保存しています。';
  shipmentReviewState.className = '';
  const latest = shipmentReviewData.latest[shipmentReviewKey(shipmentReviewTarget)];
  try {
    const response = await fetch(shipmentReviewEndpoint(), {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        jan: shipmentReviewTarget.jan,
        warehouse_id: shipmentReviewTarget.warehouse_id,
        expected_revision: latest?.revision ?? 0,
        operator_decision: document.getElementById('decision-review-action').value,
        operator_quantity_cases: document.getElementById('decision-review-quantity').value || null,
        reason_code: document.getElementById('decision-review-reason').value || null,
        comment: document.getElementById('decision-review-comment').value || null,
        actor: document.getElementById('decision-review-actor').value,
        confirm_shadow_review: document.getElementById('decision-review-confirm').checked,
      }),
    });
    const value = await response.json();
    if (!response.ok) throw new Error(value.detail || '担当者判断を保存できませんでした。');
    shipmentReviewData = value;
    renderShipmentReview(value);
    selectShipmentReview(shipmentReviewTarget);
    shipmentReviewState.textContent = '判断を追記しました。設定へは自動反映されません。';
    shipmentReviewState.className = 'success';
  } catch (error) {
    shipmentReviewState.textContent = error.message;
    shipmentReviewState.className = 'error';
    if (error.message.includes('表示を更新')) {
      const {buildId, summary, result} = shipmentReviewContext;
      await loadShipmentReview(buildId, summary, result);
    }
  } finally {
    button.disabled = false;
  }
});

window.PortableShipmentReview = {
  load: loadShipmentReview,
  reset: resetShipmentReview,
  select: selectShipmentReview,
};
