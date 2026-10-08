# ABC Phones credit portfolio pipeline

A batch data pipeline, a data quality framework and a portfolio analysis for ABC Phones, which sells smartphones on installment credit. Built on Google Cloud (Cloud Storage, BigQuery, Secret Manager) with Python and SQL, for the Annex Technologies Data Engineer case study.

Raw files go in. Out come masked, analytics-ready tables, a set of automatic quality checks that can stop a bad load, and answers to three business questions: how healthy is the loan book, which customers fall behind, and how does credit performance relate to customer satisfaction.

## Headline results (December 2025 snapshot, financed loans)

| Measure | Result |
|---|---|
| Financed loans | 19,565 |
| Customers behind on payments (8-90 days late) | 17.6%, flat all year (17.3% to 19.4%) |
| Loans lost (91+ days late) | 26.3% of all loans ever sold |
| Money collected from customers still being collected | 94.2% |
| Customers who never made a first payment | 5.8%, down from 7.2% in January |
| Healthy customers still healthy at the next snapshot | 95.8%, up from 93.6% |

- **Income matters most for risk.** Delinquency falls steadily as income rises: 22% for customers earning under 10,000 a month against 14% for those on 100,000 or more (trend p < 0.0001, loans sold in 2025). Age matters little.
- **Late customers are less satisfied.** The average recommendation score is 6.8 out of 10 for customers up to date and 4.3 for those over 90 days late. Trouble reaching customer care goes with the largest drop (4.4 against 7.7).
- **Recommendation.** Contact customers in the first 1 to 7 days of lateness, with easy help from customer care and a simple payment plan, and test it against a group left alone.
- **Data quality.** 48 automatic checks, including one that every staging table still has exactly the agreed columns and types. The only one that fails on the current data is a warning about a known source defect (payment dates later than the snapshot date in 31.5% of rows), which is flagged and kept out of the analysis.

The charts are in `outputs/charts/` and are explained in plain language in `outputs/charts_explained.md`.

## How it works

```
raw files -> upload to Cloud Storage (archive)
          -> clean, mask, reconcile (Python)  -> BigQuery staging
          -> quality gate (48 checks; a critical failure stops the run)
          -> feature SQL -> BigQuery marts -> verify (checks again) -> dashboard, charts, findings
```

The full picture, error handling, alerting and monitoring cadence are in `pipeline_design/architecture.md`. Why each choice was made is in `docs/decisions.md`.

## Quick start

