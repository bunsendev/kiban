import { dateTime, decisionLabel, metric, shortId, statusTone } from "./format.js";

const STATES = [
  "OBSERVED",
  "CONFIRMED_ZERO",
  "MISSING",
  "NOT_HANDLED",
  "CLOSED",
  "PARTIAL_OR_INVALID",
];

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

function lineage(label, value) {
  return node("div", { className: "lineage-item" }, [
    node("span", { text: label }),
    node("code", { text: value ?? "—", title: value ?? "" }),
  ]);
}

export function renderDashboard(dashboard) {
  document.getElementById("product-count").textContent = dashboard.products.length;
  document.getElementById("period-count").textContent = dashboard.periods.length;
  document.getElementById("build-count").textContent = dashboard.builds.length;
  document.getElementById("issue-count").textContent = "—";
  const select = document.getElementById("period-product");
  select.replaceChildren(node("option", { value: "", text: "商品を選択" }));
  for (const product of dashboard.products) {
    select.append(node("option", {
      value: product.canonical_product_id,
      text: `${product.display_name} / ${shortId(product.canonical_product_id, 16)}`,
      title: product.canonical_product_id,
    }));
  }
  select.disabled = dashboard.products.length === 0;
}

export function renderPeriods(periods, query) {
  const needle = query.trim().toLocaleLowerCase("ja");
  const filtered = periods.filter((period) =>
    `${period.canonical_product_id} ${period.center_id} ${period.period_version}`
      .toLocaleLowerCase("ja")
      .includes(needle),
  );
  document.getElementById("period-filter-count").textContent = `${filtered.length}件`;
  const items = filtered.map((period) => node("article", { className: "record-item" }, [
    node("header", {}, [
      node("strong", { text: `${shortId(period.canonical_product_id, 18)} / ${period.center_id}` }),
      pill(period.status, period.status === "CONFIRMED" ? "確認済み" : "暫定"),
    ]),
    node("code", { text: period.period_version, title: period.period_version }),
    node("p", { text: `${period.valid_from}〜${period.valid_to || "継続中"}` }),
    node("p", { text: `${period.approved_by} / ${period.basis}` }),
  ]));
  replace("period-list", items.length ? items : [empty("該当する取扱期間はありません。")]);
}

export function renderBuildList(builds, selectedId, query, onSelect) {
  const needle = query.trim().toLocaleLowerCase("ja");
  const filtered = builds.filter((build) =>
    `${build.build_id} ${build.definition.selection_version} ${build.definition.period_version}`
      .toLocaleLowerCase("ja")
      .includes(needle),
  );
  document.getElementById("build-filter-count").textContent = `${filtered.length}件`;
  const items = filtered.map((build) => {
    const button = node("button", {
      type: "button",
      className: `comparison-item${build.build_id === selectedId ? " active" : ""}`,
    });
    button.append(
      node("strong", { text: build.definition.selection_version }),
      node("span", { text: `${decisionLabel(build.status)} / period ${build.definition.period_version}` }),
      node("code", { text: shortId(build.build_id, 25), title: build.build_id }),
    );
    button.addEventListener("click", () => onSelect(build.build_id));
    return button;
  });
  replace("build-list", items.length ? items : [empty("日次buildはありません。")]);
}

function stateCards(counts) {
  return STATES.map((state) => node("article", { className: "state-card" }, [
    node("span", { text: state }),
    node("strong", { text: String(counts[state] || 0) }),
  ]));
}

function issueRecords(issues) {
  if (!issues.length) return [empty("理由付きの要確認行はありません。")];
  return issues.map((item) => node("article", { className: "record-item" }, [
    node("header", {}, [node("strong", { text: item.issue }), pill(item.state)]),
    node("p", { text: `${item.count}行` }),
  ]));
}

function valueRows(items) {
  return items.map((item) => node("tr", {}, [
    node("td", { text: item.ds }),
    node("td", {}, [node("code", { text: item.canonical_product_id }), node("span", { text: item.center_id })]),
    node("td", {}, [pill(item.state)]),
    node("td", { text: `${metric(item.raw_quantity)} / ${metric(item.y)}` }),
    node("td", { text: item.issue || "—" }),
  ]));
}

function fileRows(items) {
  return items.map((item) => node("tr", {}, [
    node("td", {}, [node("strong", { text: item.target_date }), node("code", { text: item.center_id })]),
    node("td", {}, [pill(item.status)]),
    node("td", { text: `${item.valid_count} / ${item.expected_count}` }),
    node("td", { text: item.zero_confirmable ? "可" : "不可" }),
    node("td", { text: [...item.missing_paths, ...item.invalid_paths].join(", ") || "—" }),
  ]));
}

export function renderBuildDetail(bundle) {
  const { build, readiness, completeness, page } = bundle;
  document.getElementById("build-status-title").textContent = decisionLabel(build.status);
  document.getElementById("build-id").textContent = build.build_id;
  replace("build-status", [pill(build.status)]);
  replace("build-lineage", [
    lineage("schedule", build.definition.schedule_id),
    lineage("JAN mapping", build.definition.mapping_version),
    lineage("handling period", build.definition.period_version),
    lineage("selection", build.definition.selection_version),
    lineage("as of", dateTime(build.definition.as_of)),
    lineage("snapshot", build.snapshot_id),
  ]);
  replace("state-summary", stateCards(readiness.state_counts));
  replace("issue-list", issueRecords(readiness.issue_counts));
  replace("value-list", valueRows(page.items));
  replace("file-list", fileRows(completeness));
  const unresolved = ["MISSING", "NOT_HANDLED", "PARTIAL_OR_INVALID"].reduce(
    (sum, state) => sum + (readiness.state_counts[state] || 0),
    0,
  );
  document.getElementById("issue-count").textContent = unresolved;
  document.getElementById("value-caption").textContent = `日次行 ${page.total}件中 ${page.items.length}件表示`;
  document.getElementById("page-state").textContent = page.total
    ? `${page.offset + 1}〜${Math.min(page.offset + page.items.length, page.total)} / ${page.total}`
    : "0件";
  const previous = document.getElementById("previous-page");
  const next = document.getElementById("next-page");
  previous.dataset.blocked = String(page.offset === 0);
  next.dataset.blocked = String(page.offset + page.limit >= page.total);
  previous.disabled = previous.dataset.blocked === "true";
  next.disabled = next.dataset.blocked === "true";
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
