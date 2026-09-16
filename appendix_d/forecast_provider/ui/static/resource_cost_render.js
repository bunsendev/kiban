import { dateTime, shortId, statusTone } from "./format.js";

export const RESOURCE_METRICS = [
  ["PREPROCESSING_SECONDS", "前処理時間"],
  ["TRAINING_SECONDS", "学習時間"],
  ["INFERENCE_SECONDS", "推論時間"],
  ["CPU_SECONDS", "CPU使用時間"],
  ["GPU_SECONDS", "GPU使用時間"],
  ["PEAK_MEMORY_BYTES", "最大メモリ"],
  ["MODEL_DOWNLOAD_SECONDS", "モデル取得時間"],
  ["STORAGE_BYTES", "保存容量"],
];

const LABELS = new Map(RESOURCE_METRICS);
const STATUS_LABELS = {
  QUEUED: "待機中", RUNNING: "実行中", SUCCEEDED: "成功",
  PARTIAL: "一部成功", FAILED: "失敗", CANCELLED: "取消",
};

function node(tag, options = {}, children = []) {
  const element = document.createElement(tag);
  for (const [name, value] of Object.entries(options)) {
    if (name === "className") element.className = value;
    else if (name === "text") element.textContent = value;
    else if (name === "title") element.title = value;
    else if (value !== undefined && value !== null) element.setAttribute(name, value);
  }
  for (const child of children) element.append(child);
  return element;
}

function replace(id, children) {
  document.getElementById(id).replaceChildren(...children);
}

function decimal(value, maximumFractionDigits = 4) {
  if (value == null) return "—";
  const number = Number(value);
  if (!Number.isFinite(number)) return String(value);
  return new Intl.NumberFormat("ja-JP", { maximumFractionDigits }).format(number);
}

function quantity(item) {
  if (item.quantity == null) return "未計測";
  if (item.unit === "second") return `${decimal(item.quantity, 3)} 秒`;
  const bytes = Number(item.quantity);
  if (bytes >= 1024 ** 3) return `${decimal(bytes / 1024 ** 3, 2)} GiB`;
  if (bytes >= 1024 ** 2) return `${decimal(bytes / 1024 ** 2, 2)} MiB`;
  if (bytes >= 1024) return `${decimal(bytes / 1024, 2)} KiB`;
  return `${decimal(bytes, 0)} byte`;
}

function money(amount, currency) {
  if (amount == null || !currency) return "単価未登録";
  try {
    return new Intl.NumberFormat("ja-JP", {
      style: "currency", currency, maximumFractionDigits: 6,
    }).format(Number(amount));
  } catch {
    return `${currency} ${decimal(amount, 6)}`;
  }
}

function measurementCost(item) {
  if (item.quantity == null) return "—";
  if (item.unit_price == null) return "単価未登録";
  return money(item.cost_amount, item.currency);
}

function pill(value) {
  return node("span", {
    className: `pill ${statusTone(value)}`,
    text: STATUS_LABELS[value] || value,
  });
}

function fact(label, value) {
  return node("div", { className: "lineage-item" }, [
    node("span", { text: label }), node("code", { text: value || "—", title: value || "" }),
  ]);
}

export function renderSummary(bundle) {
  const terminal = new Set(["SUCCEEDED", "PARTIAL", "FAILED", "CANCELLED"]);
  document.getElementById("run-count").textContent = String(bundle.runs.length);
  document.getElementById("terminal-count").textContent = String(
    bundle.runs.filter((item) => terminal.has(item.status)).length,
  );
  document.getElementById("price-count").textContent = String(bundle.prices.length);
  document.getElementById("manage-state").textContent =
    bundle.session.permissions.includes("MANAGE_RESOURCE") ? "可能" : "参照のみ";
  document.getElementById("price-permission-note").textContent =
    bundle.session.permissions.includes("MANAGE_RESOURCE")
      ? "ADMIN権限で接続中です。登録者は認証中の利用者として記録されます。"
      : "単価の参照はできます。登録にはADMIN権限が必要です。";
}

