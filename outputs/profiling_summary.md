# Data profiling summary

Row counts, column types, null shares and join-key integrity. Full report: run `scripts/data_profiling.py`.

## 1. Row counts

```
               table   rows  columns
credit_all_snapshots 71,456       34
 sales_Sales Details 20,747       16
        sales_Gender 49,804        3
           sales_DOB 57,130        4
  sales_Income Level 22,839        6
                 nps  4,129       17
```

## 2. Column profiles


### credit_all_snapshots

```
                         column        kind  null_pct  null_like  unique  ws_issue                                                                                                         detail
                        LOAN_ID     text/id      0.00          0   20742         0                                                                  (values hidden: identifier, PII or free text)
                           DATE        date      0.00          0       5         0                                                                       ISO 0 | slash 71456 [M/D/Y] | unparsed 0
                   CUSTOMER_AGE     numeric      0.00          0     964         0                                                                  min 0.00 | max 1,056.00 | mean 295.01 | neg 0
                     TOTAL_PAID     numeric      0.00          0   11106         0                                                       min -20,499.00 | max 222,159.00 | mean 36,438.01 | neg 5
                TOTAL_DUE_TODAY     numeric      0.04          0    5569         0                                                         min 3,099.00 | max 334,219.00 | mean 50,379.25 | neg 0
                        BALANCE     numeric      0.01          0   10383         0                                                      min -81,294.00 | max 205,019.00 | mean 34,085.65 | neg 76
                  DAYS_PAST_DUE     numeric      0.00          0     898         0                                                                  min 0.00 | max 1,048.00 | mean 108.60 | neg 0
                CLOSING_BALANCE     numeric      0.01          0    8793         0                                                           min -1.00 | max 205,019.00 | mean 30,503.74 | neg 15
                        ADVANCE     numeric      0.00          0    2121         0                                                                 min 0.00 | max 91,254.00 | mean 442.28 | neg 0
            BALANCE_DUE_TO_DATE     numeric      0.04          0   11025         0                                                  min -205,019.00 | max 91,254.00 | mean -13,708.34 | neg 41610
                        ARREARS     numeric      0.00          0    8905         0                                                             min 0.00 | max 205,019.00 | mean 14,145.25 | neg 0
             BALANCE_DUE_STATUS categorical      0.00          0       3         0                                                                 Arrears=41610; up to date=17754; advance=12092
                        PAYMENT     numeric      0.00          0     472         0                                                                  min 0.00 | max 47,499.00 | mean 74.86 | neg 0
               EXPECTED_PAYMENT     numeric      0.00          0     294         0                                                                 min 0.00 | max 47,499.00 | mean 171.86 | neg 0
                  FIRST_PAYMENT     numeric      0.00          0       2         0                                                                        min 0.00 | max 1.00 | mean 0.00 | neg 0
         FIRST_EXPECTED_PAYMENT     numeric      0.00          0       2         0                                                                        min 0.00 | max 1.00 | mean 0.00 | neg 0
              ACCOUNT_STATUS_L1 categorical      0.00          0      20         0 Existing Active=20211; Paid Off Loan=12137; Write Off=11816; New Active=4180; First Payment Default=4160; P...
              ACCOUNT_STATUS_L2 categorical      0.00          0       9         0         Active=24391; Paid Off=15413; PAR 30=15135; Return=5766; FPD=4160; FMD=3208; Inactive=1806; PAR 7=1569
                    RETURN_DATE     text/id     90.36          0     505         0                                                             patterns: 9/99/9999 42%; 99:99.9 25%; 9/9/9999 14%
                      SALE_DATE        date      0.00          0     939         0                                                                       ISO 0 | slash 71456 [M/D/Y] | unparsed 0
              CREDIT_CHECK_DONE categorical      0.00          0       4         0                                                                Y LOAN=67329; Y CASH=3443; Y LOST=676; Z DEMO=8
                 PAYMENT_AMOUNT     numeric     95.57          0     461         0                                                               min 0.00 | max 47,499.00 | mean 1,644.37 | neg 0
              ADJUSTMENT_AMOUNT     numeric     95.57          0      17         0                                                                  min 0.00 | max 22,020.00 | mean 47.12 | neg 0
              PREPAYMENT_AMOUNT     numeric      0.00          0      26         0                                                                  min 0.00 | max 67,049.00 | mean 34.30 | neg 0
                        DEPOSIT     numeric      0.01          0     602         0                                                              min -1.00 | max 55,499.00 | mean 9,443.38 | neg 5
                    WEEKLY_RATE     numeric      0.01          0     307         0                                                              min 240.00 | max 9,060.00 | mean 1,232.49 | neg 0
                  CREDIT_EXPIRY        date      0.00          0    1051         0                                                                       ISO 0 | slash 71456 [M/D/Y] | unparsed 0
              NEXT_INVOICE_DATE        date      0.00          0      35         0                                                                       ISO 0 | slash 71456 [M/D/Y] | unparsed 0
                       DISCOUNT     numeric      0.00          0     584         0                                                                 min 0.00 | max 86,870.00 | mean 376.31 | neg 0
             OVERPAYMENT_AMOUNT     numeric      0.00          0     231         0                                                                  min 0.00 | max 91,254.00 | mean 26.76 | neg 0
               MAX_PAYMENT_DATE        date      1.05          0     909         0                                                                       ISO 0 | slash 70707 [M/D/Y] | unparsed 0
                    INITIAL_PAY     numeric      0.00          0     947         0                                                       min -2,261.00 | max 131,999.00 | mean 12,478.94 | neg 20
TOTAL_PAID_WITH_ADJUSTMENTS_15D     numeric      0.00          0   10921         0                                                       min -20,499.00 | max 222,159.00 | mean 36,675.22 | neg 5
                    Unnamed: 28       empty    100.00          0       0         0                                                                                                               
```

