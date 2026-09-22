"""
Reconcile the dashboard against raw BigQuery.

    python check_numbers.py                 # month to date
    python check_numbers.py 2026-09-01 2026-09-17

For a date window it prints, per channel, what the raw tables hold and what the dashboard shows,
plus the checks that usually explain a mismatch: duplicate rows, channel names that don't line up
between tables, rows the weekly table overlaps, zeros that should be NULL, and category splits.
Nothing here is cached and nothing is estimated unless the column says so.
"""
from __future__ import annotations

import datetime as dt
import re
import sys

import pandas as pd

import bigquery as B
import config
import metrics as M


def _fmt(df: pd.DataFrame) -> str:
    return df.to_string(index=False, na_rep="—", float_format=lambda v: f"{v:,.0f}")


EXCLUDED = sorted({re.sub(r"[^a-z]", "", c.lower()) for c in config.EXCLUDED_CATEGORIES})


def _raw(sql: str, start=None, end=None) -> pd.DataFrame:
    params = {"excluded": ("STRING", EXCLUDED)}
    if start is not None:
        params.update({"start": ("DATE", start), "end": ("DATE", end)})
    return B._run(sql, params)


def _keep(col: str) -> str:
    """SQL filter that drops the freebie categories, like the dashboard does."""
    if not col:
        return "TRUE"
    return f"({col} IS NULL OR LOWER(REGEXP_REPLACE({col}, r'[^A-Za-z]', '')) NOT IN UNNEST(@excluded))"


