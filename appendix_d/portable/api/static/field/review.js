import { api, el, button, field, download, displayTime, saveWithNotice } from "./api.js";
import { results } from "./results.js";

export async function review(ctx, row) {
  ctx.enter(4);
  ctx.root.className = "review-screen";
  el("h1", "予測量の確認・判断を保存", ctx.root);
  el("h2", `${row.name}／${row.jan}／${row.warehouse}`, ctx.root);
  const metrics = el("div", "", ctx.root);
  metrics.className = "review-metrics";
  el(
    "p",
    `在庫基準日時 ${displayTime(row.inventory_date)}／現在庫 ${row.inventory ?? "未計算"} ${row.unit}`,
    metrics,
  );
  el(
    "p",
    row.forecast === null
      ? "この商品は予測できません"
      : `元の期間予測 ${row.forecast.toLocaleString()} ${row.unit}（${row.period.join(" ～ ")}）`,
    metrics,
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
  if (row.edit_state && !row.edit_state.editable) el("p", row.edit_state.reason, ctx.root);
  const f = el("form", "", ctx.root),
    actor = field(f, "担当者");
  actor.maxLength = 100;
  actor.parentElement.className = "review-actor";
  actor.value =
    row.review?.actor || sessionStorage.getItem("field-actor") || "";
  const label = el("fieldset", "", f);
  label.className = "decision-options";
  el("legend", "現場の判断", label);
  const choice = {
    value: row.review?.choice || (row.edit_state?.editable === false || row.forecast === null ? "HOLD" : "ACCEPT"),
  };
  for (const [key, text] of [
    ["ACCEPT", "この予測量を確認した"],
    ["CHANGE", "数量を修正する"],
    ["HOLD", "情報不足・判断できないため保留"],
  ]) {
    const optionLabel = el("label", "", label);
    const option = el("input", "", optionLabel);
    option.type = "radio";
    option.name = "decision";
    option.value = key;
    option.disabled = (row.forecast === null && key !== "HOLD") || (key === "CHANGE" && row.edit_state?.editable === false);
    option.checked = choice.value === key;
    optionLabel.append(document.createTextNode(text));
    option.onchange = () => {
      choice.value = key;
      sync();
    };
  }
  choice.value =
    row.review?.choice || (row.edit_state?.editable === false || row.forecast === null ? "HOLD" : "ACCEPT");
  const quantity = field(f, `修正後の期間合計（${row.unit}）`, "number", false);
  quantity.min = 0;
  quantity.step = "any";
  quantity.value = row.review?.quantity ?? "";
  const reason = field(f, "数量変更・保留の理由", "text", false);
  reason.parentElement.className = "review-reason";
  reason.maxLength = 500;
  reason.value = row.review?.reason || "";
  const cl = el("label", "気づいたこと・改善してほしいこと（任意）", f),
    comment = el("textarea", "", cl);
  cl.className = "review-comment";
  comment.maxLength = 1000;
  comment.value = row.review?.comment || "";
  const state = el(
    "p",
    row.review ? `保存済み：${row.review.created_at}` : "未確認",
    f,
  );
  state.setAttribute("role", "status");
  function sync() {
    quantity.disabled = choice.value !== "CHANGE" || row.edit_state?.editable === false;
    quantity.required = choice.value === "CHANGE";
    reason.required = choice.value !== "ACCEPT";
  }
  sync();
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
        await saveWithNotice(() => api(`/api/field/results/${ctx.resultId}/review`, {
          item: row.item,
          revision: row.review?.revision || 0,
          actor: actor.value,
          choice: choice.value,
          quantity: choice.value === "CHANGE" ? Number(quantity.value) : null,
          reason: reason.value,
          comment: comment.value,
        }), "担当者の判断を保存しました。次の確認へ進みます。");
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
  ctx.root.className = "finish-screen";
  el("div", counts.pending || counts.held ? "!" : "✓", ctx.root).className =
    "completion-icon";
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
  const endStatus=el("p","",ctx.root);endStatus.setAttribute("role","status");
  button("本日の作業を完了",()=>{
    endStatus.textContent="作業は保存済みです。ログの提出状況を確認しています…";
    const controller=new AbortController();const timer=setTimeout(()=>controller.abort(),20000);
    fetch('/api/operations/finish-day',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}',signal:controller.signal})
      .then(r=>{if(!r.ok)throw new Error();return r.json();})
      .then(v=>{endStatus.textContent=v.status==='COMPLETED'?'本日の作業は完了しました。ログを提出しました。':v.status==='LOCAL_ONLY'?'本日の作業は完了しました。ログはこのPCに保存しています。':'本日の作業は完了しました。未送信ログを保存しています。必要に応じIT担当者へご連絡ください。';})
      .catch(()=>{endStatus.textContent='本日の作業は完了しました。送信状況は次回確認します。保存済みの作業は残っています。';})
      .finally(()=>clearTimeout(timer));
  },ctx.root);
}
