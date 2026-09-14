import { dateTime, decisionLabel, metric, shortId, statusTone } from "./format.js";

function node(tag, options = {}, children = []) {
  const element = document.createElement(tag);
  for (const [name, value] of Object.entries(options)) {
    if (name === "className") element.className = value;
    else if (name === "text") element.textContent = value;
    else if (name === "title") element.title = value;
    else if (value !== undefined && value !== null) element.setAttribute(name, value);
  }
  for (const child of children) element.append(child);
  return element;
}

function replace(id, children) {
  document.getElementById(id).replaceChildren(...children);
}

const empty = (message) => node("div", { className: "empty-inline", text: message });
const pill = (value) => node("span", {
  className: `pill ${statusTone(value)}`,
  text: decisionLabel(value),
});

function lineage(label, value) {
  return node("div", { className: "lineage-item" }, [
    node("span", { text: label }),
    node("code", { text: value ?? "—", title: value ?? "" }),
  ]);
}

function tableEmpty(columns, message) {
  return node("tr", {}, [node("td", { colspan: String(columns), text: message })]);
}

function fillSelect(id, records, placeholder, valueOf, labelOf) {
  const select = document.getElementById(id);
  const selected = select.value;
  select.replaceChildren(node("option", { value: "", text: placeholder }));
  for (const record of records) {
    select.append(node("option", { value: valueOf(record), text: labelOf(record) }));
  }
  select.disabled = records.length === 0;
  if (records.some((record) => valueOf(record) === selected)) select.value = selected;
}

function bytes(value) {
  if (value === null || value === undefined) return "—";
  return new Intl.NumberFormat("ja-JP", { maximumFractionDigits: 1 }).format(value / 1024) + " KiB";
}

function mappingLabel(mapping) {
  const definition = mapping.definition;
  return `${definition.date_column}・${definition.jan_column}・${definition.quantity_column} / ${decisionLabel(definition.availability_mode)} / ${decisionLabel(definition.file_mode)}`;
}

export function renderValidationSetup(dashboard) {
  const sourceSelect = document.getElementById("dry-run-source-path");
  const mappingSelect = document.getElementById("dry-run-mapping");
  const source = dashboard.sources.find((item) => item.source_path === sourceSelect.value);
  const mapping = dashboard.mappings.find((item) => item.mapping_id === mappingSelect.value);
  const sourceHelp = document.getElementById("dry-run-source-info");
  const mappingHelp = document.getElementById("dry-run-mapping-info");
  const submit = document.getElementById("dry-run-submit");
  const requiredColumns = mapping ? [
    mapping.definition.date_column,
    mapping.definition.jan_column,
    mapping.definition.product_name_column,
    mapping.definition.quantity_column,
    mapping.definition.unit_column,
    mapping.definition.center?.mode === "COLUMN" ? mapping.definition.center.value : null,
    mapping.definition.row_type_column || null,
    mapping.definition.availability_mode === "OBSERVED" ? mapping.definition.available_at_column : null,
  ].filter(Boolean) : [];
  const missingColumns = source && !source.header_error
    ? requiredColumns.filter((column) => !source.columns.includes(column))
    : [];
  if (source) {
    sourceHelp.textContent = source.header_error
      ? `ヘッダーを確認できません（${source.header_error}）。検証結果で詳細を確認してください。`
      : `${bytes(source.size_bytes)} / ${source.encoding} / 列: ${source.columns.join("、")}`;
  } else {
    sourceHelp.textContent = dashboard.sourceCatalogConfigured
      ? "検証するCSVを選択してください。"
      : "管理対象入力フォルダーが設定されていません。環境設定を確認してください。";
  }
  mappingHelp.textContent = mapping
    ? `日付=${mapping.definition.date_column}、JAN=${mapping.definition.jan_column}、数量=${mapping.definition.quantity_column}、単位=${mapping.definition.unit_column}`
    : dashboard.mappings.length ? "列の対応付けを選択してください。" : "先に新しい対応付けを作成してください。";
  document.getElementById("wizard-source-step").className = `wizard-step${source ? " complete" : dashboard.sources.length ? " ready" : ""}`;
  document.getElementById("wizard-mapping-step").className = `wizard-step${mapping ? " complete" : source ? " ready" : ""}`;
  document.getElementById("wizard-run-step").className = `wizard-step${source && mapping && !missingColumns.length ? " ready" : missingColumns.length ? " error" : ""}`;
  submit.dataset.blocked = String(!source || !mapping || missingColumns.length > 0);
  submit.disabled = submit.dataset.blocked === "true";
  const progress = document.getElementById("validation-progress");
  progress.className = "validation-progress";
  progress.textContent = !source
    ? "手順1: 検証するCSVを選択してください。"
    : !mapping
      ? "手順2: CSVの列に合う対応付けを選択してください。"
      : missingColumns.length
        ? `対応付けに必要な列がCSVにありません: ${missingColumns.join("、")}。対応付けを選び直すか作成してください。`
        : "準備できました。「このCSVを検証」を押してください。";
  if (missingColumns.length) progress.className = "validation-progress error";
}

