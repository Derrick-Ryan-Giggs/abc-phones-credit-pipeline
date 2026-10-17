# Data quality report

Project: ABC Phones credit portfolio pipeline (Annex Technologies Data Engineer case study)
Evidence: `outputs/profiling_summary.md` (profiling run), `outputs/cleaning_log.csv` (row counts per cleaning step), `outputs/dq_results.csv` (latest quality run), `outputs/analysis_findings.md`.

## 1. What was profiled

| Dataset | Files | Rows | Grain and key |
|---|---|---|---|
| Credit snapshots | 5 CSVs (1 Jan, 31 Mar, 30 Jun, 30 Sep, 30 Dec 2025) | 71,456 (8,935 / 11,024 / 13,891 / 16,864 / 20,742) | One row per loan per snapshot. `LOAN_ID` + `DATE` |
| Sales Details | sheet of Sales_and_Customer_Data.xlsx | 20,747 | One row per sale. `SALE_ID` (unique) |
| Gender, DOB, Income Level | three more sheets of the same workbook | 49,804 / 57,130 / 22,839 | Keyed by `Loan Id`, which is mostly missing (finding 11) |
| NPS survey | NPS_Data.xlsx | 4,129 responses (3,532 loans) | One row per response. `Submission ID` |
| Definitions | Credit_Data_Definitions.xlsx | 33 columns defined | Reference only |

Method: every column was profiled for row counts, types, null shares, null-like tokens, number and date formats, uniqueness, rule violations, schema drift and cross-file join coverage. Raw files are never modified. Every decision below is applied in `data_cleaning.py` and tested.

## 2. Findings and decisions

### Credit snapshots

| # | Finding | Evidence | Decision | Why |
|---|---|---|---|---|
| 1 | `CUSTOMER_AGE` is days since the sale, not age in years | Equals snapshot date minus `SALE_DATE` in every row | Age comes from the DOB sheet, calculated at each snapshot date | Using it as age would put every customer in the youngest band |
| 2 | Credit `RETURN_DATE` is corrupted | About a quarter of filled values look like time fragments (hh:mm.s) mixed with M/D/YYYY dates | Column dropped. Return dates come from Sales Details (ISO) | A corrupted date cannot be repaired reliably |
| 3 | `MAX_PAYMENT_DATE` is later than the snapshot date | 22,473 rows (31.5%) in the first four snapshots, none in December | Kept, flagged `dq_payment_after_snapshot`, excluded from features and ML. Reported by check `range.payment_date_after_snapshot_share` | The extract stamps it at extract time, so older snapshots contain future information. Using it would leak the outcome |
| 4 | Column 28 is unnamed and empty | Empty in all five files | Dropped | No content |
| 5 | The "30-03" file holds 31 March | `DATE` value is 2025-03-31 | `snapshot_date` comes from the `DATE` column, not the filename | The data is the authority on its own date |
| 6 | Contradictory amounts | Arrears above zero with zero days past due in 10,148 rows (median arrears 100 KES, 62% under 1,000, mostly Paid Off and Active loans); the reverse in 18 rows; 106 rows (0.15%) with a negative balance, closing balance, total paid, deposit or initial payment | Flag only (`dq_*` columns), never overwrite. `days_past_due` is set to 0 when arrears are zero or less, as the brief says | Most arrears-without-days rows are small residuals or timing, not errors. Overwriting would hide source problems |
| 7 | Cash, demo and "lost" sales sit among the loans | `CREDIT_CHECK_DONE`: Y LOAN, Y CASH, Y LOST, Z DEMO (December: 19,565 / 992 / 183 / 2) | Column `portfolio_scope`. Portfolio metrics use financed loans only | Cash sales have no credit risk |
| 8 | Status taxonomy | 20 L1 and 9 L2 values. "Write Off" rows are all 91+ days past due. PAR 30 mixes Blocked 31-90 days with write-offs | Loss = 91+ days past due (includes FPD/FMD loans past 90 days). Delinquency = 8-90 days | Keeps delinquency and loss separate and independent of how labels are applied |
| 9 | Loans never leave the extracts | No loan drops out. 2,089 to 3,878 new loans per snapshot | Retention is measured as survival (healthy last time and not returned or 91+ days late now) | Presence in the file says nothing about retention |

### Sales and customer workbook

