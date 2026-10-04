#!/usr/bin/env python3
"""feature_engineering.py

Run the feature SQL (sql/02_features/*.sql) in BigQuery and summarise the result.

Features built in sql/02_features/loan_snapshot_features.sql:
    age_band                 as at each snapshot date (derived upstream in data_cleaning.py, DOB then discarded)
    avg_monthly_income_band  Received / Duration, banded as in the brief
    days_past_due            reported days, 0 when there is no arrears
    risk_category            rule based; risk_rule records which rule fired

Run from the project root:
    uv run python scripts/feature_engineering.py --dry-run   # validate the SQL, no cost, nothing created
    uv run python scripts/feature_engineering.py             # build abc_staging.int_loan_snapshot_features

The SQL files use two placeholders that are filled in here: {{STG}} (the staging dataset) and
{{PARTITION}} (partition and cluster clause). Output: a BigQuery table and outputs/feature_summary.csv.
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SQL_DIR = ROOT / "sql" / "02_features"
LOG = logging.getLogger("feature_engineering")

SUMMARY_SQL = """
SELECT 'risk_category' AS feature, snapshot_date, risk_category AS value, COUNT(*) AS loans
FROM {{STG}}.int_loan_snapshot_features GROUP BY 1, 2, 3
UNION ALL
SELECT 'age_band', snapshot_date, age_band, COUNT(*)
FROM {{STG}}.int_loan_snapshot_features GROUP BY 1, 2, 3
UNION ALL
SELECT 'avg_monthly_income_band', snapshot_date, avg_monthly_income_band, COUNT(*)
FROM {{STG}}.int_loan_snapshot_features GROUP BY 1, 2, 3
UNION ALL
SELECT 'dpd_bucket', snapshot_date, dpd_bucket, COUNT(*)
FROM {{STG}}.int_loan_snapshot_features GROUP BY 1, 2, 3
ORDER BY 1, 2, 3
"""


def render(sql: str, cfg: dict) -> str:
    """Fill in the dataset and partition placeholders."""
    stg = f"`{cfg['gcp']['project_id']}.{cfg['bigquery']['dataset_staging']}`"
    return sql.replace("{{STG}}", stg).replace("{{PARTITION}}", "PARTITION BY snapshot_date CLUSTER BY loan_key")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="validate the SQL and estimate cost without creating anything")
    ap.add_argument("--config", type=Path, default=ROOT / "config" / "settings.yaml")
    ap.add_argument("--out-dir", type=Path, default=ROOT / "outputs")
    ap.add_argument("--log-dir", type=Path, default=ROOT / "logs")
    args = ap.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    args.log_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.FileHandler(args.log_dir / "feature_engineering.log"), logging.StreamHandler(sys.stderr)],
    )
    cfg = yaml.safe_load(args.config.read_text())

    files = sorted(SQL_DIR.glob("*.sql"))
    if not files:
        LOG.error("No SQL files found in %s", SQL_DIR)
        return 1

    from google.cloud import bigquery

    client = bigquery.Client(project=cfg["gcp"]["project_id"], location=cfg["bigquery"]["location"])
    for f in files:
        job = client.query(render(f.read_text(), cfg), job_config=bigquery.QueryJobConfig(dry_run=args.dry_run, use_query_cache=False))
        if args.dry_run:
            LOG.info("%s is valid. It would process about %.1f MB.", f.name, (job.total_bytes_processed or 0) / 1e6)
        else:
            job.result()
            LOG.info("%s finished.", f.name)

    if args.dry_run:
        return 0

    summary = client.query(render(SUMMARY_SQL, cfg)).to_dataframe()
    summary.to_csv(args.out_dir / "feature_summary.csv", index=False)
    risk = summary[summary["feature"] == "risk_category"].pivot(index="snapshot_date", columns="value", values="loans").fillna(0).astype(int)
    print("\n## Loans by risk_category and snapshot (all scopes)\n")
    print(risk.to_string())
    print(f"\nFull summary (risk, age band, income band, dpd bucket) saved to {args.out_dir / 'feature_summary.csv'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())