def main(start: dt.date, end: dt.date) -> None:
    c = config
    if c.DEMO_MODE or not c.bq_configured():
        print("DEMO MODE: BigQuery is not configured, so there is nothing to reconcile.")
        return
    print(f"Project {c.GCP_PROJECT}.{c.BQ_DATASET}   window {start} to {end}\n")
    B.apply_schema()

    # ---- 1. raw totals straight from the sales master -------------------------------------
    raw = _raw(f"""
        SELECT {c.COL_CHANNEL} AS channel,
               SUM({c.COL_MRP}) AS mrp_raw,
               SUM({c.COL_GROSS}) AS gross_raw,
               SUM({c.COL_QTY}) AS qty_raw,
               COUNT(*) AS rows,
               COUNT(DISTINCT {c.COL_DATE}) AS days,
               COUNTIF({c.COL_GROSS} IS NULL) AS gross_nulls,
               COUNTIF({c.COL_GROSS} = 0) AS gross_zeros,
               MAX({c.COL_DATE}) AS last_row
        FROM `{c.table_fqn()}`
        WHERE {c.COL_DATE} BETWEEN @start AND @end AND {_keep(c.COL_CATEGORY)}
        GROUP BY channel ORDER BY mrp_raw DESC
    """, start, end)

    # ---- 2. the same window as the dashboard computes it ----------------------------------
    data = B.load_dashboard_data()
    P = M.build_periods(end, data.channel_last_date)
    cd = M.add_lag(M.attach_targets(M.channel_daily(data.df, []), data.targets, [], []), P)
    win = cd[(cd["date"] >= pd.Timestamp(start)) & (cd["date"] <= pd.Timestamp(end))]
    dash = win.groupby("channel").agg(
        mrp_dash=("mrp_sales", lambda x: x.sum(min_count=1)),
        gross_dash=("gross_sales", lambda x: x.sum(min_count=1)),
        qty_dash=("quantity", lambda x: x.sum(min_count=1)),
        est_days=("est", "sum"),
    ).reset_index()

    cmp = raw.merge(dash, on="channel", how="outer")
    cmp["mrp_diff"] = cmp["mrp_dash"] - cmp["mrp_raw"]
    cmp["gross_added"] = cmp["gross_dash"] - cmp["gross_raw"].fillna(0)
    print("PER CHANNEL: raw sales master vs dashboard")
    print("  mrp_diff should be 0. gross_added is what the weekly table and estimates filled in.")
    print(_fmt(cmp[["channel", "mrp_raw", "mrp_dash", "mrp_diff", "gross_raw", "gross_dash",
                    "gross_added", "est_days", "qty_raw", "qty_dash", "rows", "days",
                    "gross_nulls", "gross_zeros", "last_row"]]))
    print(f"\nTOTAL   raw MRP {cmp['mrp_raw'].sum():,.0f}   dashboard MRP {cmp['mrp_dash'].sum():,.0f}"
          f"   raw gross {cmp['gross_raw'].sum():,.0f}   dashboard gross {cmp['gross_dash'].sum():,.0f}")

    # ---- 3. duplicate rows at the stated grain --------------------------------------------
    grain = f"{c.COL_DATE}, {c.COL_CHANNEL}" + (f", {c.COL_CATEGORY}" if c.COL_CATEGORY else "")
    dup = _raw(f"""
        SELECT COUNT(*) AS duplicate_groups, SUM(n - 1) AS extra_rows FROM (
          SELECT {grain}, COUNT(*) AS n FROM `{c.table_fqn()}`
          WHERE {c.COL_DATE} BETWEEN @start AND @end GROUP BY {grain} HAVING COUNT(*) > 1)
    """, start, end)
    print(f"\nDUPLICATES in the sales master at ({grain}): "
          f"{int(dup['duplicate_groups'][0] or 0)} groups, {int(dup['extra_rows'][0] or 0)} extra rows")
    print("  Anything above 0 means the dashboard is summing the same day more than once.")

    # ---- 4. channel names across the tables -----------------------------------------------
    names = {"sales": set(raw["channel"].dropna())}
    if c.BQ_WEEKLY_TABLE:
        names["weekly"] = set(_raw(f"SELECT DISTINCT {c.W_COL_CHANNEL} AS channel FROM "
                                   f"`{c.fqn(c.BQ_WEEKLY_TABLE)}` WHERE {c.W_COL_DATE} BETWEEN @start AND @end",
                                   start, end)["channel"].dropna())
    if c.BQ_TARGET_TABLE:
        names["AOP"] = set(_raw(f"SELECT DISTINCT {c.T_COL_CHANNEL} AS channel FROM "
                                f"`{c.fqn(c.BQ_TARGET_TABLE)}` WHERE DATE({c.T_COL_DATE}) BETWEEN @start AND @end",
                                start, end)["channel"].dropna())
    if c.BQ_AD_TABLE:
        names["spends"] = set(_raw(f"SELECT DISTINCT {c.AD_COL_CHANNEL} AS channel FROM "
                                   f"`{c.fqn(c.BQ_AD_TABLE)}` WHERE {c.AD_COL_DATE} BETWEEN @start AND @end",
                                   start, end)["channel"].dropna()) if c.AD_COL_CHANNEL else set()
    print("\nCHANNEL NAMES")
    for label, values in names.items():
        print(f"  {label:7} {sorted(values)}")
    unknown = names["sales"] - set(config.CHANNELS)
    if unknown:
        print(f"  !! in the sales table but not in config.CHANNELS: {sorted(unknown)}")
    for label in ("weekly", "AOP", "spends"):
        if label in names and names[label]:
            odd = names[label] - names["sales"]
            if odd:
                print(f"  !! in {label} but not in the sales table: {sorted(odd)} "
                      "-> add these to CHANNEL_ALIASES in config.py")

    # ---- 5. AOP targets --------------------------------------------------------------------
    if c.BQ_TARGET_TABLE:
        tg = _raw(f"""
            SELECT {c.T_COL_CHANNEL} AS channel, SUM({c.T_COL_TARGET}) AS target_raw,
                   COUNT(*) AS rows, COUNT(DISTINCT DATE({c.T_COL_DATE})) AS days
            FROM `{c.fqn(c.BQ_TARGET_TABLE)}`
            WHERE DATE({c.T_COL_DATE}) BETWEEN @start AND @end
            GROUP BY channel ORDER BY target_raw DESC
        """, start, end)
        dash_t = win[win["target_sales"].notna()].groupby("channel")["target_sales"].sum().reset_index(
            name="target_dash") if "target_sales" in win else pd.DataFrame(columns=["channel", "target_dash"])
        print("\nAOP TARGETS: raw vs dashboard")
        print(_fmt(tg.merge(dash_t, on="channel", how="outer")))

    # ---- 6. freebie categories excluded ----------------------------------------------------
    if c.COL_CATEGORY:
        fb = _raw(f"""
            SELECT {c.COL_CATEGORY} AS category, SUM({c.COL_MRP}) AS mrp, SUM({c.COL_QTY}) AS qty
            FROM `{c.table_fqn()}`
            WHERE {c.COL_DATE} BETWEEN @start AND @end AND NOT {_keep(c.COL_CATEGORY)}
            GROUP BY category ORDER BY mrp DESC
        """, start, end)
        print("\nEXCLUDED freebie categories in this window (not counted anywhere):")
        print(_fmt(fb) if len(fb) else "  none")

    # ---- 7. AOP plan: year totals straight from the table vs the dashboard ----------------
    if c.BQ_AOP_TABLE:
        fy_raw = _raw(f"""
            SELECT CAST({c.A_COL_FY} AS STRING) AS financial_year, SUM({c.A_COL_REVENUE}) AS revenue_sql,
                   COUNT(DISTINCT {c.A_COL_MONTH}) AS months, COUNT(DISTINCT {c.A_COL_CHANNEL}) AS channels
            FROM `{c.fqn(c.BQ_AOP_TABLE)}` GROUP BY financial_year ORDER BY financial_year
        """)
        fy_raw["fy_start"] = [B.fy_start_year(f) for f in fy_raw["financial_year"]]
        dash_fy = data.aop.groupby("fy_start")["aop"].sum().rename("revenue_dashboard").reset_index() \
            if data.aop is not None else pd.DataFrame(columns=["fy_start", "revenue_dashboard"])
        fy = fy_raw.merge(dash_fy, on="fy_start", how="left")
        fy["diff"] = fy["revenue_dashboard"] - fy["revenue_sql"]
        print("\nAOP BY FINANCIAL YEAR: SUM(Revenue) vs dashboard  (diff should be 0)")
        print(_fmt(fy[["financial_year", "revenue_sql", "revenue_dashboard", "diff", "months", "channels"]]))
        months = _raw(f"SELECT DISTINCT CAST({c.A_COL_MONTH} AS STRING) AS month FROM `{c.fqn(c.BQ_AOP_TABLE)}`")
        bad = [m for m in months["month"] if pd.isna(B.parse_aop_month("2026-27", m))]
        print(f"  Month labels seen: {sorted(months['month'].astype(str))[:14]}")
        if bad:
            print(f"  !! months the dashboard can't read (their revenue is left out): {bad}")
        aop_channels = set(_raw(f"SELECT DISTINCT {c.A_COL_CHANNEL} AS channel FROM `{c.fqn(c.BQ_AOP_TABLE)}`")["channel"].dropna())
        odd = aop_channels - set(raw["channel"].dropna())
        if odd:
            print(f"  !! AOP channels with no sales under that name: {sorted(odd)} -> add to CHANNEL_ALIASES")

    print("\nIf mrp_diff is 0 and the channel names line up, the dashboard matches the source. "
          "Differences in gross are the weekly table and the estimate rules (est_days).")


if __name__ == "__main__":
    args = sys.argv[1:]
    if len(args) == 2:
        s, e = (dt.date.fromisoformat(a) for a in args)
    else:
        today = dt.date.today()
        s, e = today.replace(day=1), today - dt.timedelta(days=1)
    main(s, e)
