"""
Tables. A pandas Styler controls display (₹ L/Cr, %, markers, subtle colour) while the underlying
numbers stay numeric, so st.dataframe's native column-header sort stays correct. The Total row is
NOT a row inside that sortable grid -- st.dataframe's interactive sort is a client-side grid feature
with no way to exclude one row from it, so a Total row living inside the grid would itself get
sorted into the middle of the table. Instead it's a compact summary strip rendered right below.

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


def _help() -> dict:
    basis = M.METRIC_LABELS[config.GROWTH_METRIC]
    return {
        "MRP sales": "MTD sales at MRP, including freebies",
        "Gross sales": "MTD gross sales, excluding freebies",
        "Net sales": f"Gross sales less {config.GST_RATE * 100:.0f}% GST",
        "Discount": "1 − gross sales ÷ MRP sales",
        "AOV": "Gross sales ÷ orders, or ASP where orders aren't tracked",
        "ASP": "Gross sales ÷ units",
        "MoM": f"{basis} vs the comparison period",
        "Target": "AOP for the months in the selected period",
        "Ach.": "Achieved so far ÷ AOP. Green when on pace for the time elapsed",
        "Share": f"Share of MTD {M.metric_lc(config.GROWTH_METRIC)} in this view",
    }


def _col_config(df: pd.DataFrame, first_label: str) -> dict:
    helps = _help()
    basis = M.METRIC_LABELS[config.GROWTH_METRIC].split()[0]
    cfg = {df.columns[0]: st.column_config.Column(first_label, width="medium", pinned=True)}
    for c in df.columns[1:]:
        label = {"MoM": f"Growth ({basis})", "Target": "AOP", "Ach.": "AOP ach."}.get(c, c)
        cfg[c] = st.column_config.Column(label, help=helps.get(c))
    return cfg


def _fmt_total_value(col: str, v, raw: bool) -> str:
    if M.is_na(v):
        return "—"
    if col in MONEY:
        return M.fmt_inr_full(v) if raw else M.fmt_inr(v)
    if col in PRICES:
        return M.fmt_price(v)
    if col in ("Discount", "Ach.", "Share"):
        return M.fmt_pct(v, signed=False)
    if col == "MoM":
        return M.fmt_pct(v)
    return str(v)


def _total_strip(total_row, cols: list[str], raw: bool) -> None:
    """A slim summary bar directly under the table -- deliberately not another table, so it can
    never be reordered by the sortable grid above, and can't be mistaken for a repeated header."""
    cells = "".join(
        f'<div class="tbl-total-cell"><span>{T.esc(c)}</span>{T.esc(_fmt_total_value(c, total_row[c], raw))}</div>'
        for c in cols[1:]
    )
    st.markdown(
        f'<div class="tbl-total-strip"><div class="tbl-total-cell tbl-total-label-cell">'
        f'<span>&nbsp;</span>Total</div>{cells}</div>',
        unsafe_allow_html=True,
    )


def _table_with_total(df: pd.DataFrame, sty, cols: list[str], raw: bool, height: int,
                      col_config: dict, key: str, total_row) -> None:
    with st.container(key=f"{key}_wrap"):
        st.dataframe(sty, hide_index=True, width="stretch", placeholder="—",
                    height=height, column_config=col_config, key=key)
        _total_strip(total_row, cols, raw)


def channel_table(tbl: pd.DataFrame, key_col: str, raw: bool, expected: float = 1.0) -> None:
    label = "Channel" if key_col == "channel" else "Channel group"
    cols = [key_col, "MRP sales", "Gross sales", "Net sales", "Discount", "AOV", "ASP", "MoM", "Target", "Ach."]
    if tbl["Target"].isna().all():
        cols = [c for c in cols if c not in ("Target", "Ach.")]
    df = tbl[cols].reset_index(drop=True)
    sty = _styler(df, raw, {"Discount": False, "MoM": True, "Ach.": False}, expected)
    total_row = M.add_totals_row(tbl, key_col).iloc[-1]
    _table_with_total(df, sty, cols, raw, min(38 + 35 * len(df), 560), _col_config(df, label),
                      f"tbl_{key_col}_{raw}", total_row)


def category_table(ct: pd.DataFrame, raw: bool) -> None:
    # No AOV here: an order spans categories, so a per-category order count (and the AOV built on
    # it) is not a real number. ASP (gross / units) is fine at category grain and stays.
    cols = ["Category", "MRP sales", "Gross sales", "Net sales", "Discount", "ASP", "MoM", "Share"]
    df = ct[cols].reset_index(drop=True)
    sty = _styler(df, raw, {"Discount": False, "MoM": True, "Share": False})
    total_row = M.add_totals_row(ct, "Category").iloc[-1]
    _table_with_total(df, sty, cols, raw, min(38 + 35 * len(df), 460), _col_config(df, "Category"),
                      f"cat_{raw}", total_row)
