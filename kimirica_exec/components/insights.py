"""Highlights and watchlist. Text is assembled in metrics.py from computed numbers only."""
from __future__ import annotations

import streamlit as st


def highlights(lines: list[str]) -> None:
    if not lines:
        st.markdown('<div class="empty">Not enough comparable data to summarise this selection.</div>',
                    unsafe_allow_html=True)
        return
    items = "".join(f"<li>{line}</li>" for line in lines)
    st.markdown(f'<ul class="ins">{items}</ul>', unsafe_allow_html=True)


def watchlist(items: list[tuple[str, str]]) -> None:
    if not items:
        st.markdown('<div class="empty">Nothing needs attention: all channel feeds are current, '
                    'no unusual daily swings, and no channel is materially behind target.</div>',
                    unsafe_allow_html=True)
        return
    lis = "".join(f'<li class="{sev}">{text}</li>' for sev, text in items)
    st.markdown(f'<ul class="ins watch">{lis}</ul>', unsafe_allow_html=True)
