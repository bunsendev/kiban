CREATE TABLE IF NOT EXISTS inventory_forecast_bridge_versions (
  bridge_version TEXT PRIMARY KEY,
  content_sha256 TEXT NOT NULL UNIQUE CHECK(length(content_sha256)=64),
  created_by TEXT NOT NULL,
  reason TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL
);
CREATE TABLE IF NOT EXISTS inventory_forecast_bridge_records (
  bridge_version TEXT NOT NULL REFERENCES inventory_forecast_bridge_versions(bridge_version),
  jan TEXT NOT NULL CHECK(length(jan) IN (8,13)),
  warehouse_id TEXT NOT NULL,
  canonical_product_id TEXT NOT NULL,
  forecast_center_id TEXT NOT NULL,
  effective_from DATE NOT NULL,
  effective_to DATE,
  PRIMARY KEY(
    bridge_version,jan,warehouse_id,canonical_product_id,forecast_center_id,effective_from
  ),
  CHECK(effective_to IS NULL OR effective_to >= effective_from)
);
CREATE INDEX IF NOT EXISTS inventory_forecast_bridge_lookup_idx
  ON inventory_forecast_bridge_records(bridge_version,jan,warehouse_id,effective_from);
