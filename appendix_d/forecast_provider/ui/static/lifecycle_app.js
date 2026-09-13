import { installPkceLogin } from "./pkce.js";
import { ApiError, clearToken, setToken } from "./api.js";
import {
  assessTrial,
  completeCycle,
  createLifecyclePlan,
  failCycle,
  loadLifecycleDashboard,
  loadLifecyclePlan,
  promoteCycle,
  recordTrialForecast,
  rollbackChampion,
  runLifecycleSchedule,
} from "./lifecycle_api.js";
import {
  renderAdoptions,
  renderPlanDetail,
  renderPlanList,
  renderSummary,
  setTab,
  showDetail,
} from "./lifecycle_render.js";

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
  search: byId("plan-search"),
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

function drawPlanList() {
  if (!state.dashboard) return;
  renderPlanList(
    state.dashboard,
    state.selectedId,
    elements.search.value,
    selectPlan,
  );
}

async function selectPlan(planId) {
  if (state.busy || planId === state.selectedId) return;
  setBusy(true);
  notice("Lifecycleの追記履歴を読み込んでいます。");
  try {
    state.selected = await loadLifecyclePlan(planId);
    state.selectedId = planId;
    drawPlanList();
    renderPlanDetail(state.selected);
    setTab("cycles");
    notice("Lifecycle計画を読み込みました。", "success");
  } catch (error) {
    handleError(error);
  } finally {
    setBusy(false);
  }
}

async function refreshDashboard(preferredId = state.selectedId) {
  setBusy(true);
  notice("Lifecycle台帳を更新しています。");
  try {
    state.dashboard = await loadLifecycleDashboard();
    state.permissions = new Set(state.dashboard.session.permissions);
    elements.sessionIdentity.textContent = `${state.dashboard.session.subject} / ${state.dashboard.session.roles.join(", ")}`;
    renderSummary(state.dashboard);
    renderAdoptions(state.dashboard.adoptions);
    const available = state.dashboard.plans.some((plan) => plan.plan_id === preferredId);
    state.selectedId = null;
    state.selected = null;
    showDetail(false);
    drawPlanList();
    const nextId = available ? preferredId : state.dashboard.plans[0]?.plan_id;
    if (nextId) {
      setBusy(false);
      await selectPlan(nextId);
    } else {
      notice("接続しました。Lifecycle計画はまだありません。", "success");
    }
  } catch (error) {
    handleError(error);
  } finally {
    setBusy(false);
  }
}

async function runAction(message, callback, tab = null) {
  if (state.busy) return;
  setBusy(true);
  notice(message);
  try {
    await callback();
    const selected = state.selectedId;
    setBusy(false);
    await refreshDashboard(selected);
    if (tab && state.selected) setTab(tab);
    notice("操作結果を台帳へ保存し、最新状態を読み込みました。", "success");
  } catch (error) {
    handleError(error);
  } finally {
    setBusy(false);
  }
}

byId("plan-form").addEventListener("submit", (event) => {
  event.preventDefault();
  runAction("採用判断と月次Experimentを検証しています。", () =>
    createLifecyclePlan({
      plan_version: value("plan-version"),
      adoption_id: value("plan-adoption"),
      experiment_id: value("plan-experiment"),
      schedule_day: Number(value("plan-schedule-day")),
      schedule_time: value("plan-schedule-time"),
      timezone: value("plan-timezone"),
      trial_start_date: value("plan-trial-start"),
      metric: "wape_pct",
      minimum_improvement_pct: Number(value("plan-improvement")),
      maximum_failure_rate: Number(value("plan-failure-rate")),
      reason: value("plan-reason"),
    }),
  );
});

byId("schedule-button").addEventListener("click", () =>
  runAction("期限到来した月次cycleを登録しています。", runLifecycleSchedule, "cycles"),
);

byId("complete-cycle-form").addEventListener("submit", (event) => {
  event.preventDefault();
  runAction("champion/challenger比較を再検証しています。", () =>
    completeCycle(value("complete-cycle"), {
      challenger_run_id: value("challenger-run"),
      comparison_id: value("cycle-comparison"),
    }), "cycles");
});

byId("fail-cycle-form").addEventListener("submit", (event) => {
  event.preventDefault();
  runAction("cycle失敗を記録しています。", () =>
    failCycle(value("fail-cycle"), { failure_code: value("failure-code") }), "cycles");
});

byId("promote-form").addEventListener("submit", (event) => {
  event.preventDefault();
  runAction("最新revisionを照合してchallengerを昇格しています。", () =>
    promoteCycle(value("promote-cycle"), {
      expected_revision: state.selected.status.champion.revision,
      reason: value("promote-reason"),
    }), "cycles");
});

byId("rollback-form").addEventListener("submit", (event) => {
  event.preventDefault();
  runAction("最新revisionを照合してrollbackしています。", () =>
    rollbackChampion(state.selectedId, {
      target_run_id: value("rollback-target"),
      expected_revision: state.selected.status.champion.revision,
      reason: value("rollback-reason"),
    }), "history");
});

byId("forecast-form").addEventListener("submit", (event) => {
  event.preventDefault();
  runAction("最初の実績利用可能時刻より前か検証しています。", () =>
    recordTrialForecast(state.selectedId, {
      run_id: value("trial-run"),
      origin_date: value("trial-origin"),
    }), "trial");
});

byId("assessment-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const latest = state.selected.assessments.at(-1);
  runAction("trial期間、予測coverage、比較目的を検証しています。", () =>
    assessTrial(state.selectedId, {
      expected_revision: latest?.revision ?? 0,
      period_start: value("assessment-start"),
      period_end: value("assessment-end"),
      comparison_id: value("assessment-comparison"),
      decision: value("assessment-decision"),
      reason: value("assessment-reason"),
    }), "trial");
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
  state.selected = null;
  state.permissions = new Set();
  elements.connectionForm.hidden = false;
  elements.sessionControls.hidden = true;
  elements.sessionIdentity.textContent = "";
  elements.search.value = "";
  renderSummary({ plans: [], statuses: [] });
  byId("plan-list").replaceChildren();
  byId("plan-filter-count").textContent = "0件";
  showDetail(false);
  notice("切断しました。tokenは画面から破棄されました。", "success");
});

elements.search.addEventListener("input", drawPlanList);
for (const tab of document.querySelectorAll(".tab")) {
  tab.addEventListener("click", () => setTab(tab.dataset.tab));
}
byId("plan-trial-start").value = new Date().toISOString().slice(0, 10);
setBusy(false);

installPkceLogin();
