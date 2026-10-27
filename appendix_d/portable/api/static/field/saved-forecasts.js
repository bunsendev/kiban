import { api, el, button, displayTime } from "./api.js";

export async function savedForecasts(parent, open) {
  const panel = el("section", "", parent);
  panel.className = "saved-forecasts";
  el("h2", "保存済みの予測を見る", panel);
  el("p", "別の倉庫に不足データがあっても、作成済みの結果はここから確認できます。保存当時の在庫基準日と予測期間を確認してください。", panel);
  const status = el("p", "読み込み中です", panel);
  status.setAttribute("role", "status");
  const controls = el("div", "", panel);
  const warehouse = el("select", "", el("label", "倉庫", controls));
  el("option", "すべての倉庫", warehouse).value = "";
  const version = el("select", "", el("label", "保存した予測", controls));
  const show = button("この予測を見る", async () => {
    const item = entries[Number(version.value)];
    if (!item) return;
    show.disabled = true;
    try { await open(item); }
    catch (e) { status.textContent = e.message; }
    finally { show.disabled = !entries.length; }
  }, controls);
  button("一覧を更新", () => refresh(), panel, true);
  const more = button("さらに表示", () => refresh(true), controls, true);
  let entries = [], generation = 0;
  async function refresh(append = false) {
    const token = ++generation;
    const chosen = warehouse.value;
    show.disabled = true;
    status.textContent = "保存済みの完成した予測を確認しています";
    try {
      const value = await api("/api/saved-forecasts?" + new URLSearchParams({
        warehouse: chosen, offset: String(append ? entries.length : 0), limit: "50",
      }));
      if (token !== generation) return;
      entries = append ? entries.concat(value.items) : value.items;
      warehouse.replaceChildren();
      el("option", "すべての倉庫", warehouse).value = "";
      value.warehouses.forEach(w => { el("option", w, warehouse).value = w; });
      warehouse.value = chosen;
      version.replaceChildren();
      entries.forEach((item, i) => {
        el("option", `${item.provisional?'暫定予測／':''}${item.warehouse}／在庫基準日 ${item.inventory_date || "未確認"}／予測 ${item.period.join(" ～ ")}／${item.series_count}商品／作成 ${displayTime(item.created_at)}`, version).value = String(i);
      });
      show.disabled = !entries.length;
      more.hidden = entries.length >= value.total;
      controls.hidden = !value.warehouses.length;
      status.textContent = entries.length ? `保存版 ${entries.length}件を表示。現在の取込を変更せず、結果の表示・CSV保存・フィードバックができます。` : "条件に合う完成した保存版はありません。未完了・条件不足のデータを予測済みとして表示しません。";
      if (value.unavailable_count) status.textContent += ` 整合性を確認できない保存版 ${value.unavailable_count}件は表示していません。`;
    } catch (e) {
      if (token !== generation) return;
      entries = []; version.replaceChildren(); show.disabled = true;
      status.textContent = e.message;
    }
  }
  warehouse.onchange = () => refresh();
  await refresh();
  return refresh;
}
