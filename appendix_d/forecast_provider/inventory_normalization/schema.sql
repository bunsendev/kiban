CREATE TABLE IF NOT EXISTS inventory_normalization_jobs (
  job_id TEXT PRIMARY KEY,
  source_prefix TEXT NOT NULL,
  product_mapping_id TEXT NOT NULL,
  unit_value TEXT NOT NULL,
  requested_by TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('QUEUED','RUNNING','SUCCEEDED','FAILED')),
  file_count INTEGER NOT NULL DEFAULT 0,
  processed_file_count INTEGER NOT NULL DEFAULT 0,
  accepted_row_count INTEGER NOT NULL DEFAULT 0,
  quarantined_row_count INTEGER NOT NULL DEFAULT 0,
  reason_counts_json TEXT NOT NULL DEFAULT '{}',
  error_code TEXT,
  requested_at TIMESTAMPTZ NOT NULL,
  started_at TIMESTAMPTZ,
  finished_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS inventory_normalization_jobs_status_idx
  ON inventory_normalization_jobs(status, requested_at, job_id);
CREATE TABLE IF NOT EXISTS inventory_daily_quantities (
  job_id TEXT NOT NULL REFERENCES inventory_normalization_jobs(job_id),
  inventory_date TEXT NOT NULL,
  jan TEXT NOT NULL,
  center_id TEXT NOT NULL,
  unit TEXT NOT NULL,
  quantity TEXT NOT NULL,
  PRIMARY KEY(job_id, inventory_date, jan, center_id, unit)
);
CREATE TABLE IF NOT EXISTS inventory_normalization_summaries (
  job_id TEXT PRIMARY KEY REFERENCES inventory_normalization_jobs(job_id),
  source_quantity TEXT NOT NULL,
  normalized_quantity TEXT NOT NULL
);
