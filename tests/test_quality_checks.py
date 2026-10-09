"""Unit tests for the data quality framework. The SQL checks run in an in-memory DuckDB on tiny tables, so no cloud
access is needed. Each test seeds one defect and asserts that exactly the right check fails.

Run:  uv run --extra dev pytest tests/test_quality_checks.py -q
"""
import sys
from datetime import date
from pathlib import Path

import duckdb
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import quality_checks as qc  # noqa: E402

S1, S2 = date(2025, 1, 1), date(2025, 3, 31)
LOANS = list("ABCDEFGHIJ")


def clean_tables() -> dict[str, pd.DataFrame]:
    credit = [{"loan_key": k, "snapshot_date": s, "account_status_l2": "Active", "days_past_due": 0.0, "arrears": 0.0,
               "total_due_today": 100.0, "max_payment_date": s, "dq_payment_after_snapshot": False, "dq_negative_amount": False}
              for s in (S1, S2) for k in LOANS]
    return {
        "stg_credit_snapshots": pd.DataFrame(credit),
        "stg_sales": pd.DataFrame([{"loan_key": k, "sale_type": "Financed", "loan_term_months": 12.0, "dq_return_before_sale": False} for k in LOANS]),
        "stg_loan_age": pd.DataFrame([{"loan_key": k, "snapshot_date": s, "age_years": 30, "age_band": "26-35"} for s in (S1, S2) for k in LOANS]),
        "stg_income": pd.DataFrame([{"loan_key": k, "avg_monthly_income": 20000.0} for k in LOANS]),
        "stg_nps": pd.DataFrame([{"response_key": f"r{i}", "loan_key": k, "nps_score": 8.0} for i, k in enumerate(LOANS[:4])]),
    }


