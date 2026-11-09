# -*- coding: utf-8 -*-
"""南工大论文透视 · 7 个页面。

数据访问约定:完整双域数据(NJTechData)由 load() 存入 session_state,
页面通过 _data(ctx) 取回;ctx.snapshots / ctx.meta 仅为主域(高被引)。
"""
import re
from collections import Counter
from itertools import combinations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from common.registry import PageCtx
from common.ui import style_fig, safe_slider
from .data import NJTechData, split_multi

_NOTE_RE = re.compile(r"\s*[(（][^()（）]*[)）]\s*$")
_MISSING = {"", "nan", "none", "null", "/", "-"}

DOM_H, DOM_T = "📌 高被引", "🔥 热点"


# ================= 数据访问 & 页内小工具 =================
def _explode_colleges(df: pd.DataFrame) -> pd.DataFrame:
    """一行一篇论文 -> 一行一个学院(每篇论文每个单位只计一次)。"""
    if df.empty:
        return df.iloc[0:0]          # 保留列结构的空表
    rows = []
    for _, r in df.iterrows():
        colleges = [c for c in (c.strip() for c in re.split(r"[;；,，]", str(r["学院"])))
                    if c and c.lower() not in _MISSING]
        for c in dict.fromkeys(colleges):        # 去重且保序
            rows.append({**r.to_dict(), "学院": c})
    return pd.DataFrame(rows)


def _strip_note(name: str) -> str:
    """去掉作者名尾部括注:'张三(通讯)' -> '张三'。中英文括号都处理。"""
    return _NOTE_RE.sub("", str(name)).strip()

def _data(ctx: PageCtx) -> NJTechData:
    d = st.session_state.get(f"njtech_data_{ctx.module.id}")
    if d is None:                      # 防御:正常流程 load() 先于页面执行
        st.error("数据未加载,请刷新页面。")
        st.stop()
    return d


def _parts(data: NJTechData, dom: str):
    """按榜单类型取 (snapshots, meta, snaps, timeline, paper_info)。"""
    if dom == DOM_H:
        return (data.highly, data.meta_highly, data.snaps_highly,
                data.timeline_highly, data.paper_info_highly)
    return (data.hot, data.meta_hot, data.snaps_hot,
            data.timeline_hot, data.paper_info_hot)


def _ensure_choice(key, options, prefer=None):
    cur = st.session_state.get(key)
    if cur in options:
        return
    st.session_state[key] = (prefer if prefer in options else options[0]) if options else None


def _clamp_range(key, lo_bound, hi_bound):
    cur = st.session_state.get(key)
    if cur is None:
        st.session_state[key] = (lo_bound, hi_bound)
    elif cur[0] < lo_bound or cur[1] > hi_bound:
        lo, hi = max(cur[0], lo_bound), min(cur[1], hi_bound)
        st.session_state[key] = (lo_bound, hi_bound) if lo > hi else (lo, hi)


def _dom_pick(ctx: PageCtx, page: str) -> str:
    return st.sidebar.radio("数据榜单", [DOM_H, DOM_T],
                            key=ctx.k(page, "dom"), horizontal=True)


def _snap_year(ctx: PageCtx, page: str, snaps, snapshots):
    """快照选择(默认最新一期)+ 发表年份滑块,返回 (快照名, 全量df, 年份区间)。"""
    k = ctx.k(page, "snap")
    if st.session_state.get(k) not in snaps:
        st.session_state[k] = snaps[-1]
    snap = st.sidebar.selectbox("数据快照", snaps, key=k)
    df_all = snapshots[snap]
    cited = int(df_all["被引"].sum(skipna=True))
    st.caption(f"📄 {len(df_all):,} 篇 · {df_all['学科'].nunique()} 学科 · "
               f"{df_all['刊名'].nunique()} 期刊 · 总被引 {cited:,}")
    ys = df_all["年份"].dropna()
    if ys.empty:
        return snap, df_all, (None, None)
    y_min, y_max = int(ys.min()), int(ys.max())
    _clamp_range(ctx.k(page, "year"), y_min, y_max)
    yr = st.sidebar.slider("发表年份", y_min, y_max, key=ctx.k(page, "year"))
    return snap, df_all, yr


def _in_year(df: pd.DataFrame, yr) -> pd.DataFrame:
    if yr[0] is None:
        return df
    return df[df["年份"].between(*yr)]


def _college_filter(df: pd.DataFrame, sel) -> pd.DataFrame:
    """按学院筛选:论文挂的任一学院命中即保留。"""
    if not sel:
        return df
    sel = set(sel)
    return df[df["学院"].map(lambda s: bool(set(split_multi(s)) & sel))]


def _explode(df: pd.DataFrame) -> pd.DataFrame:
    """一行一篇论文 -> 一行一位作者(净名,无括注);学院按位置对齐。"""
    if df.empty:
        return df.iloc[0:0]          # 保留列结构的空表
    rows = []
    for _, r in df.iterrows():
        authors = [_strip_note(a) for a in re.split(r"[;；]", str(r["作者"]))]
        authors = [a for a in authors if a and a.lower() not in _MISSING]
        colleges = [c for c in (c.strip() for c in re.split(r"[;；]", str(r["学院"])))
                    if c and c.lower() not in _MISSING]
        if not authors:
            continue

        # —— 错位策略 ——
        if len(colleges) == len(authors):        # 数量一致:位置对齐(最可靠)
            pair = colleges
        elif len(colleges) == 1:                 # 单单位:广播给所有作者(最常见)
            pair = colleges * len(authors)
        elif len(colleges) > len(authors):       # 单位多于作者:截断,避免凭空造空值
            pair = colleges[:len(authors)]
        else:                                    # 单位多于 1 且少于作者:无法对齐 → 留空
            pair = colleges + [""] * (len(authors) - len(colleges))

        for a, c in zip(authors, pair):
            rows.append({**r.to_dict(), "作者": a, "学院": c})
    return pd.DataFrame(rows)


def _paper_table(df: pd.DataFrame, height: int = 360):
    st.dataframe(df[["题名", "学院", "学科", "刊名", "年份", "被引"]],
                 width="stretch", height=height,
                 column_config={"题名": st.column_config.TextColumn("题名", width="large")})


def _dual_axis_fig(tl: pd.DataFrame, key: str):
    """双轴时间轴:柱 = 在榜论文数,线 = 总被引。"""
    from plotly.subplots import make_subplots
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_bar(x=tl["快照"], y=tl["论文数"], name="在榜论文数",
                marker_color="#0E5E52")
    fig.add_scatter(x=tl["快照"], y=tl["总被引"], name="总被引",
                    mode="lines+markers",
                    line=dict(color="#C89B3C", width=3), secondary_y=True)
    fig.update_yaxes(title_text="论文数", secondary_y=False)
    fig.update_yaxes(title_text="总被引", secondary_y=True)
    fig.update_layout(legend=dict(orientation="h", y=1.15),
                      margin=dict(l=10, r=10, t=50, b=10),
                      hovermode="x unified")
    style_fig(fig, height=400)
    st.plotly_chart(fig, width="stretch", key=key)


