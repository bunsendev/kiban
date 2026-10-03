const learningForm = document.getElementById('learning-review-form');
const learningState = document.getElementById('learning-review-state');
const learningResult = document.getElementById('learning-review-result');
const learningHistory = document.getElementById('learning-review-history');
const learningScopes = document.getElementById('learning-scopes');

const candidateLabels = {
  CALENDAR_FEATURE: '販促・季節情報の追加',
  LARGE_ORDER_INPUT: '大口予定入力の追加',
  PRODUCTION_PLAN_INTEGRATION: '生産予定連携の改善',
  ROUTE_POLICY: '配送・倉庫移動条件の改善',
  EXPIRY_POLICY: '賞味期限・FEFO条件の改善',
  DATA_QUALITY: '実績・データ品質の改善',
  STOCKOUT_POLICY: '欠品防止条件の改善',
};

function learningMessage(message, className = '') {
  learningState.textContent = message;
  learningState.className = className;
}

function valueOrDash(value) {
  return value === null || value === undefined ? '—' : value;
}

function metricCard(label, value, suffix = '') {
  const card = document.createElement('div');
  const title = document.createElement('span');
  const number = document.createElement('strong');
  title.textContent = label;
  number.textContent = `${valueOrDash(value)}${value === null || value === undefined ? '' : suffix}`;
  card.append(title, number);
  return card;
}

async function decideCandidate(review, candidate, form) {
  const button = form.querySelector('button');
  button.disabled = true;
  try {
    const response = await fetch(
      `/api/learning-candidates/${encodeURIComponent(candidate.candidate_id)}/decision`,
      {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({
        expected_revision: candidate.revision,
        decision: form.elements.decision.value,
        subject: document.getElementById('learning-reviewer').value,
        reason: form.elements.reason.value,
        confirm_no_automatic_application: true,
      })},
    );
    const updated = await response.json();
    if (!response.ok) throw new Error(updated.detail || '改善候補の判断を保存できませんでした。');
    renderLearningReview(updated);
    learningMessage('改善候補の判断を追記保存しました。設定は変更していません。', 'success');
  } catch (error) {
    learningMessage(error.message, 'error');
  } finally {
    button.disabled = false;
  }
}

function candidateCard(review, candidate) {
  const article = document.createElement('article');
  article.className = 'learning-candidate';
  const heading = document.createElement('h3');
  heading.textContent = candidateLabels[candidate.candidate_type] || candidate.candidate_type;
  const detail = document.createElement('p');
  detail.textContent = `状態 ${candidate.status}／根拠 ${candidate.evidence_count}件／影響数量 ${valueOrDash(candidate.impact_quantity_cases)}箱／観測 ${candidate.reason_codes.join('・')}`;
  const form = document.createElement('form');
  const decisionLabel = document.createElement('label');
  decisionLabel.textContent = '判断';
  const decision = document.createElement('select');
  decision.name = 'decision';
  for (const [value, label] of [['APPROVED', '次工程の調査対象として承認'], ['REJECTED', '今回は却下']]) {
    const option = document.createElement('option');
    option.value = value;
    option.textContent = label;
    decision.appendChild(option);
  }
  decisionLabel.appendChild(decision);
  const reasonLabel = document.createElement('label');
  reasonLabel.textContent = '判断理由';
  const reason = document.createElement('input');
  reason.name = 'reason';
  reason.maxLength = 500;
  reason.required = true;
  reasonLabel.appendChild(reason);
  const submit = document.createElement('button');
  submit.type = 'submit';
  submit.textContent = '判断を保存';
  form.append(decisionLabel, reasonLabel, submit);
  form.addEventListener('submit', event => {
    event.preventDefault();
    decideCandidate(review, candidate, form);
  });
  article.append(heading, detail, form);
  return article;
}

