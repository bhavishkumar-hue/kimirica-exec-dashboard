"""
Product view data.

MRP and units come straight from Executive_Sales_Product (the table Executive_Sales_Master is rolled
up from). Gross is shared out to products so that, per date x channel x category, the products add up
to exactly the gross the rest of the dashboard shows -- the product table's Total equals the category
table's. Each product's share is weighted by its own gross where there's one:

  1. the product table's own gross (Website, EBO, Amazon, Flipkart);
  2. else MRP x the product's discount % in Executive_Weekly_Gross_Product that day (report gross /
     report MRP, the same discount-% rule the channels use);
  3. else MRP x the channel-day's discount for that category.

Channels in config.MONTH_DISCOUNT_PRODUCT_CHANNELS (Zepto: no product-level gross anywhere) skip the
weighting: every product gets the channel's discount for that month.

Products whose category is a freebie category, or that have no category in the product master, are
left out, exactly as the category table leaves them out.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import config

KEY = ["date", "channel", "category"]


def build_product_frame(prod: pd.DataFrame, gross: pd.DataFrame | None, pm: pd.DataFrame,
                        df: pd.DataFrame, is_excluded) -> pd.DataFrame:
    p = prod.merge(pm, on="code", how="left")
    p = p[p["category"].notna() & ~p["category"].map(is_excluded)].copy()

    # Rule 2: the product's discount % in the weekly reports that day.
    if gross is not None and not gross.empty:
        g = gross.assign(ratio=gross["report_gross"] / gross["report_mrp"].where(gross["report_mrp"] > 0))
        g = g[np.isfinite(g["ratio"]) & (g["ratio"] >= 0)][["date", "channel", "code", "ratio"]]
        p = p.merge(g, on=["date", "channel", "code"], how="left")
    else:
        p["ratio"] = np.nan
    weight = p["own_gross"].where(p["own_gross"].notna(), p["mrp_sales"] * p["ratio"])

    # Rule 3 and the scaling target: the dashboard's own gross / MRP per date x channel x category.
    t = df[df["category"].notna()].groupby(KEY, as_index=False).agg(
        G=("gross_sales", lambda x: x.sum(min_count=1)), M=("mrp_sales", lambda x: x.sum(min_count=1)))
    p = p.merge(t, on=KEY, how="left")
    weight = weight.fillna(p["mrp_sales"] * (p["G"] / p["M"].where(p["M"] > 0)))

    sum_w = weight.groupby([p[k] for k in KEY]).transform("sum")
    factor = p["G"] / sum_w.where(sum_w > 0)
    p["gross_sales"] = (weight * factor).where(factor.notna(), weight)

    # Zepto-style channels: the channel's discount for the month, the same for every product.
    for ch in config.MONTH_DISCOUNT_PRODUCT_CHANNELS:
        rows = p["channel"] == ch
        if not rows.any():
            continue
        c = df[df["channel"] == ch]
        month = c["date"].dt.to_period("M")
        m = c.groupby(month).agg(G=("gross_sales", lambda x: x.sum(min_count=1)),
                                 M=("mrp_sales", lambda x: x.sum(min_count=1)))
        keep = m["G"] / m["M"].where(m["M"] > 0)
        p.loc[rows, "gross_sales"] = p.loc[rows, "mrp_sales"] * p.loc[rows, "date"].dt.to_period("M").map(keep)

    p["net_sales"] = p["gross_sales"] / (1 + config.GST_RATE)
    p["name"] = p["name"].fillna(p["code"])
    return p[["date", "channel", "category", "code", "name", "mrp_sales", "gross_sales", "net_sales",
              "quantity"]].reset_index(drop=True)
