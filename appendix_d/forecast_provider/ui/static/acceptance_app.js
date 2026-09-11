import { ApiError, clearToken, setToken } from "./api.js";
import {
  createAcceptanceCase,
  createAcceptanceDecision,
  loadAcceptanceCase,
  loadAcceptanceDashboard,
} from "./acceptance_api.js";
import {
  renderCaseDetail,
  renderCases,
  renderDashboard,
  renderProductPreview,
  setTab,
  showDetail,
} from "./acceptance_render.js";

const state = {
  dashboard: null,
  selectedId: null,
  selected: null,
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
  caseSearch: byId("case-search"),
  selection: byId("case-selection"),
  build: byId("case-build"),
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

function findSelection() {
  return state.dashboard?.selections.find((item) => item.selection_id === elements.selection.value);
}

function findBuild() {
  return state.dashboard?.builds.find((item) => item.build_id === elements.build.value);
}

function syncBuild() {
  const build = findBuild();
  if (build) byId("case-availability").value = build.definition.availability_mode;
}

function syncSelection({ chooseBuild = false } = {}) {
  const selection = findSelection();
  renderProductPreview(selection);
  if (!selection || !chooseBuild || !state.dashboard) return;
  const match = state.dashboard.builds.find((build) =>
    build.status === "SUCCEEDED"
      && build.definition.selection_version === selection.definition.selection_version,
  );
  if (match) elements.build.value = match.build_id;
  syncBuild();
}

function drawCases() {
  if (!state.dashboard) return;
  renderCases(
    state.dashboard.cases,
    state.selectedId,
    elements.caseSearch.value,
    selectCase,
  );
}

async function selectCase(caseId) {
  if (state.busy || caseId === state.selectedId) return;
  setBusy(true);
  notice("受入caseの技術証跡を読み込んでいます。");
  try {
    state.selectedId = caseId;
    drawCases();
    state.selected = await loadAcceptanceCase(caseId);
    renderCaseDetail(state.selected);
    setTab("checks");
    notice(
      state.selected.record.status === "SUCCEEDED"
        ? "技術判定と業務判断履歴を読み込みました。"
        : "受入Workerの完了後に更新してください。",
      state.selected.record.status === "SUCCEEDED" ? "success" : "",
    );
  } catch (error) {
    state.selectedId = null;
    state.selected = null;
    showDetail(false);
    drawCases();
    handleError(error);
  } finally {
    setBusy(false);
  }
}

async function refreshDashboard(preferredId = state.selectedId) {
  setBusy(true);
  notice("実データ受入台帳を更新しています。");
  try {
    const dashboard = await loadAcceptanceDashboard();
    state.dashboard = dashboard;
    state.permissions = new Set(dashboard.session.permissions);
    elements.sessionIdentity.textContent = `${dashboard.session.subject} / ${dashboard.session.roles.join(", ")}`;
    renderDashboard(dashboard);
    syncSelection();
    const available = dashboard.cases.some((record) => record.case_id === preferredId);
    state.selectedId = null;
    state.selected = null;
    showDetail(false);
    drawCases();
    const nextId = available ? preferredId : dashboard.cases[0]?.case_id;
    if (nextId) {
      setBusy(false);
      await selectCase(nextId);
    } else {
      notice("接続しました。受入caseはまだありません。", "success");
    }
    return true;
  } catch (error) {
    handleError(error);
    return false;
  } finally {
    setBusy(false);
  }
}

byId("case-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (state.busy) return;
  const selection = findSelection();
  if (!selection) {
    notice("INITIAL選定版を選択してください。", "error");
    return;
  }
  setBusy(true);
  notice("日次build、3〜5品目、受入条件を検証しています。");
  try {
    const created = await createAcceptanceCase({
      acceptance_version: value("case-version"),
      daily_build_id: value("case-build"),
      data_kind: value("case-data-kind"),
      expected_product_ids: selection.definition.items.map((item) => item.canonical_product_id),
      required_availability_mode: value("case-availability"),
      min_usable_days_per_series: Number(value("case-min-days")),
      max_missing_rate: Number(value("case-missing-rate")),
      max_partial_invalid_rate: Number(value("case-invalid-rate")),
      purpose: value("case-purpose"),
    });
    setBusy(false);
    await refreshDashboard(created.id);
    notice("受入caseを登録しました。Worker完了後に更新してください。", "success");
  } catch (error) {
    handleError(error);
  } finally {
    setBusy(false);
  }
});

byId("decision-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!state.selectedId || state.busy) return;
  setBusy(true);
  notice("技術判定と業務判断条件を再検証しています。");
  try {
    await createAcceptanceDecision(state.selectedId, {
      decision_version: value("decision-version"),
      decision: value("decision-value"),
      reason: value("decision-reason"),
    });
    const selected = state.selectedId;
    setBusy(false);
    await refreshDashboard(selected);
    setTab("decision");
    notice("業務判断を保存し、追記型履歴を再読込しました。", "success");
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
  state.permissions = new Set();
  elements.connectionForm.hidden = false;
  elements.sessionControls.hidden = true;
  elements.sessionIdentity.textContent = "";
  elements.caseSearch.value = "";
  renderDashboard({ builds: [], selections: [], cases: [] });
  renderProductPreview(null);
  byId("case-list").replaceChildren();
  byId("check-list").replaceChildren();
  byId("decision-list").replaceChildren();
  byId("case-filter-count").textContent = "0件";
  showDetail(false);
  setBusy(false);
  notice("切断しました。tokenは画面から破棄されました。", "success");
});
elements.caseSearch.addEventListener("input", drawCases);
elements.selection.addEventListener("change", () => syncSelection({ chooseBuild: true }));
elements.build.addEventListener("change", syncBuild);
for (const tab of document.querySelectorAll(".tab")) {
  tab.addEventListener("click", () => setTab(tab.dataset.tab));
}
renderProductPreview(null);
setBusy(false);
