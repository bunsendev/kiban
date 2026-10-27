import { savedForecasts } from "./saved-forecasts.js";
import { api, el, button, field } from "./api.js";
import { qualityPanel, methodFields } from "./data-quality.js";

function formBase(ctx, title) {
  const f = el("form", "", ctx.root);
  el("h2", title, f);
  const actor = field(f, "確認者");
  actor.maxLength = 100;
  actor.value = sessionStorage.getItem("field-actor") || "";
  const reason = field(f, "確認の根拠・理由");
  reason.maxLength = 500;
  f.oninput = () => {
    ctx.dirty = true;
  };
  return { f, actor, reason };
}
function submitForm(ctx, base, label, fn) {
  const b = el("button", label, base.f);
  base.f.onsubmit = (e) => {
    e.preventDefault();
    b.disabled = true;
    ctx.run(async () => {
      try {
        sessionStorage.setItem("field-actor", base.actor.value);
        await fn();
        ctx.dirty = false;
        sessionStorage.setItem("field-actor", base.actor.value);
      } finally {
        b.disabled = false;
      }
    });
  };
}
function check(parent, label) {
  const l = el("label", "", parent),
    c = el("input", "", l);
  c.type = "checkbox";
  c.required = true;
  l.append(document.createTextNode(" " + label));
  return c;
}

export async function waitJob(ctx, id) {
  ctx.enter(2);
  el("h1", "分析しています", ctx.root);
  el(
    "p",
    "データを確認しています。しばらくお待ちください。",
    ctx.root,
  ).className = "intro";
  el("div", "", ctx.root).className = "spinner";
  el("progress", "", ctx.root);
  const status = el("p", "実行状態を確認しています", ctx.root),
    started = Date.now();
  el(
    "p",
    "ブラウザーを閉じてもアプリが動いている間は処理が続きます。PCやアプリを終了すると中断することがあります。",
    ctx.root,
  );
  async function poll() {
    try {
      const job = (await api("/api/field/jobs")).find((j) => j.id === id);
      if (!job) throw new Error("処理が見つかりません");
      status.textContent = `${job.message}／待機 ${Math.floor((Date.now() - started) / 1000)}秒`;
      if (job.status === "RUNNING") {
        ctx.timer = setTimeout(poll, 1200);
        return;
      }
      if (job.analysis_id) {
        ctx.analysisId = job.analysis_id;
        localStorage.setItem("field-analysis", job.analysis_id);
      }
      if (job.status === "SUCCEEDED") {
        await ctx.open(job.analysis_id);
        return;
      }
      ctx.message(job.message, true);
      if (job.analysis_id)
        button(
          "保存済みの状態から再開",
          () => ctx.run(() => ctx.open(job.analysis_id)),
          ctx.root,
        );
      button("開始画面へ", () => ctx.run(() => ctx.home()), ctx.root, true);
    } catch (e) {
      ctx.message(e.message, true);
      button("接続を再確認", () => ctx.run(() => waitJob(ctx, id)), ctx.root);
    }
  }
  await poll();
}

