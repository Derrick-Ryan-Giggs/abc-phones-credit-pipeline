

# Dashboard: ABC Phones credit portfolio

A three-page Looker Studio report on top of the BigQuery marts. It shows the same numbers as the deck and `outputs/portfolio_metrics.csv`, so anyone can check one against the other.

- **Tool:** Looker Studio (free), report name "ABC credit portfolio"
- **Reads from:** `abc-credit-portfolio-rg.abc_marts` (BigQuery)
- **Credentials:** owner's credentials, so viewers need no BigQuery access
- **Access:** private. Shared only with named people
- **Freshness:** Looker Studio caches data for up to 12 hours. Rebuild the marts with `scripts/run_pipeline.py`, then use the report's "Refresh data" option
- **Screenshots:** `dashboard/screenshots/page1_portfolio.png`, `page2_segments.png`, `page3_nps.png`

## Data sources

| Name in the report | BigQuery source | Used on |
|---|---|---|
| `portfolio_metrics` | table `abc_marts.mart_portfolio_metrics` (5 rows, one per snapshot) | Page 1 |
| `segments_2025_sales` | custom query on `abc_marts.fct_loan_snapshot` (below) | Page 2 |
| `nps_credit` | custom query on `abc_marts.mart_nps_credit` (below) | Page 3 |

### Why page 2 is a custom query

`mart_segment_risk` covers all financed loans, including loans sold before 2025 whose age and income are unknown. The deck and `analysis.py` use only loans sold since 2025-01-01, because demographics exist only for those. To keep the dashboard and the deck identical, page 2 is built from the loan-level table, filtered to the same loans. For example, "Below 5,000" income reads 24.7% here and about 26.4% in `mart_segment_risk`. Neither is wrong. They cover different loans.

```sql
WITH base AS (
  SELECT * FROM `abc-credit-portfolio-rg.abc_marts.fct_loan_snapshot`
  WHERE snapshot_date = DATE '2025-12-30'
    AND is_financed
    AND sale_date >= DATE '2025-01-01'
)
SELECT 'Income' AS segment_type, avg_monthly_income_band AS segment,
       COUNTIF(is_live) AS live_loans,
       COUNTIF(is_performing) AS performing_loans,
       COUNTIF(is_delinquent_7plus) AS delinquent_loans,
       COUNTIF(is_loss_91plus) AS loss_loans
FROM base
WHERE avg_monthly_income_band IS NOT NULL AND avg_monthly_income_band <> 'Unknown'
GROUP BY segment
UNION ALL
SELECT 'Age', age_band,
       COUNTIF(is_live), COUNTIF(is_performing),
       COUNTIF(is_delinquent_7plus), COUNTIF(is_loss_91plus)
FROM base
WHERE age_band IS NOT NULL AND age_band <> 'Unknown'
GROUP BY age_band
```

### Why page 3 is a custom query

The NPS source selects only the columns the report needs. It leaves out `preferred_channel` (it holds the company hotline number) and every free-text field. Responses are masked and no customer identifier is included.

```sql
SELECT submitted_date, matched_snapshot_date, nps_score, nps_category,
       is_latest_response, portfolio_scope, risk_category, days_past_due,
       dpd_bucket, account_status_l2, age_band, avg_monthly_income_band,
       quality_happy, service_happy, payment_delay_experienced,
       assistance_difficulty, battery_issue, app_usage, phone_lock_experienced
FROM `abc-credit-portfolio-rg.abc_marts.mart_nps_credit`
```

## Calculated fields

| Source | Field | Formula |
|---|---|---|
| `segments_2025_sales` | Delinquency rate | `SUM(delinquent_loans) / SUM(performing_loans)` |
| `segments_2025_sales` | Loss rate | `SUM(loss_loans) / SUM(live_loans)` |
| `segments_2025_sales` | Band order | `CASE` that numbers each band in its natural order (income 1 to 8, age 1 to 5) so bars are not sorted alphabetically |
| `nps_credit` | NPS | `100 * (SUM(CASE WHEN nps_score >= 9 THEN 1 ELSE 0 END) - SUM(CASE WHEN nps_score <= 6 THEN 1 ELSE 0 END)) / COUNT(nps_score)` |
| `nps_credit` | Average score | `AVG(nps_score)` |
| `nps_credit` | Lateness | `CASE` on `days_past_due`: 0 = "1 Up to date", 1-30 = "2 Late 1-30 days", 31-90 = "3 Late 31-90 days", above 90 = "4 Late 91+ days" |

