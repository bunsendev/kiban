CREATE TABLE IF NOT EXISTS selection_candidate_jobs (
  candidate_job_id TEXT PRIMARY KEY,
  format_version INTEGER NOT NULL,
  condition_fingerprint TEXT NOT NULL UNIQUE,
  definition_json TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('QUEUED','RUNNING','SUCCEEDED','FAILED')),
  error TEXT,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS selection_candidates (
  candidate_job_id TEXT NOT NULL REFERENCES selection_candidate_jobs(candidate_job_id),
  canonical_product_id TEXT NOT NULL REFERENCES canonical_products(canonical_product_id),
  rank INTEGER NOT NULL,
  total_quantity TEXT NOT NULL,
  quantity_share TEXT,
  coefficient_of_variation TEXT,
  zero_rate TEXT,
  missing_rate TEXT,
  usable_days INTEGER NOT NULL,
  handled_days INTEGER NOT NULL,
  jan_changed INTEGER NOT NULL CHECK(jan_changed IN (0,1)),
  business_designated INTEGER NOT NULL CHECK(business_designated IN (0,1)),
  center_ids_json TEXT NOT NULL,
  tags_json TEXT NOT NULL,
  eligible INTEGER NOT NULL CHECK(eligible IN (0,1)),
  ineligibility_reason TEXT,
  PRIMARY KEY(candidate_job_id,canonical_product_id),
  UNIQUE(candidate_job_id,rank)
);
CREATE TABLE IF NOT EXISTS selections (
  selection_id TEXT PRIMARY KEY,
  format_version INTEGER NOT NULL,
  condition_fingerprint TEXT NOT NULL UNIQUE,
  selection_version TEXT NOT NULL UNIQUE,
  candidate_job_id TEXT NOT NULL REFERENCES selection_candidate_jobs(candidate_job_id),
  scope TEXT NOT NULL CHECK(scope IN ('INITIAL','FULL')),
  definition_json TEXT NOT NULL,
  selected_by TEXT NOT NULL,
  rationale TEXT NOT NULL,
  selected_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS selection_items (
  selection_id TEXT NOT NULL REFERENCES selections(selection_id),
  canonical_product_id TEXT NOT NULL REFERENCES canonical_products(canonical_product_id),
  center_ids_json TEXT NOT NULL,
  reason TEXT NOT NULL,
  PRIMARY KEY(selection_id,canonical_product_id)
);
CREATE INDEX IF NOT EXISTS selection_candidate_status_idx
  ON selection_candidate_jobs(status,created_at,candidate_job_id);
