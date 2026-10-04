-- age_band as at each snapshot, income band, days_past_due, risk_category.

-- sql/02_features/loan_snapshot_features.sql
--
-- Feature layer: one row per loan per snapshot (grain of stg_credit_snapshots).
-- Features derived here:
--   age_band                 from stg_loan_age (age is calculated as at EACH snapshot date upstream,
--                            and the date of birth is discarded there)
--   avg_monthly_income_band  Received / Duration, banded as in the brief
--   days_past_due            reported days, forced to 0 when there is no arrears
--   risk_category            rule based (see the CASE below), with risk_rule naming the rule that fired
--
-- {{STG}} and {{PARTITION}} are filled in by scripts/feature_engineering.py.
-- Source values are never overwritten: days_past_due_reported keeps the original.

CREATE OR REPLACE TABLE {{STG}}.int_loan_snapshot_features {{PARTITION}} AS
WITH base AS (
  SELECT
    c.loan_key,
    c.snapshot_date,
    c.portfolio_scope,
    c.account_status_l1,
    c.account_status_l2,
    c.balance,
    c.arrears,
    c.total_paid,
    c.total_due_today,
    c.days_past_due AS days_past_due_reported,
    -- days_past_due: the brief says 0 when there is no arrears. The reported figure is used otherwise
    -- (the due date itself is not in the data, only a future NEXT_INVOICE_DATE).
    CASE WHEN COALESCE(c.arrears, 0) <= 0 THEN 0
         ELSE GREATEST(COALESCE(c.days_past_due, 0), 0) END AS days_past_due,
    -- Payment history signal: cumulative paid versus cumulative expected.
    c.total_paid / NULLIF(c.total_due_today, 0) AS payment_coverage,
    c.dq_arrears_zero_days,
    c.dq_days_zero_arrears,
    c.dq_negative_amount,
    c.dq_payment_after_snapshot
  FROM {{STG}}.stg_credit_snapshots AS c
),

