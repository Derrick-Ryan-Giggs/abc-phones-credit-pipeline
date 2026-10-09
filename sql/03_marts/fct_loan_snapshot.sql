-- sql/03_marts/fct_loan_snapshot.sql
--
-- Analytics-ready fact table. Grain: one row per loan per snapshot (financed AND other scopes; filter on is_financed).
-- Adds sales attributes and the boolean flags every portfolio metric is built from, so metric definitions
-- live in exactly one place.
--
-- Definitions (financed loans only):
--   is_live              financed and not Paid Off or Return
--   is_loss_91plus       live and (Write Off status or 91+ days past due). Every Write Off row is 91+ days,
--                        so this also catches FPD/FMD loans that have run past 90 days.
--   is_performing        live and not is_loss_91plus (the collectable book)
--   is_delinquent_7plus  performing and 8-90 days past due
--   is_delinquent_30plus performing and 31-90 days past due
-- Return dates are only exposed when they are on or before the snapshot date (point-in-time safe).

CREATE OR REPLACE TABLE {{MARTS}}.fct_loan_snapshot {{PARTITION}} AS
WITH joined AS (
  SELECT
    f.*,
    MIN(f.snapshot_date) OVER (PARTITION BY f.loan_key) AS loan_first_snapshot_date,
    s.sale_date,
    s.sale_type,
    s.loan_price,
    s.cash_price,
    s.loan_term_months,
    s.client_model,
    s.business_model,
    s.product_name,
    s.return_date
  FROM {{STG}}.int_loan_snapshot_features AS f
  LEFT JOIN {{STG}}.stg_sales AS s
    ON s.loan_key = f.loan_key
),
flags AS (
  SELECT
    j.*,
    (j.portfolio_scope = 'financed') AS is_financed,
    (j.is_live AND (j.account_status_l1 = 'Write Off' OR j.days_past_due >= 91)) AS is_loss_91plus
  FROM joined AS j
)
SELECT
  loan_key,
  snapshot_date,
  portfolio_scope,
  is_financed,
  is_live,
  is_loss_91plus,
  (is_live AND NOT is_loss_91plus) AS is_performing,
  (is_live AND NOT is_loss_91plus AND days_past_due BETWEEN 8 AND 90) AS is_delinquent_7plus,
  (is_live AND NOT is_loss_91plus AND days_past_due BETWEEN 31 AND 90) AS is_delinquent_30plus,
  (is_financed AND account_status_l2 = 'Paid Off') AS is_paid_off,
  (is_financed AND account_status_l2 = 'Return') AS is_returned,
  (is_financed AND account_status_l2 = 'FPD') AS is_fpd,
  (snapshot_date = loan_first_snapshot_date
     AND snapshot_date > (SELECT MIN(snapshot_date) FROM {{STG}}.int_loan_snapshot_features)) AS is_new_loan,
  account_status_l1,
  account_status_l2,
  prev_status_l2,
  risk_category,
  risk_rule,
  age_band,
  age_years,
  avg_monthly_income,
  avg_monthly_income_band,
  days_past_due,
  dpd_bucket,
  arrears,
  balance,
  total_paid,
  total_due_today,
  payment_coverage,
  max_dpd_prior,
  prior_snapshots_in_arrears,
  loan_first_snapshot_date,
  sale_date,
  sale_type,
  loan_price,
  cash_price,
  loan_term_months,
  client_model,
  business_model,
  product_name,
  CASE WHEN return_date <= snapshot_date THEN return_date END AS return_date_as_of_snapshot,
  dq_arrears_zero_days,
  dq_days_zero_arrears,
  dq_negative_amount,
  dq_payment_after_snapshot
FROM flags;
