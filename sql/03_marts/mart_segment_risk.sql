-- Risk behaviour by age band and income band.

-- sql/03_marts/mart_segment_risk.sql
--
-- Question 3A, segment view. One row per snapshot x segment type x segment, financed loans only.
-- Segment types: age_band and avg_monthly_income_band. 'Unknown' means no demographic data for the loan.
--
-- Two benchmarks are provided because demographic coverage is partial (about 51-54% of December loans):
--   known_avg_*     average across loans that HAVE a value for this segment type (like for like)
--   portfolio_*     average across all financed loans
-- delinquency_vs_known_avg is the segment rate divided by the like-for-like average (1.0 = same as average).

CREATE OR REPLACE TABLE {{MARTS}}.mart_segment_risk AS
WITH seg AS (
  SELECT snapshot_date, 'age_band' AS segment_type, age_band AS segment,
         is_financed, is_performing, is_delinquent_7plus, is_delinquent_30plus, is_loss_91plus,
         total_paid, total_due_today
  FROM {{MARTS}}.fct_loan_snapshot
  WHERE is_financed
  UNION ALL
  SELECT snapshot_date, 'avg_monthly_income_band', avg_monthly_income_band,
         is_financed, is_performing, is_delinquent_7plus, is_delinquent_30plus, is_loss_91plus,
         total_paid, total_due_today
  FROM {{MARTS}}.fct_loan_snapshot
  WHERE is_financed
),
by_segment AS (
  SELECT
    snapshot_date, segment_type, segment,
    COUNT(*)                                                       AS financed_loans,
    SUM(CASE WHEN is_performing THEN 1 ELSE 0 END)                 AS performing_loans,
    SUM(CASE WHEN is_delinquent_7plus THEN 1 ELSE 0 END)           AS delinquent_7plus_loans,
    SUM(CASE WHEN is_delinquent_30plus THEN 1 ELSE 0 END)          AS delinquent_30plus_loans,
    SUM(CASE WHEN is_loss_91plus THEN 1 ELSE 0 END)                AS loss_loans,
    SUM(CASE WHEN is_performing THEN total_paid ELSE 0 END)        AS paid_performing,
    SUM(CASE WHEN is_performing THEN total_due_today ELSE 0 END)   AS due_performing
  FROM seg
  GROUP BY snapshot_date, segment_type, segment
),
with_benchmarks AS (
  SELECT
    b.*,
    SUM(delinquent_7plus_loans) OVER (PARTITION BY snapshot_date, segment_type)
      / NULLIF(SUM(performing_loans) OVER (PARTITION BY snapshot_date, segment_type), 0) AS portfolio_delinquency_rate,
    SUM(loss_loans) OVER (PARTITION BY snapshot_date, segment_type)
      / NULLIF(SUM(financed_loans) OVER (PARTITION BY snapshot_date, segment_type), 0) AS portfolio_loss_rate,
    SUM(CASE WHEN segment <> 'Unknown' THEN delinquent_7plus_loans ELSE 0 END) OVER (PARTITION BY snapshot_date, segment_type)
      / NULLIF(SUM(CASE WHEN segment <> 'Unknown' THEN performing_loans ELSE 0 END) OVER (PARTITION BY snapshot_date, segment_type), 0) AS known_avg_delinquency_rate,
    SUM(CASE WHEN segment <> 'Unknown' THEN loss_loans ELSE 0 END) OVER (PARTITION BY snapshot_date, segment_type)
      / NULLIF(SUM(CASE WHEN segment <> 'Unknown' THEN financed_loans ELSE 0 END) OVER (PARTITION BY snapshot_date, segment_type), 0) AS known_avg_loss_rate
  FROM by_segment AS b
)
SELECT
  snapshot_date,
  segment_type,
  segment,
  financed_loans,
  performing_loans,
  delinquent_7plus_loans,
  delinquent_30plus_loans,
  loss_loans,
  ROUND(delinquent_7plus_loans / NULLIF(performing_loans, 0), 4)   AS delinquency_rate_7plus,
  ROUND(delinquent_30plus_loans / NULLIF(performing_loans, 0), 4)  AS par30_rate,
  ROUND(loss_loans / NULLIF(financed_loans, 0), 4)                 AS loss_rate_count,
  ROUND(paid_performing / NULLIF(due_performing, 0), 4)            AS collection_rate,
  ROUND(known_avg_delinquency_rate, 4)                             AS known_avg_delinquency_rate,
  ROUND(portfolio_delinquency_rate, 4)                             AS portfolio_delinquency_rate,
  ROUND(known_avg_loss_rate, 4)                                    AS known_avg_loss_rate,
  ROUND(portfolio_loss_rate, 4)                                    AS portfolio_loss_rate,
  ROUND((delinquent_7plus_loans / NULLIF(performing_loans, 0)) / NULLIF(known_avg_delinquency_rate, 0), 3) AS delinquency_vs_known_avg,
  ROUND((loss_loans / NULLIF(financed_loans, 0)) / NULLIF(known_avg_loss_rate, 0), 3)                      AS loss_vs_known_avg,
  (performing_loans < 30)                                          AS small_sample
FROM with_benchmarks
ORDER BY snapshot_date, segment_type, segment;