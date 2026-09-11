import { ApiError, clearToken, setToken } from "./api.js";
import {
  createHandlingPeriod,
  loadDailyBuild,
  loadReadinessDashboard,
} from "./readiness_api.js";
import {
  renderBuildDetail,
  renderBuildList,
  renderDashboard,
  renderPeriods,
  setTab,
  showDetail,
} from "./readiness_render.js";

const state = {
  dashboard: null,
  selectedId: null,
  selected: null,
  permissions: new Set(),
  busy: false,
  filters: { state: "", canonical_product_id: "", center_id: "", limit: 100, offset: 0 },
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
  periodSearch: byId("period-search"),
  buildSearch: byId("build-search"),
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
  renderPeriods(state.dashboard.periods, elements.periodSearch.value);
  renderBuildList(
    state.dashboard.builds,
    state.selectedId,
    elements.buildSearch.value,
    selectBuild,
  );
}

async function loadSelected(tab = null) {
  if (!state.selectedId) return;
  state.selected = await loadDailyBuild(state.selectedId, state.filters);
  renderBuildDetail(state.selected);
  if (tab) setTab(tab);
}

async function selectBuild(buildId) {
  if (state.busy || buildId === state.selectedId) return;
  setBusy(true);
  notice("日次buildの完全性と欠測理由を集計しています。");
  try {
    state.selectedId = buildId;
    state.filters = { state: "", canonical_product_id: "", center_id: "", limit: 100, offset: 0 };
    byId("value-filter-form").reset();
    drawLists();
    await loadSelected("summary");
    notice("日次buildの判定を読み込みました。", "success");
  } catch (error) {
    state.selectedId = null;
    handleError(error);
  } finally {
    setBusy(false);
  }
}

async function refreshDashboard(preferredId = state.selectedId) {
  setBusy(true);
  notice("データ準備台帳を更新しています。");
  try {
    state.dashboard = await loadReadinessDashboard();
    state.permissions = new Set(state.dashboard.session.permissions);
    elements.sessionIdentity.textContent = `${state.dashboard.session.subject} / ${state.dashboard.session.roles.join(", ")}`;
    renderDashboard(state.dashboard);
    const available = state.dashboard.builds.some((build) => build.build_id === preferredId);
    state.selectedId = null;
    state.selected = null;
    showDetail(false);
    drawLists();
    const nextId = available ? preferredId : state.dashboard.builds[0]?.build_id;
    if (nextId) {
      setBusy(false);
      await selectBuild(nextId);
    } else {
      notice("接続しました。日次buildはまだありません。", "success");
    }
  } catch (error) {
    handleError(error);
  } finally {
    setBusy(false);
  }
}

byId("period-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (state.busy) return;
  setBusy(true);
  notice("商品と既存期間の競合を検証しています。");
  try {
    await createHandlingPeriod({
      canonical_product_id: value("period-product"),
      center_id: value("period-center"),
      valid_from: value("period-from"),
      valid_to: value("period-to") || null,
      status: value("period-status"),
      period_version: value("period-version"),
      basis: value("period-basis"),
    });
    const selected = state.selectedId;
    setBusy(false);
    await refreshDashboard(selected);
    notice("取扱期間を保存し、台帳を再読込しました。", "success");
  } catch (error) {
    handleError(error);
  } finally {
    setBusy(false);
  }
});

byId("value-filter-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!state.selectedId || state.busy) return;
  state.filters = {
    state: value("value-state"),
    canonical_product_id: value("value-product"),
    center_id: value("value-center"),
    limit: 100,
    offset: 0,
  };
  setBusy(true);
  notice("日次行を絞り込んでいます。");
  try {
    await loadSelected("values");
    notice("日次行を再読込しました。", "success");
  } catch (error) {
    handleError(error);
  } finally {
    setBusy(false);
  }
});

async function movePage(direction) {
  if (!state.selected || state.busy) return;
  const next = Math.max(0, state.filters.offset + direction * state.filters.limit);
  state.filters.offset = next;
  setBusy(true);
  try {
    await loadSelected("values");
  } catch (error) {
    handleError(error);
  } finally {
    setBusy(false);
  }
}

byId("previous-page").addEventListener("click", () => movePage(-1));
byId("next-page").addEventListener("click", () => movePage(1));
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
  elements.sessionIdentity.textContent = "";
  elements.periodSearch.value = "";
  elements.buildSearch.value = "";
  renderDashboard({ products: [], periods: [], builds: [] });
  byId("period-list").replaceChildren();
  byId("build-list").replaceChildren();
  byId("period-filter-count").textContent = "0件";
  byId("build-filter-count").textContent = "0件";
  showDetail(false);
  notice("切断しました。tokenは画面から破棄されました。", "success");
});
elements.periodSearch.addEventListener("input", drawLists);
elements.buildSearch.addEventListener("input", drawLists);
for (const tab of document.querySelectorAll(".tab")) {
  tab.addEventListener("click", () => setTab(tab.dataset.tab));
}
setBusy(false);
