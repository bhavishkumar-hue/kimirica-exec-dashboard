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
    df.loc[part_mask, "gross_sales"] = (joined["gross_w"] * share).to_numpy()
    return df


def fill_gross(sales: pd.DataFrame, weekly: pd.DataFrame | None,
               lookback_days: int | None = None) -> tuple[pd.DataFrame, EstimateMeta]:
    lookback = pd.Timedelta(days=lookback_days or config.EST_LOOKBACK_DAYS)
    df = sales.copy()
    df["est"] = 0.0
    if weekly is not None and not weekly.empty:
        df = _from_weekly(df, weekly)

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
