"""Unit tests for the mart SQL (sql/03_marts/*.sql), run in an in-memory DuckDB on tiny hand-built data.

The feature SQL runs first, then the four mart files, exactly as in BigQuery.
Run:  uv run --extra dev pytest tests/test_marts.py -q
"""
from datetime import date
from pathlib import Path

import duckdb
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
S1, S2 = date(2025, 1, 1), date(2025, 3, 31)


def credit(loan, snap, l1="Existing Active", l2="Active", dpd=0, scope="financed", paid=100.0, due=100.0):
    return {
        "loan_key": loan, "snapshot_date": snap, "portfolio_scope": scope, "account_status_l1": l1, "account_status_l2": l2,
        "balance": 1000.0, "arrears": 100.0 if dpd > 0 else 0.0, "total_paid": paid, "total_due_today": due, "days_past_due": float(dpd),
        "dq_arrears_zero_days": False, "dq_days_zero_arrears": False, "dq_negative_amount": False, "dq_payment_after_snapshot": False,
    }


S1_ROWS = [
    credit("A", S1),                                                              # healthy
    credit("B", S1, "Inactive 08-14", "PAR 7", 10, paid=80.0),                    # delinquent
    credit("C", S1, "Blocked 31-60", "PAR 30", 45, paid=50.0),                    # delinquent 30+
    credit("D", S1, "Write Off", "PAR 30", 120, paid=20.0),                       # loss
    credit("E", S1, "Paid Off Loan", "Paid Off"),                                 # closed, paid
    credit("F", S1, "First 2 days Return", "Return"),                             # closed, returned
    credit("G", S1, "Paid Off Cash", "Paid Off", scope="cash"),                   # not financed
]
S2_ROWS = [
    credit("A", S2, "Cancelled Returned in 3 mths", "Return"),                    # healthy before, returned now
    credit("B", S2),                                                              # recovered
    credit("C", S2, "Write Off", "PAR 30", 100, paid=40.0),                       # now lost
    credit("D", S2, "Write Off", "PAR 30", 130, paid=20.0),
    credit("H", S2),                                                              # new loan
]
AGE = [{"loan_key": k, "snapshot_date": s, "age_years": a, "age_band": b}
       for s in (S1, S2) for k, a, b in (("A", 22, "18-25"), ("B", 24, "18-25"), ("C", 30, "26-35"))]


@pytest.fixture(scope="module")
def con():
    c = duckdb.connect()
    c.execute("CREATE SCHEMA stg")
    c.execute("CREATE SCHEMA marts")
    tables = {
        "stg_credit_snapshots": pd.DataFrame(S1_ROWS + S2_ROWS),
        "stg_loan_age": pd.DataFrame(AGE),
        "stg_income": pd.DataFrame([{"loan_key": "A", "avg_monthly_income": 12000.0, "avg_monthly_income_sum_all": 20000.0}]),
        "stg_sales": pd.DataFrame([{"loan_key": k, "sale_date": S1, "sale_type": "Financed", "loan_price": 1.0, "cash_price": 1.0,
                                    "loan_term_months": 12.0, "client_model": "1C", "business_model": "x", "product_name": "p",
                                    "return_date": {"F": date(2025, 2, 1), "A": date(2025, 3, 1)}.get(k)} for k in "ABCDEFGH"]),
        "stg_nps": pd.DataFrame([{
            "response_key": "r1", "loan_key": "C", "submitted_date": date(2025, 2, 10), "matched_snapshot_date": S1, "nps_score": 3.0,
            "nps_category": "detractor", "is_latest_response": True, "quality_happy": "No", "service_happy": "No",
            "payment_delay_experienced": "Yes", "assistance_difficulty": None, "battery_issue": None, "app_usage": None,
            "preferred_channel": None, "phone_lock_experienced": None}]),
    }
    for name, df in tables.items():
        c.register("tmp", df)
        c.execute(f"CREATE TABLE stg.{name} AS SELECT * FROM tmp")
        c.unregister("tmp")
    files = [ROOT / "sql/02_features/loan_snapshot_features.sql", *sorted((ROOT / "sql/03_marts").glob("*.sql"))]
    for f in files:
        c.execute(f.read_text().replace("{{STG}}", "stg").replace("{{MARTS}}", "marts").replace("{{PARTITION}}", ""))
    return c


def table(con, name):
    df = con.execute(f"SELECT * FROM marts.{name}").df()
    for col in df.columns:
        if "date" in col and pd.api.types.is_datetime64_any_dtype(df[col]):
            df[col] = pd.to_datetime(df[col]).dt.date
    return df


def test_fact_table_has_one_row_per_loan_per_snapshot(con):
    f = table(con, "fct_loan_snapshot")
    assert len(f) == len(S1_ROWS) + len(S2_ROWS) and not f.duplicated(["loan_key", "snapshot_date"]).any()


