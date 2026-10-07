#!/usr/bin/env python3
"""analysis.py

Portfolio analysis for the brief's Part 3, built from the mart tables in BigQuery (abc_marts).

3A  Portfolio health   five metrics across the five snapshots, plus the one customer segment whose risk differs most
3B  Credit vs NPS      does NPS fall as credit performance worsens, where do collections and satisfaction clash,
                       and where could both be improved at once
(3C, data gaps, is written up in the deck; the coverage tables printed here are its evidence)

Run from the project root (needs the viz extra:  uv sync --extra viz):
    uv run python scripts/analysis.py

Outputs:
    outputs/charts/*.png          five plain-language charts for the deck (portfolio_trends, segment_risk, segment_risk_age,
                                  nps_credit, nps_experience)
    outputs/analysis_findings.md  every number behind the charts, ready to quote in the slides
    outputs/segment_analysis.csv  segment table with confidence intervals and tests

Method notes (also written into analysis_findings.md):
  * Demographics (age, income) only exist for loans sold from late 2024 onwards. Segment comparisons therefore use only
    loans sold since the first quarter with at least 80% coverage, so that "no demographics" (old loans) is not mistaken
    for a customer trait. This is checked from the data, not assumed.
  * Delinquency = loans 8-90 days past due / performing loans (loans 91+ days past due count as losses, not delinquency).
  * NPS = % scoring 9-10 minus % scoring 0-6. Only the latest scored response per loan is used, with the loan's credit state
    at the latest snapshot ON OR BEFORE the response date (no look-ahead). Intervals are 95% (Wilson for rates, bootstrap for NPS).
"""
from __future__ import annotations

import argparse
import logging
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
LOG = logging.getLogger("analysis")

COVERAGE_THRESHOLD = 0.80
MIN_PERFORMING_FOR_HEADLINE = 100
DPD_ORDER = ["0", "1-7", "8-30", "31-60", "61-90", "91+"]
RISK_ORDER = ["Low", "Medium", "High", "Critical"]
INCOME_ORDER = ["Below 5,000", "5,000-9,999", "10,000-19,999", "20,000-29,999", "30,000-49,999",
                "50,000-99,999", "100,000-149,999", "150,000+"]
AGE_ORDER = ["18-25", "26-35", "36-45", "46-55", "56+"]


