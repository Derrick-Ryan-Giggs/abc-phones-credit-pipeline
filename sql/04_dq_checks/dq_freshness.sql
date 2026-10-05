-- Data quality check: freshness. Returns rows only when the check fails.

-- sql/04_dq_checks/dq_freshness.sql
-- CHECK 1: FRESHNESS AND COMPLETENESS OF SNAPSHOTS ("is the data arriving on schedule?")
--
-- Every check returns the same columns: check_name, severity, observed, threshold, passed, description.
-- A check passes when observed <= threshold, so "observed" is always a count or share of BAD things.
-- {{EXPECTED_DATES}} comes from config/settings.yaml (snapshots.expected_dates).

WITH expected AS ({{EXPECTED_DATES}}),
present AS (SELECT DISTINCT snapshot_date AS d FROM {{STG}}.stg_credit_snapshots),
checks AS (
  SELECT 'freshness.expected_snapshots_missing' AS check_name, 'critical' AS severity,
         1.0 * (SELECT COUNT(*) FROM expected AS e LEFT JOIN present AS p ON p.d = e.d WHERE p.d IS NULL) AS observed,
         0.0 AS threshold,
         'Expected snapshot dates that have no rows in stg_credit_snapshots' AS description
  UNION ALL
  SELECT 'freshness.unexpected_snapshots', 'warning',
         1.0 * (SELECT COUNT(*) FROM present AS p LEFT JOIN expected AS e ON e.d = p.d WHERE e.d IS NULL),
         0.0,
         'Snapshot dates loaded that are not in the expected list'
  UNION ALL
  SELECT 'freshness.latest_snapshot_is_the_expected_latest', 'critical',
         1.0 * CASE WHEN (SELECT MAX(d) FROM present) = (SELECT MAX(d) FROM expected) THEN 0 ELSE 1 END,
         0.0,
         'The newest loaded snapshot date equals the newest expected date'
  UNION ALL
  SELECT 'freshness.snapshot_row_count_dropped', 'warning',
         1.0 * (SELECT COUNT(*) FROM (
                  SELECT n, LAG(n) OVER (ORDER BY snapshot_date) AS prev_n
                  FROM (SELECT snapshot_date, COUNT(*) AS n FROM {{STG}}.stg_credit_snapshots GROUP BY snapshot_date) AS c
                ) AS t WHERE prev_n IS NOT NULL AND n < prev_n),
         0.0,
         'Snapshots with fewer rows than the previous one (loans never leave the extracts, so the book should only grow)'
)
SELECT check_name, severity, observed, threshold, (observed <= threshold) AS passed, description FROM checks;