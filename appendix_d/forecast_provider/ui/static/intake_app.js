import { installPkceLogin } from "./pkce.js";
import { ApiError, clearToken, download, setToken } from "./api.js";
import {
  createImport,
  createInventoryStructureProfile,
  createInventoryNormalizationPreview,
  createInventoryNormalizationJob,
  createInventoryNormalizationDecision,
  analyzeProductJanBridge,
  uploadProductJanMapping,
  createMapping,
  createMappingDryRunJob,
  createMappingDryRunBatch,
  createNormalization,
  loadImport,
  loadIntakeDashboard,
  loadMappingDryRun,
  loadMappingDryRunJob,
  loadInventoryNormalizationJob,
  loadInventoryNormalizationDecisions,
  loadInventoryNormalizationResults,
  loadMappingDryRunBatch,
  loadMappingDryRunSource,
  loadNormalization,
  selectSource,
  uploadMappingDryRunSource,
  uploadMappingDryRunBatch,
} from "./intake_api.js";
import {
  renderInventoryNormalizationHistory,
  renderInventoryNormalizationResults,
} from "./intake_inventory_results.js";
import { mappingPayload, syncAvailability } from "./intake_forms.js";
import {
  renderImportDetail,
  renderJobLists,
  renderMappingDryRunDetail,
  renderMappingDryRunJobDetail,
  renderNormalizationDetail,
  renderSummary,
  renderValidationSetup,
  showDetail,
} from "./intake_render.js";

const state = {
  dashboard: null,
  selectedKind: null,
  selectedId: null,
  detail: null,
  page: null,
  rowStatus: "",
  permissions: new Set(),
  busy: false,
  pollTimer: null,
  pollAttempts: 0,
  batchPollTimer: null,
  uploadedBatchPrefix: null,
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
  dryRunJobReport: byId("dry-run-job-report-button"),
  dryRunJobSearch: byId("dry-run-job-search"),
  dryRunSource: byId("dry-run-source-path"),
  uploadFile: byId("upload-file"),
  dryRunMapping: byId("dry-run-mapping"),
  dryRunSearch: byId("dry-run-search"),
  importSearch: byId("import-search"),
  normalizationSearch: byId("normalization-search"),
  rowStatus: byId("row-status"),
  notice: byId("notice"),
  validationProgress: byId("validation-progress"),
  mappingDrawer: byId("mapping-drawer"),
  inventoryHistory: byId("inventory-normalization-history"),
  inventoryHistoryList: byId("inventory-normalization-history-list"),
};

async function openInventoryNormalizationJob(job) {
  const result = byId("inventory-preview-result");
  result.hidden = false;
  if (job.status !== "SUCCEEDED") {
    result.textContent = `${job.processed_file_count} / ${job.file_count || "—"}ファイル処理済み。状態: ${job.status}`;
    return;
  }
  const [results, decisions] = await Promise.all([
    loadInventoryNormalizationResults(job.job_id),
    loadInventoryNormalizationDecisions(job.job_id),
  ]);
  renderInventoryNormalizationResults(result, job.job_id, job, results, download, {
    decisions,
    canApprove: state.permissions.has("APPROVE"),
    createDecision: createInventoryNormalizationDecision,
    onError: handleError,
    onChanged: async () => {
      await refreshDashboard();
      const updated = state.dashboard.inventoryJobs.find((item) => item.job_id === job.job_id);
      await openInventoryNormalizationJob(updated);
      notice("在庫正規化結果の判断を記録しました。", "success");
    },
  });
}

function updateUploadButton() {
  const button = byId("upload-submit");
  const file = elements.uploadFile.files[0];
  button.dataset.blocked = String(!file || !/\.(csv|zip)$/i.test(file.name));
  setBusy(state.busy);
}

function clearDryRunPoll() {
  if (state.pollTimer !== null) window.clearTimeout(state.pollTimer);
  state.pollTimer = null;
}

