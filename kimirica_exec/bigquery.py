"""
Data access layer.

Load strategy (fast by design):
  * freshness query -> cached 10 min, latest date per channel in the sales table
  * sales history   -> cached 12 h, [start of last FY, latest - RECENT_DAYS]
  * sales recent    -> cached 10 min, (latest - RECENT_DAYS, month end]
  * weekly gross    -> cached 1 h, whole window (weekly refreshes can restate history)
  * ad spends       -> cached 1 h, whole window
Weekly gross is merged and estimated once per data version (estimates.py).
"""
from __future__ import annotations

import calendar
import datetime as dt
import re
from dataclasses import dataclass, field
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

import config
import queries
from estimates import fill_gross

IST = ZoneInfo(config.TIMEZONE)
NUMERIC = ["mrp_sales", "gross_sales", "quantity", "orders", "target_sales"]


@dataclass
class DashboardData:
    df: pd.DataFrame                     # date x channel x category, measures may be NaN, est flag
    ads: pd.DataFrame | None             # date x channel (channel may be None), ad_spend
    targets: pd.DataFrame | None         # date x channel, daily AOP target and achieved revenue
    aop: pd.DataFrame | None             # month x channel, monthly AOP plan
    channel_last_date: dict[str, dt.date]
    est_meta: dict
    spans: dict                          # source -> (first date with data, last date with data)
    max_date: dt.date
    min_date: dt.date
    table_modified: dt.datetime | None
    fetched_at: dt.datetime
    source: str                          # "bigquery" | "demo"
    notes: list[str] = field(default_factory=list)

    @property
    def has_category(self) -> bool:
        return self.df["category"].notna().any()

    @property
    def ads_by_channel(self) -> bool:
        return self.ads is not None and self.ads["channel"].isin(config.CHANNELS).any()


# --------------------------------------------------------------------------- #
# BigQuery plumbing
# --------------------------------------------------------------------------- #
@st.cache_resource(show_spinner=False)
def get_client():
    from google.cloud import bigquery

    credentials = None
    try:
        if "gcp_service_account" in st.secrets:
            from google.oauth2 import service_account

            credentials = service_account.Credentials.from_service_account_info(
                dict(st.secrets["gcp_service_account"]),
                scopes=["https://www.googleapis.com/auth/bigquery"],
            )
    except Exception:
        credentials = None  # fall back to GOOGLE_APPLICATION_CREDENTIALS / ADC

    return bigquery.Client(
        project=config.GCP_PROJECT or None,
        credentials=credentials,
        location=config.BQ_LOCATION or None,
    )


def _run(sql: str, params: dict[str, tuple[str, object]]) -> pd.DataFrame:
    from google.cloud import bigquery

    qp = []
    for name, (typ, value) in params.items():
        if isinstance(value, (list, tuple)):
            qp.append(bigquery.ArrayQueryParameter(name, typ, list(value)))
        else:
            qp.append(bigquery.ScalarQueryParameter(name, typ, value))
    job_config = bigquery.QueryJobConfig(query_parameters=qp, use_query_cache=True)
    return get_client().query(sql, job_config=job_config).result().to_dataframe(create_bqstorage_client=False)


def _dates(start: dt.date, end: dt.date) -> dict:
    return {"start": ("DATE", start), "end": ("DATE", end)}


_EXCLUDED = {re.sub(r"[^a-z]", "", c.lower()) for c in config.EXCLUDED_CATEGORIES}


def is_excluded_category(value) -> bool:
    return value is not None and re.sub(r"[^a-z]", "", str(value).lower()) in _EXCLUDED


def canonical_channel(name: str) -> str:
    """Apply CHANNEL_ALIASES ignoring case, so 'Website_Kimirica' and 'website_kimirica' both match."""
    aliases = {k.lower(): v for k, v in config.CHANNEL_ALIASES.items()}
    return aliases.get(name.lower(), name)


def _prep_common(df: pd.DataFrame, numeric: list[str]) -> pd.DataFrame:
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"]).dt.normalize()
    df["channel"] = df["channel"].astype(object).where(df["channel"].notna(), None)
    named = df["channel"].notna()
    df.loc[named, "channel"] = df.loc[named, "channel"].astype(str).str.strip().map(canonical_channel)
    if "category" in df:
        df["category"] = df["category"].astype(object).where(df["category"].notna(), None)
        df = df[~df["category"].map(is_excluded_category)]
    for col in numeric:
        if col not in df:
            df[col] = float("nan")
        # nullable ints -> float64 with NaN; NULL is preserved, never zero-filled
        df[col] = pd.to_numeric(df[col], errors="coerce").astype("float64")
    return df


