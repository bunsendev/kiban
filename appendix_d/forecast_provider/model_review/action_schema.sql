CREATE TABLE IF NOT EXISTS model_review_actions (
  action_id TEXT PRIMARY KEY,
  review_id TEXT NOT NULL REFERENCES model_drift_reviews(review_id),
  action_type TEXT NOT NULL CHECK(action_type IN (
    'RETEST','DATA_FIX','BUSINESS_CONFIRMATION','MODEL_REVIEW','LIFECYCLE_TRIAL','OTHER'
  )),
  title TEXT NOT NULL,
  created_by TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS model_review_actions_review_idx
  ON model_review_actions(review_id,created_at,action_id);
CREATE TABLE IF NOT EXISTS model_review_action_events (
  event_id TEXT PRIMARY KEY,
  action_id TEXT NOT NULL REFERENCES model_review_actions(action_id),
  revision INTEGER NOT NULL CHECK(revision >= 1),
  status TEXT NOT NULL CHECK(status IN (
    'OPEN','IN_PROGRESS','BLOCKED','COMPLETED','CANCELLED'
  )),
  assignee TEXT NOT NULL,
  due_date DATE NOT NULL,
  note TEXT NOT NULL,
  completion_evidence TEXT,
  recorded_by TEXT NOT NULL,
  recorded_at TIMESTAMPTZ NOT NULL,
  UNIQUE(action_id,revision),
  CHECK((status='COMPLETED') = (completion_evidence IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS model_review_action_events_current_idx
  ON model_review_action_events(action_id,revision);
