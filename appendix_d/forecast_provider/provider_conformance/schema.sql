CREATE TABLE IF NOT EXISTS provider_conformance_jobs (
  job_id TEXT PRIMARY KEY,
  experiment_id TEXT NOT NULL REFERENCES experiments(experiment_id),
  provider_id TEXT NOT NULL,
  model_id TEXT NOT NULL,
  requested_by TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('QUEUED','RUNNING','SUCCEEDED','FAILED')),
  requested_at TIMESTAMPTZ NOT NULL,
  started_at TIMESTAMPTZ,
  finished_at TIMESTAMPTZ,
  conformance_id TEXT REFERENCES provider_conformance_tests(conformance_id),
  error_code TEXT,
  error_message TEXT
);
CREATE INDEX IF NOT EXISTS provider_conformance_jobs_queue_idx
  ON provider_conformance_jobs(provider_id,status,requested_at,job_id);
CREATE INDEX IF NOT EXISTS provider_conformance_jobs_experiment_idx
  ON provider_conformance_jobs(experiment_id,requested_at,job_id);
CREATE UNIQUE INDEX IF NOT EXISTS provider_conformance_jobs_one_active_idx
  ON provider_conformance_jobs(experiment_id)
  WHERE status IN ('QUEUED','RUNNING');
