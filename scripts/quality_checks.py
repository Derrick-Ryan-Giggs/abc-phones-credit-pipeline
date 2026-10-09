#!/usr/bin/env python3
"""quality_checks.py

Data quality framework (Part 2 of the brief). Runs the checks in sql/04_dq_checks/ against the staging tables,
adds a Python check that no personal data is left in any staging or mart table, prints a pass/fail report,
and saves every result to BigQuery (abc_staging.dq_results) and outputs/dq_results.csv.

Checks (each result has: check_name, severity, observed, threshold, passed, description; passed = observed <= threshold):
    1 freshness              expected snapshots present, newest snapshot is the expected one, book never shrinks
    2 uniqueness             no duplicate loans, snapshots or survey responses
    3 referential integrity  every loan exists where it should; demographic coverage stays above a floor
    4 range and logic        ages 18-120, days past due not negative, NPS 0-10, known source defects reported
    5 null thresholds        keys never null; per-column limits set from the profiling run
    6 no unmasked PII        no raw IDs, emails or phone numbers in staging or marts (Python, see pii_checks)
    7 schema contract        every staging table has exactly the columns and types agreed in sql/01_staging (Python, see schema_checks)

Severity and alerting:
    critical  the run exits with code 2, an ALERT block is printed and logged at ERROR level; in production the
              ERROR log line triggers an email alert and the mart refresh is blocked
    warning   reported and logged at WARNING level; the load continues and the issue is reviewed in the weekly digest

Run from the project root (needs Application Default Credentials):
    uv run python scripts/quality_checks.py --dry-run     # validate the SQL only
    uv run python scripts/quality_checks.py               # run all checks and store the results
    uv run python scripts/quality_checks.py --fail-on never   # always exit 0 (used for demos)

Monitoring cadence: on every load (freshness, row counts, key nulls), daily (the full set), weekly (review
dq_results for drift in null shares, demographic coverage and the known-defect rates).
"""
from __future__ import annotations

import argparse
import logging
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import yaml

from utils.logging_setup import setup_logging

ROOT = Path(__file__).resolve().parents[1]
SQL_DIR = ROOT / "sql" / "04_dq_checks"
CONTRACT_DIR = ROOT / "sql" / "01_staging"
LOG = logging.getLogger("quality_checks")
RESULT_COLUMNS = ["check_name", "severity", "observed", "threshold", "passed", "description"]

# Tables scanned for personal data. Mart tables are only scanned if they exist.
PII_STAGING_TABLES = ["stg_credit_snapshots", "stg_sales", "stg_loan_age", "stg_income", "stg_nps"]
PII_MART_TABLES = ["fct_loan_snapshot", "mart_nps_credit"]
# The survey answer options contain the company support number, which is not personal data.
PII_SKIP_COLUMNS = ("preferred_channel",)


def expected_dates_sql(dates: list[str]) -> str:
    """A SQL snippet listing the expected snapshot dates, e.g. SELECT DATE '2025-01-01' AS d UNION ALL ..."""
    for d in dates:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(d)):
            raise ValueError(f"Bad date in settings.yaml snapshots.expected_dates: {d!r}")
    return " UNION ALL ".join(f"SELECT DATE '{d}'" + (" AS d" if i == 0 else "") for i, d in enumerate(dates))


def render(sql: str, stg: str, expected: str) -> str:
    return sql.replace("{{STG}}", stg).replace("{{EXPECTED_DATES}}", expected)


def _is_blank(sql: str) -> bool:
    """True when a file holds only comments (for example an unfinished placeholder)."""
    return all(not line.strip() or line.strip().startswith("--") for line in sql.splitlines())


def run_sql_checks(run_query, stg: str, dates: list[str], sql_dir: Path = SQL_DIR) -> pd.DataFrame:
    """Run every SQL check file. run_query(sql) must return a DataFrame, so tests can use DuckDB instead of BigQuery."""
    expected = expected_dates_sql(dates)
    frames = []
    for f in sorted(sql_dir.glob("dq_*.sql")):
        text = f.read_text()
        if _is_blank(text):
            LOG.info("Skipping %s (no SQL in it)", f.name)
            continue
        frames.append(run_query(render(text, stg, expected))[RESULT_COLUMNS])
        LOG.info("Ran %s", f.name)
    return pd.concat(frames, ignore_index=True)


