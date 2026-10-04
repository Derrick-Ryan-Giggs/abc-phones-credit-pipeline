-- Portfolio health metrics per snapshot.

-- sql/03_marts/mart_portfolio_metrics.sql
--
-- Question 3A. One row per snapshot, financed loans only.
--
--   delinquency_rate_7plus   loans 8-90 days past due / performing loans
--   par30_rate               loans 31-90 days past due / performing loans
--   loss_rate_count          loans 91+ days past due (incl. Write Off) / all financed loans
--   loss_rate_balance        balance of those loans / balance of all live loans
--   collection_rate          total paid / total due to date, performing loans
--   fpd_rate                 First Payment Default loans / financed loans
--   retention_rate           of loans healthy at the previous snapshot (Active, Inactive, PAR 7), the share
--                            not Returned and not 91+ days past due now. Loans never drop out of the extracts,
--                            so retention is measured as survival, not as presence.
-- Written-off loans leave the performing book, so they are counted under loss and not under delinquency.

CREATE OR REPLACE TABLE {{MARTS}}.mart_portfolio_metrics AS
SELECT
  snapshot_date,
  SUM(CASE WHEN is_financed THEN 1 ELSE 0 END)                                   AS financed_loans,
  SUM(CASE WHEN is_new_loan AND is_financed THEN 1 ELSE 0 END)                   AS new_financed_loans,
  SUM(CASE WHEN is_live THEN 1 ELSE 0 END)                                       AS live_loans,
  SUM(CASE WHEN is_performing THEN 1 ELSE 0 END)                                 AS performing_loans,
  SUM(CASE WHEN is_delinquent_7plus THEN 1 ELSE 0 END)                           AS delinquent_7plus_loans,
  SUM(CASE WHEN is_delinquent_30plus THEN 1 ELSE 0 END)                          AS delinquent_30plus_loans,
  SUM(CASE WHEN is_loss_91plus THEN 1 ELSE 0 END)                                AS loss_loans,
  SUM(CASE WHEN is_returned THEN 1 ELSE 0 END)                                   AS returned_loans,
  SUM(CASE WHEN is_paid_off THEN 1 ELSE 0 END)                                   AS paid_off_loans,
  SUM(CASE WHEN is_fpd THEN 1 ELSE 0 END)                                        AS fpd_loans,
  ROUND(SUM(CASE WHEN is_delinquent_7plus THEN 1 ELSE 0 END)
        / NULLIF(SUM(CASE WHEN is_performing THEN 1 ELSE 0 END), 0), 4)          AS delinquency_rate_7plus,
  ROUND(SUM(CASE WHEN is_delinquent_30plus THEN 1 ELSE 0 END)
        / NULLIF(SUM(CASE WHEN is_performing THEN 1 ELSE 0 END), 0), 4)          AS par30_rate,
  ROUND(SUM(CASE WHEN is_loss_91plus THEN 1 ELSE 0 END)
        / NULLIF(SUM(CASE WHEN is_financed THEN 1 ELSE 0 END), 0), 4)            AS loss_rate_count,
  ROUND(SUM(CASE WHEN is_loss_91plus THEN balance ELSE 0 END)
        / NULLIF(SUM(CASE WHEN is_live THEN balance ELSE 0 END), 0), 4)          AS loss_rate_balance,
  ROUND(SUM(CASE WHEN is_performing THEN total_paid ELSE 0 END)
        / NULLIF(SUM(CASE WHEN is_performing THEN total_due_today ELSE 0 END), 0), 4) AS collection_rate,
  ROUND(SUM(CASE WHEN is_fpd THEN 1 ELSE 0 END)
        / NULLIF(SUM(CASE WHEN is_financed THEN 1 ELSE 0 END), 0), 4)            AS fpd_rate,
  SUM(CASE WHEN is_financed AND prev_status_l2 IN ('Active', 'Inactive', 'PAR 7') THEN 1 ELSE 0 END)
                                                                                 AS retention_cohort_loans,
  SUM(CASE WHEN is_financed AND prev_status_l2 IN ('Active', 'Inactive', 'PAR 7')
            AND NOT is_returned AND NOT is_loss_91plus THEN 1 ELSE 0 END)        AS retained_loans,
  ROUND(SUM(CASE WHEN is_financed AND prev_status_l2 IN ('Active', 'Inactive', 'PAR 7')
                  AND NOT is_returned AND NOT is_loss_91plus THEN 1 ELSE 0 END)
        / NULLIF(SUM(CASE WHEN is_financed AND prev_status_l2 IN ('Active', 'Inactive', 'PAR 7') THEN 1 ELSE 0 END), 0), 4)
                                                                                 AS retention_rate
FROM {{MARTS}}.fct_loan_snapshot
GROUP BY snapshot_date
ORDER BY snapshot_date;