export function renderSummary(dashboard) {
  const files = dashboard.quality.files || {};
  document.getElementById("dry-run-job-count").textContent = dashboard.dryRunJobs.length;
  document.getElementById("dry-run-count").textContent =
    `${dashboard.validDryRunCount || 0} / ${dashboard.invalidDryRunCount || 0}`;
  document.getElementById("import-count").textContent = dashboard.imports.length;
  document.getElementById("accepted-file-count").textContent =
    (files.ACCEPTED || 0) + (files.CORRECTION_CANDIDATE || 0);
  document.getElementById("review-file-count").textContent =
    (files.CORRECTION_CANDIDATE || 0) + (files.QUARANTINED || 0);
  document.getElementById("normalized-row-count").textContent =
    dashboard.normalizations.reduce((sum, job) => sum + job.accepted_rows, 0);
  fillSelect(
    "dry-run-source-path",
    dashboard.sources,
    dashboard.sourceCatalogConfigured ? "CSVを選択" : "入力フォルダーが未設定です",
    (source) => source.source_path,
    (source) => `${source.source_path} / ${bytes(source.size_bytes)}`,
  );
  fillSelect(
    "dry-run-mapping",
    dashboard.mappings,
    "列mappingを選択",
    (mapping) => mapping.mapping_id,
    mappingLabel,
  );
  renderValidationSetup(dashboard);
}

function jobButton(kind, record, selectedKind, selectedId, onSelect) {
  const isDryRun = kind === "dry_run";
  const isDryRunJob = kind === "dry_run_job";
  const id = isDryRun
    ? record.report_sha256
    : isDryRunJob ? record.job_id : kind === "import" ? record.import_id : record.normalization_id;
  const title = isDryRun
    ? dateTime(record.checked_at)
    : isDryRunJob ? record.source_path
      : kind === "import" ? record.source_path : shortId(record.normalization_id, 24);
  const detail = isDryRun
    ? `${record.observations.sampled_rows}行 / 採用 ${record.observations.accepted_rows} / 隔離 ${record.observations.quarantined_rows}`
    : isDryRunJob ? `${record.sample_rows}行上限 / ${shortId(record.mapping_id, 18)}`
      : kind === "import"
      ? `${record.file_count}ファイル / 採用 ${record.accepted_count} / 隔離 ${record.quarantined_count}`
      : `${record.total_rows}行 / 採用 ${record.accepted_rows} / 隔離 ${record.quarantined_rows}`;
  const button = node("button", {
    type: "button",
    className: `comparison-item${kind === selectedKind && id === selectedId ? " active" : ""}`,
  });
  button.append(
    node("strong", { text: title }),
    node("span", { text: decisionLabel(isDryRun ? record.outcome : record.status) }),
    node("span", { text: detail }),
    node("code", { text: shortId(id, 28), title: id }),
  );
  button.addEventListener("click", () => onSelect(kind, id));
  return button;
}

