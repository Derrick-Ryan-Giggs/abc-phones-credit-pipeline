-- sql/01_staging/stg_credit_snapshots.sql
--
-- SCHEMA CONTRACT for {{STG}}.stg_credit_snapshots
-- One row per loan per snapshot, built from the five credit CSVs. Keys: (loan_key, snapshot_date).
--
-- data_cleaning.py builds this table in Python (parsing, masking and redaction are done before the load) and loads
-- it with WRITE_TRUNCATE, so this file is not run by the pipeline. It is the agreed shape of the table:
-- quality_checks.py compares it with BigQuery's INFORMATION_SCHEMA on every run (check schema.stg_credit_snapshots) and
-- fails if a column is missing, extra or of a different type. Column meanings are in docs/data_dictionary.md.

CREATE TABLE IF NOT EXISTS {{STG}}.stg_credit_snapshots (
  loan_key                        STRING,
  snapshot_date                   DATE,
  sale_date                       DATE,
  credit_expiry_date              DATE,
  next_invoice_date               DATE,
  max_payment_date                DATE,
  balance_due_status              STRING,
  account_status_l1               STRING,
  account_status_l2               STRING,
  credit_check_done               STRING,
  customer_age                    INT64,
  total_paid                      INT64,
  total_due_today                 FLOAT64,
  balance                         FLOAT64,
  days_past_due                   INT64,
  closing_balance                 FLOAT64,
  advance                         FLOAT64,
  balance_due_to_date             FLOAT64,
  arrears                         FLOAT64,
  payment                         INT64,
  expected_payment                FLOAT64,
  first_payment                   INT64,
  first_expected_payment          INT64,
  payment_amount                  FLOAT64,
  adjustment_amount               FLOAT64,
  prepayment_amount               INT64,
  deposit                         FLOAT64,
  weekly_rate                     FLOAT64,
  discount                        FLOAT64,
  overpayment_amount              FLOAT64,
  initial_pay                     INT64,
  total_paid_with_adjustments_15d INT64,
  portfolio_scope                 STRING,
  dq_arrears_zero_days            BOOL,
  dq_days_zero_arrears            BOOL,
  dq_negative_amount              BOOL,
  dq_payment_after_snapshot       BOOL
)
PARTITION BY snapshot_date CLUSTER BY loan_key;
