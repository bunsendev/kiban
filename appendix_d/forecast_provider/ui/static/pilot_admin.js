const el = (id) => document.getElementById(id);
const fields = [
  "kind", "location_id", "date_column", "date_format", "quantity_column",
  "location_column", "jan_column", "expiry_column", "source_unit",
  "normalized_unit", "mapping_version",
];
let candidates = [];

function headers() {
  return {
    "Content-Type": "application/json",
    "X-Field-Pilot-Admin-Token": el("token").value,
  };
}

function selected() {
  return candidates.find((item) => item.candidate_id === el("candidate").value);
}

function showCandidate() {
  const item = selected();
  el("candidate-detail").textContent = item
    ? `状態: ${item.status} / 推定: ${item.suggested_kind} / 列: ${item.headers.join("、")}`
    : "確認待ちの候補はありません。";
  if (!item) return;
  el("approve").disabled = item.status !== "PENDING_ADMIN";
  el("reject").disabled = item.status !== "PENDING_ADMIN";
  el("kind").value = item.confirmed_kind || item.suggested_kind;
  el("date_column").value = item.columns.date || "";
  el("quantity_column").value = item.columns.quantity || "";
  el("location_column").value = item.columns.location || "";
  el("jan_column").value = item.columns.jan || "";
  el("expiry_column").value = item.columns.expiry || "";
  el("source_unit").value = "";
}

async function load() {
  try {
    const response = await fetch("/api/field-pilot/admin", {
      cache: "no-store", headers: headers(),
    });
    if (!response.ok) throw new Error("access denied");
    const data = await response.json();
    candidates = data.candidates;
    const select = el("candidate");
    select.replaceChildren();
    for (const item of candidates) {
      const option = document.createElement("option");
      option.value = item.candidate_id;
      option.textContent = `${item.suggested_kind} / ${item.status}`;
      select.append(option);
    }
    showCandidate();
    const contracts = el("contracts");
    contracts.replaceChildren();
    for (const contract of data.contracts) {
      const li = document.createElement("li");
      li.textContent = `${contract.learning_version} / ${contract.status} / ${contract.approved_by}`;
      if (contract.status === "ACTIVE") {
        const button = document.createElement("button");
        button.textContent = "無効化";
        button.type = "button";
        button.addEventListener("click", () => decide(
          `/api/field-pilot/admin/deactivate/${contract.learning_version}`, { kind: "OTHER" },
        ));
        li.append(" ", button);
      }
      contracts.append(li);
    }
    const events = el("events");
    events.replaceChildren();
    for (const event of data.events) {
      const li = document.createElement("li");
      li.textContent = `${event.recorded_at} / ${event.actor} / ${event.action} / ${event.after_status}`;
      events.append(li);
    }
    el("status").textContent = "候補と履歴を表示しました。";
  } catch {
    el("status").textContent = "管理用コードまたは接続を確認してください。";
  }
}

async function decide(url, body) {
  try {
    const response = await fetch(url, {
      method: "POST", headers: headers(),
      body: JSON.stringify({ ...body, actor: el("actor").value.trim() }),
    });
    if (!response.ok) throw new Error("decision failed");
    await load();
    el("status").textContent = "判断を保存しました。正式データ採用は別途必要です。";
  } catch {
    el("status").textContent = "保存できません。候補と正式条件を確認してください。";
  }
}

el("load").addEventListener("click", load);
el("candidate").addEventListener("change", showCandidate);
el("approve").addEventListener("click", () => {
  const item = selected();
  if (!item) return;
  const body = Object.fromEntries(fields.map((key) => [key, el(key).value.trim() || null]));
  decide(`/api/field-pilot/admin/approve/${item.candidate_id}`, body);
});
el("reject").addEventListener("click", () => {
  const item = selected();
  if (item) decide(`/api/field-pilot/admin/reject/${item.candidate_id}`, { kind: "OTHER" });
});
