CREATE TABLE IF NOT EXISTS model_drift_reviews (
  review_id TEXT PRIMARY KEY,
  comparison_profile_id TEXT NOT NULL,
  decision_version TEXT NOT NULL,
  conclusion TEXT NOT NULL CHECK(conclusion IN (
    'INVESTIGATING','DATA_ISSUE','BUSINESS_EVENT','MODEL_ISSUE','NO_ACTION'
  )),
  reviewed_by TEXT NOT NULL,
  reason TEXT NOT NULL,
  action TEXT NOT NULL,
  evidence_sha256 TEXT NOT NULL,
  evidence_json TEXT NOT NULL,
  reviewed_at TIMESTAMPTZ NOT NULL,
  UNIQUE(comparison_profile_id,decision_version)
);
CREATE INDEX IF NOT EXISTS model_drift_reviews_profile_idx
  ON model_drift_reviews(comparison_profile_id,reviewed_at,review_id);