def _prepare_sales(df):
    return _prep_common(df, NUMERIC)


def _prepare_weekly(df):
    return _prep_common(df, ["gross_sales"])


def _prepare_ads(df):
    return _prep_common(df, ["ad_spend"])


def _prepare_targets(df):
    return _prep_common(df, ["target_sales", "achieved_sales"])


_MONTHS = {m.lower(): i for i, m in enumerate(calendar.month_abbr) if m}


def parse_aop_month(fy: str, month: str):
    """
    Turn a financial year ('2026-27', 'FY26-27', '2026-2027') and a month label
    ('Apr', 'April', 'Apr-26', 'Apr 2026', '2026-04', '04') into the first day of that month.
    """
    m = str(month or "").strip()
    iso = re.match(r"^(\d{4})[-/](\d{1,2})", m)
    if iso:
        return pd.Timestamp(int(iso.group(1)), int(iso.group(2)), 1)
    name = re.sub(r"[^a-z]", "", m.lower())[:3]
    num = _MONTHS.get(name) or (int(m) if m.isdigit() and 1 <= int(m) <= 12 else None)
    if num is None:
        return pd.NaT
    explicit = re.findall(r"\d{2,4}", m)
    if explicit and name:
        y = int(explicit[-1])
        return pd.Timestamp(y + 2000 if y < 100 else y, num, 1)
    digits = re.findall(r"\d+", str(fy or ""))
    if not digits:
        return pd.NaT
    start = int(digits[0])
    start = start + 2000 if start < 100 else start
    return pd.Timestamp(start if num >= config.YEAR_START_MONTH else start + 1, num, 1)


