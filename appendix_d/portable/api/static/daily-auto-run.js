const dailyPanel = document.getElementById('daily-auto-run');
const dailyStatus = document.getElementById('daily-run-status');
const dailyForm = document.getElementById('daily-run-form');
const dailySummaryForm = document.getElementById('daily-auto-summary-form');
const dailyDecisionSection = document.getElementById('daily-decision-section');
const dailyDecisionForm = document.getElementById('daily-decision-input-form');
const dailyGuidedForm = document.getElementById('daily-guided-decision-form');
const dailyResult = document.getElementById('daily-run-result');
let dailyAnalysisId = null;
let dailyPoll = null;
let dailyRequirementsSha = null;

const dailyLabels = {
  REVIEW_REQUIRED: '確認待ち',
  INVENTORY_CONFIRMATION_REQUIRED: '正式在庫の確認待ち',
  INVENTORY_BLOCKED: '正式在庫を隔離',
  READY_TO_ADVANCE: 'Production予測まで実行可能',
  FORECAST_BLOCKED: '予測条件不足',
  PRODUCTION_CONFIRMATION_REQUIRED: 'Production予測の登録待ち',
  PRODUCTION_RUNNING: 'Production予測を計算中',
  PRODUCTION_BLOCKED: 'Production予測を停止',
  SUMMARY_CONFIRMATION_REQUIRED: '賞味期限条件の確認待ち',
  DECISION_INPUT_REQUIRED: '工場・配送条件の入力待ち',
  DECISION_INPUT_BLOCKED: '正式Decision入力を隔離',
  DECISION_BLOCKED: '推奨出荷の計算を停止',
  SHIPMENT_REVIEW_REQUIRED: '推奨出荷の担当者確認待ち',
  COMPLETED: '本日の日次実行が完了',
};

function dailyBytesToBase64(buffer) {
  const bytes = new Uint8Array(buffer);
  let binary = '';
  for (let offset = 0; offset < bytes.length; offset += 0x8000) {
    binary += String.fromCharCode(...bytes.subarray(offset, offset + 0x8000));
  }
  return btoa(binary);
}

function scheduleDailyPoll() {
  if (dailyPoll) return;
  dailyPoll = setTimeout(async () => {
    dailyPoll = null;
    await refreshDailyRun(dailyAnalysisId);
  }, 800);
}

async function showDailyDecision(value) {
  if (!value.summary_key || !value.recommendation_key) return;
  const prefix = `/api/formal-forecast/${encodeURIComponent(value.build_id)}`
    + `/daily-summary/${encodeURIComponent(value.summary_key)}`;
  const [summaryResponse, recommendationResponse] = await Promise.all([
    fetch(prefix),
    fetch(`${prefix}/shipment-recommendation/${encodeURIComponent(value.recommendation_key)}`),
  ]);
  const summary = await summaryResponse.json();
  const recommendation = await recommendationResponse.json();
  if (!summaryResponse.ok) throw new Error(summary.detail || '日次サマリーを表示できません。');
  if (!recommendationResponse.ok) {
    throw new Error(recommendation.detail || '推奨出荷を表示できません。');
  }
  window.PortableShipmentDecision?.show(value.build_id, summary);
  window.PortableShipmentDecision?.render(recommendation);
}

function renderGuidedInventory(requirements) {
  const root = document.getElementById('daily-guided-inventory');
  root.replaceChildren();
  const heading = document.createElement('h4');
  heading.textContent = `商品ごとの工場在庫（${requirements.jans.length}商品）`;
  root.appendChild(heading);
  const table = document.createElement('table');
  const head = document.createElement('thead');
  head.innerHTML = '<tr><th>JAN</th><th>現在庫（箱）</th></tr>';
  table.appendChild(head);
  const body = document.createElement('tbody');
  for (const jan of requirements.jans) {
    const row = document.createElement('tr');
    const janCell = document.createElement('td');
    janCell.textContent = jan;
    const quantityCell = document.createElement('td');
    const input = document.createElement('input');
    input.type = 'number';
    input.min = '0';
    input.step = 'any';
    input.required = true;
    input.dataset.jan = jan;
    input.setAttribute('aria-label', `${jan}の工場在庫（箱）`);
    quantityCell.appendChild(input);
    row.append(janCell, quantityCell);
    body.appendChild(row);
  }
  table.appendChild(body);
  root.appendChild(table);
}

