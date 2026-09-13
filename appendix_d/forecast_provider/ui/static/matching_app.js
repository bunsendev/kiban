import { installPkceLogin } from "./pkce.js";
import { ApiError, clearToken, setToken } from "./api.js";
import {
  createDecision,
  createJanMapping,
  createMatchingJob,
  createProduct,
  loadMatchingDashboard,
  loadMatchingJob,
} from "./matching_api.js";
import {
  decisionPayload,
  janMappingPayload,
  matchingJobPayload,
  syncDecisionInputs,
} from "./matching_forms.js";
import {
  clearCandidateDetail,
  renderCandidateDetail,
  renderCatalogs,
  renderFormOptions,
  renderJobDetail,
  renderLists,
  renderSummary,
  showJobDetail,
} from "./matching_render.js";

const state = {
  dashboard: null,
  selectedJobId: null,
  selectedCandidateId: null,
  detail: null,
  permissions: new Set(),
  busy: false,
};

const byId = (id) => document.getElementById(id);
const value = (id) => byId(id).value.trim();
const elements = {
  connectionForm: byId("connection-form"),
  token: byId("api-token"),
  sessionControls: byId("session-controls"),
  sessionIdentity: byId("session-identity"),
  refresh: byId("refresh-button"),
  disconnect: byId("disconnect-button"),
  jobSearch: byId("job-search"),
  candidateSearch: byId("candidate-search"),
  notice: byId("notice"),
};

function notice(message, tone = "") {
  elements.notice.className = `notice${tone ? ` ${tone}` : ""}`;
  elements.notice.textContent = message;
}

function setBusy(busy) {
  state.busy = busy;
  document.body.setAttribute("aria-busy", String(busy));
  for (const button of document.querySelectorAll("button")) {
    const permission = button.dataset.permission;
    button.disabled = busy || (permission && !state.permissions.has(permission));
  }
}

function handleError(error) {
  if (error instanceof ApiError && error.status === 401) {
    notice("認証できません。API tokenを確認してください。", "error");
  } else if (error instanceof ApiError && error.status === 403) {
    notice("この操作に必要な権限がありません。", "error");
  } else {
    notice(error.message || "処理に失敗しました。", "error");
  }
}

function drawLists() {
  if (!state.dashboard) return;
  renderLists(
    state.dashboard,
    state.detail,
    { jobId: state.selectedJobId, candidateId: state.selectedCandidateId },
    { jobs: elements.jobSearch.value, candidates: elements.candidateSearch.value },
    selectJob,
    selectCandidate,
  );
}

function selectCandidate(candidateId) {
  if (!state.detail) return;
  const candidate = state.detail.candidates.find((item) => item.candidate_id === candidateId);
  if (!candidate) return;
  state.selectedCandidateId = candidateId;
  renderCandidateDetail(candidate, state.dashboard);
  syncDecisionInputs(byId);
  drawLists();
  notice("候補根拠と版付き判断履歴を読み込みました。", "success");
}

async function selectJob(jobId, preferredCandidateId = null) {
  if (state.busy || jobId === state.selectedJobId) return;
  setBusy(true);
  notice("名寄せjobと候補根拠を読み込んでいます。");
  try {
    state.selectedJobId = jobId;
    state.selectedCandidateId = null;
    state.detail = await loadMatchingJob(jobId);
    renderJobDetail(state.detail);
    const preferred = state.detail.candidates.find((item) =>
      item.candidate_id === preferredCandidateId);
    const next = preferred || state.detail.candidates[0];
    if (next) selectCandidate(next.candidate_id);
    else {
      clearCandidateDetail();
      notice(
        state.detail.status === "SUCCEEDED"
          ? "候補は生成されませんでした。JANは自動統合されていません。"
          : "名寄せWorkerの完了後に更新してください。",
        state.detail.status === "SUCCEEDED" ? "success" : "",
      );
    }
    drawLists();
  } catch (error) {
    state.selectedJobId = null;
    state.selectedCandidateId = null;
    state.detail = null;
    showJobDetail(false);
    drawLists();
    handleError(error);
  } finally {
    setBusy(false);
  }
}