# ----------------------------------------------------------------------------
# Statistics helpers (standard library and numpy only)
# ----------------------------------------------------------------------------
def wilson_ci(k: float, n: float, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (float("nan"), float("nan"))
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return centre - half, centre + half


def two_proportion_test(k1: float, n1: float, k2: float, n2: float) -> tuple[float, float]:
    """z statistic and two-sided p-value for rate1 - rate2."""
    if min(n1, n2) == 0:
        return float("nan"), float("nan")
    pooled = (k1 + k2) / (n1 + n2)
    se = math.sqrt(pooled * (1 - pooled) * (1 / n1 + 1 / n2))
    if se == 0:
        return float("nan"), float("nan")
    z = (k1 / n1 - k2 / n2) / se
    return z, math.erfc(abs(z) / math.sqrt(2))


def trend_test(table: pd.DataFrame) -> tuple[float, float]:
    """Cochran-Armitage test: does delinquency rise or fall steadily across the ORDERED segments? One test, so no multiple-testing issue."""
    n = table["performing_loans"].to_numpy(float)
    x = table["delinquent_loans"].to_numpy(float)
    score = np.arange(len(n), dtype=float)
    total, pbar = n.sum(), x.sum() / n.sum()
    stat = float(np.sum(score * (x - n * pbar)))
    var = pbar * (1 - pbar) * (np.sum(n * score**2) - np.sum(n * score) ** 2 / total)
    if var <= 0:
        return float("nan"), float("nan")
    z = stat / math.sqrt(var)
    return z, math.erfc(abs(z) / math.sqrt(2))


def nps_score(scores: pd.Series) -> float:
    s = scores.dropna()
    return float("nan") if s.empty else 100 * ((s >= 9).mean() - (s <= 6).mean())


def nps_ci(scores: pd.Series, n_boot: int = 1000, seed: int = 7) -> tuple[float, float]:
    s = scores.dropna().to_numpy()
    if len(s) < 2:
        return float("nan"), float("nan")
    rng = np.random.default_rng(seed)
    draws = rng.choice(s, size=(n_boot, len(s)), replace=True)
    vals = 100 * ((draws >= 9).mean(axis=1) - (draws <= 6).mean(axis=1))
    return float(np.percentile(vals, 2.5)), float(np.percentile(vals, 97.5))


def fmt_p(p: float) -> str:
    return "< 0.0001" if p < 0.0001 else f"{p:.4f}"


def md_table(df: pd.DataFrame) -> str:
    cols = list(df.columns)
    lines = ["| " + " | ".join(cols) + " |", "|" + "|".join("---" for _ in cols) + "|"]
    for row in df.itertuples(index=False):
        lines.append("| " + " | ".join("" if (isinstance(v, float) and math.isnan(v)) else str(v) for v in row) + " |")
    return "\n".join(lines)


# ----------------------------------------------------------------------------
# 3A: portfolio health and the segment comparison
# ----------------------------------------------------------------------------
def demographics_era_start(fct: pd.DataFrame, threshold: float = COVERAGE_THRESHOLD) -> pd.Timestamp:
    """First sale quarter from which income coverage stays at or above the threshold (computed from the data)."""
    d = fct[fct["is_financed"]].copy()
    d["sale_q"] = pd.to_datetime(d["sale_date"]).dt.to_period("Q")
    cov = (d["avg_monthly_income_band"] != "Unknown").groupby(d["sale_q"]).mean().sort_index()
    ok = [q for q in cov.index if (cov.loc[q:] >= threshold).all()]
    if not ok:
        raise ValueError("No sale quarter reaches the demographic coverage threshold")
    return ok[0].start_time


def coverage_by_quarter(fct: pd.DataFrame) -> pd.DataFrame:
    d = fct[fct["is_financed"]].copy()
    d["sale_quarter"] = pd.to_datetime(d["sale_date"]).dt.to_period("Q").astype(str)
    g = d.groupby("sale_quarter")
    return pd.DataFrame({
        "financed_loans": g.size(),
        "with_income": g.apply(lambda x: f"{(x['avg_monthly_income_band'] != 'Unknown').mean():.1%}", include_groups=False),
        "with_age": g.apply(lambda x: f"{(x['age_band'] != 'Unknown').mean():.1%}", include_groups=False),
        "loss_rate": g.apply(lambda x: f"{x['is_loss_91plus'].mean():.1%}", include_groups=False),
    }).reset_index()


def segment_table(perf: pd.DataFrame, column: str, order: list[str]) -> pd.DataFrame:
    """Delinquency by segment on performing loans with a known value, each tested against all OTHER known loans."""
    known = perf[perf[column].isin(order)]
    total_k, total_n = known["is_delinquent_7plus"].sum(), len(known)
    rows = []
    for seg in order:
        s = known[known[column] == seg]
        k, n = int(s["is_delinquent_7plus"].sum()), len(s)
        lo, hi = wilson_ci(k, n)
        z, p = two_proportion_test(k, n, total_k - k, total_n - n)
        rows.append({"segment_type": column, "segment": seg, "performing_loans": n, "delinquent_loans": k,
                     "delinquency_rate": k / n if n else float("nan"), "ci_low": lo, "ci_high": hi,
                     "average_rate": total_k / total_n, "vs_average": (k / n) / (total_k / total_n) if n else float("nan"),
                     "z": z, "p_value": p})
    return pd.DataFrame(rows)


def pick_headline(table: pd.DataFrame) -> pd.Series | None:
    """The riskiest segment: highest ratio to the average among segments that are large enough (100+ performing loans)
    and significantly worse than all other known loans (p < 0.05)."""
    ok = table[(table["performing_loans"] >= MIN_PERFORMING_FOR_HEADLINE) & (table["p_value"] < 0.05) & (table["vs_average"] > 1)]
    return None if ok.empty else ok.loc[ok["vs_average"].idxmax()]


def low_vs_high_income(perf: pd.DataFrame) -> dict:
    """Gradient check: customers below 10,000 a month against customers on 100,000 or more."""
    low = perf[perf["avg_monthly_income_band"].isin(["Below 5,000", "5,000-9,999"])]
    high = perf[perf["avg_monthly_income_band"].isin(["100,000-149,999", "150,000+"])]
    k1, n1, k2, n2 = int(low["is_delinquent_7plus"].sum()), len(low), int(high["is_delinquent_7plus"].sum()), len(high)
    z, p = two_proportion_test(k1, n1, k2, n2)
    return {"low_rate": k1 / n1, "low_n": n1, "high_rate": k2 / n2, "high_n": n2, "z": z, "p_value": p}


def _plt():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    return plt


GREY, RED, GREEN = "#9AA5B1", "#D9534F", "#2E8B57"
INCOME_LABELS = {"Below 5,000": "Under 5,000", "5,000-9,999": "5,000 to 9,999", "10,000-19,999": "10,000 to 19,999",
                 "20,000-29,999": "20,000 to 29,999", "30,000-49,999": "30,000 to 49,999", "50,000-99,999": "50,000 to 99,999",
                 "100,000-149,999": "100,000 to 149,999", "150,000+": "150,000 or more"}
AGE_LABELS = {"18-25": "18 to 25", "26-35": "26 to 35", "36-45": "36 to 45", "46-55": "46 to 55", "56+": "56 and over"}
STATUS_GROUPS = [("Up to date", ["0"]), ("1 to 30 days late", ["1-7", "8-30"]),
                 ("31 to 90 days late", ["31-60", "61-90"]), ("Over 90 days late", ["91+"])]


def status_group(bucket: str) -> str | None:
    for label, buckets in STATUS_GROUPS:
        if bucket in buckets:
            return label
    return None


def chart_portfolio_trends(metrics: pd.DataFrame, path: Path) -> None:
    """Six panels, one colour each. Plain titles, an arrow-free 'lower/higher is better' hint, and axes that start at zero."""
    from matplotlib.ticker import FuncFormatter

    plt = _plt()
    m = metrics.copy()
    m["snapshot_date"] = pd.to_datetime(m["snapshot_date"])
    ticks = list(m["snapshot_date"])
    panels = [
        ("delinquency_rate_7plus", "Behind on payments", "8-90 days late. Lower is better", "#E67E22"),
        ("par30_rate", "Seriously behind", "31-90 days late. Lower is better", "#C0392B"),
        ("loss_rate_count", "Lost loans", "91+ days late, treated as lost. Lower is better", "#7D3C98"),
        ("collection_rate", "Money collected", "Share of money due that was paid. Higher is better", "#1E8449"),
        ("fpd_rate", "Never paid a first instalment", "Share of all loans. Lower is better", "#138D90"),
        ("retention_rate", "Healthy loans that stayed healthy", "Since the previous snapshot. Higher is better", "#1F3864"),
    ]
    fig, axes = plt.subplots(2, 3, figsize=(14, 7.6))
    for ax, (col, title, hint, color) in zip(axes.ravel(), panels):
        y = m[col] * 100
        ax.plot(m["snapshot_date"], y, marker="o", color=color, linewidth=3, markersize=8)
        for x, v in zip(m["snapshot_date"], y):
            if pd.notna(v):
                ax.annotate(f"{v:.1f}%", (x, v), textcoords="offset points", xytext=(0, 10), ha="center", fontsize=9, color=color, fontweight="bold")
        top = float(y.max())
        ax.set_ylim(0, 105 if top > 50 else top * 1.35)
        ax.margins(x=0.1)
        ax.set_xticks(ticks)
        ax.set_xticklabels([d.strftime("%b") for d in ticks])
        ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:.0f}%"))
        ax.set_title(title, fontsize=12, fontweight="bold", color=color, loc="left", pad=24)
        ax.text(0, 1.03, hint, transform=ax.transAxes, fontsize=8.5, color="#555555")
        ax.grid(axis="y", alpha=0.25)
        ax.spines[["top", "right"]].set_visible(False)
    fig.suptitle("How the loan portfolio performed across 2025 (financed loans, five snapshots)", fontsize=14, fontweight="bold")
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    fig.savefig(path, dpi=150)
    plt.close(fig)


