import { ApiError, clearToken, setToken } from "./api.js";
import { installPkceLogin } from "./pkce.js";
import { createUnitPrice, loadResourceDashboard, loadRunResources } from "./resource_cost_api.js";
import {
  RESOURCE_METRICS, renderPrices, renderRunDetail, renderRunList,
  renderSummary, showDetail,
} from "./resource_cost_render.js";

const state = {
  dashboard: null,
  selectedId: null,
  selectedResources: null,
  permissions: new Set(),
  busy: false,
};
const byId = (id) => document.getElementById(id);
const value = (id) => byId(id).value.trim();
const elements = {
  connectionForm: byId("connection-form"), token: byId("api-token"),
  sessionControls: byId("session-controls"), sessionIdentity: byId("session-identity"),
  refresh: byId("refresh-button"), disconnect: byId("disconnect-button"),
  search: byId("run-search"), status: byId("run-status"), notice: byId("notice"),
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
    notice("単価の登録にはADMIN権限が必要です。", "error");
  } else {
    notice(error.message || "処理に失敗しました。", "error");
  }
}

function selectedRun() {
  return state.dashboard?.runs.find((item) => item.run_id === state.selectedId);
}

function drawRuns() {
  if (!state.dashboard) return;
  renderRunList(
    state.dashboard.runs, state.selectedId, elements.search.value,
    elements.status.value, selectRun,
  );
}

async function selectRun(runId) {
  if (state.busy || runId === state.selectedId) return;
  setBusy(true);
  notice("runの資源計測と適用単価を読み込んでいます。");
  try {
    state.selectedId = runId;
    state.selectedResources = await loadRunResources(runId);
    drawRuns();
    renderRunDetail(selectedRun(), state.selectedResources);
    notice("runの資源・費用を読み込みました。", "success");
  } catch (error) {
    state.selectedId = null;
    handleError(error);
  } finally {
    setBusy(false);
  }
}

async function refreshDashboard(preferredId = state.selectedId) {
  setBusy(true);
  notice("資源・費用台帳を更新しています。");
  try {
    state.dashboard = await loadResourceDashboard();
    state.permissions = new Set(state.dashboard.session.permissions);
    elements.sessionIdentity.textContent = `${state.dashboard.session.subject} / ${state.dashboard.session.roles.join(", ")}`;
    renderSummary(state.dashboard);
    renderPrices(state.dashboard.prices);
    const available = state.dashboard.runs.some((item) => item.run_id === preferredId);
    state.selectedId = null;
    state.selectedResources = null;
    showDetail(false);
    drawRuns();
    const nextId = available ? preferredId : state.dashboard.runs[0]?.run_id;
    if (nextId) {
      setBusy(false);
      await selectRun(nextId);
    } else {
      notice("接続しました。runはまだありません。", "success");
    }
  } catch (error) {
    handleError(error);
  } finally {
    setBusy(false);
  }
}

byId("price-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (state.busy) return;
  setBusy(true);
  notice("単価を登録し、runの費用を再計算しています。");
  try {
    await createUnitPrice({
      provider_id: value("price-provider"), metric: value("price-metric"),
      unit_price: value("price-amount"), currency: value("price-currency").toUpperCase(),
      retrieved_on: value("price-date"), source_ref: value("price-source"),
    });
    byId("price-amount").value = "";
    byId("price-source").value = "";
    const selected = state.selectedId;
    setBusy(false);
    await refreshDashboard(selected);
    notice("単価を登録し、表示中の費用を更新しました。", "success");
  } catch (error) {
    handleError(error);
  } finally {
    setBusy(false);
  }
});

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
  state.selectedResources = null;
  state.permissions = new Set();
  elements.connectionForm.hidden = false;
  elements.sessionControls.hidden = true;
  elements.sessionIdentity.textContent = "";
  elements.search.value = "";
  elements.status.value = "";
  byId("run-list").replaceChildren();
  byId("price-rows").replaceChildren();
  byId("run-filter-count").textContent = "0件";
  showDetail(false);
  notice("切断しました。tokenは画面から破棄されました。", "success");
});
elements.search.addEventListener("input", drawRuns);
elements.status.addEventListener("change", drawRuns);

byId("price-metric").replaceChildren(...RESOURCE_METRICS.map(([metric, label]) => {
  const option = document.createElement("option");
  option.value = metric;
  option.textContent = label;
  return option;
}));
byId("price-date").value = new Date().toISOString().slice(0, 10);
setBusy(false);
installPkceLogin();
