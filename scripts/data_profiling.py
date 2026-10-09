#!/usr/bin/env python3
"""data_profiling.py

Profile the ABC Phones source data: five credit snapshot CSVs, the Sales and
Customer workbook, the NPS survey workbook and the credit data definitions.

Run from the project root:
    uv run python scripts/data_profiling.py
    uv run python scripts/data_profiling.py --raw-dir data/raw --out-dir outputs/profiling

What it does (raw files are only ever read, never modified):
  1. Streams each xlsx sheet, stops at the blank padding rows, and caches the
     sheet as a CSV in data/interim so later steps and re-runs are fast.
  2. Profiles every column: null %, null-like tokens, uniqueness, number and
     date format problems, top value patterns.
  3. Runs dataset checks: schema drift, snapshot date vs filename, logical rules.
  4. Analyses join keys across datasets: coverage, cardinality, orphans.
  5. Writes a markdown report plus one CSV profile per table.

PII safety: the report never prints raw values for identifier, name, date of
birth or free-text columns. Free text is only counted for phone/email patterns.
It is safe to paste the report into a chat.
"""
from __future__ import annotations

import argparse
import logging
import re
import sys
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pandas as pd
from openpyxl import load_workbook

from utils.logging_setup import setup_logging
from utils.masking import EMAIL_RE, PHONE_RE

ROOT = Path(__file__).resolve().parents[1]
LOG = logging.getLogger("data_profiling")

NULL_TOKENS = {"", "na", "n/a", "nan", "null", "none", "nil", "-", "--", "#n/a", "#value!", "#ref!"}
SENSITIVE_COL = re.compile(
    r"loan.?id|sale_id|^_id$|^seller$|birth|dob|respondent|submission|reason|one thing|describe|feedback|comment|anything",
    re.I,
)
FREE_TEXT_COL = re.compile(r"reason|one thing|describe|feedback|anything|comment", re.I)
DATE_LIKE = r"^\d{4}-\d{2}-\d{2}|^\d{1,2}/\d{1,2}/\d{2,4}"
INCOME_BINS = [0, 5_000, 10_000, 20_000, 30_000, 50_000, 100_000, 150_000, np.inf]
INCOME_LABELS = ["<5k", "5k-9.9k", "10k-19.9k", "20k-29.9k", "30k-49.9k", "50k-99.9k", "100k-149.9k", "150k+"]
AGE_BINS = [-1, 18, 26, 36, 46, 56, 121, 1000]
AGE_LABELS = ["<18", "18-25", "26-35", "36-45", "46-55", "56-120", ">120"]


# ----------------------------------------------------------------------------
# Small helpers
# ----------------------------------------------------------------------------
class Report:
    """Collects markdown lines so the same text is printed and saved."""

    def __init__(self) -> None:
        self.lines: list[str] = []

    def add(self, text: str = "") -> None:
        self.lines.append(text)

    def h(self, level: int, text: str) -> None:
        self.add(f"\n{'#' * level} {text}\n")

    def block(self, content) -> None:
        if isinstance(content, pd.DataFrame):
            content = content.to_string(index=False, max_colwidth=110)
        self.add("```\n" + str(content) + "\n```")

    def text(self) -> str:
        return "\n".join(self.lines)


def num(s: pd.Series) -> pd.Series:
    """Parse strings to numbers, tolerating commas, spaces and currency tags."""
    cleaned = s.astype(str).str.replace(r"(?i)kes|ksh|\$|,|\s", "", regex=True)
    return pd.to_numeric(cleaned, errors="coerce")


def clean_key(s: pd.Series) -> pd.Series:
    """Stripped key with null-like tokens (blank, #N/A, null...) turned into empty strings."""
    st = s.astype(str).str.strip()
    return st.mask(st.str.lower().isin(NULL_TOKENS), "")


def find_col(df: pd.DataFrame, *keywords: str) -> str | None:
    for col in df.columns:
        if all(k.lower() in col.lower() for k in keywords):
            return col
    return None


