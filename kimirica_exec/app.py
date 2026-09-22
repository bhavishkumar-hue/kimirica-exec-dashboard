"""
Kimirica Lifestyle — Executive Sales Dashboard
Run:  python -m streamlit run app.py
"""
from __future__ import annotations

import datetime as dt

import pandas as pd
import streamlit as st

st.set_page_config(
    page_title="Kimirica Lifestyle | Executive Sales",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="collapsed",
)

import config  # noqa: E402
import metrics as M  # noqa: E402
from bigquery import clear_caches, load_dashboard_data  # noqa: E402
from components import charts, insights, kpi_cards, tables  # noqa: E402
from components import theme as T  # noqa: E402

T.inject_css()


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def seg(options: list[str], default: str, key: str) -> str:
    value = st.segmented_control(key, options, default=default, key=key, label_visibility="collapsed")
    return value or default


@st.cache_data(show_spinner=False, max_entries=32)
def cached_category(version: str, channels: tuple, categories: tuple, _df: pd.DataFrame) -> pd.DataFrame:
    return M.prepare_category_frame(M.filter_frame(_df, list(channels), list(categories)))


@st.cache_data(show_spinner=False, max_entries=32)
def cached_channel_daily(version: str, channels: tuple, categories: tuple, _df: pd.DataFrame) -> pd.DataFrame:
    return M.channel_daily(M.filter_frame(_df, list(channels), list(categories)), list(categories))


def panel_header(title: str, subtitle: str | None = None, ratio=(3, 2)):
    left, right = st.columns(ratio, vertical_alignment="bottom")
    with left:
        T.section(title, subtitle)
    return right


def empty(msg: str) -> None:
    st.markdown(f'<div class="empty">{T.esc(msg)}</div>', unsafe_allow_html=True)


# --------------------------------------------------------------------------- #
# Data
# --------------------------------------------------------------------------- #
if st.query_params.get("refresh"):
    clear_caches()
    st.cache_data.clear()
    del st.query_params["refresh"]

try:
    with st.spinner("Loading sales data"):
        data = load_dashboard_data()
except Exception as exc:  # actionable message instead of a stack trace
    st.error(
        "Sales data could not be loaded from BigQuery.\n\n"
        f"**Reason:** {exc}\n\n"
        "Check the service-account secret, the `GCP_PROJECT` / `BQ_DATASET` / `BQ_TABLE` settings, "
        "and that the account has BigQuery Data Viewer and Job User roles."
    )
    st.stop()

if data.df.empty:
    st.warning("The summary table returned no rows for the loaded window.")
    st.stop()

version = f"{data.source}|{data.max_date}|{data.fetched_at.isoformat()}"

# --------------------------------------------------------------------------- #
# Header (filled after filters) and filters
# --------------------------------------------------------------------------- #
header_slot = st.empty()

channel_options = [c for c in config.CHANNELS if c in set(data.df["channel"])]
channel_options += sorted(set(data.df["channel"]) - set(channel_options))
category_options = sorted(data.df["category"].dropna().unique()) if data.has_category else []
first_month = pd.Timestamp(data.min_date).replace(day=1)
last_day = pd.Timestamp(data.max_date)
months = list(pd.date_range(first_month, last_day.replace(day=1), freq="MS"))[::-1]
fys = sorted({pd.Timestamp(config.year_start(m.date())) for m in months}, reverse=True)


def _month_label(m: pd.Timestamp) -> str:
    return m.strftime("%b %Y") + (" (to date)" if m == months[0] and last_day < M._month_end(m) else "")


def _fy_label(f: pd.Timestamp) -> str:
    end = f + pd.DateOffset(years=1) - pd.Timedelta(days=1)
    label = f"FY{f.year % 100:02d}-{(f.year + 1) % 100:02d}" if config.YEAR_START_MONTH != 1 else str(f.year)
    return label + (" (to date)" if last_day < end else "")


