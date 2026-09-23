"""
Filling in gross sales.

MRP sales are daily and authoritative for every channel. Gross sales are taken in this order:

  1. Sales master, wherever it has a value.
  2. Weekly gross table (day grain, refreshed weekly), for rows the sales master leaves empty.
     A channel-level weekly table is spread across category rows by MRP share.
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


def _from_weekly(df: pd.DataFrame, weekly: pd.DataFrame) -> pd.DataFrame:
    """Fill empty gross from the weekly table, matching on category when both have it."""
    channels = set(weekly["channel"].dropna())
    part_mask = df["channel"].isin(channels) & df["gross_sales"].isna()
    if not part_mask.any():
        return df
    part = df[part_mask]

    by_category = weekly["category"].notna().any() and part["category"].notna().any()
    keys = ["date", "channel", "category"] if by_category else ["date", "channel"]
    w = weekly.groupby(keys, dropna=False)["gross_sales"].sum(min_count=1)
    joined = part.join(w.rename("gross_w"), on=keys)

    if by_category:
        share = pd.Series(1.0, index=part.index)
    else:
        grp = part.groupby(["date", "channel"])["mrp_sales"]
        total = grp.transform("sum")
        share = (part["mrp_sales"] / total.where(total > 0)).where(grp.transform("size") > 1, 1.0)

    df = df.copy()
    filled = joined["gross_w"].to_numpy() * share.to_numpy()
    # Gross can never exceed MRP (discount is never negative) or be negative. A hand-entered weekly
    # row that breaks this is bad data, not a real figure -- treat it as not-loaded so the
    # discount-estimate fallback below fills it instead of showing an impossible number.
    mrp = part["mrp_sales"].to_numpy()
    valid = np.isfinite(filled) & (filled >= 0) & (filled <= mrp + 1e-6)
    df.loc[part_mask, "gross_sales"] = np.where(valid, filled, np.nan)
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
        rate = rate.fillna(avg_discount.get(ch, config.DEFAULT_DISCOUNT))
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
        default_rate = 1 - config.DEFAULT_DISCOUNT
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