def pattern_sig(value: str) -> str:
    """Shape of a value (letters -> A, digits -> 9) so formats can be compared without showing data."""
    value = re.sub(r"[A-Za-z]+", "A", value.strip()[:40])
    return re.sub(r"\d", "9", value)


def to_date(s: pd.Series) -> tuple[pd.Series, str]:
    """Parse ISO and slash dates. Slash layout (D/M/Y or M/D/Y) is inferred from the data itself.

    Returns the parsed series and a one-line note describing formats found.
    """
    st = s.astype(str).str.strip()
    out = pd.Series(pd.NaT, index=st.index, dtype="datetime64[ns]")
    iso = st.str.match(r"^\d{4}-\d{2}-\d{2}")
    if iso.any():
        out[iso] = pd.to_datetime(st[iso].str[:10], format="%Y-%m-%d", errors="coerce")
    slash = st.str.match(r"^\d{1,2}/\d{1,2}/\d{4}")
    layout = "n/a"
    if slash.any():
        parts = st[slash].str.extract(r"^(\d{1,2})/(\d{1,2})/(\d{4})").astype(int)
        first_gt12, second_gt12 = int((parts[0] > 12).sum()), int((parts[1] > 12).sum())
        dayfirst = first_gt12 > 0 and second_gt12 == 0
        if first_gt12 and second_gt12:
            layout = "MIXED D/M and M/D"
        elif dayfirst:
            layout = "D/M/Y"
        elif second_gt12:
            layout = "M/D/Y"
        else:
            layout = "ambiguous (assumed M/D/Y)"
        fmt = "%d/%m/%Y" if dayfirst else "%m/%d/%Y"
        out[slash] = pd.to_datetime(
            st[slash].str.extract(r"^(\d{1,2}/\d{1,2}/\d{4})")[0], format=fmt, errors="coerce"
        )
    unparsed = int(((st != "") & out.isna()).sum())
    note = f"ISO {int(iso.sum())} | slash {int(slash.sum())} [{layout}] | unparsed {unparsed}"
    return out, note


def age_years(dob: pd.Series, ref: pd.Timestamp) -> pd.Series:
    birthday_pending = (dob.dt.month > ref.month) | ((dob.dt.month == ref.month) & (dob.dt.day > ref.day))
    return ref.year - dob.dt.year - birthday_pending.astype(int)


def section(rep: Report, title: str, fn, *args) -> None:
    """Run one report section; a failure is logged and reported but never stops the run."""
    rep.h(2, title)
    try:
        fn(rep, *args)
    except Exception as exc:  # noqa: BLE001 - keep profiling the remaining sections
        LOG.exception("Section failed: %s", title)
        rep.add(f"SECTION FAILED: {type(exc).__name__}: {exc}")


# ----------------------------------------------------------------------------
# Loading
# ----------------------------------------------------------------------------
def _cell_to_str(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float):
        return str(int(v)) if v.is_integer() else repr(v)
    if isinstance(v, datetime):
        return v.isoformat(sep=" ")
    if isinstance(v, date):
        return v.isoformat()
    return str(v)


def read_xlsx(path: Path, interim_dir: Path, refresh: bool = False, max_blank_run: int = 500) -> dict[str, pd.DataFrame]:
    """Stream every sheet as strings. Stops after a run of blank rows (Excel padding) and caches to CSV."""
    interim_dir.mkdir(parents=True, exist_ok=True)
    sheets: dict[str, pd.DataFrame] = {}
    wb = load_workbook(path, read_only=True, data_only=True)
    for ws in wb.worksheets:
        safe = re.sub(r"\W+", "_", f"{path.stem}__{ws.title}")
        cache = interim_dir / f"{safe}.csv"
        if cache.exists() and not refresh:
            LOG.info("Using cached %s", cache.name)
            sheets[ws.title] = pd.read_csv(cache, dtype=str, keep_default_na=False)
            continue
        LOG.info("Streaming sheet '%s' from %s", ws.title, path.name)
        rows_iter = ws.iter_rows(values_only=True)
        header = [str(h).strip() if h is not None else f"unnamed_{i}" for i, h in enumerate(next(rows_iter))]
        width, rows, blank_run = len(header), [], 0
        for raw in rows_iter:
            vals = [_cell_to_str(v) for v in raw]
            if all(v.strip().lower() in NULL_TOKENS for v in vals):
                blank_run += 1
                if blank_run >= max_blank_run:
                    break
                continue
            blank_run = 0
            rows.append((vals + [""] * width)[:width])
        df = pd.DataFrame(rows, columns=header)
        empty_unnamed = [c for c in df.columns if c.startswith("unnamed_") and (df[c].str.strip() == "").all()]
        df = df.drop(columns=empty_unnamed)
        df.to_csv(cache, index=False)
        sheets[ws.title] = df
    wb.close()
    return sheets


