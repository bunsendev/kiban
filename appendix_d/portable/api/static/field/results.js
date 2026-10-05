import { api, el, button, download, displayTime } from "./api.js";
import { review, finish } from "./review.js";
const labels = {
  ACTION: "● 要対応",
  CHECK: "▲ 要確認",
  OK: "● 問題なし（評価した範囲）",
};
const choices = { ACCEPT: "確認済み", CHANGE: "数量修正", HOLD: "保留" };

export async function results(ctx) {
  ctx.enter(3);
  ctx.dirty = false;
  el("h1", "分析結果", ctx.root);
  el(
    "p",
    "保存した結果版を表示しています。基準日時と予測期間を確認してください。新しい入力の結果に自動で置き換わりません。",
    ctx.root,
  ).className = "muted";
  const endpoint = `/api/field/results/${ctx.resultId}`;
  el(
    "p",
    "期間全体の需要予測です。「今日送る数量」ではありません。修正は担当者の判断として別保存します。",
    ctx.root,
  );
  el(
    "p",
    "この画面では推奨出荷量を表示しません。配送・工場・安全在庫の条件を含む出荷判断は、詳細画面で確認してください。",
    ctx.root,
  ).className = "notice";
  const cards = el("div", "", ctx.root);
  cards.className = "cards";
  const completion = el("p", "", ctx.root);
  const inputIssues = el("details", "", ctx.root);
  const issuesTitle = el("summary", "未確認・除外した原本情報", inputIssues);
  const issuesBody = el("div", "", inputIssues);
  const actions = el("div", "", ctx.root);
  button(
    "要対応・要確認の判定へ",
    () =>
      ctx.run(async () => {
        const v = await api(endpoint + "/next-review");
        if (v.row) await review(ctx, v.row);
        else await finish(ctx, v.counts);
      }),
    actions,
  );
  button(
    "全件ダウンロード",
    () =>
      ctx.run(async () => {
        ctx.message("CSVを準備しています");
        await download(endpoint + "/download", { selected: null });
        ctx.message("ダウンロードを開始しました");
      }),
    actions,
    true,
  );
  const selected = new Set();
  const selectedButton = button(
    "選択分ダウンロード",
    () =>
      ctx.run(async () => {
        ctx.message("CSVを準備しています");
        await download(endpoint + "/download", { selected: [...selected] });
        ctx.message("ダウンロードを開始しました");
      }),
    actions,
    true,
  );
  selectedButton.disabled = true;
  const filters = el("div", "", ctx.root);
  filters.className = "actions";
  const sl = el("label", "商品名・JANで検索", filters),
    search = el("input", "", sl);
  search.type = "search";
  const wl = el("label", "倉庫", filters),
    warehouse = el("select", "", wl);
  el("option", "すべて", warehouse).value = "";
  const al = el("label", "", filters),
    attention = el("input", "", al);
  attention.type = "checkbox";
  al.append(document.createTextNode(" 要対応・要確認だけ"));
  const counter = el("p", "", ctx.root);
  const wrap = el("div", "", ctx.root);
  wrap.className = "table-wrap";
  const table = el("table", "", wrap),
    head = el("tr", "", el("thead", "", table));
  [
    "選択",
    "商品・倉庫",
    "在庫基準日／現在庫",
    "需要予測（期間合計）",
    "注意理由",
    "判断・操作",
  ].forEach((v) => el("th", v, head));
  const body = el("tbody", "", table);
  const nav = el("div", "", ctx.root);
  let offset = 0,
    generation = 0,
    pageRows = [];
  const prev = button(
      "前のページ",
      () => {
        offset = Math.max(0, offset - 30);
        ctx.run(load);
      },
      nav,
      true,
    ),
    next = button(
      "次のページ",
      () => {
        offset += 30;
        ctx.run(load);
      },
      nav,
      true,
    );
  button(
    "このページを選択",
    () => {
      pageRows.forEach((r) => selected.add(r.item));
      ctx.run(load);
    },
    nav,
    true,
  );
  button(
    "選択を解除",
    () => {
      selected.clear();
      ctx.run(load);
    },
    nav,
    true,
  );
  async function load() {
    const token = ++generation;
    const params = new URLSearchParams({
      q: search.value,
      warehouse: warehouse.value,
      attention: String(attention.checked),
      offset: String(offset),
    });
    const v = await api(endpoint + "?" + params);
    if (token !== generation) return;
    pageRows = v.rows;
    const unresolved = v.input_issues || [];
    issuesTitle.textContent = `未確認・除外した原本情報 ${unresolved.length}項目（商品数とは別集計）`;
    issuesBody.replaceChildren();
    for (const issue of unresolved.slice(0, 100)) {
      el(
        "p",
        `${issue.name}／原本値 ${issue.source_value}／${window.PortableReview.reasonLabels[issue.reason] || issue.reason}／${issue.rows}行／${issue.status}`,
        issuesBody,
      );
    }
    if (unresolved.length > 100)
      el(
        "p",
        "先頭100項目を表示しています。全項目はCSVで確認できます。",
        issuesBody,
      );
    if (unresolved.length)
      button(
        "未確認・除外情報をダウンロード",
        () => ctx.run(() => download(endpoint + "/issues-download", {})),
        issuesBody,
        true,
      );
    cards.replaceChildren();
    for (const [key, text, cls] of [
      ["action", "要対応", "ACTION"],
      ["check", "要確認", "CHECK"],
      ["ok", "問題なし", "OK"],
      ["total", "合計", ""],
    ]) {
      const c = el("div", "", cards);
      el("span", text, c);
      const value = el("strong", String(v.counts[key]), c);
      el("small", "件", value);
      c.className = "card " + cls;
    }
    completion.textContent = `予測できた ${v.counts.forecastable}件／できない ${v.counts.total - v.counts.forecastable}件。判断保存 ${v.counts.saved}件・保留 ${v.counts.held}件・未確認 ${v.counts.pending}件。`;
    const chosen = warehouse.value;
    warehouse.replaceChildren();
    el("option", "すべて", warehouse).value = "";
    v.warehouses.forEach((w) => (el("option", w, warehouse).value = w));
    warehouse.value = chosen;
    counter.textContent = `検索一致 ${v.matched}件／${Math.floor(offset / 30) + 1}ページ／選択 ${selected.size}件（ページをまたいで保持）`;
    prev.disabled = !offset;
    next.disabled = offset + 30 >= v.matched;
    selectedButton.disabled = !selected.size;
    body.replaceChildren();
    for (const r of v.rows) {
      const tr = el("tr", "", body),
        check = el("input", "", el("td", "", tr));
      check.type = "checkbox";
      check.checked = selected.has(r.item);
      check.setAttribute("aria-label", `${r.jan} ${r.warehouse}を選択`);
      check.onchange = () => {
        check.checked ? selected.add(r.item) : selected.delete(r.item);
        ctx.run(load);
      };
      el("td", `${r.name}\n${r.jan}\n${r.warehouse}`, tr);
      el(
        "td",
        `${displayTime(r.inventory_date)}／${r.inventory ?? "未計算"} ${r.unit}`,
        tr,
      );
      el(
        "td",
        r.forecast === null
          ? "予測できません"
          : `${r.forecast.toLocaleString()} ${r.unit}\n${r.period.join(" ～ ")}`,
        tr,
      );
      const risk = el(
        "td",
        labels[r.category] + "\n" + r.reasons.join("／"),
        tr,
      );
      risk.className = r.category;
      const cell = el(
        "td",
        r.review
          ? `${choices[r.review.choice]} ${r.review.quantity ?? ""}`
          : "未確認",
        tr,
      );
      button(
        r.review ? "判断を見直す" : "確認・修正",
        () => ctx.run(() => review(ctx, r)),
        cell,
        true,
      );
    }
  }
  let debounce;
  search.oninput = () => {
    clearTimeout(debounce);
    debounce = setTimeout(() => {
      offset = 0;
      ctx.run(load);
    }, 250);
  };
  warehouse.onchange = attention.onchange = () => {
    offset = 0;
    ctx.run(load);
  };
  button(
    "今回の確認状況を見る",
    () =>
      ctx.run(async () => {
        const v = await api(endpoint + "/next-review");
        await finish(ctx, v.counts);
      }),
    ctx.root,
    true,
  );
  const history = el("details", "", ctx.root);
  el("summary", "判断履歴を見る", history);
  history.ontoggle = () => {
    if (history.open && !history.dataset.loaded)
      ctx.run(async () => {
        const records = await api(endpoint + "/history");
        const list = el("ol", "", history);
        for (const r of records.slice().reverse())
          el(
            "li",
            `${r.created_at}／${r.item}／${choices[r.choice]}／${r.quantity ?? "変更なし"}／${r.reason} ${r.comment}`,
            list,
          );
        history.dataset.loaded = "yes";
      });
  };
  button(
    "不足情報・分析条件を見直す",
    () => ctx.run(() => ctx.open(ctx.analysisId)),
    ctx.root,
    true,
  );
  button("開始画面へ", () => ctx.run(() => ctx.home()), ctx.root, true);
  await load();
}
