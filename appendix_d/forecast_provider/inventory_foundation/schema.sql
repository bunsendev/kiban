CREATE TABLE IF NOT EXISTS inventory_location_master_versions (
  location_master_version TEXT PRIMARY KEY,
  content_sha256 TEXT NOT NULL UNIQUE CHECK(length(content_sha256)=64),
  created_by TEXT NOT NULL,
  reason TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS inventory_locations (
  location_master_version TEXT NOT NULL
    REFERENCES inventory_location_master_versions(location_master_version),
  location_id TEXT NOT NULL,
  location_code TEXT NOT NULL,
  location_name TEXT NOT NULL,
  location_type TEXT NOT NULL CHECK(location_type IN ('FACTORY','WAREHOUSE')),
  effective_from DATE NOT NULL,
  effective_to DATE,
  PRIMARY KEY(location_master_version, location_id),
  UNIQUE(location_master_version, location_code),
  CHECK(effective_to IS NULL OR effective_to >= effective_from)
);
CREATE INDEX IF NOT EXISTS inventory_locations_lookup_idx
  ON inventory_locations(location_master_version, location_type, location_code);

CREATE TABLE IF NOT EXISTS inventory_route_lead_time_policies (
  policy_id TEXT PRIMARY KEY,
  policy_version TEXT NOT NULL UNIQUE,
  location_master_version TEXT NOT NULL,
  factory_location_id TEXT NOT NULL,
  warehouse_location_id TEXT NOT NULL,
  minimum_hours INTEGER NOT NULL,
  standard_hours INTEGER NOT NULL,
  maximum_hours INTEGER NOT NULL,
  recommendation_basis TEXT NOT NULL
    CHECK(recommendation_basis IN ('MINIMUM','STANDARD','MAXIMUM')),
  effective_from DATE NOT NULL,
  effective_to DATE,
  FOREIGN KEY(location_master_version, factory_location_id)
    REFERENCES inventory_locations(location_master_version, location_id),
  FOREIGN KEY(location_master_version, warehouse_location_id)
    REFERENCES inventory_locations(location_master_version, location_id),
  CHECK(factory_location_id <> warehouse_location_id),
  CHECK(12 <= minimum_hours),
  CHECK(minimum_hours <= standard_hours),
  CHECK(standard_hours <= maximum_hours),
  CHECK(maximum_hours <= 36),
  CHECK(effective_to IS NULL OR effective_to >= effective_from)
);
CREATE INDEX IF NOT EXISTS inventory_route_lead_time_lookup_idx
  ON inventory_route_lead_time_policies(
    location_master_version, factory_location_id, warehouse_location_id, effective_from
  );

CREATE TABLE IF NOT EXISTS inventory_input_mapping_versions (
  mapping_version TEXT PRIMARY KEY,
  product_column TEXT NOT NULL,
  product_identifier_kind TEXT NOT NULL
    CHECK(product_identifier_kind IN ('JAN','PRODUCT_CODE')),
  product_mapping_version TEXT,
  location_column TEXT NOT NULL,
  location_master_version TEXT NOT NULL
    REFERENCES inventory_location_master_versions(location_master_version),
  expiry_column TEXT NOT NULL,
  quantity_column TEXT NOT NULL,
  snapshot_at_column TEXT NOT NULL,
  source_quantity_column_name TEXT NOT NULL,
  source_unit_label TEXT NOT NULL,
  normalized_unit TEXT NOT NULL CHECK(normalized_unit='CASE'),
  encoding TEXT NOT NULL,
  delimiter TEXT NOT NULL CHECK(length(delimiter)=1),
  header_row INTEGER NOT NULL CHECK(header_row >= 1),
  created_by TEXT NOT NULL,
  reason TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL,
  CHECK(
    (product_identifier_kind='JAN' AND product_mapping_version IS NULL)
    OR
    (product_identifier_kind='PRODUCT_CODE' AND product_mapping_version IS NOT NULL)
  )
);

CREATE TABLE IF NOT EXISTS inventory_snapshot_jobs (
  job_id TEXT PRIMARY KEY,
  source_kind TEXT NOT NULL CHECK(source_kind IN ('CSV','PDF_EXTRACTED')),
  source_reference TEXT NOT NULL,
  source_sha256 TEXT NOT NULL CHECK(length(source_sha256)=64),
  mapping_version TEXT NOT NULL
    REFERENCES inventory_input_mapping_versions(mapping_version),
  requested_by TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('QUEUED','RUNNING','SUCCEEDED','FAILED')),
  accepted_row_count INTEGER NOT NULL DEFAULT 0 CHECK(accepted_row_count >= 0),
  quarantined_row_count INTEGER NOT NULL DEFAULT 0 CHECK(quarantined_row_count >= 0),
  error_code TEXT,
  known_at TIMESTAMPTZ NOT NULL,
  requested_at TIMESTAMPTZ NOT NULL,
  started_at TIMESTAMPTZ,
  finished_at TIMESTAMPTZ,
  attempt INTEGER NOT NULL DEFAULT 0 CHECK(attempt >= 0),
  worker_id TEXT,
  lease_token TEXT,
  leased_until TIMESTAMPTZ,
  last_heartbeat_at TIMESTAMPTZ,
  CHECK(
    (status='RUNNING' AND worker_id IS NOT NULL AND lease_token IS NOT NULL
      AND leased_until IS NOT NULL)
    OR status<>'RUNNING'
  )
);
CREATE INDEX IF NOT EXISTS inventory_snapshot_jobs_status_idx
  ON inventory_snapshot_jobs(status, requested_at, job_id);
