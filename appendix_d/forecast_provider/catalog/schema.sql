CREATE TABLE IF NOT EXISTS dataset_snapshots (
  snapshot_id TEXT PRIMARY KEY,
  format_version INTEGER NOT NULL,
  content_hash TEXT NOT NULL UNIQUE,
  manifest_json TEXT NOT NULL,
  frozen INTEGER NOT NULL CHECK (frozen=1)
);
CREATE TABLE IF NOT EXISTS experiments (
  experiment_id TEXT PRIMARY KEY,
  format_version INTEGER NOT NULL,
  condition_fingerprint TEXT NOT NULL UNIQUE,
  snapshot_id TEXT NOT NULL REFERENCES dataset_snapshots(snapshot_id),
  definition_json TEXT NOT NULL
);