export function renderRunList(runs, selectedId, search, status, onSelect) {
  const term = search.trim().toLowerCase();
  const filtered = runs.filter((item) => {
    const haystack = [item.run_id, item.experiment_id, item.provider_id, item.model_name]
      .filter(Boolean).join(" ").toLowerCase();
    return (!status || item.status === status) && (!term || haystack.includes(term));
  });
  document.getElementById("run-filter-count").textContent = `${filtered.length}件`;
  const items = filtered.map((item) => {
    const button = node("button", {
      type: "button",
      className: `comparison-item${item.run_id === selectedId ? " active" : ""}`,
    }, [
      node("strong", { text: item.model_name || item.experiment_id }),
      node("span", { text: `${item.provider_id || "Provider未設定"} / ${STATUS_LABELS[item.status] || item.status}` }),
      node("code", { text: shortId(item.run_id, 28), title: item.run_id }),
    ]);
    button.addEventListener("click", () => onSelect(item.run_id));
    return button;
  });
  replace("run-list", items.length ? items : [node("div", { className: "empty-inline", text: "条件に合うrunはありません。" })]);
}

export function showDetail(visible) {
  document.getElementById("detail-empty").hidden = visible;
  document.getElementById("detail-content").hidden = !visible;
}

export function renderRunDetail(run, resources) {
  document.getElementById("run-title").textContent = run.model_name || run.experiment_id;
  const runId = document.getElementById("run-id");
  runId.textContent = run.run_id;
  runId.title = run.run_id;
  replace("run-status-pill", [pill(run.status)]);
  replace("run-facts", [
    fact("Provider", resources.provider_id || run.provider_id),
    fact("Experiment", run.experiment_id),
    fact("成功origin", String(run.origin_counts.SUCCEEDED || 0)),
    fact("失敗記録", String(run.failure_count)),
  ]);

  const measured = resources.measurements.filter((item) => item.quantity != null).length;
  const summaryTone = resources.pricing_complete ? "complete" : "incomplete";
  replace("cost-summary", [node("article", { className: `cost-card ${summaryTone}` }, [
    node("span", { text: "推定総費用" }),
    node("strong", { text: measured === 0
      ? "未計測"
      : resources.pricing_complete
        ? money(resources.total_cost_amount, resources.currency) : "単価未登録" }),
    node("p", { text: resources.pricing_complete
      ? `${measured}項目の計測値に登録単価を適用しました。`
      : measured ? "計測済み項目の単価を登録すると総費用を確定できます。" : "このrunの資源計測はまだありません。" }),
  ])]);

  replace("measurement-rows", resources.measurements.map((item) => node("tr", {}, [
    node("th", { scope: "row", text: LABELS.get(item.metric) || item.metric }),
    node("td", { text: quantity(item) }),
    node("td", { text: item.unit_price == null ? "未登録" : `${item.currency} ${decimal(item.unit_price, 8)} / ${item.unit}` }),
    node("td", { className: "metric-value", text: measurementCost(item) }),
    node("td", { text: item.price_retrieved_on || "—" }),
  ])));

  const attempts = resources.attempt_measurements || [];
  replace("attempt-rows", attempts.length ? attempts.map((item) => node("tr", {}, [
    node("td", { text: item.origin_date }), node("td", { text: String(item.attempt) }),
    node("td", { text: LABELS.get(item.metric) || item.metric }),
    node("td", { text: quantity(item) }), node("td", { text: item.source }),
    node("td", { text: dateTime(item.measured_at) }),
  ])) : [node("tr", {}, [node("td", { colspan: "6", className: "empty-table", text: "attempt別の計測はありません。" })])]);
  showDetail(true);
}

export function renderPrices(prices) {
  replace("price-rows", prices.length ? prices.map((item) => node("tr", {}, [
    node("td", { text: item.provider_id }),
    node("td", { text: LABELS.get(item.metric) || item.metric }),
    node("td", { className: "metric-value", text: `${item.currency} ${decimal(item.unit_price, 8)} / ${item.unit}` }),
    node("td", { text: item.retrieved_on }), node("td", { text: item.source_ref }),
    node("td", { text: item.created_by }),
  ])) : [node("tr", {}, [node("td", { colspan: "6", className: "empty-table", text: "単価はまだ登録されていません。" })])]);
}