CREATE INDEX IF NOT EXISTS inventory_snapshot_jobs_lease_idx
  ON inventory_snapshot_jobs(status, leased_until, requested_at, job_id);

CREATE TABLE IF NOT EXISTS inventory_source_documents (
  document_id TEXT PRIMARY KEY,
  media_type TEXT NOT NULL,
  archive_reference TEXT NOT NULL,
  source_sha256 TEXT NOT NULL UNIQUE CHECK(length(source_sha256)=64),
  created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS inventory_extractions (
  extraction_id TEXT PRIMARY KEY,
  document_id TEXT NOT NULL REFERENCES inventory_source_documents(document_id),
  extractor_name TEXT NOT NULL,
  extractor_version TEXT NOT NULL,
  config_sha256 TEXT NOT NULL CHECK(length(config_sha256)=64),
  output_reference TEXT NOT NULL,
  output_sha256 TEXT NOT NULL CHECK(length(output_sha256)=64),
  status TEXT NOT NULL
    CHECK(status IN ('EXTRACTED','VALIDATED','REVIEW_REQUIRED','REVIEWED','FAILED')),
  created_at TIMESTAMPTZ NOT NULL,
  UNIQUE(document_id, extractor_name, extractor_version, config_sha256, output_sha256)
);

CREATE TABLE IF NOT EXISTS inventory_extraction_reviews (
  review_id TEXT PRIMARY KEY,
  extraction_id TEXT NOT NULL REFERENCES inventory_extractions(extraction_id),
  decision TEXT NOT NULL CHECK(decision IN ('APPROVED','REJECTED')),
  reviewed_by TEXT NOT NULL,
  reason TEXT NOT NULL,
  reviewed_at TIMESTAMPTZ NOT NULL,
  UNIQUE(extraction_id, review_id, decision)
);
CREATE INDEX IF NOT EXISTS inventory_extraction_reviews_lookup_idx
  ON inventory_extraction_reviews(extraction_id, reviewed_at, review_id);

CREATE TABLE IF NOT EXISTS inventory_snapshots (
  snapshot_id TEXT PRIMARY KEY,
  job_id TEXT REFERENCES inventory_snapshot_jobs(job_id),
  snapshot_at TIMESTAMPTZ NOT NULL,
  known_at TIMESTAMPTZ NOT NULL,
  source_kind TEXT NOT NULL CHECK(source_kind IN ('CSV','PDF_EXTRACTED')),
  source_reference TEXT NOT NULL,
  source_sha256 TEXT NOT NULL CHECK(length(source_sha256)=64),
  mapping_version TEXT NOT NULL
    REFERENCES inventory_input_mapping_versions(mapping_version),
  location_master_version TEXT NOT NULL
    REFERENCES inventory_location_master_versions(location_master_version),
  product_mapping_version TEXT NOT NULL,
  normalized_unit TEXT NOT NULL CHECK(normalized_unit='CASE'),
  row_count INTEGER NOT NULL CHECK(row_count >= 0),
  quantity_cases_total TEXT NOT NULL,
  content_sha256 TEXT NOT NULL UNIQUE CHECK(length(content_sha256)=64),
  created_at TIMESTAMPTZ NOT NULL,
  pdf_extraction_id TEXT,
  pdf_review_id TEXT,
  pdf_review_decision TEXT,
  UNIQUE(snapshot_id, location_master_version),
  FOREIGN KEY(pdf_extraction_id, pdf_review_id, pdf_review_decision)
    REFERENCES inventory_extraction_reviews(extraction_id, review_id, decision),
  CHECK(
    (source_kind='CSV'
      AND pdf_extraction_id IS NULL
      AND pdf_review_id IS NULL
      AND pdf_review_decision IS NULL)
    OR
    (source_kind='PDF_EXTRACTED'
      AND pdf_extraction_id IS NOT NULL
      AND pdf_review_id IS NOT NULL
      AND pdf_review_decision='APPROVED')
  )
);
CREATE INDEX IF NOT EXISTS inventory_snapshots_time_idx
  ON inventory_snapshots(snapshot_at, known_at, snapshot_id);

CREATE TABLE IF NOT EXISTS inventory_expiry_buckets (
  snapshot_id TEXT NOT NULL,
  location_master_version TEXT NOT NULL,
  jan TEXT NOT NULL CHECK(length(jan) IN (8,13)),
  canonical_product_id TEXT,
  location_id TEXT NOT NULL,
  expiry_date DATE NOT NULL,
  bucket_kind TEXT NOT NULL CHECK(bucket_kind='EXPIRY_BUCKET'),
  quantity_cases TEXT NOT NULL,
  normalized_unit TEXT NOT NULL CHECK(normalized_unit='CASE'),
  issue_codes_json TEXT NOT NULL DEFAULT '[]',
  PRIMARY KEY(snapshot_id, jan, location_id, expiry_date, normalized_unit),
  FOREIGN KEY(snapshot_id, location_master_version)
    REFERENCES inventory_snapshots(snapshot_id, location_master_version),
  FOREIGN KEY(location_master_version, location_id)
    REFERENCES inventory_locations(location_master_version, location_id)
);
CREATE INDEX IF NOT EXISTS inventory_expiry_buckets_fefo_idx
  ON inventory_expiry_buckets(snapshot_id, jan, location_id, expiry_date);

CREATE TABLE IF NOT EXISTS inventory_snapshot_quarantines (
  quarantine_id TEXT PRIMARY KEY,
  job_id TEXT NOT NULL REFERENCES inventory_snapshot_jobs(job_id),
  source_reference TEXT NOT NULL,
  row_number INTEGER NOT NULL CHECK(row_number >= 1),
  row_sha256 TEXT NOT NULL CHECK(length(row_sha256)=64),
  reason_code TEXT NOT NULL CHECK(reason_code IN (
    'ROW_SHAPE_INVALID',
    'JAN_MISSING','JAN_INVALID',
    'PRODUCT_MAPPING_MISSING','PRODUCT_MAPPING_AMBIGUOUS',
    'LOCATION_MISSING','LOCATION_UNKNOWN','LOCATION_AMBIGUOUS','LOCATION_TYPE_INVALID',
    'EXPIRY_MISSING','EXPIRY_INVALID',
    'QUANTITY_MISSING','QUANTITY_INVALID','QUANTITY_NEGATIVE',
    'SNAPSHOT_AT_MISSING','SNAPSHOT_AT_INVALID','SNAPSHOT_AT_INCONSISTENT',
    'UNIT_MAPPING_MISSING','SOURCE_DUPLICATE','PDF_EXTRACTION_NOT_APPROVED'
  )),
  created_at TIMESTAMPTZ NOT NULL,
  UNIQUE(job_id, source_reference, row_number, reason_code)
);

CREATE TABLE IF NOT EXISTS inventory_snapshot_reconciliations (
  reconciliation_id TEXT PRIMARY KEY,
  job_id TEXT NOT NULL UNIQUE REFERENCES inventory_snapshot_jobs(job_id),
  source_quantity_cases TEXT NOT NULL,
  normalized_quantity_cases TEXT NOT NULL,
  reconciled INTEGER NOT NULL CHECK(reconciled IN (0,1)),
  created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS inventory_snapshot_decisions (
  decision_id TEXT PRIMARY KEY,
  job_id TEXT NOT NULL REFERENCES inventory_snapshot_jobs(job_id),
  snapshot_id TEXT REFERENCES inventory_snapshots(snapshot_id),
  decision_version TEXT NOT NULL UNIQUE,
  decision TEXT NOT NULL CHECK(decision IN ('APPROVED','REJECTED')),
  decided_by TEXT NOT NULL,
  reason TEXT NOT NULL,
  decided_at TIMESTAMPTZ NOT NULL,
  CHECK(decision='REJECTED' OR snapshot_id IS NOT NULL)
);
CREATE INDEX IF NOT EXISTS inventory_snapshot_decisions_job_idx
  ON inventory_snapshot_decisions(job_id, decided_at, decision_id);
