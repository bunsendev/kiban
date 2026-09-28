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
    const formalJobs = el("formal-jobs");
    formalJobs.replaceChildren();
    for (const job of data.formal_jobs || []) {
      const li = document.createElement("li");
      li.textContent = `${job.kind} / ${job.location_id} / ${job.status} / 採用候補 ${job.accepted_row_count} 行 / 隔離 ${job.quarantined_row_count} 行 / 原本数量 ${job.source_quantity_cases ?? "確認中"} 箱 / 正規化数量 ${job.normalized_quantity_cases ?? "確認中"} 箱 / 照合 ${job.reconciliation_matched ? "一致" : "未確認"}`;
      if (job.status === "APPROVAL_REQUIRED" && job.quarantined_row_count === 0 && job.reconciliation_matched) {
        const button = document.createElement("button");
        button.type = "button";
        button.textContent = "照合して正式在庫を承認";
        button.addEventListener("click", () => approveFormal(job.job_id));
        li.append(" ", button);
      }
      formalJobs.append(li);
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

async function approveFormal(jobId) {
  const actor = el("actor").value.trim();
  const reason = el("formal-reason").value.trim();
  if (!actor || !reason) { el("status").textContent = "担当者名と承認理由を入力してください。"; return; }
  if (!window.confirm("隔離行がなく、原本と照合結果を確認しましたか？")) return;
  try {
    const response = await fetch(`/api/field-pilot/admin/formal-jobs/${encodeURIComponent(jobId)}/approve`, {
      method: "POST", headers: headers(),
      body: JSON.stringify({ actor, reason, expected_revision: 0 }),
    });
    if (!response.ok) throw new Error("approval failed");
    await load();
    el("status").textContent = "正式在庫の判断を保存しました。予測Runの状態を別途確認してください。";
  } catch {
    el("status").textContent = "承認できません。検証結果、隔離行、現在版を再確認してください。";
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