def _io_rank_fig(tl: pd.DataFrame, io_key: str, rank_key: str, rank_title: str):
    """左:每期新进榜/退出榜柱状图;右:排名折线(y 轴反转)。"""
    c1, c2 = st.columns(2)
    with c1:
        if tl["新增"].notna().any():
            t2 = tl.dropna(subset=["新增"])
            fig = px.bar(t2, x="快照", y=["新增", "退出"], barmode="group",
                         title="每期新进榜 / 退出榜 论文数",
                         color_discrete_sequence=["#0E5E52", "#C0C0C0"])
            style_fig(fig, height=300)
            st.plotly_chart(fig, width="stretch", key=io_key)
    with c2:
        if "排名" in tl.columns:
            fig = px.line(tl, x="快照", y="排名", markers=True, title=rank_title)
            fig.update_yaxes(autorange="reversed")
            style_fig(fig, height=300)
            st.plotly_chart(fig, width="stretch", key=rank_key)


# ================= 📊 数据总览(当前快照全景) =================
def render_overview(ctx: PageCtx):
    data = _data(ctx)
    dom = _dom_pick(ctx, "ov")
    snapshots, meta, snaps, _, _ = _parts(data, dom)
    snap, df_all, yr = _snap_year(ctx, "ov", snaps, snapshots)
    df = _in_year(df_all, yr)
    if df.empty:
        st.warning("当前筛选条件下没有数据,请调整左侧筛选器。")
        return

    st.markdown(f"### 📊 数据总览 · {dom} · {snap}")
    top_cited = df.loc[df["被引"].idxmax()] if df["被引"].notna().any() else None
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("论文总数", f"{len(df):,}")
    m2.metric("总被引", f"{int(df['被引'].sum(skipna=True)):,}")
    m3.metric("篇均被引", f"{df['被引'].mean():.1f}")
    m4.metric("最高单篇被引", f"{int(top_cited['被引']):,}" if top_cited is not None else "—")

    # ---- 两榜规模走势(全历史,各自快照轴) ----
    st.subheader("入榜规模走势(全部快照)")
    fig = go.Figure()
    for m, name, color in ((data.meta_highly, "高被引论文数", "#0E5E52"),
                           (data.meta_hot, "热点论文数", "#C89B3C")):
        fig.add_trace(go.Scatter(x=list(m.index), y=m["论文数"], name=name,
                                 mode="lines+markers", line=dict(color=color)))
    fig.update_xaxes(type="category")
    style_fig(fig, height=340)
    st.plotly_chart(fig, width="stretch", key=ctx.k("ov", "line_size"))

    c1, c2 = st.columns(2)
    with c1:
        st.subheader("学科 · 数量 × 影响力(当前快照)")
        g = (df.groupby("学科")
               .agg(论文数=("题名", "count"), 总被引=("被引", "sum"),
                    篇均被引=("被引", "mean")).reset_index())
        fig = px.scatter(g, x="论文数", y="篇均被引", size="总被引", color="学科",
                         hover_name="学科", size_max=40)
        style_fig(fig, height=420)
        st.plotly_chart(fig, width="stretch", key=ctx.k("ov", "bub"))
    with c2:
        st.subheader("发表年分布(当前快照)")
        t = df.groupby("年份")["题名"].count()
        fig = px.bar(x=t.index.astype(str), y=t.values,
                     labels={"x": "发表年", "y": "论文数"})
        fig.update_traces(marker_color="#0E5E52")
        style_fig(fig, height=420)
        st.plotly_chart(fig, width="stretch", key=ctx.k("ov", "bar_year"))

    st.subheader("被引频次分布(当前快照)")
    cited_s = df["被引"].dropna()
    if cited_s.empty:
        st.info("本期快照没有可用的被引数值。")
    else:
        fig = px.histogram(x=cited_s, nbins=30, labels={"x": "被引频次", "y": "论文数"})
        style_fig(fig, height=300)
        st.plotly_chart(fig, width="stretch", key=ctx.k("ov", "hist"))

    # ================= 🏢 学院透视(当前快照) =================
    ex_all = _explode_colleges(df)
    col_opts = sorted(c for c in ex_all["学院"].unique() if c)
    if not col_opts:
        st.info("当前条件下没有学院数据。")
    else:
        with st.sidebar:
            st.divider()
            sel = st.multiselect("学院(留空 = 全部)", col_opts, key=ctx.k("ov", "col"))
            top_n = safe_slider("图表展示学院数量", len(col_opts), 15,
                                key=ctx.k("ov", "topn"))

        df_c = _college_filter(df, sel)
        ex = _explode_colleges(df_c)
        ex = ex[ex["学院"] != ""]           # 兜底:无单位的论文不计入学院排行

        # ---- 三口径排行 ----
        st.subheader("🏢 学院透视(当前快照)")
        metric_kind = st.radio("排行口径", ["论文数", "总被引", "篇均被引"],
                               key=ctx.k("ov", "kind"), horizontal=True)
        if metric_kind == "论文数":
            g = ex.groupby("学院")["题名"].nunique()      # nunique 双保险
        elif metric_kind == "总被引":
            g = ex.groupby("学院")["被引"].sum()
        else:
            g = ex.groupby("学院")["被引"].mean()
        g = g.sort_values(ascending=False)
        t = g.head(top_n).sort_values(ascending=True)
        fig = px.bar(x=t.values, y=t.index, orientation="h",
                     labels={"x": metric_kind, "y": ""},
                     title=f"学院{metric_kind}(前 {len(t)},共 {len(g)} 个)")
        fig.update_traces(marker_color="#0E5E52")
        style_fig(fig, height=max(360, 26 * len(t)))
        st.plotly_chart(fig, width="stretch", key=ctx.k("ov", "bar"))

        # ---- 学院 × 学科热力图 ----
        top_cols = g.head(top_n).index
        heat = (ex[ex["学院"].isin(top_cols)]
                .pivot_table(index="学院", columns="学科", values="题名",
                             aggfunc="count", fill_value=0)
                .reindex(index=top_cols).iloc[::-1])
        st.subheader("学院 × 学科 热力图(当前快照)")
        fig = go.Figure(go.Heatmap(z=heat.values, x=heat.columns, y=heat.index,
                                   colorscale="Turbo",
                                   hovertemplate="%{y}<br>%{x}<br>论文数:%{z}<extra></extra>"))
        fig.update_layout(margin=dict(l=10, r=10, t=10, b=140))
        fig.update_xaxes(tickangle=-45)
        style_fig(fig, height=max(420, 24 * len(heat)))
        st.plotly_chart(fig, width="stretch", key=ctx.k("ov", "heat"))

        # ---- 学院合作共现矩阵 ----
        st.subheader("学院合作共现(当前快照)")
        pairs = Counter()
        for lst in df_c["学院"].map(split_multi):
            cs = sorted(set(lst) - {""})
            for a, b in combinations(cs, 2):
                pairs[(a, b)] += 1
        if pairs:
            mat = pd.DataFrame(0, index=top_cols, columns=top_cols)
            for (a, b), v in pairs.items():
                if a in mat.index and b in mat.columns:
                    mat.loc[a, b] = mat.loc[b, a] = v
            fig = go.Figure(go.Heatmap(z=mat.values, x=mat.columns, y=mat.index,
                                       colorscale="Blues",
                                       hovertemplate="%{y} × %{x}<br>合作论文:%{z}<extra></extra>"))
            fig.update_layout(margin=dict(l=10, r=10, t=10, b=140))
            fig.update_xaxes(tickangle=-45)
            style_fig(fig, height=max(420, 24 * len(mat)))
            st.plotly_chart(fig, width="stretch", key=ctx.k("ov", "co"))
        else:
            st.info("当前筛选下没有跨学院合作的论文。")

    # ================= 👤 作者透视(当前快照) =================
    exa = _explode(df)
    if exa.empty:
        st.info("当前条件下没有作者数据。")
        return
    # 同一作者同一篇只算一次(_explode 是论文×作者粒度)
    exu = exa.drop_duplicates(subset=["作者", "title_key"])

    g = (exu.groupby("作者")
             .agg(论文数=("title_key", "nunique"),
                  总被引=("被引", "sum"),
                  篇均被引=("被引", "mean"),
                  合作学院数=("学院", lambda s: s[s != ""].nunique()))
             .sort_values(["论文数", "总被引"], ascending=False))

    with st.sidebar:
        st.divider()
        au_topn = safe_slider("图表展示作者数量", len(g), 15,
                              key=ctx.k("ov", "autopn"))
    st.subheader("👤 作者透视(当前快照)")
    c1, c2, c3 = st.columns(3)
    c1.metric("上榜作者数", f"{len(g):,}")
    c2.metric("人均上榜论文", f"{g['论文数'].mean():.2f}" if len(g) else "—")
    c3.metric("被引最高作者", g["总被引"].idxmax() if len(g) else "—")

    kind = st.radio("排行口径", ["论文数", "总被引", "篇均被引"],
                    key=ctx.k("ov", "aukind"), horizontal=True)
    t = g[kind].head(au_topn).sort_values(ascending=True)
    fig = px.bar(x=t.values, y=t.index, orientation="h",
                 labels={"x": kind, "y": ""},
                 title=f"作者{kind}(前 {len(t)},共 {len(g)} 人)")
    fig.update_traces(marker_color="#0E5E52")
    style_fig(fig, height=max(360, 26 * len(t)))
    st.plotly_chart(fig, width="stretch", key=ctx.k("ov", "aubar"))

    # ---- 作者详情(当前快照) ----
    who_opts = list(g.index)
    _ensure_choice(ctx.k("ov", "who"), who_opts, prefer=g.index[0])
    who = st.selectbox("选择作者查看详情(当前快照)", who_opts, key=ctx.k("ov", "who"))
    if who:
        keys = exu.loc[exu["作者"] == who, "title_key"]
        papers = df[df["title_key"].isin(keys)]
        cols = exu.loc[exu["作者"] == who, "学院"]
        cols = cols[cols != ""]
        main_col = cols.value_counts().idxmax() if len(cols) else "—"

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("上榜论文", f"{g.loc[who, '论文数']:.0f}")
        m2.metric("总被引", f"{g.loc[who, '总被引']:.0f}")
        m3.metric("篇均被引", f"{g.loc[who, '篇均被引']:.1f}")
        m4.metric("主要学院", main_col)

        st.dataframe(papers[["题名", "作者", "学院", "学科", "刊名", "年份", "被引"]]
                     .sort_values("被引", ascending=False, na_position="last"),
                     width="stretch", height=320,
                     column_config={
                         "题名": st.column_config.TextColumn("题名", width="large"),
                         "作者": st.column_config.TextColumn("作者", width="medium"),
                         "学院": st.column_config.TextColumn("学院", width="medium")})

    st.caption("💡 全时间轴视角请前往「🏢 学院主页」「👤 作者主页」。")


