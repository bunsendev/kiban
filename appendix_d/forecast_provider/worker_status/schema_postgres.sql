CREATE TABLE IF NOT EXISTS worker_heartbeats (
  worker_id TEXT PRIMARY KEY,
  instance_id TEXT NOT NULL,
  provider_id TEXT NOT NULL,
  state TEXT NOT NULL CHECK (state IN ('IDLE','WORKING')),
  current_run_id TEXT,
  started_at TIMESTAMPTZ NOT NULL,
  heartbeat_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_worker_heartbeats_provider
  ON worker_heartbeats(provider_id, heartbeat_at DESC, worker_id);
