"""Tests for the analyst queries in sql/05_analysis/, run in DuckDB on the small mart fixture from test_marts.py.

Run:  uv run pytest tests/test_analysis_sql.py -q
"""
import re
from pathlib import Path

import pandas as pd
import pytest

from test_marts import con  # noqa: F401  (the fixture that builds the feature and mart tables)

ROOT = Path(__file__).resolve().parents[1]


def run_file(con, name: str) -> list[pd.DataFrame]:
    sql = (ROOT / "sql" / "05_analysis" / name).read_text().replace("{{MARTS}}", "marts")
    statements = [s for s in sql.split(";") if re.sub(r"--[^\n]*", "", s).strip()]
    return [con.execute(s).df() for s in statements]


def test_portfolio_health_query_matches_the_mart(con):
    (out,) = run_file(con, "portfolio_health.sql")
    assert len(out) == 2 and list(out["snapshot_date"].astype(str).str[:10]) == ["2025-01-01", "2025-03-31"]
    first, second = out.iloc[0], out.iloc[1]
    assert first["delinquent_pct"] == pytest.approx(66.7, abs=0.05) and pd.isna(first["delinquent_vs_previous"])
    assert second["financed_loans"] == 5
    assert second["delinquent_vs_previous"] == pytest.approx(second["delinquent_pct"] - first["delinquent_pct"], abs=0.11)


def test_nps_query_groups_by_days_past_due_at_the_response(con):
    (out,) = run_file(con, "nps_vs_credit.sql")
    row = out.set_index("days_past_due_when_answered").loc["31-60"]
    assert row["responses"] == 1 and row["average_score"] == pytest.approx(3.0) and row["nps"] == pytest.approx(-100.0)