def probe_formulas(path: Path, sheet: str, n_rows: int = 5) -> dict[str, str]:
    """Look at the first rows WITHOUT cached values to see whether a column is a formula."""
    wb = load_workbook(path, read_only=True, data_only=False)
    rows = list(wb[sheet].iter_rows(min_row=1, max_row=n_rows + 1, values_only=True))
    wb.close()
    found: dict[str, str] = {}
    for j, head in enumerate(rows[0]):
        for r in rows[1:]:
            if j < len(r) and isinstance(r[j], str) and r[j].startswith("="):
                found[str(head)] = r[j][:90]
                break
    return found


def load_credit(files: list[Path]) -> pd.DataFrame:
    frames = []
    for f in files:
        df = pd.read_csv(f, dtype=str, keep_default_na=False, low_memory=False)
        df.columns = [c.strip() for c in df.columns]
        m = re.search(r"(\d{2})-(\d{2})-(\d{4})", f.name)
        df["_file_date"] = f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else f.stem
        df["_file"] = f.name
        frames.append(df)
    return pd.concat(frames, ignore_index=True).fillna("")


def find_files(raw_dir: Path):
    files = [p for p in raw_dir.rglob("*") if p.is_file() and not p.name.startswith("~$")]
    credit = sorted(
        (p for p in files if p.suffix.lower() == ".csv" and "credit" in p.name.lower()),
        key=lambda p: re.sub(r"(\d{2})-(\d{2})-(\d{4})", r"\3\2\1", p.name),
    )

    def pick(keyword: str) -> Path | None:
        hits = [p for p in files if p.suffix.lower() == ".xlsx" and keyword in p.name.lower()]
        return hits[0] if hits else None

    return credit, pick("sales"), pick("nps"), pick("definition")


# ----------------------------------------------------------------------------
# Column profiling
# ----------------------------------------------------------------------------
def profile_table(df: pd.DataFrame, skip: tuple[str, ...] = ()) -> pd.DataFrame:
    """One row per column: kind, null %, null-like tokens, uniqueness and a PII-safe detail string."""
    rows = []
    for col in df.columns:
        if col in skip:
            continue
        st = df[col].astype(str).str.strip()
        is_null = st.eq("")
        nn = st[~is_null]
        n_nn = len(nn)
        null_like = int((st.str.lower().isin(NULL_TOKENS) & ~is_null).sum())
        plain = pd.to_numeric(nn, errors="coerce").notna().mean() if n_nn else 0.0
        cleaned = num(nn)
        clean_share = cleaned.notna().mean() if n_nn else 0.0
        date_share = nn.str.match(DATE_LIKE).mean() if n_nn else 0.0
        uniq = int(nn.nunique())
        sensitive = bool(SENSITIVE_COL.search(col))

        if n_nn == 0:
            kind, detail = "empty", ""
        elif date_share >= 0.8:
            kind, detail = "date", to_date(nn)[1]
        elif clean_share >= 0.95:
            kind = "numeric"
            detail = f"min {cleaned.min():,.2f} | max {cleaned.max():,.2f} | mean {cleaned.mean():,.2f} | neg {int((cleaned < 0).sum())}"
            if clean_share - plain > 0.01:
                detail += f" | FORMATTED numbers in {clean_share - plain:.1%} of rows"
        elif sensitive:
            kind, detail = ("categorical" if uniq <= 25 else "text/id"), "(values hidden: identifier, PII or free text)"
        elif uniq <= 25:
            kind = "categorical"
            top = nn.value_counts().head(8)
            detail = "; ".join(f"{str(k)[:30]}={v}" for k, v in top.items())
            if nn.str.lower().nunique() < uniq:
                detail += " | CASE/SPACING VARIANTS"
        else:
            kind = "text/id"
            pats = nn.map(pattern_sig).value_counts(normalize=True).head(3)
            detail = "patterns: " + "; ".join(f"{k} {v:.0%}" for k, v in pats.items())

        rows.append(
            {
                "column": col[:45],
                "kind": kind,
                "null_pct": round(100 * is_null.mean(), 2),
                "null_like": null_like,
                "unique": uniq,
                "ws_issue": int((df[col].astype(str) != st).sum()),
                "detail": detail,
            }
        )
    return pd.DataFrame(rows)