export async function analysis(ctx) {
  ctx.enter(2);
  el("h1", "分析・必要な情報の確認", ctx.root);
  const id = ctx.analysisId;
  const report = await api(`/api/business-archives/${id}`),
    state = await api(`/api/daily-runs/${id}`);
  if(report.input_history)el('p',`この倉庫の取込候補履歴：${report.input_history.candidate_files}ファイル／今回追加 ${report.input_history.new_files}／重複 ${report.input_history.duplicate_files}／過去から参照 ${report.input_history.inherited_files}`,ctx.root);
  const sourceList=el('details','',ctx.root);el('summary','認識したファイルの種類・基準日',sourceList);
  for(const f of report.source_files||[])el('p',`${f.name}：${({shipment:'出荷',inventory:'在庫',document_confirmation_required:'文書の原本確認が必要',metadata:'補助ファイル'})[f.kind]||'形式を認識できません'}／${f.center||'倉庫未確認'}／${f.date||'基準日未確認'}${f.reason?'／'+f.reason:''}`,sourceList);
  button('以前の受付済み原本を履歴へ再集計',()=>ctx.run(async()=>{
    const v=await api('/api/field/input-history/rebuild',{});
    ctx.message(`再集計 ${v.accepted.length}件／失敗 ${v.errors.length}件。${v.errors.map(e=>`${e.source}：${e.reason}`).join('／')}`);
    if(v.accepted.length){ctx.analysisId=v.accepted.at(-1).analysis_id;await analysis(ctx);}
  }),ctx.root,true);
  el(
    "p",
    `読み込み完了：在庫 ${report.rows.inventory}行／出荷 ${report.rows.shipment}行／確認待ち ${report.review.pending_items}項目`,
    ctx.root,
  );
  for (const w of report.center_windows || [])
    el(
      "p",
      `${w.center || w.source_center || "倉庫"}：出荷の最終日 ${w.latest_date || "未確認"}／参考バックテスト用35日（28日学習＋7日評価）で不足 ${w.missing_recent_days ?? "未確認"}日。予測の直近28日判定とは別です。`,
      ctx.root,
    );
  await savedForecasts(ctx.root, item => ctx.openSaved(item));
  const status = el("p", state.next_action, ctx.root);
  status.className = "notice";
  const quality = await qualityPanel(ctx, ctx.root, id);
  if(state.provisional)el('p','現在表示できる結果は欠損を残した暫定予測です。通常予測とは区別して利用してください。',ctx.root).className='notice';
  if (report.issues?.length) {
    const details = el("details", "", ctx.root);
    details.open = report.review.pending_items > 0;
    el("summary", "JAN・賞味期限などの確認", details);
    el(
      "p",
      "原本の値と担当者の判断を別に保存します。未確認項目は自動承認しません。",
      details,
    );
    el("p", "", details).id = "review-state";
    el("div", "", details).id = "review-items";
    el("ol", "", details).id = "decision-history";
    await window.PortableReview.render(report, async () => {
      ctx.dirty = false;
      await analysis(ctx);
    });
    details.addEventListener("input", () => {
      ctx.dirty = true;
    });
  }
  if (
    state.status === "INVENTORY_CONFIRMATION_REQUIRED" ||
    state.status === "INVENTORY_BLOCKED"
  )
    if(report.rows.inventory)await inventoryForm(ctx, id);
  if(!report.rows.inventory){
    el('p','出荷実績は保存済みですが、この倉庫の在庫CSVはありません。需要予測だけは下から実行できます。在庫見通し・不足判定には、基準日の在庫PDFを確認して渡すか、在庫CSVを追加してください。',ctx.root);
    demandOnlyForm(ctx,id,quality);
  }
  if (
    [
      "READY_TO_ADVANCE",
      "PRODUCTION_CONFIRMATION_REQUIRED",
      "FORECAST_BLOCKED",
    ].includes(state.status)
  )
    advanceForm(ctx, id, quality);
  if (state.status === "PRODUCTION_RUNNING") {
    el("progress", "", ctx.root);
    el("p", "需要予測を計算中です。完了後に結果へ進めます。", ctx.root);
    ctx.timer = setTimeout(() => ctx.run(() => analysis(ctx)), 1800);
  }
  if (state.status === "PRODUCTION_BLOCKED")
    button(
      "予測を再開する",
      () =>
        ctx.run(async () => {
          await api(
            `/api/formal-forecast/${state.build_id}/production-run/resume`,
            {},
          );
          await analysis(ctx);
        }),
      ctx.root,
    );
  if (
    state.build_id &&
    [
      "FORECAST_BLOCKED",
      "SUMMARY_CONFIRMATION_REQUIRED",
      "DECISION_INPUT_REQUIRED",
      "DECISION_INPUT_BLOCKED",
      "DECISION_BLOCKED",
      "SHIPMENT_REVIEW_REQUIRED",
      "COMPLETED",
    ].includes(state.status)
  ) {
    button("予測結果を見る", () => ctx.run(() => ctx.showResults()), ctx.root);
    if (state.status === "SUMMARY_CONFIRMATION_REQUIRED") summaryForm(ctx, id, state.provisional);
  }
  if (state.blockers?.length) {
    el(
      "p",
      `未解決の条件が${state.blockers.length}件あります。計算できない商品を問題なしとして扱いません。`,
      ctx.root,
    );
    const reasons={HISTORY_LESS_THAN_28_DAYS:'確認済み出荷履歴が28日未満です。過去の出荷CSVを追加してください',RECENT_SOURCE_DAYS_MISSING:'直近の出荷データに欠測があります。日別CSVを確認してください',INVENTORY_SHIPMENT_AS_OF_MISMATCH:'在庫基準日と出荷履歴の最終日が違います。同じ基準日のデータを揃えてください',QUALITY_REVIEW_REQUIRED:'不足一覧の未解決項目を確認してください',MISSING_MODEL_INPUT_UNSUPPORTED:'選択した方式・モデルでは計算できません。不足を補充してください',OUT_OF_SCOPE_QUALITY:'品質検証の対象外です。取扱期間・対象商品を確認してください',FORECAST_ORIGIN_UNALIGNED:'倉庫ごとの基準日が異なります。同じ基準日の在庫・出荷データを揃えてください'};
    const list=el('ul','',ctx.root);
    for(const item of state.blockers){
      const explanation=(item.reason_codes||[]).map(code=>reasons[code]||code).join('／');
      const days=item.required_start?`／${item.required_start}〜${item.required_end}：${item.recognized_required_days}/28日／不足日 ${(item.missing_required_dates||[]).join('、')||'なし'}`:'';
      el('li',`${item.source_center||''} ${item.jan||''}：${explanation||item.detail||item.status||'入力条件を確認してください'}${days}`,list);
    }
  }
  button(
    "状態を再確認",
    () =>
      ctx.run(async () => {
        if (ctx.dirty && !confirm("未保存の入力を破棄して再表示しますか？"))
          return;
        ctx.dirty = false;
        await analysis(ctx);
      }),
    ctx.root,
    true,
  );
  button("開始画面へ", () => ctx.run(() => ctx.home()), ctx.root, true);
}