def _risk_bar_chart(table: pd.DataFrame, labels: dict[str, str], title: str, footnote: str, path: Path, few: int = 100) -> None:
    """Horizontal bars: out of every 100 customers, how many are behind on payments."""
    from matplotlib.patches import Patch

    plt = _plt()
    avg = float(table["average_rate"].iloc[0]) * 100
    rates = table["delinquency_rate"] * 100
    colors = [RED if r > avg + 1 else GREEN if r < avg - 1 else GREY for r in rates]
    names = [labels.get(r.segment, r.segment) + (f"  ({r.performing_loans:,} loans" + (", few" if r.performing_loans < few else "") + ")") for r in table.itertuples()]
    fig, ax = plt.subplots(figsize=(10.5, 0.62 * len(table) + 2.6))
    pos = np.arange(len(table))
    ax.barh(pos, rates, color=colors, height=0.66)
    for i, v in enumerate(rates):
        ax.text(v - 0.4, i, f"{v:.0f}", va="center", ha="right", fontsize=13, fontweight="bold", color="white")
    ax.axvline(avg, color="black", linestyle="--", linewidth=1.2)
    ax.text(avg + 0.3, len(table) - 0.42, f"Average: {avg:.0f} in 100", fontsize=9, va="center")
    ax.set_ylim(len(table) - 0.2, -0.6)
    ax.set_yticks(pos)
    ax.set_yticklabels(names, fontsize=10)
    ax.set_xlim(0, max(rates.max() * 1.08, avg * 1.4))
    ax.set_xlabel("Out of every 100 customers, how many are behind on payments (8-90 days late)", fontsize=10)
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(handles=[Patch(color=RED, label="More behind than average"), Patch(color=GREY, label="About average"),
                       Patch(color=GREEN, label="Fewer behind than average")], loc="upper center", bbox_to_anchor=(0.45, -0.16),
              ncol=3, frameon=False, fontsize=9)
    ax.set_title(title, fontsize=13, fontweight="bold", loc="left", pad=14)
    fig.text(0.01, 0.01, footnote, fontsize=8, color="#555555")
    fig.tight_layout(rect=(0, 0.05, 1, 1))
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)


