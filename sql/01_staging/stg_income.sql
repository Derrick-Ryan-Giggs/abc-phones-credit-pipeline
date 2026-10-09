-- sql/01_staging/stg_income.sql
--
-- SCHEMA CONTRACT for {{STG}}.stg_income
-- One row per loan with usable income data (Income Level sheet). Key: loan_key.
--
-- data_cleaning.py builds this table in Python (parsing, masking and redaction are done before the load) and loads
-- it with WRITE_TRUNCATE, so this file is not run by the pipeline. It is the agreed shape of the table:
-- quality_checks.py compares it with BigQuery's INFORMATION_SCHEMA on every run (check schema.stg_income) and
-- fails if a column is missing, extra or of a different type. Column meanings are in docs/data_dictionary.md.

CREATE TABLE IF NOT EXISTS {{STG}}.stg_income (
  loan_key                   STRING,
  duration_months            INT64,
  received                   FLOAT64,
  persons_received           FLOAT64,
  banks_received             FLOAT64,
  paybills_received          FLOAT64,
  avg_monthly_income         FLOAT64,
  avg_monthly_income_sum_all FLOAT64,
  dq_negative_component      BOOL
);