**You need:** Python 3.11 or newer, [uv](https://docs.astral.sh/uv/), the Google Cloud CLI, and a Google Cloud project with billing enabled.

```bash
# 1. Install everything (core, cloud, charts, tests)
uv sync --all-extras

# 2. Put the eight source files in data/raw/ (they are not in this repository)
#    5 credit snapshot CSVs, Sales_and_Customer_Data.xlsx, the NPS xlsx, Credit_Data_Definitions.xlsx

# 3. One-time cloud setup (use your own project id and bucket name, and put them in config/settings.yaml)
gcloud projects create YOUR_PROJECT_ID
gcloud billing projects link YOUR_PROJECT_ID --billing-account=YOUR_BILLING_ID
gcloud config set project YOUR_PROJECT_ID
gcloud services enable storage.googleapis.com bigquery.googleapis.com secretmanager.googleapis.com
gcloud storage buckets create gs://YOUR_BUCKET --location=us-central1 --uniform-bucket-level-access --public-access-prevention

# 4. The masking key: a random secret that goes straight into Secret Manager and is never shown or saved
openssl rand -base64 32 | gcloud secrets create masking-key --data-file=-

# 5. Sign in for the Python libraries
unset GOOGLE_APPLICATION_CREDENTIALS      # if your shell sets it for another project
gcloud auth application-default login
gcloud auth application-default set-quota-project YOUR_PROJECT_ID
```

There are no `.env` files. Settings that are not secret are in `config/settings.yaml`. The only secret is the masking key, which lives in Secret Manager.

## Run it

```bash
uv run python scripts/run_pipeline.py --dry-run     # show the plan, run nothing
uv run python scripts/run_pipeline.py               # all steps, with the quality gate and retries
uv run python scripts/run_pipeline.py --from features   # resume after a fix
```

Each step also runs on its own:

| Step | Command | What it does |
|---|---|---|
| Profile | `scripts/data_profiling.py` | Reads the raw files and reports what is wrong with them, without showing personal data |
| Clean | `scripts/data_cleaning.py` | Cleans, masks and loads the staging tables (`--no-load` for a local-only run) |
| Quality | `scripts/quality_checks.py` | Runs the 48 checks, stores the results, exits with an error on a critical failure |
| Features | `scripts/feature_engineering.py` | Builds age band, income band, days past due and risk category (`--dry-run` to validate the SQL) |
| Marts | `scripts/build_marts.py` | Builds the fact table and metric tables, exports `outputs/portfolio_metrics.csv` |
| Analysis | `scripts/analysis.py` | Draws the charts and writes `outputs/analysis_findings.md` |

Run any of them with `uv run python scripts/<name>.py`.

## Tests

```bash
uv run pytest
```

The tests need no cloud access. The SQL is run in an in-memory DuckDB on small hand-built tables, and the quality checks are tested by seeding defects (a duplicate, an orphan, a bad age) and confirming the right alarm fires.

## What is in the repository

```
README.md
config/settings.yaml            non-secret settings (project, bucket, datasets, expected snapshot dates)
scripts/
  run_pipeline.py               runs every step in order, with a quality gate, retries and a run log
  data_profiling.py             data_cleaning.py   feature_engineering.py
  quality_checks.py             build_marts.py     analysis.py
  utils/                        settings, logging, masking and Google Cloud helpers
sql/
  01_staging/                   schema contract of each staging table
  02_features/                  the four features and the risk rules
  03_marts/                     fact table and metric tables
  04_dq_checks/                 the SQL quality checks
  05_analysis/                  ready-made queries for analysts
tests/                          unit tests for the SQL, the checks, masking, the runner and the docs
docs/                           assumptions, data dictionary, engineering decisions
pipeline_design/                architecture.md (and architecture.png)
deploy/README.md                optional runbook for running the pipeline unattended in Google Cloud
dashboard/README.md             Looker Studio dashboard notes
outputs/                        data_quality_report.md, portfolio_metrics.csv, cleaned_summary.csv (masked sample),
                                dq_results.csv, analysis_findings.md, charts/, charts_explained.md
slides/Annex_DE_Presentation.pdf
```

## Privacy

- Raw data, logs and anything that could hold a secret are excluded by `.gitignore` and are not in the repository.
- Every identifier is replaced by a keyed hash. The date of birth is used only to work out age and is then discarded. Seller names, gender and citizenship are never loaded. Survey free text is redacted and not exposed in the marts.
- On every run, a check scans every staging and mart table for raw IDs, emails and phone numbers, and the cleaning step refuses to write anything if it finds one.
- The sample in `outputs/cleaned_summary.csv` contains hashed IDs only.

## Where to find each part of the brief

| Brief | Where |
|---|---|
| 1A Profiling and cleaning | `scripts/data_profiling.py`, `scripts/data_cleaning.py`, `outputs/data_quality_report.md`, `docs/assumptions.md` |
| 1B Features | `sql/02_features/loan_snapshot_features.sql`, `scripts/feature_engineering.py`, `tests/test_features.py` |
| 1C ETL design | `pipeline_design/architecture.md`, `docs/decisions.md`, `scripts/run_pipeline.py`, `deploy/README.md` |
| 2 Data quality framework | `scripts/quality_checks.py`, `sql/04_dq_checks/`, `outputs/dq_results.csv`, `tests/test_quality_checks.py` |
| 3A Portfolio health | `scripts/analysis.py`, `outputs/portfolio_metrics.csv`, `outputs/charts/`, `sql/05_analysis/portfolio_health.sql` |
| 3B Credit and NPS | `outputs/analysis_findings.md`, `outputs/charts_explained.md`, `sql/05_analysis/nps_vs_credit.sql` |
| 3C Data gaps | `outputs/data_quality_report.md` and the final slide |
| Slide deck | `slides/Annex_DE_Presentation.pdf` |

## Limits to keep in mind

- Age and income exist only for loans sold from late 2024, so segment results cover 2025 loans, about 85% of them.
- The survey covers about 1 loan in 6, so satisfaction results are directional.
- There are five snapshots, so trends and any future model validation are limited.
- The data shows patterns, not causes. Where the reason cannot be seen in the data, the documents say so.
- Production scheduling is described in `deploy/README.md` but not deployed.
