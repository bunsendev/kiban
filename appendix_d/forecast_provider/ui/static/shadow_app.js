import { installPkceLogin } from "./pkce.js";
import { ApiError, clearToken, request, setToken } from "./api.js";
import { loadShadowPreview } from "./shadow_api.js";
import { renderShadow } from "./shadow_render.js";

const byId = (id) => document.getElementById(id);
let busy = false;

function notice(message, tone = "") {
  byId("notice").className = `notice${tone ? ` ${tone}` : ""}`;
  byId("notice").textContent = message;
}

function setBusy(value) {
  busy = value;
  document.body.setAttribute("aria-busy", String(value));
  for (const button of document.querySelectorAll("button")) button.disabled = value;
}

function localDateTime() {
  const now = new Date();
  const local = new Date(now.getTime() - now.getTimezoneOffset() * 60000);
  return local.toISOString().slice(0, 16);
}

function payload() {
  const value = (id) => byId(id).value.trim();
  return {
    calculation_at: new Date(value("calculation-at")).toISOString(),
    pilot_scope_version: value("pilot-scope-version"),
    identity_bridge_version: value("identity-bridge-version"),
    forecast_run_id: value("forecast-run-id"),
    minimum_remaining_days: Number(value("minimum-remaining-days")),
    attention_days: Number(value("attention-days")),
    policy_confirmed_by: value("policy-confirmed-by"),
    policy_reason: value("policy-reason"),
    policy_confirmed_at: new Date(value("policy-confirmed-at")).toISOString(),
  };
}

async function refresh() {
  if (busy || !byId("preview-form").reportValidity()) return;
  setBusy(true);
  byId("result").hidden = true;
  notice("承認済み在庫と確定予測を照合しています。");
  try {
    const data = await loadShadowPreview(payload());
    renderShadow(data);
    notice(`${data.rows.length}件の参考値を表示しています。出荷指示ではありません。`, "success");
  } catch (error) {
    const message = error instanceof ApiError && error.status === 401
      ? "接続コードを確認してください。"
      : error instanceof ApiError && error.status === 403
        ? "閲覧権限がありません。"
        : error instanceof ApiError && error.status === 422
          ? "計算条件または承認済みデータがそろっていません。管理者に確認してください。"
          : error.message || "参考値を表示できませんでした。";
    notice(message, "error");
  } finally {
    setBusy(false);
  }
}

byId("calculation-at").value = localDateTime();
byId("connection-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  setToken(byId("api-token").value);
  try {
    const session = await request("/api/session");
    byId("session-identity").textContent = `${session.subject} / ${session.roles.join(", ")}`;
    byId("connection-form").hidden = true;
    byId("session-controls").hidden = false;
    byId("api-token").value = "";
    notice("接続しました。確認済みの計算条件を入力してください。", "success");
  } catch (error) {
    clearToken();
    notice(error.message || "接続できませんでした。", "error");
  }
});
byId("preview-form").addEventListener("submit", (event) => {
  event.preventDefault();
  refresh();
});
byId("refresh-button").addEventListener("click", refresh);
byId("disconnect-button").addEventListener("click", () => {
  clearToken();
  byId("connection-form").hidden = false;
  byId("session-controls").hidden = true;
  byId("result").hidden = true;
  notice("接続コードを入力してください。");
});
installPkceLogin();
