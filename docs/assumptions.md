# Assumptions

Every assumption the analysis rests on, what it affects, and what would change if it were wrong. Evidence for each is in `outputs/data_quality_report.md`. The reasons behind the design choices are in `docs/decisions.md`.

## About the data

| # | Assumption | Affects | If it is wrong |
|---|---|---|---|
| 1 | A customer is a loan. No file has a customer identifier, so a person with two phones counts twice. | Every count and rate | Rates would be per customer instead of per loan. Needs a customer master key from the source. |
| 2 | The financed portfolio is the loans with `CREDIT_CHECK_DONE` = Y LOAN (19,565 of 20,742 loans in December). Cash (Y CASH), lost (Y LOST) and demo (Z DEMO) sales are kept but excluded from portfolio metrics. | All metrics | If Y LOST loans are real credit losses they should be added to the loss figures. Their meaning is not defined in the source. |
| 3 | The snapshot date is the `DATE` column, not the file name. The "30-03" file holds 31 March. | Time ordering, point-in-time joins | A mislabelled date would shift trends by days only. |
| 4 | `#N/A`, blank and other null-like values mean "not known". They are never filled in. | Cleaning | Imputing would hide gaps. |
| 5 | The `#N/A` loan identifiers in the Gender, DOB and Income sheets cannot be recovered. Those rows are dropped. | Demographic coverage | If the source can supply the real identifiers, coverage would rise from about 51-54% of December loans. |
| 6 | The Sales `SALE_ID` is the loan identifier. The credit `LOAN_ID` equals it for every loan. | All joins | Credit and Sales would not join. They do (100% of loans). |
| 7 | Demographic data exists only for loans sold from late 2024. Missing demographics on older loans reflect when capture began, not customer behaviour. | Segment analysis | Mixing old loans in would make "no data" look like a risky segment. Segment analysis therefore uses loans sold since 2025-01-01. |
| 8 | Where a loan has several date-of-birth records, the preference is: a valid date first, then TRANSUNION, SMILEID, SPINMOBILE, then the latest record. | Age | The providers disagree on only 63 of 1,035 multi-record loans, so the effect is small. |
| 9 | `Duration` in the Income sheet is a statement window (months of income data), not employment length. | Income | It matches the loan term and is mostly 6 or 12, which fits a statement window. |
| 10 | `Received` is the best single measure of monthly inflow. Persons, Banks and Paybills overlap with it, so adding all four double counts. | Income bands | With the brief's literal sum, 38% of loans fall in the top band instead of 14%. The literal version is kept as `avg_monthly_income_sum_all`. |
| 11 | Inflow is not income. Money received includes transfers and anything else paid in. | Income bands | Bands may overstate true earnings. They are used to rank customers, not to measure pay. |
| 12 | Survey scores are 0 to 10 likelihood to recommend. NPS = share scoring 9-10 minus share scoring 0-6. | Question 3B | A different scale would change the NPS figures but not the direction. |
| 13 | Each survey response is matched to the latest snapshot on or before its date. Responses given before the loan first appeared in a snapshot have no credit state at that time. | Question 3B | Using a later snapshot would leak the outcome into the satisfaction analysis. |

## About the definitions

| # | Assumption | Notes |
|---|---|---|
| 14 | **Days past due:** the delivered value, forced to 0 when arrears are zero or less (the brief's rule). The delivered value is kept in `days_past_due_reported`. | The due date itself is not in the data, only a future invoice date, so days cannot be rebuilt. |
| 15 | **Live loan:** financed and not Paid Off or Returned. | |
| 16 | **Lost loan:** live and (Write Off status or 91+ days past due). Every Write Off row is 91+ days late, so this also catches FPD and FMD loans past 90 days. | Called "loss" in the metrics. It is a days-late definition, not an accounting write-off. |
| 17 | **Performing loan:** live and not lost. The denominator for delinquency and collection rate. | |
| 18 | **Delinquency:** performing loans 8-90 days past due. A stricter version counts 31-90 days. | Lost loans are counted under loss, not delinquency. |
| 19 | **Collection rate:** total paid / total due to date, for performing loans. | Excludes lost loans, so it looks high. Read it next to the loss rate. |
| 20 | **First payment default rate:** loans with FPD status / financed loans. | |
| 21 | **Retention:** of loans that were Active, Inactive or PAR 7 at the previous snapshot, the share that are neither returned nor lost now. | Loans never leave the extracts, so presence in the file says nothing about retention. |
| 22 | **Age bands:** 18-25, 26-35, 36-45, 46-55, 56+. Under 18, over 120 or missing is Unknown. | The brief lists 46-55 and 55+, which overlap at 55. Age 55 stays in 46-55. |
| 23 | **Income bands:** Below 5,000; 5,000-9,999; 10,000-19,999; 20,000-29,999; 30,000-49,999; 50,000-99,999; 100,000-149,999; 150,000+ (KES per month). | As in the brief. |
| 24 | **Risk category:** the first matching rule wins. Critical: Write Off, 61+ days past due or Return. High: FPD/FMD, a first-default status, or 31-60 days. Medium: 8-30 days, or earlier lateness of 8+ days, or payment coverage below 0.8. Low: Paid Off, or current. Not rated: not financed. | Each loan row records its rule in `risk_rule`. |

## About the analysis

| # | Assumption | Notes |
|---|---|---|
| 25 | Segment comparisons use the December 2025 snapshot, performing loans sold since 2025-01-01, and loans with a known value. | The start date is computed from the data: the first quarter where income coverage stays at 80% or more. |
| 26 | A segment is only called out if it has at least 100 performing loans and differs significantly (p below 0.05) from all other known loans. Because 13 segments are tested, the overall income trend (one test) is the main claim. | Tests use a two-proportion z-test and a trend test. |
| 27 | Survey analysis uses the latest scored response per loan, for financed loans that were in a snapshot when they answered. | 2,247 responses. The result is directional: only about 17% of loans have an answer. |
| 28 | All findings are patterns in one year of data. None of them proves a cause. | |