# ================= 🧪 学科主页 =================
def render_disc(ctx: PageCtx):
    data = _data(ctx)
    dom = _dom_pick(ctx, "dp")
    snapshots, meta, snaps, timeline, info = _parts(data, dom)
    snap, df_all, yr = _snap_year(ctx, "dp", snaps, snapshots)
    ydf = _in_year(df_all, yr)
    disc_opts = sorted(ydf["学科"].unique())
    if not disc_opts:
        st.warning("当前条件下没有学科数据。")
        return
    _ensure_choice(ctx.k("dp", "disc"), disc_opts)
    disc = st.sidebar.selectbox("选择学科", disc_opts, key=ctx.k("dp", "disc"))

    d = ydf[ydf["学科"] == disc]
    st.markdown(f"### 🧪 「{disc}」· {dom} · {snap} · 对应发表年份 {yr[0]}–{yr[1]}")
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("论文数", f"{len(d):,}")
    m2.metric("总被引", f"{int(d['被引'].sum(skipna=True)):,}")
    m3.metric("篇均被引", f"{d['被引'].mean():.1f}" if len(d) else "—")
    m4.metric("覆盖期刊", d["刊名"].nunique())

    # ---- 学科引用积累曲线(全历史,含当前筛选外的该学科论文) ----
    keys = info.loc[info["学科"] == disc, "title_key"]
    sub_tl = timeline.reindex(keys)
    if not sub_tl.empty:
        st.subheader(f"{disc}论文池 · 被引总量积累(共追踪 {len(keys)} 篇曾入榜论文)")
        acc = sub_tl.sum()                       # 不在榜按 0 计入
        onlist = sub_tl.notna().sum()
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=list(acc.index), y=acc.values, name="被引总量",
                                 mode="lines+markers", line=dict(color="#0E5E52")))
        fig.add_trace(go.Scatter(x=list(onlist.index), y=onlist.values, name="在榜论文数",
                                 mode="lines+markers", yaxis="y2",
                                 line=dict(color="#C89B3C")))
        fig.update_layout(yaxis=dict(title="被引总量"),
                          yaxis2=dict(title="在榜论文数", overlaying="y", side="right"))
        fig.update_xaxes(type="category")
        style_fig(fig, height=380)
        st.plotly_chart(fig, width="stretch", key=ctx.k("dp", "line_acc"))

    c1, c2 = st.columns(2)
    with c1:
        t = d.groupby("刊名")["被引"].sum().sort_values(ascending=True).tail(15)
        fig = px.bar(x=t.values, y=t.index, orientation="h",
                     labels={"x": "总被引", "y": ""}, title="发文期刊(按总被引,前 15)")
        fig.update_traces(marker_color="#0E5E52")
        style_fig(fig, height=440)
        st.plotly_chart(fig, width="stretch", key=ctx.k("dp", "bar_jr"))
    with c2:
        t = d["被引"].dropna()
        fig = px.box(y=t, labels={"y": "被引频次"}, title="被引分布箱线图")
        style_fig(fig, height=440)
        st.plotly_chart(fig, width="stretch", key=ctx.k("dp", "box"))

    st.subheader(f"被引 TOP 20 论文({yr[0]}–{yr[1]})")
    _paper_table(d.sort_values("被引", ascending=False).head(20))


