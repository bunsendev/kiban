import { dateTime, decisionLabel, metric, rate, shortId, statusTone } from "./format.js";

function node(tag, options = {}, children = []) {
  const element = document.createElement(tag);
  for (const [name, value] of Object.entries(options)) {
    if (name === "className") element.className = value;
    else if (name === "text") element.textContent = value;
    else if (name === "title") element.title = value;
    else if (name.startsWith("data-")) element.setAttribute(name, value);
    else if (value !== undefined && value !== null) element.setAttribute(name, value);
  }
  for (const child of children) element.append(child);
  return element;
}

function replace(id, children) {
  const target = document.getElementById(id);
  target.replaceChildren(...children);
  return target;
}

function pill(value, label = decisionLabel(value)) {
  return node("span", { className: `pill ${statusTone(value)}`, text: label });
}

function empty(message) {
  return node("div", { className: "empty-inline", text: message });
}

export function renderSummary(data) {
  document.getElementById("comparison-count").textContent = data.comparisons.length;
  document.getElementById("official-count").textContent = data.comparisons.filter(
    (item) => item.result.official_ranking_ready,
  ).length;
  document.getElementById("acceptance-count").textContent = data.acceptances.length;
  document.getElementById("adoption-count").textContent = data.adoptions.length;
}

export function renderComparisonList(comparisons, selectedId, query, onSelect) {
  const needle = query.trim().toLocaleLowerCase("ja");
  const filtered = comparisons.filter((item) => {
    const text = `${item.comparison_id} ${item.definition.purpose || ""}`.toLocaleLowerCase("ja");
    return text.includes(needle);
  });
  document.getElementById("comparison-filter-count").textContent = `${filtered.length}件`;
  const items = filtered.map((item) => {
    const button = node("button", {
      type: "button",
      className: `comparison-item${item.comparison_id === selectedId ? " active" : ""}`,
    });
    button.append(
      node("strong", { text: item.definition.purpose || "目的未設定" }),
      node("span", {
        text: `${
          item.result.official_ranking_ready ? "正式比較成立" : "正式比較未成立"
        } / ${dateTime(item.created_at)}`,
      }),
      node("code", { text: shortId(item.comparison_id, 25), title: item.comparison_id }),
    );
    button.addEventListener("click", () => onSelect(item.comparison_id));
    return button;
  });
  replace("comparison-list", items.length ? items : [empty("該当する比較はありません。")]);
}

export function showDetail(visible) {
  document.getElementById("detail-empty").hidden = visible;
  document.getElementById("detail-content").hidden = !visible;
}

function lineage(label, value) {
  return node("div", { className: "lineage-item" }, [
    node("span", { text: label }),
    node("code", { text: value || "—", title: value || "" }),
  ]);
}

function metricCell(value, suffix = "") {
  return node("td", { className: "metric-value", text: `${metric(value)}${value == null ? "" : suffix}` });
}

function resourceValue(resources, metricName) {
  return resources?.measurements?.find((item) => item.metric === metricName)?.quantity ?? null;
}

function resourceCost(resources) {
  if (!resources?.measurements?.some((item) => item.quantity != null)) return "未計測";
  if (!resources?.pricing_complete) return "単価未登録";
  const value = Number(resources.total_cost_amount);
  try {
    return new Intl.NumberFormat("ja-JP", {
      style: "currency", currency: resources.currency, maximumFractionDigits: 6,
    }).format(value);
  } catch {
    return `${resources.currency} ${metric(value)}`;
  }
}

function renderMetrics(detail) {
  const official = new Set(detail.result.official_runs);
  return detail.run_evaluations.map((item) => {
    const own = item.score.own_metrics || {};
    const common = item.score.common_metrics || {};
    const officialMetrics = item.score.official_common_metrics || {};
    const identity = node("td");
    identity.append(
      node("strong", { text: item.model_name }),
      node("code", { text: shortId(item.run_id, 18), title: item.run_id }),
    );
    return node("tr", {}, [
      identity,
      node("td", {}, [pill(official.has(item.run_id), official.has(item.run_id) ? "正式" : "対象外")]),
      metricCell(item.score.run_success_rate == null ? null : item.score.run_success_rate * 100, "%"),
      metricCell(common.wape_pct, "%"),
      metricCell(own.wape_pct, "%"),
      metricCell(officialMetrics.wape_pct, "%"),
      metricCell(resourceValue(item.resources, "INFERENCE_SECONDS"), " 秒"),
      node("td", { className: "metric-value", text: resourceCost(item.resources) }),
    ]);
  });
}

function renderAcceptances(context) {
  if (!context.acceptance_cases.length) return [empty("同じ日次buildの受入caseはありません。")];
  return context.acceptance_cases.map((item) => {
    const status = item.eligible ? pill(true, "採用条件を満たす") : pill(false, "要確認");
    return node("article", { className: "acceptance-card" }, [
      node("header", {}, [
        node("strong", { text: item.acceptance_version }),
        status,
      ]),
      node("div", {}, [
        pill(item.outcome),
        document.createTextNode(" "),
        pill(item.latest_decision),
      ]),
      node("code", { text: shortId(item.case_id, 28), title: item.case_id }),
    ]);
  });
}