async function loadDailyRequirements(value) {
  if (!value.summary_key || dailyRequirementsSha === value.summary_key) return;
  const response = await fetch(
    `/api/daily-runs/${encodeURIComponent(value.analysis_id)}/decision-inputs/requirements`
  );
  const requirements = await response.json();
  if (!response.ok) {
    throw new Error(requirements.detail || '不足している工場・配送条件を確認できません。');
  }
  dailyRequirementsSha = value.summary_key;
  document.getElementById('daily-decision-requirements').textContent =
    `対象は${requirements.warehouses.length}倉庫・${requirements.jans.length}商品です。`
    + '確認済みの値だけを入力してください。空欄を0箱として扱いません。';
  renderGuidedInventory(requirements);
}

async function renderDailyRun(value) {
  dailyPanel.hidden = false;
  dailyAnalysisId = value.analysis_id;
  dailyResult.replaceChildren();
  dailyStatus.textContent = `${dailyLabels[value.status] || value.status}：${value.next_action}`;
  const blocked = [
    'INVENTORY_BLOCKED', 'FORECAST_BLOCKED', 'PRODUCTION_BLOCKED',
    'DECISION_INPUT_BLOCKED', 'DECISION_BLOCKED',
  ];
  dailyStatus.className = value.status === 'COMPLETED'
    ? 'success' : (blocked.includes(value.status) ? 'error' : '');
  dailyForm.hidden = !['READY_TO_ADVANCE', 'PRODUCTION_CONFIRMATION_REQUIRED'].includes(
    value.status,
  );
  dailySummaryForm.hidden = value.status !== 'SUMMARY_CONFIRMATION_REQUIRED';
  dailyDecisionSection.hidden = ![
    'DECISION_INPUT_REQUIRED', 'DECISION_INPUT_BLOCKED',
  ].includes(value.status);
  if (value.summary_key) {
    document.getElementById('daily-decision-template').href =
      `/api/formal-forecast/${encodeURIComponent(value.build_id)}`
      + `/daily-summary/${encodeURIComponent(value.summary_key)}/decision-input-template`;
  }
  if (!dailyDecisionSection.hidden) await loadDailyRequirements(value);
  if (value.recommendation_key) await showDailyDecision(value);
  if (value.status === 'SHIPMENT_REVIEW_REQUIRED' || value.status === 'COMPLETED') {
    const p = document.createElement('p');
    p.textContent = `推奨 ${value.recommendation_count}件／担当者確認済み `
      + `${value.reviewed_recommendation_count}件／日次実行版 ${value.revision}`;
    dailyResult.appendChild(p);
  }
  if (value.status === 'COMPLETED') {
    const link = document.createElement('a');
    link.textContent = '予測結果JSONを保存';
    link.href = `/api/formal-forecast/${encodeURIComponent(value.build_id)}/download`;
    dailyResult.appendChild(link);
  }
  if (value.blockers?.length) {
    const p = document.createElement('p');
    p.textContent = `停止理由 ${value.blockers.length}件。表示された確認欄で修正してください。`;
    dailyResult.appendChild(p);
  }
  if (value.status === 'PRODUCTION_RUNNING') scheduleDailyPoll();
}

async function refreshDailyRun(analysisId) {
  if (!analysisId) return;
  try {
    const response = await fetch(`/api/daily-runs/${encodeURIComponent(analysisId)}`);
    const value = await response.json();
    if (!response.ok) throw new Error(value.detail || '日次実行を確認できません。');
    await renderDailyRun(value);
  } catch (error) {
    dailyPanel.hidden = false;
    dailyForm.hidden = true;
    dailyStatus.textContent = error.message;
    dailyStatus.className = 'error';
  }
}

dailyForm.addEventListener('submit', async event => {
  event.preventDefault();
  if (!dailyAnalysisId) return;
  const button = document.getElementById('daily-run-submit');
  button.disabled = true;
  dailyStatus.textContent = '正式在庫、出荷日次化、14日予測、Production予測を順番に実行中です。';
  try {
    const payload = {
      actor: document.getElementById('daily-run-actor').value,
      reason: document.getElementById('daily-run-reason').value,
      confirm_pilot_scope: document.getElementById('daily-confirm-scope').checked,
      confirm_quantity_reconciliation: document.getElementById('daily-confirm-quantity').checked,
      confirm_identity_bridge: document.getElementById('daily-confirm-identity').checked,
      confirm_zero_policy: document.getElementById('daily-confirm-zero').checked,
    };
    const response = await fetch(`/api/daily-runs/${encodeURIComponent(dailyAnalysisId)}/advance`, {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(payload),
    });
    const value = await response.json();
    if (!response.ok) throw new Error(value.detail || '日次実行を進められませんでした。');
    await renderDailyRun(value);
  } catch (error) {
    dailyStatus.textContent = error.message;
    dailyStatus.className = 'error';
  } finally {
    button.disabled = false;
  }
});

