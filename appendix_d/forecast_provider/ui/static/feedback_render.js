const byId = (id) => document.getElementById(id);

const EVENT_LABELS = {
  CONNECTED: "接続完了",
  SOURCE_MODE_CHANGED: "選択方法を変更",
  SOURCE_SELECTED: "データを選択",
  SOURCE_CLEARED: "データを選び直し",
  ANALYSIS_REQUESTED: "分析ボタンを実行",
  ANALYSIS_ACCEPTED: "分析を受付",
  ANALYSIS_FAILED: "分析に失敗",
  ANALYSIS_RESULT_READY: "結果を表示",
  ANALYSIS_RESULT_FAILED: "結果取得に失敗",
  STEP_VIEWED: "手順を表示",
  STEP_COMPLETED: "手順を完了",
  SOURCE_LIST_REFRESHED: "指定フォルダを更新",
  STAGE_COMPLETED: "処理を完了",
};
const ERROR_LABELS = {
  mapping_not_found: "列設定が見つからない",
  unexpected: "予期しないエラー",
};
const DROP_OFF_LABELS = {
  connected_without_selection: "接続後にデータを選ばなかった",
  selected_without_request: "データ選択後に分析を押さなかった",
  requested_without_acceptance: "分析を押したが受付完了しなかった",
  accepted_without_result: "受付後に結果を表示できなかった",
  sessions_with_reselection: "データを選び直した",
  sessions_with_failure: "分析中に失敗した",
};
const STAGE_LABELS = {
  source_prepare: "保存・内容確認",
  mapping_resolution: "列設定の判定",
  analysis_submission: "分析受付",
};

function node(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined) element.textContent = text;
  return element;
}

export function renderFeedback(summary, events) {
  const funnel = summary.funnel || {};
  byId("session-count").textContent = summary.session_count.toLocaleString("ja-JP");
  byId("selection-count").textContent = (funnel.SOURCE_SELECTED || 0).toLocaleString("ja-JP");
  byId("request-count").textContent = (funnel.ANALYSIS_REQUESTED || 0).toLocaleString("ja-JP");
  byId("accepted-count").textContent = (funnel.ANALYSIS_ACCEPTED || 0).toLocaleString("ja-JP");
  byId("result-ready-count").textContent = (funnel.ANALYSIS_RESULT_READY || 0).toLocaleString("ja-JP");
  renderFunnel(funnel);
  renderErrors(summary.error_kinds || {});
  renderDropOffs(summary.drop_offs || {});
  renderStageDurations(summary.stage_durations || {});
  renderRecommendations(summary);
  renderEvents(events);
}

function renderDropOffs(dropOffs) {
  const entries = Object.entries(DROP_OFF_LABELS);
  byId("drop-off-list").replaceChildren(...entries.map(([key, label]) => {
    const row = node("div", "feedback-list-item");
    row.append(node("span", "", label), node("strong", "", `${dropOffs[key] || 0}件`));
    return row;
  }));
}

function renderStageDurations(durations) {
  const entries = Object.entries(durations);
  if (!entries.length) {
    byId("stage-duration-list").replaceChildren(node("p", "empty-inline", "処理時間はまだ記録されていません。"));
    return;
  }
  byId("stage-duration-list").replaceChildren(...entries.map(([stage, value]) => {
    const row = node("div", "feedback-list-item");
    const p90 = value.p90_ms === null ? "—" : formatDuration(value.p90_ms);
    const median = value.median_ms === null ? "—" : formatDuration(value.median_ms);
    const failures = value.failure_count ? ` / 失敗 ${value.failure_count}件` : "";
    row.append(
      node("span", "", STAGE_LABELS[stage] || stage),
      node("strong", "", `中央値 ${median} / 遅い10% ${p90}${failures}`),
    );
    return row;
  }));
}

