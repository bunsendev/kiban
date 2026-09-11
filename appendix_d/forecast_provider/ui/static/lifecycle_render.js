import { dateTime, decisionLabel, metric, shortId, statusTone } from "./format.js";

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

function fillSelect(id, options, placeholder) {
  const select = document.getElementById(id);
  select.replaceChildren(node("option", { value: "", text: placeholder }));
  for (const option of options) {
    select.append(node("option", { value: option.value, text: option.label, title: option.value }));
  }
  select.disabled = options.length === 0;
}

export function renderAdoptions(adoptions) {
  const options = adoptions
    .filter((item) => item.decision === "ADOPTED")
    .map((item) => ({
      value: item.adoption_id,
      label: `${item.adoption_version} / ${shortId(item.adoption_id, 18)}`,
    }));
  fillSelect("plan-adoption", options, "ADOPTED判断を選択");
}

export function renderSummary(dashboard) {
  const cycles = dashboard.statuses.flatMap((item) => item.cycles);
  document.getElementById("plan-count").textContent = dashboard.plans.length;
  document.getElementById("queued-count").textContent = cycles.filter((item) => item.status === "QUEUED").length;
  document.getElementById("ready-count").textContent = cycles.filter((item) => item.status === "READY").length;
  document.getElementById("trial-count").textContent = dashboard.statuses.reduce(
    (total, item) => total + item.trial_forecast_count,
    0,
  );
}

export function renderPlanList(dashboard, selectedId, query, onSelect) {
  const needle = query.trim().toLocaleLowerCase("ja");
  const statusById = new Map(dashboard.statuses.map((item) => [item.plan.plan_id, item]));
  const plans = dashboard.plans.filter((plan) =>
    `${plan.plan_id} ${plan.plan_version} ${plan.adoption_id}`.toLocaleLowerCase("ja").includes(needle),
  );
  document.getElementById("plan-filter-count").textContent = `${plans.length}件`;
  const items = plans.map((plan) => {
    const status = statusById.get(plan.plan_id);
    const button = node("button", {
      type: "button",
      className: `comparison-item${plan.plan_id === selectedId ? " active" : ""}`,
    });
    button.append(
      node("strong", { text: plan.plan_version }),
      node("span", { text: `rev.${status?.champion.revision ?? "—"} / trial ${plan.trial_start_date}〜${plan.trial_end_date}` }),
      node("code", { text: shortId(plan.plan_id, 25), title: plan.plan_id }),
    );
    button.addEventListener("click", () => onSelect(plan.plan_id));
    return button;
  });
  replace("plan-list", items.length ? items : [empty("該当するLifecycle計画はありません。")]);
}

function renderCycles(cycles) {
  return cycles.map((cycle) => node("tr", {}, [
    node("td", { text: cycle.due_month }),
    node("td", { text: dateTime(cycle.scheduled_for) }),
    node("td", {}, [pill(cycle.status)]),
    node("td", { text: shortId(cycle.challenger_run_id, 16), title: cycle.challenger_run_id || "" }),
    node("td", { text: cycle.score?.improvement_pct == null ? "—" : `${metric(cycle.score.improvement_pct)}%` }),
  ]));
}

function renderEvents(events) {
  if (!events.length) return [empty("champion eventはありません。")];
  return [...events].reverse().map((event) => node("article", { className: "record-item" }, [
    node("header", {}, [node("strong", { text: `revision ${event.revision}` }), pill(event.action)]),
    node("code", { text: event.to_run_id, title: event.to_run_id }),
    node("p", { text: `${event.approved_by} / ${dateTime(event.created_at)}` }),
    node("p", { text: event.reason }),
  ]));
}

function renderForecasts(records) {
  if (!records.length) return [empty("trial予測の事前記録はありません。")];
  return [...records].reverse().map((record) => node("article", { className: "record-item" }, [
    node("header", {}, [node("strong", { text: record.origin_date }), pill("PASSED", "事前固定済み")]),
    node("code", { text: record.run_id, title: record.run_id }),
    node("p", { text: `${record.recorded_by} / ${dateTime(record.recorded_at)}` }),
  ]));
}

function renderAssessments(records) {
  if (!records.length) return [empty("trial評価はまだありません。")];
  return [...records].reverse().map((record) => node("article", { className: "record-item" }, [
    node("header", {}, [node("strong", { text: `revision ${record.revision}` }), pill(record.decision)]),
    node("code", { text: record.comparison_id, title: record.comparison_id }),
    node("p", { text: `${record.period_start}〜${record.period_end} / ${record.assessed_by}` }),
    node("p", { text: record.reason }),
  ]));
}

export function renderPlanDetail(bundle) {
  const { status, forecasts, assessments } = bundle;
  const { plan, champion, champion_events: events, cycles } = status;
  document.getElementById("champion-run").textContent = shortId(champion.to_run_id, 32);
  document.getElementById("champion-run").title = champion.to_run_id;
  document.getElementById("plan-id").textContent = plan.plan_id;
  replace("champion-status", [pill(champion.action, `revision ${champion.revision} / ${decisionLabel(champion.action)}`)]);
  replace("plan-lineage", [
    lineage("plan version", plan.plan_version),
    lineage("adoption", plan.adoption_id),
    lineage("monthly experiment", plan.experiment_id),
    lineage("fallback", plan.fallback_run_id),
    lineage("trial", `${plan.trial_start_date}〜${plan.trial_end_date}`),
    lineage("schedule", `毎月${plan.schedule_day}日 ${plan.schedule_time} ${plan.timezone}`),
    lineage("minimum improvement", `${metric(plan.minimum_improvement_pct)}%`),
    lineage("maximum failure", metric(plan.maximum_failure_rate)),
  ]);
  replace("cycle-list", renderCycles(cycles));
  replace("event-list", renderEvents(events));
  replace("forecast-list", renderForecasts(forecasts));
  replace("assessment-list", renderAssessments(assessments));

  const queued = cycles.filter((cycle) => cycle.status === "QUEUED").map((cycle) => ({ value: cycle.cycle_id, label: `${cycle.due_month} / ${shortId(cycle.cycle_id, 16)}` }));
  const ready = cycles.filter((cycle) => cycle.status === "READY").map((cycle) => ({ value: cycle.cycle_id, label: `${cycle.due_month} / ${shortId(cycle.challenger_run_id, 16)}` }));
  fillSelect("complete-cycle", queued, "待機cycleを選択");
  fillSelect("fail-cycle", queued, "待機cycleを選択");
  fillSelect("promote-cycle", ready, "昇格可能cycleを選択");

  const current = champion.to_run_id;
  const targets = new Set([plan.fallback_run_id, ...events.slice(0, -1).map((event) => event.to_run_id)]);
  targets.delete(current);
  fillSelect("rollback-target", [...targets].map((value) => ({ value, label: shortId(value, 30) })), "rollback先を選択");
  document.getElementById("assessment-start").value = plan.trial_start_date;
  document.getElementById("assessment-end").value = plan.trial_end_date;
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
