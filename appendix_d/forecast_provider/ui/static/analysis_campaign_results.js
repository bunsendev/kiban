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

const replace = (id, children) => document.getElementById(id).replaceChildren(...children);

function metric(value, suffix = "") {
  return value === null || value === undefined ? "—" : `${Number(value).toFixed(2)}${suffix}`;
}

export function renderCampaignStability(stability) {
  const testCount = stability?.completed_test_count || 0;
  document.getElementById("stability-test-count").textContent = `完了${testCount}条件`;
  const rows = (stability?.models || []).map((model) => {
    let state = "順位安定";
    let tone = "neutral";
    if (model.eligible_test_count < 2) state = "条件不足";
    else if (model.varies_by_condition) {
      state = "順位変動あり";
      tone = "warning";
    }
    return node("tr", {}, [
      node("td", { text: `${model.provider_id} / ${model.model_id}` }),
      node("td", {
        text: `${model.eligible_test_count}/${model.configured_test_count}（${metric(model.official_coverage_pct, "%")}）`,
      }),
      node("td", { text: `${model.win_count}/${model.eligible_test_count}` }),
      node("td", { text: metric(model.mean_rank) }),
      node("td", {
        text: model.rank_min === null ? "—" : `${model.rank_min}〜${model.rank_max}`,
      }),
      node("td", { text: metric(model.wape_mean_pct, "%") }),
      node("td", { text: metric(model.wape_range_pct, "pt") }),
      node("td", { text: metric(model.mean_abs_bias_rate_pct, "%") }),
      node("td", { text: metric(model.min_success_rate_pct, "%") }),
      node("td", {}, [node("span", { className: `pill ${tone}`, text: state })]),
    ]);
  });
  if (!rows.length) {
    replace("campaign-stability-summary", [node("div", {
      className: "empty-inline", text: "安定性を集計できる完了結果はまだありません。",
    })]);
    return;
  }
  const headings = [
    "モデル", "公式掲載", "1位回数", "平均順位", "順位幅",
    "WAPE平均", "WAPE幅", "絶対Bias平均", "最低成功率", "条件差",
  ];
  replace("campaign-stability-summary", [node("table", {}, [
    node("thead", {}, [node("tr", {}, headings.map((value) => node("th", { text: value })))]),
    node("tbody", {}, rows),
  ])]);
}

export function renderCampaignResultMatrix(matrix) {
  const rows = (matrix?.tests || []).flatMap((test) => test.models
    .filter((model) => model.official_eligible)
    .map((model) => node("tr", {}, [
      node("td", { text: test.selection_version }),
      node("td", { text: `${test.test_start}〜${test.test_end}` }),
      node("td", {
        text: test.mode === "horizon"
          ? `h=${test.horizon}`
          : `主評価（最大${test.primary_horizon_max}日）`,
      }),
      node("td", { text: `${model.provider_id} / ${model.model_id}` }),
      node("td", { text: model.rank === null ? "—" : String(model.rank) }),
      node("td", { text: metric(model.wape_pct, "%") }),
      node("td", { text: metric(model.bias_rate_pct, "%") }),
      node("td", { text: metric(model.success_rate_pct, "%") }),
    ])));
  if (!rows.length) {
    replace("campaign-result-matrix", [node("div", {
      className: "empty-inline", text: "完了済みの公式比較結果はまだありません。",
    })]);
    return;
  }
  const headings = [
    "データ条件", "テスト期間", "評価幅", "モデル", "順位", "WAPE", "Bias率", "成功率",
  ];
  replace("campaign-result-matrix", [node("table", {}, [
    node("thead", {}, [node("tr", {}, headings.map((value) => node("th", { text: value })))]),
    node("tbody", {}, rows),
  ])]);
}

