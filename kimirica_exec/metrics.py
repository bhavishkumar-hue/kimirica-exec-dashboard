"""
All business logic lives here: periods, KPI maths, tables and watchlist rules.
Nothing in this module touches Streamlit widgets, so it is easy to unit-test.

Conventions
  * Missing (NULL) metrics stay NaN / None end-to-end. Sums use min_count=1.
  * Growth % is None when the base is missing or <= 0.
  * Target achievement only compares sales on rows (channel-days) that carry a target.
  * AOV is blended: real orders for Website/EBO/Flipkart, ASP (units as orders) elsewhere.
  * Lagged channels (Amazon-VC) have every window end shifted by their lag.
  * Growth is measured on config.GROWTH_METRIC (MRP sales).
"""
from __future__ import annotations

import calendar
import html
import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

import config

ADDITIVE = ["mrp_sales", "gross_sales", "net_sales", "quantity"]
DAY = pd.Timedelta(days=1)

METRIC_LABELS = {"mrp_sales": "MRP sales", "gross_sales": "Gross sales", "net_sales": "Net sales", "quantity": "Quantity"}


# =========================================================================== #
# Formatting
# =========================================================================== #
def metric_lc(key: str) -> str:
    """Metric name for use mid-sentence: 'MRP sales', 'gross sales'."""
    label = METRIC_LABELS[key]
    return label if label.startswith("MRP") else label.lower()


def is_na(v) -> bool:
    if v is None:
        return True
    try:
        return bool(pd.isna(v))
    except (TypeError, ValueError):
        return False


def _indian_group(n: int) -> str:
    s = str(abs(n))
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        s = ",".join(parts) + "," + tail
    return ("-" if n < 0 else "") + s


def fmt_inr(v, prefix: str = "₹") -> str:
    """₹842 / ₹12.4K / ₹12.4L / ₹1.24Cr"""
    if is_na(v):
        return "—"
    sign = "−" if v < 0 else ""
    a = abs(float(v))
    if a >= 1e7:
        body = f"{a / 1e7:.2f}Cr" if a < 1e9 else f"{a / 1e7:,.0f}Cr"
    elif a >= 1e5:
        body = f"{a / 1e5:.1f}L"
    elif a >= 1e3:
        body = f"{a / 1e3:.1f}K"
    else:
        body = f"{a:.0f}"
    return f"{sign}{prefix}{body}"


def fmt_inr_full(v) -> str:
    if is_na(v):
        return "—"
    n = int(round(float(v)))
    return ("-₹" if n < 0 else "₹") + _indian_group(abs(n))


def fmt_price(v) -> str:
    """Unit prices (ASP, AOV) in exact rupees: ₹1,108 rather than ₹1.1K."""
    if is_na(v):
        return "—"
    return fmt_inr_full(v) if abs(float(v)) < 1e5 else fmt_inr(v)


def fmt_count(v) -> str:
    if is_na(v):
        return "—"
    a = abs(float(v))
    sign = "-" if v < 0 else ""
    if a >= 1e7:
        return f"{sign}{a / 1e7:.2f}Cr"
    if a >= 1e5:
        return f"{sign}{a / 1e5:.1f}L"
    if a >= 1e4:
        return f"{sign}{a / 1e3:.1f}K"
    return _indian_group(int(round(float(v))))


def fmt_count_full(v) -> str:
    return "—" if is_na(v) else _indian_group(int(round(float(v))))


def fmt_pct(v, signed: bool = True) -> str:
    if is_na(v):
        return "—"
    p = float(v) * 100
    if abs(p) < 0.05:
        p = 0.0
    decimals = 0 if abs(p) >= 100 else 1
    s = f"{p:+.{decimals}f}%" if (signed and p != 0) else f"{p:.{decimals}f}%"
    return s.replace("-", "−")


def strf(d, fmt: str) -> str:
    """strftime that supports %-d (day without leading zero) on every OS, including Windows."""
    d = pd.Timestamp(d)
    return d.strftime(fmt.replace("%-d", str(d.day)))


def fmt_date(d, with_year: bool = False) -> str:
    return strf(d, "%-d %b %Y" if with_year else "%-d %b")


# =========================================================================== #
# Small numeric helpers
# =========================================================================== #
def _v(x):
    return None if is_na(x) else float(x)


def ratio(n, d):
    if is_na(n) or is_na(d) or float(d) == 0:
        return None
    return float(n) / float(d)


def pct(cur, base):
    if is_na(cur) or is_na(base) or float(base) <= 0:
        return None
    return float(cur) / float(base) - 1


def _vpct(a: pd.Series, b: pd.Series) -> pd.Series:
    return a / b.where(b > 0) - 1


def _sum(df: pd.DataFrame, col: str):
    return _v(df[col].sum(min_count=1)) if len(df) else None


# =========================================================================== #
# Periods
# =========================================================================== #
MODES = ("Month", "Financial year", "Custom")
COMPARES = ("Previous period", "Last year", "Custom")


