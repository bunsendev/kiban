CREATE TABLE IF NOT EXISTS operation_events (
  event_id TEXT PRIMARY KEY,
  flow_session_id TEXT NOT NULL,
  subject TEXT NOT NULL,
  screen TEXT NOT NULL,
  event_name TEXT NOT NULL,
  step INTEGER NOT NULL CHECK (step BETWEEN 1 AND 4),
  sequence INTEGER NOT NULL CHECK (sequence BETWEEN 1 AND 10000),
  outcome TEXT NOT NULL,
  elapsed_ms INTEGER,
  metadata_json TEXT NOT NULL,
  occurred_at TIMESTAMPTZ NOT NULL,
  received_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_operation_events_received
  ON operation_events(received_at DESC);
CREATE INDEX IF NOT EXISTS idx_operation_events_session
  ON operation_events(flow_session_id, sequence);
CREATE INDEX IF NOT EXISTS idx_operation_events_screen_name
  ON operation_events(screen, event_name, received_at DESC);
