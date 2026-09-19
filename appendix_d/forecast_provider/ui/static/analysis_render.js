import { dateTime, decisionLabel, shortId, statusTone } from "./format.js";
import { matchingConformance } from "./analysis_rules.js";

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

export function renderCampaignOptions(bundle, selectedSnapshots = new Set(), selectedModels = new Set()) {
  const effectiveSnapshots = selectedSnapshots.size
    ? selectedSnapshots : new Set(bundle.snapshots.slice(0, 1).map((item) => item.snapshot_id));
  const snapshots = bundle.snapshots.map((snapshot) => {
    const input = node("input", {
      type: "checkbox", checked: effectiveSnapshots.has(snapshot.snapshot_id),
      "data-snapshot-id": snapshot.snapshot_id,
    });
    return node("label", { className: "campaign-snapshot-option" }, [
      input,
      node("span", {}, [
        node("strong", { text: snapshotLabel(snapshot) }),
        node("span", { text: snapshot.snapshot_id }),
      ]),
    ]);
  });
  replace("campaign-snapshot-options", snapshots.length ? snapshots : [node("div", {
    className: "empty-inline", text: "利用できるデータセットがありません。",
  })]);
  const choices = bundle.providers.flatMap((provider) => provider.models.map((model) => {
    const key = `${provider.provider_id}\u0000${model.model_id}`;
    const input = node("input", {
      type: "checkbox", checked: selectedModels.has(key),
      "data-provider-id": provider.provider_id, "data-model-id": model.model_id,
    });
    return node("label", { className: "campaign-model-option" }, [
      input,
      node("span", {}, [
        node("strong", { text: `${provider.display_name} / ${model.display_name}` }),
        node("span", { text: `${provider.provider_id} / ${model.model_id}` }),
      ]),
    ]);
  }));
  replace("campaign-model-options", choices.length ? choices : [node("div", {
    className: "empty-inline", text: "利用できるProviderモデルがありません。",
  })]);
}

function metric(value, suffix = "") {
  return value === null || value === undefined ? "—" : `${Number(value).toFixed(2)}${suffix}`;
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
  const headings = ["データ条件", "テスト期間", "評価幅", "モデル", "順位", "WAPE", "Bias率", "成功率"];
  replace("campaign-result-matrix", [node("table", {}, [
    node("thead", {}, [node("tr", {}, headings.map((value) => node("th", { text: value })))]),
    node("tbody", {}, rows),
  ])]);
}

const FINALIZATION_LABELS = {
  WAITING: "自動比較待機", RUNNING: "自動比較作成中",
  SUCCEEDED: "比較結果作成済み", FAILED: "自動比較失敗",
};

export function renderCampaigns(campaigns, onSelectRuns, onRetry) {
  document.getElementById("campaign-count").textContent = `${campaigns.length}件`;
  const cards = campaigns.map((campaign) => {
    const done = campaign.entries.filter((item) => item.status === "COMPLETED").length;
    const entries = campaign.entries.map((item) => node("div", { className: "campaign-entry" }, [
      node("strong", { text: `${item.provider_id} / ${item.model_id}` }),
      node("span", { className: `pill ${statusTone(item.status)}`, text: decisionLabel(item.status) }),
      node("small", {
        text: item.error_message
          ? `要確認: ${item.error_message}`
          : `適合試験 ${decisionLabel(item.conformance_status)} / 予測run ${decisionLabel(item.run_status)}`,
      }),
    ]));
    const selectButton = node("button", {
      type: "button", className: "button secondary", text: "完了runを比較対象に入れる",
      disabled: done === 0, "data-locked": String(done === 0),
    });
    selectButton.addEventListener("click", () => onSelectRuns(campaign));
    const finalization = campaign.finalization;
    const finalizationState = node("div", { className: "campaign-finalization" }, [
      node("span", {
        className: `pill ${statusTone(finalization?.status || "WAITING")}`,
        text: FINALIZATION_LABELS[finalization?.status] || "自動比較未登録",
      }),
      node("small", {
        text: finalization?.mode === "horizon"
          ? `評価条件: horizon ${finalization.horizon}` : "評価条件: 主評価期間",
      }),
    ]);
    if (finalization?.status === "SUCCEEDED") {
      finalizationState.append(node("a", {
        href: `/ui?comparison_id=${encodeURIComponent(finalization.comparison_id)}`,
        className: "button primary", text: "比較結果を開く",
        title: finalization.comparison_id,
      }));
    } else if (finalization?.status === "FAILED") {
      finalizationState.append(
        node("small", { className: "run-warning", text: finalization.error_message || "自動比較に失敗しました。" }),
      );
      const retry = node("button", {
        type: "button", className: "button quiet", text: "自動比較を再実行",
        "data-permission": "ANALYZE",
      });
      retry.addEventListener("click", () => onRetry(campaign.campaign_id));
      finalizationState.append(retry);
    }
    return node("article", { className: "campaign-card" }, [
      node("div", { className: "card-heading" }, [
        node("strong", { text: campaign.purpose }),
        node("span", { className: `pill ${statusTone(campaign.status)}`, text: decisionLabel(campaign.status) }),
      ]),
      node("p", { text: `${done} / ${campaign.entries.length} モデル完了・${dateTime(campaign.created_at)}` }),
      node("code", { text: campaign.campaign_id, title: campaign.campaign_id }),
      ...entries,
      finalizationState,
      selectButton,
    ]);
  });
  replace("campaign-list", cards.length ? cards : [node("div", {
    className: "empty-inline", text: "一括比較はまだありません。左のフォームから開始できます。",
  })]);
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
  intervals.disabled = !supportsIntervals;
  const defaultIntervals = (defaults?.interval_levels || []).join(",");
  if (defaultIntervals && ![...intervals.options].some((item) => item.value === defaultIntervals)) {
    intervals.append(option(defaultIntervals, `既定値（${defaultIntervals}）`));
  }
  intervals.value = supportsIntervals ? defaultIntervals : "";
  document.getElementById("seed").value = defaults?.seed ?? 7;
  document.getElementById("resource-profile").value = defaults?.resource_profile || "cpu-small";
  document.getElementById("training-policy").value = defaults?.training_policy || "FIXED";
  const facts = defaults ? [
    ["前処理版", defaults.preprocessing_version],
    ["Provider設定", JSON.stringify(defaults.params)],
    ["区間予測", !supportsIntervals ? "非対応" : observed ? "時点再現して選択可能" : "選択可能"],
    ["実行方式", provider.capabilities.requires_gpu ? "GPU Worker" : "CPU Worker"],
    ["適合記録", model?.latest_conformance ? "登録済み" : "未登録（比較前に必要）"],
  ] : [["状態", "このProviderには実験既定値がありません"]];
  replace("provider-defaults", facts.map(([label, value]) => node("div", { className: "default-fact" }, [
    node("span", { text: label }), node("code", { text: String(value) }),
  ])));
  document.getElementById("experiment-submit").disabled = !defaults;
}

