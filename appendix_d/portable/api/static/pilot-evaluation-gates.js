const pilotEvaluationForm = document.getElementById('pilot-evaluation-form');
const pilotEvaluationApplication = document.getElementById('pilot-evaluation-application');
const pilotEvaluationRuntime = document.getElementById('pilot-evaluation-runtime');
const pilotEvaluationState = document.getElementById('pilot-evaluation-state');
const pilotEvaluationResult = document.getElementById('pilot-evaluation-result');
const pilotEvaluationHistory = document.getElementById('pilot-evaluation-history');

const pilotDecisionLabels = {
  CONTINUE_PILOT: '観測を継続', PAUSE_PILOT: 'Pilotを停止',
  REQUEST_ROLLBACK: 'Baselineへ戻す作業を依頼',
  FORWARD_TO_ACCEPTANCE: '正式採用の受入審査へ送る',
};

function pilotEvaluationMessage(message, kind = '') {
  pilotEvaluationState.textContent = message;
  pilotEvaluationState.className = kind;
}

function pilotEvaluationOption(value, text) {
  const option = document.createElement('option');
  option.value = value;
  option.textContent = text;
  return option;
}

function renderPilotEvaluation(value) {
  pilotEvaluationResult.replaceChildren();
  const title = document.createElement('h4');
  title.textContent = value.report.status === 'PASSED' ? '基準を満たしました' : '確認または追加観測が必要です';
  const recommendation = document.createElement('p');
  recommendation.className = value.report.status === 'PASSED' ? 'success' : 'notice';
  recommendation.textContent = `機械判定の推奨：${pilotDecisionLabels[value.report.recommended_action]}`;
  const checks = document.createElement('ul');
  for (const check of value.report.checks) {
    const row = document.createElement('li');
    row.className = check.passed ? 'success' : 'error';
    row.textContent = `${check.passed ? '合格' : '未達'} ${check.code}／実績 ${JSON.stringify(check.actual)}／基準 ${JSON.stringify(check.expected)}`;
    checks.appendChild(row);
  }
  pilotEvaluationResult.append(title, recommendation, checks);
  if (value.decisions.length) {
    const history = document.createElement('ol');
    for (const decision of value.decisions) {
      const row = document.createElement('li');
      row.textContent = `rev.${decision.revision} ${pilotDecisionLabels[decision.decision]}／${decision.actor}：${decision.reason}`;
      history.appendChild(row);
    }
    pilotEvaluationResult.appendChild(history);
  }
  pilotEvaluationResult.appendChild(pilotDecisionForm(value));
}

function pilotDecisionForm(value) {
  const form = document.createElement('form');
  form.className = 'pilot-evaluation-decision';
  form.innerHTML = '<label>担当者判断<select name="decision" required></select></label><label>判断者<input name="actor" maxlength="100" required></label><label>判断理由<textarea name="reason" maxlength="500" rows="3" required></textarea></label><label class="confirm-case"><input name="confirm" type="checkbox" required>この記録だけで設定変更・受入・Rollbackを実行しないことを確認しました</label><button type="submit">担当者判断を追記</button>';
  const select = form.elements.decision;
  for (const [decision, label] of Object.entries(pilotDecisionLabels)) {
    const option = pilotEvaluationOption(decision, label);
    if (decision === 'FORWARD_TO_ACCEPTANCE' && value.report.status !== 'PASSED') option.disabled = true;
    if (decision === value.report.recommended_action) option.selected = true;
    select.appendChild(option);
  }
  form.addEventListener('submit', async event => {
    event.preventDefault();
    const button = form.querySelector('button');
    button.disabled = true;
    try {
      const response = await fetch(`/api/pilot-evaluation-gates/${encodeURIComponent(value.assessment_id)}/decisions`, {
        method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({
          expected_revision: value.revision, decision: select.value,
          actor: form.elements.actor.value, reason: form.elements.reason.value,
          confirm_no_automatic_action: form.elements.confirm.checked,
        }),
      });
      const updated = await response.json();
      if (!response.ok) throw new Error(updated.detail || '担当者判断を保存できませんでした。');
      renderPilotEvaluation(updated);
      await refreshPilotEvaluations();
      pilotEvaluationMessage('担当者判断を追記しました。次の操作は既存の受入・Rollback画面で行います。', 'success');
    } catch (error) { pilotEvaluationMessage(error.message, 'error'); }
    finally { button.disabled = false; }
  });
  return form;
}