@dataclass(frozen=True)
class Periods:
    """
    cur_start..as_of     the selected period (cards, tables, drivers)
    cmp_start..cmp_end   what it's compared with
    mtd_start..month_end the month containing as_of (month pacing, monthly trend)
    ytd_start..year_end  the financial year containing as_of (year pacing)
    aop_start..aop_end   whole months covering the selected period (AOP in tables and charts)
    """
    as_of: pd.Timestamp
    cur_start: pd.Timestamp
    cmp_start: pd.Timestamp
    cmp_end: pd.Timestamp
    cmp_label: str
    cmp_short: str
    mode: str
    mtd_start: pd.Timestamp
    month_end: pd.Timestamp
    lmtd_start: pd.Timestamp
    lmtd_end: pd.Timestamp
    ytd_start: pd.Timestamp
    year_end: pd.Timestamp
    ly_ytd_start: pd.Timestamp
    ly_ytd_end: pd.Timestamp
    days_elapsed: int
    days_in_month: int
    lags: tuple = ()          # ((channel, days), ...) for channels whose data ends before as_of

    def lag(self, channel: str) -> int:
        return dict(self.lags).get(channel, 0)

    def data_end(self, channel: str) -> pd.Timestamp:
        return self.as_of - pd.Timedelta(days=self.lag(channel))

    @property
    def cur_days(self) -> int:
        return (self.as_of - self.cur_start).days + 1

    @property
    def cmp_days(self) -> int:
        return (self.cmp_end - self.cmp_start).days + 1

    @property
    def aop_start(self) -> pd.Timestamp:
        return self.cur_start.replace(day=1)

    @property
    def aop_end(self) -> pd.Timestamp:
        return self.month_end

    @property
    def aop_progress(self) -> float:
        """Share of the AOP months that has elapsed by as_of."""
        return ((self.as_of - self.aop_start).days + 1) / ((self.aop_end - self.aop_start).days + 1)

    @property
    def single_month(self) -> bool:
        return self.aop_start == self.mtd_start

    @property
    def yday(self) -> pd.Timestamp:
        return self.as_of - DAY

    @property
    def days_left(self) -> int:
        return self.days_in_month - self.days_elapsed

    @property
    def month_progress(self) -> float:
        return self.days_elapsed / self.days_in_month

    @property
    def year_days_elapsed(self) -> int:
        return (self.as_of - self.ytd_start).days + 1

    @property
    def year_days(self) -> int:
        return (self.year_end - self.ytd_start).days + 1

    @property
    def year_progress(self) -> float:
        return self.year_days_elapsed / self.year_days

    @property
    def fy_label(self) -> str:
        y = self.ytd_start.year
        return str(y) if config.YEAR_START_MONTH == 1 else f"FY{y % 100:02d}-{(y + 1) % 100:02d}"

    @property
    def year_label(self) -> str:
        return f"{self.fy_label} to date"

    @property
    def period_label(self) -> str:
        if self.cur_start == self.as_of:
            return fmt_date(self.as_of, True)
        return f"{fmt_date(self.cur_start, True)} – {fmt_date(self.as_of, True)}"

    @property
    def cmp_phrase(self) -> str:
        """For sentences: 'LMTD', 'last month', 'last year', 'the previous 30 days'."""
        text = self.cmp_label[3:]
        return f"the {text}" if text.startswith("previous") else text

    @property
    def cmp_period_label(self) -> str:
        return f"{fmt_date(self.cmp_start, True)} – {fmt_date(self.cmp_end, True)}"


def _ly(ts: pd.Timestamp) -> pd.Timestamp:
    return ts - pd.DateOffset(years=1)  # 29 Feb -> 28 Feb


def _month_end(ts: pd.Timestamp) -> pd.Timestamp:
    return ts.replace(day=calendar.monthrange(ts.year, ts.month)[1])


def detect_lags(as_of, last_dates: dict | None) -> tuple:
    """Days each dynamic-lag channel is behind the selected date (0 if it has data for that date)."""
    a = pd.Timestamp(as_of).normalize()
    out = []
    for ch in config.DYNAMIC_LAG_CHANNELS:
        last = (last_dates or {}).get(ch)
        if last is not None and pd.Timestamp(last) < a:
            out.append((ch, int((a - pd.Timestamp(last)).days)))
    return tuple(out)


def _comparison(start: pd.Timestamp, end: pd.Timestamp, mode: str, compare: str):
    """Return (cmp_start, cmp_end, label, short) for the selected period."""
    if compare == "Last year":
        return _ly(start), _ly(end), "vs last year", "LY"
    if mode == "Month":
        prev_start = (start - pd.DateOffset(months=1)).replace(day=1)
        prev_end_full = _month_end(prev_start)
        if end == _month_end(end) and start.day == 1:
            return prev_start, prev_end_full, "vs last month", "Last month"
        first = prev_start.replace(day=min(start.day, prev_end_full.day))
        last = prev_start.replace(day=min(end.day, prev_end_full.day))
        return first, last, "vs LMTD", "LMTD"
    if mode == "Financial year":
        return _ly(start), _ly(end), "vs last FY", "Last FY"
    if (start.year, start.month) != (end.year, end.month):
        # Custom range spanning more than one month: same dates a year earlier
        return _ly(start), _ly(end), "vs last year", "LY"
    # Custom within one month: the same dates one month earlier (day clamped to the month's length)
    return (start - pd.DateOffset(months=1)), (end - pd.DateOffset(months=1)), "vs last month", "Last month"


