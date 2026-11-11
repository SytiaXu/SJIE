# -*- coding: utf-8 -*-
"""南工大论文透视 · 数据层。

同时加载「高被引」「热点」两个 Excel（每张工作表 = 一期快照），
产出:
  snapshots_* : {快照名: 规范化 df}
  meta_*      : 每期快照的统计概览
  timeline_*  : 论文 × 快照 的被引宽表(题名为主键, 不在榜 = NaN)
  paper_info  : 每篇论文的入榜轨迹(首次/最近在榜、在榜期数、类别标签)
  overlap     : 每期快照下「既是高被引又是热点」的题名键集合

★ 论文没有 ID 列,跨期追踪依赖规范化题名匹配,匹配率在 meta 中透明展示。
"""
import io
import os
import re
from dataclasses import dataclass, field
from typing import Dict, List, Set

import pandas as pd
import streamlit as st

REQUIRED_COLS = ("题名", "单位", "作者", "学科", "刊名", "发表年", "被引频次")
DISPLAY_COLS = ["题名", "学院", "作者", "学科", "刊名", "年份", "被引"]

# ---------- 小工具 ----------

# 全角 → 半角(含全角空格),题名规范化用
_F2H = {0xFF01 + i: 0x21 + i for i in range(0x5E)}
_F2H[0x3000] = 0x20
_F2H_TABLE = str.maketrans(_F2H)
_MISSING = {"", "nan", "none", "null", "/", "-"}


def _clean_cell(v) -> str:
    s = "" if pd.isna(v) else str(v).strip()
    return "" if s.lower() in _MISSING else s


def norm_title(s) -> str:
    """题名 → 匹配键:全角转半角、压缩空白、casefold。"""
    s = str(s).translate(_F2H_TABLE).strip()
    s = re.sub(r"\s+", " ", s)
    return s.casefold()


def split_multi(raw) -> List[str]:
    """「A;B;C」→ [A, B, C]。兼容全角/半角分号,过滤空段。"""
    if not isinstance(raw, str):
        return []
    parts = re.split(r"[;；]", raw)
    return [p.strip() for p in parts if p.strip()]


def fmt_snap(name) -> str:
    """sheet 名 → 展示名:202503 → 2025-03。"""
    s = str(name).strip()
    if re.fullmatch(r"\d{6}", s):
        return f"{s[:4]}-{s[4:]}"
    if re.fullmatch(r"\d{8}", s):
        return f"{s[:4]}-{s[4:6]}-{s[6:]}"
    return s


# ---------- 单期快照规范化 ----------

def _normalize_sheet(raw: pd.DataFrame) -> pd.DataFrame:
    df = raw.copy()
    df.columns = [str(c).strip().lower() for c in df.columns]
    missing = set(REQUIRED_COLS) - set(df.columns)
    if missing:
        raise ValueError(f"工作表缺少列:{sorted(missing)}(实际列:{list(df.columns)})")

    df = (df.rename(columns={"单位": "学院", "发表年": "年份", "被引频次": "被引"})
            [["题名", "学院", "作者", "学科", "刊名", "年份", "被引"]]
            .dropna(subset=["题名"]))

    # 年份:兼容 datetime / "2023-06" / "2023.06" 等脏格式,一律抽 4 位年份
    if pd.api.types.is_datetime64_any_dtype(df["年份"]):
        df["年份"] = df["年份"].dt.year
    else:
        df["年份"] = pd.to_numeric(df["年份"].astype(str).str.extract(r"(\d{4})")[0],
                                   errors="coerce")
    df["年份"] = df["年份"].astype("Int64")

    # 被引频次:转数值,脏数据 → NaN(页面端按"缺失"处理,不伪装成 0)
    df["被引"] = pd.to_numeric(df["被引"], errors="coerce")

    df["题名"] = df["题名"].astype(str).str.strip()
    df["title_key"] = df["题名"].map(norm_title)
    for c in ("学院", "学科", "作者"):
        df[c] = df[c].map(_clean_cell)
    df["刊名"] = df["刊名"].map(_clean_journal)

    # 同一期内题名重复:保留被引最高的一条(极可能是同文重复录入)
    dup = int(df.duplicated(subset=["title_key"]).sum())
    if dup:
        df = (df.sort_values("被引", na_position="first")
                .drop_duplicates(subset=["title_key"], keep="last"))
    df.attrs["removed_duplicates"] = dup
    return df.reset_index(drop=True)


def _clean_journal(v) -> str:
    if pd.isna(v):
        return ""
    s = str(v).strip()
    m = re.match(r"(\d+[A-Za-z]+\s*)*\D*", s)   # 允许开头出现"3D"这类词
    return m.group().rstrip()


@st.cache_data(show_spinner="正在读取 Excel…")
def _load_domain(source, _tag: str = ""):
    """读一个 Excel(高被引或热点)→ (snapshots dict, meta df)。source 为路径或 bytes。"""
    if isinstance(source, (bytes, bytearray)):
        source = io.BytesIO(source)
    sheets = pd.read_excel(source, sheet_name=None, engine="openpyxl")

    data, meta = {}, []
    for name, raw in sheets.items():
        try:
            snap = _normalize_sheet(raw)
        except ValueError as e:
            raise ValueError(f"工作表「{name}」:{e}")
        key = fmt_snap(name)
        if key in data:
            raise ValueError(f"快照名重复:{key}(来自工作表「{name}」),请检查 sheet 命名。")
        data[key] = snap
        units = snap["学院"].map(split_multi).explode().dropna()
        units = units[~units.str.lower().isin(_MISSING)]
        meta.append({"快照": key, "论文数": len(snap),
                     "去重删除": snap.attrs.get("removed_duplicates", 0),
                     "学院数": units.nunique(),
                     "学科数": snap["学科"].nunique(),
                     "期刊数": snap["刊名"].nunique(),
                     "总被引": int(snap["被引"].sum(skipna=True)),
                     "篇均被引": round(snap["被引"].mean(), 1)})
    if not data:
        raise ValueError("Excel 里没有任何可用的工作表。")
    return dict(sorted(data.items())), pd.DataFrame(meta).set_index("快照")