def chart_income_risk(income: pd.DataFrame, trend: tuple[float, float], era: pd.Timestamp, path: Path) -> None:
    falling = trend[0] < 0 and trend[1] < 0.05
    title = "Customers with lower incomes fall behind on payments more often" if falling else "Customers behind on payments, by monthly income"
    foot = (f"December 2025, loans sold since {era:%b %Y}. Income is average money received per month, in KES. "
            "Groups with few loans are less certain. Shows a pattern, not a cause.")
    _risk_bar_chart(income, INCOME_LABELS, title, foot, path)


def chart_age_risk(age: pd.DataFrame, era: pd.Timestamp, path: Path) -> None:
    foot = f"December 2025, loans sold since {era:%b %Y}. Groups with few loans are less certain. Shows a pattern, not a cause."
    _risk_bar_chart(age, AGE_LABELS, "Customers behind on payments, by age", foot, path)


# ----------------------------------------------------------------------------
# 3B: credit outcomes and NPS
# ----------------------------------------------------------------------------
def nps_by(df: pd.DataFrame, column: str, order: list[str] | None = None) -> pd.DataFrame:
    rows = []
    for key, g in df.groupby(column):
        lo, hi = nps_ci(g["nps_score"])
        rows.append({column: key, "responses": len(g), "mean_score": round(g["nps_score"].mean(), 2),
                     "nps": round(nps_score(g["nps_score"]), 1), "ci_low": round(lo, 1), "ci_high": round(hi, 1)})
    out = pd.DataFrame(rows)
    if order and not out.empty:
        labels = out[column].astype(str)
        ranking = {k: i for i, k in enumerate(order + [k for k in labels.unique() if k not in order])}
        out = out.assign(**{column: labels}).sort_values(column, key=lambda c: c.map(ranking))
    return out.reset_index(drop=True)


