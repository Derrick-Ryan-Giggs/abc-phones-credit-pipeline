# Engineering decisions

Short records of the choices that shaped the pipeline: what was decided, why, what it costs, and what else was considered.

## 1. A small stack: Python scripts and BigQuery SQL
- **Decision:** Python (pandas) for cleaning and loading, BigQuery SQL files for features and marts, Looker Studio for the dashboard.
- **Why:** three source files and about 70,000 rows do not need an orchestrator or a transformation framework. The brief's own folder layout is a set of scripts.
- **Cost:** no automatic lineage graph and no built-in scheduler.
- **Considered:** dbt and Airflow. Both are the natural next step if the project grows (see `pipeline_design/architecture.md`).

## 2. Cleaning in Python, features and metrics in SQL
- **Decision:** parsing, deduplication, masking and redaction happen in `data_cleaning.py`. Everything after staging is SQL.
- **Why:** messy parsing (mixed date formats, `#N/A`, xlsx sheets padded to a million rows) is easier to write and test in Python. Set-based logic (bands, risk rules, rates) is clearer and cheaper in SQL, and analysts can read it.
- **Cost:** two languages. The boundary is explicit: the staging tables are the contract (`sql/01_staging`).

## 3. Raw files are never modified, flags are never overwritten
- **Decision:** raw files are only read. Suspect values get a `dq_*` flag and keep their delivered value.
- **Why:** every later step can be re-run from the source, and every correction is visible.
- **Cost:** a few extra columns.

## 4. Mask identifiers early with a key held only in Secret Manager
- **Decision:** every identifier becomes a keyed hash (HMAC-SHA256, 20 hex characters) inside `data_cleaning.py`. The date of birth is used to derive age at each snapshot and then discarded. Seller names, gender and citizenship are not loaded. Free text is redacted and never reaches the marts.
- **Why:** nothing downstream, including the dashboard and any model, can expose a customer. The same key on every table keeps joins working. No `.env` file means no secret on disk or in git.
- **Cost:** hashing is pseudonymisation, not anonymisation. Rare combinations of attributes could still identify someone, so marts expose bands, not raw values. Losing the key means re-masking from the raw files, which are kept.
- **Considered:** random tokens with a lookup table (a second sensitive table to protect) and dropping identifiers entirely (breaks joins).

## 5. SALE_ID is the master key
- **Decision:** the loan key is the SALE_ID, not the `Loan Id` column.
- **Why:** it is unique and covers every credit loan. `Loan Id` has `#N/A` values and duplicates.

## 6. Whole-table reloads, partitioned by snapshot
- **Decision:** each run replaces the staging tables entirely. The large tables are partitioned by `snapshot_date` and clustered by `loan_key`.
- **Why:** reloading everything takes about a minute at this size, is idempotent and is simple to reason about.
- **Cost:** it will not scale to many snapshots. The upgrade is to replace only the partitions of new snapshots.

## 7. A data quality gate before the marts
- **Decision:** `quality_checks.py` runs on staging first. A critical failure exits with code 2 and `run_pipeline.py` stops, so the marts are not rebuilt from bad data. Warnings are reported and the run continues.
- **Why:** bad data is better stopped early than explained later.
- **Known defects:** problems already understood and neutralised (for example `MAX_PAYMENT_DATE` after the snapshot) are warnings. They are still reported on every run, so they cannot go unnoticed.
- **Cost:** a failed check needs a person. That is the point.

## 8. Retries only for crashes
- **Decision:** a step that crashes is retried with a growing pause. A data quality failure is never retried.
- **Why:** a network error is temporary. Bad data is not.

## 9. A schema contract for every staging table
- **Decision:** `sql/01_staging/*.sql` states the agreed columns and types of each staging table. `quality_checks.py` compares them with BigQuery on every run (critical), and a unit test compares them with what `data_cleaning.py` writes.
- **Why:** it catches a changed or malformed source before it reaches the marts, and documents the interface between the Python and SQL halves.

## 10. Metrics are defined once, in the fact table
- **Decision:** `fct_loan_snapshot` holds boolean flags (`is_live`, `is_performing`, `is_loss_91plus`, `is_delinquent_7plus`, and others). Every metric table only counts and divides.
- **Why:** one definition cannot drift between the dashboard, the segment table and the analysis.

## 11. Delinquency and loss are kept separate
- **Decision:** the company's "PAR 30" group mixes live 31-90 day lateness with write-offs (81% of PAR 30 rows are write-offs). Delinquency counts 8-90 days past due. Loss counts 91 or more days. Lost loans leave the delinquency denominator.
- **Why:** otherwise delinquency would be dominated by loans that left the collectable book long ago.

## 12. Point-in-time correctness everywhere
- **Decision:** age is calculated at each snapshot date, survey responses use the credit state at the response date, return dates are shown only if on or before the snapshot, and earlier-snapshot history uses past rows only. `MAX_PAYMENT_DATE`, which contains future information, is excluded from features.
- **Why:** it stops the outcome leaking into the inputs, which matters for the analysis and any later model.

## 13. Segment analysis uses recent loans only
- **Decision:** age and income segments are compared on loans sold since 2025-01-01.
- **Why:** demographics exist only from late 2024. Including older loans would turn missing data into an apparent risk factor.

## 14. Honest statistics
- **Decision:** intervals and tests are reported with the numbers. Thirteen segments were tested, so the single income-trend test is the main claim, and the lowest income band alone is described as the highest rate, not as proven.
- **Why:** with many comparisons, one "significant" bar can appear by chance.

## 15. Tests without the cloud
- **Decision:** SQL logic is tested in an in-memory DuckDB on tiny hand-built tables. The pipeline runner is tested with fake steps. Statistics and masking are tested directly.
- **Why:** the tests are fast, free and run anywhere. Cloud-specific code (queries, loads, uploads) is kept thin so there is little left untested.
- **Cost:** DuckDB's SQL is not identical to BigQuery's, so the SQL uses only functions both support. Each file is also validated in BigQuery with a dry run.

## 16. Not built, on purpose
- **Quarantine of bad files and per-partition loads:** the design is in `pipeline_design/architecture.md`.
- **Cloud Run deployment:** designed in `deploy/README.md`. It needs a container image, and building one was not worth the cost and data use for a portfolio project.
- **Machine learning:** deferred until every deliverable was complete. The point-in-time rules above are what make it safe to add.
