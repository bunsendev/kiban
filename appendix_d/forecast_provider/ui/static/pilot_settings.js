const $ = (id) => document.getElementById(id);
let currentVersion = null;
let history = [];

const headers = () => ({
  "Content-Type": "application/json",
  "X-Field-Pilot-Admin-Token": $("token").value,
});
const status = (message) => { $("status").textContent = message; };
const type = () => $("type").value;
const target = () => type() === "INVENTORY_TIME_POLICY" ? "WAREHOUSE" : $("target").value.trim();

async function loadUnresolved() {
  if (!$("token").value) { status("管理用コードを入力してください。"); return; }
  const response = await fetch("/api/field-pilot/admin/unresolved-products", {
    headers: headers(), cache: "no-store",
  });
  if (!response.ok) { $("unresolved-status").textContent = "一覧を確認できません。管理用コードを確認してください。"; return; }
  const data = await response.json();
  const list = $("unresolved-products");
  list.replaceChildren();
  for (const item of data.items) {
    const line = document.createElement("li");
    const button = document.createElement("button");
    button.type = "button";
    const candidate = item.candidate_status === "UNIQUE"
      ? `JAN候補 ${item.candidate_jans[0]}（${item.direct_code_match ? "商品コード一致" : "商品名一致"}・要確認）`
      : item.candidate_status === "AMBIGUOUS"
        ? `複数候補 ${item.candidate_jans.join(" / ")}（要確認）`
        : "JAN候補なし（別資料で確認）";
    button.textContent = `${item.product_code} / ${item.product_name || "商品名なし"} / ${candidate}`;
    button.addEventListener("click", () => {
      $("type").value = "JAN_MAPPING";
      showType();
      $("target").value = item.product_code;
      $("product-name").value = item.product_name;
      $("jan").value = item.candidate_status === "UNIQUE" ? item.candidate_jans[0] : "";
      void load();
    });
    line.append(button);
    list.append(line);
  }
  $("unresolved-status").textContent = `未確定 ${data.unresolved_count} 商品 / 対象CSV ${data.file_count} 件` +
    (data.complete ? "" : ` / 読取できないCSV ${data.skipped_file_count} 件。管理担当者へ確認してください。`);
  const confirmed = $("confirmed-products");
  confirmed.replaceChildren();
  const evidenceLabels = {
    JAN_CONFLICT: "出荷履歴のJANと確認値が不一致",
    SHIPMENT_HISTORY_MISSING: "一致する出荷履歴なし",
    HISTORY_REVIEW_REQUIRED: "出荷日が28日未満。期間を確認",
    HISTORY_PRESENT: "出荷履歴あり。欠落日・単位の確認待ち",
  };
  const blockerLabels = {
    JAN_UNCONFIRMED: "JAN未確定",
    JAN_CONFLICT: "JAN矛盾",
    SHIPMENT_HISTORY_MISSING: "出荷履歴なし",
    SHIPMENT_HISTORY_SHORT: "出荷履歴28日未満",
    SOURCE_FILES_UNREADABLE: "読取不能な原本あり",
    SHIPMENT_UNIT_UNCONFIRMED: "出荷数量の単位未確定",
    MISSING_DAY_POLICY_UNCONFIRMED: "出荷ファイルのない日の扱い未確定",
  };
  for (const item of data.confirmed_items || []) {
    const line = document.createElement("li");
    const blockers = item.readiness?.blocking_reasons || [];
    line.textContent = `${item.product_code} / JAN ${item.jan} / 出荷記録 ${item.observed_shipment_days} 日 / ${evidenceLabels[item.evidence_status] || "要確認"} / 予測判定: ${blockers.length ? blockers.map((code) => blockerLabels[code] || code).join("、") : "可能"}`;
    confirmed.append(line);
  }
}

async function publishJan() {
  const actor = $("actor").value.trim();
  const reason = $("publish-reason").value.trim();
  if (!actor || !reason || !$("token").value) {
    $("publish-status").textContent = "管理担当者ID、管理用コード、登録理由を入力してください。";
    return;
  }
  if (!window.confirm("JAN確認済みの商品だけを版付き正式対応表へ登録しますか？")) return;
  try {
    const response = await fetch("/api/field-pilot/admin/product-mapping/publish", {
      method: "POST", headers: headers(), body: JSON.stringify({ actor, reason }),
    });
    if (!response.ok) throw new Error("publication failed");
    const data = await response.json();
    $("publish-status").textContent = `正式対応表 ${data.product_mapping_version} に ${data.published_count} 商品を登録しました。未確定 ${data.unresolved_count} 件、JAN矛盾 ${data.conflict_count} 件は対象外です。`;
  } catch {
    $("publish-status").textContent = "登録できません。原本、確認履歴、JAN矛盾を確認してください。";
  }
}