async function refreshDashboard(preferred = {}) {
  setBusy(true);
  notice("名寄せ・商品マスター台帳を更新しています。");
  try {
    state.dashboard = await loadMatchingDashboard();
    state.permissions = new Set(state.dashboard.session.permissions);
    elements.sessionIdentity.textContent = `${state.dashboard.session.subject} / ${state.dashboard.session.roles.join(", ")}`;
    renderSummary(state.dashboard);
    renderFormOptions(state.dashboard);
    renderCatalogs(state.dashboard);
    const requestedJob = preferred.jobId || state.selectedJobId;
    const available = requestedJob && state.dashboard.jobs.some((job) =>
      job.matching_job_id === requestedJob);
    const nextJobId = available ? requestedJob : state.dashboard.jobs[0]?.matching_job_id;
    state.selectedJobId = null;
    state.selectedCandidateId = null;
    state.detail = null;
    showJobDetail(false);
    drawLists();
    if (nextJobId) {
      setBusy(false);
      await selectJob(nextJobId, preferred.candidateId);
    } else {
      notice("接続しました。名寄せjobはまだありません。", "success");
    }
    return true;
  } catch (error) {
    handleError(error);
    return false;
  } finally {
    setBusy(false);
  }
}

byId("matching-job-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (state.busy) return;
  setBusy(true);
  notice("正規化jobと候補生成条件を検証しています。");
  try {
    const created = await createMatchingJob(matchingJobPayload(byId));
    setBusy(false);
    await refreshDashboard({ jobId: created.id });
    notice("名寄せjobを登録しました。Worker完了後に更新してください。", "success");
  } catch (error) {
    handleError(error);
  } finally {
    setBusy(false);
  }
});

byId("product-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (state.busy) return;
  setBusy(true);
  notice("canonical productを登録しています。");
  try {
    await createProduct({ display_name: value("product-name"), reason: value("product-reason") });
    byId("product-form").reset();
    setBusy(false);
    await refreshDashboard({ jobId: state.selectedJobId, candidateId: state.selectedCandidateId });
    notice("canonical productを登録し、選択肢を更新しました。", "success");
  } catch (error) {
    handleError(error);
  } finally {
    setBusy(false);
  }
});

byId("jan-mapping-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (state.busy) return;
  setBusy(true);
  notice("JAN有効期間の重複と商品を検証しています。");
  try {
    await createJanMapping(janMappingPayload(byId));
    setBusy(false);
    await refreshDashboard({ jobId: state.selectedJobId, candidateId: state.selectedCandidateId });
    notice("JAN有効期間を版・理由付きで登録しました。", "success");
  } catch (error) {
    handleError(error);
  } finally {
    setBusy(false);
  }
});

byId("decision-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (state.busy || !state.selectedCandidateId) return;
  setBusy(true);
  notice("候補、商品、判断版を再検証しています。");
  try {
    await createDecision(decisionPayload(byId, state.selectedCandidateId));
    setBusy(false);
    await refreshDashboard({ jobId: state.selectedJobId, candidateId: state.selectedCandidateId });
    notice("名寄せ判断を追記し、履歴を再読込しました。", "success");
  } catch (error) {
    handleError(error);
  } finally {
    setBusy(false);
  }
});

elements.connectionForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  setToken(elements.token.value);
  if (await refreshDashboard()) {
    elements.connectionForm.hidden = true;
    elements.sessionControls.hidden = false;
    elements.token.value = "";
  }
});
elements.refresh.addEventListener("click", () => refreshDashboard());
elements.disconnect.addEventListener("click", () => {
  clearToken();
  state.dashboard = null;
  state.selectedJobId = null;
  state.selectedCandidateId = null;
  state.detail = null;
  state.permissions = new Set();
  elements.connectionForm.hidden = false;
  elements.sessionControls.hidden = true;
  elements.sessionIdentity.textContent = "";
  elements.jobSearch.value = "";
  elements.candidateSearch.value = "";
  const emptyDashboard = { jobs: [], products: [], mappings: [], normalizations: [] };
  renderSummary(emptyDashboard);
  renderFormOptions(emptyDashboard);
  renderCatalogs(emptyDashboard);
  byId("job-list").replaceChildren();
  byId("candidate-list").replaceChildren();
  byId("job-filter-count").textContent = "0件";
  byId("candidate-filter-count").textContent = "0件";
  showJobDetail(false);
  setBusy(false);
  notice("切断しました。tokenは画面から破棄されました。", "success");
});

elements.jobSearch.addEventListener("input", drawLists);
elements.candidateSearch.addEventListener("input", drawLists);
byId("decision-value").addEventListener("change", () => syncDecisionInputs(byId));
syncDecisionInputs(byId);
setBusy(false);

installPkceLogin();
