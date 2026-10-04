const changeApplicationForm = document.getElementById('change-application-form');
const changeApplicationProposal = document.getElementById('change-application-proposal');
const changeApplicationState = document.getElementById('change-application-state');
const changeApplicationResult = document.getElementById('change-application-result');
const changeApplicationHistory = document.getElementById('change-application-history');

const applicationStateLabels = {
  PREPARED: '準備済み', PILOT_ACTIVE: 'Pilot運用中', BLOCKED: '開始停止',
  ROLLBACK_REQUIRED: 'Rollback必須', ACCEPTED: '受入完了', ROLLED_BACK: 'Rollback完了',
};

function applicationMessage(value, kind = '') {
  changeApplicationState.textContent = value;
  changeApplicationState.className = kind;
}

function applicationJsonBlock(title, value) {
  const section = document.createElement('section');
  const heading = document.createElement('h4');
  const pre = document.createElement('pre');
  heading.textContent = title;
  pre.textContent = JSON.stringify(value, null, 2);
  section.append(heading, pre);
  return section;
}

function applicationBaseForm(buttonText) {
  const form = document.createElement('form');
  form.className = 'change-application-action';
  form.innerHTML = `<label>実行担当者<input name="actor" maxlength="100" required></label><label>記録理由<textarea name="reason" maxlength="500" rows="3" required></textarea></label><label class="confirm-case"><input name="confirm" type="checkbox" required>この操作を監査履歴へ追記することを確認しました</label><button type="submit">${buttonText}</button>`;
  return form;
}

function appendCheck(container, name, label, checked = true) {
  const row = document.createElement('fieldset');
  row.className = 'application-check';
  row.dataset.name = name;
  const legend = document.createElement('legend');
  legend.textContent = label;
  const passLabel = document.createElement('label');
  const pass = document.createElement('input');
  pass.type = 'checkbox';
  pass.name = 'passed';
  pass.checked = checked;
  passLabel.append(pass, ' 合格');
  const evidenceLabel = document.createElement('label');
  evidenceLabel.textContent = '確認根拠';
  const evidence = document.createElement('input');
  evidence.name = 'evidence';
  evidence.maxLength = 500;
  evidence.required = true;
  evidenceLabel.appendChild(evidence);
  row.append(legend, passLabel, evidenceLabel);
  container.appendChild(row);
}

function collectChecks(form, selector = '.application-check') {
  return [...form.querySelectorAll(selector)].map(row => ({
    name: row.dataset.name,
    passed: row.querySelector('[name="passed"]').checked,
    evidence: row.querySelector('[name="evidence"]').value,
  }));
}

async function applicationPost(application, endpoint, body) {
  const response = await fetch(
    `/api/change-applications/${encodeURIComponent(application.application_id)}/${endpoint}`,
    {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)},
  );
  const value = await response.json();
  if (!response.ok) throw new Error(value.detail || 'Pilot適用状態を更新できませんでした。');
  renderChangeApplication(value);
  await refreshChangeApplications();
  return value;
}

function renderGateForm(application) {
  const form = applicationBaseForm('開始Gateを評価');
  const checks = document.createElement('div');
  appendCheck(checks, 'candidate_config', '候補設定の内容・ハッシュ');
  appendCheck(checks, 'api_startup', 'アプリとAPIの起動');
  appendCheck(checks, 'pilot_read', 'Pilot対象データの参照');
  form.insertBefore(checks, form.firstChild);
  const flags = document.createElement('fieldset');
  flags.innerHTML = '<legend>開始前の必須確認</legend><label><input name="backup" type="checkbox" required>事前backupをSHA-256まで照合しました</label><label><input name="staged" type="checkbox" required>候補版をPilot領域へ分離配置しました</label>';
  form.insertBefore(flags, checks);
  form.addEventListener('submit', async event => {
    event.preventDefault();
    const button = form.querySelector('button');
    button.disabled = true;
    try {
      await applicationPost(application, 'pilot-gate', {
        expected_revision: application.revision,
        backup_verified: form.elements.backup.checked,
        candidate_staged: form.elements.staged.checked,
        smoke_checks: collectChecks(form), actor: form.elements.actor.value,
        reason: form.elements.reason.value,
        confirm_audited_transition: form.elements.confirm.checked,
      });
      applicationMessage('Pilot開始Gateの結果を保存しました。', 'success');
    } catch (error) { applicationMessage(error.message, 'error'); }
    finally { button.disabled = false; }
  });
  return form;
}