def build_periods(start, end=None, last_dates: dict | None = None,
                  mode: str = "Month", compare: str = "Previous period",
                  cmp_start: object = None, cmp_end: object = None) -> Periods:
    """
    build_periods(as_of) keeps the old behaviour: this month to date vs LMTD.
    build_periods(start, end, ...) sets any period and comparison.
    compare="Custom" needs cmp_start/cmp_end (the caller's own comparison window).
    """
    if end is None or isinstance(end, dict):
        last_dates = end if isinstance(end, dict) else last_dates
        a = pd.Timestamp(start).normalize()
        start, end = a.replace(day=1), a
    s_, a = pd.Timestamp(start).normalize(), pd.Timestamp(end).normalize()
    if s_ > a:
        s_, a = a, s_
    dim = calendar.monthrange(a.year, a.month)[1]
    mtd_start = a.replace(day=1)
    pm_end = mtd_start - DAY
    ytd_start = pd.Timestamp(config.year_start(a.date()))
    if compare == "Custom" and cmp_start is not None and cmp_end is not None:
        c_start, c_end = pd.Timestamp(cmp_start).normalize(), pd.Timestamp(cmp_end).normalize()
        if c_start > c_end:
            c_start, c_end = c_end, c_start
        cmp_start, cmp_end, label, short = c_start, c_end, "vs custom period", "Custom"
    else:
        cmp_start, cmp_end, label, short = _comparison(s_, a, mode, compare)
    return Periods(
        as_of=a, cur_start=s_, cmp_start=cmp_start, cmp_end=cmp_end, cmp_label=label, cmp_short=short,
        mode=mode, mtd_start=mtd_start, month_end=a.replace(day=dim),
        lmtd_start=pm_end.replace(day=1), lmtd_end=pm_end.replace(day=min(a.day, pm_end.day)),
        ytd_start=ytd_start, year_end=ytd_start + pd.DateOffset(years=1) - DAY,
        ly_ytd_start=_ly(ytd_start), ly_ytd_end=_ly(a),
        days_elapsed=a.day, days_in_month=dim, lags=detect_lags(a, last_dates),
    )


# =========================================================================== #
# Frames
# =========================================================================== #
def filter_frame(df: pd.DataFrame, channels: list[str], categories: list[str]) -> pd.DataFrame:
    mask = pd.Series(True, index=df.index)
    if channels:
        mask &= df["channel"].isin(channels)
    if categories:
        mask &= df["category"].isin(categories)
    return df[mask]


def add_lag(df: pd.DataFrame | None, P: Periods) -> pd.DataFrame | None:
    if df is None:
        return None
    return df.assign(lag_td=pd.to_timedelta(df["channel"].map(dict(P.lags)).fillna(0), unit="D"))


def add_aov_columns(df: pd.DataFrame, use_orders: bool = True) -> pd.DataFrame:
    """
    Blended AOV denominator.
      * Website / EBO / Flipkart rows with orders -> real orders
      * every other row                           -> quantity (so AOV falls back to ASP)
    aov_proxy flags rows where the ASP fallback was used.
    """
    real = (df["channel"].isin(config.ORDER_CHANNELS) & df["orders"].notna()) if use_orders \
        else pd.Series(False, index=df.index)
    df = df.assign(aov_den=df["orders"].where(real, df["quantity"]))
    df["aov_proxy"] = (~real & df["quantity"].notna()).astype(float)
    return df


def prepare_category_frame(df: pd.DataFrame) -> pd.DataFrame:
    d = df[df["category"].notna()]
    return add_aov_columns(d, use_orders=config.AGG_ORDERS == "SUM")


def channel_daily(df: pd.DataFrame, categories: list[str]) -> pd.DataFrame:
    """Roll category rows up to date x channel, honouring the orders/target aggregation mode."""
    g = df.groupby(["date", "channel"], sort=False)
    out = g[ADDITIVE].sum(min_count=1)
    for col, agg in (("orders", config.AGG_ORDERS), ("target_sales", config.AGG_TARGET)):
        out[col] = g[col].max() if agg == "MAX" else g[col].sum(min_count=1)
    out["est"] = g["est"].max()
    out = out.reset_index()
    if categories:
        # Targets are channel-level. Orders survive only for a single category with
        # category-allocated orders; otherwise they would double count.
        out["target_sales"] = np.nan
        if not (len(categories) == 1 and config.AGG_ORDERS == "SUM"):
            out["orders"] = np.nan
    out["group"] = out["channel"].map(config.CHANNEL_GROUPS).fillna("Other")
    return add_aov_columns(out)


def prepare_ads(ads: pd.DataFrame | None, channels: list[str], P: Periods) -> tuple[pd.DataFrame | None, bool]:
    """Returns (ads, filtered). Ads are filtered by channel only when the table carries our channel names."""
    if ads is None or ads.empty:
        return None, False
    has_channels = ads["channel"].isin(config.CHANNELS).any()
    a = ads[ads["channel"].isin(channels)] if (channels and has_channels) else ads
    a = a.assign(channel=a["channel"].fillna(""))
    return add_lag(a, P), bool(channels and has_channels)


def attach_targets(cd: pd.DataFrame, targets: pd.DataFrame | None, channels: list[str],
                   categories: list[str]) -> pd.DataFrame:
    """
    Merge date x channel AOP targets onto the daily channel frame. Target-only dates (the rest of
    the month or year) are kept so pacing can use them. Hidden while a category filter is on,
    because targets aren't split by category.
    """
    if targets is None or targets.empty or categories:
        cd = cd.copy()
        cd["target_sales"] = np.nan
        cd["achieved_sales"] = np.nan
        cd["ach_metric"] = np.nan
        return cd
    t = targets[targets["channel"].isin(channels)] if channels else targets
    t = t.groupby(["date", "channel"], as_index=False)[["target_sales", "achieved_sales"]].sum(min_count=1)
    out = cd.drop(columns=["target_sales"]).merge(t, on=["date", "channel"], how="outer")
    out["group"] = out["channel"].map(config.CHANNEL_GROUPS).fillna("Other")
    for col in ("aov_proxy", "est"):
        out[col] = out[col].fillna(0.0)
    out["ach_metric"] = achieved_series(out)
    return out