# ================= 🏢 学院主页(全时间轴) =================
def render_college(ctx: PageCtx):
    data = _data(ctx)
    dom = _dom_pick(ctx, "cg")
    snapshots, meta, snaps, _, info = _parts(data, dom)
    snap, df_all, yr = _snap_year(ctx, "cg", snaps, snapshots)

    # 学院选项:全期论文池并集(覆盖所有快照曾入榜论文)
    info_y = _in_year(info, yr)
    ex_info0 = _explode_colleges(info_y)
    col_counts = ex_info0[ex_info0["学院"] != ""] \
        .groupby("学院")["题名"].nunique().sort_values(ascending=False)
    col_opts = list(col_counts.index)

    if not col_opts:
        st.warning("当前条件下没有学院数据。")
        return
    with st.sidebar:
        st.divider()
        top_n = safe_slider("图表展示学院数量", len(col_opts), 15,
                            key=ctx.k("cg", "topn"))

    # ---- 📈 单学院全期趋势 ----
    _ensure_choice(ctx.k("au", "col"), col_opts)
    tl_col = st.selectbox("选择学院", col_opts, key=ctx.k("cg", "tl_col"))
    st.markdown(f"### 🏢 「{tl_col}」· 全时间轴 · {dom} · 对应发表年份 {yr[0]}–{yr[1]}")

    # 预计算:各快照 explode 后的表(趋势 / 热力图模块复用)
    exploded = []
    for s in snaps:
        e = _explode_colleges(_in_year(snapshots[s], yr))
        e = e[e["学院"] != ""]
        exploded.append((s, e))

    rows, disc_rows = [], []
    prev, union_titles, onlist_cnt = None, set(), 0
    for s, e in exploded:
        cnt_all = e.groupby("学院")["题名"].nunique()      # 全院计数,用于排名
        sub = e[e["学院"] == tl_col]
        cur = set(sub["title_key"])
        cited = sub["被引"].sum()
        rank = (cnt_all.rank(ascending=False, method="min").get(tl_col)
                if tl_col in cnt_all.index else None)

        rows.append({
            "快照": s,
            "论文数": len(cur),
            "总被引": cited,
            "篇均被引": cited / len(cur) if cur else 0.0,
            "新增": len(cur - prev) if prev is not None else None,
            "退出": len(prev - cur) if prev is not None else None,
            "排名": rank,
            "学院总数": int((cnt_all > 0).sum()),
        })
        for d, n in sub.groupby("学科")["题名"].nunique().items():
            disc_rows.append({"快照": s, "学科": d, "论文数": n})
        union_titles |= cur
        onlist_cnt += 1 if cur else 0
        prev = cur

    tl = pd.DataFrame(rows)

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("曾入榜论文(全期去重)", f"{len(union_titles):,}")
    m2.metric("在榜期数", f"{onlist_cnt} / {len(snaps)}")
    m3.metric("最新期论文数", int(tl.iloc[-1]["论文数"]))
    m4.metric("最新期校内排名",
              f"第 {int(tl.iloc[-1]['排名'])} / {int(tl.iloc[-1]['学院总数'])}"
              if pd.notna(tl.iloc[-1]["排名"]) else "未入榜")

    _dual_axis_fig(tl, ctx.k("cg", "tl_main"))
    _io_rank_fig(tl, ctx.k("cg", "tl_io"), ctx.k("cg", "tl_rank"),
                 "校内排名(按论文数,越靠上越强)")

    # 学科结构演变(堆叠面积,Top 8 学科 + 其他)
    dl = pd.DataFrame(disc_rows)
    if not dl.empty:
        top_disc = (dl.groupby("学科")["论文数"].sum()
                    .sort_values(ascending=False).head(8).index)
        dl["学科"] = dl["学科"].where(dl["学科"].isin(top_disc), "其他")
        dl = dl.groupby(["快照", "学科"], as_index=False)["论文数"].sum()
        fig = px.area(dl, x="快照", y="论文数", color="学科",
                      category_orders={"快照": snaps},
                      title=f"「{tl_col}」学科结构演变(按在榜论文数)")
        style_fig(fig, height=340)
        st.plotly_chart(fig, width="stretch", key=ctx.k("cg", "tl_disc"))

    # ---- 👤 学院高产作者(全期) ----
    st.subheader(f"👤 「{tl_col}」高产作者(全期)")
    per_snap_author = {}      # 作者 -> {快照: 论文数}
    union_pairs = set()       # (作者, title_key) 全期去重
    for s in snaps:
        d = _college_filter(_in_year(snapshots[s], yr), [tl_col])
        if d.empty:
            continue
        e = _explode(d).drop_duplicates(subset=["作者", "title_key"])
        if e.empty:
            continue
        for a, grp in e.groupby("作者"):
            per_snap_author.setdefault(a, {})[s] = int(grp["title_key"].nunique())
        union_pairs |= set(zip(e["作者"], e["title_key"]))

    if not per_snap_author:
        st.info("该学院在筛选条件下没有可统计的作者。")
        return
    alltime = Counter(a for a, _ in union_pairs)
    top_a = [a for a, _ in alltime.most_common(12)]

    c1, c2 = st.columns([1, 2])
    with c1:
        t = pd.Series({a: alltime[a] for a in top_a}).sort_values(ascending=True)
        fig = px.bar(x=t.values, y=t.index, orientation="h",
                     labels={"x": "全期论文数(去重)", "y": ""},
                     title=f"TOP {len(t)} 作者")
        fig.update_traces(marker_color="#0E5E52")
        style_fig(fig, height=max(360, 26 * len(t)))
        st.plotly_chart(fig, width="stretch", key=ctx.k("cg", "aubar"))
    with c2:
        hm = pd.DataFrame([[per_snap_author.get(a, {}).get(s, 0) for s in snaps]
                           for a in top_a],
                          index=top_a, columns=snaps).iloc[::-1]
        fig = go.Figure(go.Heatmap(z=hm.values, x=list(hm.columns), y=hm.index,
                                   colorscale="Greens",
                                   hovertemplate="%{y}<br>%{x}<br>论文数:%{z}<extra></extra>"))
        fig.update_layout(margin=dict(l=10, r=10, t=40, b=140))
        fig.update_xaxes(tickangle=-45)
        style_fig(fig, height=max(360, 26 * len(hm)))
        st.plotly_chart(fig, width="stretch", key=ctx.k("cg", "auheat"))
    st.caption("左:全期累计入榜论文数(每篇只计一次);右:每位作者各快照在榜论文数。")

    # ---- 🔥 学院 × 快照 热力图 ----
    st.subheader("学院 × 快照 热力图(在榜论文数)")
    mat = pd.DataFrame({s: e.groupby("学院")["题名"].nunique()
                        for s, e in exploded}).fillna(0)
    order = mat.sum(axis=1).sort_values(ascending=False).head(top_n).index
    mat = mat.loc[order].iloc[::-1]                 # 强者在上,时间从左到右
    fig = go.Figure(go.Heatmap(z=mat.values, x=list(mat.columns), y=mat.index,
                               colorscale="Turbo",
                               hovertemplate="%{y}<br>%{x}<br>论文数:%{z}<extra></extra>"))
    fig.update_layout(margin=dict(l=10, r=10, t=10, b=140))
    fig.update_xaxes(tickangle=-45)
    style_fig(fig, height=max(420, 24 * len(mat)))
    st.plotly_chart(fig, width="stretch", key=ctx.k("cg", "heat"))
    st.caption("每格 = 该学院当期在榜论文数(去重);只统计发表年份在筛选区间内的论文。")

    # ---- 🤝 学院合作共现(全期,论文池去重) ----
    st.subheader("学院合作共现(全期曾入榜论文)")
    ex_info = _explode_colleges(info_y)
    cnt_alltime = ex_info.groupby("学院")["题名"].nunique().sort_values(ascending=False)
    top_cols = cnt_alltime.head(top_n).index

    pairs = Counter()
    for lst in info_y["学院"].map(split_multi):
        cs = sorted(set(lst) - {""})
        for a, b in combinations(cs, 2):
            pairs[(a, b)] += 1
    if pairs:
        mat = pd.DataFrame(0, index=top_cols, columns=top_cols)
        for (a, b), v in pairs.items():
            if a in mat.index and b in mat.columns:
                mat.loc[a, b] = mat.loc[b, a] = v
        fig = go.Figure(go.Heatmap(z=mat.values, x=mat.columns, y=mat.index,
                                   colorscale="Blues",
                                   hovertemplate="%{y} × %{x}<br>合作论文:%{z}<extra></extra>"))
        fig.update_layout(margin=dict(l=10, r=10, t=10, b=140))
        fig.update_xaxes(tickangle=-45)
        style_fig(fig, height=max(420, 24 * len(mat)))
        st.plotly_chart(fig, width="stretch", key=ctx.k("cg", "co"))
        st.caption("以论文池为口径,每篇论文全期只计一次。")
    else:
        st.info("当前筛选下没有跨学院合作的论文。")


