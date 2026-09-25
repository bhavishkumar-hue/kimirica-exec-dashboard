"""
Daily data-health check. Looks for the exact classes of problem found by hand in this project so
far (gross exceeding MRP, a channel's feed going quiet, category tagging breaking down, duplicate
rows, AOP channel names that don't match sales) and emails a summary if it finds any. Silent when
everything's clean -- this is meant to interrupt you only when something needs attention.

Run manually:
    python check_alerts.py

Meant to run on a schedule via .github/workflows/data_alerts.yml (see that file for the GitHub
Secrets it needs: GCP_SA_KEY, GCP_PROJECT, BQ_DATASET, SMTP_USER, SMTP_PASS, ALERT_TO).
"""
from __future__ import annotations

import datetime as dt
import os
import smtplib
from email.mime.text import MIMEText

import pandas as pd

import bigquery as B
import config as c

STALE_DAYS = 3        # a channel with no MRP for this many days is worth a look
CATEGORY_GAP_PCT = 0.10  # flag if more than this share of this month's MRP has no category


def _raw(sql: str, params: dict | None = None) -> pd.DataFrame:
    return B._run(sql, params or {})


def check_gross_exceeds_mrp(today: dt.date) -> list[str]:
    df = _raw(f"""
        SELECT {c.COL_CHANNEL} AS channel, MAX({c.COL_DATE}) AS last_bad, COUNT(*) AS n
        FROM `{c.table_fqn()}`
        WHERE {c.COL_GROSS} > {c.COL_MRP}
        GROUP BY channel ORDER BY n DESC
    """)
    if df.empty:
        return []
    recent = df[pd.to_datetime(df["last_bad"]).dt.date >= today - dt.timedelta(days=STALE_DAYS)]
    if recent.empty:
        return []
    lines = [f"- {r.channel}: {r.n} rows with gross > MRP, most recently {r.last_bad}" for r in recent.itertuples()]
    return ["Gross sales exceeding MRP (should never happen -- discount can't be negative):"] + lines


def check_stale_channels(today: dt.date) -> list[str]:
    df = _raw(f"""
        SELECT {c.COL_CHANNEL} AS channel, MAX(IF({c.COL_MRP} IS NOT NULL, {c.COL_DATE}, NULL)) AS last_date
        FROM `{c.table_fqn()}`
        GROUP BY channel HAVING last_date IS NOT NULL
    """)
    if df.empty:
        return []
    df["gap_days"] = df["last_date"].apply(lambda d: (today - d).days)
    stale = df[df["gap_days"] > STALE_DAYS].sort_values("gap_days", ascending=False)
    if stale.empty:
        return []
    lines = [f"- {r.channel}: no MRP sales since {r.last_date} ({r.gap_days} days ago)" for r in stale.itertuples()]
    return ["Channels with no recent data (feed may have gone quiet):"] + lines


def check_missing_days() -> list[str]:
    """
    A day missing entirely within a channel's own recent window, even though the channel is
    otherwise loading right up to it -- different from check_stale_channels, which only catches
    the whole tail going quiet. Checked over each channel's own last 30 loaded days, not the
    calendar's, since channels like Amazon-VC normally lag a day or two.
    """
    df = _raw(f"""
        SELECT {c.COL_CHANNEL} AS channel, {c.COL_DATE} AS d
        FROM `{c.table_fqn()}` WHERE {c.COL_MRP} IS NOT NULL
        GROUP BY channel, d
    """)
    if df.empty:
        return []
    df["d"] = pd.to_datetime(df["d"]).dt.date
    lines = []
    for ch, g in df.groupby("channel"):
        last, first = g["d"].max(), g["d"].min()
        window_start = max(first, last - dt.timedelta(days=29))
        expected = pd.date_range(window_start, last, freq="D").date
        present = set(g["d"])
        missing = sorted(d for d in expected if d not in present)
        if missing:
            shown = ", ".join(str(d) for d in missing[:8]) + (f" (+{len(missing) - 8} more)" if len(missing) > 8 else "")
            lines.append(f"- {ch}: missing {len(missing)} day(s) in its own last 30 loaded days: {shown}")
    if not lines:
        return []
    return ["Days missing entirely inside a channel's own recent, otherwise-active window "
           "(a gap, not just the tail going stale):"] + lines


