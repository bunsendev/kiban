import { ApiError, clearToken, setToken } from "./api.js";
import { installPkceLogin } from "./pkce.js";
import {
  createComparison, createConformanceJob, createExperiment, createRun, loadAnalysisDashboard,
} from "./analysis_api.js";
import {
  renderComparisonCreated, renderDefaults, renderExperiments, renderFormOptions,
  renderModels, renderRecentComparisons, renderRuns, renderSummary,
  renderWorkerStatus,
} from "./analysis_render.js";
import { runContext as resolveRunContext } from "./analysis_rules.js";

const state = { dashboard: null, permissions: new Set(), selectedRuns: new Set(), busy: false };
const byId = (id) => document.getElementById(id);
let pollTimer = null;

function notice(message, tone = "") {
  byId("notice").className = `notice${tone ? ` ${tone}` : ""}`;
  byId("notice").textContent = message;
}

function setBusy(busy) {
  state.busy = busy;
  document.body.setAttribute("aria-busy", String(busy));
  for (const button of document.querySelectorAll("button")) {
    const permission = button.dataset.permission;
    button.disabled = busy || button.dataset.locked === "true"
      || (permission && !state.permissions.has(permission));
  }
  if (!busy && byId("comparison-submit")) {
    byId("comparison-submit").disabled = (
      !state.selectedRuns.size || !state.permissions.has("ANALYZE")
    );
  }
}

function handleError(error) {
  if (error instanceof ApiError && error.status === 401) notice("認証できません。API tokenを確認してください。", "error");
  else if (error instanceof ApiError && error.status === 403) notice("この操作にはANALYZE権限が必要です。", "error");
  else notice(error.message || "処理に失敗しました。", "error");
}

function currentProvider() {
  return state.dashboard?.providers.find((item) => item.provider_id === byId("provider-select").value);
}

function currentSnapshot() {
  return state.dashboard?.snapshots.find((item) => item.snapshot_id === byId("snapshot-select").value);
}

function drawDefaults() {
  const provider = currentProvider();
  renderModels(provider, byId("model-select").value);
  renderDefaults(provider, currentSnapshot(), byId("model-select").value);
  setBusy(state.busy);
}

function runContext(run) {
  return resolveRunContext(state.dashboard, run);
}

function drawDashboard() {
  const bundle = state.dashboard;
  renderSummary(bundle);
  renderWorkerStatus(bundle.workerStatus);
  renderFormOptions(bundle, {
    snapshotId: byId("snapshot-select").value,
    providerId: byId("provider-select").value,
  });
  drawDefaults();
  renderExperiments(
    bundle.experiments, bundle.snapshots, bundle.providers, bundle.conformances,
    bundle.conformanceJobs, registerRun, registerConformance,
  );
  renderRuns(bundle.runs, bundle.experiments, state.selectedRuns, runContext, toggleRun);
  renderRecentComparisons(bundle.comparisons);
  byId("comparison-submit").disabled = !state.selectedRuns.size;
}

function schedulePoll() {
  window.clearTimeout(pollTimer);
  if (
    state.dashboard?.runs.some((item) => ["QUEUED", "RUNNING"].includes(item.status))
    || state.dashboard?.conformanceJobs.some((item) => ["QUEUED", "RUNNING"].includes(item.status))
  ) {
    pollTimer = window.setTimeout(() => refreshDashboard(true), 5000);
  }
}

async function registerConformance(experimentId) {
  if (state.busy) return;
  setBusy(true);
  notice("Provider適合試験を登録しています。");
  try {
    const created = await createConformanceJob(experimentId);
    setBusy(false);
    await refreshDashboard(true);
    notice(`適合試験を登録しました（${created.status}）。Provider別Workerが人工データで検証します。`, "success");
  } catch (error) { handleError(error); } finally { setBusy(false); }
}

async function refreshDashboard(silent = false) {
  if (state.busy) return;
  setBusy(true);
  if (!silent) notice("分析実行状況を更新しています。");
  try {
    state.dashboard = await loadAnalysisDashboard();
    state.permissions = new Set(state.dashboard.session.permissions);
    state.selectedRuns = new Set([...state.selectedRuns].filter((id) => (
      state.dashboard.runs.some((run) => run.run_id === id) && runContext(
        state.dashboard.runs.find((run) => run.run_id === id),
      ).eligible
    )));
    byId("session-identity").textContent = `${state.dashboard.session.subject} / ${state.dashboard.session.roles.join(", ")}`;
    drawDashboard();
    if (!silent) notice("分析実行ワークスペースを更新しました。", "success");
  } catch (error) {
    handleError(error);
  } finally {
    setBusy(false);
    schedulePoll();
  }
}

