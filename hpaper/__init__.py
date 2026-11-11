# -*- coding: utf-8 -*-
"""论文类观测：同一套 data + pages，注册成多个数据域。

★ 新增同格式数据域（如 ESI、某专题论文）只需在底部加一行 make_papers_module(...)，
  并在 app.py 的 DOMAINS 里登记，页面代码零改动。
"""
from common.registry import ObsModule
from .data import load_paper_snapshots
from . import pages


def make_papers_module(mid: str, icon: str, title: str,
                       excel_path: str, upload_label: str) -> ObsModule:
    return ObsModule(
        id=mid, icon=icon, title=title,
        load=lambda: load_paper_snapshots(excel_path, upload_label, mid),
        pages={
            "📊 数据总览": pages.render_overview,
            "🏫 高校主页": pages.render_school,
            "📚 学科主页": pages.render_disc,
            "🗺️ 省市主页": pages.render_prov,
            "🔀 往期对比": pages.render_diff,
            "📈 时间轴": pages.render_timeline,
        },
    )


HOT = make_papers_module(
    mid="hot", icon="🔥", title="全球热点论文",
    excel_path="data/hot.xlsx",
    upload_label="上传「热点论文」Excel 数据文件",
)

HIGHLY = make_papers_module(
    mid="highly", icon="📌", title="全球高被引论文",
    excel_path="data/highly.xlsx",
    upload_label="上传「高被引论文」Excel 数据文件",
)