### sales_Sales Details

```
                  column        kind  null_pct  null_like  unique  ws_issue                                                                                                         detail
                 SALE_ID     text/id      0.00          0   20747         0                                                                  (values hidden: identifier, PII or free text)
               SALE_DATE        date      0.00          0     939         0                                                                         ISO 20747 | slash 0 [n/a] | unparsed 0
                RETURNED categorical      0.00          0       2         0                                                                                         False=19004; True=1743
             RETURN_DATE        date     91.59          0     530         0                                                                          ISO 1744 | slash 0 [n/a] | unparsed 0
               SALE_TYPE categorical      0.01          0       3         0                                                                   Financed=19570; Non Financed=992; Y Lost=183
                  SELLER     text/id      0.37          0     518      1080                                                                  (values hidden: identifier, PII or free text)
             SELLER_TYPE categorical     23.96          0       5         0 Sales Executive=10517; Telesales Executive=3642; SFM (Sales Force Manager)=1554; Commission Merchant=62; Ri...
RETURN_POLICY_COMPLIANCE categorical     91.59          0       2         0                                                                              out of policy=1260; in policy=484
              CASH_PRICE     numeric      0.01          0     259         0                                                         min 7,999.00 | max 215,499.00 | mean 42,392.58 | neg 0
              LOAN_PRICE     numeric      0.01          0     930         0                                                        min 15,159.00 | max 334,219.00 | mean 73,090.44 | neg 0
            CLIENT_MODEL categorical      0.12          0       3         0                                                                                      1C=16099; 3C=4462; 2C=161
          BUSINESS_MODEL categorical      0.00          0       7         0                              1P1C=12721; 1P3C=3479; Not Available=2111; 3P1C=1662; 3P3C=615; 1P2C=132; 3P2C=27
               LOAN_TERM categorical      0.02          0       3         0                                                                                 12M=19418; STDHIGH=761; 3M=564
            PRODUCT_NAME     text/id      0.01          0     132         0                                              patterns: A-A-A99-A-999A 20%; A-A-99-A-999A 19%; A-A-A99-999A 18%
                   MODEL     text/id      0.01          0      82         0                                                                   patterns: A-A99-A 20%; A-99-A 19%; A-A99 19%
                 Loan Id     text/id      0.00         51   20692         0                                                                  (values hidden: identifier, PII or free text)
```

### sales_Gender

```
     column        kind  null_pct  null_like  unique  ws_issue                                                         detail
    Loan Id     text/id      0.00      34908   10498         0                  (values hidden: identifier, PII or free text)
Citizenship categorical      0.03          0       3         0 KENYAN=46075; CITIZEN=3545; Kenyan=168 | CASE/SPACING VARIANTS
     Gender categorical      0.04          0       5         0          Male=31329; Female=18276; M=156; F=12; Unspecified=10
```

### sales_DOB

```
       column        kind  null_pct  null_like  unique  ws_issue                                          detail
          _id     text/id      0.00          0   57130         0   (values hidden: identifier, PII or free text)
     provider categorical      0.00          0       3         0 SPINMOBILE=39244; TRANSUNION=17302; SMILEID=584
date_of_birth        date      0.37          0   17087         0          ISO 56921 | slash 0 [n/a] | unparsed 0
      Loan Id     text/id      0.00      43568   11218         0   (values hidden: identifier, PII or free text)
createdAt UTC        date      0.00          0   57130         0          ISO 57130 | slash 0 [n/a] | unparsed 0
```

### sales_Income Level

