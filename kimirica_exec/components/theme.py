"""
Visual system: tokens, global CSS, header and section headings.

Dark mode: Streamlit detects the viewer's OS/browser colour-scheme preference itself (confirmed via
st.context.theme -- no .streamlit/config.toml entry needed, and no in-app toggle since our own CSS
hides Streamlit's menu). _apply_theme() reads that once per rerun and reassigns the module-level
colour names (INK, MUTED, ACCENT, ...) to the light or dark palette. Every other module reads these
as plain attribute lookups (T.INK, T.POS, ...) at the point it builds CSS or a Plotly figure -- never
cached at import time -- so they automatically pick up whichever palette this rerun resolved to,
including the charts, which bake in real hex colours and can't be themed via CSS alone.
"""
from __future__ import annotations

import html
from pathlib import Path

import streamlit as st

FONT = "'IBM Plex Sans', -apple-system, 'Segoe UI', Roboto, sans-serif"

_LIGHT = dict(
    INK="#17231F", MUTED="#5E6B67", FAINT="#8A9591", LINE="#E2E7E5", GRID="#EEF1F0",
    PAGE="#F4F6F5", SURFACE="#FFFFFF", ACCENT="#1F4D46", ACCENT_SOFT="#DCE8E5", STRIPE="#C7DAD5",
    POS="#1D7A4C", NEG="#B3402E", WARN="#A76A0E", INPUT_BG="#FAFBFB", INPUT_BG_FILTERS="#F4F7F6",
    SHADOW="rgba(23,35,31,.05)", GHOST_STRONG="#D5DDDA", GHOST_FAINT="#E6EBE9",
)
_DARK = dict(
    INK="#EDF1EF", MUTED="#9BA8A3", FAINT="#6E7A75", LINE="#2B322D", GRID="#1F2521",
    PAGE="#0E1117", SURFACE="#171B21", ACCENT="#4FB89C", ACCENT_SOFT="#1D3733", STRIPE="#284A44",
    POS="#3FCB86", NEG="#F0796A", WARN="#E3AE55", INPUT_BG="#1B2126", INPUT_BG_FILTERS="#1B2126",
    SHADOW="rgba(0,0,0,.25)", GHOST_STRONG="#3A453E", GHOST_FAINT="#20262C",
)

# Populated by _apply_theme() before anything else reads them; light values are the fallback if
# that hasn't run yet for some reason (e.g. a module imported outside a page run).
IS_DARK = False
globals().update(_LIGHT)


def _apply_theme() -> None:
    global IS_DARK
    try:
        IS_DARK = st.context.theme.get("type") == "dark"
    except Exception:
        IS_DARK = False
    globals().update(_DARK if IS_DARK else _LIGHT)


