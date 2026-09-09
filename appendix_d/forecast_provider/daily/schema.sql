CREATE TABLE IF NOT EXISTS file_schedules (
  schedule_id TEXT PRIMARY KEY,
  format_version INTEGER NOT NULL,
  content_hash TEXT NOT NULL UNIQUE,
  definition_json TEXT NOT NULL,
  frozen INTEGER NOT NULL CHECK(frozen=1)
);
CREATE TABLE IF NOT EXISTS planned_files (
  schedule_id TEXT NOT NULL REFERENCES file_schedules(schedule_id),
  logical_path TEXT NOT NULL,
  center_id TEXT NOT NULL,
  file_type TEXT NOT NULL,
  target_start TEXT NOT NULL,
  target_end TEXT NOT NULL,
  absence_means_zero INTEGER NOT NULL CHECK(absence_means_zero IN (0,1)),
  PRIMARY KEY(schedule_id,logical_path)
);
CREATE INDEX IF NOT EXISTS planned_files_target_idx
  ON planned_files(schedule_id,center_id,target_start,target_end);
CREATE TABLE IF NOT EXISTS closed_days (
  closed_day_id TEXT PRIMARY KEY,
  center_id TEXT NOT NULL,
  closed_date TEXT NOT NULL,
  closure_version TEXT NOT NULL,
  available_at TEXT NOT NULL,
  approved_by TEXT NOT NULL,
  reason TEXT NOT NULL,
  decided_at TEXT NOT NULL,
  UNIQUE(center_id,closed_date,closure_version)
);
CREATE TABLE IF NOT EXISTS daily_build_jobs (
  build_id TEXT PRIMARY KEY,
  format_version INTEGER NOT NULL,
  condition_fingerprint TEXT NOT NULL UNIQUE,
  definition_json TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('QUEUED','RUNNING','SUCCEEDED','FAILED')),
  snapshot_id TEXT REFERENCES dataset_snapshots(snapshot_id),
  data_uri TEXT,
  data_sha256 TEXT,
  error TEXT,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS daily_file_completeness (
  build_id TEXT NOT NULL REFERENCES daily_build_jobs(build_id),
  center_id TEXT NOT NULL,
  target_date TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('COMPLETE','MISSING','PARTIAL_OR_INVALID')),
  expected_count INTEGER NOT NULL,
  valid_count INTEGER NOT NULL,
  zero_confirmable INTEGER NOT NULL CHECK(zero_confirmable IN (0,1)),
  available_at TEXT NOT NULL,
  missing_paths_json TEXT NOT NULL,
  invalid_paths_json TEXT NOT NULL,
  PRIMARY KEY(build_id,center_id,target_date)
);
CREATE TABLE IF NOT EXISTS daily_values (
  build_id TEXT NOT NULL REFERENCES daily_build_jobs(build_id),
  canonical_product_id TEXT NOT NULL REFERENCES canonical_products(canonical_product_id),
  center_id TEXT NOT NULL,
  ds TEXT NOT NULL,
  unique_id TEXT NOT NULL,
  raw_quantity TEXT,
  y TEXT,
  state TEXT NOT NULL CHECK(state IN (
    'OBSERVED','CONFIRMED_ZERO','MISSING','NOT_HANDLED','CLOSED','PARTIAL_OR_INVALID'
  )),
  available_at TEXT NOT NULL,
  issue TEXT,
  PRIMARY KEY(build_id,canonical_product_id,center_id,ds)
);
CREATE INDEX IF NOT EXISTS daily_values_snapshot_idx
  ON daily_values(build_id,unique_id,ds);
