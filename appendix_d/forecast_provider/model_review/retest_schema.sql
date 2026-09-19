CREATE TABLE IF NOT EXISTS model_review_retests (
  retest_id TEXT PRIMARY KEY,
  action_id TEXT NOT NULL REFERENCES model_review_actions(action_id),
  request_key_hash TEXT NOT NULL,
  source_campaign_id TEXT NOT NULL REFERENCES comparison_campaigns(campaign_id),
  target_snapshot_id TEXT NOT NULL REFERENCES dataset_snapshots(snapshot_id),
  campaign_id TEXT NOT NULL UNIQUE REFERENCES comparison_campaigns(campaign_id),
  requested_by TEXT NOT NULL,
  requested_at TIMESTAMPTZ NOT NULL,
  outcome_status TEXT CHECK(outcome_status IN ('SUCCEEDED','FAILED')),
  comparison_id TEXT REFERENCES comparison_reports(comparison_id),
  error_message TEXT,
  finished_at TIMESTAMPTZ,
  UNIQUE(action_id,request_key_hash),
  CHECK(
    (outcome_status IS NULL AND comparison_id IS NULL AND error_message IS NULL AND finished_at IS NULL)
    OR (outcome_status='SUCCEEDED' AND comparison_id IS NOT NULL AND error_message IS NULL AND finished_at IS NOT NULL)
    OR (outcome_status='FAILED' AND comparison_id IS NULL AND error_message IS NOT NULL AND finished_at IS NOT NULL)
  )
);
CREATE INDEX IF NOT EXISTS model_review_retests_pending_idx
  ON model_review_retests(outcome_status,requested_at,retest_id);
