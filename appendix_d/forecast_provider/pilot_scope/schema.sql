CREATE TABLE IF NOT EXISTS pilot_scope_versions (
  pilot_scope_version TEXT PRIMARY KEY,
  content_sha256 TEXT NOT NULL UNIQUE CHECK(length(content_sha256)=64),
  scope_kind TEXT NOT NULL CHECK(scope_kind='PILOT_PARTIAL'),
  effective_from DATE NOT NULL,
  effective_to DATE,
  approved_by TEXT NOT NULL,
  reason TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL,
  CHECK(effective_to IS NULL OR effective_to >= effective_from)
);
CREATE TABLE IF NOT EXISTS pilot_scope_items (
  pilot_scope_version TEXT NOT NULL REFERENCES pilot_scope_versions(pilot_scope_version),
  jan TEXT NOT NULL CHECK(length(jan) IN (8,13)),
  warehouse_id TEXT NOT NULL,
  PRIMARY KEY(pilot_scope_version,jan,warehouse_id)
);
CREATE INDEX IF NOT EXISTS pilot_scope_lookup_idx
  ON pilot_scope_items(pilot_scope_version,warehouse_id,jan);

CREATE TABLE IF NOT EXISTS pilot_scoped_snapshot_references (
  scoped_snapshot_id TEXT PRIMARY KEY,
  inventory_snapshot_id TEXT NOT NULL,
  pilot_scope_version TEXT NOT NULL REFERENCES pilot_scope_versions(pilot_scope_version),
  scope_kind TEXT NOT NULL CHECK(scope_kind='PILOT_PARTIAL'),
  source_sha256 TEXT NOT NULL CHECK(length(source_sha256)=64),
  source_row_count INTEGER NOT NULL CHECK(source_row_count >= 0),
  scoped_row_count INTEGER NOT NULL CHECK(scoped_row_count >= 0),
  out_of_scope_row_count INTEGER NOT NULL CHECK(out_of_scope_row_count >= 0),
  quarantined_scope_row_count INTEGER NOT NULL CHECK(quarantined_scope_row_count >= 0),
  source_quantity_cases TEXT NOT NULL,
  scoped_quantity_cases TEXT NOT NULL,
  out_of_scope_quantity_cases TEXT NOT NULL,
  quarantined_scope_quantity_cases TEXT NOT NULL,
  known_at TIMESTAMPTZ NOT NULL,
  recorded_at TIMESTAMPTZ NOT NULL,
  content_sha256 TEXT NOT NULL UNIQUE CHECK(length(content_sha256)=64),
  UNIQUE(inventory_snapshot_id,pilot_scope_version)
);
CREATE INDEX IF NOT EXISTS pilot_scoped_snapshot_lookup_idx
  ON pilot_scoped_snapshot_references(pilot_scope_version,known_at,inventory_snapshot_id);