# ----------------------------------------------------------------------------
# Credit snapshot checks
# ----------------------------------------------------------------------------
def credit_overview(rep: Report, cred: pd.DataFrame, defs: pd.DataFrame | None) -> None:
    data_cols = [c for c in cred.columns if not c.startswith("_")]
    union = list(dict.fromkeys(data_cols))

    rows = []
    for fdate, g in cred.groupby("_file_date"):
        parsed, _ = to_date(g["DATE"])
        vals = sorted(parsed.dropna().dt.strftime("%Y-%m-%d").unique())
        file_cols = [c for c in g.columns if not c.startswith("_") and (g[c] != "").any() or c in ("LOAN_ID", "DATE")]
        rows.append(
            {
                "file_date": fdate,
                "rows": len(g),
                "unique_loans": g["LOAN_ID"].nunique(),
                "dup_loan_date_rows": int(g.duplicated(["LOAN_ID", "DATE"]).sum()),
                "DATE_values": ",".join(vals[:3]) + ("..." if len(vals) > 3 else ""),
                "DATE_matches_filename": len(vals) == 1 and vals[0] == fdate,
                "populated_cols": len(file_cols),
            }
        )
    rep.add("Per snapshot file:")
    rep.block(pd.DataFrame(rows))

    rep.add("Schema drift (columns that are entirely empty in a snapshot, or unnamed):")
    drift = []
    for fdate, g in cred.groupby("_file_date"):
        empty = [c for c in union if (g[c].str.strip() == "").all()]
        drift.append({"file_date": fdate, "all_empty_columns": ", ".join(empty) or "-"})
    unnamed = [c for c in union if c.lower().startswith("unnamed")]
    rep.block(pd.DataFrame(drift))
    rep.add(f"Unnamed columns found: {unnamed or 'none'}")

    if defs is not None and "Column Name" in defs.columns:
        defined = {c.strip() for c in defs["Column Name"] if c.strip()}
        rep.add(f"In data but not defined: {sorted(set(union) - defined) or 'none'}")
        rep.add(f"Defined but not in data: {sorted(defined - set(union)) or 'none'}")

    rep.add("\nLoan persistence between consecutive snapshots:")
    order = sorted(cred["_file_date"].unique())
    seen: set[str] = set()
    prev: set[str] = set()
    pers = []
    for fdate in order:
        ids = set(cred.loc[cred["_file_date"] == fdate, "LOAN_ID"])
        pers.append(
            {
                "snapshot": fdate,
                "loans": len(ids),
                "new_vs_previous": len(ids - prev) if prev else "-",
                "dropped_vs_previous": len(prev - ids) if prev else "-",
                "returning_after_gap": len((ids - prev) & seen) if prev else "-",
            }
        )
        seen |= ids
        prev = ids
    rep.block(pd.DataFrame(pers))