def _build_css() -> str:
    return f"""
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
[data-baseweb="select"] > div, [data-baseweb="input"] {{ border-radius: 8px; border: 1px solid {LINE} !important; background: {INPUT_BG}; color: {INK}; }}
[data-baseweb="input"] > div {{ background: transparent; }}
.st-key-filters div[data-baseweb="select"] > div, .st-key-filters div[data-baseweb="input"] {{ background-color: {INPUT_BG_FILTERS} !important; }}
.stButton button {{ border-radius: 8px; border: 1px solid {LINE}; background: {SURFACE}; color: {INK}; font-weight: 500; }}
.stButton button:hover {{ border-color: {ACCENT}; color: {ACCENT}; }}
.stButton button:focus-visible {{ outline: 2px solid {ACCENT}; outline-offset: 2px; }}

/* panels: containers keyed "panel_*" */
[class*="st-key-panel"] {{
  background: {SURFACE}; border: 1px solid {LINE}; border-radius: 14px; padding: 22px 24px 18px;
  box-shadow: 0 1px 2px {SHADOW};
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

/* KPI cards: one grid, every card the same size. Nine cards (with ROAS) divide evenly into 3x3. */
.kpi-grid {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; margin-bottom: 4px; }}
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
  -45deg, {ACCENT_SOFT}, {ACCENT_SOFT} 4px, {STRIPE} 4px, {STRIPE} 8px); }}
.pace-proj-label {{ position: absolute; top: 28px; transform: translateX(-100%); font-size: 11.5px;
  color: {MUTED}; white-space: nowrap; font-variant-numeric: tabular-nums; }}
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
/* The Total row is a second st.dataframe stacked right under the sortable one, using the exact
   same column_config -- see the long comment in components/tables.py for why (short version:
   st.dataframe's column-sort can't exclude a single row, and its canvas-rendered grid has no
   externally-readable column widths to match with anything else, so identical rendering is the
   only way to guarantee the two line up). The wrapper's own gap (Python gap= param) gets
   overridden by the broader `[class*="st-key-panel"] [data-testid="stVerticalBlock"]` rule above,
   since that's a descendant selector reaching into every nested container inside any panel_*
   section, including this one -- so it's pinned here too, as a single compound selector (class +
   data-testid on the SAME element, no space) with !important so it wins regardless of which rule
   loaded last. */
[data-testid="stVerticalBlock"][class*="st-key-tbl_"],
[data-testid="stVerticalBlock"][class*="st-key-cat_"] {{ gap: 4px !important; }}

/* The Total row's own header is redundant -- the table above it already labels every column --
   and having two header rows is what made it read as a second, disconnected table. Streamlit's
   dataframe grid draws its header on its own overlay <canvas> with no data-testid, separate from
   the body canvas (data-testid="data-grid-canvas"); confirmed by toggling each canvas's visibility
   on the live page and watching which one the header text disappeared from. Hiding that overlay
   removes only the header text; the blank space it leaves is then clipped away by capping the
   wrapping element to one row's height and shifting the dataframe up underneath it by the header
   canvas's own height. Both pixel numbers (37, 36) came from measuring the live page -- they are
   unrelated to the 38/35 used for sizing in tables.py, and would need re-measuring if a Streamlit
   upgrade changes the grid's header/row pixel height. */
[class*="st-key-tbl_"][class*="_wrap"] [data-testid="stElementContainer"]:last-of-type,
[class*="st-key-cat_"][class*="_wrap"] [data-testid="stElementContainer"]:last-of-type {{
  height: 37px !important; overflow: hidden;
}}
/* The inner stDataFrame keeps its own default border/radius (the generic rule above) completely
   untouched -- adding or removing a border here shifts how many pixels the grid renders itself at
   (confirmed by measuring it: giving this element its own border made it 2px NARROWER than the main
   table, because the grid sizes its own canvas off this element's box, border included). Only the
   position moves, so the width/border math stays byte-for-byte identical to the main table -- the
   bottom of its already-rounded box is what ends up on screen once the top is clipped away above. */
[class*="st-key-tbl_"][class*="_wrap"] [data-testid="stElementContainer"]:last-of-type [data-testid="stDataFrame"],
[class*="st-key-cat_"][class*="_wrap"] [data-testid="stElementContainer"]:last-of-type [data-testid="stDataFrame"] {{
  margin-top: -36px !important;
}}
[class*="st-key-tbl_"][class*="_wrap"] [data-testid="stElementContainer"]:last-of-type canvas:not([data-testid="data-grid-canvas"]),
[class*="st-key-cat_"][class*="_wrap"] [data-testid="stElementContainer"]:last-of-type canvas:not([data-testid="data-grid-canvas"]) {{
  visibility: hidden !important;
}}
[class*="st-key-tbl_"][class*="_wrap"] [data-testid="stElementContainer"]:last-of-type [data-testid="stElementToolbar"],
[class*="st-key-cat_"][class*="_wrap"] [data-testid="stElementContainer"]:last-of-type [data-testid="stElementToolbar"] {{
  display: none !important;
}}
.stApp .note {{ font-size: 11.5px; color: {FAINT}; margin: 0; }}
</style>
"""


def inject_css() -> None:
    _apply_theme()
    st.markdown(_build_css(), unsafe_allow_html=True)


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
