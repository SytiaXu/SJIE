# coding: utf-8 -*-
"""学科建设观测 · 入口。两级导航：观测域 → 页面。此处不含业务逻辑。"""
import streamlit as st

from common.ui import setup_page
from common.registry import PageCtx
from hpaper import HOT, HIGHLY
from njtech import NJTECH

# 域注册表：侧边栏一级导航顺序即此字典顺序。
DOMAINS: dict[str, object] = {
    f"{m.icon} {m.title}": m for m in (NJTECH, HOT, HIGHLY)
}

setup_page("学科建设观测")
st.markdown("## 🏆 学科建设观测")

# ================= 1. 一级导航：观测域 =================
with st.sidebar:
    st.markdown("### 🧭 观测域")
    domain_name = st.radio("域", list(DOMAINS), label_visibility="collapsed")
    module = DOMAINS[domain_name]
    st.caption(f"当前域：{module.icon} {module.title}")
    st.divider()

# ================= 2. 加载数据（惰性：切到该域才读） =================
try:
    snapshots, meta = module.load()
except Exception as e:
    st.error(f"「{module.title}」数据加载失败：{e}")
    st.stop()

# ================= 3. 二级导航：页面 =================
with st.sidebar:
    st.markdown("### 📑 页面")
    page_name = st.radio("页面", list(module.pages), label_visibility="collapsed")
    st.divider()

# ================= 4. 渲染 =================
ctx = PageCtx(module=module, snapshots=snapshots, meta=meta)
module.pages[page_name](ctx)
