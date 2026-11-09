# -*- coding: utf-8 -*-
"""域框架：ObsModule（数据域配置）+ PageCtx（页面函数的全部输入）"""
from dataclasses import dataclass
from typing import Callable

import pandas as pd


@dataclass
class ObsModule:
    id: str                    # 域 id：决定 widget key 前缀（hot_… / highly_…）
    icon: str
    title: str
    load: Callable             # () -> (snapshots: dict[str, DataFrame], meta: DataFrame)
    pages: dict[str, Callable] # 页面显示名 -> render(ctx)


@dataclass
class PageCtx:
    module: ObsModule
    snapshots: dict            # 快照名 -> DataFrame
    meta: pd.DataFrame

    def k(self, page: str, name: str) -> str:
        """生成全局唯一 widget key：域_页面_控件 → 各域各页状态完全独立。"""
        return f"{self.module.id}_{page}_{name}"