# ================= 👤 作者主页(全时间轴) =================
def render_authors(ctx: PageCtx):
    data = _data(ctx)
    dom = _dom_pick(ctx, "au")
    snapshots, meta, snaps, _, info = _parts(data, dom)
    snap, df_all, yr = _snap_year(ctx, "au", snaps, snapshots)
    info_y = _in_year(info, yr)

    # 预计算:各快照作者表(论文×作者去重)
    per_snap = []
    for s in snaps:
        e = _explode(_in_year(snapshots[s], yr)) \
              .drop_duplicates(subset=["作者", "title_key"])
        per_snap.append((s, e))

    # 全期作者统计(去重计数用于排序;逐快照计数用于热力图)
    seen = set()
    au_alltime = Counter()
    au_per_snap = {}          # 作者 -> {快照: 论文数}
    for s, e in per_snap:
        if e.empty:
            continue
        for a, tk in zip(e["作者"], e["title_key"]):
            if (a, tk) not in seen:
                seen.add((a, tk))
                au_alltime[a] += 1
        for a, grp in e.groupby("作者"):
            au_per_snap.setdefault(a, {})[s] = int(grp["title_key"].nunique())

    # 候选作者 = 当期快照的上榜作者(当期排行见「📊 数据总览」)
    cur_snap = dict(per_snap).get(snap, pd.DataFrame())
    if cur_snap.empty:
        who_opts = []
    else:
        who_opts = (cur_snap.groupby("作者")["title_key"].nunique()
                    .sort_values(ascending=False).index.tolist())

    if not who_opts:
        st.warning("当前条件下没有作者数据。")
        return
    _ensure_choice(ctx.k("au", "who"), who_opts)
    who = st.selectbox("选择作者", who_opts, key=ctx.k("au", "who"))

    with st.sidebar:
        st.divider()
        au_topn = safe_slider("热力图展示作者数量", len(au_alltime), 15,
                              key=ctx.k("au", "topn"))

    st.markdown(f"### 👤 「{who}」· 全时间轴 · {dom} · 对应发表年份 {yr[0]}–{yr[1]}")

    # ---- 📈 单作者全期趋势 ----
    rows, prev = [], None
    union_keys = set()
    paper_authors = {}        # title_key -> 全部作者(跨快照汇总)
    for s, e in per_snap:
        gsub = e.groupby("作者").agg(论文数=("title_key", "nunique"),
                                     总被引=("被引", "sum"))
        cur_keys = set(e.loc[e["作者"] == who, "title_key"])
        cited = float(gsub.loc[who, "总被引"]) if who in gsub.index else 0.0
        rank = (gsub["论文数"].rank(ascending=False, method="min").get(who)
                if who in gsub.index else None)
        for tk, grp in e.groupby("title_key"):
            paper_authors.setdefault(tk, set()).update(grp["作者"])
        co = set()
        for p in cur_keys:
            co |= paper_authors.get(p, set()) - {who}
        rows.append({
            "快照": s,
            "论文数": len(cur_keys),
            "总被引": cited,
            "篇均被引": cited / len(cur_keys) if cur_keys else 0.0,
            "新增": len(cur_keys - prev) if prev is not None else None,
            "退出": len(prev - cur_keys) if prev is not None else None,
            "排名": rank,
            "总人数": len(gsub),
            "合作者数": len(co),
        })
        union_keys |= cur_keys
        prev = cur_keys
    tl = pd.DataFrame(rows)

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("曾入榜论文(全期去重)", f"{len(union_keys):,}")
    m2.metric("在榜期数", f"{int((tl['论文数'] > 0).sum())} / {len(snaps)}")
    m3.metric("最新期论文数", int(tl.iloc[-1]["论文数"]))
    m4.metric("最新期全校排名",
              f"第 {int(tl.iloc[-1]['排名'])} / {int(tl.iloc[-1]['总人数'])}"
              if pd.notna(tl.iloc[-1]["排名"]) else "未入榜")

    _dual_axis_fig(tl, ctx.k("au", "tl_main"))
    _io_rank_fig(tl, ctx.k("au", "tl_io"), ctx.k("au", "tl_rank"),
                 "全校排名(按论文数,越靠上越强)")

    c1, c2 = st.columns(2)
    with c1:
        fig = px.bar(tl, x="快照", y="合作者数",
                     title="当期合作者数(在榜论文涉及,去重)",
                     color_discrete_sequence=["#C89B3C"])
        style_fig(fig, height=300)
        st.plotly_chart(fig, width="stretch", key=ctx.k("au", "tl_co"))
    with c2:
        fig = px.line(tl, x="快照", y="篇均被引", markers=True,
                      title="篇均被引(全期)")
        style_fig(fig, height=300)
        st.plotly_chart(fig, width="stretch", key=ctx.k("au", "tl_avg"))

    # ---- 🤝 全期合作伙伴 ----
    partners = Counter()
    for p in union_keys:
        for a in paper_authors.get(p, set()) - {who}:
            partners[a] += 1
    st.subheader(f"🤝 「{who}」全期合作伙伴 TOP 20")
    if partners:
        t = pd.Series(dict(partners.most_common(20))).sort_values(ascending=True)
        fig = px.bar(x=t.values, y=t.index, orientation="h",
                     labels={"x": "合作论文数(全期去重)", "y": ""})
        fig.update_traces(marker_color="#C89B3C")
        style_fig(fig, height=max(360, 26 * len(t)))
        st.plotly_chart(fig, width="stretch", key=ctx.k("au", "partner"))
    else:
        st.info("该作者在筛选条件下没有合作者(或均为独著)。")

    # ---- 📄 全期入榜论文明细 ----
    st.subheader(f"📄 「{who}」全期入榜论文明细(共 {len(union_keys):,} 篇)")
    papers = info_y[info_y["title_key"].isin(union_keys)]
    if not papers.empty:
        st.dataframe(papers[["题名", "学院", "学科", "刊名", "年份",
                             "被引", "在榜期数", "首次入榜快照"]]
                     .sort_values("在榜期数", ascending=False, na_position="last"),
                     width="stretch", height=380,
                     column_config={
                         "题名": st.column_config.TextColumn("题名", width="large"),
                         "学院": st.column_config.TextColumn("学院", width="medium")})
        st.download_button("导出该作者全期论文",
                           papers.to_csv(index=False).encode("utf-8-sig"),
                           f"author_{who}_alltime.csv", "text/csv",
                           key=ctx.k("au", "csv"))

    # ---- 🔥 高产作者 × 快照 热力图 ----
    st.subheader("高产作者 × 快照 热力图(在榜论文数)")
    top_a = [a for a, _ in au_alltime.most_common(au_topn)]
    hm = pd.DataFrame([[au_per_snap.get(a, {}).get(s, 0) for s in snaps]
                       for a in top_a],
                      index=top_a, columns=snaps).iloc[::-1]
    fig = go.Figure(go.Heatmap(z=hm.values, x=list(hm.columns), y=hm.index,
                               colorscale="Viridis",
                               hovertemplate="%{y}<br>%{x}<br>论文数:%{z}<extra></extra>"))
    fig.update_layout(margin=dict(l=10, r=10, t=10, b=140))
    fig.update_xaxes(tickangle=-45)
    style_fig(fig, height=max(420, 24 * len(hm)))
    st.plotly_chart(fig, width="stretch", key=ctx.k("au", "heat"))
    st.caption("按全期累计在榜论文数(去重)排序;每格 = 该作者当期在榜论文数(发表年份在筛选区间内)。")



