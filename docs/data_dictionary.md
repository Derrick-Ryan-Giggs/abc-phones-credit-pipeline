# Data dictionary

Every table the pipeline creates, with every column. Types are BigQuery types. Generated from the real tables and kept in step by `tests/test_data_dictionary.py`.

**Conventions**

- `loan_key` is a keyed hash (HMAC-SHA256, 20 hex characters) of the SALE_ID. It is the same in every table, so tables join on it. Real loan identifiers never leave `data_cleaning.py`.
- Columns starting `dq_` are data quality flags. They mark suspect values. Source values are never overwritten.
- Amounts are in Kenyan shillings (KES). Dates are `DATE` values.
- Money and risk definitions: see `docs/assumptions.md`. Why each choice was made: see `docs/decisions.md`.

## Staging tables (built by data_cleaning.py, loaded to abc_staging)

### `stg_credit_snapshots`

One row per loan per snapshot (71,456 rows).

- **Key:** loan_key + snapshot_date. Partitioned by snapshot_date, clustered by loan_key.
- **Built by:** `data_cleaning.py`

| Column | Type | Meaning |
|---|---|---|
| `loan_key` | STRING | Masked loan identifier: a keyed hash of the SALE_ID. It joins every table. It cannot be reversed without the secret key. |
| `snapshot_date` | DATE | Date of the snapshot, taken from the DATE column of the extract (the file called 30-03 holds 31 March). |
| `sale_date` | DATE | Date the phone was sold (loan origination). |
| `credit_expiry_date` | DATE | Date the credit term is expected to end, based on payments made. |
| `next_invoice_date` | DATE | Next scheduled repayment due date. Always a future date, so it cannot rebuild days past due. |
| `max_payment_date` | DATE | Most recent payment date recorded for the loan. Stamped at extract time, so in older snapshots it can be later than snapshot_date. Flagged and never used in features or models. |
| `balance_due_status` | STRING | High-level payment position as delivered: advance, up to date or arrears. |
| `account_status_l1` | STRING | Detailed credit status as delivered (20 values), for example Existing Active, Inactive 08-14, Blocked 31-60, Write Off, Paid Off Loan. |
| `account_status_l2` | STRING | Portfolio grouping of the L1 status (9 values): Active, Inactive, PAR 7, PAR 30, FPD, FMD, Paid Off, Return, Unknown. |
| `credit_check_done` | STRING | Credit check result at sale as delivered: Y LOAN (financed), Y CASH, Y LOST, Z DEMO. |
| `customer_age` | INT64 | Days since the sale date. Despite the name it is NOT the customer's age. Kept as delivered. |
| `total_paid` | INT64 | Cumulative amount paid up to the snapshot date, excluding adjustments. |
| `total_due_today` | FLOAT64 | Amount the customer should have paid by the snapshot date under the loan terms. |
| `balance` | FLOAT64 | Outstanding balance after payments, adjustments, discounts and the deposit. |
| `days_past_due` | INT64 | Days behind on payments as delivered. |
| `closing_balance` | FLOAT64 | Final balance for reporting: zero if the loan is paid off, otherwise equal to balance. |
| `advance` | FLOAT64 | Amount paid ahead of schedule. |
| `balance_due_to_date` | FLOAT64 | Net payment position: positive means ahead of schedule, negative means arrears. |
| `arrears` | FLOAT64 | Amount the customer is behind on payments at the snapshot date. |
| `payment` | INT64 | Indicator that a payment occurred on the snapshot date. |
| `expected_payment` | FLOAT64 | Payment amount expected for the period. |
| `first_payment` | INT64 | First payment made after the loan was activated. |
| `first_expected_payment` | INT64 | Expected amount of the first scheduled repayment. |
| `payment_amount` | FLOAT64 | Regular payment recorded on the snapshot date. Null for about 96% of rows (no payment recorded), not imputed. |
| `adjustment_amount` | FLOAT64 | Adjustment applied to the balance on the snapshot date (positive or negative). Null for about 96% of rows, not imputed. |
| `prepayment_amount` | INT64 | Amount paid in advance, typically at or before the sale. |
| `deposit` | FLOAT64 | Upfront payment at origination. |
| `weekly_rate` | FLOAT64 | Scheduled weekly repayment amount. |
| `discount` | FLOAT64 | Discount applied to the loan or cash price. |
| `overpayment_amount` | FLOAT64 | Amount paid above the total expected obligation. |
| `initial_pay` | INT64 | Initial payment at the start of the loan, including deposit and early payments. |
| `total_paid_with_adjustments_15d` | INT64 | Payments plus adjustments in the first 15 days after activation (used by the source for default classification). |
| `portfolio_scope` | STRING | financed (Y LOAN), cash (Y CASH), lost (Y LOST), demo (Z DEMO) or other. All portfolio metrics use financed loans only. |
| `dq_arrears_zero_days` | BOOL | Flag: arrears above zero but days past due is zero. Mostly small residual amounts. Reported, never changed. |
| `dq_days_zero_arrears` | BOOL | Flag: days past due above zero but arrears are zero or less. Reported, never changed. |
| `dq_negative_amount` | BOOL | Flag: a negative balance, closing balance, total paid, deposit or initial payment on this row. |
| `dq_payment_after_snapshot` | BOOL | Flag: max_payment_date is later than snapshot_date (extract-time leak). |

