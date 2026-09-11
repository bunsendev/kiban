import { dateTime, decisionLabel, rate, shortId, statusTone } from "./format.js";

const CHECK_LABELS = {
  BUILD_SUCCEEDED: "日次build成功",
  PRODUCT_SCOPE: "3〜5品目の一致",
  AVAILABILITY_MODE: "利用可能時点方式",
  SNAPSHOT_LINKED: "snapshot接続",
  ARTIFACT_CHECKSUM: "artifact checksum",
  SERIES_CALENDAR: "全暦日行",
  USABLE_DAYS: "系列別利用可能日数",
  MISSING_RATE: "系列別欠損率",
  PARTIAL_INVALID_RATE: "系列別部分・不正率",
  REAL_DATA_DECLARATION: "実データ宣言",
};

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

const empty = (message) => node("div", { className: "empty-inline", text: message });
const pill = (value, label = decisionLabel(value)) =>
  node("span", { className: `pill ${statusTone(value)}`, text: label });
const json = (value) => node("pre", { className: "check-json", text: JSON.stringify(value, null, 2) });

function lineage(label, value) {
  return node("div", { className: "lineage-item" }, [
    node("span", { text: label }),
    node("code", { text: value ?? "—", title: value ?? "" }),
  ]);
}

function fillSelect(id, records, placeholder, valueOf, labelOf) {
  const select = document.getElementById(id);
  select.replaceChildren(node("option", { value: "", text: placeholder }));
  for (const record of records) {
    select.append(node("option", { value: valueOf(record), text: labelOf(record) }));
  }
  select.disabled = records.length === 0;
}

export function renderDashboard(dashboard) {
  const active = dashboard.cases.filter((item) => ["QUEUED", "RUNNING"].includes(item.status));
  const passed = dashboard.cases.filter((item) => item.outcome === "PASSED");
  const review = dashboard.cases.filter((item) => ["FAILED", "DRY_RUN"].includes(item.outcome));
  document.getElementById("case-count").textContent = dashboard.cases.length;
  document.getElementById("active-count").textContent = active.length;
  document.getElementById("passed-count").textContent = passed.length;
  document.getElementById("review-count").textContent = review.length;

  const initial = dashboard.selections.filter((selection) =>
    selection.definition.scope === "INITIAL"
      && selection.definition.items.length >= 3
      && selection.definition.items.length <= 5,
  );
  fillSelect(
    "case-selection",
    initial,
    "INITIAL選定版を選択",
    (selection) => selection.selection_id,
    (selection) => `${selection.definition.selection_version} / ${selection.definition.items.length}品目`,
  );
  const succeeded = dashboard.builds.filter((build) => build.status === "SUCCEEDED");
  fillSelect(
    "case-build",
    succeeded,
    "成功済み日次buildを選択",
    (build) => build.build_id,
    (build) => `${build.definition.selection_version} / ${shortId(build.build_id, 18)}`,
  );
}

export function renderProductPreview(selection) {
  const products = selection?.definition.items.map((item) => item.canonical_product_id) || [];
  replace(
    "case-products",
    products.length
      ? products.map((value) => node("code", { text: value, title: value }))
      : [node("span", { text: "INITIAL選定版を選択してください。" })],
  );
}

export function renderCases(cases, selectedId, query, onSelect) {
  const needle = query.trim().toLocaleLowerCase("ja");
  const filtered = cases.filter((record) =>
    `${record.case_id} ${record.definition.acceptance_version} ${record.definition.purpose} ${record.definition.data_kind}`
      .toLocaleLowerCase("ja")
      .includes(needle),
  );
  document.getElementById("case-filter-count").textContent = `${filtered.length}件`;
  const items = filtered.map((record) => {
    const button = node("button", {
      type: "button",
      className: `comparison-item${record.case_id === selectedId ? " active" : ""}`,
    });
    button.append(
      node("strong", { text: record.definition.acceptance_version }),
      node("span", { text: `${decisionLabel(record.status)} / ${decisionLabel(record.outcome)}` }),
      node("span", { text: `${record.definition.data_kind} / ${record.definition.expected_product_ids.length}品目` }),
      node("code", { text: shortId(record.case_id, 28), title: record.case_id }),
    );
    button.addEventListener("click", () => onSelect(record.case_id));
    return button;
  });
  replace("case-list", items.length ? items : [empty("受入caseはありません。")]);
}