# ================= 🕸️ 作者合作网络 =================
def render_network(ctx: PageCtx):
    data = _data(ctx)
    dom = _dom_pick(ctx, "nw")
    snapshots, meta, snaps, timeline, info = _parts(data, dom)
    snap, df_all, yr = _snap_year(ctx, "nw", snaps, snapshots)
    ydf = _in_year(df_all, yr)

    ex = _explode(ydf).drop_duplicates(subset=["作者", "title_key"])
    # 边表:同一篇论文内净名两两配对
    edges = Counter()
    for _, grp in ex.groupby("title_key"):
        names = sorted(set(grp["作者"]) - {""})
        for a, b in combinations(names, 2):
            edges[(a, b)] += 1
    if not edges:
        st.warning("当前条件下没有合作论文(上榜论文需至少有两位作者)。")
        return

    max_w = max(edges.values())
    with st.sidebar:
        min_w = safe_slider("最少合作次数(过滤弱连接)", max_w, min(2, max_w),
                            key=ctx.k("nw", "minw"))
    strong = {e: w for e, w in edges.items() if w >= min_w}
    if not strong:
        st.warning("当前阈值下没有合作边,请调低。")
        return

    # ---- 度数指标(手算)----
    partners: dict = {}
    for a, b in strong:
        partners.setdefault(a, set()).add(b)
        partners.setdefault(b, set()).add(a)
    deg = (pd.DataFrame([(n, len(p), sum(strong[tuple(sorted((n, q)))] for q in p))
                         for n, p in partners.items()],
                        columns=["作者", "合作伙伴数", "总合作次数"])
             .sort_values(["总合作次数", "合作伙伴数"], ascending=False))

    st.markdown(f"### 🕸️ 作者合作网络 · {dom} · {snap} · {yr[0]}–{yr[1]}")
    m1, m2, m3 = st.columns(3)
    m1.metric("作者节点数", f"{len(deg):,}")
    m2.metric("合作边数", f"{len(strong):,}")
    m3.metric("最高合作次数", max(strong.values()))

    tab1, tab2 = st.tabs(["🔗 高频合作对 TOP 30", "⭐ 核心枢纽作者 TOP 30"])
    with tab1:
        pairs_df = (pd.DataFrame([{"作者 A": a, "作者 B": b, "合作次数": w}
                                  for (a, b), w in strong.items()])
                    .sort_values("合作次数", ascending=False).head(30))
        st.dataframe(pairs_df, width="stretch", hide_index=True)
    with tab2:
        st.dataframe(deg.head(30), width="stretch", hide_index=True)

    # ---- 网络图 ----
    nodes = sorted({n for e in strong for n in e})
    try:
        import networkx as nx            # 仅用于力导向布局,可选
        G = nx.Graph()
        for (a, b), w in strong.items():
            G.add_edge(a, b, weight=w)
        pos = nx.spring_layout(G, k=1.4 / len(G) ** 0.5, seed=42, weight="weight")
    except ImportError:                  # 无 networkx:圆形布局兜底
        import math
        pos = {n: (math.cos(2 * math.pi * i / len(nodes)),
                   math.sin(2 * math.pi * i / len(nodes)))
               for i, n in enumerate(nodes)}

    ex_, ey_, etxt, ew = [], [], [], []
    for (a, b), w in strong.items():
        ex_ += [pos[a][0], pos[b][0], None]
        ey_ += [pos[a][1], pos[b][1], None]
        etxt += [f"{a} × {b}<br>合作 {w} 次", "", ""]
        ew += [w, w, 1]
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=ex_, y=ey_, mode="lines", text=etxt,
                             hoverinfo="text", opacity=0.35,
                             line=dict(color="#0E5E52")))
    deg_map = deg.set_index("作者")["合作伙伴数"].to_dict()
    fig.add_trace(go.Scatter(
        x=[pos[n][0] for n in nodes], y=[pos[n][1] for n in nodes],
        mode="markers+text", text=nodes, textposition="top center",
        textfont=dict(size=9),
        marker=dict(size=[10 + 4 * deg_map.get(n, 1) for n in nodes],
                    color="#0E5E52", opacity=0.85, line=dict(width=0)),
        hovertemplate="%{text}<br>合作伙伴数:%{marker.size}<extra></extra>"))
    fig.update_layout(showlegend=False, margin=dict(l=10, r=10, t=10, b=10),
                      xaxis=dict(visible=False), yaxis=dict(visible=False))
    st.plotly_chart(fig, width="stretch", key=ctx.k("nw", "graph"))
    st.caption("节点大小 ∝ 合作伙伴数,悬停查看合作对详情。有 networkx 时为力导向布局,否则为圆形布局。")


