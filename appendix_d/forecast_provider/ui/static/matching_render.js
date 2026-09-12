import { dateTime, decisionLabel, metric, rate, shortId, statusTone } from "./format.js";

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

const empty = (message) => node("div", { className: "empty-inline", text: message });
const pill = (value) => node("span", {
  className: `pill ${statusTone(value)}`,
  text: decisionLabel(value),
});

function lineage(label, value) {
  return node("div", { className: "lineage-item" }, [
    node("span", { text: label }),
    node("code", { text: value ?? "—", title: value ?? "" }),
  ]);
}

function fillSelect(id, records, placeholder, valueOf, labelOf, { multiple = false } = {}) {
  const select = document.getElementById(id);
  select.replaceChildren();
  if (!multiple) select.append(node("option", { value: "", text: placeholder }));
  for (const record of records) {
    select.append(node("option", { value: valueOf(record), text: labelOf(record) }));
  }
  select.disabled = records.length === 0;
}

export function renderSummary(dashboard) {
  document.getElementById("job-count").textContent = dashboard.jobs.length;
  document.getElementById("candidate-count").textContent = dashboard.jobs
    .reduce((sum, job) => sum + job.candidate_count, 0);
  document.getElementById("product-count").textContent = dashboard.products.length;
  document.getElementById("mapping-count").textContent = dashboard.mappings.length;
}

export function renderFormOptions(dashboard) {
  const succeeded = dashboard.normalizations.filter((job) => job.status === "SUCCEEDED");
  fillSelect(
    "job-normalizations",
    succeeded,
    "",
    (job) => job.normalization_id,
    (job) => `${shortId(job.normalization_id, 25)} / ${job.accepted_rows}行 / ${shortId(job.source_file_id, 12)}`,
    { multiple: true },
  );
  for (const id of ["mapping-product", "decision-left-product", "decision-right-product"]) {
    fillSelect(
      id,
      dashboard.products,
      "canonical productを選択",
      (product) => product.canonical_product_id,
      (product) => `${product.display_name} / ${shortId(product.canonical_product_id, 12)}`,
    );
  }
}

function jobButton(job, selectedId, onSelect) {
  const button = node("button", {
    type: "button",
    className: `comparison-item${job.matching_job_id === selectedId ? " active" : ""}`,
  });
  button.append(
    node("strong", { text: job.definition.policy_version }),
    node("span", { text: decisionLabel(job.status) }),
    node("span", { text: `${job.definition.normalization_ids.length}正規化 / ${job.candidate_count}候補` }),
    node("code", { text: shortId(job.matching_job_id, 30), title: job.matching_job_id }),
  );
  button.addEventListener("click", () => onSelect(job.matching_job_id));
  return button;
}

function candidateButton(candidate, selectedId, onSelect) {
  const button = node("button", {
    type: "button",
    className: `comparison-item${candidate.candidate_id === selectedId ? " active" : ""}`,
  });
  button.append(
    node("strong", { text: `${candidate.left_jan} ↔ ${candidate.right_jan}` }),
    node("span", { text: `${candidate.details.left_name} / ${candidate.details.right_name}` }),
    node("span", { text: `${rate(candidate.details.name_similarity)} / ${candidate.details.reasons.map(decisionLabel).join("・")}` }),
    node("code", { text: shortId(candidate.candidate_id, 30), title: candidate.candidate_id }),
  );
  button.addEventListener("click", () => onSelect(candidate.candidate_id));
  return button;
}

export function renderLists(dashboard, detail, selection, queries, onJob, onCandidate) {
  const jobNeedle = queries.jobs.trim().toLocaleLowerCase("ja");
  const jobs = dashboard.jobs.filter((job) =>
    `${job.matching_job_id} ${job.definition.policy_version}`.toLocaleLowerCase("ja")
      .includes(jobNeedle));
  const candidateNeedle = queries.candidates.trim().toLocaleLowerCase("ja");
  const candidates = (detail?.candidates || []).filter((candidate) =>
    `${candidate.left_jan} ${candidate.right_jan} ${candidate.details.left_name} ${candidate.details.right_name}`
      .toLocaleLowerCase("ja").includes(candidateNeedle));
  document.getElementById("job-filter-count").textContent = `${jobs.length}件`;
  document.getElementById("candidate-filter-count").textContent = `${candidates.length}件`;
  replace("job-list", jobs.length
    ? jobs.map((job) => jobButton(job, selection.jobId, onJob))
    : [empty("名寄せjobはありません。")] );
  replace("candidate-list", candidates.length
    ? candidates.map((candidate) => candidateButton(candidate, selection.candidateId, onCandidate))
    : [empty(detail ? "このjobに候補はありません。" : "jobを選択してください。")] );
}

