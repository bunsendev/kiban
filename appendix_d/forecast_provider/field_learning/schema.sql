CREATE TABLE IF NOT EXISTS field_reference_cases (
  case_id TEXT PRIMARY KEY,
  business_date DATE NOT NULL,
  jan TEXT NOT NULL CHECK(length(jan) IN (8,13)),
  canonical_product_id TEXT NOT NULL,
  warehouse_id TEXT NOT NULL,
  forecast_center_id TEXT NOT NULL,
  forecast_run_id TEXT NOT NULL,
  inventory_snapshot_id TEXT NOT NULL,
  pilot_scope_version TEXT NOT NULL,
  identity_bridge_version TEXT NOT NULL,
  system_forecast_quantity TEXT NOT NULL,
  system_reference_quantity TEXT NOT NULL,
  policy_version TEXT NOT NULL,
  mode TEXT NOT NULL CHECK(mode IN ('SHADOW','ADVISORY','OPERATIONAL')),
  known_at TIMESTAMPTZ NOT NULL,
  recorded_at TIMESTAMPTZ NOT NULL,
  content_sha256 TEXT NOT NULL UNIQUE CHECK(length(content_sha256)=64)
);
CREATE INDEX IF NOT EXISTS field_reference_cases_daily_idx
  ON field_reference_cases(business_date,pilot_scope_version,warehouse_id,jan);
CREATE INDEX IF NOT EXISTS field_reference_cases_report_page_idx
  ON field_reference_cases(business_date DESC,case_id);

CREATE TABLE IF NOT EXISTS field_operator_decision_events (
  decision_event_id TEXT PRIMARY KEY,
  case_id TEXT NOT NULL REFERENCES field_reference_cases(case_id),
  revision INTEGER NOT NULL CHECK(revision >= 1),
  operator_decision TEXT NOT NULL CHECK(operator_decision IN (
    'OBSERVED','ACCEPTED','INCREASED','DECREASED','REJECTED','NO_ACTION'
  )),
  operator_quantity TEXT,
  operator_reason_code TEXT CHECK(operator_reason_code IS NULL OR operator_reason_code IN (
    'PROMOTION','SEASONAL_EVENT','CUSTOMER_INFORMATION','EXPECTED_LARGE_ORDER',
    'PRODUCTION_CONSTRAINT','DELIVERY_CONSTRAINT','EXPIRY_CONCERN','STOCKOUT_CONCERN',
    'WAREHOUSE_CAPACITY','EXPERIENCE_JUDGMENT','DATA_ERROR','OTHER'
  )),
  operator_comment TEXT CHECK(operator_comment IS NULL OR length(operator_comment) <= 500),
  subject TEXT NOT NULL,
  known_at TIMESTAMPTZ NOT NULL,
  recorded_at TIMESTAMPTZ NOT NULL,
  UNIQUE(case_id,revision)
);
CREATE INDEX IF NOT EXISTS field_operator_decisions_case_idx
  ON field_operator_decision_events(case_id,revision);

CREATE TABLE IF NOT EXISTS field_actual_outcome_events (
  actual_event_id TEXT PRIMARY KEY,
  case_id TEXT NOT NULL REFERENCES field_reference_cases(case_id),
  revision INTEGER NOT NULL CHECK(revision >= 1),
  source_version TEXT NOT NULL,
  source_sha256 TEXT NOT NULL CHECK(length(source_sha256)=64),
  actual_shipped_quantity TEXT,
  actual_demand_quantity TEXT,
  stockout_quantity TEXT,
  expired_quantity TEXT,
  interwarehouse_transfer_quantity TEXT,
  known_at TIMESTAMPTZ NOT NULL,
  recorded_at TIMESTAMPTZ NOT NULL,
  content_sha256 TEXT NOT NULL UNIQUE CHECK(length(content_sha256)=64),
  UNIQUE(case_id,revision),
  CHECK(
    actual_shipped_quantity IS NOT NULL OR actual_demand_quantity IS NOT NULL OR
    stockout_quantity IS NOT NULL OR expired_quantity IS NOT NULL OR
    interwarehouse_transfer_quantity IS NOT NULL
  )
);
CREATE INDEX IF NOT EXISTS field_actual_outcomes_case_idx
  ON field_actual_outcome_events(case_id,revision);