function scheduleDryRunPoll(jobId) {
  clearDryRunPoll();
  if (state.pollAttempts >= 30) {
    elements.validationProgress.className = "validation-progress warning";
    elements.validationProgress.textContent = "処理待ちが続いています。Workerが起動しているか確認し、必要に応じて「更新」を押してください。";
    return;
  }
  state.pollTimer = window.setTimeout(() => pollDryRunJob(jobId), 2000);
}

async function pollDryRunJob(jobId) {
  state.pollTimer = null;
  if (state.selectedKind !== "dry_run_job" || state.selectedId !== jobId) return;
  if (state.busy) {
    scheduleDryRunPoll(jobId);
    return;
  }
  state.pollAttempts += 1;
  try {
    const job = await loadMappingDryRunJob(jobId);
    state.detail = job;
    const summary = state.dashboard?.dryRunJobs.find((item) => item.job_id === jobId);
    if (summary) Object.assign(summary, job);
    drawLists();
    renderMappingDryRunJobDetail(job);
    if (["QUEUED", "RUNNING"].includes(job.status)) {
      scheduleDryRunPoll(jobId);
      return;
    }
    await refreshDashboard({ kind: "dry_run_job", id: jobId });
    await openCompletedDryRunReport(job);
  } catch (error) {
    handleError(error);
  }
}

async function openCompletedDryRunReport(job) {
  if (job?.status !== "SUCCEEDED" || !job.report_sha256) return false;
  await selectJob("dry_run", job.report_sha256);
  notice("検証が完了しました。判定と修正方法を表示しています。", "success");
  return true;
}

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
  renderJobLists(
    state.dashboard,
    { kind: state.selectedKind, id: state.selectedId },
    {
      dryRunJobs: elements.dryRunJobSearch.value,
      dryRuns: elements.dryRunSearch.value,
      imports: elements.importSearch.value,
      normalizations: elements.normalizationSearch.value,
    },
    selectJob,
  );
}

async function selectJob(kind, id, { status = "", offset = 0 } = {}) {
  if (state.busy) return;
  const samePage = kind === state.selectedKind && id === state.selectedId
    && (kind !== "normalization" || (state.page?.offset === offset && state.rowStatus === status));
  if (samePage) return;
  clearDryRunPoll();
  if (kind !== "dry_run_job") state.pollAttempts = 0;
  setBusy(true);
  const loadingMessages = {
    dry_run_job: "ローカルデータ検証jobを読み込んでいます。",
    dry_run: "checksum検証済みのドライラン証跡を読み込んでいます。",
    import: "原本取込の証跡を読み込んでいます。",
    normalization: "正規化結果を読み込んでいます。",
  };
  notice(loadingMessages[kind]);
  try {
    state.selectedKind = kind;
    state.selectedId = id;
    drawLists();
    if (kind === "dry_run_job") {
      state.detail = await loadMappingDryRunJob(id);
      state.page = null;
      state.rowStatus = "";
      renderMappingDryRunJobDetail(state.detail);
      notice(
        state.detail.status === "SUCCEEDED"
          ? "検証jobは完了しました。このジョブの検証結果を表示できます。"
          : "検証Workerの完了後に更新してください。",
        state.detail.status === "SUCCEEDED" ? "success" : "",
      );
      if (["QUEUED", "RUNNING"].includes(state.detail.status)) scheduleDryRunPoll(id);
    } else if (kind === "dry_run") {
      state.detail = await loadMappingDryRun(id);
      state.page = null;
      state.rowStatus = "";
      renderMappingDryRunDetail(state.detail);
      notice("秘匿済みの判定・隔離理由・制約を読み込みました。", "success");
    } else if (kind === "import") {
      state.detail = await loadImport(id);
      state.page = null;
      state.rowStatus = "";
      renderImportDetail(state.detail, state.dashboard);
      notice(
        state.detail.status === "SUCCEEDED"
          ? "原本、訂正版候補、採用履歴を読み込みました。"
          : "取込Workerの完了後に更新してください。",
        state.detail.status === "SUCCEEDED" ? "success" : "",
      );
    } else {
      const result = await loadNormalization(id, status, offset);
      state.detail = result.summary;
      state.page = result.page;
      state.rowStatus = status;
      elements.rowStatus.value = status;
      renderNormalizationDetail(result.summary, result.page);
      notice(
        result.summary.status === "SUCCEEDED"
          ? "数量照合と正規化行を読み込みました。"
          : "正規化Workerの完了後に更新してください。",
        result.summary.status === "SUCCEEDED" ? "success" : "",
      );
    }
  } catch (error) {
    state.selectedKind = null;
    state.selectedId = null;
    state.detail = null;
    state.page = null;
    state.rowStatus = "";
    showDetail();
    drawLists();
    handleError(error);
  } finally {
    setBusy(false);
  }
}