function demandOnlyForm(ctx,id,quality){
 const panel=el('section','',ctx.root);el('h2','出荷実績だけで需要を参考予測する',panel);
 const actor=field(panel,'確認者'),unit=field(panel,'CSV数量の単位（例：バラ／ボール）');
 const confirmed=field(panel,'出荷実績と原本数量の単位を確認した','checkbox',false);
 const method=methodFields(panel,quality);
 const output=el('div','',panel);
 button('需要予測のみを計算（在庫は未評価）',()=>ctx.run(async()=>{
   const v=await api(`/api/field/${id}/demand`,{actor:actor.value,unit:unit.value,confirmed:confirmed.checked,...method()});
   output.replaceChildren();el('p',v.notice,output);
   for(const s of v.series){const uid=`${s.source_center}:${s.jan}`;const ps=v.predictions.filter(p=>p.unique_id===uid);const total=ps.reduce((n,p)=>n+Number(p.yhat),0);
    el('p',`${s.source_center} ${s.jan}：${s.required_start}〜${s.required_end} ${s.recognized_days}/28日／${s.eligible?`今後14日 ${total.toFixed(2)} ${v.unit}`:`不足日 ${s.missing_dates.join('、')}`}`,output);}
 }),panel);
}

async function inventoryForm(ctx, id) {
  const data = await api(`/api/business-archives/${id}/formal-inventory`),
    base = formBase(ctx, "在庫の拠点・時刻・数量単位を確認");
  el(
    "p",
    "取込用CSVの数量をボール（CASE）で確認します。PDFのバラ数は、原本確認でボール数＋バラ数÷1ボールあたりのバラ数に換算した数量です。バラをそのままボールとみなす操作ではありません。",
    base.f,
  );
  const inputs = data.centers.map((c) => {
    const fs = el("fieldset", "", base.f);
    el("legend", `${c.source_center}／在庫基準日 ${c.latest_date}`, fs);
    const code = field(fs, "正式拠点コード"),
      name = field(fs, "倉庫名"),
      time = field(fs, "在庫基準時刻", "time");
    name.value = c.source_center;
    return { source_center: c.source_center, code, name, time };
  });
  const confirmed = check(base.f, "この在庫数量の業務単位はボール（CASE）です");
  submitForm(ctx, base, "確認して在庫を準備する", async () => {
    await api(`/api/business-archives/${id}/formal-inventory`, {
      actor: base.actor.value,
      reason: base.reason.value,
      confirm_case: confirmed.checked,
      locations: inputs.map((v) => ({
        source_center: v.source_center,
        location_code: v.code.value,
        location_name: v.name.value,
        snapshot_time: v.time.value,
      })),
    });
    ctx.dirty = false;
    await analysis(ctx);
  });
}
function advanceForm(ctx, id, quality) {
  const base = formBase(ctx, "予測の条件を確認");
  const method = methodFields(base.f, quality);
  const labels = {
    confirm_pilot_scope: "準備した全商品・倉庫を今回の対象とします",
    confirm_quantity_reconciliation:
      "数量が一致し、隔離のない在庫だけを採用します",
    confirm_identity_bridge: "在庫と出荷のJAN・倉庫対応を確認しました",
    confirm_zero_policy:
      "日別出荷ファイルが存在する日に商品行がない場合は出荷0と扱います（ファイル欠落は欠測）",
  };
  const checks = Object.fromEntries(
    Object.entries(labels).map(([k, v]) => [k, check(base.f, v)]),
  );
  const batch = field(
    base.f,
    "一度に処理する商品数（全商品を分割処理）",
    "number",
  );
  batch.value = 100;
  batch.min = 0;
  batch.max = 10000;
  el(
    "p",
    "0は一括、1以上は分割処理です。商品総数を制限する設定ではありません。",
    base.f,
  );
  submitForm(ctx, base, "確認して予測を開始", async () => {
    const job = await api(`/api/field/${id}/advance`, {
      actor: base.actor.value,
      reason: base.reason.value,
      batch_size: Number(batch.value),
      ...method(),
      ...Object.fromEntries(
        Object.entries(checks).map(([k, v]) => [k, v.checked]),
      ),
    });
    ctx.dirty = false;
    await waitJob(ctx, job.id);
  });
}
function summaryForm(ctx, id, isProvisional=false) {
  const details = el("details", "", ctx.root);
  el("summary", "在庫不足・賞味期限の評価も行う", details);
  const base = formBase(ctx, "賞味期限の条件");
  details.append(base.f);
  const min = field(base.f, "出荷時に必要な賞味期限残日数", "number"),
    attention = field(base.f, "注意する賞味期限残日数", "number");
  min.min = 0;
  attention.min = 0;
  const confirmed = check(base.f, "この条件で在庫・賞味期限を参考評価します");
  const provisional = isProvisional ? check(base.f, "暫定予測の欠損と影響を確認し、担当者の判断として評価を進めます") : {checked:false};
  submitForm(ctx, base, "条件を確認して評価", async () => {
    await api(`/api/daily-runs/${id}/daily-summary`, {
      actor: base.actor.value,
      reason: base.reason.value,
      minimum_remaining_days: Number(min.value),
      attention_days: Number(attention.value),
      confirm_expiry_policy: confirmed.checked,
      confirm_provisional: provisional.checked,
    });
    ctx.dirty = false;
    await ctx.showResults();
  });
}
