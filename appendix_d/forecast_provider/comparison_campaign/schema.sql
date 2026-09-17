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
CREATE TABLE IF NOT EXISTS comparison_campaign_finalizations (
  campaign_id TEXT PRIMARY KEY REFERENCES comparison_campaigns(campaign_id),
  mode TEXT NOT NULL CHECK(mode IN ('horizon','primary')),
  horizon INTEGER,
  policy_version TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('WAITING','RUNNING','SUCCEEDED','FAILED')),
  requested_at TIMESTAMPTZ NOT NULL,
  started_at TIMESTAMPTZ,
  finished_at TIMESTAMPTZ,
  comparison_id TEXT REFERENCES comparison_reports(comparison_id),
  error_code TEXT,
  error_message TEXT,
  CHECK((mode='primary' AND horizon IS NULL) OR (mode='horizon' AND horizon BETWEEN 1 AND 400)),
  CHECK((status='SUCCEEDED') = (comparison_id IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS comparison_campaign_finalizations_queue_idx
  ON comparison_campaign_finalizations(status,requested_at,campaign_id);
INSERT INTO comparison_campaign_finalizations(
  campaign_id,mode,horizon,policy_version,status,requested_at
)
SELECT campaign_id,'primary',NULL,'evaluation-v2.9','WAITING',created_at
FROM comparison_campaigns
WHERE 1=1
ON CONFLICT(campaign_id) DO NOTHING;