CREATE TABLE IF NOT EXISTS field_weekly_reviews (
  review_id TEXT PRIMARY KEY,
  week_start DATE NOT NULL,
  week_end DATE NOT NULL,
  pilot_scope_versions_json TEXT NOT NULL,
  aggregation_version TEXT NOT NULL,
  threshold_version TEXT NOT NULL,
  report_json TEXT NOT NULL,
  reviewer TEXT NOT NULL,
  known_at TIMESTAMPTZ NOT NULL,
  recorded_at TIMESTAMPTZ NOT NULL,
  content_sha256 TEXT NOT NULL UNIQUE CHECK(length(content_sha256)=64)
);
CREATE INDEX IF NOT EXISTS field_weekly_reviews_period_idx
  ON field_weekly_reviews(week_end DESC,review_id);

CREATE TABLE IF NOT EXISTS field_learning_candidates (
  candidate_id TEXT PRIMARY KEY,
  review_id TEXT NOT NULL REFERENCES field_weekly_reviews(review_id),
  candidate_type TEXT NOT NULL CHECK(candidate_type IN (
    'CALENDAR_FEATURE','LARGE_ORDER_INPUT','PRODUCTION_PLAN_INTEGRATION',
    'ROUTE_POLICY','EXPIRY_POLICY','DATA_QUALITY','STOCKOUT_POLICY'
  )),
  evidence_count INTEGER NOT NULL CHECK(evidence_count >= 1),
  impact_quantity TEXT,
  reason_codes_json TEXT NOT NULL,
  evidence_case_ids_json TEXT NOT NULL,
  content_sha256 TEXT NOT NULL UNIQUE CHECK(length(content_sha256)=64)
);
CREATE INDEX IF NOT EXISTS field_learning_candidates_review_idx
  ON field_learning_candidates(review_id,candidate_type,candidate_id);

CREATE TABLE IF NOT EXISTS field_learning_candidate_decision_events (
  decision_event_id TEXT PRIMARY KEY,
  candidate_id TEXT NOT NULL REFERENCES field_learning_candidates(candidate_id),
  revision INTEGER NOT NULL CHECK(revision >= 1),
  decision TEXT NOT NULL CHECK(decision IN ('APPROVED','REJECTED')),
  subject TEXT NOT NULL,
  reason TEXT NOT NULL CHECK(length(reason) <= 500),
  known_at TIMESTAMPTZ NOT NULL,
  recorded_at TIMESTAMPTZ NOT NULL,
  content_sha256 TEXT NOT NULL UNIQUE CHECK(length(content_sha256)=64),
  UNIQUE(candidate_id,revision)
);
CREATE INDEX IF NOT EXISTS field_candidate_decisions_idx
  ON field_learning_candidate_decision_events(candidate_id,revision);

CREATE TABLE IF NOT EXISTS field_learning_experiment_plans (
  plan_id TEXT PRIMARY KEY,
  candidate_id TEXT NOT NULL REFERENCES field_learning_candidates(candidate_id),
  target TEXT NOT NULL CHECK(target IN ('DEMAND_FORECAST','SHIPMENT_RECOMMENDATION')),
  baseline_version TEXT NOT NULL,
  challenger_version TEXT NOT NULL,
  hypothesis TEXT NOT NULL CHECK(length(hypothesis) <= 500),
  evidence_case_ids_json TEXT NOT NULL,
  subject TEXT NOT NULL,
  known_at TIMESTAMPTZ NOT NULL,
  recorded_at TIMESTAMPTZ NOT NULL,
  content_sha256 TEXT NOT NULL UNIQUE CHECK(length(content_sha256)=64),
  case_count INTEGER NOT NULL CHECK(case_count >= 1)
);
CREATE INDEX IF NOT EXISTS field_experiment_plans_candidate_idx
  ON field_learning_experiment_plans(candidate_id,recorded_at DESC,plan_id);

