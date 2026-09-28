const $ = (id) => document.getElementById(id);
let version = null;
const headers = () => ({
  "Content-Type": "application/json",
  "X-Field-Pilot-Admin-Token": $("token").value,
});
const level = () => Number(document.querySelector('input[name="level"]:checked').value);
const flags = () => Object.fromEntries(
  [...document.querySelectorAll("[data-flag]")].map((box) => [box.dataset.flag, box.checked]),
);
function preview() {
  const current = level();
  document.querySelectorAll("[data-flag]").forEach((box) => {
    const detailed = ["pseudonymous_products", "pseudonymous_warehouses", "absolute_quantities", "expiry_dates"];
    const unavailable = ["operator_corrections", "business_kpis", "expiry_dates"];
    box.disabled = current === 0 || unavailable.includes(box.dataset.flag)
      || (current < 3 && detailed.includes(box.dataset.flag));
    if (box.disabled) box.checked = false;
  });
  const selected = Object.entries(flags()).filter(([, enabled]) => enabled).map(([name]) => name);
  $("preview").textContent = current === 0
    ? "送信しません。ローカル処理だけ続けます。"
    : `送信候補: ${selected.join("、") || "なし"}。原本・商品名・取引先名は送信しません。`;
}
async function load() {
  const response = await fetch("/api/field-pilot/feedback", { headers: headers(), cache: "no-store" });
  if (!response.ok) { $("status").textContent = "管理用コードを確認してください。"; return; }
  const data = await response.json();
  version = data.version;
  document.querySelector(`input[name="level"][value="${data.policy.level}"]`).checked = true;
  document.querySelectorAll("[data-flag]").forEach((box) => {
    box.checked = data.policy.flags[box.dataset.flag] === true;
  });
  $("version").textContent = version ? `設定版: ${version}` : "未設定です。初期状態は送信OFFです。";
  $("status").textContent = "現在の設定を読み込みました。";
  preview();
}
async function save() {
  if (!$("actor").value.trim() || !$("reason").value.trim()) {
    $("status").textContent = "変更者と理由を入力してください。"; return;
  }
  preview();
  if (!window.confirm("プレビューの共有範囲を確認しましたか？")) return;
  const response = await fetch("/api/field-pilot/feedback/change", {
    method: "POST", headers: headers(), body: JSON.stringify({
      expected_version: version, actor: $("actor").value.trim(), reason: $("reason").value.trim(),
      policy: { level: level(), flags: flags() },
    }),
  });
  $("status").textContent = response.ok ? "新しい設定版を保存しました。" : "設定を保存できません。版と入力を確認してください。";
  if (response.ok) await load();
}
async function consent() {
  const expires = $("support-expires").value;
  if (!expires || !window.confirm("今回だけの許可を記録しますか？ 原本の自動送信は行いません。")) return;
  const response = await fetch("/api/field-pilot/feedback/support-consent", {
    method: "POST", headers: headers(), body: JSON.stringify({
      target: $("support-target").value, purpose: $("support-purpose").value,
      destination: $("support-destination").value, actor: $("actor").value,
      expires_at: new Date(expires).toISOString(),
    }),
  });
  if (response.ok) {
    const data = await response.json();
    $("support-result").textContent = `個別許可ID: ${data.consent_id}。中央管理者へ同じID、対象ファイルのSHA-256、有効期限を伝え、承認後にPCの「サポート資料を送信」を実行してください。`;
    $("status").textContent = "期限付きの個別許可を記録しました。";
  } else {
    $("status").textContent = "対象と期限を確認してください。";
  }
}
$("load").addEventListener("click", load);
$("save").addEventListener("click", save);
$("support-consent").addEventListener("click", consent);
document.querySelectorAll('input[name="level"], [data-flag]').forEach((item) => item.addEventListener("change", preview));
preview();
