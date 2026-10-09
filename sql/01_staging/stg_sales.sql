-- sql/01_staging/stg_sales.sql
--
-- SCHEMA CONTRACT for {{STG}}.stg_sales
-- One row per sale, from the Sales Details sheet. Key: loan_key (the SALE_ID, masked).
--
-- data_cleaning.py builds this table in Python (parsing, masking and redaction are done before the load) and loads
-- it with WRITE_TRUNCATE, so this file is not run by the pipeline. It is the agreed shape of the table:
-- quality_checks.py compares it with BigQuery's INFORMATION_SCHEMA on every run (check schema.stg_sales) and
-- fails if a column is missing, extra or of a different type. Column meanings are in docs/data_dictionary.md.

CREATE TABLE IF NOT EXISTS {{STG}}.stg_sales (
  loan_key                 STRING,
  sale_date                DATE,
  returned                 BOOL,
  return_date              DATE,
  sale_type                STRING,
  seller_type              STRING,
  return_policy_compliance STRING,
  cash_price               FLOAT64,
  loan_price               FLOAT64,
  client_model             STRING,
  business_model           STRING,
  loan_term_raw            STRING,
  product_name             STRING,
  model                    STRING,
  loan_term_months         FLOAT64,
  dq_return_before_sale    BOOL
);