history AS (
  -- Payment history from EARLIER snapshots only (never the current or later ones), so no leakage.
  SELECT
    b.*,
    MAX(b.days_past_due) OVER (
      PARTITION BY b.loan_key ORDER BY b.snapshot_date
      ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS max_dpd_prior,
    SUM(CASE WHEN b.days_past_due > 0 THEN 1 ELSE 0 END) OVER (
      PARTITION BY b.loan_key ORDER BY b.snapshot_date
      ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS prior_snapshots_in_arrears,
    LAG(b.account_status_l2) OVER (PARTITION BY b.loan_key ORDER BY b.snapshot_date) AS prev_status_l2
  FROM base AS b
),

enriched AS (
  SELECT
    h.*,
    COALESCE(a.age_band, 'Unknown') AS age_band,
    a.age_years,
    i.avg_monthly_income,
    i.avg_monthly_income_sum_all,
    CASE
      WHEN i.avg_monthly_income IS NULL THEN 'Unknown'
      WHEN i.avg_monthly_income <   5000 THEN 'Below 5,000'
      WHEN i.avg_monthly_income <  10000 THEN '5,000-9,999'
      WHEN i.avg_monthly_income <  20000 THEN '10,000-19,999'
      WHEN i.avg_monthly_income <  30000 THEN '20,000-29,999'
      WHEN i.avg_monthly_income <  50000 THEN '30,000-49,999'
      WHEN i.avg_monthly_income < 100000 THEN '50,000-99,999'
      WHEN i.avg_monthly_income < 150000 THEN '100,000-149,999'
      ELSE '150,000+'
    END AS avg_monthly_income_band,
    -- The brief's literal "sum all income columns" version, kept for transparency only.
    CASE
      WHEN i.avg_monthly_income_sum_all IS NULL THEN 'Unknown'
      WHEN i.avg_monthly_income_sum_all <   5000 THEN 'Below 5,000'
      WHEN i.avg_monthly_income_sum_all <  10000 THEN '5,000-9,999'
      WHEN i.avg_monthly_income_sum_all <  20000 THEN '10,000-19,999'
      WHEN i.avg_monthly_income_sum_all <  30000 THEN '20,000-29,999'
      WHEN i.avg_monthly_income_sum_all <  50000 THEN '30,000-49,999'
      WHEN i.avg_monthly_income_sum_all < 100000 THEN '50,000-99,999'
      WHEN i.avg_monthly_income_sum_all < 150000 THEN '100,000-149,999'
      ELSE '150,000+'
    END AS avg_monthly_income_band_brief_sum,
    CASE
      WHEN h.days_past_due = 0 THEN '0'
      WHEN h.days_past_due <= 7 THEN '1-7'
      WHEN h.days_past_due <= 30 THEN '8-30'
      WHEN h.days_past_due <= 60 THEN '31-60'
      WHEN h.days_past_due <= 90 THEN '61-90'
      ELSE '91+'
    END AS dpd_bucket,
    -- Live = financed and not yet closed (paid off or returned). Used as the denominator for delinquency.
    CASE WHEN h.portfolio_scope = 'financed'
          AND h.account_status_l2 NOT IN ('Paid Off', 'Return') THEN TRUE ELSE FALSE END AS is_live,
    -- Risk rule: the FIRST matching rule wins.
    CASE
      WHEN h.portfolio_scope <> 'financed' THEN 'R0_not_financed'
      WHEN h.account_status_l1 = 'Write Off' OR h.days_past_due >= 61
           OR h.account_status_l2 = 'Return' THEN 'R1_write_off_return_or_dpd_61plus'
      WHEN h.account_status_l2 IN ('FPD', 'FMD') OR h.account_status_l1 LIKE 'First%Default%'
           OR h.days_past_due >= 31 THEN 'R2_first_default_or_dpd_31_60'
      WHEN h.days_past_due >= 8 THEN 'R3_dpd_8_30'
      WHEN h.account_status_l2 = 'Paid Off' THEN 'R4_paid_off'
      WHEN COALESCE(h.max_dpd_prior, 0) >= 8 OR COALESCE(h.payment_coverage, 1) < 0.8 THEN 'R5_history_or_low_coverage'
      ELSE 'R6_current_or_minor_lateness'
    END AS risk_rule
  FROM history AS h
  LEFT JOIN {{STG}}.stg_loan_age AS a
    ON a.loan_key = h.loan_key AND a.snapshot_date = h.snapshot_date
  LEFT JOIN {{STG}}.stg_income AS i
    ON i.loan_key = h.loan_key
)

SELECT
  loan_key,
  snapshot_date,
  portfolio_scope,
  is_live,
  account_status_l1,
  account_status_l2,
  age_band,
  age_years,
  avg_monthly_income,
  avg_monthly_income_band,
  avg_monthly_income_band_brief_sum,
  days_past_due,
  days_past_due_reported,
  dpd_bucket,
  arrears,
  balance,
  total_paid,
  total_due_today,
  payment_coverage,
  max_dpd_prior,
  COALESCE(prior_snapshots_in_arrears, 0) AS prior_snapshots_in_arrears,
  prev_status_l2,
  risk_rule,
  CASE risk_rule
    WHEN 'R0_not_financed' THEN 'Not rated'
    WHEN 'R1_write_off_return_or_dpd_61plus' THEN 'Critical'
    WHEN 'R2_first_default_or_dpd_31_60' THEN 'High'
    WHEN 'R3_dpd_8_30' THEN 'Medium'
    WHEN 'R4_paid_off' THEN 'Low'
    WHEN 'R5_history_or_low_coverage' THEN 'Medium'
    ELSE 'Low'
  END AS risk_category,
  dq_arrears_zero_days,
  dq_days_zero_arrears,
  dq_negative_amount,
  dq_payment_after_snapshot
FROM enriched;