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

import numpy as np
import pandas as pd
import streamlit as st

import config
import metrics as M
from components import theme as T

MONEY = ["MRP sales", "Gross sales", "Net sales", "Target", "Ad spend"]
PRICES = ["AOV", "ASP"]
ROW_HEIGHT = 30  # explicit row_height= so a long channel list fits without a page-length table
HEADER_HEIGHT = 36  # the grid's own header overlay height -- fixed regardless of ROW_HEIGHT (measured
                    # live); see theme.py's clip-window comment for why this exact number matters


NEW = "New"   # growth cell for a product with nothing in the comparison period (MoM = +inf)


def _is_new(v) -> bool:
    return not M.is_na(v) and np.isinf(v)


def _growth_style(v) -> str:
    if M.is_na(v):
        return ""
    if _is_new(v):
        return f"color: {T.ACCENT}; font-weight: 600"
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
    return lambda v: NEW if _is_new(v) else M.fmt_pct(v, signed=signed)


def _formatters(df: pd.DataFrame, raw: bool, pct_cols: dict[str, bool]) -> dict:
    money_fmt = M.fmt_inr_full if raw else M.fmt_inr
    fmt = {c: money_fmt for c in MONEY if c in df}
    fmt.update({c: M.fmt_price for c in PRICES if c in df})
    fmt.update({c: _pct(s) for c, s in pct_cols.items() if c in df})
    if "ROAS" in df:
        fmt["ROAS"] = M.fmt_x
    if "Units" in df:
        fmt["Units"] = M.fmt_count_full if raw else M.fmt_count
    return fmt


def _styler(df: pd.DataFrame, raw: bool, pct_cols: dict[str, bool], expected: float = 1.0):
    sty = df.style.format(_formatters(df, raw, pct_cols), na_rep="—")
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
        "Ad spend": "Ad spend for the selected period",
        "ROAS": "Gross sales ÷ ad spend, over the dates ad spend covers",
        "Units": "Units sold",
        "MoM": f"{basis} growth vs {cmp_short}",
        "Target": "AOP for the days passed so far (each month pro-rated by days elapsed)",
        "Ach.": "Achieved ÷ AOP to date, over the same days. Green at 100% or more",
        "Share": f"Share of MTD {M.metric_lc(config.GROWTH_METRIC)} in this view",
    }


# Approximate rendered character widths for the grid's canvas font, measured off screenshots.
_VALUE_CH, _HEADER_CH, _BOLD_CH = 7.2, 6.6, 7.3
_CELL_PAD, _HEADER_PAD, _MIN_WIDTH = 22, 30, 60


def _col_widths(df: pd.DataFrame, total_df: pd.DataFrame, labels: dict, raw: bool,
                pct_cols: dict[str, bool]) -> dict:
    """
    Every column gets just enough width for its own header and its widest value (Total row
    included), then st.dataframe's width="stretch" spreads any spare room across them. Fixed
    widths were sized for the widest case, so on a 1280-1366px laptop -- or with Full values on
    -- the channel table ran past the panel and scrolled sideways. Main and Total grids still get
    the same numbers from here, which is what keeps their columns aligned.
    """
    fmt = _formatters(df, raw, pct_cols)
    both = pd.concat([df, total_df], ignore_index=True)
    widths = {}
    for i, c in enumerate(df.columns):
        f = fmt.get(c, lambda v: "—" if M.is_na(v) else str(v))
        longest = max((len(f(v)) for v in both[c]), default=0)
        ch = _BOLD_CH if i == 0 else _VALUE_CH
        widths[c] = max(_MIN_WIDTH, round(longest * ch + _CELL_PAD),
                        round(len(labels[c]) * _HEADER_CH + _HEADER_PAD))
    return widths


def _labels(cols: list[str], first_label: str, cmp_short: str) -> dict:
    labels = {c: {"MoM": f"Growth vs {cmp_short}", "Target": "AOP to date", "Ach.": "AOP ach."}.get(c, c)
              for c in cols}
    labels[cols[0]] = first_label
    return labels


