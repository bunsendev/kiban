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
$("save").addEventListener("click", save);
$("effective").value = new Date().toLocaleDateString("sv-SE", { timeZone: "Asia/Tokyo" });
showType();
