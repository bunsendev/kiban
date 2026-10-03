const experimentPlanForm = document.getElementById('experiment-plan-form');
const experimentCandidate = document.getElementById('experiment-candidate');
const experimentState = document.getElementById('experiment-state');
const experimentResult = document.getElementById('experiment-result');
const experimentHistory = document.getElementById('experiment-history');

const experimentTargetLabels = {
  DEMAND_FORECAST: '需要予測',
  SHIPMENT_RECOMMENDATION: '推奨出荷量',
};

function experimentMessage(message, className = '') {
  experimentState.textContent = message;
  experimentState.className = className;
}

function experimentMetric(label, value, suffix = '') {
  const card = document.createElement('div');
  const title = document.createElement('span');
  const number = document.createElement('strong');
  title.textContent = label;
  number.textContent = value === null || value === undefined ? '—' : `${value}${suffix}`;
  card.append(title, number);
  return card;
}

function fileAsBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.addEventListener('load', () => resolve(String(reader.result).split(',', 2)[1]));
    reader.addEventListener('error', () => reject(new Error('比較CSVを読み込めませんでした。')));
    reader.readAsDataURL(file);
  });
}

async function decideExperimentRun(plan, run, form) {
  const button = form.querySelector('button');
  button.disabled = true;
  try {
    const response = await fetch(
      `/api/learning-experiments/runs/${encodeURIComponent(run.run_id)}/decision`,
      {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({
        expected_revision: run.revision,
        decision: form.elements.decision.value,
        subject: form.elements.subject.value,
        reason: form.elements.reason.value,
        confirm_no_automatic_application: true,
      })},
    );
    const value = await response.json();
    if (!response.ok) throw new Error(value.detail || '比較結果の判断を保存できませんでした。');
    renderExperimentPlan(value);
    if (window.PortableFormalChanges) window.PortableFormalChanges.refresh();
    experimentMessage('比較結果の判断を追記保存しました。正式設定は変更していません。', 'success');
  } catch (error) {
    experimentMessage(error.message, 'error');
  } finally {
    button.disabled = false;
  }
}

function renderExperimentRun(plan, run) {
  const article = document.createElement('article');
  article.className = 'learning-experiment-run';
  const title = document.createElement('h4');
  title.textContent = `${run.result_version}／${run.status}`;
  const coverage = run.report.coverage;
  const metrics = document.createElement('div');
  metrics.className = 'learning-kpis';
  metrics.append(
    experimentMetric('共通比較', coverage.comparable_count, `/${coverage.planned_count}件`),
    experimentMetric('Baseline MAE', run.report.baseline.mae_cases, '箱'),
    experimentMetric('Challenger MAE', run.report.challenger.mae_cases, '箱'),
    experimentMetric('MAE差', run.report.delta_challenger_minus_baseline.mae_cases, '箱'),
    experimentMetric('改善case', run.report.comparison.challenger_better_count, '件'),
    experimentMetric('悪化case', run.report.comparison.challenger_worse_count, '件'),
    experimentMetric('不足代理差', run.report.quantity_gap_proxies.delta_challenger_minus_baseline.under_supply_cases, '箱'),
    experimentMetric('過剰代理差', run.report.quantity_gap_proxies.delta_challenger_minus_baseline.excess_supply_cases, '箱'),
    experimentMetric('欠品実績', run.report.observed_business_outcomes.stockout_cases, '箱'),
    experimentMetric('期限切れ実績', run.report.observed_business_outcomes.expired_cases, '箱'),
  );
  const note = document.createElement('p');
  note.textContent = run.report.observed_business_outcomes.notice;
  const form = document.createElement('form');
  form.className = 'experiment-decision-form';
  form.innerHTML = '<label>判断<select name="decision"><option value="RECOMMEND_FORMAL_CHANGE">正式変更案の作成を推奨</option><option value="REJECT_CHANGE">変更を見送る</option></select></label><label>確認者<input name="subject" maxlength="100" required></label><label>判断理由<input name="reason" maxlength="500" required></label><button type="submit">判断を保存</button>';
  form.addEventListener('submit', event => {
    event.preventDefault();
    decideExperimentRun(plan, run, form);
  });
  article.append(title, metrics, note, form);
  return article;
}

