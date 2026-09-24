function node(tag, text) {
  const element = document.createElement(tag);
  element.textContent = text;
  return element;
}

function forecastCandidates(detail) {
  const official = new Set(detail.result.official_runs || []);
  return detail.run_evaluations
    .filter((item) => official.has(item.run_id))
    .map((item) => ({
      ...item,
      wape: item.score.official_common_metrics?.wape_pct,
    }))
    .sort((left, right) => (left.wape ?? Infinity) - (right.wape ?? Infinity));
}

function renderRows(values) {
  const target = document.getElementById("forecast-values");
  target.replaceChildren(...values.map((value) => {
    const row = document.createElement("tr");
    row.append(
      node("td", value.unique_id),
      node("td", value.origin_date),
      node("td", value.target_date),
      node("td", String(value.horizon)),
      node("td", new Intl.NumberFormat("ja-JP", { maximumFractionDigits: 2 }).format(value.yhat)),
    );
    return row;
  }));
}

export function createPredictionValues({ loadRunResults }) {
  const select = document.getElementById("forecast-run");
  const summary = document.getElementById("forecast-summary");
  let candidates = new Map();

  async function display(runId) {
    const candidate = candidates.get(runId);
    summary.className = "eligibility-banner";
    summary.textContent = "予測値を読み込んでいます…";
    try {
      const result = await loadRunResults(runId);
      const pointValues = result.values.filter((value) => value.forecast_kind === "POINT");
      const latestOrigin = pointValues.reduce(
        (latest, value) => value.origin_date > latest ? value.origin_date : latest,
        "",
      );
      const latest = pointValues.filter((value) => value.origin_date === latestOrigin);
      if (!latest.length) throw new Error("点予測の結果がありません。");
      renderRows(latest);
      summary.className = "eligibility-banner eligible";
      const wape = candidate.wape == null ? "—" : `${candidate.wape.toFixed(2)}%`;
      summary.textContent = `${candidate.model_name} / 最新起点 ${latestOrigin} / ${latest.length}予測点 / official WAPE ${wape}`;
    } catch (error) {
      renderRows([]);
      summary.textContent = error.message || "予測値を取得できませんでした。";
    }
  }

  select.addEventListener("change", () => display(select.value));

  async function show(detail) {
    const values = forecastCandidates(detail);
    candidates = new Map(values.map((value) => [value.run_id, value]));
    select.replaceChildren(...values.map((value) => {
      const option = node(
        "option",
        `${value.model_name} / WAPE ${value.wape == null ? "—" : value.wape.toFixed(2)}%`,
      );
      option.value = value.run_id;
      return option;
    }));
    select.disabled = values.length === 0;
    if (!values.length) {
      renderRows([]);
      summary.textContent = "正式比較に掲載できる予測結果がありません。";
      return;
    }
    select.value = values[0].run_id;
    await display(values[0].run_id);
  }

  return { show };
}
