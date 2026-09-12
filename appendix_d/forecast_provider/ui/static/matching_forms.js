const value = (byId, id) => byId(id).value.trim();

export function matchingJobPayload(byId) {
  const normalizationIds = [...byId("job-normalizations").selectedOptions]
    .map((option) => option.value);
  if (!normalizationIds.length) throw new Error("成功済み正規化jobを1件以上選択してください。");
  return {
    normalization_ids: normalizationIds,
    policy_version: value(byId, "job-policy"),
    similarity_threshold: Number(value(byId, "job-similarity")),
    handoff_similarity_threshold: Number(value(byId, "job-handoff-similarity")),
    max_handoff_gap_days: Number(value(byId, "job-gap-days")),
  };
}

export function decisionPayload(byId, candidateId) {
  const decision = value(byId, "decision-value");
  const unresolved = decision === "UNRESOLVED";
  const leftProductId = unresolved ? null : value(byId, "decision-left-product");
  const rightProductId = unresolved ? null : value(byId, "decision-right-product");
  if (!unresolved && (!leftProductId || !rightProductId)) {
    throw new Error("確定判断には左右のcanonical productが必要です。");
  }
  return {
    candidate_id: candidateId,
    decision,
    left_product_id: leftProductId,
    right_product_id: rightProductId,
    mapping_version: value(byId, "decision-version"),
    reason: value(byId, "decision-reason"),
  };
}

export function janMappingPayload(byId) {
  return {
    jan: value(byId, "mapping-jan"),
    canonical_product_id: value(byId, "mapping-product"),
    valid_from: value(byId, "mapping-valid-from"),
    valid_to: value(byId, "mapping-valid-to") || null,
    mapping_version: value(byId, "mapping-version"),
    reason: value(byId, "mapping-reason"),
  };
}

export function syncDecisionInputs(byId) {
  const disabled = value(byId, "decision-value") === "UNRESOLVED";
  byId("decision-left-product").disabled = disabled;
  byId("decision-right-product").disabled = disabled;
}
