"""
Central configuration for the Kimirica Executive Sales Dashboard.

Every value can be overridden through Streamlit secrets (.streamlit/secrets.toml)
or environment variables, so nothing environment-specific lives in code.
"""
from __future__ import annotations

import datetime as dt
import os
import re

import streamlit as st


SECRETS_ERROR = ""  # set when .streamlit/secrets.toml exists but can't be parsed


def _load_secrets() -> dict:
    global SECRETS_ERROR
    try:
        return {k: st.secrets[k] for k in st.secrets.keys()}
    except Exception as exc:
        msg = str(exc)
        if "No secrets" not in msg and "not found" not in msg.lower():
            SECRETS_ERROR = msg
        return {}


_SECRETS = _load_secrets()


def _get(key: str, default=None):
    """Read a setting from st.secrets first, then the environment."""
    if key in _SECRETS:
        return _SECRETS[key]
    return os.getenv(key, default)


def _bool(value) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _col(key: str, default: str) -> str:
    """Column names are interpolated into SQL, so only plain identifiers are allowed."""
    value = str(_get(key, default) or "").strip()
    if value and not _IDENT.match(value):
        raise ValueError(f"{key}={value!r} is not a valid BigQuery column name")
    return value


def _agg(key: str) -> str:
    value = str(_get(key, "SUM")).strip().upper()
    if value not in {"SUM", "MAX"}:
        raise ValueError(f"{key} must be SUM or MAX, got {value!r}")
    return value


# --------------------------------------------------------------------------- #
# Data source
# --------------------------------------------------------------------------- #
GCP_PROJECT: str = str(_get("GCP_PROJECT", "") or "")
BQ_DATASET: str = str(_get("BQ_DATASET", "") or "")
BQ_TABLE: str = str(_get("BQ_TABLE", "Executive_Sales_Master") or "")
BQ_LOCATION: str = str(_get("BQ_LOCATION", "") or "")  # blank = let BigQuery resolve it

# Force synthetic data (useful for design reviews). If BigQuery is not
# configured at all, the app also falls back to demo data and says so.
DEMO_MODE: bool = _bool(_get("DEMO_MODE", "false"))

TIMEZONE = "Asia/Kolkata"


def bq_configured() -> bool:
    return bool(GCP_PROJECT and BQ_DATASET and BQ_TABLE)


def _tbl(key: str, default: str = "") -> str:
    value = str(_get(key, default) or "").strip()
    if value and not re.match(r"^[A-Za-z0-9_\-.]+$", value):
        raise ValueError(f"{key}={value!r} is not a valid table name")
    return value


# Weekly-updated gross table (quick commerce, Myntra, Nykaa, Tira). Leave blank if
# those channels' gross is maintained inside the main sales table instead.
BQ_WEEKLY_TABLE = _tbl("BQ_WEEKLY_TABLE", "Executive_Weekly_Gross_Sales")
# Daily ad spends table. Leave blank to hide the ad-spend card and rows.
BQ_AD_TABLE = _tbl("BQ_AD_TABLE", "Executive_Spends_Master")
# Daily AOP target vs achievement (product grain; aggregated to date x channel).
BQ_TARGET_TABLE = _tbl("BQ_TARGET_TABLE", "AOP_Daily_Target_vs_Achievement")
# Monthly AOP plan (product x channel x month); month and year AOP totals come from here.
BQ_AOP_TABLE = _tbl("BQ_AOP_TABLE", "AOP_targets")
# Raw Shopify order-line table -- the only trustworthy source of Website / EBO(Stores) order
# counts. Executive_Sales_Master's own `orders` column is per category row, so summing it across
# a channel double- (or N-) counts any order whose lines span more than one category. Leave blank
# to fall back to Executive_Sales_Master's orders for these two channels.
BQ_ORDERS_TABLE = _tbl("BQ_ORDERS_TABLE", "shopify_kimirica.master_orders_flat")
AUTHORITATIVE_ORDER_CHANNELS = ["Website", "EBO(Stores)"]


def fqn(table: str) -> str:
    """Accepts table, dataset.table or project.dataset.table."""
    parts = table.split(".")
    if len(parts) == 3:
        return table
    if len(parts) == 2:
        return f"{GCP_PROJECT}.{table}"
    return f"{GCP_PROJECT}.{BQ_DATASET}.{table}"


def table_fqn() -> str:
    return fqn(BQ_TABLE)


