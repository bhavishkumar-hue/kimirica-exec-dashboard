"""
Synthetic data shaped exactly like the three query outputs (sales, weekly gross, ad spends).
Used only when DEMO_MODE is on or BigQuery is not configured.

Demo quirks that exercise the business rules:
  * Amazon-VC arrives one day after the other channels.
  * Weekly channels have no gross in the sales table; the weekly table holds it up to the
    last Sunday (Myntra is a week further behind, so it shows as overdue).
"""
from __future__ import annotations

import calendar
import datetime as dt

import numpy as np
import pandas as pd
import streamlit as st

import config

# channel: (avg daily gross ₹, yearly growth, has_target)
_PROFILE = {
    "Amazon-SC": (310_000, 0.22, True),
    "Amazon-VC": (180_000, 0.10, True),
    "Amazon-UAE": (22_000, 0.35, False),
    "Blinkit": (140_000, 0.85, True),
    "EBO(Stores)": (120_000, 0.08, True),
    "FK-Minutes": (26_000, 1.40, False),
    "Flipkart": (95_000, 0.05, True),
    "Myntra": (48_000, -0.05, True),
    "Nykaa": (82_000, 0.12, True),
    "Swiggy": (60_000, 0.70, True),
    "Tira": (18_000, 0.30, False),
    "Website": (230_000, 0.15, True),
    "Zepto": (105_000, 0.95, True),
}
_CATEGORIES = {"Bath & Body": 0.38, "Hair Care": 0.20, "Skin Care": 0.18, "Fragrance": 0.12, "Gift Sets": 0.12}
_ASP = {"Bath & Body": 520, "Hair Care": 610, "Skin Care": 740, "Fragrance": 890, "Gift Sets": 1650}


_AD_RATE = {"Amazon-SC": 0.12, "Amazon-VC": 0.06, "Flipkart": 0.10, "Blinkit": 0.09, "Zepto": 0.09,
            "Swiggy": 0.08, "Myntra": 0.11, "Nykaa": 0.10, "Website": 0.16, "FK-Minutes": 0.07}


