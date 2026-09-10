CREATE TABLE IF NOT EXISTS provider_conformance_tests (
  conformance_id TEXT PRIMARY KEY,
  format_version INTEGER NOT NULL,
  condition_fingerprint TEXT NOT NULL UNIQUE,
  provider_id TEXT NOT NULL,
  provider_version TEXT NOT NULL,
  model_id TEXT NOT NULL,
  library_name TEXT NOT NULL,
  library_version TEXT NOT NULL,
  test_suite_version TEXT NOT NULL,
  adapter_config_json TEXT NOT NULL,
  environment_json TEXT NOT NULL,
  checks_json TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('PASSED','FAILED')),
  fixed_ranking_eligible INTEGER NOT NULL CHECK(fixed_ranking_eligible IN (0,1)),
  executed_by TEXT NOT NULL,
  executed_at TEXT NOT NULL,
  evidence_uri TEXT,
  evidence_sha256 TEXT,
  CHECK((evidence_uri IS NULL) = (evidence_sha256 IS NULL))
);
CREATE INDEX IF NOT EXISTS provider_conformance_lookup_idx
  ON provider_conformance_tests(provider_id,model_id,executed_at,conformance_id);

CREATE TABLE IF NOT EXISTS comparison_reports (
  comparison_id TEXT PRIMARY KEY,
  format_version INTEGER NOT NULL,
  condition_fingerprint TEXT NOT NULL UNIQUE,
  definition_json TEXT NOT NULL,
  result_json TEXT NOT NULL,
  comparison_set_id TEXT NOT NULL,
  official_comparison_set_id TEXT NOT NULL,
  truth_version TEXT NOT NULL,
  evaluation_scope_hash TEXT NOT NULL,
  mode TEXT NOT NULL CHECK(mode IN ('horizon','primary')),
  horizon INTEGER,
  ranking_ready INTEGER NOT NULL CHECK(ranking_ready IN (0,1)),
  official_ranking_ready INTEGER NOT NULL CHECK(official_ranking_ready IN (0,1)),
  created_at TEXT NOT NULL,
  CHECK(horizon IS NULL OR horizon BETWEEN 1 AND 400)
);
CREATE TABLE IF NOT EXISTS comparison_runs (
  comparison_id TEXT NOT NULL REFERENCES comparison_reports(comparison_id),
  run_id TEXT NOT NULL REFERENCES forecast_runs(run_id),
  provider_id TEXT NOT NULL,
  model_name TEXT NOT NULL,
  conformance_id TEXT NOT NULL REFERENCES provider_conformance_tests(conformance_id),
  score_json TEXT NOT NULL,
  PRIMARY KEY(comparison_id,run_id)
);
CREATE INDEX IF NOT EXISTS comparison_run_lookup_idx
  ON comparison_runs(run_id,comparison_id);
