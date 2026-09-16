CREATE TABLE IF NOT EXISTS api_idempotency_records (
  scope_hash TEXT PRIMARY KEY,
  request_hash TEXT NOT NULL,
  state TEXT NOT NULL CHECK (state IN ('PENDING','COMPLETED')),
  pending_until TEXT NOT NULL,
  status_code INTEGER,
  media_type TEXT,
  response_body BLOB,
  created_at TEXT NOT NULL,
  completed_at TEXT
);
