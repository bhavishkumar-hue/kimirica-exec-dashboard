"""KPI cards and the month / year pacing panels."""
from __future__ import annotations

import streamlit as st

import config
import metrics as M
from components.theme import esc

AOV_NOTE = "AOV is ASP for channels where order data isn't available."


def _delta(value, label: str, neutral: bool = False, invert: bool = False) -> str:
    if value is None:
        return f'<div class="kpi-delta flat">—<span>{esc(label)}</span></div>'
    tiny = abs(value) < 0.0005
    good = value > 0 if not invert else value < 0
    cls = "flat" if (neutral or tiny) else ("up" if good else "down")
    arrow = "■" if tiny else "▲" if value > 0 else "▼"
    return f'<div class="kpi-delta {cls}">{arrow} {esc(M.fmt_pct(value))} <span>{esc(label)}</span></div>'


def _card(label: str, value: str, delta_html: str, sub: str, extra_cls: str = "") -> str:
    return (f'<div class="kpi {extra_cls}"><div class="kpi-label">{esc(label)}</div>'
            f'<div class="kpi-value">{esc(value)}</div>'
            f'{delta_html}<div class="kpi-sub">{esc(sub)}</div></div>')


def render_kpis(s: dict, P: M.Periods, ads_available: bool) -> None:
    """Eight equal cards for the selected period, each against the chosen comparison."""
    cur, prev = s["cur"], s["prev"]
    vs = P.cmp_label
    ref = P.cmp_short
    gst = f"{config.GST_RATE * 100:.0f}%"

    if ads_available:
        ad_card = _card("Ad spends", M.fmt_inr(cur["ad_spend"]), _delta(s["ad_mom"], vs, neutral=True),
                        (f"{M.fmt_pct(cur['ad_share'], signed=False)} of gross"
                         if cur["ad_share"] is not None else f"{ref} {M.fmt_inr(prev['ad_spend'])}"))
    else:
        ad_card = _card("Ad spends", "—", _delta(None, vs), "Not connected")

    cards = [
        _card("MRP sales", M.fmt_inr(cur["mrp"]), _delta(s["mrp_mom"], vs),
              f"{ref} {M.fmt_inr(prev['mrp'])}", extra_cls="kpi-lead"),
        _card("Gross sales", M.fmt_inr(cur["gross"]), _delta(s["gross_mom"], vs),
              f"{ref} {M.fmt_inr(prev['gross'])}"),
        _card(f"Net sales (ex {gst} GST)", M.fmt_inr(cur["net"]), _delta(s["net_mom"], vs),
              f"{ref} {M.fmt_inr(prev['net'])}"),
        _card("Discount", M.fmt_pct(cur["discount"], signed=False),
              _delta(M.pct(cur["discount"], prev["discount"]), vs, invert=True),
              f"{ref} {M.fmt_pct(prev['discount'], signed=False)}"),
        _card("Quantity", M.fmt_count(cur["qty"]), _delta(s["qty_mom"], vs),
              f"{ref} {M.fmt_count(prev['qty'])} units"),
        _card("AOV", M.fmt_price(cur["aov"]), _delta(s["aov_mom"], vs),
              f"{ref} {M.fmt_price(prev['aov'])}"),
        _card("ASP", M.fmt_price(cur["asp"]), _delta(s["asp_mom"], vs),
              f"{ref} {M.fmt_price(prev['asp'])}"),
        ad_card,
    ]
    st.markdown(f'<div class="kpi-grid">{"".join(cards)}</div>', unsafe_allow_html=True)


def _bar(achieved_pct: float, projected_pct: float, elapsed_pct: float,
         achieved_text: str, projected_text: str) -> str:
    a, pr = min(achieved_pct, 1.0) * 100, min(projected_pct, 1.0) * 100
    return (f'<div class="pace-bar">'
            f'<div class="pace-proj" style="width:{pr:.1f}%"></div>'
            f'<div class="pace-fill" style="width:{a:.1f}%"><span>{esc(achieved_text)}</span></div>'
            f'<div class="pace-proj-label" style="left:{pr:.1f}%">{esc(projected_text)}</div>'
            f'<div class="pace-mark" style="left:calc({elapsed_pct * 100:.1f}% - 1px)"></div>'
            f'</div>')


def _panel(title: str, period: str, target, achieved, ach, projection, projected_ach, pace,
           elapsed: float, estimated: bool) -> str:
    if not target:
        return (f'<div class="pace"><div class="pace-top"><div class="pace-title">{esc(title)}</div>'
                f'<div class="pace-meta">{esc(period)}</div></div>'
                f'<div class="empty">No AOP for this selection.</div></div>')
    bar = _bar(
        (achieved or 0) / target, (projection or 0) / target, elapsed,
        f"{M.fmt_inr(achieved)}  {M.fmt_pct(ach, signed=False)}",
        f"projected {M.fmt_inr(projection)}  {M.fmt_pct(projected_ach, signed=False)}",
    )
    stats = [
        ("AOP", M.fmt_inr(target) + (" est." if estimated else "")),
        ("Achieved", M.fmt_inr(achieved)),
        ("Projected", M.fmt_inr(projection)),
        ("Pace", f"{M.fmt_inr(pace)}/day"),
    ]
    stat_html = "".join(f'<div class="pace-stat"><div class="l">{esc(l)}</div><div class="v">{esc(v)}</div></div>'
                        for l, v in stats)
    return (f'<div class="pace"><div class="pace-top"><div class="pace-title">{esc(title)}</div>'
            f'<div class="pace-meta">{esc(period)}</div></div>{bar}'
            f'<div class="pace-stats">{stat_html}</div></div>')


def render_pacing(s: dict, P: M.Periods) -> None:
    """Month and year pacing against AOP, on MRP sales. Projected = at the current pace."""
    cur = s["cur"]
    if not s["month_target"] and not s["year_target"]:
        return
    month = _panel(
        "Month pacing", f"{P.as_of:%B %Y}, {P.days_left} days left",
        s["month_target"], s["month_achieved"], s["month_ach"],
        s["target_projection"], s["projected_ach"], s["current_rr"],
        P.month_progress, s["month_target_estimated"],
    )
    year = _panel(
        "Year pacing", f"{P.year_label.replace(' to date', '')}, day {P.year_days_elapsed} of {P.year_days}",
        s["year_target"], s["year_actual"], s["year_ach"],
        s["year_projection"], s["year_projected_ach"], s["year_rr"],
        P.year_progress, s["year_target_estimated"],
    )
    st.markdown(f'<div class="pace-wrap">{month}{year}</div>', unsafe_allow_html=True)
