-- Data quality check: range_checks. Returns rows only when the check fails.

-- sql/04_dq_checks/dq_range_checks.sql
-- CHECK 4: RANGE AND LOGIC CHECKS ("are values plausible?")
-- Known source defects are severity 'warning': they are flagged in staging (dq_* columns), never overwritten,
-- and kept out of the features. The check still reports them so they are caught before analysts see them.

WITH checks AS (
  SELECT 'range.age_outside_18_120' AS check_name, 'critical' AS severity,
         1.0 * (SELECT COUNT(*) FROM {{STG}}.stg_loan_age WHERE age_years IS NOT NULL AND (age_years < 18 OR age_years > 120)) AS observed,
         0.0 AS threshold,
         'Derived ages outside 18-120' AS description
  UNION ALL
  SELECT 'range.negative_days_past_due', 'critical',
         1.0 * (SELECT COUNT(*) FROM {{STG}}.stg_credit_snapshots WHERE days_past_due < 0),
         0.0, 'Negative days_past_due'
  UNION ALL
  SELECT 'range.nps_score_outside_0_10', 'critical',
         1.0 * (SELECT COUNT(*) FROM {{STG}}.stg_nps WHERE nps_score IS NOT NULL AND (nps_score < 0 OR nps_score > 10)),
         0.0, 'NPS scores outside the 0-10 scale'
  UNION ALL
  SELECT 'range.payment_date_after_snapshot_share', 'warning',
         1.0 * (SELECT SUM(CASE WHEN dq_payment_after_snapshot THEN 1 ELSE 0 END) FROM {{STG}}.stg_credit_snapshots)
             / (SELECT COUNT(*) FROM {{STG}}.stg_credit_snapshots),
         0.0, 'Share of rows where MAX_PAYMENT_DATE is later than the snapshot date. The extract stamps this field at extract time, so older snapshots contain future information. Flagged, and excluded from features and ML'
  UNION ALL
  SELECT 'range.negative_amount_share', 'warning',
         1.0 * (SELECT SUM(CASE WHEN dq_negative_amount THEN 1 ELSE 0 END) FROM {{STG}}.stg_credit_snapshots)
             / (SELECT COUNT(*) FROM {{STG}}.stg_credit_snapshots),
         0.005, 'Share of rows with a negative balance, closing balance, total paid, deposit or initial payment'
  UNION ALL
  SELECT 'range.return_before_sale_share', 'warning',
         1.0 * (SELECT SUM(CASE WHEN dq_return_before_sale THEN 1 ELSE 0 END) FROM {{STG}}.stg_sales)
             / (SELECT COUNT(*) FROM {{STG}}.stg_sales),
         0.001, 'Share of sales whose return date is before the sale date'
  UNION ALL
  SELECT 'range.negative_monthly_income', 'warning',
         1.0 * (SELECT COUNT(*) FROM {{STG}}.stg_income WHERE avg_monthly_income < 0),
         0.0, 'Loans with a negative average monthly income'
)
SELECT check_name, severity, observed, threshold, (observed <= threshold) AS passed, description FROM checks;