CREATE TABLE IF NOT EXISTS lifecycle_plans (
  plan_id TEXT PRIMARY KEY,
  format_version INTEGER NOT NULL,
  condition_fingerprint TEXT NOT NULL UNIQUE,
  plan_version TEXT NOT NULL UNIQUE,
  adoption_id TEXT NOT NULL,
  experiment_id TEXT NOT NULL,
  initial_champion_run_id TEXT NOT NULL,
  fallback_run_id TEXT NOT NULL,
  schedule_day INTEGER NOT NULL CHECK(schedule_day BETWEEN 1 AND 28),
  schedule_time TEXT NOT NULL,
  timezone TEXT NOT NULL,
  trial_start_date TEXT NOT NULL,
  trial_end_date TEXT NOT NULL,
  metric TEXT NOT NULL,
  minimum_improvement_pct REAL NOT NULL,
  maximum_failure_rate REAL NOT NULL,
  created_by TEXT NOT NULL,
  reason TEXT NOT NULL,
  created_at TEXT NOT NULL,
  CHECK(initial_champion_run_id<>fallback_run_id),
  CHECK(trial_start_date<=trial_end_date),
  CHECK(minimum_improvement_pct BETWEEN 0 AND 100),
  CHECK(maximum_failure_rate BETWEEN 0 AND 1)
);

CREATE TABLE IF NOT EXISTS lifecycle_cycles (
  cycle_id TEXT PRIMARY KEY,
  plan_id TEXT NOT NULL REFERENCES lifecycle_plans(plan_id),
  due_month TEXT NOT NULL,
  scheduled_for TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('QUEUED','READY','REJECTED','PROMOTED','FAILED')),
  challenger_run_id TEXT,
  comparison_id TEXT,
  score_json TEXT,
  failure_code TEXT,
  created_at TEXT NOT NULL,
  completed_at TEXT,
  UNIQUE(plan_id,due_month),
  CHECK(
    (status='QUEUED' AND challenger_run_id IS NULL AND comparison_id IS NULL
      AND score_json IS NULL AND failure_code IS NULL AND completed_at IS NULL)
    OR
    (status IN ('READY','REJECTED','PROMOTED') AND challenger_run_id IS NOT NULL
      AND comparison_id IS NOT NULL AND score_json IS NOT NULL
      AND failure_code IS NULL AND completed_at IS NOT NULL)
    OR
    (status='FAILED' AND challenger_run_id IS NULL AND comparison_id IS NULL
      AND score_json IS NULL AND failure_code IS NOT NULL AND completed_at IS NOT NULL)
  )
);
CREATE INDEX IF NOT EXISTS lifecycle_cycle_plan_idx
  ON lifecycle_cycles(plan_id,scheduled_for,cycle_id);

CREATE TABLE IF NOT EXISTS champion_events (
  event_id TEXT PRIMARY KEY,
  plan_id TEXT NOT NULL REFERENCES lifecycle_plans(plan_id),
  revision INTEGER NOT NULL CHECK(revision >= 1),
  action TEXT NOT NULL CHECK(action IN ('INITIALIZED','PROMOTED','ROLLED_BACK')),
  from_run_id TEXT,
  to_run_id TEXT NOT NULL,
  cycle_id TEXT REFERENCES lifecycle_cycles(cycle_id),
  comparison_id TEXT,
  approved_by TEXT NOT NULL,
  reason TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE(plan_id,revision),
  CHECK(
    (action='INITIALIZED' AND revision=1 AND from_run_id IS NULL
      AND cycle_id IS NULL AND comparison_id IS NULL)
    OR
    (action='PROMOTED' AND from_run_id IS NOT NULL
      AND cycle_id IS NOT NULL AND comparison_id IS NOT NULL)
    OR
    (action='ROLLED_BACK' AND from_run_id IS NOT NULL
      AND cycle_id IS NULL AND comparison_id IS NULL)
  )
);

CREATE TABLE IF NOT EXISTS trial_forecast_records (
  record_id TEXT PRIMARY KEY,
  plan_id TEXT NOT NULL REFERENCES lifecycle_plans(plan_id),
  run_id TEXT NOT NULL,
  origin_date TEXT NOT NULL,
  recorded_by TEXT NOT NULL,
  recorded_at TEXT NOT NULL,
  UNIQUE(plan_id,origin_date)
);

CREATE TABLE IF NOT EXISTS trial_assessments (
  assessment_id TEXT PRIMARY KEY,
  plan_id TEXT NOT NULL REFERENCES lifecycle_plans(plan_id),
  revision INTEGER NOT NULL CHECK(revision >= 1),
  period_start TEXT NOT NULL,
  period_end TEXT NOT NULL,
  comparison_id TEXT NOT NULL,
  evidence_kind TEXT NOT NULL CHECK(evidence_kind='FUTURE_TRIAL'),
  decision TEXT NOT NULL CHECK(decision IN ('CONTINUE','COMPLETE','ROLLBACK')),
  assessed_by TEXT NOT NULL,
  reason TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE(plan_id,revision),
  CHECK(period_start<=period_end)
);
