#!/usr/bin/env python3
"""build_marts.py

Build the analysis tables ("marts") in BigQuery from the features table.

Runs every file in sql/03_marts/ in alphabetical order (fct_loan_snapshot first, because the other
metric tables read from it) and creates these tables in the abc_marts dataset:
    fct_loan_snapshot        one row per loan per snapshot, with the yes/no flags every metric is built from
    mart_portfolio_metrics   one row per snapshot: delinquency, loss, collection, first payment default, retention
    mart_segment_risk        the same metrics by age band and income band
    mart_nps_credit          each NPS response with the loan's credit status at that time

Run from the project root:
    uv run python scripts/build_marts.py --dry-run   # checks the SQL, creates no tables
    uv run python scripts/build_marts.py             # builds the tables and exports two CSV files

Outputs: outputs/portfolio_metrics.csv (required by the brief) and outputs/segment_risk.csv.
The SQL files use {{STG}}, {{MARTS}} and {{PARTITION}} placeholders that are filled in here.
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SQL_DIR = ROOT / "sql" / "03_marts"
LOG = logging.getLogger("build_marts")

SHOW_COLUMNS = ["snapshot_date", "financed_loans", "delinquency_rate_7plus", "par30_rate",
                "loss_rate_count", "collection_rate", "fpd_rate", "retention_rate"]


def render(sql: str, cfg: dict) -> str:
    """Fill in the dataset and partition placeholders."""
    project = cfg["gcp"]["project_id"]
    stg = f"`{project}.{cfg['bigquery']['dataset_staging']}`"
    marts = f"`{project}.{cfg['bigquery']['dataset_marts']}`"
    return (sql.replace("{{STG}}", stg).replace("{{MARTS}}", marts)
               .replace("{{PARTITION}}", "PARTITION BY snapshot_date CLUSTER BY loan_key"))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="validate the SQL without creating any tables")
    ap.add_argument("--config", type=Path, default=ROOT / "config" / "settings.yaml")
    ap.add_argument("--out-dir", type=Path, default=ROOT / "outputs")
    ap.add_argument("--log-dir", type=Path, default=ROOT / "logs")
    args = ap.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    args.log_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.FileHandler(args.log_dir / "build_marts.log"), logging.StreamHandler(sys.stderr)],
    )
    cfg = yaml.safe_load(args.config.read_text())

    files = sorted(SQL_DIR.glob("*.sql"))
    if not files:
        LOG.error("No SQL files found in %s", SQL_DIR)
        return 1

    from google.api_core.exceptions import NotFound
    from google.cloud import bigquery

    project, location = cfg["gcp"]["project_id"], cfg["bigquery"]["location"]
    client = bigquery.Client(project=project, location=location)
    dataset = bigquery.Dataset(f"{project}.{cfg['bigquery']['dataset_marts']}")
    dataset.location = location
    client.create_dataset(dataset, exists_ok=True)  # an empty dataset costs nothing

    for f in files:
        config = bigquery.QueryJobConfig(dry_run=args.dry_run, use_query_cache=False)
        try:
            job = client.query(render(f.read_text(), cfg), job_config=config)
            if args.dry_run:
                LOG.info("%s is valid (about %.1f MB to process)", f.name, (job.total_bytes_processed or 0) / 1e6)
            else:
                job.result()
                LOG.info("%s built", f.name)
        except NotFound as exc:
            if not args.dry_run:
                raise
            LOG.info("%s skipped in dry run: it reads a table that does not exist yet (%s)", f.name, str(exc).split(":")[-1].strip()[:80])

    if args.dry_run:
        return 0

    for table in ("fct_loan_snapshot", "mart_portfolio_metrics", "mart_segment_risk", "mart_nps_credit"):
        n = list(client.query(f"SELECT COUNT(*) AS n FROM `{project}.{cfg['bigquery']['dataset_marts']}.{table}`").result())[0]["n"]
        LOG.info("%-24s %s rows", table, f"{n:,}")

    marts = f"`{project}.{cfg['bigquery']['dataset_marts']}`"
    metrics = client.query(f"SELECT * FROM {marts}.mart_portfolio_metrics ORDER BY snapshot_date").to_dataframe(create_bqstorage_client=False)
    segments = client.query(f"SELECT * FROM {marts}.mart_segment_risk ORDER BY snapshot_date, segment_type, segment").to_dataframe(create_bqstorage_client=False)
    metrics.to_csv(args.out_dir / "portfolio_metrics.csv", index=False)
    segments.to_csv(args.out_dir / "segment_risk.csv", index=False)

    print("\n## Portfolio metrics by snapshot (financed loans)\n")
    print(metrics[SHOW_COLUMNS].to_string(index=False))
    print(f"\nSaved {args.out_dir / 'portfolio_metrics.csv'} and {args.out_dir / 'segment_risk.csv'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())