function renderLearningReview(review) {
  learningResult.replaceChildren();
  document.getElementById('learning-reviewer').value = review.reviewer;
  const current = review.report.current;
  const heading = document.createElement('h3');
  heading.textContent = `${review.week_start}〜${review.week_end}／${review.aggregation_version}`;
  const notice = document.createElement('p');
  notice.textContent = review.report.notice;
  const metrics = document.createElement('div');
  metrics.className = 'learning-kpis';
  metrics.append(
    metricCard('比較対象', current.reference_case_count, '件'),
    metricCard('実績あり', current.comparison_coverage.actual_any, '件'),
    metricCard('実績未取得', current.comparison_coverage.actual_missing, '件'),
    metricCard('需要予測MAE', current.forecast_kpis.mae_cases, '箱'),
    metricCard('需要予測WAPE', current.forecast_kpis.wape),
    metricCard('担当者修正', current.operator_kpis.change_count, '件'),
    metricCard('欠品', current.operational_kpis.stockout_cases, '箱'),
    metricCard('期限切れ', current.operational_kpis.expired_cases, '箱'),
    metricCard('倉庫間移動', current.operational_kpis.interwarehouse_transfer_cases, '箱'),
  );
  learningResult.append(heading, notice, metrics);
  const candidateHeading = document.createElement('h3');
  candidateHeading.textContent = `改善候補 ${review.candidates.length}件`;
  learningResult.appendChild(candidateHeading);
  if (!review.candidates.length) {
    const empty = document.createElement('p');
    empty.textContent = '設定した根拠件数を満たす候補はありません。';
    learningResult.appendChild(empty);
  } else {
    for (const candidate of review.candidates) {
      learningResult.appendChild(candidateCard(review, candidate));
    }
  }
}

async function loadReview(reviewId) {
  const response = await fetch(`/api/learning-reviews/${encodeURIComponent(reviewId)}`);
  const value = await response.json();
  if (!response.ok) throw new Error(value.detail || '週次集計版を読み込めませんでした。');
  renderLearningReview(value);
}

async function refreshLearningReviews() {
  try {
    const response = await fetch('/api/learning-reviews');
    const value = await response.json();
    if (!response.ok) throw new Error(value.detail || '週次集計一覧を読み込めませんでした。');
    const selected = new Set(
      [...learningScopes.querySelectorAll('input:checked')].map(item => item.value),
    );
    learningScopes.replaceChildren();
    if (!value.available_pilot_scope_versions.length) {
      const text = document.createElement('span');
      text.textContent = '後日実績を保存すると選択できます。';
      learningScopes.appendChild(text);
    }
    for (const scope of value.available_pilot_scope_versions) {
      const label = document.createElement('label');
      const input = document.createElement('input');
      input.type = 'checkbox';
      input.value = scope;
      input.checked = selected.size ? selected.has(scope) : true;
      label.append(input, document.createTextNode(scope));
      learningScopes.appendChild(label);
    }
    learningHistory.replaceChildren();
    for (const review of value.reviews) {
      const item = document.createElement('li');
      const button = document.createElement('button');
      button.type = 'button';
      button.textContent = `${review.week_start}〜${review.week_end}／実績 ${review.actual_count}/${review.reference_case_count}件`;
      button.addEventListener('click', () => loadReview(review.review_id).catch(error => learningMessage(error.message, 'error')));
      item.appendChild(button);
      learningHistory.appendChild(item);
    }
  } catch (error) {
    learningMessage(error.message, 'error');
  }
}

learningForm.addEventListener('submit', async event => {
  event.preventDefault();
  const button = learningForm.querySelector('button[type="submit"]');
  const scopes = [...learningScopes.querySelectorAll('input:checked')].map(item => item.value);
  button.disabled = true;
  learningMessage('週次の比較可能件数と業務KPIを固定集計しています。');
  try {
    const response = await fetch('/api/learning-reviews', {
      method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({
        week_end: document.getElementById('learning-week-end').value,
        pilot_scope_versions: scopes,
        aggregation_version: document.getElementById('learning-aggregation-version').value,
        threshold_version: document.getElementById('learning-threshold-version').value,
        minimum_evidence_count: Number(document.getElementById('learning-minimum-evidence').value),
        reviewer: document.getElementById('learning-reviewer').value,
        known_at: new Date(document.getElementById('learning-known-at').value).toISOString(),
        confirm_shadow_review: document.getElementById('learning-confirm').checked,
      })},
    );
    const value = await response.json();
    if (!response.ok) throw new Error(value.detail || '週次集計版を作成できませんでした。');
    renderLearningReview(value);
    await refreshLearningReviews();
    learningMessage('週次集計版を固定保存しました。', 'success');
  } catch (error) {
    learningMessage(error.message, 'error');
  } finally {
    button.disabled = false;
  }
});

const today = new Date();
const localNow = new Date(today.getTime() - today.getTimezoneOffset() * 60000);
document.getElementById('learning-week-end').value = localNow.toISOString().slice(0, 10);
document.getElementById('learning-known-at').value = localNow.toISOString().slice(0, 16);
window.PortableLearningReviews = {refresh: refreshLearningReviews};
refreshLearningReviews();
