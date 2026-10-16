import { api, el, field, button, saveWithNotice } from "./api.js";

const fields = {
  shipment: ["出荷日", "JAN", "数量", "商品名", "倉庫", "基準日"],
  inventory: ["商品コード", "明細バラ数", "賞味期限", "商品名", "倉庫", "基準日"],
};

export async function folderReview(ctx, parent, refresh) {
  const candidates = await api("/api/drop-folder/review");

  const group = el("details", "", parent);
  el("summary", "読み取れないCSVの内容を確認・補足する", group);
  el("p", "ファイルは編集不要です。列の対応と不足情報を確認してください。", group);
  const actor = field(group, "確認者");
  const ai = el("details", "", group);
  el("summary", "AIに列の対応を提案してもらう（任意）", ai);
  el("p", "OpenAIへ送るのは対象CSVの列名だけです。明細・数量・ファイル名は送りません。APIの利用料金が発生します。キーはこのPCのWindowsユーザー専用に暗号化して保存できます。", ai);
  const key = field(ai, "OpenAI APIキー", "password", false);
  key.autocomplete = "off";
  let credentials = await api("/api/ai-credentials");
  const keyState = el("p", "", ai);
  function showKeyState() {
    keyState.textContent = credentials.available
      ? "APIキーは保存済みです。次回から入力せず使えます。"
      : credentials.saved ? "保存したキーを開けません。再設定してください。" : "APIキーは未保存です。";
  }
  showKeyState();
  button("このPCに保存・変更", () => ctx.run(async () => {
    credentials = await saveWithNotice(async () => {const v = await api("/api/ai-credentials", {api_key:key.value});if (!v.available) throw new Error("保存したキーを読み込めません");key.value = "";return v;}, "APIキーをこのPCに保存しました。読込も確認できました。接続確認は読み取り時に行います。");
    key.value = "";
    showKeyState();
  }), ai);
  const remove = field(ai, "保存済みのAPIキーを削除することを確認", "checkbox", false);
  button("保存したキーを削除", () => ctx.run(async () => {
    if (!remove.checked) throw new Error("キー削除の確認にチェックしてください");
    credentials = await saveWithNotice(() => api("/api/ai-credentials/delete", {confirm:true}), "保存したAPIキーを削除しました。");
    key.value = ""; remove.checked = false; showKeyState();
  }), ai, true);
  const consent = field(ai, "列名の送信に同意する", "checkbox", false);
  for (const c of candidates) {
    const box = el("details", "", group);
    el("summary", c.filename, box);
    if (c.error) { el("p", c.error, box); continue; }
    const kind = el("select", "", el("label", "ファイルの種類", box));
    for (const [v, label] of [["shipment", "出荷実績"], ["inventory", "倉庫在庫"]]) {
      const option = el("option", label, kind); option.value = v;
    }
    kind.value = c.approval?.kind || (c.headers.includes("賞味期限") ? "inventory" : "shipment");
    const mappingBox = el("div", "", box);
    let selections = {};
    function render(mapping = {}) {
      mappingBox.replaceChildren(); selections = {};
      for (const target of fields[kind.value]) {
        const select = el("select", "", el("label", `${target}に使う列`, mappingBox));
        const blank = el("option", "未指定", select); blank.value = "";
        for (const h of c.headers) { const o = el("option", h, select); o.value = h; }
        select.value = mapping[target] || (c.headers.includes(target) ? target : "");
        selections[target] = select;
      }
    }
    render(c.approval?.mapping);
    kind.onchange = () => render();
    const center = field(box, "倉庫（CSVに倉庫列がない場合）", "text", false);
    const day = field(box, "基準日（CSVに基準日列がない場合・次回に持ち越しません）", "date", false);
    center.value = c.approval?.center || ""; day.value = c.approval?.day || "";
    const remember = field(box, "同じ列構成で、この列対応を次回から再利用する", "checkbox", false);
    el("p", "数量の単位や換算は自動確定しません。取込後の確認画面で確認してください。", box);
    const state = el("p", "", box); state.setAttribute("role", "status");
    button("AIの列対応案を取得", () => ctx.run(async () => {
      credentials = await api("/api/ai-credentials");
      if ((!key.value && !credentials.available) || !consent.checked) throw new Error("APIキーと列名送信の同意を確認してください");
      state.textContent = "AIの提案を取得しています…";
      try {
        const result = await api("/api/drop-folder/ai-suggest", {
          filename: c.filename, sha256: c.sha256, api_key: key.value, consent: true,
        });
        if (!["SHIPMENT_ACTUAL", "WAREHOUSE_INVENTORY"].includes(result.kind)) {
          state.textContent = "出荷実績・倉庫在庫として特定できませんでした。手動で確認してください。"; return;
        }
        kind.value = result.kind === "SHIPMENT_ACTUAL" ? "shipment" : "inventory";
        const x = result.columns;
        render(kind.value === "shipment"
          ? { "出荷日": x.date, "JAN": x.jan, "数量": x.quantity, "商品名": x.product, "倉庫": x.location }
          : { "商品コード": x.product_code || x.jan, "明細バラ数": x.quantity, "賞味期限": x.expiry, "商品名": x.product, "倉庫": x.location, "基準日": x.date });
        state.textContent = "AIの提案です。列対応を確認してから保存してください。";
      } catch (e) { state.textContent = e.message; }
    }), box, true);
    button("この内容を確認して保存", () => ctx.run(async () => {
      const mapping = Object.fromEntries(Object.entries(selections)
        .filter(([, v]) => v.value).map(([k, v]) => [k, v.value]));
      await saveWithNotice(() => api("/api/drop-folder/approve", {
        filename: c.filename, sha256: c.sha256, kind: kind.value, mapping,
        center: center.value, day: day.value, actor: actor.value, remember: remember.checked,
      }), "列の対応と補足情報を保存しました。他のCSVも確認してください。");
      state.textContent = "保存しました。他のCSVも確認後、投入ファイルを確認してください。";
    }), box);
  }
  button("確認済みファイルを分析する", refresh, group);
}
