# -*- coding: utf-8 -*-
"""南工大论文透视:高被引 + 热点双数据域的独立模块(与 hpaper 平行)。"""
from common.registry import ObsModule
from .data import load_njtech_data
from . import pages


def make_njtech_module(mid: str, icon: str, title: str,
                       highly_path: str, hot_path: str,
                       highly_url: str | None = None,
                       hot_url: str | None = None) -> ObsModule:
    return ObsModule(
        id=mid, icon=icon, title=title,
        load=lambda: load_njtech_data(highly_path, hot_path, mid, highly_url=highly_url, hot_url=hot_url),
        pages={
            "📊 数据总览":      pages.render_overview,
            "🧪 学科主页":      pages.render_disc,
            "🏢 学院主页":      pages.render_college,
            "👤 作者主页":      pages.render_authors,
            "🕸️ 合作网络":      pages.render_network,
            "📰 期刊主页":      pages.render_journal,
            "📈 引用动态":      pages.render_citation,
            "🔀 高被引×热点":   pages.render_overlap,
            "📄 论文明细":      pages.render_papers,
        },
    )

NJTHIGHLY_URL = "https://github.com/SytiaXu/SJIE/releases/download/v2026.11.11/njtech_highly.xlsx"
NJTHOT_URL = "https://github.com/SytiaXu/SJIE/releases/download/v2026.11.11/njtech_hot.xlsx"

NJTECH = make_njtech_module(
    mid="njtech", icon="🏫", title="NJTECH论文透视",
    highly_path="data/njtech_highly.xlsx",
    hot_path="data/njtech_hot.xlsx",
    highly_url=NJTHIGHLY_URL,
    hot_url=NJTHOT_URL,
)