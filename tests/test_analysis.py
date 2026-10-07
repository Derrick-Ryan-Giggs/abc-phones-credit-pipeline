"""Unit tests for the statistics and selection logic in scripts/analysis.py (no cloud access needed).

Run:  uv run --extra dev pytest tests/test_analysis.py -q
"""
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import analysis as an  # noqa: E402


def test_wilson_interval_matches_a_known_value():
    lo, hi = an.wilson_ci(50, 100)
    assert (lo, hi) == pytest.approx((0.4038, 0.5962), abs=1e-3)
    assert math.isnan(an.wilson_ci(0, 0)[0])


def test_two_proportion_test_is_symmetric_and_detects_a_real_gap():
    z, p = an.two_proportion_test(60, 200, 30, 200)
    z2, p2 = an.two_proportion_test(30, 200, 60, 200)
    assert z == pytest.approx(-z2) and p == pytest.approx(p2)
    assert z > 3 and p < 0.01
    assert an.two_proportion_test(10, 100, 10, 100)[1] == pytest.approx(1.0)


def test_nps_formula():
    s = pd.Series([10, 9, 9, 8, 7, 6, 0, 3, None])           # 3 promoters, 2 passives, 3 detractors out of 8 scored
    assert an.nps_score(s) == pytest.approx(100 * (3 / 8 - 3 / 8))
    assert an.nps_score(pd.Series([10, 10, 9, 5])) == pytest.approx(50.0)
    lo, hi = an.nps_ci(pd.Series(np.r_[np.full(80, 10), np.full(20, 0)]))
    assert lo < 60 < hi


def test_headline_is_the_riskiest_significant_large_segment():
    table = pd.DataFrame({
        "segment_type": "x", "segment": ["tiny_but_extreme", "big_and_worse", "best", "worse_but_not_significant"],
        "performing_loans": [20, 500, 800, 400], "vs_average": [2.0, 1.3, 0.7, 1.4], "p_value": [0.001, 0.01, 0.001, 0.2],
    })
    assert an.pick_headline(table)["segment"] == "big_and_worse"
    assert an.pick_headline(table.iloc[[2]]) is None   # nothing is both riskier and significant


def test_segment_table_tests_each_segment_against_the_others():
    rng = np.random.default_rng(1)
    perf = pd.DataFrame({"band": ["A"] * 400 + ["B"] * 400, "is_delinquent_7plus": np.r_[rng.random(400) < 0.3, rng.random(400) < 0.1]})
    t = an.segment_table(perf, "band", ["A", "B"]).set_index("segment")
    assert t.loc["A", "delinquency_rate"] > t.loc["B", "delinquency_rate"]
    assert t.loc["A", "vs_average"] > 1 > t.loc["B", "vs_average"] and t.loc["A", "p_value"] < 0.001


def test_demographics_era_starts_where_coverage_stays_high():
    rows = []
    for q, known in (("2024-03-31", 0.0), ("2024-06-30", 0.0), ("2024-09-30", 0.4), ("2024-12-31", 0.9), ("2025-03-31", 0.95)):
        for i in range(100):
            rows.append({"is_financed": True, "sale_date": pd.Timestamp(q), "avg_monthly_income_band": "10,000-19,999" if i < known * 100 else "Unknown",
                         "age_band": "26-35", "is_loss_91plus": False})
    assert an.demographics_era_start(pd.DataFrame(rows)) == pd.Timestamp("2024-10-01")


def test_markdown_table_helper():
    out = an.md_table(pd.DataFrame({"a": [1, 2], "b": ["x", "y"]}))
    assert out.splitlines()[0] == "| a | b |" and out.splitlines()[2] == "| 1 | x |"


def test_trend_test_detects_a_steady_gradient_and_ignores_noise():
    steady = pd.DataFrame({"performing_loans": [400] * 6, "delinquent_loans": [120, 100, 85, 70, 55, 40]})
    z, p = an.trend_test(steady)
    assert z < -5 and p < 1e-6
    flat = pd.DataFrame({"performing_loans": [400] * 6, "delinquent_loans": [80, 82, 78, 81, 79, 80]})
    assert an.trend_test(flat)[1] > 0.5


def test_nps_by_keeps_values_that_are_not_in_the_expected_order():
    df = pd.DataFrame({"risk": ["Low"] * 5 + ["Critical"] * 5 + ["Not rated"] * 5, "nps_score": [9, 10, 8, 3, 9] * 3})
    out = an.nps_by(df, "risk", ["Low", "Medium", "High", "Critical"])
    assert list(out["risk"]) == ["Low", "Critical", "Not rated"] and out["risk"].notna().all()


def test_payment_status_groups_cover_every_bucket_once():
    assert [an.status_group(b) for b in ["0", "1-7", "8-30", "31-60", "61-90", "91+"]] == [
        "Up to date", "1 to 30 days late", "1 to 30 days late", "31 to 90 days late", "31 to 90 days late", "Over 90 days late"]
    assert an.status_group("unknown") is None


def test_all_charts_render(tmp_path):
    pytest.importorskip("matplotlib")
    rng = np.random.default_rng(3)
    metrics = pd.DataFrame({"snapshot_date": pd.to_datetime(["2025-01-01", "2025-03-31", "2025-06-30", "2025-09-30", "2025-12-30"]),
                            "delinquency_rate_7plus": [.17, .19, .18, .18, .17], "par30_rate": [.11, .12, .11, .12, .11],
                            "loss_rate_count": [.23, .26, .27, .27, .26], "collection_rate": [.94, .93, .93, .93, .94],
                            "fpd_rate": [.07, .068, .061, .057, .058], "retention_rate": [np.nan, .93, .94, .95, .96]})
    an.chart_portfolio_trends(metrics, tmp_path / "a.png")
    perf = pd.DataFrame({"band": rng.choice(["A", "B", "C"], 600), "is_delinquent_7plus": rng.random(600) < 0.2})
    seg = an.segment_table(perf, "band", ["A", "B", "C"])
    an.chart_income_risk(seg, (-3.0, 0.001), pd.Timestamp("2025-01-01"), tmp_path / "b.png")
    an.chart_age_risk(seg, pd.Timestamp("2025-01-01"), tmp_path / "c.png")
    sample = pd.DataFrame({"dpd_bucket": rng.choice(["0", "1-7", "8-30", "31-60", "61-90", "91+"], 400), "nps_score": rng.integers(0, 11, 400).astype(float),
                           "assistance_difficulty": rng.choice(["Yes", "No"], 400), "phone_lock_experienced": rng.choice(["Yes", "No"], 400),
                           "payment_delay_experienced": rng.choice(["Yes", "No"], 400)})
    an.chart_nps_by_status(sample, tmp_path / "d.png")
    an.chart_nps_experience(sample, tmp_path / "e.png")
    assert all((tmp_path / f"{n}.png").stat().st_size > 5000 for n in "abcde")