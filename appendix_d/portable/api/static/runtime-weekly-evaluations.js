const runtimeEvaluationForm = document.getElementById('runtime-evaluation-form');
const runtimeEvaluationReview = document.getElementById('runtime-evaluation-review');
const runtimeEvaluationState = document.getElementById('runtime-evaluation-state');
const runtimeEvaluationResult = document.getElementById('runtime-evaluation-result');
const runtimeEvaluationHistory = document.getElementById('runtime-evaluation-history');

function runtimeEvaluationMessage(message, className = '') {
  runtimeEvaluationState.textContent = message;
  runtimeEvaluationState.className = className;
}

function runtimeMetric(label, value, suffix = '') {
  const card = document.createElement('div');
  const title = document.createElement('span');
  const number = document.createElement('strong');
  title.textContent = label;
  number.textContent = value === null || value === undefined ? '—' : `${value}${suffix}`;
  card.append(title, number);
  return card;
}

function renderRuntimeEvaluation(value) {
  runtimeEvaluationResult.replaceChildren();
  const report = value.report;
  const heading = document.createElement('h4');
  heading.textContent = `${report.week_start}〜${report.week_end}／${value.evaluation_version}`;
  const notice = document.createElement('p');
  notice.textContent = report.notice;
  runtimeEvaluationResult.append(heading, notice);
  for (const group of report.runtime_groups) {
    const article = document.createElement('article');
    article.className = 'runtime-evaluation-card';
    const title = document.createElement('h4');
    title.textContent = `${group.runtime_version}／${group.model_name}`;
    const detail = document.createElement('p');
    detail.textContent = `${group.assignment_status}／設定 ${group.runtime_configuration_sha256.slice(0, 12)}…／Scope ${group.pilot_scope_versions.join('・')}`;
    const metrics = document.createElement('div');
    metrics.className = 'learning-kpis';
    metrics.append(
      runtimeMetric('対象', group.reference_case_count, '件'),
      runtimeMetric('実績あり', group.actual_count, '件'),
      runtimeMetric('需要予測MAE', group.forecast_kpis.mae_cases, '箱'),
      runtimeMetric('需要予測WAPE', group.forecast_kpis.wape),
      runtimeMetric('担当者修正', group.operator_kpis.change_count, '件'),
      runtimeMetric('欠品', group.operational_kpis.stockout_cases, '箱'),
      runtimeMetric('期限切れ', group.operational_kpis.expired_cases, '箱'),
      runtimeMetric('倉庫間移動', group.operational_kpis.interwarehouse_transfer_cases, '箱'),
    );
    article.append(title, detail, metrics);
    runtimeEvaluationResult.appendChild(article);
  }
  const comparisonHeading = document.createElement('h4');
  comparisonHeading.textContent = '同じActualによるBaseline・候補版比較';
  runtimeEvaluationResult.appendChild(comparisonHeading);
  if (!report.pairwise_comparisons.length) {
    const empty = document.createElement('p');
    empty.textContent = '同じ週次版にBaselineと候補版の両方がまだありません。各版の観測値は上で確認できます。';
    runtimeEvaluationResult.appendChild(empty);
  }
  for (const comparison of report.pairwise_comparisons) {
    const article = document.createElement('article');
    article.className = 'runtime-evaluation-card';
    const title = document.createElement('h4');
    title.textContent = `${comparison.baseline_version} → ${comparison.candidate_version}`;
    const detail = document.createElement('p');
    detail.textContent = `状態 ${comparison.status}／共通case ${comparison.common_case_count}件／同一Actual ${comparison.same_actual_count}件／Actual不一致 ${comparison.actual_mismatch_count}件／重複 ${comparison.duplicate_case_count}件`;
    const metrics = document.createElement('div');
    metrics.className = 'learning-kpis';
    metrics.append(
      runtimeMetric('Baseline MAE', comparison.baseline_forecast_kpis.mae_cases, '箱'),
      runtimeMetric('候補版 MAE', comparison.candidate_forecast_kpis.mae_cases, '箱'),
      runtimeMetric('MAE差', comparison.candidate_minus_baseline.mae_cases, '箱'),
      runtimeMetric('WAPE差', comparison.candidate_minus_baseline.wape),
    );
    article.append(title, detail, metrics);
    runtimeEvaluationResult.appendChild(article);
  }
  if (report.blockers.length) {
    const blockers = document.createElement('p');
    blockers.className = 'error';
    blockers.textContent = `版を特定できない証跡: ${report.blockers.map(item => `${item.code} ${item.count}件`).join('／')}`;
    runtimeEvaluationResult.appendChild(blockers);
  }
}