export function renderJobLists(dashboard, selection, queries, onSelect) {
  const historyLimit = 20;
  const dryRunJobNeedle = queries.dryRunJobs.trim().toLocaleLowerCase("ja");
  const dryRunJobs = dashboard.dryRunJobs.filter((record) =>
    `${record.job_id} ${record.source_path} ${record.mapping_id} ${record.status}`
      .toLocaleLowerCase("ja")
      .includes(dryRunJobNeedle),
  );
  const dryRunNeedle = queries.dryRuns.trim().toLocaleLowerCase("ja");
  const dryRuns = dashboard.dryRuns.filter((record) =>
    `${record.report_sha256} ${record.dry_run_id} ${record.outcome} ${record.mapping_id || ""}`
      .toLocaleLowerCase("ja")
      .includes(dryRunNeedle),
  );
  const importNeedle = queries.imports.trim().toLocaleLowerCase("ja");
  const imports = dashboard.imports.filter((record) =>
    `${record.import_id} ${record.source_path}`.toLocaleLowerCase("ja").includes(importNeedle),
  );
  const normalizationNeedle = queries.normalizations.trim().toLocaleLowerCase("ja");
  const normalizations = dashboard.normalizations.filter((record) =>
    `${record.normalization_id} ${record.source_file_id} ${record.mapping_id}`
      .toLocaleLowerCase("ja")
      .includes(normalizationNeedle),
  );
  document.getElementById("dry-run-job-filter-count").textContent = `${Math.min(dryRunJobs.length, historyLimit)} / ${dryRunJobs.length}件`;
  document.getElementById("dry-run-filter-count").textContent = `${Math.min(dryRuns.length, historyLimit)} / ${dryRuns.length}件`;
  document.getElementById("import-filter-count").textContent = `${Math.min(imports.length, historyLimit)} / ${imports.length}件`;
  document.getElementById("normalization-filter-count").textContent = `${Math.min(normalizations.length, historyLimit)} / ${normalizations.length}件`;
  replace("dry-run-job-list", dryRunJobs.length
    ? dryRunJobs.slice(0, historyLimit).map((record) => jobButton("dry_run_job", record, selection.kind, selection.id, onSelect))
    : [empty("検証jobはありません。")] );
  replace("dry-run-list", dryRuns.length
    ? dryRuns.slice(0, historyLimit).map((record) => jobButton("dry_run", record, selection.kind, selection.id, onSelect))
    : [empty(dashboard.dryRunConfigured
      ? "ドライラン証跡はありません。"
      : "証跡rootは未設定です。")]);
  replace("import-list", imports.length
    ? imports.slice(0, historyLimit).map((record) => jobButton("import", record, selection.kind, selection.id, onSelect))
    : [empty("取込jobはありません。")] );
  replace("normalization-list", normalizations.length
    ? normalizations.slice(0, historyLimit).map((record) => jobButton("normalization", record, selection.kind, selection.id, onSelect))
    : [empty("正規化jobはありません。")] );
}

export function renderMappingDryRunJobDetail(job) {
  document.getElementById("dry-run-job-title").textContent = job.source_path;
  document.getElementById("dry-run-job-id").textContent = job.job_id;
  replace("dry-run-job-status", [pill(job.status)]);
  replace("dry-run-job-lineage", [
    lineage("管理対象相対path", job.source_path),
    lineage("列mapping", job.mapping_id),
    lineage("検査行上限", String(job.sample_rows)),
    lineage("登録者", job.requested_by),
    lineage("登録日時", dateTime(job.requested_at)),
    lineage("完了日時", dateTime(job.finished_at)),
    lineage("判定", job.outcome ? decisionLabel(job.outcome) : null),
    lineage("report SHA-256", job.report_sha256),
    lineage("エラーcode", job.error_code),
  ]);
  const messages = {
    QUEUED: "Workerの処理を待っています。更新すると最新状態を確認できます。",
    RUNNING: "管理対象CSVを検査しています。原値は証跡へ保存しません。",
    FAILED: "実行基盤で処理できませんでした。エラーcodeを確認してください。",
    SUCCEEDED: "検査証跡を作成しました。下のボタンからこのジョブの判定を確認できます。",
  };
  document.getElementById("dry-run-job-message").textContent = messages[job.status] || "—";
  const progress = document.getElementById("validation-progress");
  progress.className = `validation-progress${job.status === "FAILED" ? " error" : ["QUEUED", "RUNNING"].includes(job.status) ? " warning" : ""}`;
  progress.textContent = messages[job.status] || "検証状態を確認してください。";
  const reportButton = document.getElementById("dry-run-job-report-button");
  reportButton.dataset.reportSha256 = job.report_sha256 || "";
  reportButton.dataset.blocked = String(!job.report_sha256);
  reportButton.disabled = !job.report_sha256;
  reportButton.hidden = !job.report_sha256;
  showDetail("dry_run_job");
}