async function loadPilotEvaluation(id) {
  const response = await fetch(`/api/pilot-evaluation-gates/${encodeURIComponent(id)}`);
  const value = await response.json();
  if (!response.ok) throw new Error(value.detail || 'Pilot評価Gateを読み込めませんでした。');
  renderPilotEvaluation(value);
}

async function refreshPilotEvaluations() {
  try {
    const response = await fetch('/api/pilot-evaluation-gates');
    const value = await response.json();
    if (!response.ok) throw new Error(value.detail || 'Pilot評価Gate候補を読み込めませんでした。');
    const applicationValue = pilotEvaluationApplication.value;
    const runtimeValue = pilotEvaluationRuntime.value;
    pilotEvaluationApplication.replaceChildren(pilotEvaluationOption('', value.applications.length ? '選択してください' : 'Pilot運用中の計画はありません'));
    for (const item of value.applications) {
      const option = pilotEvaluationOption(item.application_id, `${item.candidate_version}／${item.executor}`);
      option.selected = item.application_id === applicationValue;
      pilotEvaluationApplication.appendChild(option);
    }
    pilotEvaluationRuntime.replaceChildren(pilotEvaluationOption('', value.runtime_evaluations.length ? '選択してください' : 'Runtime週次評価はありません'));
    for (const item of value.runtime_evaluations) {
      const option = pilotEvaluationOption(item.evaluation_id, `${item.week_start}～${item.week_end}／${item.evaluation_version}`);
      option.selected = item.evaluation_id === runtimeValue;
      pilotEvaluationRuntime.appendChild(option);
    }
    pilotEvaluationHistory.replaceChildren();
    for (const item of value.assessments) {
      const row = document.createElement('li');
      const button = document.createElement('button');
      button.type = 'button';
      button.textContent = `${item.status}／${item.policy_version}／${item.reviewer}`;
      button.addEventListener('click', () => loadPilotEvaluation(item.assessment_id).catch(error => pilotEvaluationMessage(error.message, 'error')));
      row.appendChild(button);
      pilotEvaluationHistory.appendChild(row);
    }
  } catch (error) { pilotEvaluationMessage(error.message, 'error'); }
}

pilotEvaluationForm.addEventListener('submit', async event => {
  event.preventDefault();
  const button = pilotEvaluationForm.querySelector('button');
  button.disabled = true;
  const field = id => document.getElementById(id).value;
  try {
    const response = await fetch('/api/pilot-evaluation-gates', {
      method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({
        application_id: pilotEvaluationApplication.value,
        runtime_evaluation_id: pilotEvaluationRuntime.value,
        policy_version: field('pilot-evaluation-policy'),
        minimum_observation_days: Number(field('pilot-evaluation-days')),
        minimum_same_actual_count: Number(field('pilot-evaluation-count')),
        maximum_unattributed_ratio: field('pilot-evaluation-unattributed'),
        maximum_mae_delta_cases: field('pilot-evaluation-mae'),
        maximum_wape_delta: field('pilot-evaluation-wape'),
        maximum_operator_change_ratio: field('pilot-evaluation-change'),
        maximum_stockout_cases: field('pilot-evaluation-stockout'),
        maximum_expired_cases: field('pilot-evaluation-expired'),
        maximum_interwarehouse_transfer_cases: field('pilot-evaluation-transfer'),
        reviewer: field('pilot-evaluation-reviewer'),
        confirm_advisory_only: document.getElementById('pilot-evaluation-confirm').checked,
      }),
    });
    const value = await response.json();
    if (!response.ok) throw new Error(value.detail || 'Pilot評価Gateを作成できませんでした。');
    renderPilotEvaluation(value);
    await refreshPilotEvaluations();
    pilotEvaluationMessage('Pilot評価Gateを改変検知可能な証跡として固定しました。', 'success');
  } catch (error) { pilotEvaluationMessage(error.message, 'error'); }
  finally { button.disabled = false; }
});

window.PortablePilotEvaluationGates = {refresh: refreshPilotEvaluations};
refreshPilotEvaluations();
