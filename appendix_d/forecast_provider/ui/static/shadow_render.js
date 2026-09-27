import { dateTime, shortId } from "./format.js";

const byId = (id) => document.getElementById(id);
const cases = (value) => `${value} 箱`;

function cell(row, value, tone = "") {
  const element = document.createElement("td");
  element.textContent = value;
  if (tone) element.className = tone;
  row.append(element);
  return element;
}

export function renderSelected(row) {
  byId("item-detail").hidden = false;
  byId("item-title").textContent = `${row.jan} / ${row.warehouse_id}`;
  byId("item-summary").textContent = `14日の予測需要 ${cases(row.forecast_14_days_cases)}。gross不足 ${cases(row.gross_shortfall_14_days_cases)}、期限を考慮した未充足 ${cases(row.fefo_unmet_14_days_cases)}、期限内未消化見込み ${cases(row.unconsumed_by_cutoff_14_days_cases)}。参考値・出荷指示ではありません。`;
  const body = byId("day-rows");
  body.replaceChildren();
  for (const day of row.days) {
    const line = document.createElement("tr");
    cell(line, day.business_date);
    cell(line, cases(day.forecast_demand_cases));
    cell(line, cases(day.gross_remaining_cases));
    cell(line, cases(day.fefo_ending_usable_cases));
    cell(line, cases(day.fefo_unmet_cases), day.fefo_unmet_cases !== "0" ? "shadow-alert" : "");
    cell(line, cases(day.unconsumed_by_cutoff_cases), day.unconsumed_by_cutoff_cases !== "0" ? "shadow-alert" : "");
    body.append(line);
  }
}

export function renderShadow(result) {
  byId("result").hidden = false;
  byId("item-detail").hidden = true;
  byId("row-count").textContent = `${result.rows.length} 商品×倉庫`;
  byId("snapshot-at").textContent = dateTime(result.snapshot_at);
  byId("run-id").textContent = shortId(result.forecast_run_id, 20);
  const body = byId("shadow-rows");
  body.replaceChildren();
  for (const item of result.rows) {
    const line = document.createElement("tr");
    cell(line, `${item.jan} / ${item.warehouse_id}`);
    cell(line, cases(item.current_warehouse_cases));
    cell(line, cases(item.forecast_7_days_cases));
    cell(line, cases(item.forecast_14_days_cases));
    cell(line, item.first_gross_shortage_date || "なし", item.first_gross_shortage_date ? "shadow-alert" : "");
    cell(line, cases(item.unconsumed_by_cutoff_14_days_cases), item.unconsumed_by_cutoff_14_days_cases !== "0" ? "shadow-alert" : "");
    const action = document.createElement("td");
    const button = document.createElement("button");
    button.type = "button";
    button.className = "button secondary";
    button.textContent = "見る";
    button.setAttribute("aria-label", `${item.jan}の14日見通しを見る`);
    button.addEventListener("click", () => renderSelected(item));
    action.append(button);
    line.append(action);
    body.append(line);
  }
  const lineage = byId("lineage");
  lineage.replaceChildren();
  for (const [label, value] of [
    ["在庫snapshot", result.inventory_snapshot_id],
    ["snapshot時刻", result.snapshot_at],
    ["在庫known_at", result.snapshot_known_at],
    ["Pilot scope", result.pilot_scope_version],
    ["identity bridge", result.identity_bridge_version],
    ["予測run", result.forecast_run_id],
    ["予測cutoff", result.forecast_cutoff_at],
    ["run完了", result.forecast_finished_at],
    ["期限policy", result.policy_version],
    ["計算時点", result.calculation_at],
  ]) {
    const term = document.createElement("dt");
    term.textContent = label;
    const definition = document.createElement("dd");
    definition.textContent = value;
    lineage.append(term, definition);
  }
}
