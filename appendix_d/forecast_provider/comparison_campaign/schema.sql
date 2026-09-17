CREATE TABLE IF NOT EXISTS comparison_campaigns (
  campaign_id TEXT PRIMARY KEY,
  request_key_hash TEXT NOT NULL,
  snapshot_id TEXT NOT NULL REFERENCES dataset_snapshots(snapshot_id),
  requested_by TEXT NOT NULL,
  purpose TEXT NOT NULL,
  model_keys TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL,
  UNIQUE(requested_by, request_key_hash)
);
CREATE INDEX IF NOT EXISTS comparison_campaigns_created_idx
  ON comparison_campaigns(created_at,campaign_id);
CREATE TABLE IF NOT EXISTS comparison_campaign_entries (
  campaign_id TEXT NOT NULL REFERENCES comparison_campaigns(campaign_id),
  provider_id TEXT NOT NULL,
  model_id TEXT NOT NULL,
  experiment_id TEXT NOT NULL REFERENCES experiments(experiment_id),
  conformance_job_id TEXT NOT NULL REFERENCES provider_conformance_jobs(job_id),
  run_id TEXT NOT NULL REFERENCES forecast_runs(run_id),
  PRIMARY KEY(campaign_id,provider_id,model_id),
  UNIQUE(run_id)
);
