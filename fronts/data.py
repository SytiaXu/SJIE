# -*- coding: utf-8 -*-
"""前沿方向透视 · 数据层。

加载一个 Excel(每张工作表 = 一期快照,行 = 前沿方向,含
Fronts / Papers / Citations / xk / myear 五列),产出:
  snapshots : {快照名: 规范化 df}(含 来源/去向 分类、轨迹 ID)
  meta      : 每期快照的统计概览(方向数、头部长尾、词汇重合率、匹配率)
  links     : 相邻两期的贪心一对一匹配结果(轨迹链的边)
  traj      : 轨迹汇总表(一条轨迹 = 跨期软对齐形成的方向演化链)
  traj_tl   : 轨迹 × 快照 的论文数宽表(缺席期 = NaN)

★ 每期聚类独立产生,方向没有天然 ID;跨期追踪依赖关键词 Jaccard
  软对齐,匹配率在 meta 中透明展示。链上相似度越低,轨迹越不可信。
"""
import io
import os
import re
from collections import defaultdict, Counter
from dataclasses import dataclass, field
from typing import Dict, List

import pandas as pd
import streamlit as st
from common.download import download_from_release

# ---------- 配置 ----------
REQUIRED_COLS = ("Fronts", "Papers", "Citations", "xk", "myear")
RENAME = {"Fronts": "关键词", "Papers": "论文数", "Citations": "总被引",
          "xk": "学科", "myear": "年份中位"}

PAPER_THRESHOLD = 10    # 头部方向阈值(论文数)
SIM_THRESHOLD = 0.30    # 软对齐判定阈值(Jaccard)

_TAG_RE = re.compile(r"<[^>]+>")     # 关键词里的 <I>N</I> 之类 HTML 残留


# ---------- 小工具 ----------
def fmt_snap(name) -> str:
    """sheet 名 → 展示名:202503 → 2025-03。"""
    s = str(name).strip()
    if re.fullmatch(r"\d{6}", s):
        return f"{s[:4]}-{s[4:]}"
    if re.fullmatch(r"\d{8}", s):
        return f"{s[:4]}-{s[4:6]}-{s[6:]}"
    return s


def parse_kw(raw) -> frozenset:
    """「A;B;C」→ 归一化关键词集合(去标签、去空格、小写)。"""
    if not isinstance(raw, str):
        return frozenset()
    s = _TAG_RE.sub("", raw)
    parts = re.split(r"[;；]", s)
    return frozenset(p.strip().lower() for p in parts if p.strip())


def kw_label(s, n=60) -> str:
    """关键词串 → 短标签(取前 n 字符,用于下拉框/图例)。"""
    s = str(s).replace(";", " · ")
    return s if len(s) <= n else s[:n] + "…"


# ---------- 单期快照规范化 ----------
def _normalize_sheet(raw: pd.DataFrame) -> pd.DataFrame:
    df = raw.copy()
    df.columns = [str(c).strip() for c in df.columns]
    lower_map = {c.lower(): c for c in df.columns}
    missing = [c for c in REQUIRED_COLS if c.lower() not in lower_map]
    if missing:
        raise ValueError(f"工作表缺少列:{missing}(实际列:{list(df.columns)})")
    df = df.rename(columns={lower_map[c.lower()]: c for c in REQUIRED_COLS})
    df = df.rename(columns=RENAME)[list(RENAME.values())]

    df["论文数"] = pd.to_numeric(df["论文数"], errors="coerce")
    df["总被引"] = pd.to_numeric(df["总被引"], errors="coerce")
    df["年份中位"] = pd.to_numeric(df["年份中位"], errors="coerce")
    df = df.dropna(subset=["关键词", "论文数"])
    df = df[df["论文数"] > 0].reset_index(drop=True)

    df["kw_set"] = df["关键词"].map(parse_kw)
    df = df[df["kw_set"].map(len) > 0 ].reset_index(drop=True)
    df["篇均引用"] = df["总被引"] / df["论文数"]
    df["是否头部"] = df["论文数"] >= PAPER_THRESHOLD
    df["学科"] = df["学科"].map(lambda v: "" if pd.isna(v) else str(v).strip())
    return df


@st.cache_data(show_spinner="正在读取快照…")
def _load_snapshots(source, _tag: str = ""):
    """读 Excel(每 sheet 一期)→ 按名称排序的 {快照名: df}。"""
    if isinstance(source, (bytes, bytearray)):
        source = io.BytesIO(source)
    sheets = pd.read_excel(source, sheet_name=None, engine="openpyxl")
    data = {}
    for name, raw in sheets.items():
        try:
            data[fmt_snap(name)] = _normalize_sheet(raw)
        except ValueError as e:
            raise ValueError(f"工作表「{name}」:{e}")
    if not data:
        raise ValueError("Excel 里没有任何可用的工作表。")
    return dict(sorted(data.items()))