# --------------------------------------------------------------------------- #
# Schema mapping: main daily sales table (BQ_TABLE)
# Expected grain: one row per date x channel (x category, if present).
# Set COL_CATEGORY / COL_ORDERS / COL_TARGET to "" if the table lacks them.
# --------------------------------------------------------------------------- #
COL_DATE = _col("COL_DATE", "sales_date")
COL_CHANNEL = _col("COL_CHANNEL", "channel")
COL_CATEGORY = _col("COL_CATEGORY", "category")
COL_MRP = _col("COL_MRP", "mrp_sales")
COL_GROSS = _col("COL_GROSS", "gross_sales")
COL_QTY = _col("COL_QTY", "quantity_sold")
COL_ORDERS = _col("COL_ORDERS", "orders")
COL_TARGET = _col("COL_TARGET", "")             # daily AOP target inside the sales table, if any

# How orders / targets roll up across category rows of the same date x channel.
#   SUM -> values are allocated per category row (default)
#   MAX -> the channel-level value is repeated on every category row
AGG_ORDERS = _agg("AGG_ORDERS")
AGG_TARGET = _agg("AGG_TARGET")

# Weekly gross table (BQ_WEEKLY_TABLE)
W_COL_DATE = _col("W_COL_DATE", "sales_date")
W_COL_CHANNEL = _col("W_COL_CHANNEL", "channel")
W_COL_CATEGORY = _col("W_COL_CATEGORY", "category")  # "" if the weekly table is channel-level
W_COL_GROSS = _col("W_COL_GROSS", "gross_sales")

# AOP target table (BQ_TARGET_TABLE)
T_COL_DATE = _col("T_COL_DATE", "sales_date")        # DATE or DATETIME
T_COL_CHANNEL = _col("T_COL_CHANNEL", "Channel")
T_COL_TARGET = _col("T_COL_TARGET", "Target_Revenue")
T_COL_ACHIEVED = _col("T_COL_ACHIEVED", "Achieved_Revenue")  # "" -> achievement uses MRP sales

# Monthly AOP plan (BQ_AOP_TABLE)
A_COL_FY = _col("A_COL_FY", "Financial_Year")        # e.g. '2026-27'
A_COL_MONTH = _col("A_COL_MONTH", "Month")           # e.g. 'Apr', 'April', 'Apr-26', '2026-04'
A_COL_CHANNEL = _col("A_COL_CHANNEL", "Channel")
A_COL_REVENUE = _col("A_COL_REVENUE", "Revenue")

# Ad spends table (BQ_AD_TABLE)
AD_COL_DATE = _col("AD_COL_DATE", "spend_date")
AD_COL_CHANNEL = _col("AD_COL_CHANNEL", "channel")   # "" if spends are company-wide
AD_COL_SPEND = _col("AD_COL_SPEND", "spend")

# --------------------------------------------------------------------------- #
# Business rules
# --------------------------------------------------------------------------- #
# Net sales = gross sales with GST removed.
GST_RATE = float(_get("GST_RATE", 0.18))

# AOP targets are set on this metric.
TARGET_METRIC = "mrp_sales"

# Channels whose latest loaded date is detected at runtime. If Amazon-VC only has data
# to 14 Sep while the dashboard is at 16 Sep, its MTD ends on 14 Sep and its LMTD / LY /
# year-to-date windows end on the same day number, so comparisons stay like-for-like.
DYNAMIC_LAG_CHANNELS = ["Amazon-VC"]
# Normal delay per channel; only delays beyond this are flagged as late.
EXPECTED_LAG_DAYS: dict[str, int] = {"Amazon-VC": 1}

# Gross sales fall back in this order: sales table -> weekly gross table ->
# daily MRP x (1 - the channel's discount over the last EST_LOOKBACK_DAYS of actuals)
# -> daily MRP x (1 - DEFAULT_DISCOUNT) when a channel has no discount history at all.
EST_LOOKBACK_DAYS = int(_get("EST_LOOKBACK_DAYS", 28))
DEFAULT_DISCOUNT = float(_get("DEFAULT_DISCOUNT", 0.11))
# Per-channel override of DEFAULT_DISCOUNT, for channels whose no-history fallback shouldn't use
# the general 11% (owner-specified).
CHANNEL_DEFAULT_DISCOUNT: dict[str, float] = {"FK-Minutes": 0.15}
# Channels refreshed weekly; used only to flag an overdue weekly load.
WEEKLY_GROSS_CHANNELS = ["Blinkit", "Zepto", "Swiggy", "FK-Minutes", "Myntra", "Nykaa", "Tira"]
WEEKLY_OVERDUE_DAYS = 9

# Freebie categories: removed from every metric (MRP, gross, quantity, AOV, ASP, category views).
# Matched case-insensitively, ignoring spaces and punctuation.
EXCLUDED_CATEGORIES = ["Consumables", "Consumable", "Freebie", "Freebies", "Primary",
                       "Uncategorised", "Uncategorized"]

# Map source channel names onto the dashboard's names, e.g. {"Amazon SC": "Amazon-SC"}.
CHANNEL_ALIASES: dict[str, str] = {
    "website_kimirica": "Website",   # AOP tables
    "az_uae": "Amazon-UAE",
}