async function refreshDashboard(preferred = { kind: state.selectedKind, id: state.selectedId }) {
  setBusy(true);
  notice("原本取込・正規化台帳を更新しています。");
  try {
    state.dashboard = await loadIntakeDashboard();
    state.permissions = new Set(state.dashboard.session.permissions);
    elements.sessionIdentity.textContent = `${state.dashboard.session.subject} / ${state.dashboard.session.roles.join(", ")}`;
    renderSummary(state.dashboard);
    elements.inventoryHistory.hidden = state.dashboard.inventoryJobs.length === 0;
    renderInventoryNormalizationHistory(
      elements.inventoryHistoryList,
      state.dashboard.inventoryJobs,
      state.dashboard.inventoryAdoption,
      (job) => openInventoryNormalizationJob(job).catch(handleError),
    );
    const recordSets = {
      dry_run_job: [state.dashboard.dryRunJobs, "job_id"],
      dry_run: [state.dashboard.dryRuns, "report_sha256"],
      import: [state.dashboard.imports, "import_id"],
      normalization: [state.dashboard.normalizations, "normalization_id"],
    };
    const [preferredRecords, preferredKey] = recordSets[preferred.kind] || [[], ""];
    const available = preferred.id && preferredRecords.some((record) => record[preferredKey] === preferred.id);
    const next = available
      ? preferred
      : state.dashboard.dryRunJobs[0]
        ? { kind: "dry_run_job", id: state.dashboard.dryRunJobs[0].job_id }
        : state.dashboard.dryRuns[0]
        ? { kind: "dry_run", id: state.dashboard.dryRuns[0].report_sha256 }
        : state.dashboard.imports[0]
        ? { kind: "import", id: state.dashboard.imports[0].import_id }
        : state.dashboard.normalizations[0]
          ? { kind: "normalization", id: state.dashboard.normalizations[0].normalization_id }
          : null;
    state.selectedKind = null;
    state.selectedId = null;
    state.detail = null;
    state.page = null;
    state.rowStatus = "";
    showDetail();
    drawLists();
    if (next) {
      setBusy(false);
      await selectJob(next.kind, next.id);
    } else {
      notice(
        state.dashboard.dryRunConfigured
          ? "接続しました。ドライラン証跡と取込jobはまだありません。"
          : "接続しました。ドライラン証跡rootは未設定です。",
        "success",
      );
    }
    return true;
  } catch (error) {
    handleError(error);
    return false;
  } finally {
    setBusy(false);
  }
}

byId("import-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (state.busy) return;
  setBusy(true);
  notice("管理対象入力root内の取込jobを登録しています。");
  try {
    const created = await createImport({ source_path: value("import-source-path") });
    setBusy(false);
    await refreshDashboard({ kind: "import", id: created.id });
    notice("取込jobを登録しました。Worker完了後に更新してください。", "success");
  } catch (error) {
    handleError(error);
  } finally {
    setBusy(false);
  }
});

