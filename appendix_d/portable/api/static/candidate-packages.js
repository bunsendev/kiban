const candidatePackageForm = document.getElementById('candidate-package-form');
const candidatePackageProposal = document.getElementById('candidate-package-proposal');
const candidatePackageState = document.getElementById('candidate-package-state');
const candidatePackageResult = document.getElementById('candidate-package-result');
const candidatePackageHistory = document.getElementById('candidate-package-history');
let candidatePackageCache = [];

function candidatePackageMessage(message, kind = '') {
  candidatePackageState.textContent = message;
  candidatePackageState.className = kind;
}

function renderCandidatePackage(value) {
  candidatePackageResult.replaceChildren();
  const title = document.createElement('h4');
  title.textContent = `${value.candidate_version}／${value.model_name}`;
  const details = document.createElement('p');
  details.textContent = `manifest SHA-256：${value.manifest_sha256}`;
  const smoke = document.createElement('p');
  smoke.textContent = `smoke test：${value.smoke_test.status}／予測 ${value.smoke_test.forecast_count}件／結果SHA-256 ${value.smoke_test.prediction_sha256}`;
  const limits = document.createElement('p');
  limits.textContent = `資源上限：${value.resource_limits.max_series}系列・履歴${value.resource_limits.max_history_days}日・予測${value.resource_limits.max_horizon_days}日・network ${value.resource_limits.network_access ? '許可' : '禁止'}`;
  candidatePackageResult.append(title, details, smoke, limits);
}

async function refreshCandidatePackages() {
  try {
    const response = await fetch('/api/runtime-candidate-packages');
    const value = await response.json();
    if (!response.ok) throw new Error(value.detail || '候補版を読み込めませんでした。');
    candidatePackageCache = value.packages;
    const selected = candidatePackageProposal.value;
    candidatePackageProposal.replaceChildren();
    const placeholder = document.createElement('option');
    placeholder.value = '';
    placeholder.textContent = value.eligible_proposals.length
      ? '選択してください' : '承認済みの予測モデル変更案はありません';
    candidatePackageProposal.appendChild(placeholder);
    for (const proposal of value.eligible_proposals) {
      const option = document.createElement('option');
      option.value = proposal.proposal_id;
      option.disabled = !proposal.supported;
      option.textContent = `${proposal.candidate_version || '版未設定'}／${proposal.model_name || 'モデル未設定'}${proposal.supported ? '' : '（実行未対応）'}`;
      candidatePackageProposal.appendChild(option);
    }
    if ([...candidatePackageProposal.options].some(item => item.value === selected)) {
      candidatePackageProposal.value = selected;
    }
    candidatePackageHistory.replaceChildren();
    for (const item of value.packages) {
      const row = document.createElement('li');
      row.textContent = `${item.candidate_version}／${item.model_name}／${item.smoke_test.status}／SHA-256 ${item.manifest_sha256}`;
      row.addEventListener('click', () => renderCandidatePackage(item));
      candidatePackageHistory.appendChild(row);
    }
    candidatePackageMessage(value.notice, 'notice');
  } catch (error) {
    candidatePackageMessage(error.message, 'error');
  }
}

candidatePackageForm.addEventListener('submit', async event => {
  event.preventDefault();
  const button = candidatePackageForm.querySelector('button');
  button.disabled = true;
  candidatePackageMessage('候補版を起動確認しています。');
  try {
    const knownAt = new Date(document.getElementById('candidate-package-known-at').value);
    const response = await fetch('/api/runtime-candidate-packages', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        proposal_id: candidatePackageProposal.value,
        actor: document.getElementById('candidate-package-actor').value,
        known_at: knownAt.toISOString(),
        confirm_shadow_package: document.getElementById('candidate-package-shadow').checked,
        confirm_rollback_target: document.getElementById('candidate-package-rollback').checked,
      }),
    });
    const value = await response.json();
    if (!response.ok) throw new Error(value.detail || '候補版を発行できませんでした。');
    renderCandidatePackage(value);
    candidatePackageMessage('候補版を発行しました。表示されたmanifest SHA-256を開始Gateで確認してください。', 'success');
    await refreshCandidatePackages();
    if (window.PortableRuntimeAssignments) await window.PortableRuntimeAssignments.refresh();
  } catch (error) {
    candidatePackageMessage(error.message, 'error');
  } finally {
    button.disabled = false;
  }
});

window.PortableCandidatePackages = {
  refresh: refreshCandidatePackages,
  forApplication: application => candidatePackageCache.find(item => (
    item.proposal_id === application.proposal.proposal_id
      && item.candidate_version === application.candidate_version
  )),
};
refreshCandidatePackages();