# ================= 📰 期刊主页 =================
def render_journal(ctx: PageCtx):
    data = _data(ctx)
    dom = _dom_pick(ctx, "jr")
    snapshots, meta, snaps, _, _ = _parts(data, dom)
    snap, df_all, yr = _snap_year(ctx, "jr", snaps, snapshots)
    df = _in_year(df_all, yr)
    jr_opts = sorted(df["刊名"].unique())
    if not jr_opts:
        st.warning("当前条件下没有期刊数据。")
        return
    with st.sidebar:
        jr_sel = st.multiselect("期刊(留空 = 全部)", jr_opts, key=ctx.k("jr", "sel"))
        top_n = safe_slider("展示期刊数量", len(jr_opts), 20, key=ctx.k("jr", "topn"))
    if jr_sel:
        df = df[df["刊名"].isin(jr_sel)]

    st.markdown(f"### 📰 期刊主页 · {dom} · {snap}")
    kind = st.radio("排行口径", ["论文数", "总被引"], key=ctx.k("jr", "kind"),
                    horizontal=True)
    if kind == "论文数":
        g = df.groupby("刊名")["题名"].count()
    else:
        g = df.groupby("刊名")["被引"].sum()
    t = g.sort_values(ascending=False).head(top_n).sort_values(ascending=True)
    fig = px.bar(x=t.values, y=t.index, orientation="h",
                 labels={"x": kind, "y": ""},
                 title=f"期刊{kind}(前 {len(t)},共 {len(g)} 种)")
    fig.update_traces(marker_color="#0E5E52")
    style_fig(fig, height=max(380, 26 * len(t)))
    st.plotly_chart(fig, width="stretch", key=ctx.k("jr", "bar"))

    top_jrs = g.sort_values(ascending=False).head(top_n).index
    heat = (df[df["刊名"].isin(top_jrs)]
            .pivot_table(index="刊名", columns="学科", values="题名",
                         aggfunc="count", fill_value=0))
    st.subheader("期刊 × 学科 热力图")
    fig = go.Figure(go.Heatmap(z=heat.values, x=heat.columns, y=heat.index,
                               colorscale="Turbo",
                               hovertemplate="%{y}<br>%{x}<br>论文数:%{z}<extra></extra>"))
    fig.update_layout(margin=dict(l=10, r=10, t=10, b=140))
    fig.update_xaxes(tickangle=-45)
    style_fig(fig, height=max(420, 24 * len(heat)))
    st.plotly_chart(fig, width="stretch", key=ctx.k("jr", "heat"))

    st.subheader("各期刊被引分布(箱线图)")
    sub = df[df["刊名"].isin(top_jrs) & df["被引"].notna()]
    if not sub.empty:
        order = (sub.groupby("刊名")["被引"].median().sort_values().index.tolist())
        fig = px.box(sub, x="刊名", y="被引", category_orders={"刊名": order})
        fig.update_xaxes(tickangle=-45)
        style_fig(fig, height=420)
        st.plotly_chart(fig, width="stretch", key=ctx.k("jr", "box"))
    else:
        st.info("没有可用的被引数值。")


# ================= 📈 引用动态 =================
def render_citation(ctx: PageCtx):
    data = _data(ctx)
    dom = _dom_pick(ctx, "ct")
    snapshots, meta, snaps, timeline, info = _parts(data, dom)

    # ---- 单篇生命周期 ----
    st.subheader("单篇论文 · 引用生命周期")
    kw = st.text_input("按题名关键字搜索论文", key=ctx.k("ct", "kw"))
    pool = info
    if kw:
        pool = info[info["题名"].str.contains(kw, case=False, na=False)]
    else:                                   # 无关键字时默认列被引最高的前 300 篇
        pool = info.sort_values("被引", ascending=False).head(300)
    if pool.empty:
        st.info("没有匹配的论文,请更换关键字。")
        return
    _ensure_choice(ctx.k("ct", "paper"), pool["题名"].tolist())
    title = st.selectbox("选择论文", pool["题名"].tolist(), key=ctx.k("ct", "paper"))
    row = pool[pool["题名"] == title].iloc[0]

    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("最新被引", f"{int(row['被引']):,}" if pd.notna(row["被引"]) else "—")
    m2.metric("首次入榜", row["首次入榜快照"])
    m3.metric("最近在榜", row["最近在榜快照"])
    m4.metric("在榜期数", f"{int(row['在榜期数'])} / {len(snaps)}")
    m5.metric("发表年", row["年份"])

    tl_row = timeline.loc[row["title_key"]]
    fig = go.Figure(go.Scatter(
        x=list(tl_row.index), y=tl_row.values, mode="lines+markers",
        connectgaps=False,               # 不在榜的期次断线,入榜/出榜一目了然
        line=dict(color="#0E5E52"),
        hovertemplate="%{x}<br>被引:%{y}<extra></extra>"))
    fig.update_xaxes(type="category")
    style_fig(fig, height=320)
    st.plotly_chart(fig, width="stretch", key=ctx.k("ct", "life"))
    st.caption("断线处 = 该期快照未入榜。")

    # ---- 两期引用增速榜 ----
    st.divider()
    st.subheader("两期对比 · 引用增速榜")
    k_a, k_b = ctx.k("ct", "a"), ctx.k("ct", "b")
    with st.sidebar:
        st.divider()
        if st.session_state.get(k_a) not in snaps:
            st.session_state[k_a] = snaps[-2] if len(snaps) >= 2 else snaps[0]
        if st.session_state.get(k_b) not in snaps:
            st.session_state[k_b] = snaps[-1]
        if snaps.index(st.session_state[k_a]) >= snaps.index(st.session_state[k_b]):
            st.session_state[k_a], st.session_state[k_b] = \
                st.session_state[k_b], st.session_state[k_a]
        snap_a = st.selectbox("基准期", snaps, key=k_a)
        snap_b = st.selectbox("对比期", snaps, key=k_b)
        disc_f = st.multiselect("学科过滤(留空 = 全部)",
                                sorted(info["学科"].unique()), key=ctx.k("ct", "disc"))

    a = timeline[snap_a]
    b = timeline[snap_b]
    delta = (pd.DataFrame({"被引_基准": a, "被引_对比": b})
             .fillna(0).assign(增量=lambda d: d["被引_对比"] - d["被引_基准"])
             .join(info.set_index("title_key")[["题名", "学科", "学院", "刊名", "年份"]]))
    if disc_f:
        delta = delta[delta["学科"].isin(disc_f)]

    m1, m2, m3 = st.columns(3)
    m1.metric("两期均入榜", f"{int(((a.notna()) & (b.notna())).sum()):,}")
    m2.metric("新增入榜", f"{int((a.isna() & b.notna()).sum()):,}")
    m3.metric("掉出榜单", f"{int((a.notna() & b.isna()).sum()):,}")

    t = delta.sort_values("增量", ascending=False).head(20).iloc[::-1]
    fig = px.bar(x=t["增量"], y=t["题名"], orientation="h",
                 labels={"x": f"被引增量({snap_a} → {snap_b})", "y": ""},
                 title="引用增速 TOP 20")
    fig.update_traces(marker_color="#0E5E52")
    style_fig(fig, height=max(400, 30 * len(t)))
    st.plotly_chart(fig, width="stretch", key=ctx.k("ct", "bar_delta"))

    st.subheader("增量明细(前 100)")
    show = (delta.sort_values("增量", ascending=False).head(100)
            .reset_index()[["题名", "学科", "学院", "刊名", "年份",
                            "被引_基准", "被引_对比", "增量"]])
    st.dataframe(show, width="stretch", height=380,
                 column_config={"题名": st.column_config.TextColumn("题名", width="large")})
    st.download_button("导出全部增量数据",
                       delta.reset_index().to_csv(index=False).encode("utf-8-sig"),
                       f"citation_delta_{snap_a}_{snap_b}.csv", "text/csv",
                       key=ctx.k("ct", "csv"))