function reportCard(label, uri, checksum) {
  return node("article", { className: "report-card" }, [
    node("strong", { text: label }),
    node("code", { text: uri || "未発行", title: uri || "" }),
    node("code", { text: checksum || "—", title: checksum || "" }),
  ]);
}

function checkRows(checks) {
  const order = Object.keys(CHECK_LABELS);
  return [...checks].sort(
    (left, right) => order.indexOf(left.check_id) - order.indexOf(right.check_id),
  ).map((check) => node("tr", {
    className: check.status === "FAILED" ? "check-row-failed" : "",
  }, [
    node("td", {}, [node("strong", { text: CHECK_LABELS[check.check_id] || check.check_id }), node("code", { text: check.check_id })]),
    node("td", {}, [pill(check.status)]),
    node("td", {}, [json(check.actual)]),
    node("td", {}, [json(check.expected)]),
    node("td", { text: check.detail }),
  ]));
}

function decisionRecords(decisions) {
  if (!decisions.length) return [empty("業務判断はまだありません。")];
  return decisions.map((decision) => node("article", { className: "record-item" }, [
    node("header", {}, [node("strong", { text: decision.decision_version }), pill(decision.decision)]),
    node("code", { text: decision.decision_id, title: decision.decision_id }),
    node("p", { text: `${decision.decided_by} / ${dateTime(decision.decided_at)}` }),
    node("p", { text: decision.reason }),
  ]));
}

export function renderCaseDetail(bundle) {
  const { record, checks, decisions } = bundle;
  document.getElementById("case-outcome-title").textContent = decisionLabel(record.outcome || record.status);
  document.getElementById("case-id").textContent = record.case_id;
  replace("case-status", [pill(record.status), pill(record.outcome)]);
  replace("case-lineage", [
    lineage("acceptance version", record.definition.acceptance_version),
    lineage("日次build", record.definition.daily_build_id),
    lineage("データ区分", record.definition.data_kind),
    lineage("availability mode", record.definition.required_availability_mode),
    lineage("期待商品", record.definition.expected_product_ids.join(", ")),
    lineage("最小利用日数", String(record.definition.min_usable_days_per_series)),
    lineage("欠損率上限", rate(record.definition.max_missing_rate)),
    lineage("部分・不正率上限", rate(record.definition.max_partial_invalid_rate)),
    lineage("依頼者", record.definition.requested_by),
    lineage("目的", record.definition.purpose),
    lineage("処理エラー", record.error),
  ]);
  replace("report-records", [
    reportCard("JSON品質レポート", record.report_uri, record.report_sha256),
    reportCard("Markdown品質レポート", record.markdown_uri, record.markdown_sha256),
  ]);
  const rows = checkRows(checks);
  replace("check-list", rows.length ? rows : [
    node("tr", {}, [node("td", { colspan: "5", text: "Worker完了後に技術チェックを表示します。" })]),
  ]);
  replace("decision-list", decisionRecords(decisions));

  const approvalEligible = record.status === "SUCCEEDED"
    && record.outcome === "PASSED"
    && record.definition.data_kind === "REAL";
  const completed = record.status === "SUCCEEDED";
  const banner = document.getElementById("decision-eligibility");
  banner.className = `eligibility-banner${approvalEligible ? " eligible" : ""}`;
  banner.textContent = approvalEligible
    ? "技術判定PASSEDの実データcaseです。元数量照合後に承認できます。"
    : completed
      ? "このcaseは承認条件を満たしません。必要に応じて却下理由を記録してください。"
      : "技術判定の完了後に業務判断を記録できます。";
  const approve = document.querySelector('#decision-value option[value="APPROVED"]');
  approve.disabled = !approvalEligible;
  document.getElementById("decision-value").value = approvalEligible ? "APPROVED" : "REJECTED";
  const submit = document.querySelector('#decision-form button[type="submit"]');
  submit.dataset.blocked = String(!completed);
  showDetail(true);
}

export function showDetail(visible) {
  document.getElementById("detail-empty").hidden = visible;
  document.getElementById("detail-content").hidden = !visible;
}

export function setTab(name) {
  for (const button of document.querySelectorAll(".tab")) {
    const active = button.dataset.tab === name;
    button.classList.toggle("active", active);
    button.setAttribute("aria-selected", String(active));
    document.getElementById(`tab-${button.dataset.tab}`).hidden = !active;
  }
}
