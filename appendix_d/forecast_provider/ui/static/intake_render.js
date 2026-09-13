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
  select.replaceChildren(node("option", { value: "", text: placeholder }));
  for (const record of records) {
    select.append(node("option", { value: valueOf(record), text: labelOf(record) }));
  }
  select.disabled = records.length === 0;
}

function bytes(value) {
  if (value === null || value === undefined) return "—";
  return new Intl.NumberFormat("ja-JP", { maximumFractionDigits: 1 }).format(value / 1024) + " KiB";
}

export function renderSummary(dashboard) {
  const files = dashboard.quality.files || {};
  document.getElementById("dry-run-count").textContent =
    `${dashboard.validDryRunCount || 0} / ${dashboard.invalidDryRunCount || 0}`;
  document.getElementById("import-count").textContent = dashboard.imports.length;
  document.getElementById("accepted-file-count").textContent =
    (files.ACCEPTED || 0) + (files.CORRECTION_CANDIDATE || 0);
  document.getElementById("review-file-count").textContent =
    (files.CORRECTION_CANDIDATE || 0) + (files.QUARANTINED || 0);
  document.getElementById("normalized-row-count").textContent =
    dashboard.normalizations.reduce((sum, job) => sum + job.accepted_rows, 0);
}

function jobButton(kind, record, selectedKind, selectedId, onSelect) {
  const isDryRun = kind === "dry_run";
  const id = isDryRun
    ? record.report_sha256
    : kind === "import" ? record.import_id : record.normalization_id;
  const title = isDryRun
    ? dateTime(record.checked_at)
    : kind === "import" ? record.source_path : shortId(record.normalization_id, 24);
  const detail = isDryRun
    ? `${record.observations.sampled_rows}行 / 採用 ${record.observations.accepted_rows} / 隔離 ${record.observations.quarantined_rows}`
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
  document.getElementById("dry-run-filter-count").textContent = `${dryRuns.length}件`;
  document.getElementById("import-filter-count").textContent = `${imports.length}件`;
  document.getElementById("normalization-filter-count").textContent = `${normalizations.length}件`;
  replace("dry-run-list", dryRuns.length
    ? dryRuns.map((record) => jobButton("dry_run", record, selection.kind, selection.id, onSelect))
    : [empty(dashboard.dryRunConfigured
      ? "ドライラン証跡はありません。"
      : "証跡rootは未設定です。")]);
  replace("import-list", imports.length
    ? imports.map((record) => jobButton("import", record, selection.kind, selection.id, onSelect))
    : [empty("取込jobはありません。")] );
  replace("normalization-list", normalizations.length
    ? normalizations.map((record) => jobButton("normalization", record, selection.kind, selection.id, onSelect))
    : [empty("正規化jobはありません。")] );
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
  replace("dry-run-check-list", report.checks.map((check) => node("tr", {}, [
    node("td", {}, [node("code", { text: check.check_id })]),
    node("td", {}, [pill(check.status)]),
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
    (mapping) => `${mapping.definition.availability_mode} / ${mapping.definition.file_mode} / ${shortId(mapping.mapping_id, 16)}`,
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
  document.getElementById("dry-run-detail").hidden = kind !== "dry_run";
  document.getElementById("import-detail").hidden = kind !== "import";
  document.getElementById("normalization-detail").hidden = kind !== "normalization";
}
