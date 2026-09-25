"""
Tables. Streamlit's st.dataframe grid has no way to keep one specific row pinned during an
interactive column-header sort (that sort is a client-side grid feature with no exclusion hook), so
these two tables are rendered as a plain HTML table with our own "Sort by" control instead: we sort
server-side and always re-append the Total row last, guaranteeing it never moves.

Markers: * = AOV uses ASP (channel has no orders), † = includes estimated gross.
"""
from __future__ import annotations

import html as _html

import pandas as pd
import streamlit as st

import config
import metrics as M
from components import theme as T

MONEY = ["MRP sales", "Gross sales", "Net sales", "Target"]
PRICES = ["AOV", "ASP"]
PERCENT = {"Discount": False, "MoM": True, "Ach.": False, "Share": False}


def _growth_style(v) -> str:
    if M.is_na(v):
        return ""
    if v >= 0.0005:
        return f"color:{T.POS}"
    if v <= -0.0005:
        return f"color:{T.NEG}"
    return f"color:{T.MUTED}"


def _ach_style(v, expected: float) -> str:
    """Colour achievement against where it should be by now (share of the month elapsed)."""
    if M.is_na(v):
        return ""
    if v >= expected:
        return f"color:{T.POS};font-weight:600"
    if v >= config.TARGET_LAG_THRESHOLD * expected:
        return f"color:{T.WARN};font-weight:600"
    return f"color:{T.NEG};font-weight:600"


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


def _header_label(c: str) -> str:
    basis = M.METRIC_LABELS[config.GROWTH_METRIC].split()[0]
    return {"MoM": f"Growth ({basis})", "Target": "AOP", "Ach.": "AOP ach."}.get(c, c)


def _fmt_cell(col: str, v, raw: bool) -> str:
    if M.is_na(v):
        return "—"
    if col in MONEY:
        return M.fmt_inr_full(v) if raw else M.fmt_inr(v)
    if col in PRICES:
        return M.fmt_price(v)
    if col in PERCENT:
        return M.fmt_pct(v, signed=PERCENT[col])
    return _html.escape(str(v))


def _cell_style(col: str, v, expected: float) -> str:
    if col == "MoM":
        return _growth_style(v)
    if col == "Ach.":
        return _ach_style(v, expected)
    return ""


def _row_html(row, cols: list[str], raw: bool, expected: float, bold: bool = False) -> str:
    cells = []
    for i, c in enumerate(cols):
        v = row[c]
        style = _cell_style(c, v, expected)
        if i == 0:
            style = (style + ";" if style else "") + "font-weight:600;color:" + T.INK
        elif bold:
            style = (style + ";" if style else "") + "font-weight:700"
        cells.append(f'<td style="{style}">{_fmt_cell(c, v, raw)}</td>')
    return "<tr>" + "".join(cells) + "</tr>"


def _render(df: pd.DataFrame, total_row, raw: bool, cols: list[str], expected: float,
           sort_key: str, default_sort: str = "MRP sales") -> None:
    helps = _help()
    sc1, sc2 = st.columns([3, 1])
    sort_options = [c for c in cols[1:]]
    with sc1:
        sort_col = st.selectbox("Sort by", sort_options, index=sort_options.index(default_sort),
                                key=f"{sort_key}_col", label_visibility="collapsed")
    with sc2:
        ascending = st.toggle("Ascending", key=f"{sort_key}_asc")
    df = df.sort_values(sort_col, ascending=ascending, na_position="last")

    thead = "".join(f'<th title="{_html.escape(helps.get(c, ""))}">{_html.escape(_header_label(c))}</th>'
                    for c in cols)
    body = "".join(_row_html(r, cols, raw, expected) for _, r in df.iterrows())
    total_html = f'<tbody class="k-tbl-total">{_row_html(total_row, cols, raw, expected, bold=True)}</tbody>' \
        if total_row is not None else ""
    st.markdown(
        f'<div class="k-tbl-wrap"><table class="k-tbl">'
        f'<thead><tr>{thead}</tr></thead><tbody>{body}</tbody>{total_html}</table></div>',
        unsafe_allow_html=True,
    )


def channel_table(tbl: pd.DataFrame, key_col: str, raw: bool, expected: float = 1.0) -> None:
    label = "Channel" if key_col == "channel" else "Channel group"
    cols = [key_col, "MRP sales", "Gross sales", "Net sales", "Discount", "AOV", "ASP", "MoM", "Target", "Ach."]
    if tbl["Target"].isna().all():
        cols = [c for c in cols if c not in ("Target", "Ach.")]
    total = M.add_totals_row(tbl, key_col)
    total_row = total.loc[total[key_col] == M.TOTAL_LABEL, cols].iloc[0]
    df = tbl[cols].reset_index(drop=True).rename(columns={key_col: label})
    total_row = total_row.rename({key_col: label})
    _render(df, total_row, raw, [label] + cols[1:], expected, f"tbl_{key_col}_{raw}")


def category_table(ct: pd.DataFrame, raw: bool) -> None:
    # No AOV here: an order spans categories, so a per-category order count (and the AOV built on
    # it) is not a real number. ASP (gross / units) is fine at category grain and stays.
    cols = ["Category", "MRP sales", "Gross sales", "Net sales", "Discount", "ASP", "MoM", "Share"]
    total = M.add_totals_row(ct, "Category")
    total_row = total.loc[total["Category"] == M.TOTAL_LABEL, cols].iloc[0]
    df = ct[cols].reset_index(drop=True)
    _render(df, total_row, raw, cols, 1.0, f"cat_{raw}")
