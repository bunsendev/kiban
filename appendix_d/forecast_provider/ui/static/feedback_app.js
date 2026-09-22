import { ApiError, clearToken, setToken } from "./api.js";
import { downloadFeedback, loadFeedback } from "./feedback_api.js";
import { renderFeedback } from "./feedback_render.js";

const byId = (id) => document.getElementById(id);
let busy = false;

function notice(message, tone = "") {
  byId("notice").className = `notice${tone ? ` ${tone}` : ""}`;
  byId("notice").textContent = message;
}

function setBusy(value) {
  busy = value;
  document.body.setAttribute("aria-busy", String(value));
  for (const control of document.querySelectorAll("button, input, select")) {
    control.disabled = value;
  }
}

async function refresh() {
  if (busy) return false;
  setBusy(true);
  notice("操作記録を集計しています。");
  try {
    const dashboard = await loadFeedback(Number(byId("period-days").value));
    byId("session-identity").textContent = `${dashboard.session.subject} / ${dashboard.session.roles.join(", ")}`;
    renderFeedback(dashboard.summary, dashboard.events);
    byId("feedback-content").hidden = false;
    notice("最新の操作記録を表示しています。", "success");
    return true;
  } catch (error) {
    const message = error instanceof ApiError && error.status === 403
      ? "操作改善レポートを閲覧する権限がありません。"
      : error.message || "操作記録を読み込めませんでした。";
    notice(message, "error");
    return false;
  } finally {
    setBusy(false);
  }
}

byId("connection-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  setToken(byId("api-token").value);
  if (await refresh()) {
    byId("connection-form").hidden = true;
    byId("session-controls").hidden = false;
    byId("api-token").value = "";
  }
});
byId("refresh-button").addEventListener("click", refresh);
byId("period-days").addEventListener("change", refresh);
byId("export-button").addEventListener("click", async () => {
  setBusy(true);
  try {
    await downloadFeedback(Number(byId("period-days").value));
    notice("操作ログCSVを出力しました。", "success");
  } catch (error) {
    notice(error.message || "CSVを出力できませんでした。", "error");
  } finally {
    setBusy(false);
  }
});
byId("disconnect-button").addEventListener("click", () => {
  clearToken();
  byId("connection-form").hidden = false;
  byId("session-controls").hidden = true;
  byId("feedback-content").hidden = true;
  notice("管理者用の接続コードを入力してください。");
});
