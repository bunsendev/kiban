const byId = (id) => document.getElementById(id);

const CHECK_LABELS = {
  MAPPING_CONTRACT: "列設定",
  SOURCE_PATH_SAFE: "ファイルの場所",
  SOURCE_SIZE_LIMIT: "ファイル容量",
  SOURCE_ENCODING: "文字コード",
  HEADER_UNIQUE: "列名の重複",
  REQUIRED_COLUMNS: "必要な列",
  SAMPLE_ROWS: "データ行",
  SAMPLE_ACCEPTANCE: "行データの内容",
  QUANTITY_RECONCILIATION: "数量の整合性",
};

const OUTCOME_PRESENTATION = {
  READY_FOR_NORMALIZATION: {
    tone: "success",
    title: "データを利用できます",
    message: "確認した範囲では問題ありません。次の予測実行へ進める状態です。",
  },
  REVIEW_REQUIRED: {
    tone: "warning",
    title: "一部のデータを確認してください",
    message: "利用できる行はありますが、修正をおすすめする行が含まれています。",
  },
  BLOCKED: {
    tone: "error",
    title: "データを修正してやり直してください",
    message: "問題項目を修正し、ファイルを選び直してもう一度分析してください。",
  },
};

function metric(id, value) {
  byId(id).textContent = Number(value || 0).toLocaleString("ja-JP");
}

function setIssues(items) {
  const list = byId("result-issues");
  if (!items.length) {
    const item = document.createElement("li");
    item.textContent = "確認が必要な項目はありません。";
    list.replaceChildren(item);
    return;
  }
  list.replaceChildren(...items.map((text) => {
    const item = document.createElement("li");
    item.textContent = text;
    return item;
  }));
}

function showResult(title, message, tone) {
  byId("result-state").className = `easy-result-state ${tone}`;
  byId("result-title").textContent = title;
  byId("result-message").textContent = message;
}

export function renderEasyProgress(status) {
  const running = status === "RUNNING";
  showResult(
    running ? "データを確認しています" : "分析の順番を待っています",
    running
      ? "ファイルの形式、列、行データを確認しています。画面を閉じずにお待ちください。"
      : "受付は完了しています。処理が始まるまでそのままお待ちください。",
    "progress",
  );
  byId("result-metrics").hidden = true;
  byId("result-detail").hidden = true;
  byId("result-refresh").hidden = false;
}

export function renderEasyFailure(message, canRetry = true) {
  showResult("分析結果を取得できませんでした", message, "error");
  byId("result-metrics").hidden = true;
  byId("result-detail").hidden = false;
  setIssues(["画面のメッセージと受付番号を管理担当者へ連絡してください。"]);
  byId("result-refresh").hidden = !canRetry;
}

export function renderEasyReport(report) {
  const presentation = OUTCOME_PRESENTATION[report.outcome] || {
    tone: "warning",
    title: "判定結果を確認してください",
    message: "詳細を管理担当者へ確認してください。",
  };
  const observations = report.observations || {};
  showResult(presentation.title, presentation.message, presentation.tone);
  metric("result-sampled", observations.sampled_rows);
  metric("result-accepted", observations.accepted_rows);
  metric("result-quarantined", observations.quarantined_rows);
  const failed = (report.checks || []).filter((check) => check.status === "FAILED");
  setIssues(failed.map((check) => `${CHECK_LABELS[check.check_id] || check.check_id}を確認してください。`));
  byId("result-metrics").hidden = false;
  byId("result-detail").hidden = false;
  byId("result-refresh").hidden = true;
}

export function renderEasyBatch(batch) {
  const failed = batch.counts?.FAILED || 0;
  const blocked = batch.outcomes?.BLOCKED || 0;
  const review = batch.outcomes?.REVIEW_REQUIRED || 0;
  const ready = batch.outcomes?.READY_FOR_NORMALIZATION || 0;
  const tone = failed || blocked ? "error" : review ? "warning" : "success";
  const title = tone === "success"
    ? "すべての対象ファイルを利用できます"
    : tone === "warning"
      ? "確認が必要なファイルがあります"
      : "利用できないファイルがあります";
  showResult(title, `${batch.selected_count}ファイルの確認が完了しました。`, tone);
  metric("result-sampled", batch.selected_count);
  metric("result-accepted", ready);
  metric("result-quarantined", review + blocked + failed);
  const issues = [];
  if (review) issues.push(`修正をおすすめするファイル: ${review}件`);
  if (blocked) issues.push(`処理できないファイル: ${blocked}件`);
  if (failed) issues.push(`分析処理に失敗したファイル: ${failed}件`);
  setIssues(issues);
  byId("result-metrics").hidden = false;
  byId("result-detail").hidden = false;
  byId("result-refresh").hidden = true;
}