export function renderJobDetail(job) {
  document.getElementById("job-title").textContent = job.definition.policy_version;
  document.getElementById("job-id").textContent = job.matching_job_id;
  replace("job-status", [pill(job.status)]);
  replace("job-lineage", [
    lineage("通常類似度", rate(job.definition.similarity_threshold)),
    lineage("切替候補類似度", rate(job.definition.handoff_similarity_threshold)),
    lineage("最大切替空白", `${job.definition.max_handoff_gap_days}日`),
    lineage("候補数", String(job.candidates.length)),
    lineage("条件fingerprint", job.condition_fingerprint),
    lineage("処理エラー", job.error),
  ]);
  replace("job-normalization-list", job.definition.normalization_ids.map((id) =>
    node("code", { text: id, title: id })));
  showJobDetail();
}

function evidence(label, value) {
  return node("article", { className: "evidence-card" }, [
    node("span", { text: label }),
    node("strong", { text: value ?? "—" }),
  ]);
}

function quantityRows(totals, daily) {
  const centers = Object.keys(totals || {});
  if (!centers.length) return [empty("center別数量はありません。")];
  return centers.map((center) => {
    const history = (daily?.[center] || [])
      .map((item) => `${item.date}: ${item.quantity}`)
      .join(" / ");
    return node("div", { className: "quantity-row" }, [
      node("strong", { text: `${center}: ${totals[center]}` }),
      node("code", { text: history || "—", title: history }),
    ]);
  });
}

function decisionRecords(decisions, productNames) {
  if (!decisions.length) return [empty("判断履歴はありません。")];
  return [...decisions].reverse().map((decision) => node("article", { className: "record-item" }, [
    node("header", {}, [node("strong", { text: decision.mapping_version }), pill(decision.decision)]),
    node("p", { text: `${productNames.get(decision.left_product_id) || "—"} / ${productNames.get(decision.right_product_id) || "—"}` }),
    node("p", { text: `${decision.approved_by} / ${dateTime(decision.decided_at)}` }),
    node("p", { text: decision.reason }),
  ]));
}

export function renderCandidateDetail(candidate, dashboard) {
  const details = candidate.details;
  const productNames = new Map(dashboard.products.map((product) =>
    [product.canonical_product_id, product.display_name]));
  document.getElementById("candidate-title").textContent = `${candidate.left_jan} ↔ ${candidate.right_jan}`;
  document.getElementById("candidate-id").textContent = candidate.candidate_id;
  replace("candidate-reasons", details.reasons.map((reason) => pill(reason)));
  replace("candidate-evidence", [
    evidence("左商品名", details.left_name),
    evidence("右商品名", details.right_name),
    evidence("名称類似度", rate(details.name_similarity)),
    evidence("併存日数", `${metric(details.coexistence_days)}日`),
    evidence("左期間", `${details.left_first_date}〜${details.left_last_date}`),
    evidence("右期間", `${details.right_first_date}〜${details.right_last_date}`),
    evidence("切替空白", `${metric(details.gap_days)}日`),
    evidence("単位", `${details.left_units.join(", ")} / ${details.right_units.join(", ")}`),
  ]);
  replace("left-quantities", quantityRows(details.left_center_quantities, details.left_center_daily_quantities));
  replace("right-quantities", quantityRows(details.right_center_quantities, details.right_center_daily_quantities));
  replace("decision-list", decisionRecords(
    dashboard.decisions.filter((decision) => decision.candidate_id === candidate.candidate_id),
    productNames,
  ));
  document.getElementById("candidate-empty").hidden = true;
  document.getElementById("candidate-detail").hidden = false;
}

function productRecords(products) {
  if (!products.length) return [empty("canonical productはありません。")];
  return products.map((product) => node("article", { className: "record-item" }, [
    node("header", {}, [node("strong", { text: product.display_name }), node("code", { text: shortId(product.canonical_product_id, 16), title: product.canonical_product_id })]),
    node("p", { text: `${product.created_by} / ${dateTime(product.created_at)}` }),
    node("p", { text: product.reason }),
  ]));
}

function mappingRecords(mappings, products) {
  if (!mappings.length) return [empty("JAN有効期間はありません。")];
  const names = new Map(products.map((product) => [product.canonical_product_id, product.display_name]));
  return [...mappings].reverse().map((mapping) => node("article", { className: "record-item" }, [
    node("header", {}, [node("strong", { text: mapping.jan }), node("span", { text: mapping.mapping_version })]),
    node("p", { text: `${names.get(mapping.canonical_product_id) || mapping.canonical_product_id} / ${mapping.valid_from}〜${mapping.valid_to || "継続"}` }),
    node("p", { text: `${mapping.approved_by} / ${mapping.reason}` }),
  ]));
}

export function renderCatalogs(dashboard) {
  document.getElementById("product-list-count").textContent = `${dashboard.products.length}件`;
  document.getElementById("mapping-list-count").textContent = `${dashboard.mappings.length}件`;
  replace("product-list", productRecords(dashboard.products));
  replace("mapping-list", mappingRecords(dashboard.mappings, dashboard.products));
}

export function clearCandidateDetail() {
  document.getElementById("candidate-empty").hidden = false;
  document.getElementById("candidate-detail").hidden = true;
}

export function showJobDetail(show = true) {
  document.getElementById("detail-empty").hidden = show;
  document.getElementById("job-detail").hidden = !show;
  if (!show) clearCandidateDetail();
}
