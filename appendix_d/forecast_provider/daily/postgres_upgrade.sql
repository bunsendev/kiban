ALTER TABLE closed_days ADD COLUMN IF NOT EXISTS available_at TEXT;
UPDATE closed_days SET available_at=decided_at WHERE available_at IS NULL;
ALTER TABLE closed_days ALTER COLUMN available_at SET NOT NULL;
ALTER TABLE daily_file_completeness ADD COLUMN IF NOT EXISTS available_at TEXT;
UPDATE daily_file_completeness
SET available_at=daily_build_jobs.definition_json::jsonb->>'as_of'
FROM daily_build_jobs
WHERE daily_file_completeness.build_id=daily_build_jobs.build_id
  AND daily_file_completeness.available_at IS NULL;
ALTER TABLE daily_file_completeness ALTER COLUMN available_at SET NOT NULL;
