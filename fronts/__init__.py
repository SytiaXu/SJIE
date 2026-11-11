# -*- coding: utf-8 -*-
"""前沿方向透视:多期聚类快照 + 软对齐轨迹的独立模块。"""
from common.registry import ObsModule
from .data import load_fronts_data
from . import pages


def make_fronts_module(mid: str, icon: str, title: str, path: str, release_url: str | None = None) -> ObsModule:
    return ObsModule(
        id=mid, icon=icon, title=title,
        load=lambda: load_fronts_data(path, mid, release_url=release_url),
        pages={
            "📊 数据总览":    pages.render_overview,
            "🔀 变迁全景":    pages.render_transition,
            "🧪 学科主页":    pages.render_disc,
            "🧭 轨迹追踪":    pages.render_traj,
            "📄 方向明细":    pages.render_papers,
        },
    )

# GitHub Release 资产地址
FRONT_URL = "https://github.com/SytiaXu/SJIE/releases/download/v2026.11.11/front.xlsx"

FRONTS = make_fronts_module(
    mid="fronts", icon="🧭", title="前沿方向透视",
    path="data/front.xlsx",
    release_url=FRONT_URL,
)