def pii_checks(read_table, staging: list[str], marts: list[str]) -> pd.DataFrame:
    """Check 6: count raw IDs, emails and phone numbers left in any table. read_table(name) returns a DataFrame or None."""
    from data_cleaning import pii_guard  # imported here so the SQL checks and their tests stay lightweight

    rows = []
    for name in [*staging, *marts]:
        df = read_table(name)
        if df is None:
            LOG.info("PII scan skipped for %s (table does not exist yet)", name)
            continue
        hits = pii_guard(name, df, skip=PII_SKIP_COLUMNS)
        rows.append({"check_name": f"pii.{name}", "severity": "critical", "observed": float(hits), "threshold": 0.0,
                     "passed": hits == 0, "description": f"Raw IDs, emails, phone numbers or unmasked keys found in {name}"})
    return pd.DataFrame(rows, columns=RESULT_COLUMNS)


def parse_contract(sql: str):
    """Read a staging contract file. Returns (table name, {column: type}) or None if the file has no CREATE TABLE."""
    m = re.search(r"CREATE TABLE IF NOT EXISTS\s+\{\{STG\}\}\.(\w+)\s*\((.*?)\n\)", sql, re.S)
    if not m:
        return None
    cols = {}
    for line in m.group(2).splitlines():
        c = re.match(r"\s*(\w+)\s+(STRING|FLOAT64|INT64|BOOL|DATE|TIMESTAMP)\b", line)
        if c:
            cols[c.group(1)] = c.group(2)
    return m.group(1), cols


def schema_checks(run_query, stg: str, contract_dir: Path = CONTRACT_DIR) -> pd.DataFrame:
    """Check 7: each staging table must have exactly the columns and types in its contract file (catches a malformed load)."""
    rows = []
    for f in sorted(contract_dir.glob("*.sql")):
        parsed = parse_contract(f.read_text())
        if parsed is None:
            continue
        table, expected = parsed
        actual_df = run_query(f"SELECT column_name, data_type FROM {stg}.INFORMATION_SCHEMA.COLUMNS WHERE table_name = '{table}'")
        actual = dict(zip(actual_df["column_name"], actual_df["data_type"]))
        problems = ([f"missing {c}" for c in sorted(set(expected) - set(actual))]
                    + [f"unexpected {c}" for c in sorted(set(actual) - set(expected))]
                    + [f"{c} is {actual[c]}, expected {expected[c]}" for c in expected if c in actual and actual[c] != expected[c]])
        detail = f": {'; '.join(problems[:5])}" if problems else ""
        rows.append({"check_name": f"schema.{table}", "severity": "critical", "observed": float(len(problems)), "threshold": 0.0,
                     "passed": not problems, "description": f"{table} matches its schema contract in sql/01_staging{detail}"})
    return pd.DataFrame(rows, columns=RESULT_COLUMNS)


def exit_code(results: pd.DataFrame, fail_on: str = "critical") -> int:
    """0 = fine, 2 = a critical check failed, 1 = only warnings failed and --fail-on warning was chosen."""
    failed = results[~results["passed"].astype(bool)]
    if fail_on == "never" or failed.empty:
        return 0
    if (failed["severity"] == "critical").any():
        return 2
    return 1 if fail_on == "warning" else 0


def report(results: pd.DataFrame) -> str:
    shown = results.assign(status=results["passed"].map({True: "PASS", False: "FAIL"}))
    shown = shown.sort_values(["passed", "check_name"])
    shown["observed"] = shown["observed"].map(lambda v: f"{v:.5g}")
    shown["threshold"] = shown["threshold"].map(lambda v: f"{v:.5g}")
    n_fail = int((~results["passed"].astype(bool)).sum())
    crit = int(((~results["passed"].astype(bool)) & (results["severity"] == "critical")).sum())
    lines = [shown[["status", "severity", "check_name", "observed", "threshold"]].to_string(index=False),
             f"\n{len(results)} checks: {len(results) - n_fail} passed, {n_fail} failed ({crit} critical)"]
    return "\n".join(lines)


