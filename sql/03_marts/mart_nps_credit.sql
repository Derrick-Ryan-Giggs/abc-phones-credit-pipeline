-- sql/03_marts/mart_nps_credit.sql
--
-- Question 3B. One row per NPS response with the loan's credit state AT the matched snapshot (the latest snapshot
-- on or before the response date, so no future information) and at the latest snapshot.
-- Free-text answers stay in staging and are not exposed here.
-- No credit score exists in the source data, so risk_category and days past due are the credit proxy.

CREATE OR REPLACE TABLE {{MARTS}}.mart_nps_credit AS
WITH latest AS (
  SELECT
    loan_key,
    risk_category    AS risk_category_latest,
    account_status_l2 AS status_l2_latest,
    dpd_bucket       AS dpd_bucket_latest
  FROM {{STG}}.int_loan_snapshot_features
  WHERE snapshot_date = (SELECT MAX(snapshot_date) FROM {{STG}}.int_loan_snapshot_features)
)
SELECT
  n.response_key,
  n.loan_key,
  n.submitted_date,
  n.matched_snapshot_date,
  n.nps_score,
  n.nps_category,
  n.is_latest_response,
  n.quality_happy,
  n.service_happy,
  n.payment_delay_experienced,
  n.assistance_difficulty,
  n.battery_issue,
  n.app_usage,
  n.preferred_channel,
  n.phone_lock_experienced,
  f.portfolio_scope,
  f.risk_category,
  f.risk_rule,
  f.account_status_l2,
  f.dpd_bucket,
  f.days_past_due,
  f.payment_coverage,
  f.age_band,
  f.avg_monthly_income_band,
  l.risk_category_latest,
  l.status_l2_latest,
  l.dpd_bucket_latest
FROM {{STG}}.stg_nps AS n
LEFT JOIN {{STG}}.int_loan_snapshot_features AS f
  ON f.loan_key = n.loan_key AND f.snapshot_date = n.matched_snapshot_date
LEFT JOIN latest AS l
  ON l.loan_key = n.loan_key;
