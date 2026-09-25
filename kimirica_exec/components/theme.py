"""Visual system: tokens, global CSS, header and section headings."""
from __future__ import annotations

import html
from pathlib import Path

import streamlit as st

INK = "#17231F"
MUTED = "#5E6B67"
FAINT = "#8A9591"
LINE = "#E2E7E5"
GRID = "#EEF1F0"
PAGE = "#F4F6F5"
SURFACE = "#FFFFFF"
ACCENT = "#1F4D46"
ACCENT_SOFT = "#DCE8E5"
POS = "#1D7A4C"
NEG = "#B3402E"
WARN = "#A76A0E"
FONT = "'IBM Plex Sans', -apple-system, 'Segoe UI', Roboto, sans-serif"

_CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600&display=swap');

html, body, .stApp, .stApp p, .stApp li, .stApp div, .stApp label, .stApp input, .stApp button,
.stApp h1, .stApp h2, .stApp h3, .stApp span:not([data-testid="stIconMaterial"]) {{ font-family: {FONT}; }}
.stApp {{ background: {PAGE}; color: {INK}; }}
.block-container {{ padding: 2.2rem 2.6rem 4rem; max-width: 1560px; }}
[data-testid="stToolbar"], [data-testid="stDecoration"], .stAppDeployButton, footer {{ display: none !important; }}
header[data-testid="stHeader"] {{ background: transparent; }}
[data-testid="stMainBlockContainer"] > div > [data-testid="stVerticalBlock"] {{ gap: 1.25rem; }}