# ================= 🔀 高被引 × 热点 =================
def render_overlap(ctx: PageCtx):
    data = _data(ctx)
    common = [s for s in data.snaps_highly if s in data.hot]
    if not common:
        st.error("两个 Excel 没有同名的快照工作表,无法做双榜交叉分析。")
        return
    k = ctx.k("ol", "snap")
    if st.session_state.get(k) not in common:
        st.session_state[k] = common[-1]
    snap = st.sidebar.selectbox("数据快照(两榜共有)", common, key=k)
    st.sidebar.divider()
    st.sidebar.dataframe(data.meta_highly, width="stretch")

    dh = data.highly[snap]
    dt = data.hot[snap]
    keys_h, keys_t = set(dh["title_key"]), set(dt["title_key"])
    both = keys_h & keys_t

    st.markdown(f"### 🔀 高被引 × 热点 · {snap}")
    m1, m2, m3 = st.columns(3)
    m1.metric("仅高被引", f"{len(keys_h - keys_t):,}")
    m2.metric("仅热点", f"{len(keys_t - keys_h):,}")
    m3.metric("双榜论文", f"{len(both):,}",
              delta=f"占高被引 {len(both) / len(keys_h):.1%}" if keys_h else "—")

    # ---- 结构差异对比 ----
    c1, c2 = st.columns(2)
    for col, (frame, keys, name, color) in zip(
            (c1, c2),
            ((dh, keys_h, "高被引", "#0E5E52"), (dt, keys_t, "热点", "#C89B3C"))):
        with col:
            t = frame.groupby("学科")["题名"].count().sort_values(ascending=True).tail(15)
            fig = px.bar(x=t.values, y=t.index, orientation="h",
                         labels={"x": "论文数", "y": ""}, title=f"{name} · 学科分布")
            fig.update_traces(marker_color=color)
            style_fig(fig, height=440)
            st.plotly_chart(fig, width="stretch",
                            key=ctx.k("ol", f"bar_{name}"))

    # ---- 双榜论文明细 ----
    st.subheader(f"双榜论文明细({len(both):,} 篇)")
    d_both = (dh[dh["title_key"].isin(both)]
              .merge(dt[["title_key", "被引"]].rename(columns={"被引": "热点榜被引"}),
                     on="title_key", how="left")
              .rename(columns={"被引": "高被引榜被引"}))
    st.dataframe(d_both[["题名", "学院", "学科", "刊名", "年份",
                         "高被引榜被引"]]
                 .sort_values("高被引榜被引", ascending=False),
                 width="stretch", height=420,
                 column_config={"题名": st.column_config.TextColumn("题名", width="large")})
    st.download_button("导出双榜论文",
                       d_both.to_csv(index=False).encode("utf-8-sig"),
                       f"overlap_{snap}.csv", "text/csv", key=ctx.k("ol", "csv"))


# ================= 📄 论文明细 =================
def render_papers(ctx: PageCtx):
    data = _data(ctx)
    dom = _dom_pick(ctx, "pp")
    snapshots, meta, snaps, timeline, info = _parts(data, dom)
    snap, df_all, yr = _snap_year(ctx, "pp", snaps, snapshots)
    df = _in_year(df_all, yr)

    with st.sidebar:
        st.divider()
        disc = st.multiselect("学科", sorted(df["学科"].dropna().unique()),
                              key=ctx.k("pp", "disc"))
        col_opts = sorted(c for c in _explode_colleges(df)["学院"].unique() if c)
        col_sel = st.multiselect("学院(挂任一即中)", col_opts, key=ctx.k("pp", "col"))
        jr = st.multiselect("期刊", sorted(df["刊名"].dropna().unique()),
                            key=ctx.k("pp", "jr"))
        kw = st.text_input("题名/作者关键字", key=ctx.k("pp", "kw"))

    if disc:  df = df[df["学科"].isin(disc)]
    if jr:    df = df[df["刊名"].isin(jr)]
    df = _college_filter(df, col_sel)
    if kw:
        mask = df["题名"].str.contains(kw, case=False, na=False) | \
               df["作者"].str.contains(kw, case=False, na=False)
        df = df[mask]
    if df.empty:
        st.warning("当前筛选条件下没有论文。")
        return

    # 附上跨期信息(在榜期数)
    df = df.merge(info[["title_key", "在榜期数", "首次入榜快照"]],
                  on="title_key", how="left")

    st.markdown(f"### 📄 论文明细 · {dom} · {snap} · 共 {len(df):,} 篇")
    st.dataframe(df[["题名", "学院", "作者", "学科", "刊名", "年份", "被引",
                     "在榜期数", "首次入榜快照"]]
                 .sort_values("被引", ascending=False, na_position="last"),
                 width="stretch", height=560,
                 column_config={
                     "题名": st.column_config.TextColumn("题名", width="large"),
                     "学院": st.column_config.TextColumn("学院", width="medium"),
                     "作者": st.column_config.TextColumn("作者", width="medium")})
    st.download_button("导出当前筛选结果",
                       df.to_csv(index=False).encode("utf-8-sig"),
                       f"papers_{snap}.csv", "text/csv", key=ctx.k("pp", "csv"))