@st.cache_data(show_spinner=False)
def generate_demo_frame(today: dt.date):
    rng = np.random.default_rng(7)
    max_date = today - dt.timedelta(days=1)
    start = max_date - dt.timedelta(days=760)
    fy = config.year_start(max_date)
    month_end = fy.replace(year=fy.year + 1) - dt.timedelta(days=1)  # plan runs to the FY end
    dates = pd.date_range(start, month_end, freq="D")
    n = len(dates)

    last_dates = {ch: max_date for ch in _PROFILE}
    for ch, lag in config.EXPECTED_LAG_DAYS.items():
        if ch in last_dates:
            last_dates[ch] = max_date - dt.timedelta(days=lag)
    last_sunday = max_date - dt.timedelta(days=(max_date.weekday() + 1) % 7 or 7)
    weekly_last = {ch: last_sunday for ch in config.WEEKLY_GROSS_CHANNELS}
    weekly_last["Myntra"] = last_sunday - dt.timedelta(days=7)

    t = np.arange(n) / 365.0
    dow = dates.dayofweek.to_numpy()
    weekly = np.where(dow >= 5, 1.12, 1.0)
    month_day = dates.day.to_numpy()
    payday = np.where(month_day <= 5, 1.10, 1.0)
    festive = 1 + 0.45 * np.exp(-(((dates.dayofyear.to_numpy() - 300) / 18.0) ** 2))

    frames = []
    for ch, (base, growth, has_target) in _PROFILE.items():
        level = base * (1 + growth) ** (t - t[-1]) * weekly * payday * festive
        if ch in config.QUICK_COMMERCE:
            level = level * np.where(dow >= 5, 1.10, 1.0)
        noise = rng.normal(1, 0.12, n).clip(0.5, 1.6)
        daily = level * noise
        # a sharp one-day drop on the latest date for one channel (watchlist demo)
        if ch == "Myntra":
            daily[dates.date == max_date] *= 0.45

        is_future = dates.date > last_dates[ch]
        target_daily = base * 1.34 * 1.08 * weekly * payday if has_target else None  # AOP on MRP

        for cat, share in _CATEGORIES.items():
            gross = daily * share * rng.normal(1, 0.06, n).clip(0.7, 1.3)
            qty = np.round(gross / (_ASP[cat] * rng.normal(1, 0.04, n)))
            mrp = gross * rng.normal(1.34, 0.03, n) + qty * 6  # includes freebies
            frame = pd.DataFrame({
                "date": dates,
                "channel": ch,
                "category": cat,
                "mrp_sales": np.where(is_future, np.nan, mrp.round(2)),
                "gross_sales": np.where(is_future, np.nan, gross.round(2)),
                "quantity": np.where(is_future, np.nan, qty),
            })
            if ch in config.ORDER_CHANNELS:
                items_per_order = 1.7 if ch == "Website" else 1.4
                frame["orders"] = np.where(is_future, np.nan, np.round(qty / items_per_order))
            else:
                frame["orders"] = np.nan
            frame["target_sales"] = (np.where(dates.date >= start + dt.timedelta(days=120),
                                              (target_daily * share).round(2), np.nan)
                                     if has_target else np.nan)
            frames.append(frame)

    df = pd.concat(frames, ignore_index=True)
    # freebie rows, as they appear in the real table; the loader must drop them everywhere
    fb = df[df["category"] == "Bath & Body"].copy()
    for cat, scale in (("Freebie", 0.04), ("Consumables", 0.02), ("Primary", 0.01), ("Uncategorised", 0.01)):
        part = fb.assign(category=cat, mrp_sales=fb["mrp_sales"] * scale, gross_sales=0.0,
                         quantity=(fb["quantity"] * scale * 3).round())
        frames.append(part)
    df = pd.concat(frames, ignore_index=True)
    # future dates only matter where a target exists
    df = df.reset_index(drop=True)

    # weekly channels: gross lives in the weekly table, only up to their last refresh
    wk = df["channel"].isin(config.WEEKLY_GROSS_CHANNELS) & df["gross_sales"].notna()
    weekly = df.loc[wk, ["date", "channel", "category", "gross_sales"]].copy()
    cutoff = pd.to_datetime(weekly["channel"].map(weekly_last))
    weekly = weekly[weekly["date"] <= cutoff]
    df.loc[df["channel"].isin(config.WEEKLY_GROSS_CHANNELS), "gross_sales"] = np.nan

    # AOP: daily target vs achieved (date x channel) plus a monthly plan (FY, month label, channel)
    targets = df.groupby(["date", "channel"], as_index=False).agg(
        target_sales=("target_sales", lambda x: x.sum(min_count=1)),
        achieved_sales=("mrp_sales", lambda x: x.sum(min_count=1)),
    )
    targets = targets[targets["target_sales"].notna()]
    plan = targets.assign(m=targets["date"].dt.to_period("M").dt.to_timestamp())
    plan = plan.groupby(["m", "channel"], as_index=False)["target_sales"].sum()
    fy_start = np.where(plan["m"].dt.month >= config.YEAR_START_MONTH, plan["m"].dt.year, plan["m"].dt.year - 1)
    aop = pd.DataFrame({
        "fy": [f"{y}-{(y + 1) % 100:02d}" for y in fy_start],
        "month": plan["m"].dt.strftime("%b"),
        "channel": plan["channel"],
        "aop": plan["target_sales"].round(0),
    })
    df = df.drop(columns=["target_sales"])

    # ad spends: date x channel, a share of gross sales
    daily = (pd.concat(frames).groupby(["date", "channel"])["gross_sales"].sum(min_count=1)
             .dropna().reset_index())
    daily = daily[daily["channel"].isin(_AD_RATE)]
    ads = daily.assign(ad_spend=(daily["gross_sales"] * daily["channel"].map(_AD_RATE)
                                 * rng.normal(1, 0.15, len(daily))).round(0))[["date", "channel", "ad_spend"]]
    return df, weekly, ads, targets, aop, last_dates
