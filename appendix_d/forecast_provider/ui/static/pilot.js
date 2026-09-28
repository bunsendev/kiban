const byId = (id) => document.getElementById(id);
const cases = (value) => `${value} 箱`;
const dateTime = (value) => new Intl.DateTimeFormat("ja-JP", {
  timeZone: "Asia/Tokyo", year: "numeric", month: "numeric", day: "numeric",
  hour: "2-digit", minute: "2-digit",
}).format(new Date(value));
const kindLabels = {
  WAREHOUSE_INVENTORY: "倉庫在庫", SHIPMENT_ACTUAL: "出荷実績",
  FACTORY_INVENTORY: "工場在庫", PRODUCTION_SCHEDULE: "生産予定",
  PRODUCTION_PLAN: "生産予定", OTHER: "その他",
};
const columnLabels = {
  date: "日付", jan: "商品", product: "商品名", location: "倉庫・拠点",
  quantity: "数量", expiry: "賞味期限",
};
let currentCandidate = null;

function cell(line, value, tone = "") {
  const element = document.createElement("td");
  element.textContent = value;
  if (tone) element.className = tone;
  line.append(element);
}

function detail(item) {
  byId("detail").hidden = false;
  byId("detail-title").textContent = `${item.product} / ${item.warehouse}`;
  byId("detail-note").textContent = "14日間の参考見通しです。入庫・工場供給・輸送は含みません。";
  const daily = byId("daily-rows");
  daily.replaceChildren();
  for (const day of item.days) {
    const line = document.createElement("tr");
    cell(line, day.business_date);
    cell(line, cases(day.forecast_demand_cases));
    cell(line, cases(day.gross_remaining_cases));
    cell(line, cases(day.fefo_ending_usable_cases));
    cell(line, cases(day.fefo_unmet_cases), day.fefo_unmet_cases !== "0" ? "attention" : "");
    cell(line, cases(day.unconsumed_by_cutoff_cases));
    daily.append(line);
  }
  const expiry = byId("expiry-rows");
  expiry.replaceChildren();
  for (const bucket of item.expiry_buckets) {
    const line = document.createElement("tr");
    cell(line, bucket.expiry_date);
    cell(line, cases(bucket.opening_cases));
    cell(line, cases(bucket.consumed_cases));
    cell(line, cases(bucket.unconsumed_by_cutoff_cases));
    expiry.append(line);
  }
  byId("detail").scrollIntoView({ behavior: "smooth", block: "start" });
}

async function loadInbox() {
  const status = byId("inbox-status");
  const list = byId("inbox-required");
  list.replaceChildren();
  try {
    const response = await fetch("/api/field-pilot/inbox", { cache: "no-store" });
    if (!response.ok) throw new Error("request failed");
    const data = await response.json();
    if (!Array.isArray(data.required)) {
      status.textContent = data.message || "投入先の設定を管理担当者へご確認ください。";
      byId("inbox-counts").hidden = true;
      return data;
    }
    status.textContent = data.status === "READY"
      ? "本日の必要データは確認済みです。"
      : "不足または確認待ちがあります。詳細を管理担当者へご確認ください。";
    const counts = byId("inbox-counts");
    counts.hidden = false;
    counts.textContent = `確認済み ${data.processed_count} 件 / 受付 ${data.received_count} 件 / 確認待ち ${data.review_count} 件 / 重複 ${data.duplicate_count} 件`;
    const labels = {
      VALID: "確認済み", RECEIVED: "受付済み・管理者確認待ち",
      MISSING: "未投入", INVALID: "内容を確認してください",
      REVIEW_REQUIRED: "管理者確認待ち",
    };
    for (const required of data.required) {
      const item = document.createElement("li");
      item.textContent = `${required.display_name}: ${labels[required.status] || "要確認"}`;
      if (required.status !== "VALID") item.className = "needs-review";
      list.append(item);
    }
    byId("inbox-updated").textContent = data.last_updated_at
      ? `最終確認: ${dateTime(data.last_updated_at)}` : "まだファイルが確認されていません。";
    return data;
  } catch {
    status.textContent = "投入状況を表示できません。管理担当者へご連絡ください。";
    byId("inbox-counts").hidden = true;
    return null;
  }
}

function renderLearning(data) {
  currentCandidate = data.candidates?.[0] || null;
  const section = byId("learning");
  section.hidden = !currentCandidate;
  if (!currentCandidate) return;
  const kind = kindLabels[currentCandidate.suggested_kind] || "種類不明";
  byId("learning-message").textContent = currentCandidate.confidence === "LOW"
    ? "自動判定できません。管理担当者へ確認してください。"
    : `このファイルは${kind}だと思われます。内容をご確認ください。`;
  const columns = Object.entries(currentCandidate.columns)
    .map(([key, value]) => `${columnLabels[key] || key} → ${value}`);
  byId("learning-columns").textContent = columns.join(" / ") || "列の確認が必要です。";
  byId("learn-accept").hidden = currentCandidate.confidence === "LOW";
  byId("learning-kind").value = currentCandidate.suggested_kind in kindLabels
    ? currentCandidate.suggested_kind : "OTHER";
  byId("learning-correction").hidden = true;
  byId("learning-actions").hidden = false;
  byId("learning-status").textContent = "";
}