# ---------- 跨期结构:timeline 宽表 / paper_info / overlap ----------

def _build_timeline(snapshots: Dict[str, pd.DataFrame], snaps: List[str]) -> pd.DataFrame:
    """index=题名键,columns=按时间排序的快照名,值=该期被引(NaN=不在榜)。"""
    series = {s: snapshots[s].set_index("title_key")["被引"] for s in snaps}
    tl = pd.DataFrame(series).reindex(columns=snaps)
    return tl


def _build_paper_info(snapshots: Dict[str, pd.DataFrame], snaps: List[str]) -> pd.DataFrame:
    """每篇论文一行:入榜轨迹 + 最近一期的展示字段。"""
    frames = []
    for i, s in enumerate(snaps):
        d = snapshots[s].copy()
        d["序号"], d["快照名"] = i, s
        frames.append(d)
    panel = pd.concat(frames, ignore_index=True)

    g = panel.groupby("title_key")
    info = g.agg(首次入榜=("序号", "min"), 最近在榜=("序号", "max"),
                 在榜期数=("序号", "nunique"))
    # 展示字段取「最近一期在榜」的记录(被引等取最新值)
    latest = (panel.sort_values("序号").groupby("title_key").tail(1)
                    .set_index("title_key")[DISPLAY_COLS])
    info = info.join(latest)

    info["首次入榜快照"] = info["首次在榜"] if False else [snaps[i] for i in info["首次入榜"]]
    info["最近在榜快照"] = [snaps[i] for i in info["最近在榜"]]
    info["学院列表"] = info["学院"].map(split_multi)
    info["作者列表"] = info["作者"].map(split_multi)
    return info.reset_index()


# ---------- 汇总容器 ----------

@dataclass
class NJTechData:
    """一次加载的全部结构。pages 通过 ctx 拿到的就是它(见 __init__.py 说明)。"""
    highly: Dict[str, pd.DataFrame]
    hot: Dict[str, pd.DataFrame]
    meta_highly: pd.DataFrame
    meta_hot: pd.DataFrame
    snaps_highly: List[str] = field(default_factory=list)
    snaps_hot: List[str] = field(default_factory=list)
    timeline_highly: pd.DataFrame = None
    timeline_hot: pd.DataFrame = None
    paper_info_highly: pd.DataFrame = None
    paper_info_hot: pd.DataFrame = None
    overlap: Dict[str, Set[str]] = field(default_factory=dict)

    def __post_init__(self):
        self.snaps_highly = list(self.highly.keys())
        self.snaps_hot = list(self.hot.keys())
        self.timeline_highly = _build_timeline(self.highly, self.snaps_highly)
        self.timeline_hot = _build_timeline(self.hot, self.snaps_hot)
        self.paper_info_highly = _build_paper_info(self.highly, self.snaps_highly)
        self.paper_info_hot = _build_paper_info(self.hot, self.snaps_hot)
        # 双榜交集:以两域共有的快照为准
        common = [s for s in self.snaps_highly if s in self.hot]
        self.overlap = {s: set(self.highly[s]["title_key"]) & set(self.hot[s]["title_key"])
                        for s in common}

    # ---- 兼容层:让通用基础设施能按 (snapshots, meta) 解包 / 访问 ----
    # 高被引作为"主域",热点数据通过附加属性访问
    @property
    def snapshots(self):
        return self.highly

    @property
    def meta(self):
        return self.meta_highly

    def __iter__(self):
        """若 PageCtx 由 `snapshots, meta = load()` 构造,此处保证不炸。"""
        yield self.highly
        yield self.meta_highly


# ---------- 入口 ----------

def _resolve_source(path: str, label: str, domain_id: str):
    """本地文件优先,否则侧边栏上传兜底。返回 (source, tag) 或 None。"""
    if os.path.exists(path):
        return path, os.path.getmtime(path)
    up = st.sidebar.file_uploader(f"上传「{label}」Excel 数据文件", type=["xlsx"],
                                  key=f"upload_{domain_id}_{label}")
    if up is None:
        return None
    return up.getvalue(), len(up.getvalue())


def load_njtech_data(highly_path: str, hot_path: str, domain_id: str) -> NJTechData:
    src_h = _resolve_source(highly_path, "高被引论文", domain_id)
    src_t = _resolve_source(hot_path, "热点论文", domain_id)
    if src_h is None or src_t is None:
        st.info(f"未找到 `{highly_path}` / `{hot_path}`,请在左侧上传对应 Excel"
                "(每张工作表一个时间快照,含题名/单位/作者/学科/刊名/发表年/被引频次七列)。")
        st.stop()

    highly, meta_h = _load_domain(src_h[0], _tag=src_h[1])
    hot, meta_t = _load_domain(src_t[0], _tag=src_t[1])
    result = NJTechData(highly=highly, hot=hot, meta_highly=meta_h, meta_hot=meta_t)
    # 完整双域数据经 session_state 中转给 pages
    st.session_state[f"njtech_data_{domain_id}"] = result
    return result          # app.py 解包时取主域(高被引)的 snapshots/meta