byId("dry-run-job-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (state.busy) return;
  setBusy(true);
  notice("ローカルデータ検証jobを登録しています。");
  try {
    const created = await createMappingDryRunJob({
      source_path: value("dry-run-source-path"),
      mapping_id: value("dry-run-mapping"),
      sample_rows: Number(value("dry-run-sample-rows")),
    });
    setBusy(false);
    state.pollAttempts = 0;
    await refreshDashboard({ kind: "dry_run_job", id: created.id });
    if (!await openCompletedDryRunReport(state.detail)) {
      notice("検証を開始しました。完了まで自動で更新します。", "success");
    }
  } catch (error) {
    handleError(error);
  } finally {
    setBusy(false);
  }
});

byId("upload-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const file = elements.uploadFile.files[0];
  if (state.busy || !file) return;
  setBusy(true);
  const isZip = file.name.toLocaleLowerCase("en").endsWith(".zip");
  notice(isZip ? "ZIP内のCSVを検査して一括アップロードしています。" : "CSVを安全な検証領域へアップロードしています。");
  try {
    const uploaded = isZip
      ? await uploadMappingDryRunBatch(file)
      : await uploadMappingDryRunSource(file);
    elements.uploadFile.value = "";
    setBusy(false);
    await refreshDashboard();
    const uploadedPath = uploaded.source_path || uploaded.first_source_path;
    if (!state.dashboard.sources.some((source) => source.source_path === uploadedPath)) {
      const source = await loadMappingDryRunSource(uploadedPath);
      if (source) state.dashboard.sources.push(source);
      renderSummary(state.dashboard);
    }
    elements.dryRunSource.value = uploadedPath;
    if (isZip) {
      byId("dry-run-batch-prefix").value = uploaded.source_prefix;
      byId("dry-run-batch-form").hidden = false;
      state.uploadedBatchPrefix = uploaded.source_prefix;
      byId("inventory-profile-panel").hidden = false;
      byId("product-bridge-panel").hidden = false;
    }
    renderValidationSetup(state.dashboard);
    notice(
      isZip
        ? `${uploaded.file_count.toLocaleString("ja-JP")}件のCSVを一括アップロードしました。`
        : "アップロードしました。列の対応付けを選んで分析を実行してください。",
      "success",
    );
  } catch (error) {
    handleError(error);
  } finally {
    setBusy(false);
    updateUploadButton();
  }
});

byId("product-bridge-submit").addEventListener("click", async () => {
  if (state.busy || !state.uploadedBatchPrefix) return;
  setBusy(true);
  notice("商品コードとJANの対応可否を診断しています。");
  try {
    const analysis = await analyzeProductJanBridge(state.uploadedBatchPrefix);
    const result = byId("product-bridge-result");
    result.hidden = false;
    result.textContent = [
      `出荷サンプル ${analysis.shipment_sampled_rows.toLocaleString("ja-JP")}行のうち、商品コードとJANの組は ${analysis.shipment_code_jan_pair_rows.toLocaleString("ja-JP")}行です。`,
      `在庫の商品コードは ${analysis.inventory_distinct_product_codes.toLocaleString("ja-JP")}種類です。`,
    ].join(" ");
    if (analysis.status === "EXTERNAL_MAPPING_REQUIRED") {
      const button = document.createElement("button");
      button.className = "button secondary";
      button.type = "button";
      button.textContent = "JAN記入用CSVをダウンロード";
      button.addEventListener("click", () => download(
        `/api/product-jan-bridge-template.csv?source_prefix=${encodeURIComponent(state.uploadedBatchPrefix)}`,
        "product-jan-mapping.csv",
      ).catch(handleError));
      result.append(button);
      byId("product-mapping-upload-form").hidden = false;
    }
    notice("商品コードとJANの対応診断が完了しました。", "success");
  } catch (error) {
    handleError(error);
  } finally {
    setBusy(false);
  }
});