function fillSelect(id, options, placeholder = "選択してください") {
  const select = document.getElementById(id);
  const items = [node("option", { value: "", text: placeholder })];
  for (const option of options) {
    items.push(node("option", { value: option.value, text: option.label, title: option.value }));
  }
  select.replaceChildren(...items);
  select.disabled = options.length === 0;
}

function configureForms(detail, context) {
  const runOptions = detail.run_evaluations.map((item) => ({
    value: item.run_id,
    label: `${item.model_name} / ${shortId(item.run_id, 16)}`,
  }));
  const official = new Set(detail.result.official_runs);
  const officialOptions = runOptions.filter((item) => official.has(item.value));
  const acceptanceOptions = context.acceptance_cases
    .filter((item) => item.eligible)
    .map((item) => ({ value: item.case_id, label: item.acceptance_version }));
  const decisionOptions = context.acceptance_cases.map((item) => ({
    value: item.case_id,
    label: `${item.acceptance_version} / ${decisionLabel(item.outcome)}`,
  }));
  fillSelect("export-baseline", runOptions, "baseline runを選択");
  fillSelect("selected-run", officialOptions, "採用runを選択");
  fillSelect("fallback-run", officialOptions, "fallback runを選択");
  fillSelect("acceptance-case", acceptanceOptions, "承認済み受入caseを選択");
  fillSelect("decision-case", decisionOptions, "受入caseを選択");
  document.getElementById("product-ids").value = context.canonical_product_ids.join(", ");
  document.getElementById("center-ids").value = context.center_ids.join(", ");
  const eligible = context.official_ranking_ready && acceptanceOptions.length > 0;
  const banner = document.getElementById("eligibility-banner");
  banner.className = `eligibility-banner${eligible ? " eligible" : ""}`;
  banner.textContent = eligible
    ? "正式比較と承認済み実データ受入が揃っています。採用判断を記録できます。"
    : "採用には正式比較の成立と、同じ日次buildの実データ受入PASSED・APPROVEDが必要です。";
}

function exportRecords(records, onDownload) {
  if (!records.length) return [empty("この比較のCSV発行履歴はありません。")];
  return records.map((record) => {
    const button = node("button", { type: "button", className: "button secondary", text: "取得" });
    button.addEventListener("click", () => onDownload(record));
    return node("article", { className: "record-item" }, [
      node("header", {}, [node("strong", { text: record.export_version }), pill("PASSED", `${record.row_count}行`)]),
      node("code", { text: shortId(record.output_sha256, 24), title: record.output_sha256 }),
      node("p", { text: `baseline ${shortId(record.baseline_run_id, 16)} / ${dateTime(record.created_at)}` }),
      node("div", { className: "inline-actions" }, [button]),
    ]);
  });
}

function adoptionRecords(records) {
  if (!records.length) return [empty("この比較の採用判断はありません。")];
  return records.map((record) => node("article", { className: "record-item" }, [
    node("header", {}, [node("strong", { text: record.adoption_version }), pill(record.decision)]),
    node("code", { text: shortId(record.adoption_id, 28), title: record.adoption_id }),
    node("p", { text: `${record.decided_by} / ${dateTime(record.decided_at)}` }),
    node("p", { text: record.reason }),
  ]));
}

export function renderDetail(bundle, records, onDownload) {
  const { detail, context } = bundle;
  document.getElementById("comparison-purpose").textContent = detail.definition.purpose;
  const id = document.getElementById("comparison-id");
  id.textContent = detail.comparison_id;
  id.title = detail.comparison_id;
  replace("comparison-status", [
    pill(
      detail.result.official_ranking_ready,
      detail.result.official_ranking_ready ? "正式比較成立" : "正式比較未成立",
    ),
  ]);
  replace("lineage-grid", [
    lineage("truth snapshot", detail.definition.truth_snapshot_id),
    lineage("selection version", context.selection_version),
    lineage("daily build", context.daily_build_id),
    lineage("comparison set", detail.result.comparison_set_id),
    lineage("official set", detail.result.official_comparison_set_id),
    lineage("policy", detail.definition.policy_version),
  ]);
  replace("run-metrics", renderMetrics(detail));
  replace("acceptance-list", renderAcceptances(context));
  configureForms(detail, context);
  replace("export-list", exportRecords(records.exports, onDownload));
  replace("adoption-list", adoptionRecords(records.adoptions));
  showDetail(true);
}

export function setTab(name) {
  for (const button of document.querySelectorAll(".tab")) {
    const active = button.dataset.tab === name;
    button.classList.toggle("active", active);
    button.setAttribute("aria-selected", String(active));
    document.getElementById(`tab-${button.dataset.tab}`).hidden = !active;
  }
}
