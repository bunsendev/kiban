import {
  renderEasyBatch,
  renderEasyFailure,
  renderEasyProgress,
  renderEasyReport,
} from "./easy_result.js";

export function createEasyResultFlow({ loadAnalysis, loadReport, telemetry, onReady }) {
  const state = {
    workItemId: null,
    resultKind: null,
    sourceMode: null,
    pollTimer: null,
    pollAttempts: 0,
  };

  function stop() {
    if (state.pollTimer !== null) window.clearTimeout(state.pollTimer);
    state.pollTimer = null;
    state.workItemId = null;
  }

  function schedule(delay = 2_000) {
    if (state.pollTimer !== null) window.clearTimeout(state.pollTimer);
    state.pollTimer = window.setTimeout(refresh, delay);
  }

  async function refresh() {
    state.pollTimer = null;
    if (!state.workItemId) return;
    state.pollAttempts += 1;
    try {
      const isBatch = state.resultKind === "batch";
      const result = await loadAnalysis(state.workItemId, isBatch);
      if (isBatch) {
        if (result.status !== "COMPLETED") {
          renderEasyProgress("RUNNING");
          if (state.pollAttempts < 60) schedule();
          return;
        }
        renderEasyBatch(result);
        telemetry.analysisResultReady(
          state.sourceMode, "batch", batchOutcome(result), state.workItemId,
        );
        state.workItemId = null;
        onReady();
        return;
      }
      if (["QUEUED", "RUNNING"].includes(result.status)) {
        renderEasyProgress(result.status);
        if (state.pollAttempts < 60) schedule();
        return;
      }
      if (result.status === "FAILED") {
        renderEasyFailure(
          "処理に失敗しました。受付番号を管理担当者へ連絡してください。",
          false,
        );
        telemetry.analysisResultFailed(
          state.sourceMode, "job", result.error_code, state.workItemId,
        );
        state.workItemId = null;
        return;
      }
      const report = await loadReport(result.report_sha256);
      renderEasyReport(report);
      telemetry.analysisResultReady(
        state.sourceMode, "job", report.outcome, state.workItemId,
      );
      state.workItemId = null;
      onReady();
    } catch (error) {
      renderEasyFailure(
        error.message || "結果を取得できませんでした。しばらくしてから更新してください。",
      );
    }
  }

  function start(workItemId, resultKind, sourceMode) {
    stop();
    state.workItemId = workItemId;
    state.resultKind = resultKind;
    state.sourceMode = sourceMode;
    state.pollAttempts = 0;
    renderEasyProgress("QUEUED");
    schedule(500);
  }

  return { refresh, start, stop };
}

function batchOutcome(batch) {
  if ((batch.counts?.FAILED || 0) || (batch.outcomes?.BLOCKED || 0)) return "BLOCKED";
  if (batch.outcomes?.REVIEW_REQUIRED) return "REVIEW_REQUIRED";
  return "READY_FOR_NORMALIZATION";
}
