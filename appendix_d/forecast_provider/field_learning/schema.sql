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
