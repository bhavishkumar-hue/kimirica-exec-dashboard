"""Plotly charts. One template, rupee-formatted axes and tooltips, no mode bar."""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import config
import metrics as M
from components import theme as T

PLOT_CONFIG = {"displayModeBar": False, "responsive": True}


def _base(fig: go.Figure, height: int, hovermode: str = "x unified", legend: bool = True) -> go.Figure:
    fig.update_layout(
        height=height,
        margin=dict(l=4, r=12, t=8 if not legend else 36, b=4),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family=T.FONT, size=12, color=T.MUTED),
        hovermode=hovermode,
        hoverlabel=dict(bgcolor="white", bordercolor=T.LINE, font=dict(family=T.FONT, size=12, color=T.INK)),
        showlegend=legend,
        legend=dict(orientation="h", yanchor="bottom", y=1.0, xanchor="left", x=0,
                    font=dict(size=11.5, color=T.MUTED), itemclick="toggle", itemdoubleclick="toggleothers",
                    bgcolor="rgba(0,0,0,0)", traceorder="normal"),
        bargap=0.28,
    )
    fig.update_xaxes(showgrid=False, linecolor=T.LINE, ticks="", tickfont=dict(color=T.FAINT), zeroline=False)
    fig.update_yaxes(showgrid=True, gridcolor=T.GRID, zeroline=False, ticks="", tickfont=dict(color=T.FAINT))
    return fig


def _money_axis(fig: go.Figure, lo: float, hi: float, axis: str = "y", currency: bool = True) -> None:
    ticks = M.nice_ticks(lo, hi)
    text = [M.fmt_inr(t) if currency else M.fmt_count(t) for t in ticks]
    text = [t if v != 0 else ("₹0" if currency else "0") for t, v in zip(text, ticks)]
    upd = dict(tickmode="array", tickvals=ticks, ticktext=text, range=[ticks[0], ticks[-1] * 1.02 or 1])
    (fig.update_yaxes if axis == "y" else fig.update_xaxes)(**upd)


def _show(fig: go.Figure, key: str) -> None:
    st.plotly_chart(fig, config=PLOT_CONFIG, width="stretch", key=key)


def _fmt(v, currency: bool) -> str:
    return M.fmt_inr_full(v) if currency else M.fmt_count_full(v)


# --------------------------------------------------------------------------- #
def growth_drivers_chart(tbl: pd.DataFrame, key_col: str, height: int | None = None) -> None:
    d = tbl.dropna(subset=["Δ vs LMTD"]).sort_values("Δ vs LMTD")
    if d.empty:
        st.markdown('<div class="empty">No comparable last-month data for this selection.</div>', unsafe_allow_html=True)
        return
    total_lmtd = tbl["LMTD"].sum(min_count=1)
    contrib = d["Δ vs LMTD"] / total_lmtd if total_lmtd and total_lmtd > 0 else d["Δ vs LMTD"] * np.nan
    colors = [T.POS if v >= 0 else T.NEG for v in d["Δ vs LMTD"]]
    fig = go.Figure(go.Bar(
        x=d["Δ vs LMTD"], y=d[key_col], orientation="h",
        marker=dict(color=colors, opacity=0.85, line=dict(width=0)),
        text=[("+" if v > 0 else "") + M.fmt_inr(v) for v in d["Δ vs LMTD"]],
        textposition="outside", cliponaxis=False, textfont=dict(size=11, color=T.MUTED),
        customdata=np.stack([
            [M.fmt_inr_full(v) for v in d["Δ vs LMTD"]],
            [M.fmt_pct(v) for v in d["MoM"]],
            [M.fmt_pct(v) for v in contrib],
        ], axis=-1),
        hovertemplate="<b>%{y}</b><br>Change %{customdata[0]}<br>Growth %{customdata[1]}"
                      "<br>Share of total change %{customdata[2]}<extra></extra>",
    ))
    _base(fig, height or max(260, 30 * len(d) + 40), hovermode="closest", legend=False)
    lo, hi = float(d["Δ vs LMTD"].min()), float(d["Δ vs LMTD"].max())
    pad = (hi - lo) * 0.18 or 1
    _money_axis(fig, lo - pad, hi + pad, axis="x")
    ticks = M.nice_ticks(lo - pad, hi + pad)
    fig.update_xaxes(showgrid=True, gridcolor=T.GRID, zeroline=True, zerolinecolor=T.LINE, range=[ticks[0], ticks[-1]])
    fig.update_yaxes(showgrid=False, tickfont=dict(color=T.INK, size=12))
    _show(fig, "drivers")