function dryRunObservationCards(observations) {
  const records = [
    ["検査行", observations.sampled_rows],
    ["採用行", observations.accepted_rows],
    ["隔離行", observations.quarantined_rows],
    ["サンプル打切り", observations.truncated ? "あり" : "なし"],
  ];
  return records.map(([label, value]) => node("article", { className: "reconciliation-card" }, [
    node("span", { text: label }),
    node("strong", { text: String(value) }),
  ]));
}

const checkHelp = {
  MAPPING_CONTRACT: ["列の対応付け", "必須項目、利用可能時点、更新方式を確認してください。"],
  SOURCE_PATH_SAFE: ["CSVの保存場所", "管理対象フォルダー内のCSVを選び直してください。"],
  SOURCE_SIZE_LIMIT: ["CSVのファイルサイズ", "空ファイル、またはサイズ上限を超えていないか確認してください。"],
  SOURCE_ENCODING: ["CSVの文字コード", "UTF-8またはCP932で保存し直してください。"],
  HEADER_UNIQUE: ["列名の重複", "同じ列名を一つに整理してください。"],
  REQUIRED_COLUMNS: ["必要な列", "CSVの列名と選択した対応付けを見直してください。"],
  SAMPLE_ROWS: ["データ行", "ヘッダー以外のデータ行があるか確認してください。"],
  SAMPLE_ACCEPTANCE: ["行データの品質", "隔離理由を確認し、該当する値を修正してください。"],
  QUANTITY_RECONCILIATION: ["数量の整合性", "採用数量と隔離数量に説明できない差がないか確認してください。"],
};

function renderResultGuidance(report) {
  const guidance = document.getElementById("dry-run-guidance");
  const values = {
    READY_FOR_NORMALIZATION: ["検証に合格しました", "このCSVは正規化へ進めます。次に原本取込を実行してください。", ""],
    REVIEW_REQUIRED: ["修正をおすすめします", "一部の行が隔離対象です。隔離理由を確認してCSVを修正し、もう一度検証してください。", "warning"],
    BLOCKED: ["このままでは処理できません", "不合格の検査項目にある確認・修正方法を実施してから、もう一度検証してください。", "error"],
  };
  const [title, message, tone] = values[report.outcome] || ["判定を確認してください", "検査項目の結果を確認してください。", "warning"];
  guidance.className = `result-guidance${tone ? ` ${tone}` : ""}`;
  guidance.replaceChildren(node("h3", { text: title }), node("p", { text: message }));
}

