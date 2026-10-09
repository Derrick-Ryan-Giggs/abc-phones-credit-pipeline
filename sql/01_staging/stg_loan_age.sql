-- sql/01_staging/stg_loan_age.sql
--
-- SCHEMA CONTRACT for {{STG}}.stg_loan_age
-- Age and age band for every credit row, as at that snapshot date. The date of birth is discarded. Keys: (loan_key, snapshot_date).
--
-- data_cleaning.py builds this table in Python (parsing, masking and redaction are done before the load) and loads
-- it with WRITE_TRUNCATE, so this file is not run by the pipeline. It is the agreed shape of the table:
-- quality_checks.py compares it with BigQuery's INFORMATION_SCHEMA on every run (check schema.stg_loan_age) and
-- fails if a column is missing, extra or of a different type. Column meanings are in docs/data_dictionary.md.

CREATE TABLE IF NOT EXISTS {{STG}}.stg_loan_age (
  loan_key           STRING,
  snapshot_date      DATE,
  age_years          INT64,
  age_band           STRING,
  age_unknown_reason STRING
);
