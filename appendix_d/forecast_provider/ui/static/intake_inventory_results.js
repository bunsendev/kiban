const cell = (value) => {
  const element = document.createElement("td");
  element.textContent = value;
  return element;
};

export function renderInventoryNormalizationResults(
  container,
  jobId,
  job,
  results,
  download,
  options = {},
) {
  container.replaceChildren();
  const reasons = Object.entries(job.reason_counts)
    .map(([code, count]) => `${code}: ${count.toLocaleString("ja-JP")}行`)
    .join("、") || "なし";

  const summary = document.createElement("p");
  summary.textContent = [
    `${job.file_count.toLocaleString("ja-JP")}ファイルの処理が完了しました。`,
    `採用 ${job.accepted_row_count.toLocaleString("ja-JP")}行、隔離 ${job.quarantined_row_count.toLocaleString("ja-JP")}行。`,
    `正規化結果 ${results.total.toLocaleString("ja-JP")}件。`,
    results.reconciled ? "採用した元数量と正規化後数量は一致しています。" : "数量照合が一致しません。",
    `隔離理由: ${reasons}。`,
    `画面には先頭${results.items.length.toLocaleString("ja-JP")}件を表示しています。`,
  ].join(" ");
  container.append(summary);

  const table = document.createElement("table");
  const header = document.createElement("tr");
  ["在庫日", "JAN", "倉庫コード", "単位", "数量"].forEach((label) => {
    const heading = document.createElement("th");
    heading.scope = "col";
    heading.textContent = label;
    header.append(heading);
  });
  table.append(header);
  results.items.forEach((item) => {
    const row = document.createElement("tr");
    row.append(
      cell(item.inventory_date),
      cell(item.jan),
      cell(item.center_id),
      cell(item.unit),
      cell(item.quantity),
    );
    table.append(row);
  });
  container.append(table);

  const button = document.createElement("button");
  button.className = "button secondary";
  button.type = "button";
  button.textContent = "正規化結果CSVをダウンロード";
  button.addEventListener("click", () => download(
    `/api/inventory-normalization-jobs/${encodeURIComponent(jobId)}/results.csv`,
    `inventory-normalized-${jobId}.csv`,
  ));
  container.append(button);

  const history = document.createElement("p");
  const decisions = options.decisions || [];
  history.textContent = decisions.length
    ? `判断履歴: ${decisions.map((item) => `${item.decision_version} ${item.decision}`).join("、")}`
    : "判断履歴はありません。";
  container.append(history);

  if (!options.canApprove) return;
  const form = document.createElement("form");
  form.className = "drawer-form compact-form";
  const version = document.createElement("input");
  version.required = true;
  version.maxLength = 100;
  version.value = `inventory-${jobId.slice(0, 8)}-v1`;
  const decision = document.createElement("select");
  const approved = document.createElement("option");
  approved.value = "APPROVED";
  approved.textContent = "採用";
  approved.disabled = !results.reconciled || job.quarantined_row_count !== 0;
  const rejected = document.createElement("option");
  rejected.value = "REJECTED";
  rejected.textContent = "却下";
  decision.append(approved, rejected);
  decision.value = approved.disabled ? "REJECTED" : "APPROVED";
  const reason = document.createElement("textarea");
  reason.required = true;
  reason.maxLength = 1000;
  reason.rows = 2;
  reason.placeholder = "数量照合と隔離理由を確認した根拠";
  const submit = document.createElement("button");
  submit.className = "button primary";
  submit.type = "submit";
  submit.textContent = "判断を記録";
  [
    ["decision version", version],
    ["判断", decision],
    ["理由", reason],
  ].forEach(([labelText, control]) => {
    const label = document.createElement("label");
    label.append(document.createTextNode(labelText), control);
    form.append(label);
  });
  form.append(submit);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    submit.disabled = true;
    try {
      await options.createDecision(jobId, {
        decision_version: version.value.trim(),
        decision: decision.value,
        reason: reason.value.trim(),
      });
      await options.onChanged();
    } catch (error) {
      options.onError(error);
    } finally {
      submit.disabled = false;
    }
  });
  container.append(form);
}

export function renderInventoryNormalizationHistory(container, jobs, current, onOpen) {
  container.replaceChildren();
  jobs.forEach((job) => {
    const button = document.createElement("button");
    button.className = "record-item";
    button.type = "button";
    button.textContent = [
      `${job.status} / ${job.processed_file_count} of ${job.file_count || "—"} files`,
      `採用 ${job.accepted_row_count}行・隔離 ${job.quarantined_row_count}行`,
      current?.job_id === job.job_id ? "現在の採用版" : "",
    ].filter(Boolean).join(" / ");
    button.addEventListener("click", () => onOpen(job));
    container.append(button);
  });
}

export function renderInventoryFeatureView(container, view, download) {
  container.hidden = false;
  container.textContent = [
    `判定: ${view.status}。`,
    `在庫行 ${view.source_row_count.toLocaleString("ja-JP")}件、canonical商品へ解決 ${view.resolved_row_count.toLocaleString("ja-JP")}件。`,
    `未対応 ${view.missing_mapping_count.toLocaleString("ja-JP")}件、期間競合 ${view.ambiguous_mapping_count.toLocaleString("ja-JP")}件。`,
    `利用可能時刻: ${view.available_at}。`,
    view.status === "READY" ? `特徴ビューID: ${view.view_id}` : "JAN名寄せ版を修正してください。",
  ].join(" ");
  if (view.status !== "READY") return;
  const button = document.createElement("button");
  button.className = "button secondary";
  button.type = "button";
  button.textContent = "在庫特徴CSVをダウンロード";
  const params = new URLSearchParams({
    mapping_version: view.mapping_version,
    as_of: view.as_of,
  });
  button.addEventListener("click", () => download(
    `/api/inventory-feature-views.csv?${params}`,
    `inventory-feature-${view.view_id}.csv`,
  ));
  container.append(button);
}