def nps_sample(nps: pd.DataFrame) -> pd.DataFrame:
    """Latest scored response per loan, financed loans, with a credit state at the matched snapshot."""
    s = nps[nps["is_latest_response"].astype(bool) & nps["nps_score"].notna() & (nps["portfolio_scope"] == "financed")]
    return s.copy()


def driver_table(sample: pd.DataFrame) -> pd.DataFrame:
    """NPS for customers who did and did not report each experience, for current and late customers."""
    rows = []
    s = sample.assign(group=np.where(sample["dpd_bucket"] == "0", "current", "1+ days late"))
    for col, label in (("assistance_difficulty", "Had difficulty getting customer care help"),
                       ("phone_lock_experienced", "Phone was locked"), ("payment_delay_experienced", "Experienced a payment delay")):
        t = s[s[col].isin(["Yes", "No"])]
        for grp, g in list(t.groupby("group")) + [("all", t)]:
            for ans in ("Yes", "No"):
                x = g[g[col] == ans]
                rows.append({"experience": label, "customers": grp, "answer": ans, "responses": len(x), "nps": round(nps_score(x["nps_score"]), 1)})
    return pd.DataFrame(rows)


def chart_nps_by_status(sample: pd.DataFrame, path: Path) -> None:
    """Average survey rating (0-10) by how late the customer was when they answered."""
    plt = _plt()
    g = sample.assign(group=sample["dpd_bucket"].map(status_group))
    rows = [(label, g.loc[g["group"] == label, "nps_score"].mean(), int((g["group"] == label).sum())) for label, _ in STATUS_GROUPS]
    labels, means, ns = zip(*rows)
    colors = ["#2E8B57", "#E0A800", "#E67E22", "#C0392B"]
    fig, ax = plt.subplots(figsize=(10, 5.8))
    ax.bar(labels, means, color=colors, width=0.62)
    for i, (v, n) in enumerate(zip(means, ns)):
        ax.text(i, v + 0.15, f"{v:.1f}", ha="center", fontsize=14, fontweight="bold")
        ax.text(i, 0.25, f"{n:,} customers", ha="center", fontsize=9, color="white")
    ax.set_ylim(0, 10)
    ax.set_ylabel("Average rating out of 10", fontsize=10)
    ax.spines[["top", "right"]].set_visible(False)
    far = means[0] - means[-1]
    title = "Customers who are far behind on payments rate ABC Phones much lower" if far >= 1 else "Customer rating by payment status"
    ax.set_title(title, fontsize=13, fontweight="bold", loc="left", pad=26)
    ax.text(0, 1.02, "Survey question: how likely are you to recommend ABC Phones? (0 = not at all, 10 = definitely)", transform=ax.transAxes, fontsize=9, color="#555555")
    fig.text(0.01, 0.01, "Customers with a financed loan, grouped by how late they were when they answered. Shows a link, not a cause.", fontsize=8, color="#555555")
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    fig.savefig(path, dpi=150)
    plt.close(fig)


EXPERIENCES = [("assistance_difficulty", "Getting help from\ncustomer care", "Trouble getting help from customer care"),
               ("phone_lock_experienced", "Phone was locked", "Having the phone locked"),
               ("payment_delay_experienced", "A payment delay", "A payment delay")]


