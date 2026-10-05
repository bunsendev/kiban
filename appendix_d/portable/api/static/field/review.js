import { api, el, button, field, download, displayTime } from "./api.js";
import { results } from "./results.js";

export async function review(ctx, row) {
  ctx.enter(4);
  el("h1", "4. 予測量の確認・判断を保存", ctx.root);
  el("h2", `${row.name}／${row.jan}／${row.warehouse}`, ctx.root);
  el(
    "p",
    `在庫基準日時 ${displayTime(row.inventory_date)}／現在庫 ${row.inventory ?? "未計算"} ${row.unit}`,
    ctx.root,
  );
  el(
    "p",
    row.forecast === null
      ? "この商品は予測できません"
      : `元の期間予測 ${row.forecast.toLocaleString()} ${row.unit}（${row.period.join(" ～ ")}）`,
    ctx.root,
  );
  el(
    "p",
    row.reasons.join("／") || "評価した範囲では注意なし",
    ctx.root,
  ).className = "notice";
  el(
    "p",
    "数量を修正しても元の予測は残ります。出荷数量の決定・実績登録ではありません。",
    ctx.root,
  );
  const f = el("form", "", ctx.root),
    actor = field(f, "担当者");
  actor.maxLength = 100;
  actor.value =
    row.review?.actor || sessionStorage.getItem("field-actor") || "";
  const label = el("label", "判断", f),
    choice = el("select", "", label);
  for (const [key, text] of [
    ["ACCEPT", "この予測量を確認した"],
    ["CHANGE", "数量を修正する"],
    ["HOLD", "情報不足・判断できないため保留"],
  ]) {
    const option = el("option", text, choice);
    option.value = key;
    option.disabled = row.forecast === null && key !== "HOLD";
  }
  choice.value =
    row.review?.choice || (row.forecast === null ? "HOLD" : "ACCEPT");
  const quantity = field(f, `修正後の期間合計（${row.unit}）`, "number", false);
  quantity.min = 0;
  quantity.step = "any";
  quantity.value = row.review?.quantity ?? "";
  const reason = field(f, "数量変更・保留の理由", "text", false);
  reason.maxLength = 500;
  reason.value = row.review?.reason || "";
  const cl = el("label", "気づいたこと・改善してほしいこと（任意）", f),
    comment = el("textarea", "", cl);
  comment.maxLength = 1000;
  comment.value = row.review?.comment || "";
  const state = el(
    "p",
    row.review ? `保存済み：${row.review.created_at}` : "未確認",
    f,
  );
  state.setAttribute("role", "status");
  function sync() {
    quantity.disabled = choice.value !== "CHANGE";
    quantity.required = choice.value === "CHANGE";
    reason.required = choice.value !== "ACCEPT";
  }
  sync();
  choice.onchange = sync;
  f.oninput = () => {
    ctx.dirty = true;
    state.textContent = "入力中・未保存";
  };
  const save = el("button", "保存して次へ", f);
  f.onsubmit = (e) => {
    e.preventDefault();
    save.disabled = true;
    ctx.run(async () => {
      try {
        await api(`/api/field/results/${ctx.resultId}/review`, {
          item: row.item,
          revision: row.review?.revision || 0,
          actor: actor.value,
          choice: choice.value,
          quantity: choice.value === "CHANGE" ? Number(quantity.value) : null,
          reason: reason.value,
          comment: comment.value,
        });
        ctx.dirty = false;
        sessionStorage.setItem("field-actor", actor.value);
        const v = await api(`/api/field/results/${ctx.resultId}/next-review`);
        if (v.row) await review(ctx, v.row);
        else await finish(ctx, v.counts);
      } catch (e) {
        state.textContent = e.message;
        throw e;
      } finally {
        save.disabled = false;
      }
    });
  };
  button(
    "一覧に戻る",
    () =>
      ctx.run(async () => {
        if (ctx.dirty && !confirm("未保存の内容を破棄して戻りますか？")) return;
        ctx.dirty = false;
        await results(ctx);
      }),
    ctx.root,
    true,
  );
}
export async function finish(ctx, counts) {
  ctx.enter(4);
  ctx.dirty = false;
  el(
    "h1",
    counts.pending
      ? "確認作業を途中保存しています"
      : counts.held
        ? "今回の確認を保存しました（保留あり）"
        : "今回の確認を保存しました",
    ctx.root,
  );
  el(
    "p",
    `判断保存 ${counts.saved}件／保留 ${counts.held}件／未確認 ${counts.pending}件／個別確認対象外 ${counts.ok}件`,
    ctx.root,
  );
  el(
    "p",
    "確認の保存は、在庫不足や賞味期限リスクの解消・出荷完了を意味しません。未計算や保留の情報は引き続き残ります。",
    ctx.root,
  ).className = "notice";
  if (counts.pending)
    button(
      "未確認の判定を続ける",
      () =>
        ctx.run(async () => {
          const v = await api(`/api/field/results/${ctx.resultId}/next-review`);
          if (v.row) await review(ctx, v.row);
          else await finish(ctx, v.counts);
        }),
      ctx.root,
    );
  button(
    "結果をダウンロード",
    () =>
      ctx.run(() =>
        download(`/api/field/results/${ctx.resultId}/download`, {
          selected: null,
        }),
      ),
    ctx.root,
  );
  button("判断を見直す", () => ctx.run(() => results(ctx)), ctx.root, true);
  button(
    "未確定情報を確認する",
    () => ctx.run(() => ctx.open(ctx.analysisId)),
    ctx.root,
    true,
  );
  button("開始画面へ", () => ctx.run(() => ctx.home()), ctx.root, true);
}