def achieved_series(df: pd.DataFrame) -> pd.Series:
    """
    Per-row achievement figure: the daily AOP table's achieved revenue for channels that have it
    loaded at all (e.g. Website, Amazon-UAE), else MRP sales for channels the daily table has never
    tracked (Amazon-SC, Amazon-VC only appear there as a combined "Amazon" row, and Tata Cliq_Others
    / Smytten aren't in it at all) -- so those channels still show progress against their AOP target
    instead of a permanent blank.
    """
    if "achieved_sales" not in df or not df["achieved_sales"].notna().any():
        return df[config.TARGET_METRIC]
    has_ach = df.groupby("channel")["achieved_sales"].transform(lambda s: s.notna().any())
    return df["achieved_sales"].where(has_ach, df[config.TARGET_METRIC])


def aop_for(aop: pd.DataFrame | None, channels: list[str], start=None, end=None,
            by: str | None = None, fy_start: int | None = None):
    """
    Sum of monthly AOP, optionally per channel/group. Either months starting within [start, end],
    or a whole financial year (fy_start=2026 -> Financial_Year '2026-27'), exactly like
    SUM(Revenue) WHERE Financial_Year = '2026-27'. An empty channel list means all channels.
    """
    if aop is None or aop.empty:
        return None
    if fy_start is not None:
        a = aop[aop["fy_start"] == fy_start]
    else:
        a = aop[(aop["date"] >= pd.Timestamp(start)) & (aop["date"] <= pd.Timestamp(end))]
    if channels:
        a = a[a["channel"].isin(channels)]
    if a.empty:
        return None
    if by == "channel":
        return a.groupby("channel")["aop"].sum(min_count=1)
    if by == "group":
        return a.assign(group=a["channel"].map(config.CHANNEL_GROUPS).fillna("Other")).groupby("group")["aop"].sum(min_count=1)
    return _v(a["aop"].sum(min_count=1))


def between(df: pd.DataFrame, start, end) -> pd.DataFrame:
    return df[(df["date"] >= start) & (df["date"] <= end)]


def window(df: pd.DataFrame, start, end, shift_start: bool = False) -> pd.DataFrame:
    """
    Date window that respects channel lags: a channel that lands N days late has its
    window end (and, for single-day windows, its start) moved N days earlier.
    """
    if df is None:
        return None
    end_eff = pd.Timestamp(end) - df["lag_td"]
    start_eff = (pd.Timestamp(start) - df["lag_td"]) if shift_start else pd.Timestamp(start)
    return df[(df["date"] >= start_eff) & (df["date"] <= end_eff)]


# =========================================================================== #
# Block metrics (one window, any grain)
# =========================================================================== #
def block(w: pd.DataFrame, days: int | None = None, ads: pd.DataFrame | None = None) -> dict:
    gross, mrp, net = _sum(w, "gross_sales"), _sum(w, "mrp_sales"), _sum(w, "net_sales")
    qty = _sum(w, "quantity")
    has_t = "target_sales" in w and w["target_sales"].notna().any()
    t = w[w["target_sales"].notna()] if has_t else None
    t_act, t_tgt = (_sum(t, "ach_metric"), _sum(t, "target_sales")) if has_t else (None, None)
    ad = _sum(ads, "ad_spend") if ads is not None else None
    return {
        "gross": gross, "mrp": mrp, "net": net, "qty": qty,
        "orders": _sum(w, "orders") if "orders" in w else None,
        "discount": (1 - gross / mrp) if gross is not None and mrp else None,
        "asp": ratio(gross, qty),
        "aov": ratio(_sum(w[w["aov_den"].notna()], "gross_sales"), _sum(w, "aov_den")) if len(w) else None,
        "aov_proxy": bool((w["aov_proxy"] > 0).any()) if len(w) else False,
        "est": bool((w["est"] > 0).any()) if len(w) and "est" in w else False,
        "target": t_tgt, "target_actual": t_act, "ach": ratio(t_act, t_tgt),
        "per_day": ratio(gross, days) if days else None,
        "ad_spend": ad, "ad_share": ratio(ad, gross),
    }


def growth(cur: dict, prev: dict):
    key = {"mrp_sales": "mrp", "gross_sales": "gross"}[config.GROWTH_METRIC]
    return pct(cur[key], prev[key])


def _target_total(cd: pd.DataFrame, start, end, days: int):
    """Sum of AOP targets in a window; pro-rated when targets aren't loaded to the end."""
    t = between(cd, start, end)
    t = t[t["target_sales"].notna()]
    if t.empty:
        return None, False
    total = float(t["target_sales"].sum())
    if t["date"].max() >= pd.Timestamp(end):
        return total, False
    return total / t["date"].nunique() * days, True


def _diff(a, b):
    return None if a is None or b is None else a - b


def _lagged_projection(w: pd.DataFrame, P: Periods, col: str = "gross_sales"):
    """Month-end run-rate where each channel is paced over the days it actually has."""
    if w.empty:
        return None
    by = w.groupby("channel")[col].sum(min_count=1).dropna()
    if by.empty:
        return None
    elapsed = (P.days_elapsed - by.index.map(P.lag)).to_numpy().clip(min=1)
    return float((by.to_numpy() / elapsed).sum() * P.days_in_month)