def target_chart(tf: pd.DataFrame, height: int | None = None, expected: float = 1.0) -> None:
    fig = go.Figure()
    fig.add_trace(go.Bar(
        y=tf["channel"], x=tf["target"], name="AOP target", orientation="h",
        marker=dict(color="#D5DDDA", line=dict(width=0)),
        customdata=[M.fmt_inr_full(v) for v in tf["target"]], hovertemplate="%{customdata}",
    ))
    fig.add_trace(go.Bar(
        y=tf["channel"], x=tf["actual"], name="Achieved", orientation="h",
        marker=dict(color=T.ACCENT, line=dict(width=0)),
        customdata=[M.fmt_inr_full(v) for v in tf["actual"]], hovertemplate="%{customdata}",
    ))
    hi = float(np.nanmax(tf[["actual", "target"]].to_numpy(dtype=float)))
    for _, r in tf.iterrows():
        ach = r["ach"]
        color = (T.MUTED if M.is_na(ach) else T.POS if ach >= expected
                 else T.WARN if ach >= config.TARGET_LAG_THRESHOLD * expected else T.NEG)
        fig.add_annotation(x=hi * 1.02, y=r["channel"], text=f"<b>{M.fmt_pct(ach, signed=False)}</b>",
                           showarrow=False, xanchor="left", font=dict(size=12, color=color))
    _base(fig, height or max(280, 34 * len(tf) + 60), hovermode="y unified")
    fig.update_layout(barmode="overlay", bargap=0.35)
    fig.data[1].update(width=0.42)
    _money_axis(fig, 0, hi * 1.14, axis="x")
    fig.update_xaxes(showgrid=True, gridcolor=T.GRID)
    fig.update_yaxes(showgrid=False, tickfont=dict(color=T.INK, size=12))
    _show(fig, "target")


def category_chart(ct: pd.DataFrame, P: M.Periods) -> None:
    col = M.METRIC_LABELS[config.GROWTH_METRIC]
    d = ct.sort_values(col)
    fig = go.Figure()
    fig.add_trace(go.Bar(
        y=d["Category"], x=d[col], name=f"{col}, this period", orientation="h",
        marker=dict(color=T.ACCENT, line=dict(width=0)),
        text=[f"\u2003{M.fmt_inr(v)}  {M.fmt_pct(g)}" for v, g in zip(d[col], d["MoM"])],
        textposition="outside", cliponaxis=False, textfont=dict(size=11, color=T.MUTED),
        customdata=[M.fmt_inr_full(v) for v in d[col]], hovertemplate="%{customdata}",
    ))
    fig.add_trace(go.Scatter(
        y=d["Category"], x=d["LMTD"], name=P.cmp_short, mode="markers",
        marker=dict(symbol="line-ns", size=18, line=dict(width=2.5, color=T.INK)),
        customdata=[M.fmt_inr_full(v) for v in d["LMTD"]], hovertemplate="%{customdata}",
    ))
    hi = float(np.nanmax(d[[col, "LMTD"]].to_numpy(dtype=float)))
    _base(fig, max(260, 40 * len(d) + 60), hovermode="y unified")
    _money_axis(fig, 0, hi * 1.3, axis="x")
    fig.update_xaxes(showgrid=True, gridcolor=T.GRID)
    fig.update_yaxes(showgrid=False, tickfont=dict(color=T.INK, size=12))
    _show(fig, "category")


_TREND_KEYS = {"mrp_sales": "mrp", "gross_sales": "gross", "net_sales": "net", "quantity": "qty"}


def monthly_trend_chart(mt: pd.DataFrame, metric: str) -> None:
    """Monthly bars for this year, last year as a faint ghost behind. Hover: value, LY, YoY, MoM."""
    k = _TREND_KEYS[metric]
    currency = metric != "quantity"
    fmt = M.fmt_inr if currency else M.fmt_count
    x = mt["label"]
    hover = [
        (f"<b>{fmt(r[k])}</b>{' MTD' if r['current'] else ''}<br>"
         f"Last year {fmt(r['ly_' + k])}<br>"
         f"YoY {M.fmt_pct(r['yoy_' + k])}{'  (same days)' if r['current'] else ''}<br>"
         f"MoM {M.fmt_pct(r['mom_' + k])}")
        for _, r in mt.iterrows()
    ]
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=x, y=mt["ly_" + k], name="Last year", width=0.72,
        marker=dict(color="#E6EBE9", line=dict(width=0)), hoverinfo="skip",
    ))
    fig.add_trace(go.Bar(
        x=x, y=mt[k], name="This year", width=0.42,
        marker=dict(color=T.ACCENT, line=dict(width=0),
                    pattern=dict(shape=["/" if c else "" for c in mt["current"]],
                                 fgcolor="rgba(255,255,255,0.35)", size=6, fillmode="overlay")),
        text=[("" if M.is_na(v) else ("▲ " if v >= 0 else "▼ ") + M.fmt_pct(v)) for v in mt["yoy_" + k]],
        textposition="outside", cliponaxis=False, textfont=dict(size=11, color=T.MUTED),
        customdata=hover, hovertemplate="%{customdata}<extra></extra>",
    ))
    _base(fig, 360, hovermode="x")
    fig.update_layout(barmode="overlay", bargap=0.3)
    fig.update_xaxes(tickfont=dict(color=T.INK, size=12))
    vals = mt[[k, "ly_" + k]].to_numpy(dtype=float)
    hi = float(np.nanmax(vals)) if np.isfinite(vals).any() else 1.0
    _money_axis(fig, 0, hi * 1.14, currency=currency)
    _show(fig, "monthly_trend")
