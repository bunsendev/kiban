CREATE TABLE IF NOT EXISTS forecast_runs (
  run_id TEXT PRIMARY KEY, experiment_id TEXT NOT NULL,
  condition_fingerprint TEXT NOT NULL, provider_id TEXT NOT NULL,
  model_name TEXT NOT NULL, seed BIGINT NOT NULL,
  status TEXT NOT NULL CHECK (status IN
    ('QUEUED','RUNNING','SUCCEEDED','PARTIAL','FAILED','CANCELLED')),
  cancellation_requested INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_forecast_runs_runnable_provider
  ON forecast_runs(provider_id, status, cancellation_requested, run_id);
CREATE TABLE IF NOT EXISTS forecast_origins (
  run_id TEXT NOT NULL REFERENCES forecast_runs(run_id), origin_date DATE NOT NULL,
  cutoff_at TIMESTAMPTZ NOT NULL,
  status TEXT NOT NULL CHECK (status IN
    ('QUEUED','RUNNING','SUCCEEDED','FAILED','CANCELLED')),
  attempt INTEGER NOT NULL DEFAULT 0, model_artifact TEXT, context_artifact TEXT,
  error TEXT, worker_id TEXT, lease_token UUID, leased_until TIMESTAMPTZ,
  PRIMARY KEY(run_id, origin_date)
);
CREATE INDEX IF NOT EXISTS ix_forecast_origins_claim
  ON forecast_origins(run_id, status, origin_date);
CREATE TABLE IF NOT EXISTS forecast_expectations (
  run_id TEXT NOT NULL, unique_id TEXT NOT NULL, origin_date DATE NOT NULL,
  target_date DATE NOT NULL, horizon SMALLINT NOT NULL CHECK (horizon BETWEEN 1 AND 400),
  status TEXT NOT NULL, PRIMARY KEY(run_id, unique_id, origin_date, target_date),
  FOREIGN KEY(run_id, origin_date) REFERENCES forecast_origins(run_id, origin_date),
  CHECK (target_date > origin_date), CHECK (horizon = target_date - origin_date)
);
CREATE TABLE IF NOT EXISTS forecast_values (
  run_id TEXT NOT NULL, unique_id TEXT NOT NULL, origin_date DATE NOT NULL,
  target_date DATE NOT NULL, horizon SMALLINT NOT NULL CHECK (horizon BETWEEN 1 AND 400),
  forecast_kind TEXT NOT NULL CHECK (forecast_kind IN ('POINT','QUANTILE')),
  quantile NUMERIC(8,6), yhat_raw NUMERIC(20,6) NOT NULL,
  yhat NUMERIC(20,6) NOT NULL, attempt INTEGER NOT NULL,
  FOREIGN KEY(run_id, origin_date) REFERENCES forecast_origins(run_id, origin_date),
  CHECK (target_date > origin_date), CHECK (horizon = target_date - origin_date),
  CHECK ((forecast_kind='POINT' AND quantile IS NULL) OR
         (forecast_kind='QUANTILE' AND quantile > 0 AND quantile < 1)),
  CHECK (yhat = GREATEST(yhat_raw, 0))
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_forecast_point ON forecast_values
  (run_id, unique_id, origin_date, target_date) WHERE forecast_kind='POINT';
CREATE UNIQUE INDEX IF NOT EXISTS uq_forecast_quantile ON forecast_values
  (run_id, unique_id, origin_date, target_date, quantile)
  WHERE forecast_kind='QUANTILE';
CREATE UNIQUE INDEX IF NOT EXISTS uq_forecast_point ON forecast_values
  (run_id, unique_id, origin_date, target_date) WHERE forecast_kind='POINT';
CREATE UNIQUE INDEX IF NOT EXISTS uq_forecast_quantile ON forecast_values
  (run_id, unique_id, origin_date, target_date, quantile) WHERE forecast_kind='QUANTILE';
CREATE TABLE IF NOT EXISTS forecast_failures (
  run_id TEXT NOT NULL, origin_date DATE NOT NULL, attempt INTEGER NOT NULL,
  error TEXT NOT NULL, retryable BOOLEAN NOT NULL,
  PRIMARY KEY(run_id, origin_date, attempt),
  FOREIGN KEY(run_id, origin_date) REFERENCES forecast_origins(run_id, origin_date)
);
