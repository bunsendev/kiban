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

const empty = (message) => node("div", { className: "empty-inline", text: message });
const pill = (value, label = decisionLabel(value)) =>
  node("span", { className: `pill ${statusTone(value)}`, text: label });

function lineage(label, value) {
  return node("div", { className: "lineage-item" }, [
    node("span", { text: label }),
    node("code", { text: value ?? "—", title: value ?? "" }),
  ]);
}

function tags(values) {
  return node("div", { className: "tag-list" },
    (values.length ? values : ["—"]).map((value) => node("span", { className: "tag", text: value })),
  );
}

export function renderDashboard(dashboard) {
  const succeeded = dashboard.builds.filter((build) => build.status === "SUCCEEDED");
  document.getElementById("build-count").textContent = succeeded.length;
  document.getElementById("job-count").textContent = dashboard.jobs.length;
  document.getElementById("eligible-count").textContent = "—";
  document.getElementById("selection-count").textContent = dashboard.selections.length;
  const select = document.getElementById("job-build");
  select.replaceChildren(node("option", { value: "", text: "成功済み日次buildを選択" }));
  for (const build of succeeded) {
    select.append(node("option", {
      value: build.build_id,
      text: `${build.definition.selection_version} / ${shortId(build.build_id, 18)}`,
      title: build.build_id,
    }));
  }
  select.disabled = succeeded.length === 0;
}

export function renderJobs(jobs, selectedId, query, onSelect) {
  const needle = query.trim().toLocaleLowerCase("ja");
  const filtered = jobs.filter((job) =>
    `${job.candidate_job_id} ${job.definition.candidate_version} ${job.definition.daily_build_id}`
      .toLocaleLowerCase("ja")
      .includes(needle),
  );
  document.getElementById("job-filter-count").textContent = `${filtered.length}件`;
  const items = filtered.map((job) => {
    const button = node("button", {
      type: "button",
      className: `comparison-item${job.candidate_job_id === selectedId ? " active" : ""}`,
    });
    button.append(
      node("strong", { text: job.definition.candidate_version }),
      node("span", { text: `${decisionLabel(job.status)} / ${shortId(job.definition.daily_build_id, 20)}` }),
      node("code", { text: shortId(job.candidate_job_id, 28), title: job.candidate_job_id }),
    );
    button.addEventListener("click", () => onSelect(job.candidate_job_id));
    return button;
  });
  replace("job-list", items.length ? items : [empty("候補算出jobはありません。")]);
}

export function renderJobDetail(bundle) {
  const { job, candidates } = bundle;
  document.getElementById("job-status-title").textContent = decisionLabel(job.status);
  document.getElementById("job-id").textContent = job.candidate_job_id;
  replace("job-status", [pill(job.status)]);
  replace("job-lineage", [
    lineage("日次build", job.definition.daily_build_id),
    lineage("candidate version", job.definition.candidate_version),
    lineage("欠損率上限", rate(job.definition.max_missing_rate)),
    lineage("安定品CV上限", metric(job.definition.stable_cv_max)),
    lineage("間欠品0率下限", rate(job.definition.intermittent_zero_rate_min)),
    lineage("依頼者", job.definition.requested_by),
    lineage("目的", job.definition.purpose),
    lineage("業務指定", job.definition.business_product_ids.join(", ") || "なし"),
    lineage("エラー", job.error),
  ]);
  document.getElementById("eligible-count").textContent = candidates.filter((item) => item.eligible).length;
  const submit = document.querySelector('#selection-form button[type="submit"]');
  submit.dataset.blocked = String(job.status !== "SUCCEEDED");
  showDetail(true);
}