with st.container(key="filters"):
    f1, f2, f3, f4, f5 = st.columns([2.4, 1.6, 2.0, 2.0, 1.6], vertical_alignment="bottom")
    with f1:
        mode = st.segmented_control("View", list(M.MODES), default="Month", key="view_mode") or "Month"
    with f2:
        if mode == "Month":
            month = st.selectbox("Month", months, format_func=_month_label, key="sel_month")
            start_ts, end_ts = month, min(M._month_end(month), last_day)
        elif mode == "Financial year":
            fy = st.selectbox("Financial year", fys, format_func=_fy_label, key="sel_fy")
            start_ts, end_ts = fy, min(fy + pd.DateOffset(years=1) - pd.Timedelta(days=1), last_day)
        else:
            default = st.session_state.get("custom_valid",
                                           (max(data.min_date, data.max_date - dt.timedelta(days=89)), data.max_date))
            picked = st.date_input("Dates", value=default, min_value=data.min_date, max_value=data.max_date,
                                   format="DD/MM/YYYY", key="custom_dates")
            if isinstance(picked, (tuple, list)) and len(picked) == 2:
                st.session_state["custom_valid"] = (picked[0], picked[1])
            start_ts, end_ts = (pd.Timestamp(d) for d in st.session_state.get("custom_valid", default))
    with f3:
        compare = st.segmented_control("Compare with", list(M.COMPARES), default="Previous period",
                                       key="compare") or "Previous period"
    with f4:
        sel_channels = st.multiselect("Channels", channel_options, placeholder="All channels", key="channels")
    with f5:
        if category_options:
            sel_categories = st.multiselect("Categories", category_options, placeholder="All categories",
                                            key="categories")
        else:
            sel_categories = []

scope = sel_channels or channel_options
P = M.build_periods(start_ts, end_ts, data.channel_last_date, mode=mode, compare=compare)
cd_raw = M.attach_targets(
    cached_channel_daily(version, tuple(sel_channels), tuple(sel_categories), data.df),
    data.targets, sel_channels, sel_categories,
)
cd = M.add_lag(cd_raw, P)
# Pacing, highlights and needs attention always describe the current month to date, whatever dates are picked
PT = M.build_periods(last_day.replace(day=1), last_day, data.channel_last_date)
cd_today = M.add_lag(cd_raw, PT)
ads, ads_filtered = M.prepare_ads(data.ads, sel_channels, P)
if sel_categories:
    ads = None  # ad spends aren't split by category
scope_channels = sel_channels  # empty = every channel, including any only present in the AOP tables
aop = None if sel_categories else data.aop  # the AOP plan isn't split by category
snap = M.kpi_snapshot(cd, ads, P, aop, scope_channels)
tbl = M.channel_table(cd, P, "channel", aop, scope_channels)
ads_today, _ = M.prepare_ads(data.ads, sel_channels, PT)
snap_today = M.kpi_snapshot(cd_today, None if sel_categories else ads_today, PT, aop, scope_channels)
tbl_today = M.channel_table(cd_today, PT, "channel", aop, scope_channels)
in_scope = sorted(set(cd["channel"]))

with st.container(key="filters_caption"):
    T.note(f"{P.period_label}, compared with {P.cmp_period_label}.")

with header_slot.container():
    T.header()
    if config.SECRETS_ERROR:
        st.error("**`.streamlit/secrets.toml` couldn't be read, so BigQuery isn't connected and these "
                 f"numbers are not real.**\n\n{config.SECRETS_ERROR}\n\nEvery line must be "
                 '`key = "value"` (TOML), not `key: "value",` (JSON).', icon="🚨")
    elif data.source == "demo":
        st.error("**These numbers are not real.** BigQuery isn't connected, so the dashboard is "
                 "showing synthetic demo data. Check `.streamlit/secrets.toml`.", icon="🚨")
for n in data.notes:
    st.warning(n)

# --------------------------------------------------------------------------- #
# 1. Headline KPIs and pacing
# --------------------------------------------------------------------------- #
kpi_cards.render_kpis(snap, P, ads_available=ads is not None)
gaps = M.coverage_notes(data.spans, P.cur_start, P.as_of)
T.note(" ".join([kpi_cards.AOV_NOTE] + gaps))
kpi_cards.render_pacing(snap_today, PT)

# --------------------------------------------------------------------------- #
# 2. Channel performance
# --------------------------------------------------------------------------- #
with st.container(key="panel_channels"):
    ctrl = panel_header("Channel performance")
    with ctrl:
        c1, c2 = st.columns([1.6, 1], vertical_alignment="center")
        with c1:
            view = seg(["Channels", "Channel groups"], "Channels", "tbl_view")
        with c2:
            raw = st.toggle("Full values", key="raw_values")
    key_col = "channel" if view == "Channels" else "group"
    view_tbl = tbl if key_col == "channel" else M.channel_table(cd, P, "group", aop, scope_channels)
    if view_tbl.empty:
        empty("No sales for this selection.")
    else:
        tables.channel_table(view_tbl, key_col, raw, expected=P.aop_progress)

