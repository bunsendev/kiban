import { installPkceLogin } from "./pkce.js";
import { ApiError, clearToken, setToken } from "./api.js";
import {
  createCandidateJob,
  createSelection,
  loadCandidateJob,
  loadSelectionDashboard,
} from "./selection_api.js";
import {
  renderCandidates,
  renderDashboard,
  renderDraft,
  renderJobDetail,
  renderJobs,
  renderSelections,
  setTab,
  showDetail,
} from "./selection_render.js";
import { parseList } from "./format.js";

const state = {
  dashboard: null,
  selectedId: null,
  selected: null,
  draft: new Map(),
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
  selectionSearch: byId("selection-search"),
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
    const blocked = button.dataset.blocked === "true";
    button.disabled = busy || blocked || (permission && !state.permissions.has(permission));
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
  renderJobs(state.dashboard.jobs, state.selectedId, elements.jobSearch.value, selectJob);
  renderSelections(state.dashboard.selections, elements.selectionSearch.value);
}

function redrawCandidates() {
  if (!state.selected) return;
  renderCandidates(
    state.selected.candidates,
    state.draft,
    elements.candidateSearch.value,
    toggleCandidate,
  );
}

function redrawDraft() {
  renderDraft(
    state.draft,
    value("selection-scope"),
    (productId, centers) => { state.draft.get(productId).centerIds = centers; },
    (productId, reason) => { state.draft.get(productId).reason = reason; },
    (candidate) => toggleCandidate(candidate, false),
  );
}

function toggleCandidate(candidate, selected) {
  if (selected) {
    state.draft.set(candidate.canonical_product_id, {
      candidate,
      centerIds: new Set(candidate.center_ids),
      reason: "",
    });
  } else {
    state.draft.delete(candidate.canonical_product_id);
  }
  redrawCandidates();
  redrawDraft();
}

async function selectJob(jobId) {
  if (state.busy || jobId === state.selectedId) return;
  setBusy(true);
  notice("候補指標を読み込んでいます。");
  try {
    state.selectedId = jobId;
    state.draft = new Map();
    elements.candidateSearch.value = "";
    drawLists();
    state.selected = await loadCandidateJob(jobId);
    renderJobDetail(state.selected);
    redrawCandidates();
    redrawDraft();
    setTab("candidates");
    notice(
      state.selected.job.status === "SUCCEEDED"
        ? "候補指標を読み込みました。"
        : "候補算出Workerの完了後に更新してください。",
      state.selected.job.status === "SUCCEEDED" ? "success" : "",
    );
  } catch (error) {
    state.selectedId = null;
    state.selected = null;
    showDetail(false);
    drawLists();
    handleError(error);
  } finally {
    setBusy(false);
  }
}

async function refreshDashboard(preferredId = state.selectedId) {
  setBusy(true);
  notice("重要品目選定台帳を更新しています。");
  try {
    const dashboard = await loadSelectionDashboard();
    state.dashboard = dashboard;
    state.permissions = new Set(dashboard.session.permissions);
    elements.sessionIdentity.textContent = `${dashboard.session.subject} / ${dashboard.session.roles.join(", ")}`;
    renderDashboard(dashboard);
    const available = dashboard.jobs.some((job) => job.candidate_job_id === preferredId);
    state.selectedId = null;
    state.selected = null;
    state.draft = new Map();
    showDetail(false);
    drawLists();
    const nextId = available ? preferredId : dashboard.jobs[0]?.candidate_job_id;
    if (nextId) {
      setBusy(false);
      await selectJob(nextId);
    } else {
      redrawDraft();
      notice("接続しました。候補算出jobはまだありません。", "success");
    }
    return true;
  } catch (error) {
    handleError(error);
    return false;
  } finally {
    setBusy(false);
  }
}

byId("candidate-job-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (state.busy) return;
  setBusy(true);
  notice("日次buildと候補算出条件を検証しています。");
  try {
    const created = await createCandidateJob({
      candidate_version: value("job-version"),
      daily_build_id: value("job-build"),
      business_product_ids: parseList(value("job-business-products")),
      max_missing_rate: Number(value("job-missing-rate")),
      stable_cv_max: Number(value("job-stable-cv")),
      intermittent_zero_rate_min: Number(value("job-zero-rate")),
      purpose: value("job-purpose"),
    });
    setBusy(false);
    await refreshDashboard(created.id);
    notice("候補算出jobを登録しました。Worker完了後に更新してください。", "success");
  } catch (error) {
    handleError(error);
  } finally {
    setBusy(false);
  }
});

byId("selection-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!state.selectedId || state.busy) return;
  const scope = value("selection-scope");
  const limits = scope === "INITIAL" ? [3, 5] : [20, 50];
  const items = [...state.draft.values()].map((entry) => ({
    canonical_product_id: entry.candidate.canonical_product_id,
    center_ids: [...entry.centerIds],
    reason: entry.reason.trim(),
  }));
  if (items.length < limits[0] || items.length > limits[1]) {
    notice(`${scope}の選定品目数は${limits[0]}〜${limits[1]}件です。`, "error");
    return;
  }
  if (items.some((item) => !item.center_ids.length || !item.reason)) {
    notice("全品目で1件以上のcenterと選定理由を指定してください。", "error");
    return;
  }
  setBusy(true);
  notice("候補品質、center、品目数、選定版を検証しています。");
  try {
    await createSelection({
      selection_version: value("selection-version"),
      candidate_job_id: state.selectedId,
      scope,
      items,
      rationale: value("selection-rationale"),
    });
    const selected = state.selectedId;
    setBusy(false);
    await refreshDashboard(selected);
    notice("選定版を確定し、追記型台帳を再読込しました。", "success");
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
  state.selectedId = null;
  state.selected = null;
  state.draft = new Map();
  state.permissions = new Set();
  elements.connectionForm.hidden = false;
  elements.sessionControls.hidden = true;
  elements.sessionIdentity.textContent = "";
  elements.jobSearch.value = "";
  elements.candidateSearch.value = "";
  elements.selectionSearch.value = "";
  renderDashboard({ builds: [], jobs: [], selections: [] });
  byId("job-list").replaceChildren();
  byId("candidate-list").replaceChildren();
  byId("selection-list").replaceChildren();
  byId("job-filter-count").textContent = "0件";
  byId("candidate-filter-count").textContent = "0件";
  byId("selection-filter-count").textContent = "0件";
  redrawDraft();
  showDetail(false);
  notice("切断しました。tokenは画面から破棄されました。", "success");
});
elements.jobSearch.addEventListener("input", drawLists);
elements.candidateSearch.addEventListener("input", redrawCandidates);
elements.selectionSearch.addEventListener("input", drawLists);
byId("selection-scope").addEventListener("change", redrawDraft);
for (const tab of document.querySelectorAll(".tab")) {
  tab.addEventListener("click", () => setTab(tab.dataset.tab));
}
redrawDraft();
setBusy(false);

installPkceLogin();