def _prepare_aop(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    pairs = {(f, m): parse_aop_month(f, m) for f, m in df[["fy", "month"]].drop_duplicates().itertuples(index=False)}
    df["date"] = [pairs[(f, m)] for f, m in zip(df["fy"], df["month"])]
    unparsed = df[df["date"].isna()]
    if len(unparsed):
        st.warning("Some AOP months couldn't be read: "
                   + ", ".join(sorted({f"{f} {m}" for f, m in zip(unparsed["fy"], unparsed["month"])}))[:300])
    df["fy_start"] = [fy_start_year(f) for f in df["fy"]]
    df = _prep_common(df[df["date"].notna()], ["aop"])
    return df.groupby(["fy_start", "date", "channel"], as_index=False)["aop"].sum(min_count=1)


def fy_start_year(fy) -> int | None:
    """'2026-27', 'FY26-27', '2026-2027' -> 2026."""
    digits = re.findall(r"\d+", str(fy or ""))
    if not digits:
        return None
    y = int(digits[0])
    return y + 2000 if y < 100 else y


@st.cache_data(ttl=config.TTL_HISTORY, show_spinner=False)
def fetch_columns() -> dict[str, set]:
    tables = [t for t in (config.BQ_TABLE, config.BQ_WEEKLY_TABLE, config.BQ_AD_TABLE,
                          config.BQ_TARGET_TABLE, config.BQ_AOP_TABLE) if t]
    df = _run(queries.columns_sql(), {"tables": ("STRING", [t.split(".")[-1] for t in tables])})
    out: dict[str, set] = {}
    for table, group in df.groupby("table_name"):
        out[str(table)] = set(group["column_name"].astype(str))
    return out


def apply_schema() -> list[str]:
    """Switch off optional columns and tables that don't exist. Returns notes for the UI."""
    try:
        present = fetch_columns()
    except Exception as exc:
        return [f"Could not read the table schema ({exc}); using the configured column names as-is."]

    notes: list[str] = []
    main = present.get(config.BQ_TABLE.split(".")[-1], set())
    if not main:
        raise RuntimeError(f"Table {config.table_fqn()} was not found, or the service account can't see it.")
    required = {"date": config.COL_DATE, "channel": config.COL_CHANNEL,
                "MRP sales": config.COL_MRP, "gross sales": config.COL_GROSS, "quantity": config.COL_QTY}
    missing = {k: v for k, v in required.items() if v not in main}
    if missing:
        raise RuntimeError("Missing columns in " + config.table_fqn() + ": "
                           + ", ".join(f"{v} ({k})" for k, v in missing.items()))
    for attr, label in (("COL_CATEGORY", "category"), ("COL_ORDERS", "orders"), ("COL_TARGET", "AOP target")):
        name = getattr(config, attr)
        if name and name not in main:
            setattr(config, attr, "")
            notes.append(f"No {label} column ({name}) in {config.BQ_TABLE}; that part of the dashboard is hidden.")

    for attr, cols, label in (
        ("BQ_WEEKLY_TABLE", {"W_COL_DATE", "W_COL_CHANNEL", "W_COL_GROSS"}, "weekly gross"),
        ("BQ_AD_TABLE", {"AD_COL_DATE", "AD_COL_SPEND"}, "ad spends"),
        ("BQ_TARGET_TABLE", {"T_COL_DATE", "T_COL_CHANNEL", "T_COL_TARGET"}, "daily AOP targets"),
        ("BQ_AOP_TABLE", {"A_COL_FY", "A_COL_MONTH", "A_COL_CHANNEL", "A_COL_REVENUE"}, "monthly AOP"),
    ):
        table = getattr(config, attr)
        if not table:
            continue
        found = present.get(table.split(".")[-1], set())
        if not found:
            setattr(config, attr, "")
            notes.append(f"Table {table} was not found; {label} is switched off.")
            continue
        for col_attr in sorted(cols):
            if getattr(config, col_attr) not in found:
                setattr(config, attr, "")
                notes.append(f"{table} has no {getattr(config, col_attr)} column; {label} is switched off.")
                break
    for col_attr, table_attr in (("W_COL_CATEGORY", "BQ_WEEKLY_TABLE"), ("AD_COL_CHANNEL", "BQ_AD_TABLE"),
                                 ("T_COL_ACHIEVED", "BQ_TARGET_TABLE")):
        table = getattr(config, table_attr)
        name = getattr(config, col_attr)
        if table and name and name not in present.get(table.split(".")[-1], set()):
            setattr(config, col_attr, "")
    return notes


@st.cache_data(ttl=config.TTL_RECENT, show_spinner=False)
def fetch_freshness() -> tuple[pd.DataFrame, dt.datetime | None]:
    meta = _run(queries.freshness_sql(), {})
    for col in ("last_date", "first_date"):
        meta[col] = pd.to_datetime(meta[col]).dt.date
    modified = None
    try:
        modified = get_client().get_table(config.table_fqn()).modified
    except Exception:
        pass
    return meta, modified


@st.cache_data(ttl=config.TTL_HISTORY, show_spinner=False)
def fetch_history(start: dt.date, end: dt.date) -> pd.DataFrame:
    return _prepare_sales(_run(queries.summary_sql(), _dates(start, end)))


@st.cache_data(ttl=config.TTL_RECENT, show_spinner=False)
def fetch_recent(start: dt.date, end: dt.date) -> tuple[pd.DataFrame, dt.datetime]:
    return _prepare_sales(_run(queries.summary_sql(), _dates(start, end))), dt.datetime.now(IST)


@st.cache_data(ttl=config.TTL_SIDE_TABLES, show_spinner=False)
def fetch_weekly(start: dt.date, end: dt.date) -> pd.DataFrame:
    return _prepare_weekly(_run(queries.weekly_sql(), _dates(start, end)))


@st.cache_data(ttl=config.TTL_SIDE_TABLES, show_spinner=False)
def fetch_ads(start: dt.date, end: dt.date) -> pd.DataFrame:
    return _prepare_ads(_run(queries.ads_sql(), _dates(start, end)))


@st.cache_data(ttl=config.TTL_SIDE_TABLES, show_spinner=False)
def fetch_targets(start: dt.date, end: dt.date) -> pd.DataFrame:
    return _prepare_targets(_run(queries.targets_sql(), _dates(start, end)))


@st.cache_data(ttl=config.TTL_SIDE_TABLES, show_spinner=False)
def fetch_aop_raw() -> pd.DataFrame:
    return _run(queries.aop_sql(), {})


@st.cache_data(show_spinner=False, max_entries=4)
def combine(version: str, _sales: pd.DataFrame, _weekly: pd.DataFrame | None):
    """Fill gross (weekly table, then estimates) and derive net sales. Cached per data version."""
    df, meta = fill_gross(_sales, _weekly)
    df["net_sales"] = df["gross_sales"] / (1 + config.GST_RATE)
    return df, meta


def _span(df: pd.DataFrame | None, value_col: str):
    if df is None or df.empty or value_col not in df:
        return None
    d = df.loc[df[value_col].notna(), "date"]
    return (d.min().date(), d.max().date()) if len(d) else None


def _spans(sales, weekly, ads, targets) -> dict:
    return {k: v for k, v in {
        "Sales": _span(sales, "mrp_sales"),
        "Gross sales in the sales table": _span(sales, "gross_sales"),
        "Weekly gross": _span(weekly, "gross_sales"),
        "Ad spends": _span(ads, "ad_spend"),
        "AOP achievement": _span(targets, "achieved_sales"),
    }.items() if v}


def _month_end(d: dt.date) -> dt.date:
    return d.replace(day=calendar.monthrange(d.year, d.month)[1])


# --------------------------------------------------------------------------- #
# Public entry point
# --------------------------------------------------------------------------- #
def load_dashboard_data() -> DashboardData:
    if config.DEMO_MODE or not config.bq_configured():
        return _load_demo()

    notes = apply_schema()
    meta, modified = fetch_freshness()
    if meta.empty:
        raise RuntimeError(f"No sales found in {config.table_fqn()}. Check the table and column mapping.")
    channels = meta["channel"].astype(str).str.strip().map(canonical_channel)
    last_dates = dict(zip(channels, meta["last_date"]))
    max_date = max(last_dates.values())
    hist_start = config.history_start(min(meta["first_date"]), max_date)
    cutoff = max_date - dt.timedelta(days=config.RECENT_DAYS)
    year_end = config.year_start(max_date).replace(year=config.year_start(max_date).year + 1) - dt.timedelta(days=1)
    load_to = max(_month_end(max_date), year_end)

    history = fetch_history(hist_start, cutoff)
    recent, fetched_at = fetch_recent(cutoff + dt.timedelta(days=1), load_to)
    sales = pd.concat([history, recent], ignore_index=True)

    weekly = None
    if config.BQ_WEEKLY_TABLE:
        try:
            weekly = fetch_weekly(hist_start, load_to)
        except Exception as exc:
            notes.append(f"Weekly gross table could not be read ({exc}); using the main table's gross.")
    ads = None
    if config.BQ_AD_TABLE:
        try:
            ads = fetch_ads(hist_start, load_to)
        except Exception as exc:
            notes.append(f"Ad spends table could not be read ({exc}).")
    targets = None
    if config.BQ_TARGET_TABLE:
        try:
            targets = fetch_targets(hist_start, load_to)
        except Exception as exc:
            notes.append(f"AOP target table could not be read ({exc}).")
    aop = None
    if config.BQ_AOP_TABLE:
        try:
            aop = _prepare_aop(fetch_aop_raw())
        except Exception as exc:
            notes.append(f"Monthly AOP table could not be read ({exc}).")

    version = f"bq|{max_date}|{fetched_at.isoformat()}|{len(weekly) if weekly is not None else 0}"
    df, est_meta = combine(version, sales, weekly)
    spans = _spans(sales, weekly, ads, targets)

    return DashboardData(
        df=df, ads=ads, targets=targets, aop=aop, channel_last_date=last_dates, est_meta=est_meta, spans=spans,
        max_date=max_date, min_date=hist_start,
        table_modified=modified.astimezone(IST) if modified else None,
        fetched_at=fetched_at, source="bigquery", notes=notes,
    )


def _load_demo() -> DashboardData:
    from demo_data import generate_demo_frame

    now = dt.datetime.now(IST)
    sales, weekly, ads, targets, aop, last_dates = generate_demo_frame(now.date())
    if not config.BQ_AD_TABLE:
        ads = None
    if not config.BQ_TARGET_TABLE:
        targets = None
    sales, weekly = _prepare_sales(sales), _prepare_weekly(weekly)
    ads = _prepare_ads(ads) if ads is not None else None
    targets = _prepare_targets(targets) if targets is not None else None
    aop = _prepare_aop(aop) if (aop is not None and config.BQ_AOP_TABLE) else None
    max_date = max(last_dates.values())
    df, est_meta = combine(f"demo|{max_date}", sales, weekly)
    return DashboardData(
        df=df, ads=ads, targets=targets, aop=aop, channel_last_date=last_dates, est_meta=est_meta,
        spans=_spans(sales, weekly, ads, targets),
        max_date=max_date, min_date=df["date"].min().date(),
        table_modified=now.replace(hour=7, minute=45, second=0, microsecond=0),
        fetched_at=now, source="demo",
    )


def clear_caches() -> None:
    for fn in (fetch_columns, fetch_freshness, fetch_recent, fetch_history,
               fetch_weekly, fetch_ads, fetch_targets, fetch_aop_raw, combine):
        fn.clear()