def _col_config(df: pd.DataFrame, total_df: pd.DataFrame, first_label: str, cmp_short: str,
                raw: bool, pct_cols: dict[str, bool]) -> dict:
    helps = _help(cmp_short)
    # cmp_short names the actual comparison ("LMTD", "LY", "Last month", ...) so the header says
    # what growth is measured against; the MRP basis lives in the tooltip to keep the header short.
    labels = _labels(list(df.columns), first_label, cmp_short)
    widths = _col_widths(df, total_df, labels, raw, pct_cols)
    cfg = {df.columns[0]: st.column_config.Column(first_label, width=widths[df.columns[0]], pinned=True)}
    for c in df.columns[1:]:
        cfg[c] = st.column_config.Column(labels[c], help=helps.get(c), width=widths[c])
    return cfg


def _fit_height(n_rows: int) -> int:
    # Exact fit, never capped: a cap forces a scrollbar in the main grid only, which steals width from
    # its columns and breaks alignment with the Total grid. The +2 covers the frame's own border --
    # without it the grid's content ran 1px taller than its viewport and could be scrolled.
    return HEADER_HEIGHT + ROW_HEIGHT * n_rows + 2


def _table_with_total(df: pd.DataFrame, sty, total_df: pd.DataFrame, raw: bool,
                      pct_cols: dict[str, bool], expected: float, height: int,
                      col_config: dict, key: str) -> None:
    # gap="xxsmall": theme.py forces gap:4px !important on these specific wrapper containers (a
    # broader panel_* rule was overriding whatever gap= said here -- see the comment there), so the
    # second dataframe sits right against the first with no visible page-section-sized gap.
    total_sty = _styler(total_df, raw, pct_cols, expected).set_properties(**{"font-weight": "700"})
    with st.container(key=f"{key}_wrap", gap="xxsmall"):
        st.dataframe(sty, hide_index=True, width="stretch", placeholder="—", row_height=ROW_HEIGHT,
                    height=height, column_config=col_config, key=key)
        # Same height rule as the main grid. Without the +2 border allowance the grid's content
        # overflowed by 2px, Streamlit treated it as scrolling and widened it by a scrollbar's width
        # (~10px where the browser shows real scrollbars), so every Total line drifted right.
        # A main grid that scrolls (the product table) still lines up with this one -- measured with
        # real scrollbars at 100% and 125%.
        st.dataframe(total_sty, hide_index=True, width="stretch", placeholder="—", row_height=ROW_HEIGHT,
                    height=_fit_height(1), column_config=col_config, key=f"{key}_total")


def channel_table(tbl: pd.DataFrame, key_col: str, raw: bool, cmp_short: str, expected: float = 1.0) -> None:
    label = "Channel" if key_col == "channel" else "Channel group"
    cols = _channel_cols(tbl, key_col)
    df = tbl[cols].reset_index(drop=True)
    pct_cols = {"Discount": False, "MoM": True, "Ach.": False}
    sty = _styler(df, raw, pct_cols, expected)
    total_df = M.add_totals_row(tbl, key_col)[cols].iloc[[-1]].reset_index(drop=True)
    _table_with_total(df, sty, total_df, raw, pct_cols, expected, _fit_height(len(df)),
                      _col_config(df, total_df, label, cmp_short, raw, pct_cols), f"tbl_{key_col}_{raw}")


PRODUCT_COLS = ["Product", "MRP sales", "Gross sales", "Net sales", "Discount", "Units", "ASP", "MoM", "Share"]
CATEGORY_COLS = ["Category", "MRP sales", "Gross sales", "Net sales", "Discount", "ASP", "MoM", "Share"]
SHARE_PCT = {"Discount": False, "MoM": True, "Share": False}