# --------------------------------------------------------------------------- #
# 3. Category performance
# --------------------------------------------------------------------------- #
if data.has_category:
    fdf = M.add_lag(cached_category(version, tuple(sel_channels), tuple(sel_categories), data.df), P)
    ct = M.category_table(fdf, P)
    with st.container(key="panel_category"):
        ctrl = panel_header("Category performance")
        with ctrl:
            raw_cat = st.toggle("Full values", key="raw_cat")
        if ct.empty:
            empty("No category sales for this selection.")
        else:
            tables.category_table(ct, raw_cat)
            charts.category_chart(ct)

# --------------------------------------------------------------------------- #
# 4. Growth drivers and target vs actual
# --------------------------------------------------------------------------- #
has_targets = cd["target_sales"].notna().any() or (aop is not None and not aop.empty)
target_mode = st.session_state.get("target_mode") or "Period"
tf = M.target_frame(cd, P, target_mode, aop, scope_channels) if has_targets else None
n_rows = max(int(view_tbl["Δ vs LMTD"].notna().sum()), 0 if tf is None else len(tf))
pair_height = max(300, 32 * n_rows + 70)

d_col, t_col = st.columns([1, 1], gap="medium") if has_targets else (st.container(), None)
with d_col, st.container(key="panel_drivers"):
    T.section(f"What moved {M.metric_lc(config.GROWTH_METRIC)} {P.cmp_label}")
    charts.growth_drivers_chart(view_tbl, key_col, height=pair_height if has_targets else None)
if t_col is not None:
    with t_col, st.container(key="panel_target"):
        ctrl = panel_header("AOP vs actual", ratio=(2, 1))
        with ctrl:
            seg(["Period", "Day"], "Period", "target_mode")
        if tf.empty or tf["target"].sum() == 0:
            empty(f"No AOP loaded for {'this day' if target_mode == 'Day' else 'this period'}.")
        else:
            charts.target_chart(tf, height=pair_height,
                                expected=P.aop_progress if target_mode == "Period" else 1.0)

# --------------------------------------------------------------------------- #
# 5. Monthly trend
# --------------------------------------------------------------------------- #
with st.container(key="panel_monthly"):
    ctrl = panel_header("Monthly trend")
    with ctrl:
        trend_labels = [M.METRIC_LABELS[k] for k in ("mrp_sales", "gross_sales", "net_sales")]
        m_label = seg(trend_labels, M.METRIC_LABELS[config.GROWTH_METRIC], "monthly_metric")
    m_metric = {v: k for k, v in M.METRIC_LABELS.items()}[m_label]
    mt = M.monthly_trend(cd, ads, P)
    if mt["mrp"].notna().any():
        charts.monthly_trend_chart(mt, m_metric)
    else:
        empty("No monthly sales for this selection.")

# --------------------------------------------------------------------------- #
# 6. Highlights and watchlist
# --------------------------------------------------------------------------- #
h_col, w_col = st.columns([1.4, 1], gap="medium")
with h_col, st.container(key="panel_highlights"):
    T.section("Highlights")
    insights.highlights(M.insights(cd_today, PT, snap_today, tbl_today))
with w_col, st.container(key="panel_watch"):
    T.section("Needs attention")
    insights.watchlist(M.watchlist(cd_today, PT, tbl_today, data.channel_last_date, scope, data.est_meta))

# --------------------------------------------------------------------------- #
# Sidebar: definitions only
# --------------------------------------------------------------------------- #
with st.sidebar:
    st.markdown("#### Definitions")
    st.markdown(
        f"""
- **MRP sales** includes freebies. Growth is measured on MRP sales.
- **Gross sales** excludes freebies. **Net sales** = gross ÷ {1 + config.GST_RATE:.2f}.
- **MTD** is the 1st to the selected date; **LMTD** the same days of last month.
- **AOP** targets are on MRP sales.
- **AOV** uses orders where the sales table has them; elsewhere units count as orders, so AOV equals ASP.
- **Gross sales** come from the sales table, then the weekly gross table, then daily MRP less the channel's last {config.EST_LOOKBACK_DAYS} days' discount, then {config.DEFAULT_DISCOUNT:.0%} if a channel has no history.
- **Amazon-VC** uses its latest loaded date for MTD and every comparison.
- A dash (—) means the metric isn't tracked.
        """
    )
    src = config.table_fqn() if data.source == "bigquery" else "Synthetic demo data"
    st.caption(f"Source: {src}")
    st.caption(f"Loaded: {M.fmt_date(data.min_date, True)} to {M.fmt_date(data.max_date, True)}")