```
                     column    kind  null_pct  null_like  unique  ws_issue                                                          detail
                    Loan Id text/id       0.0      10954   10610         0                   (values hidden: identifier, PII or free text)
                   Duration numeric       0.0          0      23         0                        min 1.00 | max 24.00 | mean 8.57 | neg 0
                   Received numeric       0.0          0   21191         0          min 0.00 | max 38,271,145.81 | mean 700,564.82 | neg 0
Persons Received From Total numeric       0.0          0   20993         0          min 0.00 | max 37,895,675.00 | mean 625,723.15 | neg 0
             Banks Received numeric       0.0          0   16632         0          min 0.00 | max 26,076,151.00 | mean 349,548.46 | neg 0
   Paybills Received Others numeric       0.0          0   12560         0 min -1,975,599.00 | max 22,007,251.25 | mean 92,289.03 | neg 35
```

### nps

```
                                       column        kind  null_pct  null_like  unique  ws_issue                                                                                                         detail
                                Submission ID     text/id      0.00          0    4129         0                                                                  (values hidden: identifier, PII or free text)
                                Respondent ID     text/id      0.00          0    3756         0                                                                  (values hidden: identifier, PII or free text)
                                 Submitted at        date      0.00          0    3087         0                                                                          ISO 4129 | slash 0 [n/a] | unparsed 0
                                      Loan Id     text/id      0.00          0    3532         0                                                                  (values hidden: identifier, PII or free text)
Using a scale from 0 (not likely) to 10 (very     numeric      3.49          0      11         0                                                                       min 0.00 | max 10.00 | mean 6.78 | neg 0
      What is the main reason for your score?     text/id     71.23          8    1063         0                                                                  (values hidden: identifier, PII or free text)
What is one thing we could do to improve your     text/id     72.32         13    1071         0                                                                  (values hidden: identifier, PII or free text)
Are you happy with the quality and performanc categorical     36.38          0       2         0                                                                                               Yes=1999; No=628
Are you happy with the service and support pr categorical     36.84          0       2         0                                                                                               Yes=2037; No=571
Have you ever experienced a delay in your pay categorical     42.63          0       2         0                                                                                               No=1647; Yes=722
Have you ever had difficulty getting assistan categorical     43.04          0       3         0                                                           No=1460; Yes=621; No, I have never looked for cu=271
(If Yes) – Please describe the challenge you      text/id     46.48        299    1343         0                                                                  (values hidden: identifier, PII or free text)
Have you experienced any battery-related issu categorical     49.60          0       2         0                                                                                               No=1293; Yes=788
Have you used the MoPhones app (MoApp) to man categorical     50.11          0       3         0          Yes, and I am satisfied with t=1419; No, I have never used it=407; Yes, but I am not satisfied wi=234
Which communication channel do you prefer whe categorical     50.67          0       5         0 Phone Call – +254 728 444 442 =1046; MoPhones App=468; Free SMS – 25044=232; Reach Out via a Sales Agent=23...
Have you ever had your phone lock despite mak categorical     50.84          0       2         0                                                                                               No=1467; Yes=563
                          Any other Feedback?     text/id     51.34        294    1167         0                                                                  (values hidden: identifier, PII or free text)
```

## 10. Join keys across datasets

Key integrity and cardinality against ALL credit snapshots:
```
     table.key  rows  blank_or_NA_keys  unique_keys  extra_rows_on_dup_keys credit_loans_covered  orphan_keys_not_in_credit
 sales.Loan Id 20747                51        20691                       5                99.7%                          2
gender.Loan Id 49804             34908        10497                    4399                50.6%                          0
   dob.Loan Id 57130             43568        11217                    2345                54.1%                          0
income.Loan Id 22839             10954        10609                    1276                51.1%                          0
   nps.Loan Id  4129                 0         3532                     597                17.0%                          0
 sales.SALE_ID 20747                 0        20747                       0               100.0%                          5
```
Share of each snapshot's loans found in each table:
```
     table.key 2025-01-01 2025-03-30 2025-06-30 2025-09-30 2025-12-30
 sales.Loan Id     100.0%     100.0%     100.0%     100.0%      99.7%
gender.Loan Id      12.7%      22.3%      34.1%      42.5%      50.6%
   dob.Loan Id      12.0%      24.7%      37.0%      46.0%      54.1%
income.Loan Id       9.9%      22.9%      34.9%      43.2%      51.1%
   nps.Loan Id       8.8%      12.4%      16.0%      18.6%      17.0%
 sales.SALE_ID     100.0%     100.0%     100.0%     100.0%     100.0%
```
WARNING: join key blank or #N/A on most rows in ['gender.Loan Id', 'dob.Loan Id']. Those sheets cannot be joined to credit data for most rows.
Check section 9 (formula columns) and whether rows line up by position with Sales Details.
Row counts for comparison: sales.Loan Id=20,747; gender.Loan Id=49,804; dob.Loan Id=57,130; income.Loan Id=22,839; nps.Loan Id=4,129; sales.SALE_ID=20,747