# ---------- 软对齐:倒排索引 + 贪心一对一 ----------
def _match_pass(df_a: pd.DataFrame, df_b: pd.DataFrame, threshold: float):
    """df_a 每行 → df_b 的最佳匹配。
    返回 (cands, best_sim, best_j):
      cands   = [(sim, i, j)] 所有 sim>=threshold 的候选对(贪心用)
      best_sim/best_j = 按行位置索引(与 RangeIndex 一致)"""
    inv = defaultdict(list)
    for j, kws in enumerate(df_b["kw_set"]):
        for k in kws:
            inv[k].append(j)
    nkw_b = df_b["kw_set"].map(len).tolist()

    cands = []
    best_sim = [0.0] * len(df_a)
    best_j = [-1] * len(df_a)
    for i, kws in enumerate(df_a["kw_set"]):
        cnt = Counter()
        for k in kws:
            cnt.update(inv.get(k, ()))
        ni = len(kws)
        for j, inter in cnt.items():
            sim = inter / (ni + nkw_b[j] - inter) if inter else 0.0
            if sim > best_sim[i]:
                best_sim[i], best_j[i] = sim, j
            if sim >= threshold:
                cands.append((sim, i, j))
    return cands, best_sim, best_j


def _greedy_pairs(cands, threshold: float):
    """按相似度降序贪心一对一配对,每个方向只配一次。"""
    used_i, used_j, pairs = set(), set(), []
    for sim, i, j in sorted(cands, reverse=True):
        if sim < threshold:
            break
        if i in used_i or j in used_j:
            continue
        used_i.add(i)
        used_j.add(j)
        pairs.append((i, j, sim))
    return pairs


# ---------- 跨期结构:分类 / 轨迹链 / meta ----------
def _build_alignment(snapshots: Dict[str, pd.DataFrame], snaps: List[str]):
    n = len(snaps)
    links = []
    vocab_overlap = [None] * n      # 与上一期的词汇 Jaccard(首期无)
    match_rates = [None] * n        # 上一期头部方向在本期能匹配上的比例

    for t in range(n):
        df = snapshots[snaps[t]]
        df["来源"] = "—(首期)" if t == 0 else ""
        df["去向"] = "—(末期)" if t == n - 1 else ""

    for t in range(n - 1):
        a, b = snapshots[snaps[t]], snapshots[snaps[t + 1]]
        _, best_ab, bj_ab = _match_pass(a, b, SIM_THRESHOLD)   # a→b
        _, best_ba, bj_ba = _match_pass(b, a, SIM_THRESHOLD)   # b→a

        # 期 t+1 方向的来源
        for j in range(len(b)):
            if best_ba[j] >= SIM_THRESHOLD:
                i = bj_ba[j]
                b.at[j, "来源"] = "延续" if a.at[i, "是否头部"] else "从长尾毕业"
            else:
                b.at[j, "来源"] = "全新出现"

        # 期 t 方向的去向
        for i in range(len(a)):
            if best_ab[i] >= SIM_THRESHOLD:
                j = bj_ab[i]
                a.at[i, "去向"] = "延续" if b.at[j, "是否头部"] else "退回长尾"
            else:
                a.at[i, "去向"] = "彻底消失"

        cands, _, _ = _match_pass(a, b, SIM_THRESHOLD)
        links.append({"a": snaps[t], "b": snaps[t + 1],
                      "pairs": _greedy_pairs(cands, SIM_THRESHOLD)})

        # 诊断指标:词汇重合率 + 头部匹配率
        va = set().union(*a["kw_set"])
        vb = set().union(*b["kw_set"])
        vocab_overlap[t + 1] = len(va & vb) / len(va | vb) if va | vb else None
        head_mask = a["是否头部"].tolist()
        sims = [s for s, m in zip(best_ab, head_mask) if m]
        match_rates[t + 1] = (sum(s >= SIM_THRESHOLD for s in sims) / len(sims)
                              if sims else None)

    # ---- 轨迹链:沿贪心边向后串,每个方向属于且仅属于一条轨迹 ----
    fwd = [{i: (j, s) for i, j, s in lk["pairs"]} for lk in links]
    traj_id_map = {}                                  # (期序号, 行号) -> traj_id
    traj_rows = []
    tid = 0
    for t in range(n):
        df = snapshots[snaps[t]]
        for i in range(len(df)):
            if (t, i) in traj_id_map:
                continue
            chain, cur, min_sim = [], (t, i), 1.0
            while True:
                tt, ii = cur
                chain.append(cur)
                traj_id_map[cur] = tid
                nxt = fwd[tt].get(ii) if tt < n - 1 else None
                if nxt is None:
                    break
                cur = (tt + 1, nxt[0])
                min_sim = min(min_sim, nxt[1])
            papers = [snapshots[snaps[tt]].at[ii, "论文数"] for tt, ii in chain]
            subs = [snapshots[snaps[tt]].at[ii, "学科"] for tt, ii in chain]
            traj_rows.append({
                "traj_id": tid,
                "起始期": snaps[chain[0][0]],
                "结束期": snaps[chain[-1][0]],
                "跨度期数": len(chain),
                "链上最低相似度": round(min_sim, 3),
                "累计论文数": int(sum(papers)),
                "峰值论文数": int(max(papers)),
                "学科": (pd.Series([s for s in subs if s]).mode().iat[0]
                         if any(subs) else ""),
                "首现关键词": snapshots[snaps[chain[0][0]]].at[chain[0][1], "关键词"],
                "最新关键词": snapshots[snaps[chain[-1][0]]].at[chain[-1][1], "关键词"],
            })
            tid += 1
    traj = pd.DataFrame(traj_rows)

    # traj_id 写回各快照 + 轨迹 × 快照 论文数宽表
    for t in range(n):
        df = snapshots[snaps[t]]
        df["traj_id"] = [traj_id_map.get((t, i), -1) for i in range(len(df))]
    tl = pd.DataFrame(0.0, index=traj["traj_id"], columns=snaps)
    for (t, i), k in traj_id_map.items():
        tl.at[k, snaps[t]] = snapshots[snaps[t]].at[i, "论文数"]
    tl = tl.mask(tl == 0.0)            # 缺席期 → NaN(论文数恒 > 0)
    return links, traj.set_index("traj_id"), tl, vocab_overlap, match_rates


