import { ApiError, clearToken, setToken } from "./api.js";
import { installPkceLogin } from "./pkce.js";
import {
  createCampaign, createCampaignBatch, createComparison, createConformanceJob, createExperiment,
  createModelDriftReview, createReviewAction, createRun, updateReviewAction,
  retryCampaignFinalization,
  loadAnalysisDashboard,
} from "./analysis_api.js";
import {
  renderCampaignDrift, renderCampaignResultMatrix, renderCampaignStability,
} from "./analysis_campaign_results.js";
import {
  renderModelReviewOptions, renderModelReviews, setSuggestedReviewVersion,
} from "./analysis_model_reviews.js";
import {
  fillReviewActionUpdate, renderReviewActionOptions, renderReviewActions,
  toggleCompletionEvidence,
} from "./analysis_review_actions.js";
import {
  renderCampaignOptions, renderCampaigns, renderComparisonCreated, renderDefaults,
  renderExperiments, renderFormOptions, renderModels, renderRecentComparisons, renderRuns, renderSummary,
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
  else if (error instanceof ApiError && error.status === 403) notice("この操作に必要な権限がありません。", "error");
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
  const campaignSnapshots = new Set([
    ...document.querySelectorAll("#campaign-snapshot-options input:checked"),
  ].map((item) => item.dataset.snapshotId));
  const campaignModels = new Set([...document.querySelectorAll("#campaign-model-options input:checked")]
    .map((item) => `${item.dataset.providerId}\u0000${item.dataset.modelId}`));
  renderSummary(bundle);
  renderWorkerStatus(bundle.workerStatus);
  renderFormOptions(bundle, {
    snapshotId: byId("snapshot-select").value,
    providerId: byId("provider-select").value,
  });
  renderCampaignOptions(bundle, campaignSnapshots, campaignModels);
  renderCampaigns(bundle.campaigns, selectCampaignRuns, retryCampaign);
  renderCampaignStability(bundle.campaignResults.model_stability);
  renderCampaignDrift(bundle.campaignResults.model_drift);
  renderModelReviewOptions(bundle.campaignResults.model_drift, bundle.modelReviews);
  renderModelReviews(bundle.modelReviews);
  renderReviewActionOptions(bundle.modelReviews, bundle.reviewActions);
  renderReviewActions(bundle.reviewActions, bundle.reviewActionEvents);
  renderCampaignResultMatrix(bundle.campaignResults);
  drawDefaults();
  renderExperiments(
    bundle.experiments, bundle.snapshots, bundle.providers, bundle.conformances,
    bundle.conformanceJobs, registerRun, registerConformance,
  );
  renderRuns(bundle.runs, bundle.experiments, state.selectedRuns, runContext, toggleRun);
  renderRecentComparisons(bundle.comparisons);
  byId("comparison-submit").disabled = !state.selectedRuns.size;
}

function selectCampaignRuns(campaign) {
  const eligible = campaign.entries.filter((entry) => {
    const run = state.dashboard.runs.find((item) => item.run_id === entry.run_id);
    return run && runContext(run).eligible;
  });
  state.selectedRuns = new Set(eligible.map((item) => item.run_id));
  renderRuns(
    state.dashboard.runs, state.dashboard.experiments, state.selectedRuns,
    runContext, toggleRun,
  );
  byId("comparison-submit").disabled = !state.selectedRuns.size || state.busy;
  if (eligible.length) notice(`${eligible.length}件の完了runを比較対象に設定しました。`, "success");
  else notice("比較できる完了runはまだありません。処理完了後にもう一度選択してください。", "error");
}

function schedulePoll() {
  window.clearTimeout(pollTimer);
  if (
    state.dashboard?.runs.some((item) => ["QUEUED", "RUNNING"].includes(item.status))
    || state.dashboard?.conformanceJobs.some((item) => ["QUEUED", "RUNNING"].includes(item.status))
    || state.dashboard?.campaigns.some((item) => (
      item.status === "RUNNING" || ["WAITING", "RUNNING"].includes(item.finalization?.status)
    ))
  ) {
    pollTimer = window.setTimeout(() => refreshDashboard(true), 5000);
  }
}