dailySummaryForm.addEventListener('submit', async event => {
  event.preventDefault();
  const button = document.getElementById('daily-summary-submit');
  button.disabled = true;
  dailyStatus.textContent = '賞味期限条件で倉庫別日次サマリーを作成しています。';
  try {
    const response = await fetch(
      `/api/daily-runs/${encodeURIComponent(dailyAnalysisId)}/daily-summary`,
      {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          actor: document.getElementById('daily-summary-actor').value,
          reason: document.getElementById('daily-summary-reason').value,
          minimum_remaining_days: Number(
            document.getElementById('daily-summary-minimum-days').value
          ),
          attention_days: Number(document.getElementById('daily-summary-attention-days').value),
          confirm_expiry_policy: document.getElementById('daily-summary-confirm').checked,
        }),
      },
    );
    const value = await response.json();
    if (!response.ok) throw new Error(value.detail || '日次サマリーを作成できませんでした。');
    await renderDailyRun(value);
  } catch (error) {
    dailyStatus.textContent = error.message;
    dailyStatus.className = 'error';
  } finally {
    button.disabled = false;
  }
});

dailyDecisionForm.addEventListener('submit', async event => {
  event.preventDefault();
  const button = document.getElementById('daily-decision-submit');
  const file = document.getElementById('daily-decision-file').files[0];
  button.disabled = true;
  dailyStatus.textContent = '工場・配送条件を検証し、到着時点在庫を計算しています。';
  try {
    const response = await fetch(
      `/api/daily-runs/${encodeURIComponent(dailyAnalysisId)}/decision-inputs`,
      {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          actor: document.getElementById('daily-decision-actor').value,
          reason: document.getElementById('daily-decision-reason').value,
          confirm_decision_inputs: document.getElementById('daily-decision-confirm').checked,
          archive_base64: dailyBytesToBase64(await file.arrayBuffer()),
        }),
      },
    );
    const value = await response.json();
    if (!response.ok) throw new Error(value.detail || '正式Decision入力を確認できませんでした。');
    await renderDailyRun(value);
  } catch (error) {
    dailyStatus.textContent = error.message;
    dailyStatus.className = 'error';
  } finally {
    button.disabled = false;
  }
});

dailyGuidedForm.addEventListener('submit', async event => {
  event.preventDefault();
  const button = document.getElementById('daily-guided-submit');
  button.disabled = true;
  dailyStatus.textContent = '画面入力を正式契約で検証し、到着時点在庫を計算しています。';
  try {
    const inventory = [...document.querySelectorAll('#daily-guided-inventory input[data-jan]')]
      .map(input => ({jan: input.dataset.jan, inventory_cases: input.value}));
    const snapshot = document.getElementById('daily-guided-snapshot').value;
    if (!snapshot) throw new Error('工場在庫の基準日時を入力してください。');
    const response = await fetch(
      `/api/daily-runs/${encodeURIComponent(dailyAnalysisId)}/decision-inputs/guided`,
      {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          actor: document.getElementById('daily-guided-actor').value,
          reason: document.getElementById('daily-guided-reason').value,
          factory_id: document.getElementById('daily-guided-factory').value,
          policy_version: document.getElementById('daily-guided-policy').value,
          snapshot_at: new Date(snapshot).toISOString(),
          route: {
            minimum_hours: Number(document.getElementById('daily-guided-min-hours').value),
            standard_hours: Number(document.getElementById('daily-guided-standard-hours').value),
            maximum_hours: Number(document.getElementById('daily-guided-max-hours').value),
            recommendation_basis: document.getElementById('daily-guided-basis').value,
          },
          safety_stock: {
            coverage_days: Number(document.getElementById('daily-guided-safety-days').value),
            shipment_unit_cases: document.getElementById('daily-guided-unit-cases').value,
          },
          factory_inventory: inventory,
          production_plans: [],
          confirm_decision_inputs: document.getElementById('daily-guided-confirm').checked,
        }),
      },
    );
    const value = await response.json();
    if (!response.ok) throw new Error(value.detail || '工場・配送条件を確認できませんでした。');
    await renderDailyRun(value);
  } catch (error) {
    dailyStatus.textContent = error.message;
    dailyStatus.className = 'error';
  } finally {
    button.disabled = false;
  }
});

document.addEventListener(
  'portable-analysis-changed', event => refreshDailyRun(event.detail.analysisId)
);
document.addEventListener(
  'portable-shipment-review-changed', () => refreshDailyRun(dailyAnalysisId)
);