def run(tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    con = duckdb.connect()
    con.execute("CREATE SCHEMA stg")
    for name, df in tables.items():
        con.register("tmp", df)
        con.execute(f"CREATE TABLE stg.{name} AS SELECT * FROM tmp")
        con.unregister("tmp")
    return qc.run_sql_checks(lambda sql: con.execute(sql).df(), "stg", ["2025-01-01", "2025-03-31"])


def failed(results: pd.DataFrame) -> set[str]:
    return set(results.loc[~results["passed"].astype(bool), "check_name"])


def test_clean_data_passes_every_check():
    results = run(clean_tables())
    assert failed(results) == set() and len(results) >= 30


def seed_duplicate_credit_row(t):
    t["stg_credit_snapshots"] = pd.concat([t["stg_credit_snapshots"], t["stg_credit_snapshots"].iloc[[0]]], ignore_index=True)

def seed_null_credit_key(t):
    t["stg_credit_snapshots"].loc[0, "loan_key"] = None

def seed_orphan_nps_loan(t):
    t["stg_nps"].loc[0, "loan_key"] = "ZZZ"

def seed_age_out_of_range(t):
    t["stg_loan_age"].loc[0, "age_years"] = 15

def seed_negative_days_past_due(t):
    t["stg_credit_snapshots"].loc[0, "days_past_due"] = -3.0

def seed_nps_score_out_of_range(t):
    t["stg_nps"].loc[0, "nps_score"] = 12.0

def seed_missing_snapshot(t):
    t["stg_credit_snapshots"] = t["stg_credit_snapshots"][t["stg_credit_snapshots"].snapshot_date == S1]
    t["stg_loan_age"] = t["stg_loan_age"][t["stg_loan_age"].snapshot_date == S1]

def seed_future_payment_dates(t):
    t["stg_credit_snapshots"]["dq_payment_after_snapshot"] = True

def seed_book_shrinks(t):
    c = t["stg_credit_snapshots"]
    t["stg_credit_snapshots"] = c.drop(c[(c.snapshot_date == S2) & (c.loan_key.isin(["I", "J"]))].index)
    a = t["stg_loan_age"]
    t["stg_loan_age"] = a.drop(a[(a.snapshot_date == S2) & (a.loan_key.isin(["I", "J"]))].index)

def seed_credit_loan_without_sale(t):
    t["stg_sales"] = t["stg_sales"].iloc[1:]

def seed_missing_nps_scores(t):
    t["stg_nps"]["nps_score"] = None

def seed_demographic_coverage_collapse(t):
    t["stg_loan_age"]["age_band"] = "Unknown"


@pytest.mark.parametrize(
    "seed, expected_check, expected_severity",
    [
        (seed_duplicate_credit_row, "uniqueness.credit_loan_snapshot", "critical"),
        (seed_null_credit_key, "nulls.credit.loan_key", "critical"),
        (seed_orphan_nps_loan, "integrity.nps_loans_missing_from_credit", "critical"),
        (seed_age_out_of_range, "range.age_outside_18_120", "critical"),
        (seed_negative_days_past_due, "range.negative_days_past_due", "critical"),
        (seed_nps_score_out_of_range, "range.nps_score_outside_0_10", "critical"),
        (seed_missing_snapshot, "freshness.expected_snapshots_missing", "critical"),
        (seed_future_payment_dates, "range.payment_date_after_snapshot_share", "warning"),
        (seed_book_shrinks, "freshness.snapshot_row_count_dropped", "warning"),
        (seed_credit_loan_without_sale, "integrity.credit_loans_missing_from_sales", "critical"),
        (seed_missing_nps_scores, "nulls.nps.nps_score", "warning"),
        (seed_demographic_coverage_collapse, "integrity.share_of_latest_loans_without_age", "warning"),
    ],
)
def test_each_seeded_defect_is_caught(seed, expected_check, expected_severity):
    tables = clean_tables()
    seed(tables)
    results = run(tables)
    assert expected_check in failed(results)
    assert results.set_index("check_name").loc[expected_check, "severity"] == expected_severity


def test_alerting_and_exit_codes():
    tables = clean_tables()
    seed_future_payment_dates(tables)
    warning_only = run(tables)
    assert qc.exit_code(warning_only, "critical") == 0 and qc.exit_code(warning_only, "warning") == 1
    seed_orphan_nps_loan(tables)
    with_critical = run(tables)
    assert qc.exit_code(with_critical, "critical") == 2 and qc.exit_code(with_critical, "never") == 0
    lines = qc.alerts(with_critical)
    assert any(line.startswith("ALERT [critical] integrity.nps_loans_missing_from_credit") for line in lines)
    assert any(line.startswith("WARNING [warning] range.payment_date_after_snapshot_share") for line in lines)


def test_expected_dates_sql_rejects_bad_input():
    assert qc.expected_dates_sql(["2025-01-01", "2025-03-31"]) == "SELECT DATE '2025-01-01' AS d UNION ALL SELECT DATE '2025-03-31'"
    with pytest.raises(ValueError):
        qc.expected_dates_sql(["2025-01-01'; DROP TABLE x; --"])


def test_files_with_only_comments_are_skipped(tmp_path):
    (tmp_path / "dq_placeholder.sql").write_text("-- placeholder only\n")
    (tmp_path / "dq_real.sql").write_text(
        "SELECT 'x.check' AS check_name, 'warning' AS severity, 0.0 AS observed, 1.0 AS threshold, TRUE AS passed, 'demo' AS description")
    seen = []
    def fake_query(sql):
        seen.append(sql)
        return pd.DataFrame([{"check_name": "x.check", "severity": "warning", "observed": 0.0, "threshold": 1.0, "passed": True, "description": "demo"}])
    out = qc.run_sql_checks(fake_query, "stg", ["2025-01-01"], sql_dir=tmp_path)
    assert len(seen) == 1 and list(out["check_name"]) == ["x.check"]


def test_pii_check_flags_leaks_and_passes_clean_tables():
    clean = pd.DataFrame({"loan_key": ["0123456789abcdef0123"], "note": ["all good"]})
    leaky = pd.DataFrame({"loan_key": ["0123456789abcdef0123"], "note": ["call me on 0712 345 678 or me@example.com"]})
    unmasked = pd.DataFrame({"loan_key": ["recAbCdEfGh1234567"], "note": ["fine"]})
    tables = {"stg_a": clean, "stg_b": leaky, "stg_c": unmasked}
    res = qc.pii_checks(lambda name: tables.get(name), ["stg_a", "stg_b", "stg_c", "stg_missing"], []).set_index("check_name")
    assert bool(res.loc["pii.stg_a", "passed"]) and not bool(res.loc["pii.stg_b", "passed"]) and not bool(res.loc["pii.stg_c", "passed"])
    assert "pii.stg_missing" not in res.index  # tables that do not exist yet are skipped


CONTRACT = """-- header
CREATE TABLE IF NOT EXISTS {{STG}}.stg_demo (
  loan_key STRING,
  snapshot_date DATE,
  amount   FLOAT64
)
PARTITION BY snapshot_date;
"""


def test_contract_file_is_parsed():
    assert qc.parse_contract(CONTRACT) == ("stg_demo", {"loan_key": "STRING", "snapshot_date": "DATE", "amount": "FLOAT64"})
    assert qc.parse_contract("-- just a comment") is None


def test_schema_check_passes_on_a_matching_table_and_names_every_problem(tmp_path):
    (tmp_path / "stg_demo.sql").write_text(CONTRACT)
    good = pd.DataFrame({"column_name": ["loan_key", "snapshot_date", "amount"], "data_type": ["STRING", "DATE", "FLOAT64"]})
    assert bool(qc.schema_checks(lambda q: good, "`p.d`", tmp_path)["passed"].iloc[0])
    bad = pd.DataFrame({"column_name": ["loan_key", "amount", "extra_col"], "data_type": ["STRING", "STRING", "INT64"]})
    res = qc.schema_checks(lambda q: bad, "`p.d`", tmp_path).iloc[0]
    assert res["check_name"] == "schema.stg_demo" and res["severity"] == "critical" and not bool(res["passed"])
    assert res["observed"] == 3
    assert "missing snapshot_date" in res["description"] and "unexpected extra_col" in res["description"] and "amount is STRING" in res["description"]
    missing_table = pd.DataFrame({"column_name": [], "data_type": []})
    assert qc.schema_checks(lambda q: missing_table, "`p.d`", tmp_path)["observed"].iloc[0] == 3


def test_schema_query_targets_the_information_schema_of_the_staging_dataset(tmp_path):
    (tmp_path / "stg_demo.sql").write_text(CONTRACT)
    seen = []
    qc.schema_checks(lambda q: seen.append(q) or pd.DataFrame({"column_name": [], "data_type": []}), "`p.d`", tmp_path)
    assert seen == ["SELECT column_name, data_type FROM `p.d`.INFORMATION_SCHEMA.COLUMNS WHERE table_name = 'stg_demo'"]


def test_the_real_contract_files_in_the_repo_are_readable():
    files = sorted(qc.CONTRACT_DIR.glob("stg_*.sql"))
    assert len(files) == 5
    for f in files:
        table, cols = qc.parse_contract(f.read_text())
        assert table == f.stem and len(cols) >= 5 and any(c.endswith("_key") and t == "STRING" for c, t in cols.items())
