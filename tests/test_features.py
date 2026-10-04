"""Unit tests for age_band, income band, days_past_due and risk_category."""

"""Unit tests for the feature SQL (sql/02_features/loan_snapshot_features.sql).

The SQL is run in an in-memory DuckDB against tiny hand-built staging tables, so no cloud access is needed.
Install once:  uv add --optional dev duckdb pytest
Run:           uv run pytest tests/test_features.py -q
"""
from datetime import date
from pathlib import Path

import duckdb
import pandas as pd
import pytest

SQL = Path(__file__).resolve().parents[1] / "sql" / "02_features" / "loan_snapshot_features.sql"
S1, S2 = date(2025, 1, 1), date(2025, 3, 31)


def credit(loan, snap=S1, l1="Existing Active", l2="Active", dpd=0, arrears=None, scope="financed", paid=100.0, due=100.0):
    arrears = (100.0 if dpd > 0 else 0.0) if arrears is None else arrears
    return {
        "loan_key": loan, "snapshot_date": snap, "portfolio_scope": scope, "account_status_l1": l1, "account_status_l2": l2,
        "balance": 1000.0, "arrears": arrears, "total_paid": paid, "total_due_today": due, "days_past_due": float(dpd),
        "dq_arrears_zero_days": False, "dq_days_zero_arrears": False, "dq_negative_amount": False, "dq_payment_after_snapshot": False,
    }


def run(credit_rows, age_rows=None, income_rows=None) -> pd.DataFrame:
    con = duckdb.connect()
    con.execute("CREATE SCHEMA stg")
    age = pd.DataFrame(age_rows or [{"loan_key": "none", "snapshot_date": S1, "age_years": 0, "age_band": "Unknown"}])
    inc = pd.DataFrame(income_rows or [{"loan_key": "none", "avg_monthly_income": 0.0, "avg_monthly_income_sum_all": 0.0}])
    for name, df in (("stg_credit_snapshots", pd.DataFrame(credit_rows)), ("stg_loan_age", age), ("stg_income", inc)):
        con.register("tmp", df)
        con.execute(f"CREATE TABLE stg.{name} AS SELECT * FROM tmp")
        con.unregister("tmp")
    con.execute(SQL.read_text().replace("{{STG}}", "stg").replace("{{PARTITION}}", ""))
    out = con.execute("SELECT * FROM stg.int_loan_snapshot_features").df()
    out["snapshot_date"] = pd.to_datetime(out["snapshot_date"]).dt.date  # DuckDB returns timestamps
    return out


@pytest.mark.parametrize(
    "kwargs, category, rule",
    [
        (dict(), "Low", "R6"),
        (dict(l1="Paid Off Loan", l2="Paid Off"), "Low", "R4"),
        (dict(l1="Write Off", l2="PAR 30", dpd=120), "Critical", "R1"),
        (dict(l1="Blocked 61-90", l2="PAR 30", dpd=70), "Critical", "R1"),
        (dict(l1="Cancelled Returned in 3 mths", l2="Return", dpd=0), "Critical", "R1"),
        (dict(l1="Blocked 31-60", l2="PAR 30", dpd=45), "High", "R2"),
        (dict(l1="First Payment Default", l2="FPD", dpd=5), "High", "R2"),
        (dict(l1="First Month Default without inventory 01-07", l2="Inactive", dpd=3), "High", "R2"),
        (dict(l1="Inactive 15-30", l2="PAR 7", dpd=20), "Medium", "R3"),
        (dict(l1="Inactive 01-07", l2="Inactive", dpd=3), "Low", "R6"),
        (dict(scope="cash", l1="Paid Off Cash", l2="Paid Off"), "Not rated", "R0"),
        (dict(scope="lost", l1="Lost Write Off", l2="PAR 30", dpd=200), "Not rated", "R0"),
        (dict(paid=70.0, due=100.0), "Medium", "R5"),  # low payment coverage on a current account
    ],
)
def test_risk_category_rules(kwargs, category, rule):
    out = run([credit("a", **kwargs)])
    assert out.loc[0, "risk_category"] == category
    assert out.loc[0, "risk_rule"].startswith(rule)


def test_days_past_due_is_zero_without_arrears_and_original_is_kept():
    out = run([credit("a", dpd=5, arrears=0.0), credit("b", dpd=5, arrears=50.0)]).set_index("loan_key")
    assert out.loc["a", "days_past_due"] == 0 and out.loc["a", "days_past_due_reported"] == 5
    assert out.loc["b", "days_past_due"] == 5


def test_dpd_buckets():
    cases = {0: "0", 1: "1-7", 7: "1-7", 8: "8-30", 30: "8-30", 31: "31-60", 60: "31-60", 61: "61-90", 90: "61-90", 91: "91+"}
    out = run([credit(f"l{d}", dpd=d) for d in cases]).set_index("loan_key")
    assert {int(k[1:]): v for k, v in out["dpd_bucket"].items()} == cases


def test_payment_history_uses_earlier_snapshots_only():
    rows = [
        credit("a", S1, l1="Inactive 08-14", l2="PAR 7", dpd=10),  # was late earlier
        credit("a", S2),                                              # current now: history lifts it to Medium
        credit("b", S1), credit("b", S2, l1="Inactive 08-14", l2="PAR 7", dpd=10),  # late only AFTER: no effect on first row
    ]
    out = run(rows).set_index(["loan_key", "snapshot_date"])
    assert out.loc[("a", S2), "risk_category"] == "Medium" and out.loc[("a", S2), "risk_rule"].startswith("R5")
    assert out.loc[("b", S1), "risk_category"] == "Low"
    assert pd.isna(out.loc[("a", S1), "max_dpd_prior"]) and out.loc[("a", S2), "max_dpd_prior"] == 10
    assert out.loc[("a", S2), "prior_snapshots_in_arrears"] == 1


@pytest.mark.parametrize(
    "income, band",
    [(None, "Unknown"), (4999.99, "Below 5,000"), (5000, "5,000-9,999"), (9999.99, "5,000-9,999"), (10000, "10,000-19,999"),
     (29999, "20,000-29,999"), (30000, "30,000-49,999"), (50000, "50,000-99,999"), (100000, "100,000-149,999"), (150000, "150,000+")],
)
def test_income_bands_follow_the_brief(income, band):
    inc = [{"loan_key": "a", "avg_monthly_income": income, "avg_monthly_income_sum_all": income}]
    out = run([credit("a")], income_rows=inc)
    assert out.loc[0, "avg_monthly_income_band"] == band


def test_age_band_comes_from_loan_age_and_defaults_to_unknown():
    age = [{"loan_key": "a", "snapshot_date": S1, "age_years": 30, "age_band": "26-35"}]
    out = run([credit("a"), credit("b")], age_rows=age).set_index("loan_key")
    assert out.loc["a", "age_band"] == "26-35" and out.loc["b", "age_band"] == "Unknown"


def test_grain_is_one_row_per_loan_per_snapshot():
    rows = [credit("a", S1), credit("a", S2), credit("b", S1)]
    out = run(rows)
    assert len(out) == 3 and not out.duplicated(["loan_key", "snapshot_date"]).any()


def test_is_live_excludes_closed_and_non_financed():
    rows = [credit("a"), credit("b", l1="Paid Off Loan", l2="Paid Off"), credit("c", l2="Return", l1="First 2 days Return"), credit("d", scope="cash")]
    out = run(rows).set_index("loan_key")
    assert out["is_live"].to_dict() == {"a": True, "b": False, "c": False, "d": False}