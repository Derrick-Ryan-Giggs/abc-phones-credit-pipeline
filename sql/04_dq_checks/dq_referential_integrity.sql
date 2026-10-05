-- Data quality check: referential_integrity. Returns rows only when the check fails.

-- sql/04_dq_checks/dq_referential_integrity.sql
-- CHECK 3: REFERENTIAL INTEGRITY ("do all keys exist where they should?")

WITH latest AS (SELECT MAX(snapshot_date) AS d FROM {{STG}}.stg_credit_snapshots),
checks AS (
  SELECT 'integrity.credit_loans_missing_from_sales' AS check_name, 'critical' AS severity,
         1.0 * (SELECT COUNT(DISTINCT c.loan_key) FROM {{STG}}.stg_credit_snapshots AS c
                LEFT JOIN {{STG}}.stg_sales AS s ON s.loan_key = c.loan_key WHERE s.loan_key IS NULL) AS observed,
         0.0 AS threshold,
         'Loans in the credit snapshots with no row in stg_sales' AS description
  UNION ALL
  SELECT 'integrity.nps_loans_missing_from_credit', 'critical',
         1.0 * (SELECT COUNT(DISTINCT n.loan_key) FROM {{STG}}.stg_nps AS n
                LEFT JOIN (SELECT DISTINCT loan_key FROM {{STG}}.stg_credit_snapshots) AS c ON c.loan_key = n.loan_key
                WHERE n.loan_key IS NOT NULL AND c.loan_key IS NULL),
         0.0, 'NPS responses whose loan is not in the credit snapshots'
  UNION ALL
  SELECT 'integrity.loan_age_rows_without_credit_row', 'critical',
         1.0 * (SELECT COUNT(*) FROM {{STG}}.stg_loan_age AS a
                LEFT JOIN {{STG}}.stg_credit_snapshots AS c ON c.loan_key = a.loan_key AND c.snapshot_date = a.snapshot_date
                WHERE c.loan_key IS NULL),
         0.0, 'stg_loan_age rows with no matching credit snapshot row'
  UNION ALL
  SELECT 'integrity.income_loans_missing_from_credit', 'warning',
         1.0 * (SELECT COUNT(*) FROM {{STG}}.stg_income AS i
                LEFT JOIN (SELECT DISTINCT loan_key FROM {{STG}}.stg_credit_snapshots) AS c ON c.loan_key = i.loan_key
                WHERE c.loan_key IS NULL),
         0.0, 'Income rows whose loan is not in the credit snapshots'
  UNION ALL
  SELECT 'integrity.share_of_sales_without_credit', 'warning',
         1.0 * (SELECT COUNT(*) FROM {{STG}}.stg_sales AS s
                LEFT JOIN (SELECT DISTINCT loan_key FROM {{STG}}.stg_credit_snapshots) AS c ON c.loan_key = s.loan_key
                WHERE c.loan_key IS NULL) / (SELECT COUNT(*) FROM {{STG}}.stg_sales),
         0.001, 'Share of sales with no credit record (a few are expected: sales not yet in any snapshot)'
  UNION ALL
  SELECT 'integrity.share_of_latest_loans_without_age', 'warning',
         1.0 * (SELECT SUM(CASE WHEN a.age_band = 'Unknown' THEN 1 ELSE 0 END) FROM {{STG}}.stg_loan_age AS a
                WHERE a.snapshot_date = (SELECT d FROM latest)) / (SELECT COUNT(*) FROM {{STG}}.stg_loan_age WHERE snapshot_date = (SELECT d FROM latest)),
         0.60, 'Share of latest-snapshot loans with no age band. Demographic coverage is about 54% today; alert if it falls below 40%'
  UNION ALL
  SELECT 'integrity.share_of_latest_loans_without_income', 'warning',
         1.0 * (SELECT COUNT(*) FROM {{STG}}.stg_credit_snapshots AS c
                LEFT JOIN {{STG}}.stg_income AS i ON i.loan_key = c.loan_key
                WHERE c.snapshot_date = (SELECT d FROM latest) AND i.loan_key IS NULL)
              / (SELECT COUNT(*) FROM {{STG}}.stg_credit_snapshots WHERE snapshot_date = (SELECT d FROM latest)),
         0.60, 'Share of latest-snapshot loans with no income row. Coverage is about 51% today; alert if it falls below 40%'
)
SELECT check_name, severity, observed, threshold, (observed <= threshold) AS passed, description FROM checks;