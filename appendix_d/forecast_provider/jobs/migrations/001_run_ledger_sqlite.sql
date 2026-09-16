CREATE TABLE IF NOT EXISTS forecast_runs (
  run_id TEXT PRIMARY KEY, experiment_id TEXT NOT NULL,
  condition_fingerprint TEXT NOT NULL, provider_id TEXT NOT NULL,
  model_name TEXT NOT NULL, seed INTEGER NOT NULL,
  status TEXT NOT NULL, cancellation_requested INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_forecast_runs_runnable_provider
  ON forecast_runs(provider_id, status, cancellation_requested, run_id);
CREATE TABLE IF NOT EXISTS forecast_origins (
  run_id TEXT NOT NULL REFERENCES forecast_runs(run_id), origin_date TEXT NOT NULL,
  cutoff_at TEXT NOT NULL, status TEXT NOT NULL, attempt INTEGER NOT NULL DEFAULT 0,
  model_artifact TEXT, context_artifact TEXT, error TEXT,
  worker_id TEXT, lease_token TEXT, leased_until TEXT,
  PRIMARY KEY(run_id, origin_date)
);
CREATE TABLE IF NOT EXISTS forecast_expectations (
  run_id TEXT NOT NULL, unique_id TEXT NOT NULL, origin_date TEXT NOT NULL,
  target_date TEXT NOT NULL, horizon INTEGER NOT NULL, status TEXT NOT NULL,
  PRIMARY KEY(run_id, unique_id, origin_date, target_date),
  FOREIGN KEY(run_id, origin_date) REFERENCES forecast_origins(run_id, origin_date)
);
CREATE TABLE IF NOT EXISTS forecast_values (
  run_id TEXT NOT NULL, unique_id TEXT NOT NULL, origin_date TEXT NOT NULL,
  target_date TEXT NOT NULL, horizon INTEGER NOT NULL, forecast_kind TEXT NOT NULL,
  quantile TEXT NOT NULL DEFAULT '', yhat_raw TEXT NOT NULL, yhat TEXT NOT NULL,
  attempt INTEGER NOT NULL,
  PRIMARY KEY(run_id, unique_id, origin_date, target_date, forecast_kind, quantile),
  FOREIGN KEY(run_id, origin_date) REFERENCES forecast_origins(run_id, origin_date)
);
CREATE TABLE IF NOT EXISTS forecast_failures (
  run_id TEXT NOT NULL, origin_date TEXT NOT NULL, attempt INTEGER NOT NULL,
  error TEXT NOT NULL, retryable INTEGER NOT NULL,
  PRIMARY KEY(run_id, origin_date, attempt)
);