async function loadRuntimeEvaluation(evaluationId) {
  const response = await fetch(`/api/runtime-weekly-evaluations/${encodeURIComponent(evaluationId)}`);
  const value = await response.json();
  if (!response.ok) throw new Error(value.detail || 'Runtime週次評価を読み込めませんでした。');
  renderRuntimeEvaluation(value);
}

async function refreshRuntimeEvaluations() {
  try {
    const response = await fetch('/api/runtime-weekly-evaluations');
    const value = await response.json();
    if (!response.ok) throw new Error(value.detail || 'Runtime週次評価一覧を読み込めませんでした。');
    const selected = runtimeEvaluationReview.value;
    runtimeEvaluationReview.replaceChildren();
    const placeholder = document.createElement('option');
    placeholder.value = '';
    placeholder.textContent = value.weekly_reviews.length ? '週次集計版を選択' : '先に週次集計版を作成してください';
    runtimeEvaluationReview.appendChild(placeholder);
    for (const review of value.weekly_reviews) {
      const option = document.createElement('option');
      option.value = review.review_id;
      option.textContent = `${review.week_start}〜${review.week_end}／実績 ${review.actual_count}/${review.reference_case_count}件`;
      option.selected = option.value === selected;
      runtimeEvaluationReview.appendChild(option);
    }
    runtimeEvaluationHistory.replaceChildren();
    for (const item of value.evaluations) {
      const row = document.createElement('li');
      const button = document.createElement('button');
      button.type = 'button';
      button.textContent = `${item.week_start}〜${item.week_end}／Runtime ${item.runtime_group_count}版／未特定 ${item.unattributed_case_count}件`;
      button.addEventListener('click', () => loadRuntimeEvaluation(item.evaluation_id).catch(error => runtimeEvaluationMessage(error.message, 'error')));
      row.appendChild(button);
      runtimeEvaluationHistory.appendChild(row);
    }
  } catch (error) {
    runtimeEvaluationMessage(error.message, 'error');
  }
}

runtimeEvaluationForm.addEventListener('submit', async event => {
  event.preventDefault();
  const button = runtimeEvaluationForm.querySelector('button[type="submit"]');
  button.disabled = true;
  runtimeEvaluationMessage('Runtime版、実行証跡、同じActualを照合しています。');
  try {
    const response = await fetch('/api/runtime-weekly-evaluations', {
      method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({
        weekly_review_id: runtimeEvaluationReview.value,
        evaluation_version: document.getElementById('runtime-evaluation-version').value,
        reviewer: document.getElementById('runtime-evaluation-reviewer').value,
        confirm_same_actual_shadow: document.getElementById('runtime-evaluation-confirm').checked,
      }),
    });
    const value = await response.json();
    if (!response.ok) throw new Error(value.detail || 'Runtime週次評価を作成できませんでした。');
    renderRuntimeEvaluation(value);
    await refreshRuntimeEvaluations();
    runtimeEvaluationMessage('Runtime版別の週次評価を固定保存しました。', 'success');
  } catch (error) {
    runtimeEvaluationMessage(error.message, 'error');
  } finally {
    button.disabled = false;
  }
});

window.PortableRuntimeWeeklyEvaluations = {refresh: refreshRuntimeEvaluations};
refreshRuntimeEvaluations();
