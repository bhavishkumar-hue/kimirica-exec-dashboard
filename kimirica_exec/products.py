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
    p["category"] = p["category"].astype(object)
    return p[["date", "channel", "category", "code", "name", "mrp_sales", "gross_sales", "net_sales",
              "quantity"]].reset_index(drop=True)


def as_sales_frame(pf: pd.DataFrame) -> pd.DataFrame:
    """
    The product frame rolled up to the dashboard's own grain (date x channel x category), so the
    page's top Products filter can run every card, table and chart on just those products. Orders,
    AOP targets and estimates don't exist per product: orders are left empty (AOV falls back to
    ASP) and nothing is flagged as estimated.
    """
    sums = lambda x: x.sum(min_count=1)  # noqa: E731 -- NULL stays NULL
    out = (pf.groupby(["date", "channel", "category"], as_index=False)
             .agg(mrp_sales=("mrp_sales", sums), gross_sales=("gross_sales", sums),
                  quantity=("quantity", sums), net_sales=("net_sales", sums)))
    out["orders"] = np.nan
    out["target_sales"] = np.nan
    out["est"] = 0.0
    out["channel"] = out["channel"].astype(object)
    out["category"] = out["category"].astype(object)
    return out[["date", "channel", "category", "mrp_sales", "gross_sales", "quantity", "orders",
                "target_sales", "est", "net_sales"]]


ATTRIBUTES = ["sub_category", "sub_category_2", "collection"]
# Product_Master_New placeholders that mean "not set" (Sub Group 2 uses 0 and #N/A, Collection
# Name 'Not Applicable'): such a product just isn't offered under that filter.
_NOT_SET = {"", "0", "#n/a", "n/a", "na", "none", "nan", "null", "not applicable", "-"}


def product_attributes(pf: pd.DataFrame, pm: pd.DataFrame) -> pd.DataFrame:
    """code -> category, sub category, sub category 2, collection, for the products in the frame.
    Spellings that differ only in case or spaces ('Face care' / 'Face Care') become the most
    common one."""
    codes = pd.Index(pf["code"].dropna().unique())
    a = pm.drop_duplicates("code").set_index("code").reindex(codes)[ATTRIBUTES].astype("string")
    a["category"] = pf.groupby("code")["category"].first().reindex(codes).astype("string")
    for col in ATTRIBUTES:
        s = a[col].str.replace(r"\s+", " ", regex=True).str.strip()
        s = s.mask(s.str.lower().isin(_NOT_SET))
        key = s.str.lower()
        common = s.groupby(key).agg(lambda v: v.value_counts().index[0])
        a[col] = key.map(common).astype("string")
    return a


def product_labels(pf: pd.DataFrame) -> dict:
    """code -> name for the Products filter; a name shared by two codes gets its code appended."""
    names = pf.groupby("code")["name"].first().astype(str).str.strip()
    dup = names.duplicated(keep=False)
    names[dup] = names[dup] + " (" + names.index[dup].astype(str) + ")"
    return names.sort_values().to_dict()
