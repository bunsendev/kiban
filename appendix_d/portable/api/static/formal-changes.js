const formalChangeForm = document.getElementById('formal-change-form');
const formalChangeRun = document.getElementById('formal-change-run');
const formalChangeState = document.getElementById('formal-change-state');
const formalChangeResult = document.getElementById('formal-change-result');
const formalChangeHistory = document.getElementById('formal-change-history');

const formalTargetLabels = {
  FORECAST_MODEL: '需要予測モデル',
  FORECAST_FEATURE: '需要予測の入力項目',
  SHIPMENT_POLICY: '推奨出荷Policy',
  ROUTE_POLICY: '配送Route Policy',
  DATA_CONTRACT: 'データ契約',
};

function formalChangeMessage(value, kind = '') {
  formalChangeState.textContent = value;
  formalChangeState.className = kind;
}

function formalJson(id, label) {
  try {
    const value = JSON.parse(document.getElementById(id).value);
    if (!value || Array.isArray(value) || typeof value !== 'object') throw new Error();
    return value;
  } catch {
    throw new Error(`${label}はJSON objectで入力してください。`);
  }
}

function formalLines(id, label) {
  const values = document.getElementById(id).value.split(/\r?\n/).map(value => value.trim()).filter(Boolean);
  if (!values.length) throw new Error(`${label}を1件以上入力してください。`);
  return values;
}

async function decideFormalChange(proposal, form) {
  const button = form.querySelector('button');
  button.disabled = true;
  try {
    const response = await fetch(
      `/api/formal-changes/${encodeURIComponent(proposal.proposal_id)}/decision`,
      {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({
        expected_revision: proposal.revision,
        decision: form.elements.decision.value,
        approver: form.elements.approver.value,
        reason: form.elements.reason.value,
        confirm_separate_approval: form.elements.confirm.checked,
      })},
    );
    const value = await response.json();
    if (!response.ok) throw new Error(value.detail || '正式変更案の判断を保存できませんでした。');
    renderFormalChange(value);
    await refreshFormalChanges();
    formalChangeMessage('判断を追記しました。変更はまだ適用されていません。', 'success');
  } catch (error) {
    formalChangeMessage(error.message, 'error');
  } finally {
    button.disabled = false;
  }
}

function formalJsonBlock(title, value) {
  const section = document.createElement('section');
  const heading = document.createElement('h4');
  const pre = document.createElement('pre');
  heading.textContent = title;
  pre.textContent = JSON.stringify(value, null, 2);
  section.append(heading, pre);
  return section;
}

function formalList(title, values) {
  const section = document.createElement('section');
  const heading = document.createElement('h4');
  const list = document.createElement('ol');
  heading.textContent = title;
  for (const value of values) {
    const item = document.createElement('li');
    item.textContent = value;
    list.appendChild(item);
  }
  section.append(heading, list);
  return section;
}

function renderFormalChange(proposal) {
  formalChangeResult.replaceChildren();
  const title = document.createElement('h3');
  title.textContent = `${formalTargetLabels[proposal.change_target]}／${proposal.status}`;
  const source = document.createElement('p');
  source.textContent = `比較対象 ${proposal.source.target}、${proposal.source.baseline_version} → ${proposal.source.challenger_version}、共通比較 ${proposal.source.comparable_count}件`;
  const safety = document.createElement('p');
  safety.className = 'notice';
  safety.textContent = '適用状態：未適用。承認は実装工程へ進める判断であり、設定変更ではありません。';
  formalChangeResult.append(
    title, source, safety,
    formalJsonBlock('現行設定', proposal.current_configuration),
    formalJsonBlock('変更後設定', proposal.proposed_configuration),
    formalJsonBlock('適用範囲', proposal.application_scope),
    formalList('受入基準', proposal.acceptance_criteria),
    formalList('Rollback条件', proposal.rollback_conditions),
  );
  const rollback = document.createElement('p');
  rollback.textContent = `Rollback先版：${proposal.rollback_target_version}`;
  formalChangeResult.appendChild(rollback);
  const history = document.createElement('ol');
  for (const event of proposal.decision_history) {
    const item = document.createElement('li');
    item.textContent = `rev.${event.revision} ${event.decision}／${event.approver}：${event.reason}`;
    history.appendChild(item);
  }
  formalChangeResult.appendChild(history);
  const form = document.createElement('form');
  form.className = 'formal-change-decision-form';
  form.innerHTML = '<label>別承認者<input name="approver" maxlength="100" required></label><label>判断<select name="decision"><option value="APPROVED_FOR_IMPLEMENTATION">実装案として承認</option><option value="REJECTED">変更案を却下</option></select></label><label>判断理由<textarea name="reason" maxlength="500" rows="3" required></textarea></label><label class="confirm-case"><input name="confirm" type="checkbox" required>作成者とは別担当者が確認し、承認しても自動適用されないことを確認しました</label><button type="submit">判断を追記</button>';
  form.addEventListener('submit', event => {
    event.preventDefault();
    decideFormalChange(proposal, form);
  });
  formalChangeResult.appendChild(form);
}