def chart_nps_experience(sample: pd.DataFrame, path: Path) -> None:
    """Average rating of customers who did and did not report each experience."""
    plt = _plt()
    stats = []
    for col, label, phrase in EXPERIENCES:
        yes, no = sample.loc[sample[col] == "Yes", "nps_score"], sample.loc[sample[col] == "No", "nps_score"]
        stats.append((label, phrase, no.mean(), len(no), yes.mean(), len(yes)))
    fig, ax = plt.subplots(figsize=(10, 5.8))
    x = np.arange(len(stats))
    ax.bar(x - 0.19, [s[2] for s in stats], width=0.36, color="#2E8B57", label="No problem")
    ax.bar(x + 0.19, [s[4] for s in stats], width=0.36, color="#C0392B", label="Had this problem")
    for i, (_, _, m_no, n_no, m_yes, n_yes) in enumerate(stats):
        ax.text(i - 0.19, m_no + 0.15, f"{m_no:.1f}", ha="center", fontsize=13, fontweight="bold")
        ax.text(i + 0.19, m_yes + 0.15, f"{m_yes:.1f}", ha="center", fontsize=13, fontweight="bold")
        ax.text(i - 0.19, 0.25, f"{n_no:,}", ha="center", fontsize=9, color="white")
        ax.text(i + 0.19, 0.25, f"{n_yes:,}", ha="center", fontsize=9, color="white")
    ax.set_xticks(x)
    ax.set_xticklabels([s[0] for s in stats], fontsize=11)
    ax.set_ylim(0, 10)
    ax.set_ylabel("Average rating out of 10", fontsize=10)
    ax.legend(frameon=False, loc="upper right")
    ax.spines[["top", "right"]].set_visible(False)
    biggest = max(stats, key=lambda s: s[2] - s[4])
    ax.set_title(f"{biggest[1]} goes with the biggest drop in ratings", fontsize=13, fontweight="bold", loc="left", pad=26)
    ax.text(0, 1.02, "Average rating out of 10 for customers who did and did not report each experience (numbers inside bars = customers)", transform=ax.transAxes, fontsize=9, color="#555555")
    fig.text(0.01, 0.01, "Survey answers from customers with a financed loan. Shows a link, not a cause.", fontsize=8, color="#555555")
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    fig.savefig(path, dpi=150)
    plt.close(fig)


