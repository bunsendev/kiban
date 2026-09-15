CREATE TABLE IF NOT EXISTS mapping_dry_run_jobs (
  job_id TEXT PRIMARY KEY,
  source_path TEXT NOT NULL,
  mapping_id TEXT NOT NULL,
  requested_by TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('QUEUED','RUNNING','SUCCEEDED','FAILED')),
  sample_rows INTEGER NOT NULL CHECK(sample_rows BETWEEN 1 AND 10000),
  requested_at TIMESTAMPTZ NOT NULL,
  started_at TIMESTAMPTZ,
  finished_at TIMESTAMPTZ,
  dry_run_id TEXT,
  outcome TEXT CHECK(outcome IS NULL OR outcome IN ('READY_FOR_NORMALIZATION','REVIEW_REQUIRED','BLOCKED')),
  report_sha256 TEXT,
  error_code TEXT
);
CREATE INDEX IF NOT EXISTS mapping_dry_run_jobs_status_idx
  ON mapping_dry_run_jobs(status, requested_at, job_id);
CREATE TABLE IF NOT EXISTS mapping_dry_run_batches (
  batch_id TEXT PRIMARY KEY,
  source_prefix TEXT NOT NULL,
  mapping_id TEXT NOT NULL,
  requested_by TEXT NOT NULL,
  sample_rows INTEGER NOT NULL CHECK(sample_rows BETWEEN 1 AND 10000),
  requested_at TIMESTAMPTZ NOT NULL,
  selected_count INTEGER NOT NULL,
  excluded_count INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS mapping_dry_run_batch_jobs (
  batch_id TEXT NOT NULL REFERENCES mapping_dry_run_batches(batch_id),
  job_id TEXT NOT NULL REFERENCES mapping_dry_run_jobs(job_id),
  PRIMARY KEY(batch_id, job_id)
);
