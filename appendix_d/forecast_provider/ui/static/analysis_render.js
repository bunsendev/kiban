import { dateTime, decisionLabel, shortId, statusTone } from "./format.js";

const node = (tag, options = {}, children = []) => {
  const element = document.createElement(tag);
  for (const [name, value] of Object.entries(options)) {
    if (name === "className") element.className = value;
    else if (name === "text") element.textContent = value;
    else if (name === "checked") element.checked = value;
    else if (name === "disabled") element.disabled = value;
    else if (value !== undefined && value !== null) element.setAttribute(name, value);
  }
  element.append(...children);
  return element;
};

const replace = (id, children) => document.getElementById(id).replaceChildren(...children);
const option = (value, text) => node("option", { value, text });

function snapshotLabel(snapshot) {
  const value = snapshot.manifest;
  return `${value.selection_version} / ${value.test_start}〜${value.test_end} / ${shortId(snapshot.snapshot_id)}`;
}

export function renderSummary(bundle) {
  document.getElementById("snapshot-count").textContent = String(bundle.snapshots.length);
  document.getElementById("experiment-count").textContent = String(bundle.experiments.length);
  document.getElementById("active-run-count").textContent = String(
    bundle.runs.filter((item) => ["QUEUED", "RUNNING"].includes(item.status)).length,
  );
  document.getElementById("comparison-count").textContent = String(bundle.comparisons.length);
}

const WORKER_LABELS = {
  WORKING: "処理中", ONLINE: "待機中", STALE: "応答遅延", NOT_STARTED: "未起動",
};

export function renderWorkerStatus(values) {
  const cards = values.map((item) => node("article", {
    className: `worker-status-item ${item.status.toLowerCase().replace("_", "-")}`,
  }, [
    node("div", { className: "card-heading" }, [
      node("strong", { text: item.display_name }),
      node("span", {
        className: `pill ${["WORKING", "ONLINE"].includes(item.status) ? "positive" : "warning"}`,
        text: WORKER_LABELS[item.status] || item.status,
      }),
    ]),
    node("span", { text: `待機run ${item.queued_runs} / 実行中run ${item.running_runs}` }),
    node("span", { text: item.last_heartbeat ? `最終応答 ${dateTime(item.last_heartbeat)}` : "heartbeat未登録" }),
    node("code", { text: item.provider_id }),
  ]));
  replace("worker-status-list", cards.length ? cards : [node("div", {
    className: "empty-inline", text: "ProviderまたはWorker情報がありません。",
  })]);
}

export function renderFormOptions(bundle, selected = {}) {
  const snapshots = bundle.snapshots.map((item) => option(item.snapshot_id, snapshotLabel(item)));
  replace("snapshot-select", snapshots.length ? snapshots : [option("", "snapshotがありません")]);
  const providers = bundle.providers.map((item) => option(item.provider_id, item.display_name));
  replace("provider-select", providers.length ? providers : [option("", "Providerがありません")]);
  if (selected.snapshotId) document.getElementById("snapshot-select").value = selected.snapshotId;
  if (selected.providerId) document.getElementById("provider-select").value = selected.providerId;
}

export function renderModels(provider, selectedModel) {
  const models = (provider?.models || []).map((item) => option(item.model_id, item.display_name));
  replace("model-select", models.length ? models : [option("", "モデルがありません")]);
  if (selectedModel) document.getElementById("model-select").value = selectedModel;
}

export function renderDefaults(provider, snapshot, modelId) {
  const defaults = provider?.experiment_defaults;
  const model = provider?.models?.find((item) => item.model_id === modelId);
  const intervals = document.getElementById("interval-preset");
  const supportsIntervals = Boolean(provider?.capabilities?.supports_intervals);
  const observed = snapshot?.manifest?.availability_mode === "OBSERVED";
  intervals.disabled = !supportsIntervals || observed;
  const defaultIntervals = (defaults?.interval_levels || []).join(",");
  if (defaultIntervals && ![...intervals.options].some((item) => item.value === defaultIntervals)) {
    intervals.append(option(defaultIntervals, `既定値（${defaultIntervals}）`));
  }
  intervals.value = supportsIntervals && !observed ? defaultIntervals : "";
  document.getElementById("seed").value = defaults?.seed ?? 7;
  document.getElementById("resource-profile").value = defaults?.resource_profile || "cpu-small";
  document.getElementById("training-policy").value = defaults?.training_policy || "FIXED";
  const facts = defaults ? [
    ["前処理版", defaults.preprocessing_version],
    ["Provider設定", JSON.stringify(defaults.params)],
    ["区間予測", !supportsIntervals ? "非対応" : observed ? "OBSERVEDではPOINTのみ" : "選択可能"],
    ["実行方式", provider.capabilities.requires_gpu ? "GPU Worker" : "CPU Worker"],
    ["適合記録", model?.latest_conformance ? "登録済み" : "未登録（比較前に必要）"],
  ] : [["状態", "このProviderには実験既定値がありません"]];
  replace("provider-defaults", facts.map(([label, value]) => node("div", { className: "default-fact" }, [
    node("span", { text: label }), node("code", { text: String(value) }),
  ])));
  document.getElementById("experiment-submit").disabled = !defaults;
}