function resultRow(statement, kind) {
  const row = document.createElement('fieldset');
  row.className = `application-result application-${kind}`;
  row.dataset.statement = statement;
  const legend = document.createElement('legend');
  legend.textContent = statement;
  const label = document.createElement('label');
  const flag = document.createElement('input');
  flag.type = 'checkbox';
  flag.name = kind;
  label.append(flag, kind === 'passed' ? ' 合格' : ' 条件に該当');
  const evidenceLabel = document.createElement('label');
  evidenceLabel.textContent = '確認根拠';
  const evidence = document.createElement('input');
  evidence.name = 'evidence';
  evidence.maxLength = 500;
  evidence.required = true;
  evidenceLabel.appendChild(evidence);
  row.append(legend, label, evidenceLabel);
  return row;
}

function collectResults(form, kind) {
  return [...form.querySelectorAll(`.application-${kind}`)].map(row => ({
    statement: row.dataset.statement,
    [kind]: row.querySelector(`[name="${kind}"]`).checked,
    evidence: row.querySelector('[name="evidence"]').value,
  }));
}

function renderAcceptanceForm(application) {
  const form = applicationBaseForm('受入結果を記録');
  const results = document.createElement('div');
  const acceptanceTitle = document.createElement('h4');
  acceptanceTitle.textContent = '受入基準';
  results.appendChild(acceptanceTitle);
  for (const statement of application.proposal.acceptance_criteria) {
    results.appendChild(resultRow(statement, 'passed'));
  }
  const rollbackTitle = document.createElement('h4');
  rollbackTitle.textContent = 'Rollback条件';
  results.appendChild(rollbackTitle);
  for (const statement of application.proposal.rollback_conditions) {
    results.appendChild(resultRow(statement, 'triggered'));
  }
  form.insertBefore(results, form.firstChild);
  form.addEventListener('submit', async event => {
    event.preventDefault();
    const button = form.querySelector('button');
    button.disabled = true;
    try {
      await applicationPost(application, 'acceptance', {
        expected_revision: application.revision,
        acceptance_results: collectResults(form, 'passed'),
        rollback_results: collectResults(form, 'triggered'),
        actor: form.elements.actor.value, reason: form.elements.reason.value,
        confirm_audited_transition: form.elements.confirm.checked,
      });
      applicationMessage('受入評価を保存しました。未達時はrollbackが必須です。', 'success');
    } catch (error) { applicationMessage(error.message, 'error'); }
    finally { button.disabled = false; }
  });
  return form;
}

function renderRollbackForm(application) {
  const form = applicationBaseForm('Rollback結果を記録');
  const target = document.createElement('p');
  target.textContent = `戻す版：${application.proposal.rollback_target_version}`;
  const restored = document.createElement('label');
  restored.innerHTML = '<input name="restored" type="checkbox" required>事前backupから復元しました';
  const checks = document.createElement('div');
  appendCheck(checks, 'configuration_restored', '旧設定への復帰');
  appendCheck(checks, 'api_restart', 'アプリとAPIの再起動');
  appendCheck(checks, 'data_read', '既存データの参照');
  form.insertBefore(checks, form.firstChild);
  form.insertBefore(restored, checks);
  form.insertBefore(target, restored);
  form.addEventListener('submit', async event => {
    event.preventDefault();
    const button = form.querySelector('button');
    button.disabled = true;
    try {
      await applicationPost(application, 'rollback', {
        expected_revision: application.revision,
        rollback_target_version: application.proposal.rollback_target_version,
        backup_restored: form.elements.restored.checked,
        rollback_checks: collectChecks(form), actor: form.elements.actor.value,
        reason: form.elements.reason.value,
        confirm_audited_transition: form.elements.confirm.checked,
      });
      applicationMessage('Rollback結果を保存しました。', 'success');
    } catch (error) { applicationMessage(error.message, 'error'); }
    finally { button.disabled = false; }
  });
  return form;
}

