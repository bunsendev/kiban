CREATE TABLE IF NOT EXISTS import_jobs (
  import_id TEXT PRIMARY KEY,
  source_path TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('QUEUED','RUNNING','SUCCEEDED','FAILED')),
  error TEXT,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS source_files (
  source_file_id TEXT PRIMARY KEY,
  import_id TEXT NOT NULL REFERENCES import_jobs(import_id),
  logical_path TEXT NOT NULL,
  size_bytes INTEGER NOT NULL,
  sha256 TEXT NOT NULL,
  encoding TEXT,
  status TEXT NOT NULL CHECK(status IN ('ACCEPTED','QUARANTINED','DUPLICATE','CORRECTION_CANDIDATE')),
  stored_path TEXT,
  duplicate_of TEXT,
  correction_of TEXT,
  error TEXT,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(import_id, logical_path)
);
CREATE INDEX IF NOT EXISTS source_files_hash_idx ON source_files(sha256);
CREATE INDEX IF NOT EXISTS source_files_logical_idx ON source_files(logical_path);
