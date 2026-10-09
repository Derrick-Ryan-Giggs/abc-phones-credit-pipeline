-- sql/05_analysis/nps_vs_credit.sql
--
-- Question 3B for analysts: customer satisfaction by how late the customer was when they answered the survey.
-- A read-only query. {{MARTS}} is the abc_marts dataset.
--
-- Sample: the latest scored response per loan, financed loans only, with the loan's credit state at the latest
-- snapshot ON OR BEFORE the response date (no look-ahead). There is no credit score in the source data, so days
-- past due is the credit measure.
-- NPS = % of answers 9-10 minus % of answers 0-6. average_score is the plain 0-10 average.

SELECT
  dpd_bucket AS days_past_due_when_answered,
  COUNT(*)   AS responses,
  ROUND(AVG(nps_score), 2) AS average_score,
  ROUND(100 * AVG(CASE WHEN nps_score >= 9 THEN 1.0 ELSE 0.0 END), 1) AS promoters_pct,
  ROUND(100 * AVG(CASE WHEN nps_score <= 6 THEN 1.0 ELSE 0.0 END), 1) AS detractors_pct,
  ROUND(100 * (AVG(CASE WHEN nps_score >= 9 THEN 1.0 ELSE 0.0 END) - AVG(CASE WHEN nps_score <= 6 THEN 1.0 ELSE 0.0 END)), 1) AS nps
FROM {{MARTS}}.mart_nps_credit
WHERE is_latest_response
  AND nps_score IS NOT NULL
  AND portfolio_scope = 'financed'
GROUP BY dpd_bucket
ORDER BY CASE dpd_bucket WHEN '0' THEN 1 WHEN '1-7' THEN 2 WHEN '8-30' THEN 3 WHEN '31-60' THEN 4 WHEN '61-90' THEN 5 ELSE 6 END;
