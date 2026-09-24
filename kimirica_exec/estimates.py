"""
Filling in gross sales.

MRP sales are daily and authoritative for every channel. Gross sales are taken in this order:

  1. Sales master, wherever it has a value.
  2. Weekly gross table (day grain, refreshed weekly), for rows the sales master leaves empty.
     Matched by category where the weekly table has a real one; a channel-level (or "Unmapped")
     weekly figure is spread across that day's category rows by MRP share instead.
  3. Estimated: daily MRP x (1 - discount), where the discount is gross / MRP over the
     EST_LOOKBACK_DAYS of actuals before the channel's last actual day, per category when possible.
  4. Estimated with DEFAULT_DISCOUNT (11%) when a channel has no actuals to learn from.

Filled rows carry est = 1. Net sales are derived from gross afterwards.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import config

EstimateMeta = dict  # channel -> {"last_actual": Timestamp | None, "discount": float, "estimated_days": int}


def _ratio(num: pd.Series, den: pd.Series) -> float:
    d = den.sum()
    return float(num.sum() / d) if d and d > 0 else np.nan


def _default_discount(channel) -> float:
    """A channel's no-history fallback discount: CHANNEL_DEFAULT_DISCOUNT override, else DEFAULT_DISCOUNT."""
    return config.CHANNEL_DEFAULT_DISCOUNT.get(channel, config.DEFAULT_DISCOUNT)


def _clamp_gross(filled: np.ndarray, mrp: np.ndarray) -> np.ndarray:
    """Gross can never exceed MRP (discount is never negative) or be negative. A weekly-table row
    that breaks this is bad data, not a real figure -- treat it as not-loaded so the discount-
    estimate fallback fills it instead of showing an impossible number."""
    valid = np.isfinite(filled) & (filled >= 0) & (filled <= mrp + 1e-6)
    return np.where(valid, filled, np.nan)


def _from_weekly(df: pd.DataFrame, weekly: pd.DataFrame) -> pd.DataFrame:
    """
    Fill empty gross from the weekly table, in two passes:
      1. Match date x channel x category directly, wherever the weekly table actually has that
         category (channels like Blinkit are split by real category throughout).
      2. Whatever's left is a channel-level (or partly-unmapped) weekly figure -- spread it by MRP
         share across that date x channel's still-empty category rows.
    Some channels' weekly rows are only ever tagged "Unmapped" (normalized to NULL category at
    load) even though the sales master itself has real categories for them -- a single all-or-
    nothing category match would then never fire for those rows, silently losing the whole
    channel's weekly gross (this is what was happening to Myntra, and partly to Nykaa/Tira).
    Running both passes handles a channel that's 100% real category, 100% unmapped, or a mix.
    """
    channels = set(weekly["channel"].dropna())
    part_mask = df["channel"].isin(channels) & df["gross_sales"].isna()
    if not part_mask.any():
        return df
    df = df.copy()

    # Pass 1: real-category weekly rows match a category row directly.
    real_w = weekly[weekly["category"].notna()]
    part = df[part_mask]
    if not real_w.empty and part["category"].notna().any():
        w_cat = real_w.groupby(["date", "channel", "category"], dropna=False)["gross_sales"].sum(min_count=1)
        matched = part.join(w_cat.rename("gross_w"), on=["date", "channel", "category"])["gross_w"].to_numpy()
        df.loc[part_mask, "gross_sales"] = _clamp_gross(matched, part["mrp_sales"].to_numpy())

    # Pass 2: whatever the weekly table couldn't attribute to a category is a channel-day total;
    # spread it across that date x channel's rows that are STILL empty after pass 1.
    still_gap = df["channel"].isin(channels) & df["gross_sales"].isna()
    w_chan = weekly[weekly["category"].isna()].groupby(["date", "channel"])["gross_sales"].sum(min_count=1)
    if still_gap.any() and w_chan.notna().any():
        rem = df[still_gap]
        joined = rem.join(w_chan.rename("gross_w"), on=["date", "channel"])
        grp = rem.groupby(["date", "channel"])["mrp_sales"]
        total = grp.transform("sum")
        share = (rem["mrp_sales"] / total.where(total > 0)).where(grp.transform("size") > 1, 1.0)
        filled = (joined["gross_w"] * share).to_numpy()
        df.loc[still_gap, "gross_sales"] = _clamp_gross(filled, rem["mrp_sales"].to_numpy())
    return df