def product_table(pt: pd.DataFrame, raw: bool, cmp_short: str) -> None:
    """Category columns plus Units; every product, scrolling inside a fixed-height box."""
    df = pt[PRODUCT_COLS].reset_index(drop=True)
    sty = _styler(df, raw, SHARE_PCT)
    total_df = M.add_totals_row(pt, "Product")[PRODUCT_COLS].iloc[[-1]].reset_index(drop=True)
    rows = min(len(df), config.PRODUCT_VISIBLE_ROWS)
    _table_with_total(df, sty, total_df, raw, SHARE_PCT, 1.0, _fit_height(rows),
                      _col_config(df, total_df, "Product", cmp_short, raw, SHARE_PCT),
                      f"cat_prod_{raw}")


# --------------------------------------------------------------------------- #
# CSV export: the full table (every row, Total included), plain numbers for Excel
# --------------------------------------------------------------------------- #
def _csv(tbl: pd.DataFrame, label_col: str, first_label: str, cols: list[str], cmp_short: str,
         pct_cols: dict[str, bool]) -> bytes:
    full = M.add_totals_row(tbl, label_col)[cols]
    labels = _labels(cols, first_label, cmp_short)
    out = pd.DataFrame(index=full.index)
    for c in cols:
        v = full[c]
        if c in pct_cols:
            num = pd.to_numeric(v, errors="coerce")
            out[f"{labels[c]} (%)"] = np.where(np.isinf(num), NEW, (num * 100).round(1).astype(object))
            out[f"{labels[c]} (%)"] = out[f"{labels[c]} (%)"].where(num.notna(), None)
        elif c == "ROAS":
            out[labels[c]] = pd.to_numeric(v, errors="coerce").round(2)
        elif c in MONEY or c in PRICES or c == "Units":
            out[labels[c]] = pd.to_numeric(v, errors="coerce").round(0)
        else:
            out[labels[c]] = v
    return out.to_csv(index=False).encode("utf-8-sig")   # BOM so Excel opens it as UTF-8


def _channel_cols(tbl: pd.DataFrame, key_col: str) -> list[str]:
    cols = [key_col, "MRP sales", "Gross sales", "Net sales", "Discount", "AOV", "ASP",
            "Ad spend", "ROAS", "MoM", "Target", "Ach."]
    if tbl["Target"].isna().all():
        cols = [c for c in cols if c not in ("Target", "Ach.")]
    if tbl["Ad spend"].isna().all():
        cols = [c for c in cols if c not in ("Ad spend", "ROAS")]
    return cols


def channel_csv(tbl: pd.DataFrame, key_col: str, cmp_short: str) -> bytes:
    label = "Channel" if key_col == "channel" else "Channel group"
    return _csv(tbl, key_col, label, _channel_cols(tbl, key_col), cmp_short,
                {"Discount": False, "MoM": True, "Ach.": False})


def category_csv(ct: pd.DataFrame, cmp_short: str) -> bytes:
    return _csv(ct, "Category", "Category", CATEGORY_COLS, cmp_short, SHARE_PCT)


def product_csv(pt: pd.DataFrame, cmp_short: str) -> bytes:
    return _csv(pt, "Product", "Product", PRODUCT_COLS, cmp_short, SHARE_PCT)


def category_table(ct: pd.DataFrame, raw: bool, cmp_short: str) -> None:
    # No AOV here: an order spans categories, so a per-category order count (and the AOV built on
    # it) is not a real number. ASP (gross / units) is fine at category grain and stays.
    cols = ["Category", "MRP sales", "Gross sales", "Net sales", "Discount", "ASP", "MoM", "Share"]
    df = ct[cols].reset_index(drop=True)
    pct_cols = {"Discount": False, "MoM": True, "Share": False}
    sty = _styler(df, raw, pct_cols)
    total_df = M.add_totals_row(ct, "Category")[cols].iloc[[-1]].reset_index(drop=True)
    _table_with_total(df, sty, total_df, raw, pct_cols, 1.0, _fit_height(len(df)),
                      _col_config(df, total_df, "Category", cmp_short, raw, pct_cols), f"cat_{raw}")