# =========================================================================== #
# KPI snapshot: MTD vs LMTD everywhere, plus year-to-date vs last year
# =========================================================================== #
def kpi_snapshot(cd: pd.DataFrame, ads: pd.DataFrame | None, P: Periods,
                 aop: pd.DataFrame | None = None, channels: list[str] | None = None) -> dict:
    mtd_w = window(cd, P.cur_start, P.as_of)
    cur = block(mtd_w, P.cur_days, window(ads, P.cur_start, P.as_of))
    prev = block(window(cd, P.cmp_start, P.cmp_end), P.cmp_days, window(ads, P.cmp_start, P.cmp_end))
    month_w = window(cd, P.mtd_start, P.as_of)

    s = {"cur": cur, "prev": prev}
    s["growth"] = growth(cur, prev)
    s["growth_change"] = _diff(cur["mrp"], prev["mrp"]) if config.GROWTH_METRIC == "mrp_sales" \
        else _diff(cur["gross"], prev["gross"])
    s["mrp_mom"] = pct(cur["mrp"], prev["mrp"])
    s["gross_mom"] = pct(cur["gross"], prev["gross"])
    s["net_mom"] = pct(cur["net"], prev["net"])
    s["disc_change"] = _diff(cur["discount"], prev["discount"])
    s["aov_mom"] = pct(cur["aov"], prev["aov"])
    s["asp_mom"] = pct(cur["asp"], prev["asp"])
    s["ach_change"] = _diff(cur["ach"], prev["ach"])
    s["ad_mom"] = pct(cur["ad_spend"], prev["ad_spend"])
    s["qty_mom"] = pct(cur["qty"], prev["qty"])

    ytd = block(window(cd, P.ytd_start, P.as_of))
    ly_ytd = block(window(cd, P.ly_ytd_start, P.ly_ytd_end))
    s["ytd_gross"], s["ly_ytd_gross"] = ytd["gross"], ly_ytd["gross"]
    s["ytd_yoy"] = pct(ytd["gross"], ly_ytd["gross"])
    s["ytd_est"] = ytd["est"]

    s["target_channels"] = int(mtd_w.loc[mtd_w["target_sales"].notna(), "channel"].nunique())
    s["active_channels"] = int(mtd_w.loc[mtd_w["mrp_sales"].notna(), "channel"].nunique())
    plan_month = aop_for(aop, channels or [], P.mtd_start, P.mtd_start)
    if plan_month is not None:
        s["month_target"], s["month_target_estimated"] = plan_month, False
    else:
        s["month_target"], s["month_target_estimated"] = _target_total(cd, P.mtd_start, P.month_end, P.days_in_month)
    s["month_achieved"] = _sum(month_w[month_w["target_sales"].notna()], "ach_metric")

    s["projection"] = _lagged_projection(month_w, P, config.TARGET_METRIC)
    s["target_projection"] = _lagged_projection(month_w[month_w["ach_metric"].notna()], P, "ach_metric")
    s["current_rr"] = s["target_projection"] / P.days_in_month if s["target_projection"] is not None else None
    s["projected_ach"] = ratio(s["target_projection"], s["month_target"])
    s["month_ach"] = ratio(s["month_achieved"], s["month_target"])
    # year pacing (financial year to date vs the full-year AOP)
    ytd_w = window(cd, P.ytd_start, P.as_of)
    s["year_actual"] = _sum(ytd_w[ytd_w["target_sales"].notna()], "ach_metric")
    plan_year = aop_for(aop, channels or [], fy_start=P.ytd_start.year)
    if plan_year is not None:
        s["year_target"], s["year_target_estimated"] = plan_year, False
    else:
        s["year_target"], s["year_target_estimated"] = _target_total(cd, P.ytd_start, P.year_end, P.year_days)
    s["year_ach"] = ratio(s["year_actual"], s["year_target"])
    s["year_rr"] = ratio(s["year_actual"], P.year_days_elapsed)
    s["year_projection"] = s["year_rr"] * P.year_days if s["year_rr"] is not None else None
    s["year_projected_ach"] = ratio(s["year_projection"], s["year_target"])
    return s


# =========================================================================== #
# Tables
# =========================================================================== #
_SUMS = ["mrp_sales", "gross_sales", "net_sales", "quantity", "orders", "target_sales",
         "aov_den", "aov_proxy", "est"]


def _grouped(w: pd.DataFrame, key: str) -> pd.DataFrame:
    cols = [c for c in _SUMS if c in w]
    out = w.groupby(key)[cols].sum(min_count=1)
    if "target_sales" in w:
        # ach_metric is only present after attach_targets (channel frames); the category frame never
        # gets targets merged in, but keep this column-safe rather than crash on the always-NaN case.
        ach_col = "ach_metric" if "ach_metric" in w else config.TARGET_METRIC
        out["t_act"] = w[w["target_sales"].notna()].groupby(key)[ach_col].sum(min_count=1)
    out["aov_num"] = w[w["aov_den"].notna()].groupby(key)["gross_sales"].sum(min_count=1)
    return out


def _ratio_col(num: pd.Series, den: pd.Series) -> pd.Series:
    return num / den.where(den > 0)


