function canonical(value) {
  if (Array.isArray(value)) return value.map(canonical);
  if (value && typeof value === "object") {
    return Object.fromEntries(Object.keys(value).sort().map((key) => [key, canonical(value[key])]));
  }
  return value;
}

export function sameConfig(record, definition) {
  const expected = {
    params: definition.params || {}, interval_levels: definition.interval_levels || [],
    preprocessing_version: definition.preprocessing_version,
  };
  return JSON.stringify(canonical(record.adapter_config)) === JSON.stringify(canonical(expected));
}

export function matchingConformance(conformances, definition, provider = null) {
  return conformances.find((item) => (
    item.provider_id === definition.provider_id && item.model_id === definition.model_name
    && (!provider || (
      item.provider_version === provider.provider_version
      && item.library_name === provider.library_name
      && item.library_version === provider.library_version
    ))
    && sameConfig(item, definition)
  ));
}

export function runContext(dashboard, run) {
  const terminal = ["SUCCEEDED", "PARTIAL", "FAILED"].includes(run.status);
  if (!terminal) {
    const worker = dashboard.workerStatus.find((item) => item.provider_id === run.provider_id);
    if (!worker || worker.status === "NOT_STARTED") {
      return { eligible: false, reason: "対応するProvider Workerが未起動です。" };
    }
    if (worker.status === "STALE") {
      return { eligible: false, reason: "Provider Workerのheartbeatが遅延しています。" };
    }
    return { eligible: false, reason: "Provider Workerが処理中です。完了後に選択できます。" };
  }
  const experiment = dashboard.experiments.find(
    (item) => item.experiment_id === run.experiment_id,
  );
  if (!experiment) return { eligible: false, reason: "実験定義を確認できません。" };
  const provider = dashboard.providers.find(
    (item) => item.provider_id === experiment.definition.provider_id,
  );
  const conformance = matchingConformance(
    dashboard.conformances, experiment.definition, provider,
  );
  if (!conformance) {
    return { eligible: false, reason: "実験条件と一致するProvider適合記録がありません。" };
  }
  return { eligible: true, experiment, conformance };
}