CREATE TABLE IF NOT EXISTS field_learning_experiment_runs (
  run_id TEXT PRIMARY KEY,
  plan_id TEXT NOT NULL REFERENCES field_learning_experiment_plans(plan_id),
  result_version TEXT NOT NULL,
  source_sha256 TEXT NOT NULL CHECK(length(source_sha256)=64),
  report_json TEXT NOT NULL,
  subject TEXT NOT NULL,
  known_at TIMESTAMPTZ NOT NULL,
  recorded_at TIMESTAMPTZ NOT NULL,
  content_sha256 TEXT NOT NULL UNIQUE CHECK(length(content_sha256)=64),
  comparable_count INTEGER NOT NULL CHECK(comparable_count >= 0)
);
CREATE INDEX IF NOT EXISTS field_experiment_runs_plan_idx
  ON field_learning_experiment_runs(plan_id,recorded_at DESC,run_id);

CREATE TABLE IF NOT EXISTS field_learning_experiment_decision_events (
  decision_event_id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL REFERENCES field_learning_experiment_runs(run_id),
  revision INTEGER NOT NULL CHECK(revision >= 1),
  decision TEXT NOT NULL CHECK(decision IN ('RECOMMEND_FORMAL_CHANGE','REJECT_CHANGE')),
  subject TEXT NOT NULL,
  reason TEXT NOT NULL CHECK(length(reason) <= 500),
  known_at TIMESTAMPTZ NOT NULL,
  recorded_at TIMESTAMPTZ NOT NULL,
  content_sha256 TEXT NOT NULL UNIQUE CHECK(length(content_sha256)=64),
  UNIQUE(run_id,revision)
);
CREATE INDEX IF NOT EXISTS field_experiment_decisions_run_idx
  ON field_learning_experiment_decision_events(run_id,revision);

CREATE TABLE IF NOT EXISTS field_formal_change_proposals (
  proposal_id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL REFERENCES field_learning_experiment_runs(run_id),
  source_decision_revision INTEGER NOT NULL CHECK(source_decision_revision >= 1),
  change_target TEXT NOT NULL CHECK(change_target IN (
    'FORECAST_MODEL','FORECAST_FEATURE','SHIPMENT_POLICY','ROUTE_POLICY','DATA_CONTRACT'
  )),
  current_configuration_json TEXT NOT NULL,
  proposed_configuration_json TEXT NOT NULL,
  application_scope_json TEXT NOT NULL,
  acceptance_criteria_json TEXT NOT NULL,
  rollback_conditions_json TEXT NOT NULL,
  rollback_target_version TEXT NOT NULL,
  author TEXT NOT NULL,
  known_at TIMESTAMPTZ NOT NULL,
  recorded_at TIMESTAMPTZ NOT NULL,
  content_sha256 TEXT NOT NULL UNIQUE CHECK(length(content_sha256)=64),
  application_status TEXT NOT NULL CHECK(application_status='NOT_APPLIED')
);
CREATE INDEX IF NOT EXISTS field_formal_change_proposals_run_idx
  ON field_formal_change_proposals(run_id,recorded_at);

CREATE TABLE IF NOT EXISTS field_formal_change_decision_events (
  decision_event_id TEXT PRIMARY KEY,
  proposal_id TEXT NOT NULL REFERENCES field_formal_change_proposals(proposal_id),
  revision INTEGER NOT NULL CHECK(revision >= 1),
  decision TEXT NOT NULL CHECK(decision IN ('APPROVED_FOR_IMPLEMENTATION','REJECTED')),
  approver TEXT NOT NULL,
  reason TEXT NOT NULL CHECK(length(reason) <= 500),
  known_at TIMESTAMPTZ NOT NULL,
  recorded_at TIMESTAMPTZ NOT NULL,
  content_sha256 TEXT NOT NULL UNIQUE CHECK(length(content_sha256)=64),
  UNIQUE(proposal_id,revision)
);
CREATE INDEX IF NOT EXISTS field_formal_change_decisions_proposal_idx
  ON field_formal_change_decision_events(proposal_id,revision);