byId("product-mapping-upload-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const file = byId("product-mapping-file").files[0];
  if (state.busy || !file || !state.uploadedBatchPrefix) return;
  setBusy(true);
  notice("JAN対応表の重複・形式・充足率を検証しています。");
  try {
    const report = await uploadProductJanMapping(state.uploadedBatchPrefix, file);
    const result = byId("product-mapping-upload-result");
    result.hidden = false;
    result.textContent = report.status === "READY"
      ? `全${report.expected_product_count}商品のJAN対応表を保存しました。ID: ${report.mapping_id}`
      : [
        `${report.completed_product_count} / ${report.expected_product_count}商品を確認済みです。`,
        `未記入 ${report.issues.blank_jans}、JAN形式不正 ${report.issues.invalid_jans}、重複 ${report.issues.duplicate_product_codes}、対象外 ${report.issues.unknown_product_codes}、不足 ${report.issues.missing_product_codes}。`,
      ].join(" ");
    if (report.status === "READY") {
      byId("inventory-preview-mapping-id").value = report.mapping_id;
      byId("inventory-preview-form").hidden = false;
    }
    notice(
      report.status === "READY" ? "JAN対応表を検証して保存しました。" : "修正が必要な項目があります。",
      report.status === "READY" ? "success" : "error",
    );
  } catch (error) {
    handleError(error);
  } finally {
    setBusy(false);
  }
});

byId("inventory-preview-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (state.busy || !state.uploadedBatchPrefix) return;
  setBusy(true);
  notice("在庫データの正規化可否を検証しています。");
  try {
    const report = await createInventoryNormalizationPreview({
      source_prefix: state.uploadedBatchPrefix,
      product_mapping_id: value("inventory-preview-mapping-id"),
      unit_value: value("inventory-preview-unit"),
      sample_rows: Number(value("inventory-preview-rows")),
    });
    const result = byId("inventory-preview-result");
    result.hidden = false;
    result.textContent = [
      `${report.file_count.toLocaleString("ja-JP")}ファイル、${report.sampled_rows.toLocaleString("ja-JP")}行を検査しました。`,
      `採用 ${report.accepted_rows.toLocaleString("ja-JP")}行、隔離 ${report.quarantined_rows.toLocaleString("ja-JP")}行。`,
      `判定: ${report.outcome}。証跡ID: ${report.report_id}`,
    ].join(" ");
    if (report.outcome === "READY_FOR_INVENTORY_NORMALIZATION") {
      const button = document.createElement("button");
      button.className = "button primary";
      button.type = "button";
      button.textContent = "全在庫データを正規化";
      button.addEventListener("click", async () => {
        try {
          const created = await createInventoryNormalizationJob({
            source_prefix: state.uploadedBatchPrefix,
            product_mapping_id: value("inventory-preview-mapping-id"),
            unit_value: value("inventory-preview-unit"),
          });
          const poll = async () => {
            const job = await loadInventoryNormalizationJob(created.id);
            result.textContent = `${job.processed_file_count} / ${job.file_count || "—"}ファイル処理済み。採用 ${job.accepted_row_count}行、隔離 ${job.quarantined_row_count}行。状態: ${job.status}`;
            if (["QUEUED", "RUNNING"].includes(job.status)) {
              window.setTimeout(() => poll().catch(handleError), 2000);
            } else if (job.status === "SUCCEEDED") {
              await openInventoryNormalizationJob(job);
            }
          };
          await poll();
        } catch (error) {
          handleError(error);
        }
      });
      result.append(button);
    }
    notice(
      report.outcome === "READY_FOR_INVENTORY_NORMALIZATION"
        ? "在庫データは正規化準備完了です。"
        : "隔離理由の確認が必要です。",
      report.outcome === "READY_FOR_INVENTORY_NORMALIZATION" ? "success" : "error",
    );
  } catch (error) {
    handleError(error);
  } finally {
    setBusy(false);
  }
});