async function loadFormalChange(proposalId) {
  const response = await fetch(`/api/formal-changes/${encodeURIComponent(proposalId)}`);
  const value = await response.json();
  if (!response.ok) throw new Error(value.detail || '正式変更案を読み込めませんでした。');
  renderFormalChange(value);
}

function updateFormalTargets(sourceTarget) {
  const select = document.getElementById('formal-change-target');
  const allowed = sourceTarget === 'DEMAND_FORECAST'
    ? ['FORECAST_MODEL', 'FORECAST_FEATURE', 'DATA_CONTRACT']
    : ['SHIPMENT_POLICY', 'ROUTE_POLICY', 'DATA_CONTRACT'];
  select.replaceChildren();
  for (const value of allowed) {
    const option = document.createElement('option');
    option.value = value;
    option.textContent = formalTargetLabels[value];
    select.appendChild(option);
  }
}

async function refreshFormalChanges() {
  try {
    const response = await fetch('/api/formal-changes');
    const value = await response.json();
    if (!response.ok) throw new Error(value.detail || '正式変更案一覧を読み込めませんでした。');
    const selected = formalChangeRun.value;
    formalChangeRun.replaceChildren();
    const placeholder = document.createElement('option');
    placeholder.value = '';
    placeholder.textContent = value.eligible_runs.length ? '選択してください' : '作成推奨の比較runはありません';
    formalChangeRun.appendChild(placeholder);
    for (const run of value.eligible_runs) {
      const option = document.createElement('option');
      option.value = run.run_id;
      option.dataset.target = run.target;
      option.dataset.baseline = run.baseline_version;
      option.dataset.challenger = run.challenger_version;
      option.textContent = `${run.target}／${run.baseline_version} → ${run.challenger_version}／${run.comparable_count}件`;
      option.selected = option.value === selected;
      formalChangeRun.appendChild(option);
    }
    updateFormalTargets(formalChangeRun.selectedOptions[0]?.dataset.target || 'DEMAND_FORECAST');
    formalChangeHistory.replaceChildren();
    for (const proposal of value.proposals) {
      const item = document.createElement('li');
      const button = document.createElement('button');
      button.type = 'button';
      button.textContent = `${formalTargetLabels[proposal.change_target]}／${proposal.author}`;
      button.addEventListener('click', () => loadFormalChange(proposal.proposal_id).catch(error => formalChangeMessage(error.message, 'error')));
      item.appendChild(button);
      formalChangeHistory.appendChild(item);
    }
  } catch (error) {
    formalChangeMessage(error.message, 'error');
  }
}

formalChangeRun.addEventListener('change', () => {
  const selected = formalChangeRun.selectedOptions[0];
  updateFormalTargets(selected?.dataset.target || 'DEMAND_FORECAST');
  if (selected?.value) {
    document.getElementById('formal-current-config').value = JSON.stringify({
      version: selected.dataset.baseline,
    }, null, 2);
    document.getElementById('formal-proposed-config').value = JSON.stringify({
      version: selected.dataset.challenger,
    }, null, 2);
    document.getElementById('formal-rollback-target').value = selected.dataset.baseline;
  }
});

formalChangeForm.addEventListener('submit', async event => {
  event.preventDefault();
  const button = formalChangeForm.querySelector('button');
  button.disabled = true;
  try {
    const response = await fetch('/api/formal-changes', {
      method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({
        run_id: formalChangeRun.value,
        change_target: document.getElementById('formal-change-target').value,
        current_configuration: formalJson('formal-current-config', '現行設定'),
        proposed_configuration: formalJson('formal-proposed-config', '変更後設定'),
        application_scope: formalJson('formal-application-scope', '適用範囲'),
        acceptance_criteria: formalLines('formal-acceptance-criteria', '受入基準'),
        rollback_conditions: formalLines('formal-rollback-conditions', 'Rollback条件'),
        rollback_target_version: document.getElementById('formal-rollback-target').value,
        author: document.getElementById('formal-change-author').value,
        known_at: new Date(document.getElementById('formal-change-known-at').value).toISOString(),
        confirm_no_automatic_application: document.getElementById('formal-change-confirm').checked,
      })},
    );
    const value = await response.json();
    if (!response.ok) throw new Error(value.detail || '正式変更案を保存できませんでした。');
    renderFormalChange(value);
    await refreshFormalChanges();
    formalChangeMessage('正式変更案を固定しました。設定は変更していません。', 'success');
  } catch (error) {
    formalChangeMessage(error.message, 'error');
  } finally {
    button.disabled = false;
  }
});

const formalNow = new Date();
document.getElementById('formal-change-known-at').value = new Date(formalNow.getTime() - formalNow.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
window.PortableFormalChanges = {refresh: refreshFormalChanges};
refreshFormalChanges();
