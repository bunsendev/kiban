const runtimeAssignmentState = document.getElementById('runtime-assignment-state');
const runtimeCandidateList = document.getElementById('runtime-candidate-list');
const runtimeResolutionList = document.getElementById('runtime-resolution-list');

const runtimeStatusLabels = {
  BASELINE_SELECTED: 'Baselineを使用',
  CANDIDATE_SELECTED: 'Pilot候補版を使用',
  BLOCKED: '安全停止',
};

async function refreshRuntimeAssignments() {
  try {
    const response = await fetch('/api/runtime-assignments');
    const value = await response.json();
    if (!response.ok) throw new Error(value.detail || '実行時の版選択履歴を読み込めませんでした。');
    runtimeCandidateList.replaceChildren();
    if (!value.installed_candidates.length) {
      const item = document.createElement('li');
      item.textContent = '配置済み候補版はありません。候補版を使う場合は管理者がmanifestを配置します。';
      runtimeCandidateList.appendChild(item);
    }
    for (const candidate of value.installed_candidates) {
      const item = document.createElement('li');
      item.textContent = `${candidate.candidate_version || '版不明'}／SHA-256 ${candidate.manifest_sha256}／${candidate.supported ? '実行対応' : '実行未対応'}`;
      runtimeCandidateList.appendChild(item);
    }
    runtimeResolutionList.replaceChildren();
    for (const resolution of value.resolutions) {
      const item = document.createElement('li');
      const title = document.createElement('strong');
      title.textContent = `${runtimeStatusLabels[resolution.status]}／${resolution.pilot_scope_version}／${resolution.selected_version}`;
      const detail = document.createElement('p');
      detail.textContent = `理由 ${resolution.reason_code}／設定SHA-256 ${resolution.selected_configuration_sha256}／担当 ${resolution.actor}`;
      item.append(title, detail);
      runtimeResolutionList.appendChild(item);
    }
    runtimeAssignmentState.textContent = value.notice;
    runtimeAssignmentState.className = 'notice';
  } catch (error) {
    runtimeAssignmentState.textContent = error.message;
    runtimeAssignmentState.className = 'error';
  }
}

window.PortableRuntimeAssignments = {refresh: refreshRuntimeAssignments};
refreshRuntimeAssignments();