def test_loan_flags(con):
    f = table(con, "fct_loan_snapshot").set_index(["loan_key", "snapshot_date"])
    assert f.loc[("D", S1), "is_loss_91plus"] and not f.loc[("D", S1), "is_performing"]
    assert f.loc[("C", S1), "is_delinquent_30plus"] and f.loc[("C", S1), "is_delinquent_7plus"]
    assert f.loc[("B", S1), "is_delinquent_7plus"] and not f.loc[("B", S1), "is_delinquent_30plus"]
    assert f.loc[("E", S1), "is_paid_off"] and f.loc[("F", S1), "is_returned"]
    assert not f.loc[("G", S1), "is_financed"]
    assert f.loc[("H", S2), "is_new_loan"] and not f.loc[("A", S1), "is_new_loan"]  # the first snapshot is the opening book


def test_return_date_is_only_shown_when_on_or_before_the_snapshot(con):
    f = table(con, "fct_loan_snapshot").set_index(["loan_key", "snapshot_date"])
    # Loan F was returned on 1 Feb 2025, after the 1 Jan snapshot, so the date must be hidden there.
    assert pd.isna(f.loc[("F", S1), "return_date_as_of_snapshot"])
    # Loan A was returned on 1 Mar 2025: hidden at the 1 Jan snapshot, visible at the 31 Mar snapshot.
    assert pd.isna(f.loc[("A", S1), "return_date_as_of_snapshot"])
    assert f.loc[("A", S2), "return_date_as_of_snapshot"] == date(2025, 3, 1)


def test_portfolio_metrics_first_snapshot(con):
    m = table(con, "mart_portfolio_metrics").set_index("snapshot_date").loc[S1]
    assert (m.financed_loans, m.live_loans, m.performing_loans) == (6, 4, 3)
    assert (m.delinquent_7plus_loans, m.delinquent_30plus_loans, m.loss_loans) == (2, 1, 1)
    assert (m.returned_loans, m.paid_off_loans, m.fpd_loans) == (1, 1, 0)
    assert m.delinquency_rate_7plus == pytest.approx(0.6667, abs=1e-4)
    assert m.par30_rate == pytest.approx(0.3333, abs=1e-4)
    assert m.loss_rate_count == pytest.approx(0.1667, abs=1e-4)
    assert m.loss_rate_balance == pytest.approx(0.25, abs=1e-4)      # 1,000 lost / 4,000 live balance
    assert m.collection_rate == pytest.approx(0.7667, abs=1e-4)      # (100 + 80 + 50) / 300 on performing loans
    assert pd.isna(m.retention_rate)                                  # no previous snapshot


def test_portfolio_metrics_second_snapshot_and_retention(con):
    m = table(con, "mart_portfolio_metrics").set_index("snapshot_date").loc[S2]
    assert (m.financed_loans, m.new_financed_loans, m.loss_loans, m.returned_loans) == (5, 1, 2, 1)
    # Healthy last time: A (Active) and B (PAR 7). A has since been returned, B recovered -> 1 of 2 retained.
    assert (m.retention_cohort_loans, m.retained_loans) == (2, 1)
    assert m.retention_rate == pytest.approx(0.5)


def test_segment_risk_and_benchmarks(con):
    s = table(con, "mart_segment_risk")
    s = s[(s.snapshot_date == S1) & (s.segment_type == "age_band")].set_index("segment")
    assert s.loc["18-25", "performing_loans"] == 2 and s.loc["18-25", "delinquency_rate_7plus"] == pytest.approx(0.5)
    assert s.loc["26-35", "delinquency_rate_7plus"] == pytest.approx(1.0)
    assert s.loc["18-25", "known_avg_delinquency_rate"] == pytest.approx(0.6667, abs=1e-4)  # 2 of 3 on loans with a known age
    assert s.loc["18-25", "delinquency_vs_known_avg"] == pytest.approx(0.75, abs=1e-3)
    assert bool(s.loc["26-35", "small_sample"])
    assert s.loc["Unknown", "financed_loans"] == 3 and pd.isna(s.loc["Unknown", "delinquency_rate_7plus"])


def test_nps_mart_uses_credit_status_at_the_matched_snapshot(con):
    n = table(con, "mart_nps_credit")
    assert len(n) == 1
    r = n.iloc[0]
    assert r.risk_category == "High" and r.risk_category_latest == "Critical"  # was 45 days late then, written off by the latest snapshot
    assert r.dpd_bucket == "31-60" and r.nps_category == "detractor"
    assert not {"reason_text", "improve_text", "challenge_text", "other_feedback_text"} & set(n.columns)  # free text stays in staging