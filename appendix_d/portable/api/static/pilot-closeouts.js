const pilotCloseoutRoot = document.getElementById('pilot-closeout-result');

function pilotCloseoutText(tag, text, className = '') {
  const value = document.createElement(tag);
  value.textContent = text;
  value.className = className;
  return value;
}

function pilotCloseoutBaseForm(label) {
  const form = document.createElement('form');
  form.className = 'pilot-closeout-form';
  form.innerHTML = '<label>実行担当者<input name="actor" maxlength="100" required></label><label>記録理由<textarea name="reason" maxlength="500" rows="3" required></textarea><label class="confirm-case"><input name="confirm" type="checkbox" required>評価証跡を参照し、担当者確認を省略しない監査記録として追記します</label><button type="submit"></button>';
  form.querySelector('button').textContent = label;
  return form;
}

function pilotCloseoutResultRow(statement, kind, label) {
  const row = document.createElement('fieldset');
  row.dataset.statement = statement;
  row.dataset.kind = kind;
  row.appendChild(pilotCloseoutText('legend', statement));
  const resultLabel = document.createElement('label');
  const result = document.createElement('input');
  result.type = 'checkbox';
  result.name = kind;
  resultLabel.append(result, ` ${label}`);
  const evidenceLabel = document.createElement('label');
  evidenceLabel.textContent = '確認根拠';
  const evidence = document.createElement('input');
  evidence.name = 'evidence';
  evidence.maxLength = 500;
  evidence.required = true;
  evidenceLabel.appendChild(evidence);
  row.append(resultLabel, evidenceLabel);
  return row;
}

function pilotCloseoutCollect(form, kind) {
  return [...form.querySelectorAll(`[data-kind="${kind}"]`)].map(row => ({
    statement: row.dataset.statement,
    [kind]: row.querySelector(`[name="${kind}"]`).checked,
    evidence: row.querySelector('[name="evidence"]').value,
  }));
}

async function pilotCloseoutPost(view, endpoint, payload, success) {
  const response = await fetch(`/api/pilot-closeouts/${encodeURIComponent(view.assessment_id)}/${endpoint}`, {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({
      expected_assessment_revision: view.assessment_revision,
      expected_revision: view.application.revision,
      actor: payload.actor, reason: payload.reason,
      confirm_audited_transition: payload.confirm,
      ...payload.extra,
    }),
  });
  const value = await response.json();
  if (!response.ok) throw new Error(value.detail || 'Pilot完了結果を保存できませんでした。');
  pilotCloseoutRoot.replaceChildren(pilotCloseoutText('p', success, 'success'));
  await window.PortableChangeApplications?.refresh();
  await window.PortablePilotEvaluationGates?.refresh();
  await renderPilotCloseout({assessment_id: view.assessment_id});
}

function pilotCloseoutAcceptance(view) {
  const form = pilotCloseoutBaseForm('評価証跡と受入結果を保存');
  const results = document.createElement('div');
  results.appendChild(pilotCloseoutText('h5', '受入基準'));
  for (const statement of view.application.proposal.acceptance_criteria) {
    results.appendChild(pilotCloseoutResultRow(statement, 'passed', '合格'));
  }
  results.appendChild(pilotCloseoutText('h5', 'Rollback条件'));
  for (const statement of view.application.proposal.rollback_conditions) {
    results.appendChild(pilotCloseoutResultRow(statement, 'triggered', '条件に該当'));
  }
  form.insertBefore(results, form.firstChild);
  form.addEventListener('submit', async event => {
    event.preventDefault();
    const button = form.querySelector('button');
    button.disabled = true;
    try {
      await pilotCloseoutPost(view, 'acceptance', {
        actor: form.elements.actor.value, reason: form.elements.reason.value,
        confirm: form.elements.confirm.checked,
        extra: {
          acceptance_results: pilotCloseoutCollect(form, 'passed'),
          rollback_results: pilotCloseoutCollect(form, 'triggered'),
        },
      }, '評価証跡を参照した受入結果を保存しました。');
    } catch (error) { pilotCloseoutRoot.prepend(pilotCloseoutText('p', error.message, 'error')); }
    finally { button.disabled = false; }
  });
  return form;
}

