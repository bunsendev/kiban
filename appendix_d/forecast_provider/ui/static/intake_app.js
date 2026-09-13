import { installPkceLogin } from "./pkce.js";
import { ApiError, clearToken, setToken } from "./api.js";
import {
  createImport,
  createMapping,
  createNormalization,
  loadImport,
  loadIntakeDashboard,
  loadMappingDryRun,
  loadNormalization,
  selectSource,
} from "./intake_api.js";
import { mappingPayload, syncAvailability } from "./intake_forms.js";
import {
  renderImportDetail,
  renderJobLists,
  renderMappingDryRunDetail,
  renderNormalizationDetail,
  renderSummary,
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
  dryRunSearch: byId("dry-run-search"),
  importSearch: byId("import-search"),
  normalizationSearch: byId("normalization-search"),
  rowStatus: byId("row-status"),
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
  renderJobLists(
    state.dashboard,
    { kind: state.selectedKind, id: state.selectedId },
    {
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
  setBusy(true);
  const loadingMessages = {
    dry_run: "checksum検証済みのドライラン証跡を読み込んでいます。",
    import: "原本取込の証跡を読み込んでいます。",
    normalization: "正規化結果を読み込んでいます。",
  };
  notice(loadingMessages[kind]);
  try {
    state.selectedKind = kind;
    state.selectedId = id;
    drawLists();
    if (kind === "dry_run") {
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
    const recordSets = {
      dry_run: [state.dashboard.dryRuns, "report_sha256"],
      import: [state.dashboard.imports, "import_id"],
      normalization: [state.dashboard.normalizations, "normalization_id"],
    };
    const [preferredRecords, preferredKey] = recordSets[preferred.kind] || [[], ""];
    const available = preferred.id && preferredRecords.some((record) => record[preferredKey] === preferred.id);
    const next = available
      ? preferred
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

byId("mapping-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (state.busy) return;
  setBusy(true);
  notice("列、時点方式、許可単位を検証しています。");
  try {
    await createMapping(mappingPayload(byId));
    setBusy(false);
    await refreshDashboard();
    notice("内容アドレス方式の列mappingを登録しました。", "success");
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
elements.disconnect.addEventListener("click", () => {
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
  elements.importSearch.value = "";
  elements.normalizationSearch.value = "";
  elements.dryRunSearch.value = "";
  renderSummary({
    dryRuns: [],
    validDryRunCount: 0,
    invalidDryRunCount: 0,
    imports: [],
    normalizations: [],
    quality: { files: {} },
  });
  replaceListsAfterDisconnect();
  showDetail();
  setBusy(false);
  notice("切断しました。tokenは画面から破棄されました。", "success");
});

function replaceListsAfterDisconnect() {
  byId("dry-run-filter-count").textContent = "0件";
  byId("import-filter-count").textContent = "0件";
  byId("normalization-filter-count").textContent = "0件";
  byId("dry-run-list").replaceChildren();
  byId("import-list").replaceChildren();
  byId("normalization-list").replaceChildren();
}

elements.dryRunSearch.addEventListener("input", drawLists);
elements.importSearch.addEventListener("input", drawLists);
elements.normalizationSearch.addEventListener("input", drawLists);
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