CREATE TABLE IF NOT EXISTS field_change_applications (
  application_id TEXT PRIMARY KEY,
  proposal_id TEXT NOT NULL REFERENCES field_formal_change_proposals(proposal_id),
  source_proposal_decision_revision INTEGER NOT NULL
    CHECK(source_proposal_decision_revision >= 1),
  candidate_version TEXT NOT NULL,
  application_scope_json TEXT NOT NULL,
  backup_reference TEXT NOT NULL,
  backup_sha256 TEXT NOT NULL CHECK(length(backup_sha256)=64),
  executor TEXT NOT NULL,
  known_at TIMESTAMPTZ NOT NULL,
  recorded_at TIMESTAMPTZ NOT NULL,
  content_sha256 TEXT NOT NULL UNIQUE CHECK(length(content_sha256)=64)
);
CREATE INDEX IF NOT EXISTS field_change_applications_proposal_idx
  ON field_change_applications(proposal_id,recorded_at);

CREATE TABLE IF NOT EXISTS field_change_application_events (
  event_id TEXT PRIMARY KEY,
  application_id TEXT NOT NULL REFERENCES field_change_applications(application_id),
  revision INTEGER NOT NULL CHECK(revision >= 1),
  transition TEXT NOT NULL CHECK(transition IN (
    'PILOT_GATE_EVALUATED','ACCEPTANCE_EVALUATED','ROLLBACK_EVALUATED'
  )),
  resulting_state TEXT NOT NULL CHECK(resulting_state IN (
    'PILOT_ACTIVE','BLOCKED','ROLLBACK_REQUIRED','ACCEPTED','ROLLED_BACK'
  )),
  actor TEXT NOT NULL,
  reason TEXT NOT NULL CHECK(length(reason) <= 500),
  evidence_json TEXT NOT NULL,
  known_at TIMESTAMPTZ NOT NULL,
  recorded_at TIMESTAMPTZ NOT NULL,
  content_sha256 TEXT NOT NULL UNIQUE CHECK(length(content_sha256)=64),
  UNIQUE(application_id,revision)
);
CREATE INDEX IF NOT EXISTS field_change_application_events_application_idx
  ON field_change_application_events(application_id,revision);

CREATE TABLE IF NOT EXISTS field_runtime_assignment_resolutions (
  resolution_id TEXT PRIMARY KEY,
  execution_key TEXT NOT NULL,
  pilot_scope_version TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN (
    'BASELINE_SELECTED','CANDIDATE_SELECTED','BLOCKED'
  )),
  selected_version TEXT NOT NULL,
  selected_configuration_json TEXT NOT NULL,
  application_id TEXT REFERENCES field_change_applications(application_id),
  application_revision INTEGER CHECK(application_revision >= 1),
  proposal_id TEXT REFERENCES field_formal_change_proposals(proposal_id),
  candidate_manifest_sha256 TEXT CHECK(
    candidate_manifest_sha256 IS NULL OR length(candidate_manifest_sha256)=64
  ),
  reason_code TEXT NOT NULL,
  actor TEXT NOT NULL,
  known_at TIMESTAMPTZ NOT NULL,
  recorded_at TIMESTAMPTZ NOT NULL,
  content_sha256 TEXT NOT NULL UNIQUE CHECK(length(content_sha256)=64),
  CHECK((application_id IS NULL) = (application_revision IS NULL))
);
CREATE INDEX IF NOT EXISTS field_runtime_assignment_execution_idx
  ON field_runtime_assignment_resolutions(execution_key,recorded_at);
CREATE INDEX IF NOT EXISTS field_runtime_assignment_scope_idx
  ON field_runtime_assignment_resolutions(pilot_scope_version,recorded_at);
