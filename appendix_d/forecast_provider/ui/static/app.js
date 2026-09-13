import { installPkceLogin } from "./pkce.js";
import {
  ApiError,
  clearToken,
  createAcceptanceDecision,
  createAdoption,
  createExport,
  downloadExport,
  loadComparison,
  loadDashboard,
  setToken,
} from "./api.js";
import { parseList } from "./format.js";
import {
  renderComparisonList,
  renderDetail,
  renderSummary,
  setTab,
  showDetail,
} from "./render.js";

const state = {
  dashboard: null,
  selectedId: null,
  selected: null,
  busy: false,
  permissions: new Set(),
};

const elements = {
  connectionForm: document.getElementById("connection-form"),
  sessionControls: document.getElementById("session-controls"),
  sessionIdentity: document.getElementById("session-identity"),
  token: document.getElementById("api-token"),
  notice: document.getElementById("notice"),
  refresh: document.getElementById("refresh-button"),
  disconnect: document.getElementById("disconnect-button"),
  search: document.getElementById("comparison-search"),
  exportForm: document.getElementById("export-form"),
  acceptanceDecisionForm: document.getElementById("acceptance-decision-form"),
  adoptionForm: document.getElementById("adoption-form"),
  decision: document.getElementById("adoption-decision"),
  adoptedFields: document.getElementById("adopted-fields"),
};

function notice(message, tone = "") {
  elements.notice.className = `notice${tone ? ` ${tone}` : ""}`;
  elements.notice.textContent = message;
}

function setBusy(value) {
  state.busy = value;
  for (const button of document.querySelectorAll("button")) {
    const permission = button.dataset.permission;
    button.disabled = value || (permission && !state.permissions.has(permission));
  }
  document.body.setAttribute("aria-busy", String(value));
}

function showSession(session) {
  state.permissions = new Set(session.permissions);
  elements.sessionIdentity.textContent = `${session.subject} / ${session.roles.join(", ")}`;
}

function recordsFor(comparisonId) {
  return {
    exports: state.dashboard.exports.filter((item) => item.comparison_id === comparisonId),
    adoptions: state.dashboard.adoptions.filter(
      (item) => item.comparison_id === comparisonId,
    ),
  };
}

function drawComparisonList() {
  if (!state.dashboard) return;
  renderComparisonList(
    state.dashboard.comparisons,
    state.selectedId,
    elements.search.value,
    selectComparison,
  );
}

async function selectComparison(comparisonId) {
  if (state.busy || comparisonId === state.selectedId) return;
  setBusy(true);
  notice("比較の証跡と採用条件を確認しています。");
  try {
    state.selected = await loadComparison(comparisonId);
    state.selectedId = comparisonId;
    drawComparisonList();
    renderDetail(state.selected, recordsFor(comparisonId), handleDownload);
    updateDecisionFields();
    setTab("overview");
    notice("比較結果を読み込みました。", "success");
  } catch (error) {
    handleError(error);
  } finally {
    setBusy(false);
  }
}

async function refreshDashboard(preferredId = state.selectedId) {
  setBusy(true);
  notice("台帳を更新しています。");
  try {
    state.dashboard = await loadDashboard();
    showSession(state.dashboard.session);
    renderSummary(state.dashboard);
    const available = state.dashboard.comparisons.some(
      (item) => item.comparison_id === preferredId,
    );
    state.selectedId = null;
    state.selected = null;
    showDetail(false);
    drawComparisonList();
    const nextId = available ? preferredId : state.dashboard.comparisons[0]?.comparison_id;
    if (nextId) {
      setBusy(false);
      await selectComparison(nextId);
    } else {
      notice("接続しました。保存済みの比較はまだありません。", "success");
    }
  } catch (error) {
    handleError(error);
  } finally {
    setBusy(false);
  }
}

function handleError(error) {
  if (error instanceof ApiError && error.status === 401) {
    notice("認証できません。API tokenを確認してください。", "error");
  } else {
    notice(error.message || "処理に失敗しました。", "error");
  }
}

async function handleDownload(record) {
  if (state.busy) return;
  setBusy(true);
  notice("CSVのchecksumを確認して取得しています。");
  try {
    await downloadExport(record);
    notice("CSVを取得しました。", "success");
  } catch (error) {
    handleError(error);
  } finally {
    setBusy(false);
  }
}