def credit_logic_checks(rep: Report, cred: pd.DataFrame) -> None:
    c = cred
    snap, _ = to_date(c["DATE"])
    sale, _ = to_date(c["SALE_DATE"])
    ret, _ = to_date(c["RETURN_DATE"])
    maxpay, _ = to_date(c["MAX_PAYMENT_DATE"])
    age, arrears, dpd = num(c["CUSTOMER_AGE"]), num(c["ARREARS"]), num(c["DAYS_PAST_DUE"])
    bdtd = num(c["BALANCE_DUE_TO_DATE"])
    days_since_sale = (snap - sale).dt.days
    valid_age = age.notna() & days_since_sale.notna()

    checks = {
        "SALE_DATE after snapshot DATE": sale > snap,
        "MAX_PAYMENT_DATE after snapshot DATE": maxpay > snap,
        "RETURN_DATE before SALE_DATE": ret < sale,
        "RETURN_DATE after snapshot DATE": ret > snap,
        "CUSTOMER_AGE != days since SALE_DATE": valid_age & (age != days_since_sale),
        "ARREARS > 0 but DAYS_PAST_DUE = 0": (arrears > 0) & (dpd == 0),
        "ARREARS = 0 but DAYS_PAST_DUE > 0": (arrears == 0) & (dpd > 0),
        "ARREARS != -BALANCE_DUE_TO_DATE (when negative)": (bdtd < 0) & (arrears != -bdtd),
        "BALANCE < 0": num(c["BALANCE"]) < 0,
        "CLOSING_BALANCE < 0": num(c["CLOSING_BALANCE"]) < 0,
        "TOTAL_PAID < 0": num(c["TOTAL_PAID"]) < 0,
        "DAYS_PAST_DUE < 0": dpd < 0,
        "LOAN_ID blank": c["LOAN_ID"].str.strip() == "",
    }
    table = pd.DataFrame({name: m.groupby(c["_file_date"]).sum() for name, m in checks.items()}).T
    table["ALL"] = table.sum(axis=1)
    table.insert(0, "check", table.index)
    rep.add("Rule violations (row counts per snapshot):")
    rep.block(table.reset_index(drop=True))

    gap = (age - days_since_sale)[valid_age]
    if len(gap):
        rep.add(f"CUSTOMER_AGE minus days since sale: median {gap.median():.0f}, min {gap.min():.0f}, max {gap.max():.0f} days")

    for col in ("ACCOUNT_STATUS_L1", "ACCOUNT_STATUS_L2", "BALANCE_DUE_STATUS", "CREDIT_CHECK_DONE"):
        if col in c.columns:
            rep.add(f"\n{col} by snapshot (top 30 values):")
            ct = pd.crosstab(c[col].replace("", "(blank)"), c["_file_date"])
            ct = ct.loc[ct.sum(axis=1).sort_values(ascending=False).index].head(30)
            rep.block(ct.reset_index())
    if {"ACCOUNT_STATUS_L1", "ACCOUNT_STATUS_L2"} <= set(c.columns):
        rep.add("\nL1 to L2 mapping (top 40 combinations, all snapshots):")
        combo = c.groupby(["ACCOUNT_STATUS_L1", "ACCOUNT_STATUS_L2"]).size().sort_values(ascending=False).head(40)
        rep.block(combo.reset_index(name="rows"))


# ----------------------------------------------------------------------------
# Sales and customer workbook
# ----------------------------------------------------------------------------
def sheet_by_kw(sheets: dict[str, pd.DataFrame], kw: str) -> pd.DataFrame | None:
    for name, df in sheets.items():
        if kw in name.lower():
            return df
    return None


