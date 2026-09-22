export function createEasyTelemetry(sendEvent) {
  const sessionId = crypto.randomUUID();
  const startedAt = performance.now();
  let sequence = 0;
  let retryCount = 0;

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
    analysisRequested(sourceMode) {
      record("ANALYSIS_REQUESTED", "INFO", { source_mode: sourceMode }, performance.now() - startedAt);
    },
    analysisAccepted(sourceMode, mappingMatch) {
      record("ANALYSIS_ACCEPTED", "SUCCESS", {
        source_mode: sourceMode,
        mapping_match: mappingMatch,
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

function viewportBucket() {
  if (window.innerWidth < 680) return "small";
  if (window.innerWidth < 1024) return "medium";
  return "large";
}