Rates on page 2 are ratios of sums, never averages of rates, so small groups are not over-weighted.

## Pages

### Page 1: Portfolio health (December 2025 snapshot)

- **Six scorecards,** each limited to the 2025-12-30 snapshot with the aggregation set to Average: Behind on payments, Seriously late (31-90 days), Loans lost, Money collected, First payment missed, Customers retained.
- **Six trend lines,** one per rate across the five snapshots (1 Jan, 31 Mar, 30 Jun, 30 Sep, 30 Dec 2025). Each has its own colour and the title says whether lower or higher is better. Missing dates are interpolated so the line does not fall to zero between snapshots.
- Retention starts at the March snapshot because it compares each snapshot with the one before.

| Card | Field in `mart_portfolio_metrics` | December value |
|---|---|---|
| Behind on payments | `delinquency_rate_7plus` | 17.6% |
| Seriously late (31-90 days) | `par30_rate` | 11.3% |
| Loans lost | `loss_rate_count` | 26.3% |
| Money collected | `collection_rate` | 94.2% |
| First payment missed | `fpd_rate` | 5.8% |
| Customers retained | `retention_rate` | 95.8% |

### Page 2: Who falls behind? Risk by income and age

- Two bar charts: delinquency rate by monthly income band and by age band. Each has its own `segment_type` filter and is sorted by `Band order`.
- A table of loan counts (`live_loans`, `performing_loans`), `Delinquency rate` and `Loss rate` for each group.
- A note box states the scope: loans sold since 1 Jan 2025, December snapshot, and that differences between small groups are not all statistically significant.
- Reading it: delinquency falls as income rises, from 24.7% in the lowest band to 12.9% to 15.0% in the highest two. By age, 18-25 (20.2%) and 56+ (20.6%) fall behind more than 26-55 (15.5% to 16.9%). The 56+ group has only 73 performing loans.

### Page 3: Do customers who fall behind score us lower?

- Average satisfaction score and NPS by how late the customer is, in four groups.
- Three charts of the average score by yes or no answer to: trouble getting customer care help, payment delay experienced, phone lock experienced.
- Every chart on this page is filtered to `is_latest_response = true` and `portfolio_scope = financed`, so each customer counts once, at their latest answer.
- A text box carries the recommendation: contact customers in the first 7 days of arrears, make customer care help easy to reach, offer a simple payment plan, and test it against a control group.

| Group | Average score | NPS |
|---|---|---|
| Up to date | 6.8 | +6.5 |
| Late 1-30 days | 6.1 | about -5 |
| Late 31-90 days | 5.7 | about -8 |
| Late 91+ days | 4.3 | -39 |

## Metric definitions

| Metric | Definition |
|---|---|
| Live loan | Financed loan that is not Paid Off or Return |
| Loss | Live and (status Write Off or 91+ days past due) |
| Performing | Live and not loss |
| Behind on payments (delinquency) | Performing loans 8 to 90 days past due, divided by performing loans |
| Seriously late (par30) | Performing loans 31 to 90 days past due, divided by performing loans |
| Money collected | Total paid divided by total due today, on performing loans |
| First payment missed (FPD) | Loans that missed the first payment, divided by financed loans |
| Customers retained | Of loans Active, Inactive or PAR 7 at the previous snapshot, the share not Returned and not loss now |
| NPS | Share scoring 9 to 10 minus share scoring 0 to 6, times 100 |

Full definitions and the reasoning behind them: `docs/assumptions.md` and `docs/data_dictionary.md`.

## Privacy

- Every identifier is a keyed hash. No names, phone numbers, emails, dates of birth, or seller names are loaded.
- The dashboard shows only aggregates. No loan-level table is on any page.
- The report is private. Do not set sharing to "anyone with the link" until the case study is submitted.

## Rebuilding the dashboard

1. Run `uv run python scripts/run_pipeline.py` (builds staging, runs the 48 quality checks, builds the marts).
2. Open the report and click Refresh data.
3. If a mart column is renamed, edit the data source (Resource, then Manage added data sources) and refresh its fields.