# ----------------------------------------------------------------------------
# Orchestration
# ----------------------------------------------------------------------------
def analyse(metrics: pd.DataFrame, fct_latest: pd.DataFrame, nps: pd.DataFrame, out_dir: Path) -> dict:
    charts = out_dir / "charts"
    charts.mkdir(parents=True, exist_ok=True)
    md: list[str] = ["# Analysis findings", "", "Generated by scripts/analysis.py. Every number below feeds a slide.", ""]

    # --- 3A ---------------------------------------------------------------
    md += ["## 3A Portfolio health", "", md_table(metrics[["snapshot_date", "financed_loans", "delinquency_rate_7plus", "par30_rate",
                                                         "loss_rate_count", "collection_rate", "fpd_rate", "retention_rate"]].round(4)), ""]
    chart_portfolio_trends(metrics, charts / "portfolio_trends.png")

    era = demographics_era_start(fct_latest)
    md += ["### Why segments use recent loans only", "",
           f"Demographics exist only for loans sold from late 2024. Segment tests use loans sold since {era:%Y-%m-%d}, the first quarter "
           f"where income coverage stays at or above {COVERAGE_THRESHOLD:.0%}.", "", md_table(coverage_by_quarter(fct_latest)), ""]
    perf = fct_latest[fct_latest["is_performing"] & (pd.to_datetime(fct_latest["sale_date"]) >= era)]
    income = segment_table(perf, "avg_monthly_income_band", INCOME_ORDER)
    age = segment_table(perf, "age_band", AGE_ORDER)
    seg = pd.concat([income, age], ignore_index=True)
    seg["p_bonferroni"] = (seg["p_value"] * len(seg)).clip(upper=1.0)
    seg.to_csv(out_dir / "segment_analysis.csv", index=False)
    trend_z, trend_p = trend_test(income)
    headline = pick_headline(seg)
    fmt = seg.assign(**{c: seg[c].map(lambda v: f"{v:.1%}") for c in ("delinquency_rate", "ci_low", "ci_high", "average_rate")},
                     vs_average=seg["vs_average"].round(2), z=seg["z"].round(2), p_value=seg["p_value"].map(lambda v: f"{v:.4f}"),
                     p_bonferroni=seg["p_bonferroni"].map(lambda v: f"{v:.3f}"))
    md += ["### Delinquency by segment (December 2025, performing loans sold since the era start)", "", md_table(fmt), ""]
    if headline is not None:
        md += [f"**Headline segment:** {headline['segment_type']} = {headline['segment']}: delinquency {headline['delinquency_rate']:.1%} "
               f"({headline['delinquent_loans']:.0f} of {headline['performing_loans']:.0f}) against an average of {headline['average_rate']:.1%} "
               f"({headline['vs_average']:.2f}x), p = {fmt_p(headline['p_value'])}.", ""]
        adj = float(seg.loc[(seg["segment_type"] == headline["segment_type"]) & (seg["segment"] == headline["segment"]), "p_bonferroni"].iloc[0])
        if adj >= 0.05:
            md += [f"**Caution:** {len(seg)} segments were tested. After correcting for that (Bonferroni) this band on its own is not significant "
                   f"(adjusted p = {adj:.3f}) because only {headline['performing_loans']:.0f} loans are in it. The robust finding is the income "
                   "gradient below, which is a single test.", ""]
    md += [f"**Trend across the eight income bands:** delinquency {'falls' if trend_z < 0 else 'rises'} steadily as income rises (trend z = {trend_z:.2f}, p {fmt_p(trend_p) if trend_p < 0.0001 else '= ' + fmt_p(trend_p)}).", ""]
    gap = low_vs_high_income(perf)
    md += [f"**Income gradient:** customers below 10,000 a month are {gap['low_rate']:.1%} delinquent ({gap['low_n']} performing loans) against "
           f"{gap['high_rate']:.1%} for customers on 100,000 or more ({gap['high_n']}), z = {gap['z']:.2f}, p {fmt_p(gap['p_value']).replace('<', '<') if gap['p_value'] < 0.0001 else '= ' + fmt_p(gap['p_value'])}.", ""]
    chart_income_risk(income, (trend_z, trend_p), era, charts / "segment_risk.png")
    chart_age_risk(age, era, charts / "segment_risk_age.png")

    # --- 3B ---------------------------------------------------------------
    sample = nps_sample(nps)
    by_dpd = nps_by(sample, "dpd_bucket", DPD_ORDER)
    by_risk = nps_by(sample, "risk_category", RISK_ORDER)
    drivers = driver_table(sample)
    latest_view = nps[nps["is_latest_response"].astype(bool) & nps["nps_score"].notna() & nps["risk_category_latest"].isin(RISK_ORDER)]
    by_latest = nps_by(latest_view, "risk_category_latest", RISK_ORDER)
    latest_all = nps[nps["is_latest_response"].astype(bool)]
    scored = latest_all[latest_all["nps_score"].notna()]
    n_unscored = len(latest_all) - len(scored)
    n_other_scope = int((scored["portfolio_scope"].notna() & (scored["portfolio_scope"] != "financed")).sum())
    n_no_state = int(scored["portfolio_scope"].isna().sum())
    md += ["## 3B Credit outcomes and customer experience", "",
           f"Sample: {len(sample):,} responses. Of {len(latest_all):,} latest responses (one per loan), {n_unscored:,} have no score, "
           f"{n_other_scope:,} are cash or other non-financed sales, and {n_no_state:,} were answered before the loan appeared in a snapshot "
           "(sold after the matched snapshot), so they have no credit state at that time.", "",
           "### NPS by days past due at the time of the response", "", md_table(by_dpd), "",
           "### NPS by risk category at the time of the response", "", md_table(by_risk), "",
           "### Sensitivity: NPS by risk category at the LATEST snapshot (financed loans, includes loans sold after the response date)", "", md_table(by_latest), "",
           "### Experience drivers", "", md_table(drivers), ""]
    A = sample[sample["assistance_difficulty"].isin(["Yes", "No"])].assign(difficulty=lambda d: d["assistance_difficulty"].eq("Yes"))
    share = A.groupby("dpd_bucket")["difficulty"].agg(responses="size", reported_difficulty="mean").reindex(DPD_ORDER).dropna().reset_index()
    share["reported_difficulty"] = share["reported_difficulty"].map(lambda v: f"{v:.1%}")
    md += ["### Share reporting difficulty getting customer care help, by days past due", "", md_table(share), ""]
    early = sample[sample["dpd_bucket"].isin(["1-7", "8-30", "31-60"]) & sample["assistance_difficulty"].isin(["Yes", "No"])]
    outcome = early.assign(critical_later=early["risk_category_latest"].eq("Critical")).groupby("assistance_difficulty")["critical_later"] \
        .agg(responses="size", share_critical_at_latest="mean").reset_index()
    outcome["share_critical_at_latest"] = outcome["share_critical_at_latest"].map(lambda v: f"{v:.1%}")
    md += ["### Outcome check: customers 1-60 days late when they answered, share Critical at the latest snapshot", "", md_table(outcome), "",
           "Small samples. This is directional only and is not evidence of cause.", ""]
    chart_nps_by_status(sample, charts / "nps_credit.png")
    chart_nps_experience(sample, charts / "nps_experience.png")

    (out_dir / "analysis_findings.md").write_text("\n".join(md), encoding="utf-8")
    return {"headline": headline, "gap": gap, "trend": (trend_z, trend_p), "by_dpd": by_dpd, "drivers": drivers, "income": income, "age": age, "era": era}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", type=Path, default=ROOT / "config" / "settings.yaml")
    ap.add_argument("--out-dir", type=Path, default=ROOT / "outputs")
    ap.add_argument("--log-dir", type=Path, default=ROOT / "logs")
    args = ap.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    args.log_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.FileHandler(args.log_dir / "analysis.log"), logging.StreamHandler(sys.stderr)])
    cfg = yaml.safe_load(args.config.read_text())
    project, location = cfg["gcp"]["project_id"], cfg["bigquery"]["location"]
    marts = f"`{project}.{cfg['bigquery']['dataset_marts']}`"

    from google.cloud import bigquery

    client = bigquery.Client(project=project, location=location)

    def read(sql: str) -> pd.DataFrame:
        return client.query(sql).to_dataframe(create_bqstorage_client=False)

    metrics = read(f"SELECT * FROM {marts}.mart_portfolio_metrics ORDER BY snapshot_date")
    fct = read(f"""SELECT loan_key, is_financed, is_performing, is_delinquent_7plus, is_loss_91plus, age_band, avg_monthly_income_band, sale_date
                   FROM {marts}.fct_loan_snapshot
                   WHERE snapshot_date = (SELECT MAX(snapshot_date) FROM {marts}.fct_loan_snapshot) AND is_financed""")
    nps = read(f"SELECT * FROM {marts}.mart_nps_credit")
    for col in ("is_financed", "is_performing", "is_delinquent_7plus", "is_loss_91plus"):
        fct[col] = fct[col].fillna(False).astype(bool)
    fct["sale_date"] = pd.to_datetime(fct["sale_date"])

    result = analyse(metrics, fct, nps, args.out_dir)
    h = result["headline"]
    print(f"\nCharts saved in {args.out_dir / 'charts'}; all numbers in {args.out_dir / 'analysis_findings.md'}")
    if h is not None:
        print(f"Headline segment: {h['segment_type']} = {h['segment']}, delinquency {h['delinquency_rate']:.1%} vs average {h['average_rate']:.1%} ({h['vs_average']:.2f}x)")
    print("\nNPS by days past due:\n" + result["by_dpd"].to_string(index=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())