/* widgets */
.stApp label p {{ font-size: 12px; color: {MUTED}; font-weight: 500; }}
[data-baseweb="select"] > div, [data-baseweb="input"] {{ border-radius: 8px; border: 1px solid {LINE} !important; background: #FAFBFB; }}
[data-baseweb="input"] > div {{ background: transparent; }}
.st-key-filters div[data-baseweb="select"] > div, .st-key-filters div[data-baseweb="input"] {{ background-color: #F4F7F6 !important; }}
.stButton button {{ border-radius: 8px; border: 1px solid {LINE}; background: {SURFACE}; color: {INK}; font-weight: 500; }}
.stButton button:hover {{ border-color: {ACCENT}; color: {ACCENT}; }}
.stButton button:focus-visible {{ outline: 2px solid {ACCENT}; outline-offset: 2px; }}

/* panels: containers keyed "panel_*" */
[class*="st-key-panel"] {{
  background: {SURFACE}; border: 1px solid {LINE}; border-radius: 14px; padding: 22px 24px 18px;
  box-shadow: 0 1px 2px rgba(23,35,31,.03);
}}
[class*="st-key-panel"] [data-testid="stVerticalBlock"] {{ gap: 0.75rem; }}
.st-key-filters {{ background: {SURFACE}; border: 1px solid {LINE}; border-radius: 14px; padding: 12px 18px 14px; margin-bottom: 8px; }}

/* header */
.k-head {{ text-align: center; padding: 6px 0 2px; margin-bottom: 8px; }}
.k-logo {{ color: {INK}; line-height: 0; }}
.k-logo svg {{ height: clamp(28px, 2.8vw, 38px); width: auto; }}

/* section headings */
.k-sec {{ margin: 0; }}
.k-sec h3 {{ font-size: 17px; font-weight: 600; color: {INK}; margin: 0; padding: 0; letter-spacing: -0.01em; }}
.k-sec p {{ font-size: 12.5px; color: {MUTED}; margin: 3px 0 0; }}

/* KPI cards: one grid, every card the same size */
.kpi-grid {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin-bottom: 4px; }}
@media (max-width: 1100px) {{ .kpi-grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }} }}
.kpi-lead {{ box-shadow: inset 3px 0 0 {ACCENT}; }}
.kpi {{ background: {SURFACE}; border: 1px solid {LINE}; border-radius: 14px; padding: 16px clamp(12px, 1.2vw, 18px) 14px; min-width: 0; }}
.kpi-label {{ font-size: 13px; font-weight: 500; color: {MUTED}; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
.kpi-label sup {{ font-size: 12px; color: {WARN}; margin-left: 1px; vertical-align: baseline; position: relative; top: -0.35em; line-height: 0; }}
.kpi-value {{ font-size: clamp(22px, 2vw, 31px); font-weight: 600; letter-spacing: -0.025em; color: {INK};
  line-height: 1.1; margin: 10px 0 10px; font-variant-numeric: tabular-nums; white-space: nowrap; }}
.kpi-delta {{ font-size: 13px; font-weight: 600; font-variant-numeric: tabular-nums; }}
.kpi-delta span {{ font-weight: 400; color: {MUTED}; margin-left: 2px; }}
.kpi-sub {{ font-size: 12px; color: {FAINT}; margin-top: 4px; white-space: nowrap; overflow: hidden;
  text-overflow: ellipsis; font-variant-numeric: tabular-nums; }}
.kpi-value.up {{ color: {POS}; }} .kpi-value.down {{ color: {NEG}; }}
.up {{ color: {POS}; }} .down {{ color: {NEG}; }} .flat {{ color: {MUTED}; }}
.kpi-feature {{ background: {ACCENT}; border-color: {ACCENT}; }}
.kpi-feature .kpi-label, .kpi-feature .kpi-delta span, .kpi-feature .kpi-sub {{ color: rgba(255,255,255,.72); }}
.kpi-feature .kpi-value {{ color: #FFFFFF; }}
.kpi-feature .up {{ color: #A6E3BE; }} .kpi-feature .down {{ color: #FFB9AA; }} .kpi-feature .flat {{ color: #FFFFFF; }}
.stApp .k-foot {{ font-size: 12px; line-height: 1.55; color: {MUTED}; margin: 0 0 14px 2px; }}
.k-foot b {{ color: {WARN}; font-weight: 600; }}

/* pacing: month and year */
.pace-wrap {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; margin: 6px 0 4px; }}
@media (max-width: 1000px) {{ .pace-wrap {{ grid-template-columns: minmax(0, 1fr); }} }}
.pace {{ background: {SURFACE}; border: 1px solid {LINE}; border-radius: 14px; padding: 18px 22px 16px; }}
.pace-top {{ display: flex; justify-content: space-between; align-items: baseline; gap: 12px; }}
.pace-title {{ font-size: 16px; font-weight: 600; color: {INK}; letter-spacing: -0.01em; }}
.pace-meta {{ font-size: 12px; color: {MUTED}; }}
.pace-bar {{ position: relative; height: 24px; background: {GRID}; border-radius: 6px; margin: 16px 0 14px; }}
.pace-fill {{ position: absolute; left: 0; top: 0; bottom: 0; background: {ACCENT}; border-radius: 6px;
  display: flex; align-items: center; justify-content: flex-end; overflow: hidden; }}
.pace-fill span {{ font-size: 11.5px; font-weight: 600; color: #FFFFFF; padding-right: 8px; white-space: nowrap;
  font-variant-numeric: tabular-nums; }}
.pace-proj {{ position: absolute; left: 0; top: 0; bottom: 0; border-radius: 6px; background: repeating-linear-gradient(
  -45deg, {ACCENT_SOFT}, {ACCENT_SOFT} 4px, #C7DAD5 4px, #C7DAD5 8px); }}
.pace-proj-label {{ position: absolute; top: 28px; transform: translateX(-100%); font-size: 11.5px;
  color: {MUTED}; white-space: nowrap; font-variant-numeric: tabular-nums; }}
.pace-mark {{ position: absolute; top: -4px; width: 2px; height: 32px; background: {INK}; opacity: .55; }}
.pace-stats {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; margin-top: 26px; }}
.pace-stat .l {{ font-size: 11.5px; color: {MUTED}; }}
.pace-stat .v {{ font-size: 17px; font-weight: 600; color: {INK}; font-variant-numeric: tabular-nums;
  letter-spacing: -0.01em; margin-top: 2px; }}

/* insights */
.ins {{ list-style: none; margin: 0; padding: 0; }}
.ins li {{ font-size: 14px; line-height: 1.6; color: {INK}; padding: 10px 0 10px 18px; border-bottom: 1px solid {GRID}; position: relative; }}
.ins li:last-child {{ border-bottom: 0; padding-bottom: 2px; }}
.ins li::before {{ content: ""; position: absolute; left: 0; top: 19px; width: 6px; height: 6px; border-radius: 50%; background: {ACCENT}; }}
.ins li b {{ font-weight: 600; }}
.watch li::before {{ background: {WARN}; }}
.watch li.high::before {{ background: {NEG}; }}
.empty {{ font-size: 13px; color: {MUTED}; padding: 8px 0; }}

/* tables */
[data-testid="stDataFrame"] {{ border: 1px solid {LINE}; border-radius: 10px; overflow: hidden; }}
/* Total row for the channel/category tables: a summary strip directly under the sortable grid, not
   a row inside it (st.dataframe's column-sort has no way to keep one row pinned). The wrapping
   container's own gap is tightened so the strip sits right against the table, not a page-section's
   worth of space below it. */
div[class*="st-key-tbl_"][class*="_wrap"] [data-testid="stVerticalBlock"],
div[class*="st-key-cat_"][class*="_wrap"] [data-testid="stVerticalBlock"] {{ gap: 0 !important; }}
.tbl-total-strip {{ display: flex; background: {SURFACE}; border: 1px solid {LINE}; border-top: 2px solid {INK};
  border-radius: 0 0 10px 10px; margin-top: 6px; overflow: hidden; }}
.tbl-total-cell {{ flex: 1 1 0; padding: 8px 14px; text-align: right; font-size: 13.5px; font-weight: 600;
  color: {INK}; white-space: nowrap; }}
.tbl-total-cell span {{ display: block; font-size: 11px; font-weight: 500; color: {MUTED}; margin-bottom: 2px; }}
.tbl-total-label-cell {{ flex: 0 0 auto; min-width: 120px; text-align: left; }}
.stApp .note {{ font-size: 11.5px; color: {FAINT}; margin: 0; }}
</style>
"""


def inject_css() -> None:
    st.markdown(_CSS, unsafe_allow_html=True)


def esc(text) -> str:
    return html.escape(str(text))


_LOGO_PATH = Path(__file__).resolve().parent.parent / "assets" / "kimirica_logo.svg"


@st.cache_resource(show_spinner=False)
def _logo_svg() -> str:
    try:
        return _LOGO_PATH.read_text(encoding="utf-8")
    except OSError:
        return '<span style="font-size:28px;letter-spacing:.2em;font-weight:500">KIMIRICA</span>'


def header() -> None:
    st.markdown(f'<div class="k-head"><div class="k-logo">{_logo_svg()}</div></div>',
                unsafe_allow_html=True)


def section(title: str, subtitle: str | None = None) -> None:
    sub = f"<p>{esc(subtitle)}</p>" if subtitle else ""
    st.markdown(f'<div class="k-sec"><h3>{esc(title)}</h3>{sub}</div>', unsafe_allow_html=True)


def note(text: str) -> None:
    st.markdown(f'<div class="note">{esc(text)}</div>', unsafe_allow_html=True)
