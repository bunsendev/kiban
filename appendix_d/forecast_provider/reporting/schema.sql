CREATE TABLE IF NOT EXISTS report_exports (
  export_id TEXT PRIMARY KEY,
  format_version INTEGER NOT NULL,
  condition_fingerprint TEXT NOT NULL UNIQUE,
  comparison_id TEXT NOT NULL REFERENCES comparison_reports(comparison_id),
  export_version TEXT NOT NULL,
  baseline_run_id TEXT NOT NULL REFERENCES forecast_runs(run_id),
  requested_by TEXT NOT NULL,
  output_uri TEXT NOT NULL,
  output_sha256 TEXT NOT NULL,
  row_count INTEGER NOT NULL CHECK(row_count > 0),
  created_at TEXT NOT NULL,
  UNIQUE(comparison_id,export_version)
);
CREATE INDEX IF NOT EXISTS report_export_comparison_idx
  ON report_exports(comparison_id,created_at,export_id);

CREATE TABLE IF NOT EXISTS adoption_records (
  adoption_id TEXT PRIMARY KEY,
  format_version INTEGER NOT NULL,
  condition_fingerprint TEXT NOT NULL UNIQUE,
  adoption_version TEXT NOT NULL UNIQUE,
  comparison_id TEXT NOT NULL REFERENCES comparison_reports(comparison_id),
  acceptance_case_id TEXT REFERENCES acceptance_cases(case_id),
  decision TEXT NOT NULL CHECK(decision IN ('ADOPTED','REJECTED')),
  selected_run_id TEXT REFERENCES forecast_runs(run_id),
  fallback_run_id TEXT REFERENCES forecast_runs(run_id),
  target_json TEXT NOT NULL,
  decided_by TEXT NOT NULL,
  reason TEXT NOT NULL,
  decided_at TEXT NOT NULL,
  CHECK(
    (decision='ADOPTED' AND acceptance_case_id IS NOT NULL
      AND selected_run_id IS NOT NULL AND fallback_run_id IS NOT NULL
      AND selected_run_id<>fallback_run_id)
    OR
    (decision='REJECTED' AND acceptance_case_id IS NULL
      AND selected_run_id IS NULL AND fallback_run_id IS NULL)
  )
);
CREATE INDEX IF NOT EXISTS adoption_comparison_idx
  ON adoption_records(comparison_id,decided_at,adoption_id);
