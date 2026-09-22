"""
SQL for the dashboard.

1. FRESHNESS  - last date with sales per channel (cheap, partition-pruned).
2. SUMMARY    - main sales table, date x channel x category, for a date window.
3. WEEKLY     - weekly-refreshed gross for quick commerce / Myntra / Nykaa / Tira.
4. ADS        - daily ad spends.

Everything visual is derived in pandas from SUMMARY, so each page load costs at
most one BigQuery job (the historical window is cached for hours).

NULL handling: BigQuery SUM() over only-NULL input returns NULL, so a metric
that a channel does not maintain (e.g. orders) stays NULL rather than 0.
"""
from __future__ import annotations

import config as c


def _opt(col: str, agg: str) -> str:
    return f"{agg}({col})" if col else "CAST(NULL AS FLOAT64)"


def summary_sql() -> str:
    category = f"CAST({c.COL_CATEGORY} AS STRING)" if c.COL_CATEGORY else "CAST(NULL AS STRING)"
    return f"""
SELECT
  {c.COL_DATE}                  AS date,
  {c.COL_CHANNEL}               AS channel,
  {category}                    AS category,
  SUM({c.COL_MRP})              AS mrp_sales,
  SUM({c.COL_GROSS})            AS gross_sales,
  SUM({c.COL_QTY})              AS quantity,
  {_opt(c.COL_ORDERS, c.AGG_ORDERS)} AS orders,
  {_opt(c.COL_TARGET, c.AGG_TARGET)} AS target_sales
FROM `{c.table_fqn()}`
WHERE {c.COL_DATE} BETWEEN @start AND @end
GROUP BY date, channel, category
""".strip()


def freshness_sql() -> str:
    return f"""
SELECT
  {c.COL_CHANNEL} AS channel,
  MAX(IF({c.COL_MRP} IS NOT NULL, {c.COL_DATE}, NULL)) AS last_date,
  MIN(IF({c.COL_MRP} IS NOT NULL, {c.COL_DATE}, NULL)) AS first_date
FROM `{c.table_fqn()}`
WHERE {c.COL_DATE} <= CURRENT_DATE('{c.TIMEZONE}')
GROUP BY channel
HAVING MAX(IF({c.COL_MRP} IS NOT NULL, {c.COL_DATE}, NULL)) IS NOT NULL
""".strip()



def weekly_sql() -> str:
    category = f"CAST({c.W_COL_CATEGORY} AS STRING)" if c.W_COL_CATEGORY else "CAST(NULL AS STRING)"
    return f"""
SELECT
  {c.W_COL_DATE}                AS date,
  {c.W_COL_CHANNEL}             AS channel,
  {category}                    AS category,
  SUM({c.W_COL_GROSS})          AS gross_sales
FROM `{c.fqn(c.BQ_WEEKLY_TABLE)}`
WHERE {c.W_COL_DATE} BETWEEN @start AND @end
GROUP BY date, channel, category
""".strip()


def ads_sql() -> str:
    channel = f"CAST({c.AD_COL_CHANNEL} AS STRING)" if c.AD_COL_CHANNEL else "CAST(NULL AS STRING)"
    return f"""
SELECT
  {c.AD_COL_DATE}               AS date,
  {channel}                     AS channel,
  SUM({c.AD_COL_SPEND})         AS ad_spend
FROM `{c.fqn(c.BQ_AD_TABLE)}`
WHERE {c.AD_COL_DATE} BETWEEN @start AND @end
GROUP BY date, channel
""".strip()



def columns_sql() -> str:
    """Columns actually present in the dashboard's tables, so optional ones can be switched off."""
    return f"""
SELECT table_name, column_name
FROM `{c.GCP_PROJECT}.{c.BQ_DATASET}.INFORMATION_SCHEMA.COLUMNS`
WHERE table_name IN UNNEST(@tables)
""".strip()



def targets_sql() -> str:
    return f"""
SELECT
  DATE({c.T_COL_DATE})          AS date,
  {c.T_COL_CHANNEL}             AS channel,
  SUM({c.T_COL_TARGET})         AS target_sales,
  {("SUM(" + c.T_COL_ACHIEVED + ")") if c.T_COL_ACHIEVED else "CAST(NULL AS FLOAT64)"} AS achieved_sales
FROM `{c.fqn(c.BQ_TARGET_TABLE)}`
WHERE DATE({c.T_COL_DATE}) BETWEEN @start AND @end
GROUP BY date, channel
""".strip()



def aop_sql() -> str:
    """Monthly AOP by channel. Months are parsed in Python since the text format varies."""
    return f"""
SELECT
  CAST({c.A_COL_FY} AS STRING)    AS fy,
  CAST({c.A_COL_MONTH} AS STRING) AS month,
  {c.A_COL_CHANNEL}               AS channel,
  SUM({c.A_COL_REVENUE})          AS aop
FROM `{c.fqn(c.BQ_AOP_TABLE)}`
GROUP BY fy, month, channel
""".strip()
