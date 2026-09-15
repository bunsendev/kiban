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
}
