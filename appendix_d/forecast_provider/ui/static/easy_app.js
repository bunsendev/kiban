import { ApiError, clearToken, setToken } from "./api.js";
import {
  loadEasySetup,
  loadEasyAnalysis,
  loadEasyReport,
  loadEasySource,
  loadEasySources,
  sendEasyOperationEvent,
  startEasyAnalysis,
  uploadEasySource,
} from "./easy_api.js";
import { createEasyResultFlow } from "./easy_result_flow.js";
import {
  countBucket,
  createEasyTelemetry,
  fileSizeBucket,
  sourceAgeBucket,
} from "./easy_telemetry.js";

const byId = (id) => document.getElementById(id);
const state = {
  setup: null,
  mode: "upload",
  selection: null,
  busy: false,
  accepted: false,
};
const telemetry = createEasyTelemetry(sendEasyOperationEvent);
const resultFlow = createEasyResultFlow({
  loadAnalysis: loadEasyAnalysis,
  loadReport: loadEasyReport,
  telemetry,
  onReady: () => setFlowStep(2),
});

function notice(message, tone = "") {
  const element = byId("notice");
  element.className = `easy-notice${tone ? ` ${tone}` : ""}`;
  element.textContent = message;
}

function bytes(value) {
  if (!Number.isFinite(value)) return "";
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)} MB`;
  return `${Math.max(1, Math.round(value / 1_000))} KB`;
}

function updateAction() {
  const canAnalyze = state.setup?.session.permissions.includes("ANALYZE");
  byId("analyze-button").disabled = state.busy || state.accepted || !state.selection || !canAnalyze;
}

function setBusy(busy) {
  state.busy = busy;
  document.body.setAttribute("aria-busy", String(busy));
  for (const control of document.querySelectorAll("button, input, select")) {
    control.disabled = busy;
  }
  if (!busy && state.setup) {
    byId("folder-source").disabled = state.setup.sources.items.length === 0;
  }
  updateAction();
}

function setFlowStep(step) {
  for (let index = 1; index <= 4; index += 1) {
    const item = byId(`flow-step-${index}`);
    const current = index === step;
    item.classList.toggle("current", current);
    if (current) item.setAttribute("aria-current", "step");
    else item.removeAttribute("aria-current");
  }
}

function showResultPanel(workItemId, resultKind) {
  byId("source-panel").hidden = true;
  byId("result-panel").hidden = false;
  byId("result-reference").textContent = `受付番号: ${workItemId}`;
  setFlowStep(2);
  resultFlow.start(workItemId, resultKind, state.selection.kind);
}

function restartFlow() {
  resultFlow.stop();
  state.accepted = false;
  byId("result-panel").hidden = true;
  byId("source-panel").hidden = false;
  byId("source-file").value = "";
  byId("file-picker-title").textContent = "ここを押してファイルを選択";
  showSelection(null);
  if (state.mode === "folder") selectFolderSource();
  setFlowStep(1);
}

function showSelection(selection) {
  state.selection = selection;
  state.accepted = false;
  byId("analyze-button").textContent = "データを分析する →";
  byId("selected-summary").hidden = !selection;
  if (selection) {
    byId("selected-name").textContent = selection.name;
    byId("selected-detail").textContent = selection.detail;
    notice("準備できました。「データを分析する」を押してください。", "success");
  } else {
    byId("selected-name").textContent = "—";
    byId("selected-detail").textContent = "—";
    notice("ファイルを選択してください。");
  }
  updateAction();
}

function trackSelection(selection) {
  telemetry.sourceSelected({
    sourceMode: selection.kind,
    fileKind: selection.name.toLocaleLowerCase("en").endsWith(".zip") ? "zip" : "csv",
    fileSizeBucket: fileSizeBucket(selection.file?.size ?? selection.source?.size_bytes),
    sourceCountBucket: countBucket(state.setup?.sources.items.length),
  });
}

function sourceLabel(source) {
  const modified = source.modified_at
    ? new Intl.DateTimeFormat("ja-JP", { dateStyle: "medium", timeStyle: "short" }).format(new Date(source.modified_at))
    : "日時不明";
  const filename = source.source_path.split("/").at(-1);
  return `${filename}（${modified}・${bytes(source.size_bytes)}）`;
}

function renderSources(catalog) {
  state.setup.sources = catalog;
  const select = byId("folder-source");
  const sources = [...catalog.items].sort((left, right) =>
    String(right.modified_at).localeCompare(String(left.modified_at)));
  select.replaceChildren();
  for (const source of sources) {
    const option = document.createElement("option");
    option.value = source.source_path;
    option.textContent = sourceLabel(source);
    select.append(option);
  }
  select.disabled = sources.length === 0;
  byId("folder-empty").hidden = sources.length > 0;
  if (state.mode === "folder") selectFolderSource();
}

function selectFolderSource(track = false) {
  const source = state.setup?.sources.items.find(
    (item) => item.source_path === byId("folder-source").value,
  );
  const selection = source ? {
    kind: "folder",
    name: source.source_path.split("/").at(-1),
    detail: `${bytes(source.size_bytes)}・指定フォルダ`,
    sourcePath: source.source_path,
    source,
  } : null;
  showSelection(selection);
  if (track && selection) trackSelection(selection);
}

function switchMode(mode) {
  state.mode = mode;
  telemetry.sourceModeChanged(mode);
  const upload = mode === "upload";
  byId("upload-tab").classList.toggle("active", upload);
  byId("upload-tab").setAttribute("aria-selected", String(upload));
  byId("folder-tab").classList.toggle("active", !upload);
  byId("folder-tab").setAttribute("aria-selected", String(!upload));
  byId("upload-panel").hidden = !upload;
  byId("folder-panel").hidden = upload;
  if (upload) {
    const file = byId("source-file").files[0];
    showSelection(file ? fileSelection(file) : null);
  } else {
    selectFolderSource(true);
  }
}

function fileSelection(file) {
  return {
    kind: "upload",
    name: file.name,
    detail: `${bytes(file.size)}・このPCからアップロード`,
    file,
  };
}

function requiredColumns(mapping) {
  const definition = mapping.definition;
  return [
    definition.date_column,
    definition.jan_column,
    definition.product_name_column,
    definition.quantity_column,
    definition.unit_column,
    definition.center?.mode === "COLUMN" ? definition.center.value : null,
    definition.row_type_column,
    definition.availability_mode === "OBSERVED" ? definition.available_at_column : null,
  ].filter(Boolean);
}

function compatibleMapping(source) {
  if (!source || source.header_error) return null;
  return state.setup.mappings.find((mapping) =>
    requiredColumns(mapping).every((column) => source.columns.includes(column))) || null;
}

async function prepareSelection() {
  if (state.selection.kind === "folder") return state.selection;
  const uploaded = await uploadEasySource(state.selection.file);
  const sourcePath = uploaded.source_path
    || uploaded.analysis_source_path
    || uploaded.first_source_path;
  const source = await loadEasySource(sourcePath);
  return {
    ...state.selection,
    source,
    sourcePath,
    sourcePrefix: uploaded.source_prefix || null,
  };
}

async function connect(event) {
  event.preventDefault();
  setToken(byId("api-token").value);
  setBusy(true);
  try {
    state.setup = await loadEasySetup();
    byId("connection-panel").hidden = true;
    byId("source-panel").hidden = false;
    byId("connected-user").hidden = false;
    byId("session-name").textContent = `${state.setup.session.subject} / 接続済み`;
    byId("api-token").value = "";
    renderSources(state.setup.sources);
    telemetry.connected();
    notice("ファイルを選択してください。");
  } catch (error) {
    clearToken();
    const message = error instanceof ApiError && error.status === 401
      ? "接続コードを確認してください。"
      : error.message || "接続できませんでした。";
    byId("connection-panel").hidden = false;
    byId("source-panel").hidden = true;
    byId("connected-user").hidden = true;
    window.alert(message);
  } finally {
    setBusy(false);
  }
}

async function analyze() {
  if (!state.selection || state.busy) return;
  setBusy(true);
  telemetry.analysisRequested(state.selection.kind);
  notice(state.selection.kind === "upload" ? "ファイルを保存して内容を確認しています…" : "内容を確認しています…");
  try {
    telemetry.stageStarted("source_prepare");
    let prepared;
    try {
      prepared = await prepareSelection();
      telemetry.stageCompleted("source_prepare", "SUCCESS", {
        source_mode: state.selection.kind,
        column_count_bucket: countBucket(prepared.source?.columns?.length),
        source_age_bucket: sourceAgeBucket(prepared.source?.modified_at),
      });
    } catch (error) {
      telemetry.stageCompleted("source_prepare", "FAILURE", {
        source_mode: state.selection.kind,
        error_kind: operationErrorKind(error),
      });
      throw error;
    }
    telemetry.stageStarted("mapping_resolution");
    const mapping = compatibleMapping(prepared.source);
    if (!mapping) {
      telemetry.stageCompleted("mapping_resolution", "FAILURE", {
        source_mode: prepared.kind,
        mapping_match: false,
        error_kind: "mapping_not_found",
      });
      throw new Error("データの列に合う設定が見つかりません。管理担当者へ確認してください。");
    }
    telemetry.stageCompleted("mapping_resolution", "SUCCESS", {
      source_mode: prepared.kind,
      mapping_match: true,
    });
    notice("分析を開始しています…");
    telemetry.stageStarted("analysis_submission");
    let created;
    try {
      created = await startEasyAnalysis(prepared, mapping.mapping_id);
      telemetry.stageCompleted("analysis_submission", "SUCCESS", {
        source_mode: prepared.kind,
        result_kind: prepared.sourcePrefix ? "batch" : "job",
        work_item_id: String(created.id),
      });
    } catch (error) {
      telemetry.stageCompleted("analysis_submission", "FAILURE", {
        source_mode: prepared.kind,
        error_kind: operationErrorKind(error),
      });
      throw error;
    }
    state.selection = prepared;
    state.accepted = true;
    telemetry.analysisAccepted(prepared.kind, true, created.id);
    notice(`分析を開始しました。受付番号: ${created.id}`, "success");
    byId("analyze-button").textContent = "分析を受け付けました";
    showResultPanel(created.id, prepared.sourcePrefix ? "batch" : "job");
  } catch (error) {
    telemetry.analysisFailed(state.selection.kind, operationErrorKind(error));
    notice(error.message || "分析を開始できませんでした。", "error");
  } finally {
    setBusy(false);
  }
}

function operationErrorKind(error) {
  if (error instanceof ApiError) return `api_${error.status}`;
  if (String(error?.message).includes("列に合う設定")) return "mapping_not_found";
  return "unexpected";
}

byId("connection-form").addEventListener("submit", connect);
byId("upload-tab").addEventListener("click", () => switchMode("upload"));
byId("folder-tab").addEventListener("click", () => switchMode("folder"));
byId("source-file").addEventListener("change", (event) => {
  const file = event.target.files[0];
  byId("file-picker-title").textContent = file?.name || "ここを押してファイルを選択";
  const selection = file ? fileSelection(file) : null;
  showSelection(selection);
  if (selection) trackSelection(selection);
});
byId("folder-source").addEventListener("change", () => selectFolderSource(true));
byId("refresh-sources").addEventListener("click", async () => {
  setBusy(true);
  const startedAt = performance.now();
  try {
    const sources = await loadEasySources();
    renderSources(sources);
    telemetry.sourceListRefreshed(
      "SUCCESS", countBucket(sources.items.length), performance.now() - startedAt,
    );
    notice("指定フォルダの一覧を更新しました。", "success");
  } catch (error) {
    telemetry.sourceListRefreshed(
      "FAILURE", "unknown", performance.now() - startedAt, operationErrorKind(error),
    );
    notice(error.message || "一覧を更新できませんでした。", "error");
  } finally {
    setBusy(false);
  }
});
byId("clear-selection").addEventListener("click", () => {
  if (state.mode === "upload") {
    byId("source-file").value = "";
    byId("file-picker-title").textContent = "ここを押してファイルを選択";
    showSelection(null);
    telemetry.sourceCleared("upload");
    byId("source-file").click();
  } else {
    byId("folder-source").focus();
  }
});
byId("analyze-button").addEventListener("click", analyze);
byId("result-refresh").addEventListener("click", resultFlow.refresh);
byId("result-restart").addEventListener("click", restartFlow);
byId("disconnect-button").addEventListener("click", () => {
  resultFlow.stop();
  clearToken();
  state.setup = null;
  showSelection(null);
  byId("connection-panel").hidden = false;
  byId("source-panel").hidden = true;
  byId("result-panel").hidden = true;
  byId("connected-user").hidden = true;
  setFlowStep(1);
  byId("api-token").focus();
});
