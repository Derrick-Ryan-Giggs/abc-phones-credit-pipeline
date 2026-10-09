-- sql/04_dq_checks/dq_uniqueness.sql
-- CHECK 2: UNIQUENESS ("are there unexpected duplicate loans or records?")
-- observed = number of keys that appear more than once.

WITH checks AS (
  SELECT 'uniqueness.credit_loan_snapshot' AS check_name, 'critical' AS severity,
         1.0 * (SELECT COUNT(*) FROM (SELECT loan_key, snapshot_date FROM {{STG}}.stg_credit_snapshots
                                      GROUP BY loan_key, snapshot_date HAVING COUNT(*) > 1) AS d) AS observed,
         0.0 AS threshold,
         'Duplicate (loan_key, snapshot_date) in stg_credit_snapshots' AS description
  UNION ALL
  SELECT 'uniqueness.sales_loan', 'critical',
         1.0 * (SELECT COUNT(*) FROM (SELECT loan_key FROM {{STG}}.stg_sales GROUP BY loan_key HAVING COUNT(*) > 1) AS d),
         0.0, 'Duplicate loan_key in stg_sales'
  UNION ALL
  SELECT 'uniqueness.income_loan', 'critical',
         1.0 * (SELECT COUNT(*) FROM (SELECT loan_key FROM {{STG}}.stg_income GROUP BY loan_key HAVING COUNT(*) > 1) AS d),
         0.0, 'Duplicate loan_key in stg_income (must be one row per loan after deduplication)'
  UNION ALL
  SELECT 'uniqueness.loan_age_loan_snapshot', 'critical',
         1.0 * (SELECT COUNT(*) FROM (SELECT loan_key, snapshot_date FROM {{STG}}.stg_loan_age
                                      GROUP BY loan_key, snapshot_date HAVING COUNT(*) > 1) AS d),
         0.0, 'Duplicate (loan_key, snapshot_date) in stg_loan_age'
  UNION ALL
  SELECT 'uniqueness.nps_response', 'critical',
         1.0 * (SELECT COUNT(*) FROM (SELECT response_key FROM {{STG}}.stg_nps GROUP BY response_key HAVING COUNT(*) > 1) AS d),
         0.0, 'Duplicate response_key in stg_nps (a loan may answer several times, a submission id may not repeat)'
)
SELECT check_name, severity, observed, threshold, (observed <= threshold) AS passed, description FROM checks;