# Growth everywhere (cards, channel table, drivers) is measured on MRP sales,
# which is actual and daily for every channel.
GROWTH_METRIC = "mrp_sales"

# --------------------------------------------------------------------------- #
# Caching / loading
# --------------------------------------------------------------------------- #
MAX_HISTORY_DAYS = int(_get("MAX_HISTORY_DAYS", 1500))   # safety cap on how much history is loaded
RECENT_DAYS = int(_get("RECENT_DAYS", 3))       # re-read frequently (late-arriving data)
TTL_RECENT = int(_get("TTL_RECENT_SECONDS", 600))        # 10 minutes
TTL_HISTORY = int(_get("TTL_HISTORY_SECONDS", 12 * 3600))  # 12 hours
TTL_SIDE_TABLES = int(_get("TTL_SIDE_TABLES_SECONDS", 900))  # weekly gross, ad spends, AOP
# Year-to-date and month-on-month sections start at this month.
# 4 = Indian financial year (April-March). Set to 1 for calendar year.
YEAR_START_MONTH = int(_get("YEAR_START_MONTH", 4))


def year_start(d: dt.date) -> dt.date:
    y = d.year if d.month >= YEAR_START_MONTH else d.year - 1
    return dt.date(y, YEAR_START_MONTH, 1)


TREND_MONTHS = 12  # monthly trend: trailing months shown, each with last year's value


def history_start(first_date: dt.date, max_date: dt.date) -> dt.date:
    """Load everything the tables hold, capped at MAX_HISTORY_DAYS."""
    return max(first_date, max_date - dt.timedelta(days=MAX_HISTORY_DAYS))

# --------------------------------------------------------------------------- #
# Channels
# --------------------------------------------------------------------------- #
CHANNELS = [
    "Amazon-SC", "Amazon-VC", "Amazon-UAE", "Blinkit", "EBO(Stores)",
    "FK-Minutes", "Flipkart", "Myntra", "Nykaa", "Swiggy", "Tira",
    "Website", "Zepto",
]

CHANNEL_GROUPS = {
    "Website": "D2C website",
    "EBO(Stores)": "Retail stores",
    "Amazon-SC": "Marketplaces",
    "Amazon-VC": "Marketplaces",
    "Amazon": "Marketplaces",   # AOP line covering Amazon-SC + Amazon-VC
    "Flipkart": "Marketplaces",
    "Myntra": "Marketplaces",
    "Nykaa": "Marketplaces",
    "Tira": "Marketplaces",
    "Tata Cliq_Others": "Marketplaces",  # AOP-only: target line, no sales rows of its own
    "Smytten": "Marketplaces",           # AOP-only: target line, no sales rows of its own
    "Blinkit": "Quick commerce",
    "Zepto": "Quick commerce",
    "Swiggy": "Quick commerce",
    "FK-Minutes": "Quick commerce",
    "Amazon-UAE": "International",
}

AMAZON_CHANNELS = ["Amazon-SC", "Amazon-VC", "Amazon-UAE"]
QUICK_COMMERCE = [c for c, g in CHANNEL_GROUPS.items() if g == "Quick commerce"]
ORDER_CHANNELS = ["Website", "EBO(Stores)", "Flipkart"]  # only channels with orders

# Muted, distinguishable palette; one fixed colour per channel across all charts.
CHANNEL_COLORS = {
    "Amazon-SC": "#1F4D46",
    "Amazon-VC": "#4F7F77",
    "Amazon-UAE": "#9DBDB6",
    "Website": "#2E5A88",
    "EBO(Stores)": "#8AA9CC",
    "Flipkart": "#B7832F",
    "FK-Minutes": "#E0C08A",
    "Blinkit": "#6E8B3D",
    "Zepto": "#6B4E8A",
    "Swiggy": "#C0674A",
    "Myntra": "#A64D6E",
    "Nykaa": "#D797AE",
    "Tira": "#7A7F87",
    "Others": "#C9CFCC",
}
GROUP_COLORS = {
    "Marketplaces": "#1F4D46",
    "Quick commerce": "#6E8B3D",
    "D2C website": "#2E5A88",
    "Retail stores": "#8AA9CC",
    "International": "#B7832F",
    "Other": "#C9CFCC",
}

# --------------------------------------------------------------------------- #
# Watchlist thresholds
# --------------------------------------------------------------------------- #
TOP_N_CHANNELS = 6
ANOMALY_DEVIATION = 0.35     # day vs trailing-7-day average
ANOMALY_MIN_SHARE = 0.02     # ignore channels below 2% of recent sales
TARGET_LAG_THRESHOLD = 0.85  # MTD achievement below 85% is flagged
MOM_DECLINE_THRESHOLD = -0.15
MOM_MIN_SHARE = 0.03
