const byId = (id) => document.getElementById(id);

const EVENT_LABELS = {
  CONNECTED: "接続完了",
  SOURCE_MODE_CHANGED: "選択方法を変更",
  SOURCE_SELECTED: "データを選択",
  SOURCE_CLEARED: "データを選び直し",
  ANALYSIS_REQUESTED: "分析ボタンを実行",
  ANALYSIS_ACCEPTED: "分析を受付",
  ANALYSIS_FAILED: "分析に失敗",
  STEP_VIEWED: "手順を表示",
  STEP_COMPLETED: "手順を完了",
};
const ERROR_LABELS = {
  mapping_not_found: "列設定が見つからない",
  unexpected: "予期しないエラー",
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
  renderFunnel(funnel);
  renderErrors(summary.error_kinds || {});
  renderEvents(events);
}

function renderFunnel(funnel) {
  const labels = [
    ["CONNECTED", "画面へ接続"],
    ["SOURCE_SELECTED", "データを選択"],
    ["ANALYSIS_REQUESTED", "分析を実行"],
    ["ANALYSIS_ACCEPTED", "分析を受付"],
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