async function handleExport(event) {
  event.preventDefault();
  if (!state.selectedId || state.busy) return;
  setBusy(true);
  notice("比較CSVを発行しています。");
  try {
    await createExport(state.selectedId, {
      export_version: document.getElementById("export-version").value.trim(),
      baseline_run_id: document.getElementById("export-baseline").value,
    });
    notice("比較CSVを発行しました。", "success");
    setBusy(false);
    await refreshDashboard(state.selectedId);
    setTab("exports");
  } catch (error) {
    handleError(error);
  } finally {
    setBusy(false);
  }
}

function adoptionPayload() {
  const decision = elements.decision.value;
  const adopted = decision === "ADOPTED";
  return {
    adoption_version: document.getElementById("adoption-version").value.trim(),
    comparison_id: state.selectedId,
    acceptance_case_id: adopted ? document.getElementById("acceptance-case").value : null,
    decision,
    selected_run_id: adopted ? document.getElementById("selected-run").value : null,
    fallback_run_id: adopted ? document.getElementById("fallback-run").value : null,
    target: {
      selection_version: state.selected.context.selection_version,
      canonical_product_ids: parseList(document.getElementById("product-ids").value),
      center_ids: parseList(document.getElementById("center-ids").value),
      trial_period_days: Number(document.getElementById("trial-days").value),
    },
    reason: document.getElementById("adoption-reason").value.trim(),
  };
}

async function handleAdoption(event) {
  event.preventDefault();
  if (!state.selectedId || state.busy) return;
  const payload = adoptionPayload();
  if (
    payload.decision === "ADOPTED"
    && payload.selected_run_id === payload.fallback_run_id
  ) {
    notice("採用runとfallback runは別のrunを選択してください。", "error");
    return;
  }
  setBusy(true);
  notice("比較と受入証跡を再検証して判断を保存しています。");
  try {
    await createAdoption(payload);
    notice("採用判断を保存しました。", "success");
    setBusy(false);
    await refreshDashboard(state.selectedId);
    setTab("adoption");
  } catch (error) {
    handleError(error);
  } finally {
    setBusy(false);
  }
}

async function handleAcceptanceDecision(event) {
  event.preventDefault();
  if (!state.selectedId || state.busy) return;
  setBusy(true);
  notice("受入caseの業務判断を保存しています。");
  try {
    await createAcceptanceDecision(document.getElementById("decision-case").value, {
      decision_version: document
        .getElementById("acceptance-decision-version")
        .value.trim(),
      decision: document.getElementById("acceptance-decision").value,
      reason: document.getElementById("acceptance-reason").value.trim(),
    });
    notice("受入caseの業務判断を保存しました。", "success");
    setBusy(false);
    await refreshDashboard(state.selectedId);
    setTab("adoption");
  } catch (error) {
    handleError(error);
  } finally {
    setBusy(false);
  }
}

function updateDecisionFields() {
  const adopted = elements.decision.value === "ADOPTED";
  elements.adoptedFields.hidden = !adopted;
  for (const select of elements.adoptedFields.querySelectorAll("select")) {
    select.required = adopted;
    select.disabled = !adopted;
  }
}

elements.connectionForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  setToken(elements.token.value);
  await refreshDashboard();
  if (state.dashboard) {
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
  state.permissions = new Set();
  elements.connectionForm.hidden = false;
  elements.sessionControls.hidden = true;
  elements.search.value = "";
  elements.sessionIdentity.textContent = "";
  renderSummary({ comparisons: [], acceptances: [], exports: [], adoptions: [] });
  replaceComparisonListAfterDisconnect();
  showDetail(false);
  notice("切断しました。tokenは画面から破棄されました。", "success");
});

function replaceComparisonListAfterDisconnect() {
  document.getElementById("comparison-filter-count").textContent = "0件";
  document.getElementById("comparison-list").replaceChildren();
}

elements.search.addEventListener("input", drawComparisonList);
elements.exportForm.addEventListener("submit", handleExport);
elements.acceptanceDecisionForm.addEventListener(
  "submit",
  handleAcceptanceDecision,
);
elements.adoptionForm.addEventListener("submit", handleAdoption);
elements.decision.addEventListener("change", updateDecisionFields);
for (const tab of document.querySelectorAll(".tab")) {
  tab.addEventListener("click", () => setTab(tab.dataset.tab));
}
updateDecisionFields();

installPkceLogin();
