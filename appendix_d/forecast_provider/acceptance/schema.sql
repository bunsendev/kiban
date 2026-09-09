CREATE TABLE IF NOT EXISTS acceptance_cases (
  case_id TEXT PRIMARY KEY,
  format_version INTEGER NOT NULL,
  condition_fingerprint TEXT NOT NULL UNIQUE,
  definition_json TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('QUEUED','RUNNING','SUCCEEDED','FAILED')),
  outcome TEXT CHECK(outcome IN ('PASSED','FAILED','DRY_RUN')),
  report_uri TEXT,
  report_sha256 TEXT,
  markdown_uri TEXT,
  markdown_sha256 TEXT,
  error TEXT,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS acceptance_checks (
  case_id TEXT NOT NULL REFERENCES acceptance_cases(case_id),
  check_id TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('PASSED','FAILED','NOT_EVALUATED')),
  actual_json TEXT NOT NULL,
  expected_json TEXT NOT NULL,
  detail TEXT NOT NULL,
  PRIMARY KEY(case_id,check_id)
);
CREATE TABLE IF NOT EXISTS acceptance_decisions (
  decision_id TEXT PRIMARY KEY,
  case_id TEXT NOT NULL REFERENCES acceptance_cases(case_id),
  decision_version TEXT NOT NULL,
  decision TEXT NOT NULL CHECK(decision IN ('APPROVED','REJECTED')),
  decided_by TEXT NOT NULL,
  reason TEXT NOT NULL,
  decided_at TEXT NOT NULL,
  UNIQUE(case_id,decision_version)
);
CREATE INDEX IF NOT EXISTS acceptance_case_status_idx
  ON acceptance_cases(status,created_at,case_id);