def alerts(results: pd.DataFrame) -> list[str]:
    out = []
    for r in results[~results["passed"].astype(bool)].itertuples():
        out.append(f"{'ALERT' if r.severity == 'critical' else 'WARNING'} [{r.severity}] {r.check_name}: "
                   f"observed {r.observed:.5g} vs threshold {r.threshold:.5g}. {r.description}")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="validate the SQL only, run no checks")
    ap.add_argument("--no-write", action="store_true", help="do not store results in BigQuery")
    ap.add_argument("--fail-on", choices=["critical", "warning", "never"], default="critical")
    ap.add_argument("--config", type=Path, default=ROOT / "config" / "settings.yaml")
    ap.add_argument("--out-dir", type=Path, default=ROOT / "outputs")
    ap.add_argument("--log-dir", type=Path, default=ROOT / "logs")
    args = ap.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    args.log_dir.mkdir(parents=True, exist_ok=True)
    setup_logging("quality_checks", args.log_dir)
    cfg = yaml.safe_load(args.config.read_text())
    project, location = cfg["gcp"]["project_id"], cfg["bigquery"]["location"]
    stg_id, marts_id = cfg["bigquery"]["dataset_staging"], cfg["bigquery"]["dataset_marts"]
    stg = f"`{project}.{stg_id}`"
    dates = cfg["snapshots"]["expected_dates"]

    from google.api_core.exceptions import NotFound
    from google.cloud import bigquery

    client = bigquery.Client(project=project, location=location)

    if args.dry_run:
        for f in sorted(SQL_DIR.glob("dq_*.sql")):
            if _is_blank(f.read_text()):
                continue
            job = client.query(render(f.read_text(), stg, expected_dates_sql(dates)), job_config=bigquery.QueryJobConfig(dry_run=True))
            LOG.info("%s is valid (about %.1f MB)", f.name, (job.total_bytes_processed or 0) / 1e6)
        return 0

    run_id, run_ts = uuid.uuid4().hex[:8], datetime.now(timezone.utc)
    LOG.info("Quality run %s started", run_id)

    def run_query(sql: str) -> pd.DataFrame:
        return client.query(sql).to_dataframe(create_bqstorage_client=False)

    def read_table(name: str):
        dataset = marts_id if name in PII_MART_TABLES else stg_id
        try:
            return client.query(f"SELECT * FROM `{project}.{dataset}.{name}`").to_dataframe(create_bqstorage_client=False)
        except NotFound:
            return None

    results = pd.concat([run_sql_checks(run_query, stg, dates), schema_checks(run_query, stg),
                         pii_checks(read_table, PII_STAGING_TABLES, PII_MART_TABLES)], ignore_index=True)
    results["passed"] = results["passed"].astype(bool)
    results.insert(0, "run_ts", run_ts)
    results.insert(0, "run_id", run_id)
    results.to_csv(args.out_dir / "dq_results.csv", index=False)

    if not args.no_write:
        client.load_table_from_dataframe(results, f"{project}.{stg_id}.dq_results",
                                         job_config=bigquery.LoadJobConfig(write_disposition="WRITE_APPEND")).result()
        LOG.info("Saved %s results to %s.dq_results", len(results), stg_id)

    for line in alerts(results):
        (LOG.error if line.startswith("ALERT") else LOG.warning)(line)
    print(f"\n## Data quality results (run {run_id})\n")
    print(report(results))
    failing = alerts(results)
    if failing:
        print("\n## Details of failed checks\n")
        print("\n".join(failing))
    code = exit_code(results, args.fail_on)
    if code == 2:
        print("\nCRITICAL FAILURE: in production the mart refresh would be blocked and the on-call engineer emailed.")
    return code


if __name__ == "__main__":
    sys.exit(main())