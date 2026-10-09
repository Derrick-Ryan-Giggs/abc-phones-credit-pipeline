-- sql/04_dq_checks/dq_null_thresholds.sql
-- CHECK 5: NULL THRESHOLDS ("what share of missing values is acceptable per column?")
-- Keys may never be null. Other thresholds sit a little above what the profiling run observed,
-- so they flag drift without alerting on today's normal level.

WITH checks AS (
  SELECT 'nulls.credit.loan_key' AS check_name, 'critical' AS severity,
         1.0 * SUM(CASE WHEN loan_key IS NULL THEN 1 ELSE 0 END) / COUNT(*) AS observed, 0.0 AS threshold,
         'Null share of stg_credit_snapshots.loan_key (keys must never be null)' AS description
  FROM {{STG}}.stg_credit_snapshots
  UNION ALL
  SELECT 'nulls.credit.snapshot_date', 'critical', 1.0 * SUM(CASE WHEN snapshot_date IS NULL THEN 1 ELSE 0 END) / COUNT(*), 0.0,
         'Null share of stg_credit_snapshots.snapshot_date (the DATE column must parse)'
  FROM {{STG}}.stg_credit_snapshots
  UNION ALL
  SELECT 'nulls.credit.account_status_l2', 'critical', 1.0 * SUM(CASE WHEN account_status_l2 IS NULL THEN 1 ELSE 0 END) / COUNT(*), 0.01,
         'Null share of account_status_l2 (limit 1%)'
  FROM {{STG}}.stg_credit_snapshots
  UNION ALL
  SELECT 'nulls.credit.days_past_due', 'warning', 1.0 * SUM(CASE WHEN days_past_due IS NULL THEN 1 ELSE 0 END) / COUNT(*), 0.005,
         'Null share of days_past_due (limit 0.5%)'
  FROM {{STG}}.stg_credit_snapshots
  UNION ALL
  SELECT 'nulls.credit.arrears', 'warning', 1.0 * SUM(CASE WHEN arrears IS NULL THEN 1 ELSE 0 END) / COUNT(*), 0.005,
         'Null share of arrears (limit 0.5%)'
  FROM {{STG}}.stg_credit_snapshots
  UNION ALL
  SELECT 'nulls.credit.total_due_today', 'warning', 1.0 * SUM(CASE WHEN total_due_today IS NULL THEN 1 ELSE 0 END) / COUNT(*), 0.005,
         'Null share of total_due_today (limit 0.5%)'
  FROM {{STG}}.stg_credit_snapshots
  UNION ALL
  SELECT 'nulls.credit.max_payment_date', 'warning', 1.0 * SUM(CASE WHEN max_payment_date IS NULL THEN 1 ELSE 0 END) / COUNT(*), 0.03,
         'Null share of max_payment_date (limit 3%, about 1% today)'
  FROM {{STG}}.stg_credit_snapshots
  UNION ALL
  SELECT 'nulls.sales.loan_key', 'critical', 1.0 * SUM(CASE WHEN loan_key IS NULL THEN 1 ELSE 0 END) / COUNT(*), 0.0,
         'Null share of stg_sales.loan_key'
  FROM {{STG}}.stg_sales
  UNION ALL
  SELECT 'nulls.sales.sale_type', 'warning', 1.0 * SUM(CASE WHEN sale_type IS NULL THEN 1 ELSE 0 END) / COUNT(*), 0.01,
         'Null share of sale_type (limit 1%)'
  FROM {{STG}}.stg_sales
  UNION ALL
  SELECT 'nulls.sales.loan_term_months', 'warning', 1.0 * SUM(CASE WHEN loan_term_months IS NULL THEN 1 ELSE 0 END) / COUNT(*), 0.06,
         'Null share of loan_term_months (limit 6%; non-numeric terms such as STDHIGH are about 3.7% today)'
  FROM {{STG}}.stg_sales
  UNION ALL
  SELECT 'nulls.nps.loan_key', 'critical', 1.0 * SUM(CASE WHEN loan_key IS NULL THEN 1 ELSE 0 END) / COUNT(*), 0.0,
         'Null share of stg_nps.loan_key'
  FROM {{STG}}.stg_nps
  UNION ALL
  SELECT 'nulls.nps.nps_score', 'warning', 1.0 * SUM(CASE WHEN nps_score IS NULL THEN 1 ELSE 0 END) / COUNT(*), 0.05,
         'Null share of nps_score (limit 5%, about 3.5% today)'
  FROM {{STG}}.stg_nps
  UNION ALL
  SELECT 'nulls.income.avg_monthly_income', 'warning', 1.0 * SUM(CASE WHEN avg_monthly_income IS NULL THEN 1 ELSE 0 END) / COUNT(*), 0.05,
         'Null share of avg_monthly_income (needs a Duration above zero)'
  FROM {{STG}}.stg_income
)
SELECT check_name, severity, observed, threshold, (observed <= threshold) AS passed, description FROM checks;
