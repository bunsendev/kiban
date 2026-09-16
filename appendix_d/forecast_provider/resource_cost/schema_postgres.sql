CREATE TABLE IF NOT EXISTS resource_measurements (
  measurement_id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL REFERENCES forecast_runs(run_id),
  origin_date DATE NOT NULL,
  attempt INTEGER NOT NULL CHECK (attempt > 0),
  metric TEXT NOT NULL,
  unit TEXT NOT NULL,
  quantity NUMERIC NOT NULL CHECK (quantity >= 0),
  source TEXT NOT NULL,
  identity TEXT,
  measured_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_resource_measurements_run
  ON resource_measurements(run_id, metric);
CREATE TABLE IF NOT EXISTS resource_unit_prices (
  price_id TEXT PRIMARY KEY,
  provider_id TEXT NOT NULL,
  metric TEXT NOT NULL,
  unit TEXT NOT NULL,
  unit_price NUMERIC NOT NULL CHECK (unit_price >= 0),
  currency TEXT NOT NULL,
  retrieved_on DATE NOT NULL,
  source_ref TEXT NOT NULL,
  created_by TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_resource_unit_prices_lookup
  ON resource_unit_prices(provider_id, metric, retrieved_on DESC, created_at DESC);