| # | Finding | Evidence | Decision | Why |
|---|---|---|---|---|
| 10 | Sheets are padded to 1,048,575 rows with `#N/A` lookup rows | Real sizes 20,747 / 49,804 / 57,130 / 22,839 | Reader streams until a long run of blank rows | Real row counts are needed for any check |
| 11 | `Loan Id` is `#N/A` on most Gender, DOB and Income rows | 34,908 of 49,804 (Gender), 43,568 of 57,130 (DOB), 10,954 of 22,839 (Income). Stored values, not formulas. Row counts differ, so rows cannot be matched by position | Unkeyed rows are dropped from loan-level data and counted in `cleaning_log.csv` | They cannot be linked to any loan. Usable loans: 11,217 with DOB, 10,609 with income |
| 12 | Sales `Loan Id` is unreliable | 51 `#N/A`, 5 duplicates, differs from `SALE_ID` on 7 rows | `SALE_ID` is the master key (unique, 100% credit coverage) | A complete, unique key |
| 13 | Demographics exist only for recent loans | Income coverage: about 0% for loans sold before 2024Q4, 41% in 2024Q4, 85-88% for 2025 sales | Segment analysis uses loans sold since 2025-01-01 | Otherwise "no data" (old loans, higher losses) is mistaken for a customer trait. December overall coverage is 54% for age and 51% for income |
| 14 | Several DOB records per loan | 1,035 loans with more than one record, 63 disagree. Three providers | One record per loan: valid DOB first, then TRANSUNION > SMILEID > SPINMOBILE, then latest. Agreement with the chosen date: 99.9% / 97.7% / 96.1% | Providers agree almost always, so the choice has little effect |
| 15 | Income columns overlap | No column equals the sum of the others (under 0.5% of rows). Persons, Banks and Paybills mostly sit inside `Received`. `Duration` runs 1 to 24, mostly 6 or 12. 35 negative Paybills, outliers up to 38 million | Income = `Received` / `Duration`. The brief's literal sum is kept as `avg_monthly_income_sum_all` | Summing all four double counts: 38% of loans fall in the top band that way, against 14% using `Received` |
| 16 | Gender and citizenship labels are inconsistent | M/F vs Male/Female, KENYAN vs Kenyan, "CITIZEN" | Not loaded | Not needed for any question, and less personal data held |
| 17 | 765 loan terms are not numeric (for example STDHIGH) | 3.7% of sales | Raw value kept, `loan_term_months` is null | Guessing a term would invent data |
| 18 | Mixed date formats | Credit M/D/YYYY, Sales ISO, DOB ISO with +03:00 offset | All parsed to DATE. The slash layout is inferred from the data (a day above 12 appears in the second position) | One standard in staging |

### NPS survey

| # | Finding | Evidence | Decision | Why |
|---|---|---|---|---|
| 19 | Several responses per loan | 533 loans answered more than once (up to 5) | All kept. The latest per loan is flagged (`is_latest_response`) and used for analysis | Keeps history, avoids double counting |
| 20 | Blank scores | 144 (3.5%) | Kept as null, excluded from NPS | Do not guess a score |
| 21 | Personal data in free text | A few phone numbers and emails | Redacted at staging. Free text is not exposed in marts | Privacy |
| 22 | Timing | Responses run 22 Apr to 27 Dec 2025 | Each response is matched to the latest snapshot on or before its date. January never matches | No look-ahead |
| 23 | Coverage | 3,532 loans responded (17% of December loans). 1,017 latest responses were given before the loan appeared in any snapshot | Credit analysis uses the 2,247 responses with a credit state at the time | Results are directional |

## 3. Assumptions

1. Customer means loan. There is no customer identifier in any file.
2. The financed portfolio is `CREDIT_CHECK_DONE` = Y LOAN.
3. Snapshot dates come from the `DATE` column.
4. Null and `#N/A` values are treated as missing. They are never imputed.
5. A loan 91 or more days past due, or with Write Off status, is a loss.
6. `Duration` is a statement window (months of income data), not employment length.
7. `Received` is the best single measure of monthly inflow. It is inflow, not verified income.
8. Age bands: 18-25, 26-35, 36-45, 46-55, 56+. The brief lists 46-55 and 55+, which overlap at 55, so 55 stays in 46-55. Under 18, over 120 or missing is Unknown.
9. Missing demographics reflect when the data started being captured, not customer behaviour.

## 4. Privacy

Every ID is replaced with a keyed hash (HMAC-SHA256) using a key held only in Secret Manager. The date of birth is used to derive age and then discarded. Seller names, gender and citizenship are not loaded. NPS free text is redacted. A check scans every staging and mart table for raw IDs, emails and phone numbers on each run.

## 5. How these are caught in future

`quality_checks.py` runs 43 checks: freshness, uniqueness, referential integrity, range and logic, null thresholds, and no unmasked personal data. The latest run: 42 passed, 1 warning, 0 critical. The warning is finding 3, reported on every run. Critical failures exit with an error and would block the mart refresh and alert the engineer.

## 6. Known limitations

- Demographic segments cover loans sold in 2025 only, and about 85% of those.
- NPS covers a small share of loans and may not represent all customers.
- Only five snapshots exist, so trends and any model validation are limited.
- There is no credit score, write-off date, payment-level history, location or employment type in the data (see the data gaps slide).