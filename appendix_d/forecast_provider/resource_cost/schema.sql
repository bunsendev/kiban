CREATE TABLE IF NOT EXISTS resource_measurements (
  measurement_id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL REFERENCES forecast_runs(run_id),
  origin_date TEXT NOT NULL,
  attempt INTEGER NOT NULL,
  metric TEXT NOT NULL,
  unit TEXT NOT NULL,
  quantity TEXT NOT NULL,
  source TEXT NOT NULL,
  identity TEXT,
  measured_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_resource_measurements_run
  ON resource_measurements(run_id, metric);
CREATE TABLE IF NOT EXISTS resource_unit_prices (
  price_id TEXT PRIMARY KEY,
  provider_id TEXT NOT NULL,
  metric TEXT NOT NULL,
  unit TEXT NOT NULL,
  unit_price TEXT NOT NULL,
  currency TEXT NOT NULL,
  retrieved_on TEXT NOT NULL,
  source_ref TEXT NOT NULL,
  created_by TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_resource_unit_prices_lookup
  ON resource_unit_prices(provider_id, metric, retrieved_on DESC, created_at DESC);
