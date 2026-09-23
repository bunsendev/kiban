export function createEasyTelemetry(sendEvent) {
  const sessionId = crypto.randomUUID();
  const startedAt = performance.now();
  let sequence = 0;
  let retryCount = 0;
  let selectionCount = 0;
  const stageStartedAt = new Map();

  function record(eventName, outcome = "INFO", metadata = {}, elapsedMs = null) {
    sequence += 1;
    const payload = {
      event_id: crypto.randomUUID(),
      flow_session_id: sessionId,
      screen: "easy",
      event_name: eventName,
      step: 1,
      sequence,
      outcome,
      elapsed_ms: elapsedMs === null ? null : Math.max(0, Math.round(elapsedMs)),
      metadata: {
        flow_version: "easy-v1",
        viewport_bucket: viewportBucket(),
        retry_count: retryCount,
        selection_count: selectionCount,
        online: navigator.onLine,
        ...metadata,
      },
      occurred_at: new Date().toISOString(),
    };
    sendEvent(payload).catch(() => {});
  }

  return {
    connected() {
      record("CONNECTED", "SUCCESS", {}, performance.now() - startedAt);
      record("STEP_VIEWED", "INFO");
    },
    sourceModeChanged(sourceMode) {
      record("SOURCE_MODE_CHANGED", "INFO", { source_mode: sourceMode });
    },
    sourceSelected({ sourceMode, fileKind, fileSizeBucket, sourceCountBucket }) {
      selectionCount += 1;
      record("SOURCE_SELECTED", "SUCCESS", {
        source_mode: sourceMode,
        file_kind: fileKind,
        file_size_bucket: fileSizeBucket,
        source_count_bucket: sourceCountBucket,
      });
    },
    sourceCleared(sourceMode) {
      record("SOURCE_CLEARED", "CANCELLED", { source_mode: sourceMode });
    },
    sourceListRefreshed(outcome, sourceCountBucket, elapsedMs, errorKind = null) {
      record("SOURCE_LIST_REFRESHED", outcome, {
        source_mode: "folder",
        source_count_bucket: sourceCountBucket,
        ...(errorKind ? { error_kind: errorKind } : {}),
      }, elapsedMs);
    },
    stageStarted(stageName) {
      stageStartedAt.set(stageName, performance.now());
    },
    stageCompleted(stageName, outcome, metadata = {}) {
      const started = stageStartedAt.get(stageName) ?? performance.now();
      stageStartedAt.delete(stageName);
      record("STAGE_COMPLETED", outcome, {
        stage_name: stageName,
        ...metadata,
      }, performance.now() - started);
    },
    analysisRequested(sourceMode) {
      record("ANALYSIS_REQUESTED", "INFO", { source_mode: sourceMode }, performance.now() - startedAt);
    },
    analysisAccepted(sourceMode, mappingMatch, workItemId) {
      record("ANALYSIS_ACCEPTED", "SUCCESS", {
        source_mode: sourceMode,
        mapping_match: mappingMatch,
        work_item_id: String(workItemId),
      }, performance.now() - startedAt);
      record("STEP_COMPLETED", "SUCCESS", {}, performance.now() - startedAt);
    },
    analysisFailed(sourceMode, errorKind) {
      retryCount += 1;
      record("ANALYSIS_FAILED", "FAILURE", {
        source_mode: sourceMode,
        error_kind: errorKind,
      }, performance.now() - startedAt);
    },
  };
}

export function fileSizeBucket(size) {
  if (!Number.isFinite(size)) return "unknown";
  if (size < 1_000_000) return "under_1mb";
  if (size < 10_000_000) return "1mb_to_10mb";
  if (size < 50_000_000) return "10mb_to_50mb";
  return "50mb_or_more";
}

export function countBucket(count) {
  if (!Number.isFinite(count)) return "unknown";
  if (count === 0) return "zero";
  if (count === 1) return "one";
  if (count <= 10) return "two_to_ten";
  if (count <= 100) return "eleven_to_hundred";
  return "over_hundred";
}

export function sourceAgeBucket(modifiedAt) {
  if (!modifiedAt) return "unknown";
  const ageDays = (Date.now() - new Date(modifiedAt).getTime()) / 86_400_000;
  if (!Number.isFinite(ageDays)) return "unknown";
  if (ageDays < 1) return "today";
  if (ageDays < 8) return "one_to_seven_days";
  if (ageDays < 31) return "eight_to_thirty_days";
  return "over_thirty_days";
}

function viewportBucket() {
  if (window.innerWidth < 680) return "small";
  if (window.innerWidth < 1024) return "medium";
  return "large";
}