def _common_columns(out: pd.DataFrame, mtd: pd.DataFrame, lmtd: pd.DataFrame) -> None:
    out["MRP sales"] = mtd["mrp_sales"]
    out["Gross sales"] = mtd["gross_sales"]
    out["Net sales"] = mtd["net_sales"]
    out["Discount"] = 1 - _ratio_col(mtd["gross_sales"], mtd["mrp_sales"])
    out["AOV"] = _ratio_col(mtd["aov_num"], mtd["aov_den"])
    out["ASP"] = _ratio_col(mtd["gross_sales"], mtd["quantity"])
    out["MoM"] = _vpct(mtd[config.GROWTH_METRIC], lmtd[config.GROWTH_METRIC])
    total = mtd[config.GROWTH_METRIC].sum(min_count=1)
    out["Share"] = mtd[config.GROWTH_METRIC] / total if not is_na(total) and total > 0 else np.nan
    out["LMTD"] = lmtd[config.GROWTH_METRIC]
    out["Δ vs LMTD"] = mtd[config.GROWTH_METRIC] - lmtd[config.GROWTH_METRIC]
    out["LMTD AOV"] = _ratio_col(lmtd["aov_num"], lmtd["aov_den"])
    out["aov_proxy"] = mtd["aov_proxy"].fillna(0) > 0
    out["est"] = mtd["est"].fillna(0) > 0


def channel_table(cd: pd.DataFrame, P: Periods, key: str = "channel",
                  aop: pd.DataFrame | None = None, channels: list[str] | None = None) -> pd.DataFrame:
    mtd = _grouped(window(cd, P.cur_start, P.as_of), key)
    lmtd = _grouped(window(cd, P.cmp_start, P.cmp_end), key)
    plan = aop_for(aop, channels or [], P.aop_start, P.mtd_start, by=key)
    # AOP lines without sales rows of their own (Amazon, NPD, ...) stay in so the Target column totals the plan
    idx = sorted(set(mtd.index) | set(lmtd.index) | (set(plan.index) if plan is not None else set()))
    mtd, lmtd = mtd.reindex(idx), lmtd.reindex(idx)

    out = pd.DataFrame(index=pd.Index(idx, name=key))
    _common_columns(out, mtd, lmtd)
    if plan is not None:
        # AOP for the whole months in the period; achieved to date against it (read with time elapsed)
        achieved = window(cd, P.aop_start, P.as_of).groupby(key)["ach_metric"].sum(min_count=1).reindex(idx)
        out["Target"] = plan.reindex(idx)
        out["Ach."] = _ratio_col(achieved, out["Target"])
    else:
        out["Target"] = mtd["target_sales"]
        out["Ach."] = _ratio_col(mtd["t_act"], mtd["target_sales"])
    out["Orders"] = mtd["orders"]
    out["LMTD orders"] = lmtd["orders"]
    out = out.dropna(subset=["MRP sales", "LMTD", "Target"], how="all")
    return out.sort_values("MRP sales", ascending=False, na_position="last").reset_index()


def category_table(fdf: pd.DataFrame, P: Periods) -> pd.DataFrame:
    mtd = _grouped(window(fdf, P.cur_start, P.as_of), "category")
    lmtd = _grouped(window(fdf, P.cmp_start, P.cmp_end), "category")
    idx = sorted(set(mtd.index) | set(lmtd.index))
    mtd, lmtd = mtd.reindex(idx), lmtd.reindex(idx)
    out = pd.DataFrame(index=pd.Index(idx, name="Category"))
    _common_columns(out, mtd, lmtd)
    out = out.dropna(subset=["MRP sales", "LMTD"], how="all")
    return out.sort_values("MRP sales", ascending=False, na_position="last").reset_index()


# --------------------------------------------------------------------------- #
# Monthly trend: trailing months with last year's value for each
# --------------------------------------------------------------------------- #
def _month_end_ts(m: pd.Timestamp) -> pd.Timestamp:
    return m.replace(day=calendar.monthrange(m.year, m.month)[1])


def monthly_trend(cd: pd.DataFrame, ads: pd.DataFrame | None, P: Periods,
                  months: int | None = None) -> pd.DataFrame:
    """
    One row per month. Full months use full-month totals. The current month holds MTD actuals
    (lag-aware), a run-rate projection for the chart, and YoY / MoM on the same days.
    """
    months = months or config.TREND_MONTHS
    starts = pd.date_range(P.mtd_start - pd.DateOffset(months=months - 1), P.mtd_start, freq="MS")
    rows = []
    for m in starts:
        current = m == P.mtd_start
        if current:
            cur_w, cur_a = window(cd, P.mtd_start, P.as_of), window(ads, P.mtd_start, P.as_of)
            ly_same = block(window(cd, _ly(P.mtd_start), _ly(P.as_of)))
            prev = block(window(cd, P.lmtd_start, P.lmtd_end))
            ly_full = block(between(cd, _ly(m), _month_end_ts(_ly(m))))
        else:
            e = _month_end_ts(m)
            cur_w, cur_a = between(cd, m, e), (between(ads, m, e) if ads is not None else None)
            pm = m - pd.DateOffset(months=1)
            prev = block(between(cd, pm, _month_end_ts(pm)))
            ly_full = ly_same = block(between(cd, _ly(m), _month_end_ts(_ly(m))))
        b = block(cur_w, ads=cur_a)
        row = {
            "month": m, "label": m.strftime("%b %y"), "current": current,
            "mrp": b["mrp"], "gross": b["gross"], "net": b["net"], "qty": b["qty"],
            "discount": b["discount"], "aov": b["aov"], "asp": b["asp"], "est": b["est"],
            "aop": b["target"], "aop_ach": b["ach"],
            "ad_spend": b["ad_spend"], "ad_share": b["ad_share"],
            "ly_mrp": ly_full["mrp"], "ly_gross": ly_full["gross"], "ly_net": ly_full["net"],
            "ly_qty": ly_full["qty"],
        }
        for k, key in (("mrp", "mrp"), ("gross", "gross"), ("net", "net"), ("qty", "qty")):
            row[f"yoy_{k}"] = pct(b[key], ly_same[key])
            row[f"mom_{k}"] = pct(b[key], prev[key])
        rows.append(row)
    return pd.DataFrame(rows)


