CREATE TABLE IF NOT EXISTS column_mappings (
  mapping_id TEXT PRIMARY KEY,
  format_version INTEGER NOT NULL,
  content_hash TEXT NOT NULL UNIQUE,
  definition_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS source_file_selections (
  selection_id TEXT PRIMARY KEY,
  logical_path TEXT NOT NULL,
  source_file_id TEXT NOT NULL REFERENCES source_files(source_file_id),
  decision_version TEXT NOT NULL,
  decided_by TEXT NOT NULL,
  reason TEXT NOT NULL,
  decided_at TEXT NOT NULL,
  UNIQUE(logical_path, decision_version)
);
CREATE TABLE IF NOT EXISTS normalization_jobs (
  normalization_id TEXT PRIMARY KEY,
  source_file_id TEXT NOT NULL REFERENCES source_files(source_file_id),
  mapping_id TEXT NOT NULL REFERENCES column_mappings(mapping_id),
  status TEXT NOT NULL CHECK(status IN ('QUEUED','RUNNING','SUCCEEDED','FAILED')),
  error TEXT,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(source_file_id, mapping_id)
);
CREATE TABLE IF NOT EXISTS shipment_rows (
  normalization_id TEXT NOT NULL REFERENCES normalization_jobs(normalization_id),
  source_file_id TEXT NOT NULL,
  row_number INTEGER NOT NULL,
  center_id TEXT,
  shipment_date TEXT,
  raw_jan TEXT,
  raw_product_name TEXT,
  quantity TEXT,
  unit TEXT,
  row_type TEXT,
  available_at TEXT,
  status TEXT NOT NULL CHECK(status IN ('ACCEPTED','QUARANTINED')),
  error TEXT,
  PRIMARY KEY(normalization_id, row_number)
);
CREATE TABLE IF NOT EXISTS quantity_reconciliations (
  normalization_id TEXT PRIMARY KEY REFERENCES normalization_jobs(normalization_id),
  parseable_quantity TEXT NOT NULL,
  accepted_quantity TEXT NOT NULL,
  quarantined_quantity TEXT NOT NULL,
  unexplained_quantity TEXT NOT NULL
);
