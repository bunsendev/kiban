const node = (tag, options = {}, children = []) => {
  const element = document.createElement(tag);
  for (const [name, value] of Object.entries(options)) {
    if (name === "className") element.className = value;
    else if (name === "text") element.textContent = value;
    else if (value !== undefined && value !== null) element.setAttribute(name, value);
  }
  element.append(...children);
  return element;
};

const directionLabels = {
  IMPROVED: "改善", WORSENED: "悪化", UNCHANGED: "変化なし", NOT_COMPARABLE: "比較不能",
};

export function renderRetestComparison(retest, onHandoff) {
  const summary = retest.comparison_summary;
  if (!summary) return null;
  if (summary.availability !== "READY") {
    return node("p", { className: "retest-unavailable", text: `差分を表示できません: ${summary.reason}` });
  }
  const table = node("table", {}, [
    node("thead", {}, [node("tr", {}, [
      "モデル", "事実判定", "WAPE", "MAE", "RMSE", "|Bias|差", "成功率", "順位",
    ].map((label) => node("th", { text: label })))]),
    node("tbody", {}, summary.models.map((model) => node("tr", {}, [
      node("td", { text: `${model.provider_id} / ${model.model_id}` }),
      node("td", { text: directionLabels[model.direction] || model.direction }),
      node("td", { text: transition(model, "wape_pct", model.wape_change_pct_points, "pt") }),
      node("td", { text: transition(model, "mae", model.mae_change, "") }),
      node("td", { text: transition(model, "rmse", model.rmse_change, "") }),
      node("td", { text: signed(model.abs_bias_change_pct_points, "pt") }),
      node("td", { text: transition(model, "success_rate_pct", model.success_rate_change_pct_points, "pt") }),
      node("td", { text: transition(model, "rank", model.rank_change, "") }),
    ]))),
  ]);
  const children = [
    node("p", {
      className: "retest-periods",
      text: `元 ${summary.source.test_start}〜${summary.source.test_end} → 追加 ${summary.retest.test_start}〜${summary.retest.test_end}`,
    }),
    node("div", { className: "retest-comparison-table" }, [table]),
    node("p", {
      className: "field-note",
      text: "判定は公式共通WAPEの増減による事実表示です。採否は自動決定しません。",
    }),
  ];
  if (summary.review_handoff && summary.focus_model) {
    const button = node("button", {
      className: "button secondary retest-handoff",
      type: "button",
      text: "この結果を再レビューへ引き継ぐ",
      "data-permission": "APPROVE",
    });
    button.addEventListener("click", () => onHandoff(retest));
    children.push(button);
  }
  return node("section", { className: "retest-comparison" }, children);
}

function transition(model, key, delta, suffix) {
  const before = model.source?.[key];
  const after = model.retest?.[key];
  if (before === null || before === undefined || after === null || after === undefined) return "—";
  return `${format(before)} → ${format(after)} (${signed(delta, suffix)})`;
}

function signed(value, suffix) {
  if (value === null || value === undefined) return "—";
  return `${value > 0 ? "+" : ""}${format(value)}${suffix}`;
}

function format(value) {
  return Number(value).toFixed(2);
}