byId("campaign-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const snapshotIds = [
    ...document.querySelectorAll("#campaign-snapshot-options input:checked"),
  ].map((item) => item.dataset.snapshotId);
  const models = [...document.querySelectorAll("#campaign-model-options input:checked")].map((item) => ({
    provider_id: item.dataset.providerId, model_id: item.dataset.modelId,
  }));
  if (!snapshotIds.length) {
    notice("データセットを1件以上選択してください。", "error");
    return;
  }
  if (models.length < 2) {
    notice("比較するモデルを2件以上選択してください。", "error");
    return;
  }
  setBusy(true);
  notice(`${snapshotIds.length}件のデータセットへ比較処理を登録しています。`);
  try {
    const payload = {
      request_key: crypto.randomUUID(),
      models,
      purpose: byId("campaign-purpose").value.trim(),
      mode: byId("campaign-mode").value,
      horizon: byId("campaign-mode").value === "horizon"
        ? Number(byId("campaign-horizon").value) : null,
      policy_version: "evaluation-v2.9",
    };
    const result = snapshotIds.length === 1
      ? await createCampaign({ ...payload, snapshot_id: snapshotIds[0] })
      : await createCampaignBatch({ ...payload, snapshot_ids: snapshotIds });
    setBusy(false);
    await refreshDashboard(true);
    const campaignCount = result.campaign_count || 1;
    notice(`${campaignCount}件の比較キャンペーンを開始しました。Workerが順次処理します。`, "success");
  } catch (error) { handleError(error); } finally { setBusy(false); }
});

byId("model-review-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (state.busy) return;
  setBusy(true);
  notice("精度変化の調査・判断を記録しています。");
  try {
    await createModelDriftReview({
      comparison_profile_id: byId("model-review-profile").value,
      decision_version: byId("model-review-version").value.trim(),
      conclusion: byId("model-review-conclusion").value,
      reason: byId("model-review-reason").value.trim(),
      action: byId("model-review-action").value.trim(),
    });
    byId("model-review-version").value = "";
    byId("model-review-reason").value = "";
    byId("model-review-action").value = "";
    setBusy(false);
    await refreshDashboard(true);
    notice("精度変化の調査・判断を版付き履歴へ記録しました。", "success");
  } catch (error) { handleError(error); } finally { setBusy(false); }
});

byId("review-action-create-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  setBusy(true);
  notice("レビュー対応タスクを登録しています。");
  try {
    await createReviewAction({
      review_id: byId("review-action-review").value,
      action_type: byId("review-action-type").value,
      title: byId("review-action-title").value.trim(),
      assignee: byId("review-action-assignee").value.trim(),
      due_date: byId("review-action-due").value,
      note: byId("review-action-note").value.trim(),
    });
    setBusy(false);
    await refreshDashboard(true);
    notice("対応タスクを登録しました。", "success");
  } catch (error) { handleError(error); } finally { setBusy(false); }
});

byId("review-action-update-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  setBusy(true);
  notice("対応タスクの履歴を追加しています。");
  try {
    await updateReviewAction(byId("review-action-update-id").value, {
      expected_revision: Number(byId("review-action-update-revision").value),
      status: byId("review-action-update-status").value,
      assignee: byId("review-action-update-assignee").value.trim(),
      due_date: byId("review-action-update-due").value,
      note: byId("review-action-update-note").value.trim(),
      completion_evidence: byId("review-action-update-status").value === "COMPLETED"
        ? byId("review-action-update-evidence").value.trim() : null,
    });
    setBusy(false);
    await refreshDashboard(true);
    notice("対応タスクへ変更履歴を追加しました。", "success");
  } catch (error) { handleError(error); } finally { setBusy(false); }
});

async function retryCampaign(campaignId) {
  if (state.busy) return;
  setBusy(true);
  notice("自動比較を再登録しています。");
  try {
    await retryCampaignFinalization(campaignId);
    setBusy(false);
    await refreshDashboard(true);
    notice("自動比較を再登録しました。Workerが順次処理します。", "success");
  } catch (error) { handleError(error); } finally { setBusy(false); }
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
byId("campaign-mode").addEventListener("change", () => {
  byId("campaign-horizon-field").hidden = byId("campaign-mode").value === "primary";
});
byId("model-review-profile").addEventListener("change", () => {
  setSuggestedReviewVersion(state.dashboard?.modelReviews || []);
});
byId("review-action-update-id").addEventListener("change", () => {
  fillReviewActionUpdate(state.dashboard?.reviewActions || []);
});
byId("review-action-update-status").addEventListener("change", toggleCompletionEvidence);
setBusy(false);
installPkceLogin();