export function renderMappingDryRunDetail(report) {
  document.getElementById("dry-run-title").textContent = dateTime(report.checked_at);
  document.getElementById("dry-run-id").textContent = report.dry_run_id;
  replace("dry-run-status", [pill(report.outcome)]);
  replace("dry-run-lineage", [
    lineage("report SHA-256", report.report_sha256),
    lineage("mapping ID", report.mapping_id),
    lineage("原本 SHA-256", report.source_sha256),
    lineage("sample上限", String(report.limits.sample_rows)),
    lineage("原本size上限", bytes(report.limits.max_source_bytes)),
    lineage("mapping size上限", bytes(report.limits.max_mapping_bytes)),
  ]);
  replace("dry-run-observations", dryRunObservationCards(report.observations));
  renderResultGuidance(report);
  const progress = document.getElementById("validation-progress");
  progress.className = `validation-progress${report.outcome === "BLOCKED" ? " error" : report.outcome === "REVIEW_REQUIRED" ? " warning" : ""}`;
  progress.textContent = report.outcome === "READY_FOR_NORMALIZATION"
    ? "検証に合格しました。結果の詳細を確認し、原本取込へ進めます。"
    : report.outcome === "REVIEW_REQUIRED"
      ? "修正をおすすめする行があります。隔離理由を確認してください。"
      : "処理を停止する問題があります。不合格項目の修正方法を確認してください。";
  replace("dry-run-check-list", report.checks.map((check) => node("tr", {}, [
    node("td", { className: "check-name" }, [
      node("strong", { text: (checkHelp[check.check_id] || [check.check_id])[0] }),
      node("code", { text: check.check_id }),
    ]),
    node("td", {}, [pill(check.status)]),
    node("td", { text: check.status === "PASSED" ? "問題ありません。" : (checkHelp[check.check_id] || ["", "入力内容を確認してください。"])[1] }),
  ])));
  const reasons = Object.entries(report.observations.quarantine_reason_counts);
  replace("dry-run-reason-list", reasons.length
    ? reasons.map(([reason, count]) => node("article", { className: "record-item" }, [
      node("header", {}, [node("strong", { text: reason }), node("span", { text: `${count}件` })]),
    ]))
    : [empty("サンプル内の隔離理由はありません。")]);
  replace("dry-run-limitation-list", report.limitations.map((value) => node("li", { text: value })));
  showDetail("dry_run");
}

function sourceRows(files) {
  return files.map((file) => node("tr", {}, [
    node("td", {}, [node("strong", { text: file.logical_path }), node("code", { text: shortId(file.source_file_id, 20), title: file.source_file_id })]),
    node("td", {}, [pill(file.status)]),
    node("td", { text: file.encoding || "—" }),
    node("td", { text: bytes(file.size_bytes) }),
    node("td", { className: "source-lineage" }, [
      node("code", { text: file.sha256, title: file.sha256 }),
      node("code", { text: file.correction_of ? `訂正元 ${file.correction_of}` : file.duplicate_of ? `重複元 ${file.duplicate_of}` : "初回" }),
    ]),
    node("td", { className: "row-error", text: file.error || "—" }),
  ]));
}

function selectionRecords(selections, paths) {
  const records = selections.filter((selection) => paths.has(selection.logical_path));
  if (!records.length) return [empty("採用履歴はありません。")];
  return [...records].reverse().map((selection) => node("article", { className: "record-item" }, [
    node("header", {}, [node("strong", { text: selection.decision_version }), node("span", { text: selection.logical_path })]),
    node("code", { text: selection.source_file_id, title: selection.source_file_id }),
    node("p", { text: `${selection.decided_by} / ${dateTime(selection.decided_at)}` }),
    node("p", { text: selection.reason }),
  ]));
}

function currentSources(files, selections) {
  const latest = new Map();
  for (const selection of selections) latest.set(selection.logical_path, selection.source_file_id);
  return files.filter((file) => {
    if (!["ACCEPTED", "CORRECTION_CANDIDATE"].includes(file.status)) return false;
    const selected = latest.get(file.logical_path);
    return selected ? selected === file.source_file_id : file.status === "ACCEPTED";
  });
}

