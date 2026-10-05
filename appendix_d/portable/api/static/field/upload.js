import { api, el, button } from "./api.js";
import { waitJob } from "./progress.js";
import { folderReview } from "./folder-review.js";
import { documents } from "./documents.js";

export async function upload(ctx) {
  ctx.enter(1);
  el("h1", "データをアップロード", ctx.root);
  el("p", "今日のデータを取り込んでください。", ctx.root).className = "intro";
  const drop = el("div", "", ctx.root);
  drop.className = "drop";
  el("span", "", drop).className = "file-icon";
  el("p", "ここにファイルをドラッグ＆ドロップ", drop).className = "drop-title";
  el("p", "または", drop);
  const label = el("label", "ファイルを選ぶ（ZIP）", drop),
    input = el("input", "", label);
  input.type = "file";
  input.accept = ".zip";
  el("small", "対応ファイル：在庫CSVと出荷CSVをまとめたZIP", drop);
  const selected = el("p", "ファイルは未選択です", drop);
  selected.hidden = true;
  let file = null;
  const choose = (f) => {
    file = f;
    selected.hidden = !f;
    start.hidden = !f;
    selected.textContent = f
      ? `${f.name}（${(f.size / 1024 / 1024).toFixed(1)} MB）`
      : "未選択";
    start.disabled = !f;
    ctx.event("SOURCE_SELECTED");
  };
  input.onchange = () => choose(input.files[0]);
  drop.ondragover = (e) => {
    e.preventDefault();
    drop.classList.add("drag");
  };
  drop.ondragleave = () => drop.classList.remove("drag");
  drop.ondrop = (e) => {
    e.preventDefault();
    drop.classList.remove("drag");
    if (e.dataTransfer.files.length !== 1) {
      ctx.message("ZIPを1つ選択してください", true);
      return;
    }
    choose(e.dataTransfer.files[0]);
  };
  const start = button(
    "このファイルを分析する",
    () =>
      ctx.run(async () => {
        if (!file) return;
        if (!file.name.toLowerCase().endsWith(".zip"))
          throw new Error("在庫・出荷CSVを含むZIPを選んでください");
        start.disabled = true;
        ctx.event("ANALYSIS_REQUESTED");
        ctx.enter(2);
        el("h1", "ファイルを送信しています", ctx.root);
        el("progress", "", ctx.root);
        try {
          const r = await fetch("/api/field/upload", {
            method: "POST",
            headers: {
              "Content-Type": "application/zip",
              "X-File-Name": encodeURIComponent(file.name),
            },
            body: file,
          });
          const job = await r.json();
          if (!r.ok) throw new Error(job.detail || "送信に失敗しました");
          await waitJob(ctx, job.id);
        } catch (e) {
          ctx.message(e.message, true);
          button(
            "ファイル選択へ戻る",
            () => ctx.run(() => upload(ctx)),
            ctx.root,
          );
        }
      }),
    drop,
  );
  start.disabled = true;
  start.hidden = true;
  const resume = localStorage.getItem("field-analysis");
  if (resume)
    button(
      "前回の続きから",
      () => ctx.run(() => ctx.open(resume)),
      ctx.root,
      true,
    );
  const jobs = await api("/api/field/jobs");
  const running = jobs.find((j) => j.status === "RUNNING");
  if (running)
    button(
      "実行中の処理を見る",
      () => ctx.run(() => waitJob(ctx, running.id)),
      ctx.root,
    );
  const folder = el("details", "", ctx.root);
  el("summary", "投入フォルダから読み込む", folder);
  const info = el("div", "", folder);
  const reviewArea = el("div", "", folder);
  async function refresh(scan = false) {
    info.replaceChildren();
    const v = await api(
      "/api/drop-folder" + (scan ? "/scan" : ""),
      scan ? {} : undefined,
    );
    el("p", `投入先：${v.folder}`, info);
    el(
      "p",
      `投入待ち ${v.pending.length}ファイル。コピー完了後に自動分析します。`,
      info,
    );
    if (v.csv_message) el("p", v.csv_message, info);
    reviewArea.replaceChildren();
    await folderReview(ctx, reviewArea, () => ctx.run(() => refresh(true)));
    for (const r of v.recent || []) {
      if (r.status !== "PROCESSED") {
        el("p", `${r.filename}：${r.detail}`, info);
        continue;
      }
      if (r.analysis_id)
        button(
          r.filename || r.source_name || "受付済みの分析を開く",
          () => ctx.run(() => ctx.open(r.analysis_id)),
          info,
          true,
        );
    }
  }
  button(
    "投入ファイルを確認",
    () => ctx.run(() => refresh(true)),
    folder,
    true,
  );
  await refresh();
  await documents(ctx, ctx.root);
  const historyGroup = el("details", "", ctx.root);
  historyGroup.className = "work-history";
  el("summary", "過去の作業を再開", historyGroup);
  const history = el("details", "", historyGroup);
  el("summary", "過去の分析を開く", history);
  for (const r of await api("/api/business-archives")) {
    const job = jobs.find((j) => j.analysis_id === r.analysis_id);
    let name = job?.filename || "保存済み分析";
    try {
      name = decodeURIComponent(name);
    } catch {}
    button(
      `${name}／確認待ち ${r.review?.pending_items ?? 0}項目`,
      () => ctx.run(() => ctx.open(r.analysis_id)),
      history,
      true,
    );
  }
  const versions = el("details", "", historyGroup);
  el("summary", "保存した結果・判断を開く", versions);
  for (const v of await api("/api/field/versions")) {
    button(
      `${v.period.join(" ～ ") || "予測対象なし"}／${v.count}商品・倉庫／${v.risk_evaluated ? "リスク評価あり" : "リスク未評価"}`,
      () => ctx.run(() => ctx.openResult(v.result_id)),
      versions,
      true,
    );
  }
}