export function renderCandidates(candidates, draft, query, onToggle) {
  const needle = query.trim().toLocaleLowerCase("ja");
  const filtered = candidates.filter((item) =>
    `${item.canonical_product_id} ${item.tags.join(" ")} ${item.center_ids.join(" ")}`
      .toLocaleLowerCase("ja")
      .includes(needle),
  );
  document.getElementById("candidate-filter-count").textContent = `${filtered.length}件`;
  const rows = filtered.map((item) => {
    const checkbox = node("input", {
      type: "checkbox",
      className: "candidate-toggle",
      title: item.eligible ? "選定候補に追加" : item.ineligibility_reason,
    });
    checkbox.checked = draft.has(item.canonical_product_id);
    checkbox.disabled = !item.eligible;
    checkbox.addEventListener("change", () => onToggle(item, checkbox.checked));
    return node("tr", { className: item.eligible ? "" : "candidate-ineligible" }, [
      node("td", {}, [checkbox]),
      node("td", {}, [node("strong", { text: `#${item.rank}` }), node("code", { text: item.canonical_product_id, title: item.canonical_product_id })]),
      node("td", {}, [tags(item.tags)]),
      node("td", { text: `${metric(item.total_quantity)} / ${rate(item.quantity_share)}` }),
      node("td", { text: `${metric(item.coefficient_of_variation)} / ${rate(item.zero_rate)} / ${rate(item.missing_rate)}` }),
      node("td", { text: `${item.usable_days} / ${item.handled_days}` }),
      node("td", {}, [tags(item.center_ids)]),
      node("td", {}, [pill(item.eligible, item.eligible ? "選定可" : "選定不可"), node("p", { text: item.ineligibility_reason || "" })]),
    ]);
  });
  replace("candidate-list", rows.length ? rows : [
    node("tr", {}, [node("td", { colspan: "8", text: "該当する候補はありません。" })]),
  ]);
}

export function renderDraft(draft, scope, onCenters, onReason, onRemove) {
  const limits = scope === "INITIAL" ? "3〜5" : "20〜50";
  document.getElementById("draft-count").textContent = `${draft.size}件 / ${limits}件`;
  const items = [...draft.values()].sort((left, right) => left.candidate.rank - right.candidate.rank);
  const cards = items.map((entry) => {
    const remove = node("button", { type: "button", className: "button secondary", text: "選択解除" });
    remove.addEventListener("click", () => onRemove(entry.candidate));
    const centers = entry.candidate.center_ids.map((center) => {
      const checkbox = node("input", { type: "checkbox", value: center });
      checkbox.checked = entry.centerIds.has(center);
      checkbox.addEventListener("change", () => {
        const selected = new Set(entry.centerIds);
        if (checkbox.checked) selected.add(center); else selected.delete(center);
        onCenters(entry.candidate.canonical_product_id, selected);
      });
      return node("label", { className: "center-option" }, [checkbox, node("span", { text: center })]);
    });
    const reason = node("textarea", { rows: "2", required: "", placeholder: "この品目を選ぶ理由" });
    reason.value = entry.reason;
    reason.addEventListener("input", () => onReason(entry.candidate.canonical_product_id, reason.value));
    return node("article", { className: "draft-item" }, [
      node("header", {}, [
        node("div", {}, [node("strong", { text: `#${entry.candidate.rank}` }), node("code", { text: entry.candidate.canonical_product_id })]),
        remove,
      ]),
      node("div", { className: "center-options" }, centers),
      node("label", {}, [node("span", { text: "品目別の選定理由" }), reason]),
    ]);
  });
  replace("selection-draft", cards.length ? cards : [empty("候補指標タブで選定可能な品目を選択してください。")]);
}

export function renderSelections(selections, query) {
  const needle = query.trim().toLocaleLowerCase("ja");
  const filtered = selections.filter((selection) =>
    `${selection.definition.selection_version} ${selection.definition.scope} ${selection.definition.selected_by}`
      .toLocaleLowerCase("ja")
      .includes(needle),
  );
  document.getElementById("selection-filter-count").textContent = `${filtered.length}件`;
  const cards = filtered.map((selection) => {
    const itemRecords = selection.definition.items.map((item) => node("div", { className: "history-item" }, [
      node("code", { text: item.canonical_product_id, title: item.canonical_product_id }),
      node("p", { text: `${item.center_ids.join(", ")} / ${item.reason}` }),
    ]));
    return node("article", { className: "record-item" }, [
      node("header", {}, [node("strong", { text: selection.definition.selection_version }), pill(selection.definition.scope, selection.definition.scope)]),
      node("code", { text: selection.selection_id, title: selection.selection_id }),
      node("p", { text: `${selection.definition.items.length}品目 / ${selection.definition.selected_by}` }),
      node("p", { text: dateTime(selection.selected_at) }),
      node("p", { text: selection.definition.rationale }),
      node("details", {}, [node("summary", { text: "品目・center・理由を表示" }), ...itemRecords]),
    ]);
  });
  replace("selection-list", cards.length ? cards : [empty("確定済み選定版はありません。")]);
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