# =========================================================================== #
# Series for charts
# =========================================================================== #
def target_frame(cd: pd.DataFrame, P: Periods, mode: str,
                 aop: pd.DataFrame | None = None, channels: list[str] | None = None) -> pd.DataFrame:
    """Day: that day's achieved vs daily target. Period: achieved to date vs AOP for the period's months."""
    empty = pd.DataFrame(columns=["channel", "actual", "target", "ach"])
    if mode == "Day":
        w = window(cd, P.as_of, P.as_of, shift_start=True)  # the period's last day
        w = w[w["target_sales"].notna()]
        if w.empty:
            return empty
        g = w.groupby("channel").agg(actual=("ach_metric", lambda x: x.sum(min_count=1)), target=("target_sales", "sum"))
    else:
        plan = aop_for(aop, channels or [], P.aop_start, P.mtd_start, by="channel")
        w = window(cd, P.aop_start, P.as_of)
        if plan is not None:
            g = pd.DataFrame({"target": plan})
            g["actual"] = w.groupby("channel")["ach_metric"].sum(min_count=1).reindex(g.index)
        else:
            w = w[w["target_sales"].notna()]
            if w.empty:
                return empty
            g = w.groupby("channel").agg(actual=("ach_metric", lambda x: x.sum(min_count=1)), target=("target_sales", "sum"))
    g.index.name = "channel"
    g["ach"] = g["actual"] / g["target"].where(g["target"] > 0)
    return g.sort_values("target", ascending=True).reset_index()


# Sources worth a note when they run out; gross gaps are handled by the fallback rules.
COVERAGE_SOURCES = ("Sales", "Ad spends", "AOP achievement")


def coverage_notes(spans: dict, start, end) -> list[str]:
    """Short sentences for sources that don't cover the selected window."""
    start, end = pd.Timestamp(start), pd.Timestamp(end)
    out = []
    for label in COVERAGE_SOURCES:
        if label not in spans:
            continue
        first, last = (pd.Timestamp(d) for d in spans[label])
        if last < start:
            out.append(f"No {label.lower()} after {fmt_date(last, True)}.")
        elif last < end:
            out.append(f"{label} available to {fmt_date(last, True)}.")
        elif first > start:
            out.append(f"{label} start on {fmt_date(first, True)}.")
    return out


# =========================================================================== #
# Insights & watchlist (all figures computed; no generated prose)
# =========================================================================== #
def insights(cd: pd.DataFrame, P: Periods, s: dict, tbl: pd.DataFrame) -> list[str]:
    out: list[str] = []
    b = lambda x: f"<b>{html.escape(str(x))}</b>"  # noqa: E731
    cur, prev = s["cur"], s["prev"]
    basis = metric_lc(config.GROWTH_METRIC)
    key = "mrp" if config.GROWTH_METRIC == "mrp_sales" else "gross"

    if cur[key] is not None and s["growth"] is not None:
        direction = "ahead of" if s["growth"] >= 0 else "behind"
        label = basis[0].upper() + basis[1:]
        out.append(f"{label} of {b(fmt_inr(cur[key]))} are {b(fmt_pct(abs(s['growth']), signed=False))} "
                   f"{direction} {P.cmp_phrase} ({fmt_inr(prev[key])}).")

    if s["month_target"] and s["projected_ach"] is not None:
        out.append(f"At the current pace MRP sales close the month at {b(fmt_inr(s['target_projection']))}, "
                   f"{b(fmt_pct(s['projected_ach'], signed=False))} of the {fmt_inr(s['month_target'])} AOP.")
    if s["year_target"] and s["year_projected_ach"] is not None:
        out.append(f"{P.year_label}, MRP sales are {b(fmt_inr(s['year_actual']))}, "
                   f"{fmt_pct(s['year_ach'], signed=False)} of the full-year AOP, tracking to "
                   f"{b(fmt_pct(s['year_projected_ach'], signed=False))}.")

    d = tbl.dropna(subset=["Δ vs LMTD"])
    if len(d) >= 2:
        up, down = d.loc[d["Δ vs LMTD"].idxmax()], d.loc[d["Δ vs LMTD"].idxmin()]
        parts = []
        if up["Δ vs LMTD"] > 0:
            parts.append(f"{b(up['channel'])} added the most {basis} {P.cmp_label} (+{fmt_inr(up['Δ vs LMTD'])}, {fmt_pct(up['MoM'])})")
        if down["Δ vs LMTD"] < 0:
            parts.append(f"{b(down['channel'])} was the largest drag ({fmt_inr(down['Δ vs LMTD'])}, {fmt_pct(down['MoM'])})")
        if parts:
            out.append("; ".join(parts) + ".")

    if cur["gross"] is not None and cur["discount"] is not None:
        line = f"Gross sales are {b(fmt_inr(cur['gross']))} at a {b(fmt_pct(cur['discount'], signed=False))} discount to MRP"
        chg = pct(cur["discount"], prev["discount"])
        if chg is not None:
            line += f" ({fmt_pct(chg)} {P.cmp_label})"
        out.append(line + ".")

    if cur["ad_spend"] is not None:
        line = f"Ad spends are {b(fmt_inr(cur['ad_spend']))}"
        if s["ad_mom"] is not None:
            line += f" ({fmt_pct(s['ad_mom'])} {P.cmp_label})"
        if cur["ad_share"] is not None:
            line += f", {b(fmt_pct(cur['ad_share'], signed=False))} of gross sales"
            if prev["ad_share"] is not None:
                line += f" vs {fmt_pct(prev['ad_share'], signed=False)} in {P.cmp_phrase}"
        out.append(line + ".")

    if s["ytd_yoy"] is not None:
        word = "up" if s["ytd_yoy"] >= 0 else "down"
        out.append(f"{P.year_label}, gross sales are {b(fmt_inr(s['ytd_gross']))}, "
                   f"{word} {b(fmt_pct(abs(s['ytd_yoy']), signed=False))} on the same period last year.")

    qc = tbl[tbl["channel"].isin(config.QUICK_COMMERCE)]
    if len(qc) and cur[key] and prev[key]:
        now_share = qc["MRP sales" if key == "mrp" else "Gross sales"].sum(min_count=1) / cur[key]
        prev_share = qc["LMTD"].sum(min_count=1) / prev[key]
        if not is_na(now_share) and not is_na(prev_share) and 0 < now_share < 1:
            out.append(f"Quick commerce is {b(fmt_pct(now_share, signed=False))} of {basis}, "
                       f"vs {fmt_pct(prev_share, signed=False)} in {P.cmp_phrase}.")

    return out[:6]