### `stg_sales`

One row per sale (20,747 rows).

- **Key:** loan_key
- **Built by:** `data_cleaning.py`

| Column | Type | Meaning |
|---|---|---|
| `loan_key` | STRING | Masked loan identifier: a keyed hash of the SALE_ID. It joins every table. It cannot be reversed without the secret key. |
| `sale_date` | DATE | Date the phone was sold (loan origination). |
| `returned` | BOOL | True when the phone was returned. |
| `return_date` | DATE | Date the phone was returned, from the Sales sheet (clean ISO date). The credit extract's own return date is corrupted and is not loaded. |
| `sale_type` | STRING | Financed, Non Financed or Y Lost, as recorded by Sales. |
| `seller_type` | STRING | Type of seller (the seller's name is not loaded). |
| `return_policy_compliance` | STRING | Whether a return followed the return policy, as recorded by Sales. |
| `cash_price` | FLOAT64 | Cash price of the phone, KES. |
| `loan_price` | FLOAT64 | Price of the phone on the installment plan, KES. |
| `client_model` | STRING | Customer segment label as delivered by Sales. |
| `business_model` | STRING | Business model label as delivered by Sales ('Not Available' for about 10%). |
| `loan_term_raw` | STRING | Loan term as delivered, for example 12M, 3M or STDHIGH. |
| `product_name` | STRING | Phone product name. |
| `model` | STRING | Phone model. |
| `loan_term_months` | FLOAT64 | Loan term in months. Null when the delivered term is not a number of months (765 sales, for example STDHIGH). |
| `dq_return_before_sale` | BOOL | Flag: the return date is before the sale date. |

### `stg_loan_age`

Age and age band for each loan at each snapshot (71,456 rows). The date of birth is not stored.

- **Key:** loan_key + snapshot_date
- **Built by:** `data_cleaning.py`

| Column | Type | Meaning |
|---|---|---|
| `loan_key` | STRING | Masked loan identifier: a keyed hash of the SALE_ID. It joins every table. It cannot be reversed without the secret key. |
| `snapshot_date` | DATE | Date of the snapshot, taken from the DATE column of the extract (the file called 30-03 holds 31 March). |
| `age_years` | INT64 | Customer age in whole years AT the snapshot date. Null when unknown or outside 18-120. The date of birth itself is not stored. |
| `age_band` | STRING | 18-25, 26-35, 36-45, 46-55, 56+ or Unknown. The brief lists 46-55 and 55+, which overlap at 55, so 55 stays in 46-55. |
| `age_unknown_reason` | STRING | no_dob (no usable date of birth for the loan) or invalid_age (outside 18-120). Null when the age is known. |

### `stg_income`

One income row per loan that has one (10,609 rows).

- **Key:** loan_key
- **Built by:** `data_cleaning.py`

| Column | Type | Meaning |
|---|---|---|
| `loan_key` | STRING | Masked loan identifier: a keyed hash of the SALE_ID. It joins every table. It cannot be reversed without the secret key. |
| `duration_months` | INT64 | Months of income data (a statement window, 1 to 24, mostly 6 or 12). Not employment length. |
| `received` | FLOAT64 | Total money received over the window, KES. The measure used for income. |
| `persons_received` | FLOAT64 | Part of the money received that came from individuals, as named in the source. Overlaps with received. |
| `banks_received` | FLOAT64 | Part of the money received that came from banks, as named in the source. Overlaps with received. |
| `paybills_received` | FLOAT64 | Part of the money received through paybills and others, as named in the source. Overlaps with received and can be negative. |
| `avg_monthly_income` | FLOAT64 | received / duration_months, KES per month. This is inflow, not verified income. Used for the income bands. |
| `avg_monthly_income_sum_all` | FLOAT64 | The brief's literal wording: all four amounts added, divided by duration. It double counts, so it is kept for transparency only. |
| `dq_negative_component` | BOOL | Flag: one of the received amounts is negative (35 loans have a negative paybills amount). |

### `stg_nps`

One row per survey response (4,129 rows).

- **Key:** response_key
- **Built by:** `data_cleaning.py`

| Column | Type | Meaning |
|---|---|---|
| `response_key` | STRING | Masked survey submission identifier. |
| `respondent_key` | STRING | Masked respondent identifier. |
| `loan_key` | STRING | Masked loan identifier of the loan the survey is about. |
| `submitted_date` | DATE | Date the survey was submitted. |
| `nps_score` | FLOAT64 | Answer to 'how likely are you to recommend ABC Phones' from 0 to 10. Null for the 144 blank answers. |
| `quality_happy` | STRING | Survey answer: happy with product quality and performance. |
| `service_happy` | STRING | Survey answer: happy with service and support. |
| `payment_delay_experienced` | STRING | Survey answer: experienced a delay in payments. |
| `assistance_difficulty` | STRING | Survey answer: had difficulty getting help from customer care (Yes, No, or never looked for help). |
| `battery_issue` | STRING | Survey answer: battery problems. |
| `app_usage` | STRING | Survey answer: has used the ABC Phones app. |
| `preferred_channel` | STRING | Survey answer: preferred communication channel. The option text includes the company support number, which is not personal data. |
| `phone_lock_experienced` | STRING | Survey answer: the phone was locked despite paying. |
| `reason_text` | STRING | Free text: main reason for the score. Phone numbers, emails and long digit runs redacted. Stays in staging, never in marts. |
| `improve_text` | STRING | Free text: one thing to improve. Redacted as above. Staging only. |
| `challenge_text` | STRING | Free text: description of the difficulty. Redacted as above. Staging only. |
| `other_feedback_text` | STRING | Free text: any other feedback. Redacted as above. Staging only. |
| `nps_category` | STRING | promoter (9-10), passive (7-8) or detractor (0-6). Null when there is no score. |
| `is_latest_response` | BOOL | True for the most recent response of each loan. Analysis uses these only. |
| `matched_snapshot_date` | DATE | Latest snapshot on or before the response date, so credit status is as at the response (no look-ahead). Null if none. |

## Feature table (built by feature_engineering.py, in abc_staging)

### `int_loan_snapshot_features`

Credit rows plus age band, income band, days past due and risk category.

- **Key:** loan_key + snapshot_date. Partitioned by snapshot_date.
- **Built by:** `sql/02_features/loan_snapshot_features.sql`

| Column | Type | Meaning |
|---|---|---|
| `loan_key` | STRING | Masked loan identifier: a keyed hash of the SALE_ID. It joins every table. It cannot be reversed without the secret key. |
| `snapshot_date` | DATE | Date of the snapshot, taken from the DATE column of the extract (the file called 30-03 holds 31 March). |
| `portfolio_scope` | STRING | financed (Y LOAN), cash (Y CASH), lost (Y LOST), demo (Z DEMO) or other. All portfolio metrics use financed loans only. |
| `is_live` | BOOL | True for a financed loan that is not Paid Off or Returned. |
| `account_status_l1` | STRING | Detailed credit status as delivered (20 values), for example Existing Active, Inactive 08-14, Blocked 31-60, Write Off, Paid Off Loan. |
| `account_status_l2` | STRING | Portfolio grouping of the L1 status (9 values): Active, Inactive, PAR 7, PAR 30, FPD, FMD, Paid Off, Return, Unknown. |
| `age_band` | STRING | 18-25, 26-35, 36-45, 46-55, 56+ or Unknown. The brief lists 46-55 and 55+, which overlap at 55, so 55 stays in 46-55. |
| `age_years` | INT64 | Customer age in whole years AT the snapshot date. Null when unknown or outside 18-120. The date of birth itself is not stored. |
| `avg_monthly_income` | FLOAT64 | received / duration_months, KES per month. This is inflow, not verified income. Used for the income bands. |
| `avg_monthly_income_band` | STRING | Income band as in the brief: Below 5,000; 5,000-9,999; 10,000-19,999; 20,000-29,999; 30,000-49,999; 50,000-99,999; 100,000-149,999; 150,000+; or Unknown. |
| `avg_monthly_income_band_brief_sum` | STRING | The same bands using the brief's literal sum. For transparency only. |
| `days_past_due` | INT64 | Days behind on payments, set to 0 when arrears are zero or less (the brief's rule). The delivered value is kept in days_past_due_reported. |
| `days_past_due_reported` | INT64 | Days past due exactly as delivered, before the zero-arrears rule. |
| `dpd_bucket` | STRING | Days past due grouped: 0, 1-7, 8-30, 31-60, 61-90, 91+. |
| `arrears` | FLOAT64 | Amount the customer is behind on payments at the snapshot date. |
| `balance` | FLOAT64 | Outstanding balance after payments, adjustments, discounts and the deposit. |
| `total_paid` | INT64 | Cumulative amount paid up to the snapshot date, excluding adjustments. |
| `total_due_today` | FLOAT64 | Amount the customer should have paid by the snapshot date under the loan terms. |
| `payment_coverage` | FLOAT64 | total_paid / total_due_today. About 1.0 for loans on track. A payment-history signal. |
| `max_dpd_prior` | INT64 | Highest days past due at earlier snapshots of the same loan (null at the first). Uses past data only. |
| `prior_snapshots_in_arrears` | INT64 | Number of earlier snapshots in which the loan was behind. |
| `prev_status_l2` | STRING | L2 status at the previous snapshot of the same loan (null at the first). |
| `risk_rule` | STRING | The rule that set risk_category (R0 to R6). The first matching rule wins. |
| `risk_category` | STRING | Low, Medium, High, Critical or Not rated. Critical: Write Off status, 61+ days past due or Return. High: FPD/FMD or first-default status, or 31-60 days. Medium: 8-30 days, or earlier lateness or payment coverage below 0.8. Low: Paid Off, or current. Not rated: not financed. |
| `dq_arrears_zero_days` | BOOL | Flag: arrears above zero but days past due is zero. Mostly small residual amounts. Reported, never changed. |
| `dq_days_zero_arrears` | BOOL | Flag: days past due above zero but arrears are zero or less. Reported, never changed. |
| `dq_negative_amount` | BOOL | Flag: a negative balance, closing balance, total paid, deposit or initial payment on this row. |
| `dq_payment_after_snapshot` | BOOL | Flag: max_payment_date is later than snapshot_date (extract-time leak). |

## Marts (built by build_marts.py, in abc_marts)

### `fct_loan_snapshot`

The analytics-ready fact table: one row per loan per snapshot with the flags every metric is built from.

- **Key:** loan_key + snapshot_date. Partitioned by snapshot_date.
- **Built by:** `sql/03_marts/fct_loan_snapshot.sql`

| Column | Type | Meaning |
|---|---|---|
| `loan_key` | STRING | Masked loan identifier: a keyed hash of the SALE_ID. It joins every table. It cannot be reversed without the secret key. |
| `snapshot_date` | DATE | Date of the snapshot, taken from the DATE column of the extract (the file called 30-03 holds 31 March). |
| `portfolio_scope` | STRING | financed (Y LOAN), cash (Y CASH), lost (Y LOST), demo (Z DEMO) or other. All portfolio metrics use financed loans only. |
| `is_financed` | BOOL | True when portfolio_scope is financed. |
| `is_live` | BOOL | True for a financed loan that is not Paid Off or Returned. |
| `is_loss_91plus` | BOOL | Live and (Write Off status or 91+ days past due). Every Write Off row is 91+ days late, so this also catches FPD/FMD loans past 90 days. |
| `is_performing` | BOOL | Live and not is_loss_91plus. The collectable book, the denominator for delinquency and collection rate. |
| `is_delinquent_7plus` | BOOL | Performing and 8-90 days past due. |
| `is_delinquent_30plus` | BOOL | Performing and 31-90 days past due. |
| `is_paid_off` | BOOL | Financed and L2 status Paid Off. |
| `is_returned` | BOOL | Financed and L2 status Return. |
| `is_fpd` | BOOL | Financed and L2 status FPD (first payment default). |
| `is_new_loan` | BOOL | First appearance of the loan, excluding the opening snapshot. |
| `account_status_l1` | STRING | Detailed credit status as delivered (20 values), for example Existing Active, Inactive 08-14, Blocked 31-60, Write Off, Paid Off Loan. |
| `account_status_l2` | STRING | Portfolio grouping of the L1 status (9 values): Active, Inactive, PAR 7, PAR 30, FPD, FMD, Paid Off, Return, Unknown. |
| `prev_status_l2` | STRING | L2 status at the previous snapshot of the same loan (null at the first). |
| `risk_category` | STRING | Low, Medium, High, Critical or Not rated. Critical: Write Off status, 61+ days past due or Return. High: FPD/FMD or first-default status, or 31-60 days. Medium: 8-30 days, or earlier lateness or payment coverage below 0.8. Low: Paid Off, or current. Not rated: not financed. |
| `risk_rule` | STRING | The rule that set risk_category (R0 to R6). The first matching rule wins. |
| `age_band` | STRING | 18-25, 26-35, 36-45, 46-55, 56+ or Unknown. The brief lists 46-55 and 55+, which overlap at 55, so 55 stays in 46-55. |
| `age_years` | INT64 | Customer age in whole years AT the snapshot date. Null when unknown or outside 18-120. The date of birth itself is not stored. |
| `avg_monthly_income` | FLOAT64 | received / duration_months, KES per month. This is inflow, not verified income. Used for the income bands. |
| `avg_monthly_income_band` | STRING | Income band as in the brief: Below 5,000; 5,000-9,999; 10,000-19,999; 20,000-29,999; 30,000-49,999; 50,000-99,999; 100,000-149,999; 150,000+; or Unknown. |
| `days_past_due` | INT64 | Days behind on payments, set to 0 when arrears are zero or less. |
| `dpd_bucket` | STRING | Days past due grouped: 0, 1-7, 8-30, 31-60, 61-90, 91+. |
| `arrears` | FLOAT64 | Amount the customer is behind on payments at the snapshot date. |
| `balance` | FLOAT64 | Outstanding balance after payments, adjustments, discounts and the deposit. |
| `total_paid` | INT64 | Cumulative amount paid up to the snapshot date, excluding adjustments. |
| `total_due_today` | FLOAT64 | Amount the customer should have paid by the snapshot date under the loan terms. |
| `payment_coverage` | FLOAT64 | total_paid / total_due_today. About 1.0 for loans on track. A payment-history signal. |
| `max_dpd_prior` | INT64 | Highest days past due at earlier snapshots of the same loan (null at the first). Uses past data only. |
| `prior_snapshots_in_arrears` | INT64 | Number of earlier snapshots in which the loan was behind. |
| `loan_first_snapshot_date` | DATE | First snapshot in which the loan appears. |
| `sale_date` | DATE | Date the phone was sold (loan origination). |
| `sale_type` | STRING | Financed, Non Financed or Y Lost, as recorded by Sales. |
| `loan_price` | FLOAT64 | Price of the phone on the installment plan, KES. |
| `cash_price` | FLOAT64 | Cash price of the phone, KES. |
| `loan_term_months` | FLOAT64 | Loan term in months. Null when the delivered term is not a number of months (765 sales, for example STDHIGH). |
| `client_model` | STRING | Customer segment label as delivered by Sales. |
| `business_model` | STRING | Business model label as delivered by Sales ('Not Available' for about 10%). |
| `product_name` | STRING | Phone product name. |
| `return_date_as_of_snapshot` | DATE | Return date, shown only when it is on or before the snapshot date (point-in-time safe). |
| `dq_arrears_zero_days` | BOOL | Flag: arrears above zero but days past due is zero. Mostly small residual amounts. Reported, never changed. |
| `dq_days_zero_arrears` | BOOL | Flag: days past due above zero but arrears are zero or less. Reported, never changed. |
| `dq_negative_amount` | BOOL | Flag: a negative balance, closing balance, total paid, deposit or initial payment on this row. |
| `dq_payment_after_snapshot` | BOOL | Flag: max_payment_date is later than snapshot_date (extract-time leak). |

### `mart_portfolio_metrics`

One row per snapshot with the portfolio health metrics (question 3A).

- **Key:** snapshot_date
- **Built by:** `sql/03_marts/mart_portfolio_metrics.sql`

| Column | Type | Meaning |
|---|---|---|
| `snapshot_date` | DATE | Date of the snapshot, taken from the DATE column of the extract (the file called 30-03 holds 31 March). |
| `financed_loans` | INT64 | Financed loans in the snapshot. |
| `new_financed_loans` | INT64 | Financed loans appearing for the first time. Zero in the opening snapshot, where every loan is existing. |
| `live_loans` | INT64 | Live loans (financed, not Paid Off or Returned). |
| `performing_loans` | INT64 | Live loans that are not lost. |
| `delinquent_7plus_loans` | INT64 | Performing loans 8-90 days past due. |
| `delinquent_30plus_loans` | INT64 | Performing loans 31-90 days past due. |
| `loss_loans` | INT64 | Loans 91+ days past due, including Write Off. |
| `returned_loans` | INT64 | Returned loans. |
| `paid_off_loans` | INT64 | Paid off loans. |
| `fpd_loans` | INT64 | Loans with FPD status. |
| `delinquency_rate_7plus` | FLOAT64 | delinquent_7plus_loans / performing_loans. |
| `par30_rate` | FLOAT64 | delinquent_30plus_loans / performing_loans. |
| `loss_rate_count` | FLOAT64 | loss_loans / financed_loans. Cumulative, because lost loans never leave the extracts. |
| `loss_rate_balance` | FLOAT64 | Balance of lost loans / balance of live loans. |
| `collection_rate` | FLOAT64 | total_paid / total_due_today for performing loans. |
| `fpd_rate` | FLOAT64 | fpd_loans / financed_loans. |
| `retention_cohort_loans` | INT64 | Loans that were Active, Inactive or PAR 7 at the previous snapshot. |
| `retained_loans` | INT64 | Of the cohort, loans that are neither returned nor lost now. |
| `retention_rate` | FLOAT64 | retained_loans / retention_cohort_loans. Null at the first snapshot. |

### `mart_segment_risk`

Risk by age band and income band, with like-for-like benchmarks (question 3A).

- **Key:** snapshot_date + segment_type + segment
- **Built by:** `sql/03_marts/mart_segment_risk.sql`

| Column | Type | Meaning |
|---|---|---|
| `snapshot_date` | DATE | Date of the snapshot, taken from the DATE column of the extract (the file called 30-03 holds 31 March). |
| `segment_type` | STRING | age_band or avg_monthly_income_band. |
| `segment` | STRING | The band within the segment type; Unknown means no demographic data for the loan. |
| `financed_loans` | INT64 | Financed loans in the segment. |
| `performing_loans` | INT64 | Performing loans in the segment. |
| `delinquent_7plus_loans` | INT64 | Performing loans 8-90 days past due in the segment. |
| `delinquent_30plus_loans` | INT64 | Performing loans 31-90 days past due in the segment. |
| `loss_loans` | INT64 | Loans 91+ days past due in the segment. |
| `delinquency_rate_7plus` | FLOAT64 | delinquent_7plus_loans / performing_loans in the segment. |
| `par30_rate` | FLOAT64 | delinquent_30plus_loans / performing_loans in the segment. |
| `loss_rate_count` | FLOAT64 | loss_loans / financed_loans in the segment. |
| `collection_rate` | FLOAT64 | total_paid / total_due_today for performing loans in the segment. |
| `known_avg_delinquency_rate` | FLOAT64 | Delinquency rate across loans that have a known value for this segment type (like for like). |
| `portfolio_delinquency_rate` | FLOAT64 | Delinquency rate across all financed loans. |
| `known_avg_loss_rate` | FLOAT64 | Loss rate across loans with a known value for this segment type. |
| `portfolio_loss_rate` | FLOAT64 | Loss rate across all financed loans. |
| `delinquency_vs_known_avg` | FLOAT64 | Segment delinquency rate / known_avg_delinquency_rate (1.0 = same as average). |
| `loss_vs_known_avg` | FLOAT64 | Segment loss rate / known_avg_loss_rate. |
| `small_sample` | BOOL | True when the segment has fewer than 30 performing loans. Do not quote it. |

### `mart_nps_credit`

Each survey response with the loan's credit state when answered and now (question 3B). No free text.

- **Key:** response_key
- **Built by:** `sql/03_marts/mart_nps_credit.sql`

| Column | Type | Meaning |
|---|---|---|
| `response_key` | STRING | Masked survey submission identifier. |
| `loan_key` | STRING | Masked loan identifier: a keyed hash of the SALE_ID. It joins every table. It cannot be reversed without the secret key. |
| `submitted_date` | DATE | Date the survey was submitted. |
| `matched_snapshot_date` | DATE | Latest snapshot on or before the response date, so credit status is as at the response (no look-ahead). Null if none. |
| `nps_score` | FLOAT64 | Answer to 'how likely are you to recommend ABC Phones' from 0 to 10. Null for the 144 blank answers. |
| `nps_category` | STRING | promoter (9-10), passive (7-8) or detractor (0-6). Null when there is no score. |
| `is_latest_response` | BOOL | True for the most recent response of each loan. Analysis uses these only. |
| `quality_happy` | STRING | Survey answer: happy with product quality and performance. |
| `service_happy` | STRING | Survey answer: happy with service and support. |
| `payment_delay_experienced` | STRING | Survey answer: experienced a delay in payments. |
| `assistance_difficulty` | STRING | Survey answer: had difficulty getting help from customer care (Yes, No, or never looked for help). |
| `battery_issue` | STRING | Survey answer: battery problems. |
| `app_usage` | STRING | Survey answer: has used the ABC Phones app. |
| `preferred_channel` | STRING | Survey answer: preferred communication channel. The option text includes the company support number, which is not personal data. |
| `phone_lock_experienced` | STRING | Survey answer: the phone was locked despite paying. |
| `portfolio_scope` | STRING | Scope at the matched snapshot. Null when the loan was not yet in any snapshot. |
| `risk_category` | STRING | risk_category at the matched snapshot (credit status when the customer answered). |
| `risk_rule` | STRING | The rule that set risk_category (R0 to R6). The first matching rule wins. |
| `account_status_l2` | STRING | L2 status at the matched snapshot. |
| `dpd_bucket` | STRING | Days past due bucket at the matched snapshot. |
| `days_past_due` | INT64 | Days past due at the matched snapshot (0 when no arrears). |
| `payment_coverage` | FLOAT64 | total_paid / total_due_today at the matched snapshot. |
| `age_band` | STRING | Age band at the matched snapshot. |
| `avg_monthly_income_band` | STRING | Income band of the loan. |
| `risk_category_latest` | STRING | risk_category at the latest snapshot. |
| `status_l2_latest` | STRING | account_status_l2 at the latest snapshot. |
| `dpd_bucket_latest` | STRING | dpd_bucket at the latest snapshot. |

## Operational tables (in abc_staging)

### `load_audit`

One row per raw file per load: name, checksum, size.

- **Key:** run_id + file_name
- **Built by:** `data_cleaning.py`

| Column | Type | Meaning |
|---|---|---|
| `run_id` | STRING | Identifier of the pipeline or check run. |
| `run_ts` | TIMESTAMP | When the run happened (UTC). |
| `file_name` | STRING | Raw file name. |
| `sha256` | STRING | SHA-256 checksum of the raw file, to detect changed or repeated files. |
| `size_bytes` | INT64 | Raw file size in bytes. |

### `dq_results`

One row per quality check per run.

- **Key:** run_id + check_name
- **Built by:** `quality_checks.py`

| Column | Type | Meaning |
|---|---|---|
| `run_id` | STRING | Identifier of the pipeline or check run. |
| `run_ts` | TIMESTAMP | When the run happened (UTC). |
| `check_name` | STRING | Name of the quality check, for example uniqueness.credit_loan_snapshot. |
| `severity` | STRING | critical (blocks the mart refresh) or warning. |
| `observed` | FLOAT64 | What was measured (a count or a share of bad rows). The check passes when observed is at or below threshold. |
| `threshold` | FLOAT64 | Largest acceptable observed value. |
| `passed` | BOOL | True when observed <= threshold. |
| `description` | STRING | What the check looks for. |