function showType() {
  const time = type() === "INVENTORY_TIME_POLICY";
  $("jan-fields").hidden = time;
  $("time-fields").hidden = !time;
  $("target").disabled = time;
  $("targets").disabled = time;
  $("target").value = time ? "WAREHOUSE" : "";
  currentVersion = null;
  history = [];
  $("current").textContent = "未確認";
  $("history").replaceChildren();
}

async function load() {
  if (!$("token").value) { status("管理用コードを入力してください。"); return; }
  const query = new URLSearchParams({ change_type: type(), target: target() });
  const response = await fetch(`/api/field-pilot/settings?${query}`, { headers: headers(), cache: "no-store" });
  if (!response.ok) { status("設定を読み込めません。管理用コードと入力を確認してください。"); return; }
  const data = await response.json();
  const select = $("targets");
  select.replaceChildren(new Option("選択してください", ""));
  data.targets.forEach((item) => select.add(new Option(item, item)));
  if (target()) select.value = target();
  currentVersion = data.latest_version;
  history = data.history;
  $("current").textContent = data.current
    ? `現在適用中: ${data.current.version} / 適用開始: ${data.current.effective_from} / ${JSON.stringify(data.current.value)}`
    : data.latest_version
      ? `登録済みの版 ${data.latest_version} はまだ適用開始前です。履歴を確認してください。`
      : "現在の設定はありません。原本を確認して初回登録してください。";
  const list = $("history");
  list.replaceChildren();
  history.forEach((item) => {
    const row = document.createElement("li");
    const label = document.createElement("span");
    label.textContent = `${item.changed_at} / ${item.actor} / ${item.reason_code} / ${item.version} / ${JSON.stringify(item.value)} `;
    row.append(label);
    if (item.version !== currentVersion) {
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = "この版の内容へ戻す";
      button.addEventListener("click", () => rollback(item.version));
      row.append(button);
    }
    list.append(row);
  });
  status("履歴を読み込みました。");
}

async function send(path, body) {
  const response = await fetch(path, { method: "POST", headers: headers(), body: JSON.stringify(body) });
  if (!response.ok) { status("保存できません。原本・入力値・現在版・Backupの状態を確認してください。"); return; }
  status("保存しました。新しい版と変更履歴を確認してください。");
  await load();
}

async function save() {
  if (!$("actor").value.trim() || !$("effective").value || !target()) {
    status("担当者ID、適用開始日、対象を入力してください。"); return;
  }
  const time = type() === "INVENTORY_TIME_POLICY";
  const value = time
    ? { source: $("source").value, precision: $("precision").value, time_zone: "Asia/Tokyo" }
    : { jan: $("jan").value.trim(), product_name: $("product-name").value.trim() };
  if (time && value.precision === "EXACT_TIME") value.local_time = $("local-time").value;
  if (!window.confirm("原本と照合しましたか？ 変更前にBackupを作成して新版を保存します。")) return;
  await send("/api/field-pilot/settings/change", {
    change_type: type(), target: target(), value,
    effective_from: $("effective").value, actor: $("actor").value.trim(),
    reason_code: $("reason").value, comment: $("comment").value,
    expected_version: currentVersion,
  });
}

async function rollback(version) {
  if (!currentVersion || !window.confirm("選択した旧版の内容を新版として記録しますか？")) return;
  await send("/api/field-pilot/settings/rollback", {
    version, actor: $("actor").value.trim(), expected_version: currentVersion,
    comment: "管理画面から旧版へ復帰",
  });
}

$("type").addEventListener("change", showType);
$("targets").addEventListener("change", () => { $("target").value = $("targets").value; load(); });
$("load").addEventListener("click", load);
$("load-unresolved").addEventListener("click", loadUnresolved);
$("publish-jan").addEventListener("click", publishJan);
$("save").addEventListener("click", save);
$("effective").value = new Date().toLocaleDateString("sv-SE", { timeZone: "Asia/Tokyo" });
showType();