function renderChangeApplication(application) {
  changeApplicationResult.replaceChildren();
  const title = document.createElement('h3');
  title.textContent = `${applicationStateLabels[application.state]}／${application.candidate_version}`;
  const safety = document.createElement('p');
  safety.className = application.source_approval_is_current ? 'notice' : 'error';
  safety.textContent = application.source_approval_is_current
    ? '承認状態は有効です。対象は固定されたPilot Scopeだけです。'
    : '元の承認状態が更新されています。次の操作はできません。';
  changeApplicationResult.append(
    title, safety,
    applicationJsonBlock('Pilot適用範囲', application.application_scope),
    applicationJsonBlock('候補設定', application.proposal.proposed_configuration),
  );
  const backup = document.createElement('p');
  backup.textContent = `事前backup：${application.backup_reference}／SHA-256 ${application.backup_sha256}`;
  changeApplicationResult.appendChild(backup);
  const history = document.createElement('ol');
  for (const item of application.events) {
    const row = document.createElement('li');
    row.textContent = `rev.${item.revision} ${item.transition} → ${applicationStateLabels[item.resulting_state]}／${item.actor}：${item.reason}`;
    history.appendChild(row);
  }
  changeApplicationResult.appendChild(history);
  if (!application.source_approval_is_current) return;
  if (['PREPARED', 'BLOCKED'].includes(application.state)) {
    changeApplicationResult.appendChild(renderGateForm(application));
  } else if (application.state === 'PILOT_ACTIVE') {
    changeApplicationResult.appendChild(renderAcceptanceForm(application));
    changeApplicationResult.appendChild(renderRollbackForm(application));
  } else if (application.state === 'ROLLBACK_REQUIRED') {
    changeApplicationResult.appendChild(renderRollbackForm(application));
  }
}

async function loadChangeApplication(applicationId) {
  const response = await fetch(`/api/change-applications/${encodeURIComponent(applicationId)}`);
  const value = await response.json();
  if (!response.ok) throw new Error(value.detail || 'Pilot適用計画を読み込めませんでした。');
  renderChangeApplication(value);
}

async function refreshChangeApplications() {
  try {
    const response = await fetch('/api/change-applications');
    const value = await response.json();
    if (!response.ok) throw new Error(value.detail || 'Pilot適用計画を読み込めませんでした。');
    const selected = changeApplicationProposal.value;
    changeApplicationProposal.replaceChildren();
    const placeholder = document.createElement('option');
    placeholder.value = '';
    placeholder.textContent = value.eligible_proposals.length ? '選択してください' : '承認済み変更案はありません';
    changeApplicationProposal.appendChild(placeholder);
    for (const proposal of value.eligible_proposals) {
      const option = document.createElement('option');
      option.value = proposal.proposal_id;
      option.dataset.version = proposal.candidate_version_default;
      option.textContent = `${proposal.change_target}／${proposal.candidate_version_default}／承認 rev.${proposal.approval_revision}`;
      option.selected = option.value === selected;
      changeApplicationProposal.appendChild(option);
    }
    changeApplicationHistory.replaceChildren();
    for (const application of value.applications) {
      const item = document.createElement('li');
      const button = document.createElement('button');
      button.type = 'button';
      button.textContent = `${applicationStateLabels[application.state]}／${application.candidate_version}／${application.executor}`;
      button.addEventListener('click', () => loadChangeApplication(application.application_id).catch(error => applicationMessage(error.message, 'error')));
      item.appendChild(button);
      changeApplicationHistory.appendChild(item);
    }
  } catch (error) { applicationMessage(error.message, 'error'); }
}

changeApplicationProposal.addEventListener('change', () => {
  const selected = changeApplicationProposal.selectedOptions[0];
  if (selected?.dataset.version) document.getElementById('change-application-version').value = selected.dataset.version;
});

changeApplicationForm.addEventListener('submit', async event => {
  event.preventDefault();
  const button = changeApplicationForm.querySelector('button');
  button.disabled = true;
  try {
    const response = await fetch('/api/change-applications', {
      method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({
        proposal_id: changeApplicationProposal.value,
        candidate_version: document.getElementById('change-application-version').value,
        backup_reference: document.getElementById('change-application-backup').value,
        backup_sha256: document.getElementById('change-application-backup-sha').value,
        executor: document.getElementById('change-application-executor').value,
        known_at: new Date(document.getElementById('change-application-known-at').value).toISOString(),
        confirm_pilot_only: document.getElementById('change-application-confirm').checked,
      })},
    );
    const value = await response.json();
    if (!response.ok) throw new Error(value.detail || 'Pilot適用計画を準備できませんでした。');
    renderChangeApplication(value);
    await refreshChangeApplications();
    applicationMessage('Pilot適用計画を準備しました。開始Gateを確認してください。', 'success');
  } catch (error) { applicationMessage(error.message, 'error'); }
  finally { button.disabled = false; }
});

const applicationNow = new Date();
document.getElementById('change-application-known-at').value = new Date(applicationNow.getTime() - applicationNow.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
window.PortableChangeApplications = {refresh: refreshChangeApplications};
refreshChangeApplications();