async function registerRun(experimentId) {
  if (state.busy) return;
  setBusy(true);
  notice("runを登録しています。");
  try {
    const created = await createRun(experimentId);
    setBusy(false);
    await refreshDashboard(true);
    notice(`runを登録しました（${created.status}）。該当Provider Workerが順次処理します。`, "success");
  } catch (error) { handleError(error); } finally { setBusy(false); }
}

function toggleRun(runId, checked) {
  const context = runContext(state.dashboard.runs.find((item) => item.run_id === runId));
  if (checked) {
    const selected = [...state.selectedRuns].map((id) => runContext(
      state.dashboard.runs.find((item) => item.run_id === id),
    ));
    if (selected.some((item) => item.experiment.snapshot_id !== context.experiment.snapshot_id)) {
      notice("同じdataset snapshotのrunだけを1つの比較へ選択できます。", "error");
      drawDashboard();
      return;
    }
    state.selectedRuns.add(runId);
  } else state.selectedRuns.delete(runId);
  renderRuns(state.dashboard.runs, state.dashboard.experiments, state.selectedRuns, runContext, toggleRun);
  byId("comparison-submit").disabled = !state.selectedRuns.size || state.busy;
}

byId("experiment-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const provider = currentProvider();
  if (!provider?.experiment_defaults) return;
  const defaults = provider.experiment_defaults;
  setBusy(true);
  notice("実験条件を保存しています。");
  try {
    await createExperiment({
      snapshot_id: byId("snapshot-select").value,
      provider_id: provider.provider_id,
      model_name: byId("model-select").value,
      params: defaults.params,
      interval_levels: byId("interval-preset").value.split(",").filter(Boolean).map(Number),
      preprocessing_version: defaults.preprocessing_version,
      seed: Number(byId("seed").value),
      resource_profile: byId("resource-profile").value.trim(),
      training_policy: byId("training-policy").value,
    });
    setBusy(false);
    await refreshDashboard(true);
    notice("実験条件を保存しました。次に「この条件で実行登録」を押してください。", "success");
  } catch (error) { handleError(error); } finally { setBusy(false); }
});

byId("comparison-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const runIds = [...state.selectedRuns];
  if (!runIds.length) return;
  const contexts = runIds.map((id) => runContext(state.dashboard.runs.find((run) => run.run_id === id)));
  const mode = byId("comparison-mode").value;
  setBusy(true);
  notice("保存済みrunから比較結果を作成しています。");
  try {
    const comparison = await createComparison({
      run_ids: runIds,
      conformance_ids: Object.fromEntries(runIds.map((id, index) => [id, contexts[index].conformance.conformance_id])),
      truth_snapshot_id: contexts[0].experiment.snapshot_id,
      mode,
      horizon: mode === "horizon" ? Number(byId("comparison-horizon").value) : null,
      policy_version: "evaluation-v2.9",
      purpose: byId("comparison-purpose").value.trim(),
    });
    renderComparisonCreated(comparison);
    setBusy(false);
    await refreshDashboard(true);
    notice("比較結果を作成しました。比較・採用画面で指標と系譜を確認できます。", "success");
  } catch (error) { handleError(error); } finally { setBusy(false); }
});

byId("connection-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  setToken(byId("api-token").value);
  await refreshDashboard();
  if (state.dashboard) {
    byId("connection-form").hidden = true;
    byId("session-controls").hidden = false;
    byId("api-token").value = "";
  }
});
byId("refresh-button").addEventListener("click", () => refreshDashboard());
byId("disconnect-button").addEventListener("click", () => {
  window.clearTimeout(pollTimer);
  clearToken();
  state.dashboard = null;
  state.permissions = new Set();
  state.selectedRuns.clear();
  byId("connection-form").hidden = false;
  byId("session-controls").hidden = true;
  byId("session-identity").textContent = "";
  notice("切断しました。tokenは画面から破棄されました。", "success");
});
byId("provider-select").addEventListener("change", drawDefaults);
byId("snapshot-select").addEventListener("change", () => (
  renderDefaults(currentProvider(), currentSnapshot(), byId("model-select").value)
));
byId("model-select").addEventListener("change", () => (
  renderDefaults(currentProvider(), currentSnapshot(), byId("model-select").value)
));
byId("comparison-mode").addEventListener("change", () => {
  byId("comparison-horizon-field").hidden = byId("comparison-mode").value === "primary";
});
setBusy(false);
installPkceLogin();
