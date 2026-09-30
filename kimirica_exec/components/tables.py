"""
Tables. A pandas Styler controls display (₹ L/Cr, %, markers, subtle colour) while the underlying
numbers stay numeric, so st.dataframe's native column-header sort stays correct.

The Total row is a SECOND st.dataframe, not a row inside the sortable one above it. Two reasons:
  1. st.dataframe's interactive column-header sort is a client-side grid feature with no way to
     exclude one row from it -- a Total row living inside the grid would itself get sorted into
     the middle of the table.
  2. st.dataframe renders its grid onto an HTML canvas, not real per-column DOM cells, and its
     column widths come from an internal, unexposed auto-sizing algorithm. That was confirmed by
     measuring the live page: the grid's own header elements report a zero-size bounding box, so
     there's no width to read and match. An external HTML row (a flexbox strip, tried first) can
     only ever guess those widths and will drift out of alignment at other screen widths -- the
     only way to *guarantee* identical column widths is to render the total with the exact same
     component and the exact same column_config, since that's what makes the layout deterministic.
   The unavoidable cost is a second, repeated header row.

Markers: * = AOV uses ASP (channel has no orders), † = includes estimated gross.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

import config
import metrics as M
from components import theme as T

MONEY = ["MRP sales", "Gross sales", "Net sales", "Target"]
PRICES = ["AOV", "ASP"]


def _growth_style(v) -> str:
    if M.is_na(v):
        return ""
    if v >= 0.0005:
        return f"color: {T.POS}"
    if v <= -0.0005:
        return f"color: {T.NEG}"
    return f"color: {T.MUTED}"


def _ach_style_for(expected: float):
    """Colour achievement against where it should be by now (share of the month elapsed)."""
    def style(v) -> str:
        if M.is_na(v):
            return ""
        if v >= expected:
            return f"color: {T.POS}; font-weight: 600"
        if v >= config.TARGET_LAG_THRESHOLD * expected:
            return f"color: {T.WARN}; font-weight: 600"
        return f"color: {T.NEG}; font-weight: 600"
    return style


def _pct(signed: bool):
    return lambda v: M.fmt_pct(v, signed=signed)


def _styler(df: pd.DataFrame, raw: bool, pct_cols: dict[str, bool], expected: float = 1.0):
    money_fmt = M.fmt_inr_full if raw else M.fmt_inr
    fmt = {c: money_fmt for c in MONEY if c in df}
    fmt.update({c: M.fmt_price for c in PRICES if c in df})
    fmt.update({c: _pct(s) for c, s in pct_cols.items() if c in df})
    sty = df.style.format(fmt, na_rep="—")
    if "MoM" in df:
        sty = sty.map(_growth_style, subset=["MoM"])
    if "Ach." in df:
        sty = sty.map(_ach_style_for(expected), subset=["Ach."])
    return sty.set_properties(subset=[df.columns[0]], **{"font-weight": "600", "color": T.INK})


def _help(cmp_short: str) -> dict:
    basis = M.METRIC_LABELS[config.GROWTH_METRIC]
    return {
        "MRP sales": "MTD sales at MRP, including freebies",
        "Gross sales": "MTD gross sales, excluding freebies",
        "Net sales": f"Gross sales less {config.GST_RATE * 100:.0f}% GST",
        "Discount": "1 − gross sales ÷ MRP sales",
        "AOV": "Gross sales ÷ orders, or ASP where orders aren't tracked",
        "ASP": "Gross sales ÷ units",
        "MoM": f"{basis} vs {cmp_short}",
        "Target": "AOP for the months in the selected period",
        "Ach.": "Achieved so far ÷ AOP. Green when on pace for the time elapsed",
        "Share": f"Share of MTD {M.metric_lc(config.GROWTH_METRIC)} in this view",
    }


def _col_width(col: str, raw: bool) -> int:
    """
    An EXPLICIT pixel width for every column -- width=None (the default) sizes a column to fit
    that dataframe's own cell contents, which is exactly why the Total row (a second, separate
    st.dataframe -- see the module docstring) could still drift out of alignment with the main
    table even with an identical column_config: different data, different auto-sized width. An
    explicit width is content-independent by definition, so the same number here always renders
    the same regardless of which rows are in that particular dataframe.
    """
    if col in MONEY:
        return 150 if raw else 105
    if col in PRICES:
        return 90
    return 110  # Discount, MoM/Growth, Target-Ach./Share -- percent-ish or short figures


def _col_config(df: pd.DataFrame, first_label: str, cmp_short: str, raw: bool) -> dict:
    helps = _help(cmp_short)
    basis = M.METRIC_LABELS[config.GROWTH_METRIC].split()[0]
    cfg = {df.columns[0]: st.column_config.Column(first_label, width=200, pinned=True)}
    for c in df.columns[1:]:
        # cmp_short names the actual comparison ("LMTD", "LY", "Comparison period", ...) so the
        # header itself says what growth is measured against, not just "Growth (MRP)".
        label = {"MoM": f"Growth ({basis}) vs {cmp_short}", "Target": "AOP", "Ach.": "AOP ach."}.get(c, c)
        cfg[c] = st.column_config.Column(label, help=helps.get(c), width=_col_width(c, raw))
    return cfg


def _table_with_total(df: pd.DataFrame, sty, total_df: pd.DataFrame, raw: bool,
                      pct_cols: dict[str, bool], expected: float, height: int,
                      col_config: dict, key: str) -> None:
    # gap="xxsmall": theme.py forces gap:4px !important on these specific wrapper containers (a
    # broader panel_* rule was overriding whatever gap= said here -- see the comment there), so the
    # second dataframe sits right against the first with no visible page-section-sized gap.
    total_sty = _styler(total_df, raw, pct_cols, expected).set_properties(**{"font-weight": "700"})
    with st.container(key=f"{key}_wrap", gap="xxsmall"):
        st.dataframe(sty, hide_index=True, width="stretch", placeholder="—",
                    height=height, column_config=col_config, key=key)
        st.dataframe(total_sty, hide_index=True, width="stretch", placeholder="—",
                    height=38 + 35, column_config=col_config, key=f"{key}_total")


def channel_table(tbl: pd.DataFrame, key_col: str, raw: bool, cmp_short: str, expected: float = 1.0) -> None:
    label = "Channel" if key_col == "channel" else "Channel group"
    cols = [key_col, "MRP sales", "Gross sales", "Net sales", "Discount", "AOV", "ASP", "MoM", "Target", "Ach."]
    if tbl["Target"].isna().all():
        cols = [c for c in cols if c not in ("Target", "Ach.")]
    df = tbl[cols].reset_index(drop=True)
    pct_cols = {"Discount": False, "MoM": True, "Ach.": False}
    sty = _styler(df, raw, pct_cols, expected)
    total_df = M.add_totals_row(tbl, key_col)[cols].iloc[[-1]].reset_index(drop=True)
    # No min(..., cap): a capped height shorter than the content forces an internal vertical
    # scrollbar in the main grid but never in the one-row Total grid, which eats a few pixels of
    # width from the main grid's columns only and throws off the alignment this whole design
    # exists to guarantee. Exact-fit height means neither grid ever needs to scroll.
    _table_with_total(df, sty, total_df, raw, pct_cols, expected, 38 + 35 * len(df),
                      _col_config(df, label, cmp_short, raw), f"tbl_{key_col}_{raw}")


def category_table(ct: pd.DataFrame, raw: bool, cmp_short: str) -> None:
    # No AOV here: an order spans categories, so a per-category order count (and the AOV built on
    # it) is not a real number. ASP (gross / units) is fine at category grain and stays.
    cols = ["Category", "MRP sales", "Gross sales", "Net sales", "Discount", "ASP", "MoM", "Share"]
    df = ct[cols].reset_index(drop=True)
    pct_cols = {"Discount": False, "MoM": True, "Share": False}
    sty = _styler(df, raw, pct_cols)
    total_df = M.add_totals_row(ct, "Category")[cols].iloc[[-1]].reset_index(drop=True)
    _table_with_total(df, sty, total_df, raw, pct_cols, 1.0, 38 + 35 * len(df),
                      _col_config(df, "Category", cmp_short, raw), f"cat_{raw}")