function renderExperimentPlan(plan) {
  experimentResult.replaceChildren();
  const title = document.createElement('h3');
  title.textContent = `${experimentTargetLabels[plan.target]}：${plan.baseline_version} と ${plan.challenger_version}`;
  const detail = document.createElement('p');
  detail.textContent = `固定対象 ${plan.case_count}件／仮説：${plan.hypothesis}`;
  const template = document.createElement('a');
  template.href = `/api/learning-experiments/plans/${encodeURIComponent(plan.plan_id)}/template`;
  template.textContent = 'Challenger結果CSVテンプレートを保存';
  const form = document.createElement('form');
  form.className = 'experiment-run-form';
  form.innerHTML = '<label>結果版<input name="result_version" maxlength="100" required></label><label>実行者<input name="subject" maxlength="100" required></label><label>比較基準日時<input name="known_at" type="datetime-local" required></label><label>Challenger結果CSV<input name="file" type="file" accept=".csv,text/csv" required></label><label class="confirm-case"><input name="confirm" type="checkbox" required>固定された同一case集合で比較します</label><button type="submit">比較runを保存</button>';
  const now = new Date();
  form.elements.known_at.value = new Date(now.getTime() - now.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
  form.addEventListener('submit', async event => {
    event.preventDefault();
    const button = form.querySelector('button');
    button.disabled = true;
    experimentMessage('BaselineとChallengerを同じ実績で比較しています。');
    try {
      const csvBase64 = await fileAsBase64(form.elements.file.files[0]);
      const response = await fetch(
        `/api/learning-experiments/plans/${encodeURIComponent(plan.plan_id)}/runs`,
        {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({
          result_version: form.elements.result_version.value,
          subject: form.elements.subject.value,
          known_at: new Date(form.elements.known_at.value).toISOString(),
          csv_base64: csvBase64,
          confirm_same_case_set: form.elements.confirm.checked,
        })},
      );
      const value = await response.json();
      if (!response.ok) throw new Error(value.detail || '比較runを保存できませんでした。');
      renderExperimentPlan(value);
      experimentMessage('比較runを不変な結果として保存しました。', 'success');
    } catch (error) {
      experimentMessage(error.message, 'error');
    } finally {
      button.disabled = false;
    }
  });
  experimentResult.append(title, detail, template, form);
  const runTitle = document.createElement('h3');
  runTitle.textContent = `比較run ${plan.runs.length}件`;
  experimentResult.appendChild(runTitle);
  if (!plan.runs.length) {
    const empty = document.createElement('p');
    empty.textContent = 'テンプレートへChallenger数量を入力し、比較runを作成してください。';
    experimentResult.appendChild(empty);
  }
  for (const run of plan.runs) experimentResult.appendChild(renderExperimentRun(plan, run));
}

async function loadExperimentPlan(planId) {
  const response = await fetch(`/api/learning-experiments/plans/${encodeURIComponent(planId)}`);
  const value = await response.json();
  if (!response.ok) throw new Error(value.detail || '比較計画を読み込めませんでした。');
  renderExperimentPlan(value);
}

async function refreshLearningExperiments() {
  try {
    const response = await fetch('/api/learning-experiments');
    const value = await response.json();
    if (!response.ok) throw new Error(value.detail || '比較計画一覧を読み込めませんでした。');
    const selected = experimentCandidate.value;
    experimentCandidate.replaceChildren();
    const placeholder = document.createElement('option');
    placeholder.value = '';
    placeholder.textContent = value.approved_candidates.length ? '選択してください' : '承認済み候補はありません';
    experimentCandidate.appendChild(placeholder);
    for (const candidate of value.approved_candidates) {
      const option = document.createElement('option');
      option.value = candidate.candidate_id;
      option.textContent = `${candidate.week_start}〜${candidate.week_end}／${candidate.candidate_type}／${candidate.evidence_count}件`;
      option.selected = option.value === selected;
      experimentCandidate.appendChild(option);
    }
    experimentHistory.replaceChildren();
    for (const plan of value.plans) {
      const item = document.createElement('li');
      const button = document.createElement('button');
      button.type = 'button';
      button.textContent = `${experimentTargetLabels[plan.target]}／${plan.challenger_version}／${plan.case_count}件`;
      button.addEventListener('click', () => loadExperimentPlan(plan.plan_id).catch(error => experimentMessage(error.message, 'error')));
      item.appendChild(button);
      experimentHistory.appendChild(item);
    }
  } catch (error) {
    experimentMessage(error.message, 'error');
  }
}

experimentPlanForm.addEventListener('submit', async event => {
  event.preventDefault();
  const button = experimentPlanForm.querySelector('button');
  button.disabled = true;
  try {
    const response = await fetch('/api/learning-experiments/plans', {
      method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({
        candidate_id: experimentCandidate.value,
        target: document.getElementById('experiment-target').value,
        baseline_version: document.getElementById('experiment-baseline-version').value,
        challenger_version: document.getElementById('experiment-challenger-version').value,
        hypothesis: document.getElementById('experiment-hypothesis').value,
        subject: document.getElementById('experiment-plan-subject').value,
        known_at: new Date(document.getElementById('experiment-plan-known-at').value).toISOString(),
        confirm_shadow_experiment: document.getElementById('experiment-plan-confirm').checked,
      })},
    );
    const value = await response.json();
    if (!response.ok) throw new Error(value.detail || '比較計画を作成できませんでした。');
    renderExperimentPlan(value);
    await refreshLearningExperiments();
    experimentMessage('承認候補の比較計画を固定しました。', 'success');
  } catch (error) {
    experimentMessage(error.message, 'error');
  } finally {
    button.disabled = false;
  }
});

const experimentNow = new Date();
document.getElementById('experiment-plan-known-at').value = new Date(experimentNow.getTime() - experimentNow.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
window.PortableLearningExperiments = {refresh: refreshLearningExperiments};
refreshLearningExperiments();