def sales_checks(rep: Report, sales: pd.DataFrame) -> None:
    key = find_col(sales, "loan id")
    rep.add(f"rows {len(sales):,} | key column: {key}")
    if key:
        k = clean_key(sales[key])
        rep.add(f"blank or #N/A keys {int((k == '').sum())} | duplicate keys {int(k[k != ''].duplicated().sum())}")
    if "SALE_ID" in sales.columns and key:
        rep.add(f"SALE_ID equals Loan Id in {(sales['SALE_ID'] == sales[key]).mean():.1%} of rows")
    for col in ("SALE_TYPE", "RETURNED", "LOAN_TERM", "SELLER_TYPE"):
        if col in sales.columns:
            rep.add(f"{col}: " + "; ".join(f"{k or '(blank)'}={v}" for k, v in sales[col].value_counts().head(10).items()))
    cash, loan = num(sales.get("CASH_PRICE", pd.Series(dtype=str))), num(sales.get("LOAN_PRICE", pd.Series(dtype=str)))
    if len(cash) and len(loan):
        rep.add(f"LOAN_PRICE < CASH_PRICE: {int((loan < cash).sum())} | prices <= 0: {int(((cash <= 0) | (loan <= 0)).sum())}")


def dob_checks(rep: Report, dob: pd.DataFrame, ref_dates: list[pd.Timestamp]) -> None:
    key, col = find_col(dob, "loan id"), find_col(dob, "birth")
    if key:
        k = clean_key(dob[key])
        rep.add(f"rows {len(dob):,} | blank or #N/A keys {int((k == '').sum())} | duplicate keys {int(k[k != ''].duplicated().sum())}")
    if col:
        parsed, note = to_date(dob[col])
        rep.add(f"date_of_birth formats: {note} | future DOBs {int((parsed > pd.Timestamp.today()).sum())}")
        for ref in (ref_dates[0], ref_dates[-1]):
            ages = age_years(parsed.dropna(), ref)
            rep.add(f"Age at {ref.date()}: " + "; ".join(f"{k}={v}" for k, v in pd.cut(ages, AGE_BINS, labels=AGE_LABELS, right=False).value_counts().sort_index().items()))


def income_checks(rep: Report, inc: pd.DataFrame) -> None:
    key, dur = find_col(inc, "loan id"), find_col(inc, "duration")
    vals = [c for c in inc.columns if c not in (key, dur)]
    rep.add(f"rows {len(inc):,} | income-related columns: {vals}")
    if dur:
        rep.add("Duration values: " + "; ".join(f"{k or '(blank)'}={v}" for k, v in inc[dur].value_counts().head(10).items()))
    n = pd.DataFrame({c: num(inc[c]) for c in vals})
    rep.add("Does one column equal the sum of the others? (share of rows within 1 unit)")
    for total in vals:
        others = [c for c in vals if c != total]
        ok = ((n[total] - n[others].sum(axis=1)).abs() <= 1) & n[total].notna()
        rep.add(f"  {total} = sum of other columns: {ok.mean():.1%}")
    rep.add("Pairwise containment (share of rows where column A <= column B):")
    pairs = [{"A": a, "B": b, "share": f"{(n[a] <= n[b] + 1).mean():.1%}"} for a in vals for b in vals if a != b]
    rep.block(pd.DataFrame(pairs))
    if dur:
        d = num(inc[dur]).replace(0, np.nan)
        for label, series in (("SUM of all income columns", n.sum(axis=1)), (f"{vals[0]} only", n[vals[0]])):
            monthly = series / d
            bands = pd.cut(monthly, INCOME_BINS, labels=INCOME_LABELS, right=False).value_counts().reindex(INCOME_LABELS)
            rep.add(f"Monthly income band counts using {label} / Duration: " + "; ".join(f"{k}={v}" for k, v in bands.items()))
        rep.add(f"Rows with Duration blank or 0: {int(d.isna().sum())}")