function renderRecommendations(summary) {
  const sessions = summary.session_count || 0;
  const dropOffs = summary.drop_offs || {};
  const errors = summary.error_kinds || {};
  const recommendations = [];
  if (sessions < 10) {
    recommendations.push(["データ収集中", "判断前に10セッション以上を目安に集めます。"]);
  }
  if (dropOffs.connected_without_selection > 0) {
    recommendations.push(["データ選択を確認", "接続後に止まる担当者がいます。説明文と選択ボタンの見つけやすさを確認します。"]);
  }
  if (dropOffs.selected_without_request > 0) {
    recommendations.push(["分析ボタンを確認", "データ選択後に止まっています。準備完了の表示と次の操作を明確にします。"]);
  }
  if (dropOffs.sessions_with_reselection > 0) {
    recommendations.push(["選択ミスを確認", "選び直しが発生しています。対象ファイルの説明や最新データの表示を改善します。"]);
  }
  if (dropOffs.accepted_without_result > 0) {
    recommendations.push(["結果表示を確認", "受付後に結果が表示されていません。Worker、処理時間、結果取得APIを確認します。"]);
  }
  if ((errors.mapping_not_found || 0) > 0) {
    recommendations.push(["列設定を追加", "列設定不足が発生しています。該当形式のmapping追加を優先します。"]);
  }
  for (const [stage, value] of Object.entries(summary.stage_durations || {})) {
    const threshold = stage === "source_prepare" ? 10_000 : 5_000;
    if ((value.p90_ms || 0) > threshold) {
      recommendations.push([`${STAGE_LABELS[stage] || stage}を高速化`, "遅い10%の処理時間が目安を超えています。待機表示と処理性能を確認します。"]);
    }
  }
  if (!recommendations.length) {
    recommendations.push(["大きなつまずきなし", "現在の期間では目立つ離脱や失敗はありません。継続して変化を確認します。"]);
  }
  byId("recommendation-list").replaceChildren(...recommendations.slice(0, 5).map(([title, detail]) => {
    const item = node("article", "recommendation-item");
    item.append(node("strong", "", title), node("p", "", detail));
    return item;
  }));
}

function formatDuration(milliseconds) {
  if (milliseconds < 1_000) return `${milliseconds}ms`;
  return `${(milliseconds / 1_000).toFixed(1)}秒`;
}

function renderFunnel(funnel) {
  const labels = [
    ["CONNECTED", "画面へ接続"],
    ["SOURCE_SELECTED", "データを選択"],
    ["ANALYSIS_REQUESTED", "分析を実行"],
    ["ANALYSIS_ACCEPTED", "分析を受付"],
    ["ANALYSIS_RESULT_READY", "結果を表示"],
  ];
  const maximum = Math.max(1, ...labels.map(([key]) => funnel[key] || 0));
  byId("funnel-list").replaceChildren(...labels.map(([key, label]) => {
    const row = node("div", "funnel-row");
    const track = node("div", "funnel-track");
    const value = node("div", "funnel-value");
    value.style.width = `${Math.round(((funnel[key] || 0) / maximum) * 100)}%`;
    track.append(value);
    row.append(node("span", "", label), track, node("strong", "funnel-count", String(funnel[key] || 0)));
    return row;
  }));
}

function renderErrors(errors) {
  const entries = Object.entries(errors).sort((left, right) => right[1] - left[1]);
  if (!entries.length) {
    byId("error-list").replaceChildren(node("p", "empty-inline", "記録された失敗はありません。"));
    return;
  }
  byId("error-list").replaceChildren(...entries.map(([kind, count]) => {
    const row = node("div", "feedback-list-item");
    row.append(node("span", "", ERROR_LABELS[kind] || kind), node("strong", "", `${count}件`));
    return row;
  }));
}

function renderEvents(events) {
  byId("event-count").textContent = `${events.length.toLocaleString("ja-JP")}件`;
  if (!events.length) {
    const row = node("tr");
    const cell = node("td", "", "操作記録はまだありません。");
    cell.colSpan = 6;
    row.append(cell);
    byId("event-list").replaceChildren(row);
    return;
  }
  byId("event-list").replaceChildren(...events.map((event) => {
    const row = node("tr");
    row.append(
      node("td", "", new Intl.DateTimeFormat("ja-JP", { dateStyle: "short", timeStyle: "short" }).format(new Date(event.received_at))),
      node("td", "", event.subject),
      node("td", "", EVENT_LABELS[event.event_name] || event.event_name),
      node("td", "", event.outcome === "FAILURE" ? "失敗" : event.outcome === "SUCCESS" ? "成功" : "情報"),
      node("td", "", event.metadata.source_mode === "folder" ? "指定フォルダ" : event.metadata.source_mode === "upload" ? "アップロード" : "—"),
      node("td", "", event.elapsed_ms === null ? "—" : `${(event.elapsed_ms / 1000).toFixed(1)}秒`),
    );
    return row;
  }));
}