def _fill_prior_fy_gross(df: pd.DataFrame, max_date) -> pd.DataFrame:
    """
    Derive gross for last financial year's gaps, channel-wise, so YoY / last-year comparisons have
    full coverage even where the sales master and weekly table don't go back that far or never had
    gross for that channel:

      1. Real gross (sales master or weekly table, already filled in by this point) always wins.
      2. Else, if this FY's matching month (the same calendar month, one year later) has real gross
         for that channel, apply that month's discount (1 - gross/MRP) to last year's MRP.
      3. Else -- this FY's matching month hasn't happened yet, or never had real gross either --
         apply that channel's average discount across whichever months of this FY DO have real
         gross. A channel with no real discount anywhere this FY falls back to DEFAULT_DISCOUNT.

    Runs after the weekly-table fill and before the general rolling-lookback estimate, so it wins
    for last-FY dates while every other period is untouched and still uses the general estimate.
    """
    fy_start_this = pd.Timestamp(config.year_start(max_date))
    fy_start_last = fy_start_this - pd.DateOffset(years=1)
    fy_end_last = fy_start_this - pd.Timedelta(days=1)

    gap = ((df["date"] >= fy_start_last) & (df["date"] <= fy_end_last)
           & df["gross_sales"].isna() & df["mrp_sales"].notna())
    if not gap.any():
        return df

    df = df.copy()
    df["_month"] = df["date"].dt.to_period("M")
    df["_ty_month"] = (df["date"] + pd.DateOffset(years=1)).dt.to_period("M")

    this_fy_actual = (df["date"] >= fy_start_this) & df["gross_sales"].notna() & df["mrp_sales"].notna()
    monthly = df.loc[this_fy_actual].groupby(["channel", "_month"]).agg(
        g=("gross_sales", "sum"), m=("mrp_sales", "sum"))
    monthly["discount"] = 1 - monthly["g"] / monthly["m"].where(monthly["m"] > 0)
    disc_by_month = monthly["discount"].dropna().to_dict()                       # (channel, Period) -> discount
    avg_discount = monthly["discount"].dropna().groupby(level=0).mean().to_dict()  # channel -> avg discount

    for ch in df.loc[gap, "channel"].dropna().unique():
        rows = gap & (df["channel"] == ch)
        rate = df.loc[rows, "_ty_month"].map(lambda p: disc_by_month.get((ch, p))).astype(float)
        rate = rate.fillna(avg_discount.get(ch, _default_discount(ch)))
        df.loc[rows, "gross_sales"] = df.loc[rows, "mrp_sales"] * (1 - rate.to_numpy())
        df.loc[rows, "est"] = 1.0
    return df.drop(columns=["_month", "_ty_month"])


def fill_gross(sales: pd.DataFrame, weekly: pd.DataFrame | None,
               lookback_days: int | None = None, max_date=None) -> tuple[pd.DataFrame, EstimateMeta]:
    lookback = pd.Timedelta(days=lookback_days or config.EST_LOOKBACK_DAYS)
    df = sales.copy()
    df["est"] = 0.0
    if weekly is not None and not weekly.empty:
        df = _from_weekly(df, weekly)
    if max_date is not None:
        df = _fill_prior_fy_gross(df, max_date)

    meta: EstimateMeta = {}
    gap = df["gross_sales"].isna() & df["mrp_sales"].notna()
    for ch in df.loc[gap, "channel"].dropna().unique():
        rows = df["channel"] == ch
        actual = rows & df["gross_sales"].notna() & df["mrp_sales"].notna()
        last = df.loc[actual, "date"].max() if actual.any() else None

        if last is not None:
            hist = df[actual & (df["date"] > last - lookback) & (df["date"] <= last)]
            ch_rate = _ratio(hist["gross_sales"], hist["mrp_sales"])
            cat_rate = {}
            if hist["category"].notna().any():
                for cat, g in hist.groupby("category"):
                    r = _ratio(g["gross_sales"], g["mrp_sales"])
                    if not np.isnan(r):
                        cat_rate[cat] = r
        else:
            ch_rate, cat_rate = np.nan, {}
        default_rate = 1 - _default_discount(ch)
        if np.isnan(ch_rate):
            ch_rate = default_rate

        fill = rows & gap
        rate = df.loc[fill, "category"].map(cat_rate).astype(float).fillna(ch_rate)
        df.loc[fill, "gross_sales"] = df.loc[fill, "mrp_sales"] * rate
        df.loc[fill, "est"] = 1.0
        meta[ch] = {"last_actual": last, "discount": 1 - ch_rate,
                    "default_used": last is None,
                    "estimated_days": int(df.loc[fill, "date"].nunique())}
    return df, meta