# ----------------------------------------------------------------------------
# NPS
# ----------------------------------------------------------------------------
def nps_checks(rep: Report, nps: pd.DataFrame) -> None:
    key, sub = find_col(nps, "loan id"), find_col(nps, "submission")
    rep.add(f"rows {len(nps):,}")
    if sub:
        rep.add(f"duplicate Submission IDs: {int(nps[sub].duplicated().sum())}")
    if key:
        k = clean_key(nps[key])
        counts = k[k != ""].value_counts()
        rep.add(f"blank Loan Id {int((k == '').sum())} | loans with more than one response {int((counts > 1).sum())} (max {int(counts.max()) if len(counts) else 0})")
    score_col = find_col(nps, "scale from 0")
    if score_col:
        score = num(nps[score_col])
        dist = score.value_counts().sort_index()
        rep.add("Score distribution: " + "; ".join(f"{int(k) if float(k).is_integer() else k}={v}" for k, v in dist.items()))
        rep.add(f"out of 0-10 range: {int(((score < 0) | (score > 10)).sum())} | blank {int(score.isna().sum())}")
        valid = score.dropna()
        if len(valid):
            rep.add(f"Overall NPS = {100 * ((valid >= 9).mean() - (valid <= 6).mean()):.1f} (promoters 9-10, detractors 0-6)")
    when = find_col(nps, "submitted")
    if when:
        parsed, note = to_date(nps[when])
        rep.add(f"Submitted at: {note} | range {parsed.min().date() if parsed.notna().any() else 'n/a'} to {parsed.max().date() if parsed.notna().any() else 'n/a'}")
    rep.add("Free-text columns: count of cells containing phone or email patterns (values not shown):")
    for col in nps.columns:
        if FREE_TEXT_COL.search(col):
            s = nps[col].astype(str)
            rep.add(f"  {col[:50]}: filled {int((s.str.strip() != '').sum())}, phone-like {int(s.map(lambda v: bool(PHONE_RE.search(v))).sum())}, email-like {int(s.map(lambda v: bool(EMAIL_RE.search(v))).sum())}")


