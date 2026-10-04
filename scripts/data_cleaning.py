#!/usr/bin/env python3
"""data_cleaning.py

Clean, standardise and PII-mask the ABC Phones source data, then write staging
tables locally (data/staging) and load them to BigQuery.

Run from the project root:
    uv run python scripts/data_cleaning.py --no-load     # local only, no BigQuery load
    uv run python scripts/data_cleaning.py               # local files + BigQuery staging

Rules implemented (see docs/assumptions.md and the project plan):
  Credit    snapshot_date comes from the DATE column (the 30-03 file holds 31 March);
            empty column 28 and the corrupted credit RETURN_DATE are dropped;
            suspect values are flagged (dq_* columns), never overwritten.
  Sales     SALE_ID is the master key (unique, 100% credit coverage); seller names dropped;
            return dates come from here (clean ISO dates).
  DOB       rows without a usable Loan Id are dropped; one row per loan (valid DOB first,
            then provider priority, then latest record); age and age band are derived per
            snapshot and the date of birth is then discarded.
  Income    rows without a usable Loan Id are dropped; one row per loan (longest Duration);
            avg_monthly_income = Received / Duration (brief's literal sum kept as a second column).
  NPS       every response kept, latest per loan flagged, free text redacted, each response
            matched to the latest snapshot on or before its submission date.
  Masking   every ID becomes a keyed hash (HMAC-SHA256) using the key in Secret Manager.
            The same key is used on every table so joins still work. The key is never logged.

Raw files are only ever read. Gender and citizenship are not loaded (not needed, and messy).
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import logging
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

# Shared helpers live in the profiling script (scripts/ is on sys.path when run as a script).
from data_profiling import (
    EMAIL_RE,
    NULL_TOKENS,
    PHONE_RE,
    age_years,
    clean_key,
    find_col,
    find_files,
    load_credit,
    num,
    read_xlsx,
    sheet_by_kw,
    to_date,
)

ROOT = Path(__file__).resolve().parents[1]
LOG = logging.getLogger("data_cleaning")

# Provider preference for the date of birth when a loan has several records.
# Revisit after reading the provider agreement table this script prints.
PROVIDER_PRIORITY = ["TRANSUNION", "SMILEID", "SPINMOBILE"]
SCOPE_MAP = {"Y LOAN": "financed", "Y CASH": "cash", "Y LOST": "lost", "Z DEMO": "demo"}
AGE_BINS = [18, 26, 36, 46, 56, 121]
AGE_LABELS = ["18-25", "26-35", "36-45", "46-55", "56+"]
# Raw IDs look like rec + 10 or more mixed letters/digits. The lookahead (needs a digit or capital)
# stops ordinary words such as "recommendation" from matching.
RAW_ID_RE = re.compile(r"\brec(?=[A-Za-z0-9]*[0-9A-Z])[A-Za-z0-9]{10,}\b")
KEY_RE = re.compile(r"^[0-9a-f]{20}$")


# ----------------------------------------------------------------------------
# Plumbing: step log, masking, secret
# ----------------------------------------------------------------------------
class StepLog:
    """Row-count reconciliation: every step records rows in and rows out."""

    def __init__(self) -> None:
        self.rows: list[dict] = []

    def add(self, table: str, step: str, rows_in, rows_out, note: str = "") -> None:
        self.rows.append({"table": table, "step": step, "rows_in": rows_in, "rows_out": rows_out, "note": note})
        LOG.info("%-12s %-52s in=%s out=%s %s", table, step, rows_in, rows_out, note)

    def frame(self) -> pd.DataFrame:
        return pd.DataFrame(self.rows)


class Masker:
    """Keyed hash of identifiers. Blank values stay null. Only unique values are hashed."""

    def __init__(self, key: bytes) -> None:
        self._key = key

    def __call__(self, s: pd.Series) -> pd.Series:
        cache = {
            v: hmac.new(self._key, v.encode("utf-8"), hashlib.sha256).hexdigest()[:20]
            for v in s.dropna().astype(str).unique()
            if v.strip() != ""
        }
        return s.astype(object).map(cache)


def get_masking_key(cfg: dict) -> bytes:
    """Read the masking key from Secret Manager (pinned version). Never from a file or .env."""
    from google.cloud import secretmanager

    g = cfg["gcp"]
    name = f"projects/{g['project_id']}/secrets/{g['masking_secret']}/versions/{g['masking_secret_version']}"
    client = secretmanager.SecretManagerServiceClient()
    return client.access_secret_version(request={"name": name}).payload.data


def text(s: pd.Series) -> pd.Series:
    """Trimmed text with blank and null-like tokens (N/A, null, -) turned into nulls."""
    st = s.astype(str).str.strip()
    return st.where(~st.str.lower().isin(NULL_TOKENS)).astype(object)


def redact(s: pd.Series) -> pd.Series:
    """Remove emails, phone numbers and long digit runs from free text."""
    out = text(s)
    out = out.str.replace(EMAIL_RE.pattern, "[email]", regex=True)
    out = out.str.replace(PHONE_RE.pattern, "[phone]", regex=True)
    out = out.str.replace(r"\b\d{7,}\b", "[number]", regex=True)
    return out.astype(object)


# ----------------------------------------------------------------------------
# Credit snapshots
# ----------------------------------------------------------------------------
def clean_credit(raw: pd.DataFrame, mask: Masker, log: StepLog) -> pd.DataFrame:
    n0 = len(raw)
    df = raw.copy()
    df.columns = [c.strip() for c in df.columns]
    drop = [c for c in df.columns if c.lower().startswith("unnamed") or c in ("RETURN_DATE", "_file", "_file_date")]
    df = df.drop(columns=drop)
    log.add("credit", "drop empty column and corrupted RETURN_DATE", n0, n0, f"dropped {[c for c in drop if not c.startswith('_')]}")

    ids = clean_key(df["LOAN_ID"])
    df, ids = df[ids != ""], ids[ids != ""]
    log.add("credit", "drop rows with blank LOAN_ID", n0, len(df))

    out = pd.DataFrame({"loan_key": mask(ids), "snapshot_date": to_date(df["DATE"])[0]})
    date_cols = {
        "SALE_DATE": "sale_date",
        "CREDIT_EXPIRY": "credit_expiry_date",
        "NEXT_INVOICE_DATE": "next_invoice_date",
        "MAX_PAYMENT_DATE": "max_payment_date",
    }
    text_cols = {
        "BALANCE_DUE_STATUS": "balance_due_status",
        "ACCOUNT_STATUS_L1": "account_status_l1",
        "ACCOUNT_STATUS_L2": "account_status_l2",
        "CREDIT_CHECK_DONE": "credit_check_done",
    }
    for src, dst in date_cols.items():
        out[dst] = to_date(df[src])[0]
    for src, dst in text_cols.items():
        out[dst] = text(df[src])
    for col in df.columns:
        if col not in {"LOAN_ID", "DATE", *date_cols, *text_cols}:
            out[col.lower()] = num(df[col])

    out["portfolio_scope"] = out["credit_check_done"].map(SCOPE_MAP).fillna("other")
    # Flag, never overwrite: the source values stay as delivered.
    out["dq_arrears_zero_days"] = (out["arrears"] > 0) & (out["days_past_due"] == 0)
    out["dq_days_zero_arrears"] = (out["arrears"] == 0) & (out["days_past_due"] > 0)
    out["dq_negative_amount"] = (out[["balance", "closing_balance", "total_paid", "deposit", "initial_pay"]] < 0).any(axis=1)
    out["dq_payment_after_snapshot"] = out["max_payment_date"] > out["snapshot_date"]
    log.add("credit", "flags set", len(out), len(out),
            f"arrears_zero_days={int(out.dq_arrears_zero_days.sum())} payment_after_snapshot={int(out.dq_payment_after_snapshot.sum())}")

    dup = out.duplicated(["loan_key", "snapshot_date"], keep="last")
    out = out[~dup].sort_values(["snapshot_date", "loan_key"]).reset_index(drop=True)
    log.add("credit", "deduplicate on (loan_key, snapshot_date)", len(out) + int(dup.sum()), len(out))
    return out


# ----------------------------------------------------------------------------
# Sales
# ----------------------------------------------------------------------------
def clean_sales(raw: pd.DataFrame, mask: Masker, log: StepLog) -> pd.DataFrame:
    n0 = len(raw)
    sid = clean_key(raw["SALE_ID"])
    df, sid = raw[sid != ""], sid[sid != ""]
    lid = clean_key(df["Loan Id"])
    mismatch = int(((lid != "") & (lid != sid)).sum())
    log.add("sales", "drop rows with blank SALE_ID", n0, len(df), f"Loan Id differs from SALE_ID on {mismatch} rows; SALE_ID used as key")

    out = pd.DataFrame(
        {
            "loan_key": mask(sid),
            "sale_date": to_date(df["SALE_DATE"])[0],
            "returned": df["RETURNED"].astype(str).str.strip().str.lower().eq("true"),
            "return_date": to_date(df["RETURN_DATE"])[0],
            "sale_type": text(df["SALE_TYPE"]),
            "seller_type": text(df["SELLER_TYPE"]),
            "return_policy_compliance": text(df["RETURN_POLICY_COMPLIANCE"]),
            "cash_price": num(df["CASH_PRICE"]),
            "loan_price": num(df["LOAN_PRICE"]),
            "client_model": text(df["CLIENT_MODEL"]),
            "business_model": text(df["BUSINESS_MODEL"]),
            "loan_term_raw": text(df["LOAN_TERM"]),
            "product_name": text(df["PRODUCT_NAME"]),
            "model": text(df["MODEL"]),
        }
    )
    out["loan_term_months"] = df["LOAN_TERM"].astype(str).str.extract(r"^\s*(\d+)\s*M\s*$", flags=re.I)[0].astype(float)
    out["dq_return_before_sale"] = out["return_date"] < out["sale_date"]
    log.add("sales", "SELLER (names) not loaded; ISO dates parsed", len(out), len(out),
            f"loan_term not numeric on {int(out.loan_term_months.isna().sum())} rows (e.g. STDHIGH), raw value kept")
    dup = out.duplicated("loan_key", keep="first")
    out = out[~dup].reset_index(drop=True)
    log.add("sales", "deduplicate on loan_key", len(out) + int(dup.sum()), len(out))
    return out


# ----------------------------------------------------------------------------
# Demographics: DOB (discarded after age is derived) and income
# ----------------------------------------------------------------------------
def clean_dob(raw: pd.DataFrame, mask: Masker, log: StepLog) -> pd.DataFrame:
    """Return one (loan_key, dob) row per loan. The result is held in memory only, never written."""
    key = clean_key(raw["Loan Id"])
    d = raw[key != ""].copy()
    d["loan_id"] = key[key != ""]
    log.add("dob", "drop rows without a usable Loan Id", len(raw), len(d), "unkeyed rows cannot be joined to any loan")

    d["dob"] = to_date(d["date_of_birth"])[0]
    d["created"] = pd.to_datetime(d["createdAt UTC"].astype(str).str[:19], errors="coerce")
    d["provider"] = d["provider"].astype(str).str.strip().str.upper()
    d["prio"] = d["provider"].map({p: i for i, p in enumerate(PROVIDER_PRIORITY)}).fillna(len(PROVIDER_PRIORITY))
    d["valid"] = d["dob"].notna()

    rows_per_loan = d.groupby("loan_id").size()
    multi = rows_per_loan[rows_per_loan > 1].index
    distinct_dobs = d[d["valid"]].groupby("loan_id")["dob"].nunique().reindex(multi).fillna(0)
    log.add("dob", "loans with several records", len(multi), int((distinct_dobs > 1).sum()),
            "rows_out = loans whose records disagree on the date of birth")

    d = d.sort_values(["loan_id", "valid", "prio", "created"], ascending=[True, False, True, False])
    chosen = d.drop_duplicates("loan_id").set_index("loan_id")["dob"]
    d["agrees"] = d["dob"] == d["loan_id"].map(chosen)
    agree = d[d["loan_id"].isin(multi)].groupby("provider")["agrees"].agg(["size", "mean"])
    for prov, r in agree.iterrows():
        log.add("dob", f"provider agreement with chosen DOB: {prov}", int(r["size"]), int(round(r["mean"] * r["size"])),
                "rows in multi-record loans / rows that match the chosen DOB")

    one = d.drop_duplicates("loan_id")
    out = pd.DataFrame({"loan_key": mask(one["loan_id"]), "dob": one["dob"].values})
    log.add("dob", "one row per loan (valid DOB, provider priority, latest)", len(d), len(out))
    return out


def derive_age(credit: pd.DataFrame, dob: pd.DataFrame, log: StepLog) -> pd.DataFrame:
    """Age and age band as at EACH snapshot date. The date of birth is dropped afterwards.

    Bands: 18-25, 26-35, 36-45, 46-55, 56+. The brief lists 46-55 and 55+ (overlapping at 55),
    so 55 stays in 46-55 and the top band starts at 56. Under 18, over 120 or missing is 'Unknown'.
    """
    m = credit[["loan_key", "snapshot_date"]].merge(dob, on="loan_key", how="left")
    age = pd.Series(np.nan, index=m.index, dtype="float64")
    for snap in m["snapshot_date"].dropna().unique():
        sel = m["snapshot_date"] == snap
        age[sel] = age_years(m.loc[sel, "dob"], pd.Timestamp(snap))
    band = pd.cut(age, AGE_BINS, labels=AGE_LABELS, right=False).astype(object)
    reason = np.where(m["dob"].isna(), "no_dob", np.where(band.isna(), "invalid_age", None))
    out = pd.DataFrame(
        {
            "loan_key": m["loan_key"],
            "snapshot_date": m["snapshot_date"],
            "age_years": age.where(band.notna()).astype("Int64"),
            "age_band": band.fillna("Unknown"),
            "age_unknown_reason": pd.Series(reason, index=m.index, dtype=object),
        }
    )
    log.add("loan_age", "age and band at each snapshot; DOB discarded", len(m), len(out),
            f"Unknown: no_dob={int((out.age_unknown_reason == 'no_dob').sum())} invalid_age={int((out.age_unknown_reason == 'invalid_age').sum())}")
    return out


def clean_income(raw: pd.DataFrame, mask: Masker, log: StepLog) -> pd.DataFrame:
    key = clean_key(raw["Loan Id"])
    d = raw[key != ""].copy()
    d["loan_id"] = key[key != ""]
    log.add("income", "drop rows without a usable Loan Id", len(raw), len(d))

    exact = {c.strip().lower(): c for c in d.columns}
    comps = {
        "received": num(d[exact["received"]]),
        "persons_received": num(d[exact["persons received from total"]]),
        "banks_received": num(d[exact["banks received"]]),
        "paybills_received": num(d[exact["paybills received others"]]),
    }
    d = d.assign(duration_months=num(d[exact["duration"]]), **comps)
    d = d.sort_values(["loan_id", "duration_months", "received"], ascending=[True, False, False])
    one = d.drop_duplicates("loan_id")
    log.add("income", "one row per loan (longest Duration)", len(d), len(one))

    dur = one["duration_months"].where(one["duration_months"] > 0)
    out = pd.DataFrame({"loan_key": mask(one["loan_id"]), "duration_months": one["duration_months"]})
    for name in comps:
        out[name] = one[name]
    out["avg_monthly_income"] = one["received"] / dur
    out["avg_monthly_income_sum_all"] = one[list(comps)].sum(axis=1) / dur
    out["dq_negative_component"] = (one[list(comps)] < 0).any(axis=1)
    return out.reset_index(drop=True)


# ----------------------------------------------------------------------------
# NPS
# ----------------------------------------------------------------------------
def clean_nps(raw: pd.DataFrame, mask: Masker, log: StepLog, snapshots: list) -> pd.DataFrame:
    d = raw
    c = lambda *kw: find_col(d, *kw)  # noqa: E731
    submitted = pd.to_datetime(d[c("submitted")].astype(str).str[:19], errors="coerce")
    score = num(d[c("scale from 0")])

    out = pd.DataFrame(
        {
            "response_key": mask(clean_key(d[c("submission")])),
            "respondent_key": mask(clean_key(d[c("respondent")])),
            "loan_key": mask(clean_key(d[c("loan id")])),
            "submitted_date": submitted.dt.normalize(),
            "nps_score": score,
            "quality_happy": text(d[c("quality and performanc")]),
            "service_happy": text(d[c("service and support")]),
            "payment_delay_experienced": text(d[c("delay in your pay")]),
            "assistance_difficulty": text(d[c("difficulty getting assistan")]),
            "battery_issue": text(d[c("battery")]),
            "app_usage": text(d[c("mophones app")]),
            "preferred_channel": text(d[c("communication channel")]),
            "phone_lock_experienced": text(d[c("phone lock")]),
            "reason_text": redact(d[c("main reason")]),
            "improve_text": redact(d[c("one thing")]),
            "challenge_text": redact(d[c("describe")]),
            "other_feedback_text": redact(d[c("other feedback")]),
        }
    )
    out["nps_category"] = pd.Series(
        np.select([score >= 9, score >= 7, score >= 0], ["promoter", "passive", "detractor"], default="unknown"),
        index=out.index, dtype=object,
    ).where(score.notna())
    out = out.assign(_t=submitted).sort_values("_t")
    out["is_latest_response"] = ~out.duplicated("loan_key", keep="last") & out["loan_key"].notna()
    snaps = pd.DataFrame({"matched_snapshot_date": pd.to_datetime(sorted(snapshots)).astype("datetime64[ns]")})
    out["submitted_date"] = out["submitted_date"].astype("datetime64[ns]")
    out = pd.merge_asof(out.sort_values("submitted_date"), snaps, left_on="submitted_date",
                        right_on="matched_snapshot_date", direction="backward").drop(columns="_t")
    log.add("nps", "responses kept; free text redacted; matched to snapshot", len(raw), len(out),
            f"blank scores={int(out.nps_score.isna().sum())} unmatched_snapshot={int(out.matched_snapshot_date.isna().sum())} "
            f"latest_per_loan={int(out.is_latest_response.sum())}")
    return out.reset_index(drop=True)


# ----------------------------------------------------------------------------
# Extra checks, guards, reconciliation
# ----------------------------------------------------------------------------
def point_in_time_check(credit: pd.DataFrame, sales: pd.DataFrame) -> pd.DataFrame:
    """Do 'Return' statuses use return dates that fall AFTER the snapshot (a point-in-time leak)?"""
    m = credit[["loan_key", "snapshot_date", "account_status_l2"]].merge(sales[["loan_key", "return_date"]], on="loan_key", how="left")
    m["return_after_snapshot"] = m["return_date"] > m["snapshot_date"]
    m["status_return"] = m["account_status_l2"].eq("Return")
    g = m.groupby("snapshot_date")
    return pd.DataFrame(
        {
            "status_Return_rows": g["status_return"].sum(),
            "return_date_after_snapshot": g["return_after_snapshot"].sum(),
            "of_which_status_Return": g.apply(lambda x: int((x["return_after_snapshot"] & x["status_return"]).sum()), include_groups=False),
            "Return_status_without_return_date": g.apply(lambda x: int((x["status_return"] & x["return_date"].isna()).sum()), include_groups=False),
        }
    ).reset_index()


def pii_guard(name: str, df: pd.DataFrame, skip: tuple = ()) -> int:
    """Count raw IDs, emails and phone numbers left in a staging table. Must be zero."""
    hits = 0
    for col in df.select_dtypes(include=["object", "string"]).columns:
        if col in skip or col.endswith("_key"):  # key columns are validated separately below
            continue
        s = df[col].dropna().astype(str)
        n = sum(int(s.str.contains(p.pattern, regex=True).sum()) for p in (EMAIL_RE, PHONE_RE, RAW_ID_RE))
        if n:
            LOG.error("PII guard: %s.%s has %s suspicious values", name, col, n)
        hits += n
    for col in [c for c in df.columns if c.endswith("_key")]:
        bad = int((~df[col].dropna().astype(str).str.match(KEY_RE)).sum())
        if bad:
            LOG.error("PII guard: %s.%s has %s values that are not masked keys", name, col, bad)
        hits += bad
    return hits


def to_py_dates(df: pd.DataFrame) -> pd.DataFrame:
    """datetime columns become python dates (BigQuery DATE) with None for missing."""
    out = df.copy()
    for col in out.columns:
        if pd.api.types.is_datetime64_any_dtype(out[col]):
            out[col] = pd.Series([x.date() if pd.notna(x) else None for x in out[col]], index=out.index, dtype=object)
    return out


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ----------------------------------------------------------------------------
# BigQuery
# ----------------------------------------------------------------------------
def load_to_bigquery(frames: dict[str, pd.DataFrame], audit: pd.DataFrame, cfg: dict) -> None:
    from google.cloud import bigquery

    project, location = cfg["gcp"]["project_id"], cfg["bigquery"]["location"]
    client = bigquery.Client(project=project, location=location)
    dataset_id = f"{project}.{cfg['bigquery']['dataset_staging']}"
    dataset = bigquery.Dataset(dataset_id)
    dataset.location = location
    client.create_dataset(dataset, exists_ok=True)

    for name, df in frames.items():
        # Full refresh of each table is idempotent. The credit table is partitioned by snapshot.
        job_config = bigquery.LoadJobConfig(write_disposition="WRITE_TRUNCATE")
        if name == "stg_credit_snapshots":
            job_config.time_partitioning = bigquery.TimePartitioning(type_=bigquery.TimePartitioningType.DAY, field="snapshot_date")
            job_config.clustering_fields = ["loan_key"]
        client.load_table_from_dataframe(df, f"{dataset_id}.{name}", job_config=job_config).result()
        LOG.info("Loaded %s (%s rows) to %s", name, f"{len(df):,}", dataset_id)

    job_config = bigquery.LoadJobConfig(write_disposition="WRITE_APPEND")
    client.load_table_from_dataframe(audit, f"{dataset_id}.load_audit", job_config=job_config).result()
    LOG.info("Appended %s rows to load_audit", len(audit))


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--raw-dir", type=Path, default=ROOT / "data" / "raw")
    ap.add_argument("--interim-dir", type=Path, default=ROOT / "data" / "interim")
    ap.add_argument("--staging-dir", type=Path, default=ROOT / "data" / "staging")
    ap.add_argument("--out-dir", type=Path, default=ROOT / "outputs")
    ap.add_argument("--log-dir", type=Path, default=ROOT / "logs")
    ap.add_argument("--config", type=Path, default=ROOT / "config" / "settings.yaml")
    ap.add_argument("--no-load", action="store_true", help="write local files only, skip the BigQuery load")
    args = ap.parse_args()

    for d in (args.staging_dir, args.out_dir, args.log_dir, args.interim_dir):
        d.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.FileHandler(args.log_dir / "data_cleaning.log"), logging.StreamHandler(sys.stderr)],
    )
    cfg = yaml.safe_load(args.config.read_text())
    run_id, run_ts = uuid.uuid4().hex[:8], datetime.now(timezone.utc)
    LOG.info("Run %s started", run_id)

    credit_files, sales_path, nps_path, defs_path = find_files(args.raw_dir)
    if not credit_files or not sales_path or not nps_path:
        LOG.error("Raw files missing in %s", args.raw_dir)
        return 1

    mask = Masker(get_masking_key(cfg))
    log = StepLog()

    raw_credit = load_credit(credit_files)
    sheets = read_xlsx(sales_path, args.interim_dir)
    nps_raw = next(iter(read_xlsx(nps_path, args.interim_dir).values()))

    credit = clean_credit(raw_credit, mask, log)
    sales = clean_sales(sheet_by_kw(sheets, "sales"), mask, log)
    dob = clean_dob(sheet_by_kw(sheets, "dob"), mask, log)
    loan_age = derive_age(credit, dob, log)
    del dob  # the date of birth never leaves this function scope
    income = clean_income(sheet_by_kw(sheets, "income"), mask, log)
    nps = clean_nps(nps_raw, mask, log, sorted(credit["snapshot_date"].dropna().unique()))

    # Coverage of the latest snapshot: how many loans have each enrichment.
    latest = credit[credit["snapshot_date"] == credit["snapshot_date"].max()]
    n_latest = latest["loan_key"].nunique()
    for label, keys in (("sales row", sales["loan_key"]), ("income row", income["loan_key"]), ("NPS response", nps["loan_key"])):
        log.add("coverage", f"latest snapshot loans with {label}", n_latest, int(latest["loan_key"].isin(keys).sum()))
    known_age = loan_age[(loan_age["snapshot_date"] == latest["snapshot_date"].max()) & (loan_age["age_band"] != "Unknown")]
    log.add("coverage", "latest snapshot loans with a valid age band", n_latest, known_age["loan_key"].nunique())

    pit = point_in_time_check(credit, sales)

    frames = {
        "stg_credit_snapshots": credit,
        "stg_sales": sales,
        "stg_loan_age": loan_age,
        "stg_income": income,
        "stg_nps": nps,
    }
    guard = sum(pii_guard(n, f, skip=("preferred_channel",)) for n, f in frames.items())
    if guard:
        LOG.error("PII guard failed with %s findings. Nothing was written or loaded.", guard)
        return 2
    if len(loan_age) != len(credit) or credit.duplicated(["loan_key", "snapshot_date"]).any():
        LOG.error("Reconciliation failed: loan_age rows do not match credit rows or keys are not unique.")
        return 3
    LOG.info("Reconciliation and PII guard passed")

    frames = {n: to_py_dates(f) for n, f in frames.items()}
    for name, df in frames.items():
        df.to_parquet(args.staging_dir / f"{name}.parquet", index=False)

    sample = frames["stg_credit_snapshots"].merge(frames["stg_loan_age"][["loan_key", "snapshot_date", "age_band"]], on=["loan_key", "snapshot_date"], how="left")
    sample[["loan_key", "snapshot_date", "portfolio_scope", "account_status_l1", "account_status_l2", "days_past_due", "arrears", "total_paid", "balance", "age_band"]] \
        .sample(500, random_state=42).sort_values(["snapshot_date", "loan_key"]).to_csv(args.out_dir / "cleaned_summary.csv", index=False)
    log.frame().to_csv(args.out_dir / "cleaning_log.csv", index=False)
    pit.to_csv(args.out_dir / "point_in_time_check.csv", index=False)

    files = [*credit_files, sales_path, nps_path] + ([defs_path] if defs_path else [])
    audit = pd.DataFrame(
        {
            "run_id": run_id,
            "run_ts": run_ts,
            "file_name": [f.name for f in files],
            "sha256": [sha256_of(f) for f in files],
            "size_bytes": [f.stat().st_size for f in files],
        }
    )
    if args.no_load:
        LOG.info("--no-load: BigQuery load skipped")
    else:
        load_to_bigquery(frames, audit, cfg)

    print("\n## Cleaning log\n")
    print(log.frame().to_string(index=False, max_colwidth=120))
    print("\n## Point-in-time check (credit status vs sales return dates)\n")
    print(pit.to_string(index=False))
    print(f"\nRun {run_id} finished. Staging files in {args.staging_dir}, summaries in {args.out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())