def check_category_gap(today: dt.date) -> list[str]:
    month_start = today.replace(day=1)
    df = _raw(f"""
        SELECT {c.COL_CHANNEL} AS channel,
               SUM(IF({c.COL_CATEGORY} IS NULL OR LOWER({c.COL_CATEGORY}) = 'unmapped', {c.COL_MRP}, 0)) AS no_cat,
               SUM({c.COL_MRP}) AS total
        FROM `{c.table_fqn()}`
        WHERE {c.COL_DATE} BETWEEN @start AND @end
        GROUP BY channel
    """, {"start": ("DATE", month_start), "end": ("DATE", today)})
    if df.empty:
        return []
    df = df[df["total"] > 0]
    df["gap"] = df["no_cat"] / df["total"]
    bad = df[df["gap"] > CATEGORY_GAP_PCT].sort_values("gap", ascending=False)
    if bad.empty:
        return []
    lines = [f"- {r.channel}: {r.gap:.0%} of this month's MRP has no category (₹{r.no_cat:,.0f} of ₹{r.total:,.0f})"
            for r in bad.itertuples()]
    return [f"Category tagging gaps this month (>{CATEGORY_GAP_PCT:.0%} untagged):"] + lines


def check_duplicates(today: dt.date) -> list[str]:
    month_start = today.replace(day=1)
    grain = f"{c.COL_DATE}, {c.COL_CHANNEL}" + (f", {c.COL_CATEGORY}" if c.COL_CATEGORY else "")
    df = _raw(f"""
        SELECT COUNT(*) AS n_groups, SUM(n - 1) AS extra FROM (
          SELECT {grain}, COUNT(*) AS n FROM `{c.table_fqn()}`
          WHERE {c.COL_DATE} BETWEEN @start AND @end GROUP BY {grain} HAVING COUNT(*) > 1)
    """, {"start": ("DATE", month_start), "end": ("DATE", today)})
    n_groups = int(df["n_groups"].iloc[0] or 0) if len(df) else 0
    if n_groups == 0:
        return []
    extra = int(df["extra"].iloc[0] or 0)
    return [f"Duplicate rows this month at ({grain}): {n_groups} groups, {extra} extra rows -- "
            "the dashboard may be double-counting some days."]


def check_aop_channel_names() -> list[str]:
    if not c.BQ_AOP_TABLE:
        return []
    sales = set(_raw(f"SELECT DISTINCT {c.COL_CHANNEL} AS channel FROM `{c.table_fqn()}`")["channel"].dropna())
    aop = set(_raw(f"SELECT DISTINCT {c.A_COL_CHANNEL} AS channel "
                   f"FROM `{c.fqn(c.BQ_AOP_TABLE)}`")["channel"].dropna())
    odd = {a for a in aop if a not in sales and B.canonical_channel(str(a).strip()) not in sales}
    if not odd:
        return []
    return [f"AOP_targets has channel names with no matching sales channel (check CHANNEL_ALIASES): {sorted(odd)}"]


def send_email(subject: str, body: str) -> None:
    to_addr = os.environ["ALERT_TO"]
    user, pw = os.environ["SMTP_USER"], os.environ["SMTP_PASS"]
    host, port = os.environ.get("SMTP_HOST", "smtp.gmail.com"), int(os.environ.get("SMTP_PORT", 587))
    msg = MIMEText(body)
    msg["Subject"], msg["From"], msg["To"] = subject, user, to_addr
    with smtplib.SMTP(host, port) as s:
        s.starttls()
        s.login(user, pw)
        s.send_message(msg)


def main() -> None:
    if c.DEMO_MODE or not c.bq_configured():
        print("DEMO MODE / not configured: nothing to check.")
        return
    today = dt.datetime.now(B.IST).date()
    sections: list[str] = []
    for check in (check_gross_exceeds_mrp, check_stale_channels, check_missing_days, check_category_gap,
                 check_duplicates, check_aop_channel_names):
        try:
            result = check(today) if check.__code__.co_argcount else check()
        except Exception as exc:
            sections.append(f"[{check.__name__} itself failed: {exc}]")
            continue
        if result:
            sections.append("\n".join(result))

    if not sections:
        print(f"{today}: no anomalies found.")
        return

    body = f"Kimirica dashboard data check -- {today}\n\n" + "\n\n".join(sections)
    print(body)
    send_email(f"Kimirica data alert -- {today}", body)
    print("\nEmail sent.")


if __name__ == "__main__":
    main()