export function renderExperiments(
  experiments, snapshots, providers, conformances, conformanceJobs, onRun, onConformance,
) {
  const snapshotMap = new Map(snapshots.map((item) => [item.snapshot_id, item]));
  document.getElementById("experiment-filter-count").textContent = `${experiments.length}件`;
  const cards = experiments.map((item) => {
    const definition = item.definition;
    const snapshot = snapshotMap.get(item.snapshot_id);
    const provider = providers.find((value) => value.provider_id === definition.provider_id);
    const conformance = matchingConformance(conformances, definition, provider);
    const conformancePassed = conformance?.status === "PASSED";
    const jobs = conformanceJobs.filter((job) => job.experiment_id === item.experiment_id);
    const latestJob = jobs[0];
    const button = node("button", {
      type: "button", className: "button secondary", text: "この条件で実行登録",
      "data-permission": "ANALYZE",
    });
    button.addEventListener("click", () => onRun(item.experiment_id));
    const testButton = node("button", {
      type: "button", className: "button quiet",
      text: latestJob?.status === "FAILED" || (conformance && !conformancePassed)
        ? "適合試験を再実行" : "適合試験を実行",
      "data-permission": "ANALYZE",
      "data-locked": String(Boolean(
        conformancePassed || ["QUEUED", "RUNNING"].includes(latestJob?.status)
      )),
      disabled: Boolean(
        conformancePassed || ["QUEUED", "RUNNING"].includes(latestJob?.status)
      ),
    });
    testButton.addEventListener("click", () => onConformance(item.experiment_id));
    let testState = "正式比較にはProvider適合試験が必要です。";
    let testTone = "run-warning";
    if (conformancePassed) {
      testState = conformance.fixed_ranking_eligible
        ? "固定7項目に合格し、正式比較に使用できます。"
        : "固定7項目に合格しましたが、このモデルは参考比較用です。";
      testTone = conformance.fixed_ranking_eligible ? "run-ready" : "run-warning";
    } else if (conformance) {
      const failed = conformance.checks.filter((item) => item.status === "FAILED")
        .map((item) => item.code).join(", ");
      testState = `適合試験の未合格項目: ${failed || "詳細を確認してください"}`;
    } else if (["QUEUED", "RUNNING"].includes(latestJob?.status)) {
      testState = latestJob.status === "QUEUED"
        ? "適合試験を待機しています。長時間変わらない場合は適合試験Workerを確認してください。"
        : "適合試験を実行中です。";
    } else if (latestJob?.status === "FAILED") {
      testState = `適合試験を開始できませんでした: ${latestJob.error_message || latestJob.error_code}`;
    }
    return node("article", { className: "experiment-card" }, [
      node("div", { className: "card-heading" }, [
        node("strong", { text: `${definition.provider_id} / ${definition.model_name}` }),
        node("span", { className: "pill neutral", text: definition.training_policy || "FIXED" }),
      ]),
      node("p", { text: snapshot ? snapshotLabel(snapshot) : item.snapshot_id }),
      node("code", { text: item.experiment_id, title: item.experiment_id }),
      node("small", { className: testTone, text: testState }),
      node("div", { className: "experiment-actions" }, [button, testButton]),
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
