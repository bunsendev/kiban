CREATE TABLE IF NOT EXISTS matching_jobs (
  matching_job_id TEXT PRIMARY KEY,
  format_version INTEGER NOT NULL,
  condition_fingerprint TEXT NOT NULL UNIQUE,
  definition_json TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('QUEUED','RUNNING','SUCCEEDED','FAILED')),
  error TEXT,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS matching_candidates (
  candidate_id TEXT PRIMARY KEY,
  matching_job_id TEXT NOT NULL REFERENCES matching_jobs(matching_job_id),
  left_jan TEXT NOT NULL,
  right_jan TEXT NOT NULL,
  details_json TEXT NOT NULL,
  UNIQUE(matching_job_id,left_jan,right_jan)
);
CREATE TABLE IF NOT EXISTS canonical_products (
  canonical_product_id TEXT PRIMARY KEY,
  display_name TEXT NOT NULL,
  created_by TEXT NOT NULL,
  reason TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS matching_decisions (
  decision_id TEXT PRIMARY KEY,
  candidate_id TEXT NOT NULL REFERENCES matching_candidates(candidate_id),
  decision TEXT NOT NULL CHECK(decision IN ('SAME_PRODUCT','DIFFERENT_PRODUCT','SUCCESSOR','UNRESOLVED')),
  left_product_id TEXT REFERENCES canonical_products(canonical_product_id),
  right_product_id TEXT REFERENCES canonical_products(canonical_product_id),
  mapping_version TEXT NOT NULL,
  approved_by TEXT NOT NULL,
  reason TEXT NOT NULL,
  decided_at TEXT NOT NULL,
  CHECK(
    (decision='UNRESOLVED' AND left_product_id IS NULL AND right_product_id IS NULL)
    OR (decision='SAME_PRODUCT' AND left_product_id IS NOT NULL AND left_product_id=right_product_id)
    OR (decision IN ('DIFFERENT_PRODUCT','SUCCESSOR') AND left_product_id IS NOT NULL
        AND right_product_id IS NOT NULL AND left_product_id<>right_product_id)
  ),
  UNIQUE(candidate_id,mapping_version)
);
CREATE TABLE IF NOT EXISTS jan_mappings (
  jan_mapping_id TEXT PRIMARY KEY,
  jan TEXT NOT NULL,
  canonical_product_id TEXT NOT NULL REFERENCES canonical_products(canonical_product_id),
  valid_from TEXT NOT NULL,
  valid_to TEXT,
  mapping_version TEXT NOT NULL,
  approved_by TEXT NOT NULL,
  reason TEXT NOT NULL,
  decided_at TEXT NOT NULL,
  UNIQUE(jan,canonical_product_id,valid_from,mapping_version)
);
CREATE INDEX IF NOT EXISTS jan_mappings_lookup_idx ON jan_mappings(jan,mapping_version,valid_from,valid_to);
CREATE TABLE IF NOT EXISTS handling_periods (
  handling_period_id TEXT PRIMARY KEY,
  canonical_product_id TEXT NOT NULL REFERENCES canonical_products(canonical_product_id),
  center_id TEXT NOT NULL,
  valid_from TEXT NOT NULL,
  valid_to TEXT,
  status TEXT NOT NULL CHECK(status IN ('CONFIRMED','TENTATIVE')),
  period_version TEXT NOT NULL,
  approved_by TEXT NOT NULL,
  basis TEXT NOT NULL,
  decided_at TEXT NOT NULL,
  UNIQUE(canonical_product_id,center_id,valid_from,period_version)
);
CREATE INDEX IF NOT EXISTS handling_periods_lookup_idx ON handling_periods(canonical_product_id,center_id,period_version,valid_from,valid_to);