async function loadLearning() {
  try {
    const response = await fetch("/api/field-pilot/learning", { cache: "no-store" });
    if (!response.ok) throw new Error("request failed");
    const data = await response.json();
    renderLearning(data);
    return data;
  } catch {
    byId("learning").hidden = true;
    return null;
  }
}

async function decideLearning(action, kind) {
  if (!currentCandidate) return;
  byId("learn-accept").disabled = true;
  byId("learn-disagree").disabled = true;
  try {
    const response = await fetch(
      `/api/field-pilot/learning/${currentCandidate.candidate_id}/${action}`,
      { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ kind }) },
    );
    if (!response.ok) throw new Error("decision failed");
    const result = await response.json();
    byId("learning-status").textContent = result.status === "ACTIVE"
      ? "形式を覚えました。今回の数値は、正式確認が済むまで予測に使いません。"
      : "管理担当者へ確認を引き継ぎました。正式確認まで予測に使いません。";
    byId("learning-actions").hidden = true;
    byId("learning-correction").hidden = true;
    await loadInbox();
  } catch {
    byId("learning-status").textContent = "確認を保存できませんでした。管理担当者へご連絡ください。";
    byId("learn-accept").disabled = false;
    byId("learn-disagree").disabled = false;
  }
}

function updateSteps(inbox, learning, shadowReady) {
  const uploaded = Boolean(inbox?.checked_count > 0 || learning?.pending_count > 0);
  const checked = inbox?.status === "READY" && learning?.pending_count === 0;
  const complete = checked && shadowReady;
  const ids = ["step-upload", "step-check", "step-attention"];
  const done = [uploaded, checked, complete];
  ids.forEach((id, index) => {
    byId(id).className = done[index] ? "done" :
      (index === 0 || done[index - 1] ? "current" : "");
  });
  byId("daily-complete").hidden = !complete;
  if (Array.isArray(inbox?.required) && !checked) {
    const missing = inbox.required.filter((item) => item.status === "MISSING");
    if (learning?.pending_count > 0) {
      byId("inbox-status").textContent = "新しい形式があります。1回だけ内容を教えてください。";
    } else if (missing.length === 1) {
      byId("inbox-status").textContent = `${missing[0].display_name}がまだありません。`;
    } else if (missing.length > 1) {
      byId("inbox-status").textContent = `あと${missing.length}種類のデータが必要です。`;
    }
  }
}

function render(data) {
  if (data.status !== "READY") {
    byId("status").className = "status error";
    byId("status").textContent = data.message || "データを表示できません。管理担当者へご連絡ください。";
    byId("results").hidden = true;
    return;
  }
  byId("status").className = "status ready";
  byId("status").textContent = data.message;
  byId("updated").textContent = dateTime(data.data_updated_at);
  byId("count").textContent = `${data.summary.item_count} 件`;
  byId("shortage-count").textContent = `${data.summary.shortage_count} 件`;
  byId("expiry-count").textContent = `${data.summary.expiry_attention_count} 件`;
  byId("results").hidden = false;
  byId("detail").hidden = true;
  const body = byId("rows");
  body.replaceChildren();
  for (const item of data.rows) {
    const line = document.createElement("tr");
    cell(line, item.product);
    cell(line, item.warehouse);
    cell(line, cases(item.current_warehouse_cases));
    cell(line, cases(item.forecast_7_days_cases));
    cell(line, cases(item.forecast_14_days_cases));
    cell(line, item.first_shortage_date || "なし", item.first_shortage_date ? "attention" : "");
    cell(line, cases(item.expiry_attention_cases));
    cell(line, item.first_shortage_date || item.expiry_attention_cases !== "0" ? "要確認" : "参考確認");
    const action = document.createElement("td");
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = "詳細を見る";
    button.addEventListener("click", () => detail(item));
    action.append(button);
    line.append(action);
    body.append(line);
  }
}

async function load() {
  const [inbox, learning] = await Promise.all([loadInbox(), loadLearning()]);
  byId("refresh").disabled = true;
  byId("status").textContent = "参考情報を読み込んでいます。";
  try {
    const response = await fetch("/api/field-pilot/view", { cache: "no-store" });
    if (!response.ok) throw new Error("request failed");
    const data = await response.json();
    render(data);
    updateSteps(inbox, learning, data.status === "READY");
  } catch {
    byId("status").className = "status error";
    byId("status").textContent = "データの読み込みに失敗しました。管理担当者へご連絡ください。";
    byId("results").hidden = true;
    updateSteps(inbox, learning, false);
  } finally {
    byId("refresh").disabled = false;
  }
}

byId("today").textContent = new Intl.DateTimeFormat("ja-JP", {
  timeZone: "Asia/Tokyo", year: "numeric", month: "numeric", day: "numeric",
}).format(new Date());
byId("refresh").addEventListener("click", load);
byId("learn-accept").addEventListener("click", () => {
  decideLearning("confirm", currentCandidate.suggested_kind);
});
byId("learn-disagree").addEventListener("click", () => {
  byId("learning-correction").hidden = false;
});
byId("learning-send-correction").addEventListener("click", () => {
  decideLearning("disagree", byId("learning-kind").value);
});
load();