byId("inventory-profile-submit").addEventListener("click", async () => {
  if (state.busy || !state.uploadedBatchPrefix) return;
  setBusy(true);
  notice("在庫CSVのヘッダー構造を全件診断しています。");
  try {
    const profile = await createInventoryStructureProfile(state.uploadedBatchPrefix);
    const complete = (field) => profile.field_candidates[field]
      .filter((item) => item.file_count === profile.file_count)
      .map((item) => item.column)
      .join("、") || "候補なし";
    const result = byId("inventory-profile-result");
    const analysis = profile.mapping_analysis;
    const recommendation = analysis.recommendation;
    result.hidden = false;
    result.textContent = [
      `在庫CSV ${profile.file_count}件 / ヘッダー構成 ${profile.header_pattern_count}種類。`,
      `日付候補: ${complete("date")}。数量候補: ${complete("quantity")}。`,
      `倉庫候補: ${complete("center")}。単位候補: ${complete("unit")}。`,
      `要確認: ${profile.issues.join("、") || "なし"}。`,
      `値診断: ${analysis.sampled_rows.toLocaleString("ja-JP")}行。`,
      recommendation.quantity_column
        ? `数量は「${recommendation.quantity_column}」、日付はファイル名、倉庫は「${recommendation.center_column}」が候補です。`
        : "値の充足条件を満たすmapping候補はありません。",
      "単位の定義と商品コードからJANへの対応付けは業務確認が必要です。",
    ].join(" ");
    notice("在庫CSVの構造診断が完了しました。候補列を確認してください。", "success");
  } catch (error) {
    handleError(error);
  } finally {
    setBusy(false);
  }
});

async function pollDryRunBatch(batchId) {
  const batch = await loadMappingDryRunBatch(batchId);
  const result = byId("dry-run-batch-result");
  result.hidden = false;
  const done = batch.counts.SUCCEEDED + batch.counts.FAILED;
  result.replaceChildren(document.createTextNode(
    `一括検証 ${done} / ${batch.selected_count}件完了（合格 ${batch.outcomes.READY_FOR_NORMALIZATION}、要確認 ${batch.outcomes.REVIEW_REQUIRED}、停止 ${batch.outcomes.BLOCKED}、対象外 ${batch.excluded_count}）`,
  ));
  if (batch.status === "COMPLETED") {
    const button = document.createElement("button");
    button.className = "button secondary";
    button.type = "button";
    button.textContent = "結果CSVをダウンロード";
    button.addEventListener("click", () => download(
      `/api/mapping-dry-run-batches/${encodeURIComponent(batchId)}/results.csv`,
      `batch-${batchId}.csv`,
    ).catch(handleError));
    result.append(button);
    notice("ZIP内の出荷CSVの一括検証が完了しました。", "success");
  } else {
    state.batchPollTimer = window.setTimeout(() => pollDryRunBatch(batchId).catch(handleError), 2000);
  }
}

byId("dry-run-batch-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (state.busy) return;
  setBusy(true);
  notice("ZIP内の出荷CSVを判別し、一括検証を登録しています。");
  try {
    const created = await createMappingDryRunBatch({
      source_prefix: value("dry-run-batch-prefix"),
      mapping_id: value("dry-run-mapping"),
      sample_rows: Number(value("dry-run-sample-rows")),
    });
    byId("dry-run-batch-form").hidden = true;
    await pollDryRunBatch(created.id);
  } catch (error) {
    handleError(error);
  } finally {
    setBusy(false);
  }
});

byId("mapping-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (state.busy) return;
  setBusy(true);
  notice("列、時点方式、許可単位を検証しています。");
  try {
    const created = await createMapping(mappingPayload(byId));
    setBusy(false);
    await refreshDashboard();
    elements.dryRunMapping.value = created.id;
    renderValidationSetup(state.dashboard);
    elements.mappingDrawer.open = false;
    notice("列の対応付けを登録し、検証フォームへ設定しました。", "success");
  } catch (error) {
    handleError(error);
  } finally {
    setBusy(false);
  }
});

byId("source-selection-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (state.busy || state.selectedKind !== "import") return;
  const sourceFileId = value("source-selection-file");
  const file = state.detail.files.find((item) => item.source_file_id === sourceFileId);
  if (!file) return;
  setBusy(true);
  notice("原本の状態、logical path、版を再検証しています。");
  try {
    await selectSource({
      logical_path: file.logical_path,
      source_file_id: sourceFileId,
      decision_version: value("source-selection-version"),
      reason: value("source-selection-reason"),
    });
    setBusy(false);
    await refreshDashboard({ kind: "import", id: state.selectedId });
    notice("原本版を採用し、追記型履歴を再読込しました。", "success");
  } catch (error) {
    handleError(error);
  } finally {
    setBusy(false);
  }
});

