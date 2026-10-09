-- sql/01_staging/stg_nps.sql
--
-- SCHEMA CONTRACT for {{STG}}.stg_nps
-- One row per NPS survey response, free text redacted. Key: response_key. A loan may answer more than once.
--
-- data_cleaning.py builds this table in Python (parsing, masking and redaction are done before the load) and loads
-- it with WRITE_TRUNCATE, so this file is not run by the pipeline. It is the agreed shape of the table:
-- quality_checks.py compares it with BigQuery's INFORMATION_SCHEMA on every run (check schema.stg_nps) and
-- fails if a column is missing, extra or of a different type. Column meanings are in docs/data_dictionary.md.

CREATE TABLE IF NOT EXISTS {{STG}}.stg_nps (
  response_key              STRING,
  respondent_key            STRING,
  loan_key                  STRING,
  submitted_date            DATE,
  nps_score                 FLOAT64,
  quality_happy             STRING,
  service_happy             STRING,
  payment_delay_experienced STRING,
  assistance_difficulty     STRING,
  battery_issue             STRING,
  app_usage                 STRING,
  preferred_channel         STRING,
  phone_lock_experienced    STRING,
  reason_text               STRING,
  improve_text              STRING,
  challenge_text            STRING,
  other_feedback_text       STRING,
  nps_category              STRING,
  is_latest_response        BOOL,
  matched_snapshot_date     DATE
);
