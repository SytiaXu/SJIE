# -*- coding: utf-8 -*-
"""通用 UI 工具"""
import streamlit as st


def setup_page(title: str):
    st.set_page_config(page_title=title, page_icon="🏆", layout="wide",
                       initial_sidebar_state="expanded")


def style_fig(fig, height=None):
    """统一图表风格"""
    fig.update_layout(
        template="plotly_white",
        margin=dict(l=10, r=10, t=40, b=10),
        height=height,
    )
    return fig


def safe_slider(label, n, default_n, key=None, help=None):
    """按实际数量钳位 min/max/default 的侧边栏滑块，n 过小时不会报错。"""
    hi = max(5, min(100, n))
    default = max(5, min(default_n, n, hi))
    if hi <= 5:
        return hi
    return st.sidebar.slider(label, 5, hi, default, key=key, help=help)