byId("normalization-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (state.busy || state.selectedKind !== "import") return;
  setBusy(true);
  notice("採用中原本と列mappingを検証しています。");
  try {
    const created = await createNormalization({
      source_file_id: value("normalization-source-file"),
      mapping_id: value("normalization-mapping"),
    });
    setBusy(false);
    await refreshDashboard({ kind: "normalization", id: created.id });
    notice("正規化jobを登録しました。Worker完了後に更新してください。", "success");
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
elements.dryRunJobReport.addEventListener("click", () => {
  const reportSha256 = elements.dryRunJobReport.dataset.reportSha256;
  if (reportSha256) selectJob("dry_run", reportSha256);
});
elements.disconnect.addEventListener("click", () => {
  clearDryRunPoll();
  clearToken();
  state.dashboard = null;
  state.selectedKind = null;
  state.selectedId = null;
  state.detail = null;
  state.page = null;
  state.rowStatus = "";
  state.permissions = new Set();
  elements.connectionForm.hidden = false;
  elements.sessionControls.hidden = true;
  elements.sessionIdentity.textContent = "";
  elements.dryRunJobSearch.value = "";
  elements.importSearch.value = "";
  elements.normalizationSearch.value = "";
  elements.dryRunSearch.value = "";
  renderSummary({
    mappings: [],
    dryRunJobs: [],
    dryRuns: [],
    validDryRunCount: 0,
    invalidDryRunCount: 0,
    imports: [],
    normalizations: [],
    quality: { files: {} },
    sources: [],
    sourceCatalogConfigured: false,
  });
  replaceListsAfterDisconnect();
  showDetail();
  setBusy(false);
  notice("切断しました。tokenは画面から破棄されました。", "success");
});

function replaceListsAfterDisconnect() {
  byId("dry-run-job-filter-count").textContent = "0件";
  byId("dry-run-filter-count").textContent = "0件";
  byId("import-filter-count").textContent = "0件";
  byId("normalization-filter-count").textContent = "0件";
  byId("dry-run-job-list").replaceChildren();
  byId("dry-run-list").replaceChildren();
  byId("import-list").replaceChildren();
  byId("normalization-list").replaceChildren();
}

elements.dryRunJobSearch.addEventListener("input", drawLists);
elements.dryRunSearch.addEventListener("input", drawLists);
elements.importSearch.addEventListener("input", drawLists);
elements.normalizationSearch.addEventListener("input", drawLists);
elements.dryRunSource.addEventListener("change", () => renderValidationSetup(state.dashboard));
elements.uploadFile.addEventListener("change", updateUploadButton);
elements.dryRunMapping.addEventListener("change", () => renderValidationSetup(state.dashboard));
byId("open-mapping-button").addEventListener("click", () => {
  elements.mappingDrawer.open = true;
  elements.mappingDrawer.scrollIntoView({ behavior: "smooth", block: "start" });
  byId("mapping-date").focus();
});
byId("mapping-availability").addEventListener("change", () => syncAvailability(byId));
elements.rowStatus.addEventListener("change", () =>
  selectJob("normalization", state.selectedId, { status: elements.rowStatus.value, offset: 0 }));
byId("row-previous").addEventListener("click", () =>
  selectJob("normalization", state.selectedId, {
    status: elements.rowStatus.value,
    offset: Math.max(0, state.page.offset - state.page.limit),
  }));
byId("row-next").addEventListener("click", () =>
  selectJob("normalization", state.selectedId, {
    status: elements.rowStatus.value,
    offset: state.page.offset + state.page.limit,
  }));
syncAvailability(byId);
setBusy(false);

installPkceLogin();