export function renderImportDetail(record, dashboard) {
  document.getElementById("import-title").textContent = record.source_path;
  document.getElementById("import-id").textContent = record.import_id;
  replace("import-status", [pill(record.status)]);
  replace("import-lineage", [
    lineage("管理対象相対path", record.source_path),
    lineage("原本数", String(record.file_count)),
    lineage("採用・訂正版候補", String(record.accepted_count)),
    lineage("隔離", String(record.quarantined_count)),
    lineage("重複", String(record.duplicate_count)),
    lineage("処理エラー", record.error),
  ]);
  replace("source-file-list", record.files.length
    ? sourceRows(record.files)
    : [tableEmpty(6, "Worker完了後に原本を表示します。")] );
  const eligible = record.files.filter((file) =>
    ["ACCEPTED", "CORRECTION_CANDIDATE"].includes(file.status),
  );
  fillSelect(
    "source-selection-file",
    eligible,
    "採用する原本を選択",
    (file) => file.source_file_id,
    (file) => `${file.logical_path} / ${decisionLabel(file.status)} / ${shortId(file.source_file_id, 14)}`,
  );
  fillSelect(
    "normalization-source-file",
    currentSources(record.files, dashboard.selections),
    "採用中の原本を選択",
    (file) => file.source_file_id,
    (file) => `${file.logical_path} / ${shortId(file.source_file_id, 14)}`,
  );
  fillSelect(
    "normalization-mapping",
    dashboard.mappings,
    "列mappingを選択",
    (mapping) => mapping.mapping_id,
    mappingLabel,
  );
  replace(
    "source-selection-list",
    selectionRecords(dashboard.selections, new Set(record.files.map((file) => file.logical_path))),
  );
  showDetail("import");
}

function reconciliationCards(value) {
  const records = [
    ["parseable quantity", value?.parseable_quantity],
    ["accepted quantity", value?.accepted_quantity],
    ["quarantined quantity", value?.quarantined_quantity],
    ["unexplained quantity", value?.unexplained_quantity],
  ];
  return records.map(([label, amount]) => node("article", { className: "reconciliation-card" }, [
    node("span", { text: label }),
    node("strong", { text: amount ?? "—" }),
  ]));
}

function normalizedRows(rows) {
  return rows.map((row) => node("tr", {}, [
    node("td", { text: String(row.row_number) }),
    node("td", {}, [pill(row.status)]),
    node("td", {}, [node("strong", { text: row.shipment_date || "—" }), node("code", { text: row.center_id || "—" })]),
    node("td", {}, [node("strong", { text: row.raw_jan || "—" }), node("span", { text: row.raw_product_name || "—" })]),
    node("td", { text: `${row.quantity ?? "—"} / ${row.unit || "—"}` }),
    node("td", { text: row.available_at || "—" }),
    node("td", { className: "row-error", text: row.error || "—" }),
  ]));
}

export function renderNormalizationDetail(summary, page) {
  document.getElementById("normalization-title").textContent = shortId(summary.normalization_id, 28);
  document.getElementById("normalization-id").textContent = summary.normalization_id;
  replace("normalization-status", [pill(summary.status)]);
  replace("normalization-lineage", [
    lineage("原本", summary.source_file_id),
    lineage("列mapping", summary.mapping_id),
    lineage("全行", String(summary.total_rows)),
    lineage("採用行", String(summary.accepted_rows)),
    lineage("隔離行", String(summary.quarantined_rows)),
    lineage("処理エラー", summary.error),
  ]);
  replace("reconciliation-grid", reconciliationCards(summary.reconciliation));
  const start = page.total ? page.offset + 1 : 0;
  const end = Math.min(page.offset + page.items.length, page.total);
  document.getElementById("row-page-count").textContent = `${start}〜${end} / ${metric(page.total)}件`;
  document.getElementById("row-previous").dataset.blocked = String(page.offset === 0);
  document.getElementById("row-next").dataset.blocked = String(
    page.offset + page.limit >= page.total,
  );
  replace("normalized-row-list", page.items.length
    ? normalizedRows(page.items)
    : [tableEmpty(7, "条件に一致する正規化行はありません。")] );
  showDetail("normalization");
}

export function showDetail(kind = null) {
  document.getElementById("detail-empty").hidden = Boolean(kind);
  document.getElementById("dry-run-job-detail").hidden = kind !== "dry_run_job";
  document.getElementById("dry-run-detail").hidden = kind !== "dry_run";
  document.getElementById("import-detail").hidden = kind !== "import";
  document.getElementById("normalization-detail").hidden = kind !== "normalization";
}
