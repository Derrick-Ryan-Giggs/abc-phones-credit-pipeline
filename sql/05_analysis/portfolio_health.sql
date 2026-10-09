-- sql/05_analysis/portfolio_health.sql
--
-- Question 3A for analysts: the five portfolio health metrics per snapshot, with the change since the previous
-- snapshot and since the first one, in percentage points. A read-only query: run it in the BigQuery console or
-- point Looker Studio at it. {{MARTS}} is the abc_marts dataset.
--
-- Reading the *_vs_previous columns: for delinquency, loss and first payment default a NEGATIVE change is good;
-- for collection rate and retention a POSITIVE change is good.

SELECT
  snapshot_date,
  financed_loans,
  ROUND(100 * delinquency_rate_7plus, 1) AS delinquent_pct,
  ROUND(100 * (delinquency_rate_7plus - LAG(delinquency_rate_7plus) OVER w), 1) AS delinquent_vs_previous,
  ROUND(100 * par30_rate, 1)             AS seriously_delinquent_pct,
  ROUND(100 * (par30_rate - LAG(par30_rate) OVER w), 1) AS seriously_delinquent_vs_previous,
  ROUND(100 * loss_rate_count, 1)        AS loss_pct,
  ROUND(100 * (loss_rate_count - LAG(loss_rate_count) OVER w), 1) AS loss_vs_previous,
  ROUND(100 * collection_rate, 1)        AS collection_pct,
  ROUND(100 * (collection_rate - LAG(collection_rate) OVER w), 1) AS collection_vs_previous,
  ROUND(100 * fpd_rate, 1)               AS first_payment_default_pct,
  ROUND(100 * (fpd_rate - LAG(fpd_rate) OVER w), 1) AS first_payment_default_vs_previous,
  ROUND(100 * retention_rate, 1)         AS retention_pct,
  ROUND(100 * (retention_rate - LAG(retention_rate) OVER w), 1) AS retention_vs_previous,
  ROUND(100 * (delinquency_rate_7plus - FIRST_VALUE(delinquency_rate_7plus) OVER (ORDER BY snapshot_date
        ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING)), 1) AS delinquent_vs_first,
  ROUND(100 * (loss_rate_count - FIRST_VALUE(loss_rate_count) OVER (ORDER BY snapshot_date
        ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING)), 1) AS loss_vs_first
FROM {{MARTS}}.mart_portfolio_metrics
WINDOW w AS (ORDER BY snapshot_date)
ORDER BY snapshot_date;