def _build_meta(snapshots, snaps, vocab_overlap, match_rates) -> pd.DataFrame:
    rows = []
    for t, s in enumerate(snaps):
        d = snapshots[s]
        head = d[d["是否头部"]]
        rows.append({
            "快照": s,
            "方向数": len(d),
            "头部方向数": len(head),
            "长尾方向数": len(d) - len(head),
            "头部占比": round(len(head) / len(d), 3) if len(d) else None,
            "论文总量": int(d["论文数"].sum()),
            "词汇量": len(set().union(*d["kw_set"])),
            "与上期词汇重合率": (round(vocab_overlap[t], 3)
                                if vocab_overlap[t] is not None else None),
            "头部匹配率": (round(match_rates[t], 3)
                          if match_rates[t] is not None else None),
            "全新方向数": (int((d["来源"] == "全新出现").sum()) if t > 0 else None),
            "毕业方向数": (int((d["来源"] == "从长尾毕业").sum()) if t > 0 else None),
        })
    return pd.DataFrame(rows).set_index("快照")


# ---------- 汇总容器 ----------
@dataclass
class FrontsData:
    """一次加载的全部结构。pages 通过 session_state 拿到的就是它。"""
    snapshots: Dict[str, pd.DataFrame]
    snaps: List[str] = field(default_factory=list)
    links: list = field(default_factory=list)
    traj: pd.DataFrame = None
    traj_tl: pd.DataFrame = None
    meta: pd.DataFrame = None

    # ---- 兼容层:让通用基础设施能按 (snapshots, meta) 解包 ----
    def __iter__(self):
        yield self.snapshots
        yield self.meta


# ---------- 入口 ----------
def _resolve_source(path: str, release_url: str | None = None):
    """本地文件优先 → Release 下载 → 侧边栏上传兜底。返回 (source, tag) 或 None。"""
    if os.path.exists(path):
        return path, os.path.getmtime(path)
    if release_url and download_from_release(release_url, path):
        return path, os.path.getmtime(path)
    up = st.sidebar.file_uploader("上传「前沿方向」Excel 数据文件", type=["xlsx"],
                                  key="upload_fronts")
    if up is None:
        return None
    return up.getvalue(), len(up.getvalue())


@st.cache_data(show_spinner="正在读取 Excel 并进行软对齐…（可能需要数分钟）")
def _load_all(source, _tag: str):
    snapshots = _load_snapshots(source)
    snaps = list(snapshots.keys())
    links, traj, tl, vo, mr = _build_alignment(snapshots, snaps)
    meta = _build_meta(snapshots, snaps, vo, mr)
    return FrontsData(snapshots=snapshots, snaps=snaps, links=links,
                      traj=traj, traj_tl=tl, meta=meta)


def load_fronts_data(path: str, module_id: str,
                     release_url: str | None = None) -> FrontsData:
    src = _resolve_source(path, release_url)
    if src is None:
        st.info(f"未找到 `{path}`,请稍候自动下载完成,或在左侧上传 Excel"
                "(每张工作表一期快照,含 Fronts/Papers/Citations/xk/myear 五列)。")
        st.stop()
    result = _load_all(src[0], _tag=src[1])
    st.session_state[f"fronts_data_{module_id}"] = result
    return result          # app.py 解包时取 (snapshots, meta)