export function renderExperiments(experiments, snapshots, onRun) {
  const snapshotMap = new Map(snapshots.map((item) => [item.snapshot_id, item]));
  document.getElementById("experiment-filter-count").textContent = `${experiments.length}件`;
  const cards = experiments.map((item) => {
    const definition = item.definition;
    const snapshot = snapshotMap.get(item.snapshot_id);
    const button = node("button", {
      type: "button", className: "button secondary", text: "この条件で実行登録",
      "data-permission": "ANALYZE",
    });
    button.addEventListener("click", () => onRun(item.experiment_id));
    return node("article", { className: "experiment-card" }, [
      node("div", { className: "card-heading" }, [
        node("strong", { text: `${definition.provider_id} / ${definition.model_name}` }),
        node("span", { className: "pill neutral", text: definition.training_policy || "FIXED" }),
      ]),
      node("p", { text: snapshot ? snapshotLabel(snapshot) : item.snapshot_id }),
      node("code", { text: item.experiment_id, title: item.experiment_id }),
      button,
    ]);
  });
  replace("experiment-list", cards.length ? cards : [node("div", {
    className: "empty-inline", text: "実験条件はまだありません。上のフォームから作成してください。",
  })]);
}

function runFacts(run, experiment) {
  return [
    `${run.provider_id || "Provider不明"} / ${run.model_name || "モデル不明"}`,
    experiment ? `snapshot ${shortId(experiment.snapshot_id)}` : "実験定義なし",
    `成功origin ${run.origin_counts.SUCCEEDED || 0} / 失敗 ${run.failure_count}`,
  ];
}

export function renderRuns(runs, experiments, selected, contextFor, onToggle) {
  const experimentMap = new Map(experiments.map((item) => [item.experiment_id, item]));
  const cards = runs.map((run) => {
    const context = contextFor(run);
    const checkbox = node("input", {
      type: "checkbox", checked: selected.has(run.run_id), disabled: !context.eligible,
      "aria-label": `${run.model_name || run.run_id}を比較対象にする`,
    });
    checkbox.addEventListener("change", () => onToggle(run.run_id, checkbox.checked));
    return node("article", { className: `run-card${selected.has(run.run_id) ? " selected" : ""}` }, [
      node("div", { className: "run-select" }, [
        checkbox,
        node("div", {}, [
          node("div", { className: "card-heading" }, [
            node("strong", { text: run.model_name || run.experiment_id }),
            node("span", { className: `pill ${statusTone(run.status)}`, text: decisionLabel(run.status) }),
          ]),
          ...runFacts(run, experimentMap.get(run.experiment_id)).map((value) => node("span", { text: value })),
          node("code", { text: run.run_id, title: run.run_id }),
          !context.eligible ? node("small", { className: "run-warning", text: context.reason }) : node("small", {
            className: "run-ready", text: "実験条件と一致するProvider適合記録があります。",
          }),
        ]),
      ]),
    ]);
  });
  replace("run-list", cards.length ? cards : [node("div", {
    className: "empty-inline", text: "runはまだありません。実験条件から実行登録してください。",
  })]);
  document.getElementById("selected-run-count").textContent = `${selected.size}件選択`;
}

export function renderRecentComparisons(comparisons) {
  const items = comparisons.slice(0, 6).map((item) => node("li", {}, [
    node("code", { text: shortId(item.comparison_id, 18), title: item.comparison_id }),
    node("span", { text: `${item.mode === "primary" ? "主評価" : `h=${item.horizon}`} / ${item.run_ids.length} run` }),
  ]));
  replace("recent-comparisons", items.length ? items : [node("li", { text: "比較結果はまだありません。" })]);
}

export function renderComparisonCreated(comparison) {
  const link = node("a", { href: "/ui", className: "button primary", text: "比較結果・採用画面を開く" });
  replace("comparison-output", [
    node("strong", { text: "比較結果を作成しました" }),
    node("code", { text: comparison.comparison_id, title: comparison.comparison_id }),
    link,
  ]);
}