# ----------------------------------------------------------------------------
# Joins
# ----------------------------------------------------------------------------
def join_analysis(rep: Report, cred: pd.DataFrame, dims: dict[str, pd.Series], rows: dict[str, int]) -> None:
    snaps = sorted(cred["_file_date"].unique())
    all_ids = set(cred["LOAN_ID"])
    by_snap = {s: set(cred.loc[cred["_file_date"] == s, "LOAN_ID"]) for s in snaps}
    table, per_snap = [], []
    for name, ids in dims.items():
        ids = clean_key(ids)
        nn = ids[ids != ""]
        keys = set(nn)
        table.append(
            {
                "table.key": name,
                "rows": rows[name],
                "blank_or_NA_keys": rows[name] - len(nn),
                "unique_keys": len(keys),
                "extra_rows_on_dup_keys": len(nn) - len(keys),
                "credit_loans_covered": f"{len(all_ids & keys) / len(all_ids):.1%}",
                "orphan_keys_not_in_credit": len(keys - all_ids),
            }
        )
        per_snap.append({"table.key": name, **{s: f"{len(by_snap[s] & keys) / len(by_snap[s]):.1%}" for s in snaps}})
    rep.add("Key integrity and cardinality against ALL credit snapshots:")
    rep.block(pd.DataFrame(table))
    rep.add("Share of each snapshot's loans found in each table:")
    rep.block(pd.DataFrame(per_snap))
    empty = [t["table.key"] for t in table if rows[t["table.key"]] and t["blank_or_NA_keys"] / rows[t["table.key"]] > 0.5]
    if empty:
        rep.add(f"WARNING: join key blank or #N/A on most rows in {empty}. Those sheets cannot be joined to credit data for most rows.")
        rep.add("Check section 9 (formula columns) and whether rows line up by position with Sales Details.")
        rep.add("Row counts for comparison: " + "; ".join(f"{k}={v:,}" for k, v in rows.items()))


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--raw-dir", type=Path, default=ROOT / "data" / "raw")
    ap.add_argument("--interim-dir", type=Path, default=ROOT / "data" / "interim")
    ap.add_argument("--out-dir", type=Path, default=ROOT / "outputs" / "profiling")
    ap.add_argument("--log-dir", type=Path, default=ROOT / "logs")
    ap.add_argument("--refresh", action="store_true", help="re-read xlsx files instead of using the CSV cache")
    args = ap.parse_args()

    for d in (args.out_dir, args.log_dir, args.interim_dir):
        d.mkdir(parents=True, exist_ok=True)
    setup_logging("data_profiling", args.log_dir)

    credit_files, sales_path, nps_path, defs_path = find_files(args.raw_dir)
    missing = [n for n, v in (("credit CSVs", credit_files), ("sales workbook", sales_path), ("NPS workbook", nps_path)) if not v]
    if missing:
        LOG.error("Missing in %s: %s. Unzip any archives into that folder first.", args.raw_dir, ", ".join(missing))
        return 1

    rep = Report()
    rep.h(1, "Data profiling report")
    rep.add(f"Generated {datetime.now():%Y-%m-%d %H:%M} | raw dir: {args.raw_dir}")
    rep.add("Files: " + ", ".join(p.name for p in [*credit_files, sales_path, nps_path, defs_path] if p))

    cred = load_credit(credit_files)
    sales_sheets = read_xlsx(sales_path, args.interim_dir, args.refresh)
    nps = next(iter(read_xlsx(nps_path, args.interim_dir, args.refresh).values()))
    defs = next(iter(read_xlsx(defs_path, args.interim_dir, args.refresh).values())) if defs_path else None

    tables: dict[str, pd.DataFrame] = {"credit_all_snapshots": cred, **{f"sales_{k}": v for k, v in sales_sheets.items()}, "nps": nps}
    rep.h(2, "1. Row counts")
    rep.block(pd.DataFrame([{"table": k, "rows": f"{len(v):,}", "columns": len([c for c in v.columns if not c.startswith('_')])} for k, v in tables.items()]))

    rep.h(2, "2. Column profiles")
    for name, df in tables.items():
        rep.add(f"\n### {name}\n")
        prof = profile_table(df, skip=("_file", "_file_date"))
        safe_name = re.sub(r"\W+", "_", name).lower()
        prof.to_csv(args.out_dir / f"profile_{safe_name}.csv", index=False)
        rep.block(prof)

    section(rep, "3. Credit snapshots: structure and drift", credit_overview, cred, defs)
    section(rep, "4. Credit snapshots: logical rule checks", credit_logic_checks, cred)

    sales = sheet_by_kw(sales_sheets, "sales")
    gender, dob, income = (sheet_by_kw(sales_sheets, k) for k in ("gender", "dob", "income"))
    snap_dates = sorted(pd.Timestamp(d) for d in cred["_file_date"].unique())
    if sales is not None:
        section(rep, "5. Sales Details", sales_checks, sales)
    if dob is not None:
        section(rep, "6. DOB sheet and implied ages", dob_checks, dob, snap_dates)
    if income is not None:
        section(rep, "7. Income Level sheet", income_checks, income)
    section(rep, "8. NPS", nps_checks, nps)

    def formulas(r: Report) -> None:
        for sheet in sales_sheets:
            found = probe_formulas(sales_path, sheet)
            r.add(f"{sheet}: formula columns in first rows: {found or 'none (values are stored, not computed)'}")

    section(rep, "9. Are any sales workbook columns formulas?", formulas)

    dims, rows = {}, {}
    for label, df in (("sales.Loan Id", sales), ("gender.Loan Id", gender), ("dob.Loan Id", dob), ("income.Loan Id", income), ("nps.Loan Id", nps)):
        if df is not None and find_col(df, "loan id"):
            dims[label], rows[label] = df[find_col(df, "loan id")], len(df)
    if sales is not None and "SALE_ID" in sales.columns:
        dims["sales.SALE_ID"], rows["sales.SALE_ID"] = sales["SALE_ID"], len(sales)
    section(rep, "10. Join keys across datasets", join_analysis, cred, dims, rows)

    out = args.out_dir / "profiling_report.md"
    out.write_text(rep.text(), encoding="utf-8")
    LOG.info("Report written to %s", out)
    print(rep.text())
    return 0


if __name__ == "__main__":
    sys.exit(main())