def watchlist(cd: pd.DataFrame, P: Periods, tbl: pd.DataFrame, last_dates: dict,
              scope: list[str], est_meta: dict) -> list[tuple[str, str]]:
    """Return (severity, html) tuples. severity: 'high' | 'medium'."""
    items: list[tuple[str, str]] = []
    stale = set()
    for ch in scope:
        ld = last_dates.get(ch)
        expected = P.as_of - pd.Timedelta(days=config.EXPECTED_LAG_DAYS.get(ch, 0))
        if ld is not None and pd.Timestamp(ld) < expected:
            stale.add(ch)
            lag = (expected - pd.Timestamp(ld)).days
            items.append(("high", f"<b>{html.escape(ch)}</b> data missing for {fmt_date(expected)} "
                                  f"(last loaded {fmt_date(ld)}, {lag} day{'s' if lag > 1 else ''} late)."))

    for ch, m in est_meta.items():
        if ch in scope:
            age = (P.as_of - pd.Timestamp(m["last_actual"])).days
            if age > config.WEEKLY_OVERDUE_DAYS:
                items.append(("medium", f"<b>{html.escape(ch)}</b> weekly gross is {age} days old "
                                        f"(last update {fmt_date(m['last_actual'])}); figures since are estimated."))

    # day swings on MRP (actual for every channel), on each channel's own latest day
    for ch in cd["channel"].unique():
        if ch in stale:
            continue
        day = P.data_end(ch)
        c = cd[cd["channel"] == ch]
        today = _v(c.loc[c["date"] == day, "mrp_sales"].sum(min_count=1))
        trail = between(c, day - 7 * DAY, day - DAY)["mrp_sales"].mean()
        total_trail = between(cd, P.as_of - 7 * DAY, P.yday)["mrp_sales"].sum() / 7
        if today is None or is_na(trail) or trail <= 0 or trail < total_trail * config.ANOMALY_MIN_SHARE:
            continue
        v = today / trail - 1
        if abs(v) >= config.ANOMALY_DEVIATION:
            word = "below" if v < 0 else "above"
            items.append(("high" if v < 0 else "medium",
                          f"<b>{html.escape(ch)}</b> MRP sales on {fmt_date(day)} were {fmt_inr(today)}, "
                          f"{fmt_pct(abs(v), signed=False)} {word} its 7-day average."))

    for _, r in tbl.iterrows():
        if r["channel"] in stale:
            continue
        name = html.escape(r["channel"])
        if not is_na(r["Ach."]) and r["Ach."] < config.TARGET_LAG_THRESHOLD * P.aop_progress:
            items.append(("medium", f"<b>{name}</b> has achieved {fmt_pct(r['Ach.'], signed=False)} of its AOP "
                                    f"with {fmt_pct(P.aop_progress, signed=False)} of the time gone."))
        elif (not is_na(r["MoM"]) and r["MoM"] <= config.MOM_DECLINE_THRESHOLD
              and not is_na(r["Share"]) and r["Share"] >= config.MOM_MIN_SHARE):
            items.append(("medium", f"<b>{name}</b> is down {fmt_pct(abs(r['MoM']), signed=False)} {P.cmp_label}."))

    items.sort(key=lambda x: 0 if x[0] == "high" else 1)
    return items[:6]


def nice_ticks(vmin: float, vmax: float, n: int = 5) -> list[float]:
    vmin, vmax = min(vmin, 0.0), max(vmax, 0.0)
    span = vmax - vmin
    if span <= 0 or math.isnan(span):
        return [0.0]
    raw = span / n
    mag = 10 ** math.floor(math.log10(raw))
    step = next(m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw)
    lo, hi = math.floor(vmin / step), math.ceil(vmax / step)
    return [i * step for i in range(lo, hi + 1)]