function pilotCloseoutRollback(view) {
  const form = pilotCloseoutBaseForm('評価証跡とRollback結果を保存');
  const details = document.createElement('div');
  details.appendChild(pilotCloseoutText('p', `戻す版：${view.application.proposal.rollback_target_version}`));
  const restoredLabel = document.createElement('label');
  const restored = document.createElement('input');
  restored.type = 'checkbox'; restored.name = 'restored'; restored.required = true;
  restoredLabel.append(restored, ' 事前backupから復元しました');
  details.appendChild(restoredLabel);
  for (const name of [
    '旧設定への復帰',
    'アプリとAPIの再起動',
    '既存データの参照',
  ]) details.appendChild(pilotCloseoutResultRow(name, 'passed', '合格'));
  form.insertBefore(details, form.firstChild);
  form.addEventListener('submit', async event => {
    event.preventDefault();
    const button = form.querySelector('button');
    button.disabled = true;
    try {
      const rollbackChecks = [...form.querySelectorAll('[data-kind="passed"]')].map(row => ({
        name: row.dataset.statement,
        passed: row.querySelector('[name="passed"]').checked,
        evidence: row.querySelector('[name="evidence"]').value,
      }));
      await pilotCloseoutPost(view, 'rollback', {
        actor: form.elements.actor.value, reason: form.elements.reason.value,
        confirm: form.elements.confirm.checked,
        extra: {
          rollback_target_version: view.application.proposal.rollback_target_version,
          backup_restored: form.elements.restored.checked,
          rollback_checks: rollbackChecks,
        },
      }, '評価証跡を参照したRollback結果を保存しました。');
    } catch (error) { pilotCloseoutRoot.prepend(pilotCloseoutText('p', error.message, 'error')); }
    finally { button.disabled = false; }
  });
  return form;
}

function pilotCloseoutPause(view) {
  const form = pilotCloseoutBaseForm('Pilot停止を確定');
  const details = document.createElement('fieldset');
  details.innerHTML = '<legend>停止後の動作</legend><p>この候補版は以後の新規予測で選択されず、Baselineを使用します。</p><label><input name="baseline" type="checkbox" required>新規予測をBaselineへ戻すことを確認しました</label><label><input name="unchanged" type="checkbox" required>既存Run・データ・正式設定は変更されないことを確認しました</label>';
  form.insertBefore(details, form.firstChild);
  form.addEventListener('submit', async event => {
    event.preventDefault();
    const button = form.querySelector('button');
    button.disabled = true;
    try {
      await pilotCloseoutPost(view, 'pause', {
        actor: form.elements.actor.value, reason: form.elements.reason.value,
        confirm: form.elements.confirm.checked,
        extra: {
          confirm_future_runs_use_baseline: form.elements.baseline.checked,
          confirm_existing_runs_unchanged: form.elements.unchanged.checked,
        },
      }, 'Pilotを一時停止し、以後の新規予測をBaselineへ戻しました。');
    } catch (error) { pilotCloseoutRoot.prepend(pilotCloseoutText('p', error.message, 'error')); }
    finally { button.disabled = false; }
  });
  return form;
}

async function renderPilotCloseout(assessment) {
  if (!pilotCloseoutRoot || !assessment?.assessment_id) return;
  try {
    const response = await fetch(`/api/pilot-closeouts/${encodeURIComponent(assessment.assessment_id)}`);
    const view = await response.json();
    if (!response.ok) throw new Error(view.detail || 'Pilot完了Gateを読み込めませんでした。');
    pilotCloseoutRoot.replaceChildren(pilotCloseoutText('h4', '15-4. 判断を停止・受入・Rollbackへ引き渡す'));
    const decision = view.latest_decision?.decision || '未判断';
    pilotCloseoutRoot.appendChild(pilotCloseoutText('p', `最新判断：${decision}／適用状態：${view.application.state}`));
    if (view.action === 'EVALUATE_ACCEPTANCE') {
      pilotCloseoutRoot.appendChild(pilotCloseoutAcceptance(view));
    } else if (view.action === 'EVALUATE_ROLLBACK') {
      pilotCloseoutRoot.appendChild(pilotCloseoutRollback(view));
    } else if (view.action === 'CONFIRM_PAUSE') {
      pilotCloseoutRoot.appendChild(pilotCloseoutPause(view));
    } else if (view.action === 'COMPLETE') {
      pilotCloseoutRoot.appendChild(pilotCloseoutText('p', 'Pilot完了結果は適用履歴へ保存済みです。', 'success'));
    } else if (view.action === 'RECORD_DECISION') {
      pilotCloseoutRoot.appendChild(pilotCloseoutText('p', '先に担当者判断を追記してください。', 'notice'));
    } else {
      pilotCloseoutRoot.appendChild(pilotCloseoutText('p', 'この判断から受入またはRollbackへは進みません。', 'notice'));
    }
  } catch (error) {
    pilotCloseoutRoot.replaceChildren(pilotCloseoutText('p', error.message, 'error'));
  }
}

window.PortablePilotCloseouts = {render: renderPilotCloseout};
