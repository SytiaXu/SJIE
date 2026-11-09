# -*- coding: utf-8 -*-
"""论文类观测 · 6 个页面。页面只认 ctx,不知道自己是热点还是高被引。"""
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from common.ui import style_fig, safe_slider
from common.registry import PageCtx
from .data import TOP_UNI_N

# ★ 默认主体:未手动调整筛选前,所有高校/省市相关控件默认选中这两项
DEFAULT_PROV = "江苏"
DEFAULT_UNI = "南京工业大学"


# ================= 页内私有小工具 =================
def _ensure_choice(key, options, prefer=None):
    """selectbox 防御:旧值/默认值不在当前选项里时,优先取 prefer,否则取首项。"""
    cur = st.session_state.get(key)
    if cur in options:
        return
    st.session_state[key] = (prefer if prefer in options else options[0]) if options else None


def _default_multi(key, options, prefer):
    """★ multiselect 默认值:首次进入时默认选中 prefer(过滤掉不在选项里的)。"""
    if key not in st.session_state:
        opts = set(options)
        st.session_state[key] = [p for p in prefer if p in opts]


def _clamp_range(key, lo_bound, hi_bound):
    """滑块 key 防御:范围越界时钳位(lo>hi 则整段重置)。"""
    cur = st.session_state.get(key)
    if cur is None:
        st.session_state[key] = (lo_bound, hi_bound)
    elif cur[0] < lo_bound or cur[1] > hi_bound:
        lo, hi = max(cur[0], lo_bound), min(cur[1], hi_bound)
        st.session_state[key] = (lo_bound, hi_bound) if lo > hi else (lo, hi)


def _snap_year_sidebar(ctx: PageCtx, page: str):
    """侧边栏:快照 + 年份(含切快照后的边界钳位),返回 (快照名, 该快照全量df, 年份区间)。"""
    k_snap, k_year = ctx.k(page, "snap"), ctx.k(page, "year")
    snap_names = list(ctx.snapshots.keys())

    if st.session_state.get(k_snap) not in snap_names:
        st.session_state[k_snap] = snap_names[-1]          # 默认最新一期
    snap = st.sidebar.selectbox("数据快照", snap_names, key=k_snap,
                                help="工作表名为数据时间点")
    df_all = ctx.snapshots[snap]
    st.caption(f"📄 {len(df_all):,} 篇 · {df_all['高校'].nunique()} 所高校 · "
               f"{df_all['省市'].nunique()} 省市 · {df_all['学科'].nunique()} 学科")

    y_min, y_max = int(df_all["年份"].min()), int(df_all["年份"].max())
    _clamp_range(k_year, y_min, y_max)
    year_range = st.sidebar.slider("发表年份", y_min, y_max, key=k_year)
    return snap, df_all, year_range


# ================= 📊 数据总览 =================
def render_overview(ctx: PageCtx):
    snap, df_all, yr = _snap_year_sidebar(ctx, "ov")
    with st.sidebar:
        st.divider()
        disc = st.multiselect("学科(留空 = 全部)", sorted(df_all["学科"].unique()),
                              key=ctx.k("ov", "disc"))
        prov_opts = sorted(df_all["省市"].unique())
        uni_opts = sorted(df_all["高校"].unique())
        _default_multi(ctx.k("ov", "prov"), prov_opts, [DEFAULT_PROV])   # ★
        prov = st.multiselect("省市(留空 = 全部)", prov_opts,
                              key=ctx.k("ov", "prov"))
        _default_multi(ctx.k("ov", "uni"), uni_opts, [DEFAULT_UNI])      # ★
        uni_f = st.multiselect("高校(留空 = 全部)", uni_opts,
                               key=ctx.k("ov", "uni"))
        st.divider()
        heat_n = safe_slider("热力图高校数量", int(df_all["高校"].nunique()), 50,
                             key=ctx.k("ov", "topn"))

    df = df_all[df_all["年份"].between(*yr)]
    if disc:   df = df[df["学科"].isin(disc)]
    if prov:   df = df[df["省市"].isin(prov)]
    if uni_f:  df = df[df["高校"].isin(uni_f)]
    if df.empty:
        st.warning("当前筛选条件下没有数据,请调整左侧筛选器。")
        return

    st.markdown(f"### 📊 数据总览 · {snap}")
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("论文总数", f"{len(df):,}")
    m2.metric("高校数", df["高校"].nunique())
    m3.metric("学科数", df["学科"].nunique())
    m4.metric("省市数", df["省市"].nunique())

    uni_total = df.groupby("高校")["论文ID"].count().sort_values(ascending=False)
    top_unis = uni_total.head(heat_n).index
    heat_df = df[df["高校"].isin(top_unis)]

    st.subheader("高校 × 学科 论文量热力图")
    heat = heat_df.pivot_table(index="高校", columns="学科", values="论文ID",
                               aggfunc="count", fill_value=0)
    heat = heat.reindex(index=top_unis).iloc[::-1]        # 上多下少,倒序后底部为第一名
    fig = go.Figure(go.Heatmap(
        z=heat.values, x=heat.columns, y=heat.index, colorscale="Turbo",
        hovertemplate="%{y}<br>%{x}<br>论文数:%{z}<extra></extra>"))
    fig.update_layout(margin=dict(l=10, r=10, t=10, b=140))
    style_fig(fig, height=max(480, 22 * len(heat)))
    fig.update_xaxes(tickangle=-45)
    st.plotly_chart(fig, width="stretch", key=ctx.k("ov", "heat"))

    c1, c2 = st.columns(2)
    with c1:
        t = df.groupby("学科")["论文ID"].count().sort_values(ascending=True)
        fig = px.bar(x=t.values, y=t.index, orientation="h",
                     labels={"x": "论文数", "y": ""}, title="学科总量榜")
        style_fig(fig, height=560)
        st.plotly_chart(fig, width="stretch", key=ctx.k("ov", "bar_disc"))
    with c2:
        t = df.groupby("省市")["论文ID"].count().sort_values(ascending=True)
        fig = px.bar(x=t.values, y=t.index, orientation="h",
                     labels={"x": "论文数", "y": ""}, title="省市总量榜")
        fig.update_traces(marker_color="#C89B3C")
        style_fig(fig, height=560)
        st.plotly_chart(fig, width="stretch", key=ctx.k("ov", "bar_prov"))


# ================= 🏫 高校主页 =================
def render_school(ctx: PageCtx):
    snap, df_all, yr = _snap_year_sidebar(ctx, "sc")
    ydf = df_all[df_all["年份"].between(*yr)]
    with st.sidebar:
        st.divider()
        prov_opts = sorted(ydf["省市"].unique())
        _default_multi(ctx.k("sc", "prov"), prov_opts, [])
        prov = st.multiselect("按省市缩小范围(留空 = 全部)",
                              prov_opts, key=ctx.k("sc", "prov"))
        pool = ydf[ydf["省市"].isin(prov)] if prov else ydf
        kw = st.text_input("关键字过滤高校", key=ctx.k("sc", "kw"),
                           help=f"留空则只列发文量前 {TOP_UNI_N} 的高校")
        if kw:
            opts = sorted(u for u in pool["高校"].unique() if kw in u)
        else:
            opts = sorted(pool["高校"].value_counts().head(TOP_UNI_N).index)
            # ★ 默认高校不在前 N 时,强制补进选项,保证能被默认选中
            if DEFAULT_UNI in set(pool["高校"].unique()) and DEFAULT_UNI not in opts:
                opts = sorted(opts + [DEFAULT_UNI])
        if not opts:
            st.info("没有匹配的高校,请调整左侧省市筛选或关键字。")
            return
        _ensure_choice(ctx.k("sc", "uni"), opts, prefer=DEFAULT_UNI)     # ★
        uni = st.selectbox("选择高校", opts, key=ctx.k("sc", "uni"))
        st.divider()
        d_uni = ydf[ydf["高校"] == uni]
        disc_opts = sorted(d_uni["学科"].unique())
        focus = None
        if disc_opts:
            _ensure_choice(ctx.k("sc", "focus"), disc_opts)
            focus = st.selectbox("学科下钻", disc_opts, key=ctx.k("sc", "focus"))

    st.markdown(f"### 🏫 {uni} · {snap} · {yr[0]}–{yr[1]}")
    disc_counts = d_uni.groupby("学科")["论文ID"].count()
    year_counts = d_uni.groupby("年份")["论文ID"].count()
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("论文总数", f"{len(d_uni):,}")
    m2.metric("覆盖学科数", f"{disc_counts.size} / {ydf['学科'].nunique()}")
    m3.metric("最高产学科", disc_counts.idxmax() if disc_counts.size else "—")
    m4.metric("发表峰值年份", int(year_counts.idxmax()) if year_counts.size else "—")

    c1, c2 = st.columns([3, 2])
    with c1:
        t = disc_counts.sort_values(ascending=True)
        fig = px.bar(x=t.values, y=t.index, orientation="h",
                     labels={"x": "论文数", "y": ""}, title="各学科论文数量")
        style_fig(fig)
        st.plotly_chart(fig, width="stretch", key=ctx.k("sc", "bar_disc"))
    with c2:
        fig = px.bar(x=year_counts.index.astype(str), y=year_counts.values,
                     labels={"x": "年份", "y": "论文数"}, title="逐年发文量")
        fig.update_traces(marker_color="#0E5E52")
        style_fig(fig)
        st.plotly_chart(fig, width="stretch", key=ctx.k("sc", "bar_year"))

    if focus is None or d_uni.empty:
        return
    st.subheader(f"学科下钻 · {focus}")
    d_focus = d_uni[d_uni["学科"] == focus]
    cc1, cc2 = st.columns([2, 3])
    with cc1:
        fy = (d_focus.groupby("年份")["论文ID"].count()
              .reindex(range(yr[0], yr[1] + 1), fill_value=0))
        fig = px.bar(x=fy.index.astype(str), y=fy.values,
                     labels={"x": "年份", "y": "论文数"},
                     title=f"{focus}(共 {len(d_focus):,} 篇)")
        fig.update_traces(marker_color="#C89B3C")
        style_fig(fig, height=320)
        st.plotly_chart(fig, width="stretch", key=ctx.k("sc", "bar_focus"))
    with cc2:
        st.dataframe(d_focus[["题名", "年份"]].sort_values("年份"),
                     width="stretch", height=320,
                     column_config={"题名": st.column_config.TextColumn("题名", width="large")})


# ================= 📚 学科主页 =================
def render_disc(ctx: PageCtx):
    snap, df_all, yr = _snap_year_sidebar(ctx, "dp")
    ydf = df_all[df_all["年份"].between(*yr)]
    with st.sidebar:
        st.divider()
        prov_opts = sorted(ydf["省市"].unique())
        _default_multi(ctx.k("dp", "prov"), prov_opts, [])
        prov = st.multiselect("省市(缩小高校对比范围,留空 = 全部)",
                              prov_opts, key=ctx.k("dp", "prov"))
        pool = ydf[ydf["省市"].isin(prov)] if prov else ydf
        disc_opts = sorted(pool["学科"].unique())
        if not disc_opts:
            st.info("当前省市筛选下没有数据。")
            return
        _ensure_choice(ctx.k("dp", "disc"), disc_opts)
        disc_pick = st.selectbox("选择学科", disc_opts, key=ctx.k("dp", "disc"))
        st.divider()
        n_uni = int(pool[pool["学科"] == disc_pick]["高校"].nunique())
        top_n = safe_slider("展示高校数量", n_uni, 30, key=ctx.k("dp", "topn"),
                            help="高校太多时图表会非常长,默认只看前 30")

    d = pool[pool["学科"] == disc_pick]
    st.markdown(f"### 📚 「{disc_pick}」· {snap} · {yr[0]}–{yr[1]}")

    uni_counts = d.groupby("高校")["论文ID"].count().sort_values(ascending=False)
    uni_rank = uni_counts.head(top_n).sort_values(ascending=True)
    fig = px.bar(x=uni_rank.values, y=uni_rank.index, orientation="h",
                 labels={"x": "论文数", "y": ""},
                 title=f"各高校论文量对比(前 {len(uni_rank)},共 {uni_counts.size} 所)")
    fig.update_traces(marker_color="#0E5E52")
    style_fig(fig, height=max(360, 26 * len(uni_rank)))
    st.plotly_chart(fig, width="stretch", key=ctx.k("dp", "bar_uni"))

    st.subheader("发文量前 6 高校 · 年度走势")
    top6 = uni_counts.head(6).index.tolist()
    trend = (d[d["高校"].isin(top6)]
             .groupby(["年份", "高校"])["论文ID"].count().reset_index(name="论文数"))
    fig = px.line(trend, x=trend["年份"].astype(str), y="论文数", color="高校", markers=True)
    style_fig(fig, height=380)
    st.plotly_chart(fig, width="stretch", key=ctx.k("dp", "line"))

    st.subheader("各省市论文量")
    t = d.groupby("省市")["论文ID"].count().sort_values(ascending=True)
    fig = px.bar(x=t.values, y=t.index, orientation="h",
                 labels={"x": "论文数", "y": ""}, title="省市分布")
    fig.update_traces(marker_color="#C89B3C")
    style_fig(fig, height=max(360, 26 * len(t)))
    st.plotly_chart(fig, width="stretch", key=ctx.k("dp", "bar_prov"))


# ================= 🗺️ 省市主页 =================
def render_prov(ctx: PageCtx):
    snap, df_all, yr = _snap_year_sidebar(ctx, "pv")
    ydf = df_all[df_all["年份"].between(*yr)]
    with st.sidebar:
        st.divider()
        disc = st.multiselect("学科(留空 = 全部)", sorted(ydf["学科"].unique()),
                              key=ctx.k("pv", "disc"))
        pool = ydf[ydf["学科"].isin(disc)] if disc else ydf
        prov_opts = sorted(pool["省市"].unique())
        if not prov_opts:
            st.info("当前学科筛选下没有数据。")
            return
        _ensure_choice(ctx.k("pv", "prov"), prov_opts, prefer=DEFAULT_PROV)  # ★
        prov_pick = st.selectbox("选择省市", prov_opts, key=ctx.k("pv", "prov"))
        st.divider()
        n_uni = int(pool[pool["省市"] == prov_pick]["高校"].nunique())
        top_n = safe_slider("展示高校数量", n_uni, 20, key=ctx.k("pv", "topn"))

    d = pool[pool["省市"] == prov_pick]
    year_counts = d.groupby("年份")["论文ID"].count()
    uni_counts = d.groupby("高校")["论文ID"].count().sort_values(ascending=False)

    st.markdown(f"### 🗺️ {prov_pick} · {snap} · {yr[0]}–{yr[1]}")
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("论文总数", f"{len(d):,}")
    m2.metric("高校数量", uni_counts.size)
    m3.metric("最高产高校", uni_counts.idxmax() if uni_counts.size else "—")
    m4.metric("发表峰值年份", int(year_counts.idxmax()) if year_counts.size else "—")

    c1, c2 = st.columns(2)
    with c1:
        rank = uni_counts.head(top_n).sort_values(ascending=True)
        fig = px.bar(x=rank.values, y=rank.index, orientation="h",
                     labels={"x": "论文数", "y": ""},
                     title=f"高校论文量(前 {len(rank)},共 {uni_counts.size} 所)")
        fig.update_traces(marker_color="#0E5E52")
        style_fig(fig, height=max(360, 26 * len(rank)))
        st.plotly_chart(fig, width="stretch", key=ctx.k("pv", "bar_uni"))
    with c2:
        t = d.groupby("学科")["论文ID"].count().sort_values(ascending=True)
        fig = px.bar(x=t.values, y=t.index, orientation="h",
                     labels={"x": "论文数", "y": ""}, title="学科分布")
        fig.update_traces(marker_color="#C89B3C")
        style_fig(fig, height=max(360, 26 * len(t)))
        st.plotly_chart(fig, width="stretch", key=ctx.k("pv", "bar_disc"))

    st.subheader("逐年发文量")
    fig = px.bar(x=year_counts.index.astype(str), y=year_counts.values,
                 labels={"x": "年份", "y": "论文数"})
    fig.update_traces(marker_color="#0E5E52")
    style_fig(fig, height=340)
    st.plotly_chart(fig, width="stretch", key=ctx.k("pv", "bar_year"))


# ================= 🔀 往期对比(不涉及高校/省市选择,无需改动) =================
def render_diff(ctx: PageCtx):
    st.caption("对比两期快照的**题名**集合差,展示“基准期 → 对比期”之间新增/消失的论文。")
    snap_names = list(ctx.snapshots.keys())
    k_a, k_b = ctx.k("df", "a"), ctx.k("df", "b")
    with st.sidebar:
        if st.session_state.get(k_a) not in snap_names:
            st.session_state[k_a] = snap_names[-2] if len(snap_names) >= 2 else snap_names[0]
        if st.session_state.get(k_b) not in snap_names:
            st.session_state[k_b] = snap_names[-1]
        snap_a = st.selectbox("基准时间", snap_names, key=k_a)
        snap_b = st.selectbox("对比时间", snap_names, key=k_b)
        st.divider()
        st.dataframe(ctx.meta, width='stretch')

    a, b = ctx.snapshots[snap_a], ctx.snapshots[snap_b]
    d_new = b[~b["题名"].isin(set(a["题名"]))]
    d_gone = a[~a["题名"].isin(set(b["题名"]))]

    st.markdown(f"### 🔀 {snap_a} → {snap_b}")
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("基准期论文数", f"{len(a):,}")
    m2.metric("对比期论文数", f"{len(b):,}")
    m3.metric("新增论文", f"{len(d_new):,}",
              delta=f"{(len(b) - len(a)) / len(a) * 100:+.1f}% 总量" if len(a) else "—")
    m4.metric("新增涉及高校", d_new["高校"].nunique() if len(d_new) else 0)

    if d_new.empty and d_gone.empty:
        st.info("两期题名集合完全一致,没有新增或消失的论文。")
        return

    if not d_new.empty:
        c1, c2, c3 = st.columns(3)
        with c1:
            t = d_new.groupby("高校")["论文ID"].count().sort_values(ascending=True).tail(15)
            fig = px.bar(x=t.values, y=t.index, orientation="h",
                         labels={"x": "新增论文数", "y": ""}, title="新增 · 高校分布(前 15)")
            fig.update_traces(marker_color="#0E5E52")
            style_fig(fig, height=480)
            st.plotly_chart(fig, width="stretch", key=ctx.k("df", "bar_uni"))
        with c2:
            t = d_new.groupby("省市")["论文ID"].count().sort_values(ascending=True)
            fig = px.bar(x=t.values, y=t.index, orientation="h",
                         labels={"x": "新增论文数", "y": ""}, title="新增 · 省市分布")
            fig.update_traces(marker_color="#C89B3C")
            style_fig(fig, height=480)
            st.plotly_chart(fig, width="stretch", key=ctx.k("df", "bar_prov"))
        with c3:
            t = d_new.groupby("学科")["论文ID"].count().sort_values(ascending=True)
            fig = px.bar(x=t.values, y=t.index, orientation="h",
                         labels={"x": "新增论文数", "y": ""}, title="新增 · 学科分布")
            fig.update_traces(marker_color="#0E5E52")
            style_fig(fig, height=480)
            st.plotly_chart(fig, width="stretch", key=ctx.k("df", "bar_disc"))

        st.subheader("新增论文明细")
        st.dataframe(d_new[["题名", "高校", "省市", "学科", "年份"]]
                     .sort_values(["高校", "学科"]),
                     width="stretch", height=360,
                     column_config={"题名": st.column_config.TextColumn("题名", width="large")})
        st.download_button("导出新增论文(CSV)",
                           d_new.to_csv(index=False).encode("utf-8-sig"),
                           f"{ctx.module.id}_new_{snap_a}_{snap_b}.csv", "text/csv",
                           key=ctx.k("df", "csv_new"))

    if not d_gone.empty:
        with st.expander(f"基准期有、对比期消失的论文({len(d_gone):,} 篇)"):
            st.dataframe(d_gone[["题名", "高校", "省市", "学科", "年份"]]
                         .sort_values(["高校", "学科"]),
                         width="stretch", height=300,
                         column_config={"题名": st.column_config.TextColumn("题名", width="large")})
            st.download_button("导出消失论文(CSV)",
                               d_gone.to_csv(index=False).encode("utf-8-sig"),
                               f"{ctx.module.id}_gone_{snap_a}_{snap_b}.csv", "text/csv",
                               key=ctx.k("df", "csv_gone"))


# ================= 📈 时间轴 =================
def render_timeline(ctx: PageCtx):
    st.caption("选定一个主体(高校 / 学科),勾选参与对比的快照,观察其随时间的变化。")
    panel = pd.concat([d.assign(快照=name) for name, d in ctx.snapshots.items()],
                      ignore_index=True)

    # ---- 侧边栏:年份 / 快照集合 / 视角 ----
    k_year = ctx.k("tl", "year")
    g_min, g_max = int(panel["年份"].min()), int(panel["年份"].max())
    _clamp_range(k_year, g_min, g_max)
    with st.sidebar:
        tl_year = st.slider("发表年份(覆盖全部快照)", g_min, g_max, key=k_year)
        panel = panel[panel["年份"].between(*tl_year)]

        all_snaps = sorted(panel["快照"].unique())
        k_snaps = ctx.k("tl", "snaps")
        if not st.session_state.get(k_snaps):
            st.session_state[k_snaps] = all_snaps
        sel_snaps = st.multiselect("参与对比的快照", all_snaps, key=k_snaps)
        if len(sel_snaps) < 2:
            st.info("请至少选择两期快照进行对比。")
            return
        snap_axis = [s for s in all_snaps if s in sel_snaps]   # 保持时间顺序
        panel = panel[panel["快照"].isin(snap_axis)]

        view = st.radio("分析视角", ["高校 → 各学科", "学科 → 各高校"],
                        key=ctx.k("tl", "view"))

    # ---- 主区域:主体选择(分析对象,不是筛选)----
    if view == "高校 → 各学科":
        ent_opts = sorted(panel["高校"].value_counts().head(TOP_UNI_N).index)
        # ★ 默认高校不在前 N 时强制补进选项
        if DEFAULT_UNI in set(panel["高校"].unique()) and DEFAULT_UNI not in ent_opts:
            ent_opts = sorted(ent_opts + [DEFAULT_UNI])
        if not ent_opts:
            st.info("当前条件下没有高校数据。")
            return
        _ensure_choice(ctx.k("tl", "ent"), ent_opts, prefer=DEFAULT_UNI)  # ★
        entity = st.selectbox("选择高校", ent_opts, key=ctx.k("tl", "ent"))
        sub = panel[panel["高校"] == entity]
        sel_dims = st.multiselect("学科(留空 = 全部)", sorted(sub["学科"].unique()),
                                  key=ctx.k("tl", "dims"))
        if sel_dims:
            sub = sub[sub["学科"].isin(sel_dims)]
        dim_col = "学科"
    else:
        disc_opts = sorted(panel["学科"].unique())
        if not disc_opts:
            st.info("当前条件下没有学科数据。")
            return
        _ensure_choice(ctx.k("tl", "ent"), disc_opts)
        entity = st.selectbox("选择学科", disc_opts, key=ctx.k("tl", "ent"))
        sub = panel[panel["学科"] == entity]

        uni_tot = sub.groupby("高校")["论文ID"].count().sort_values(ascending=False)
        k_unis = ctx.k("tl", "unis")
        if k_unis not in st.session_state:
            # 首次进入默认选中论文量前 20 所
            st.session_state[k_unis] = list(uni_tot.head(20).index)
        chosen = st.multiselect(
            f"自选高校(共 {uni_tot.size} 所可选)",
            list(uni_tot.index), key=k_unis)
        if not chosen:
            st.info("请至少选择一所高校进行展示。")
            return
        sub = sub[sub["高校"].isin(chosen)]
        dim_col = "高校"

    mat = sub.pivot_table(index=dim_col, columns="快照", values="论文ID",
                          aggfunc="count", fill_value=0)
    mat = mat.reindex(columns=snap_axis, fill_value=0)
    if mat.empty:
        st.info(f"「{entity}」在当前条件下没有数据。")
        return

    totals = mat.sum(axis=1).sort_values(ascending=False)
    mat_plot = mat.loc[totals.index].iloc[::-1]   # 热力图仍按论文量排序,倒序显示

    st.markdown(f"### 📈 {entity} · 时间轴")
    m1, m2, m3 = st.columns(3)
    m1.metric("论文总量(所选快照合计)", f"{int(mat.values.sum()):,}")
    m2.metric(f"覆盖{dim_col}数", mat.shape[0])
    m3.metric("最近所选快照论文量", f"{int(mat[snap_axis[-1]].sum()):,}")

    st.subheader(f"{dim_col} × 快照 热力图")
    fig = go.Figure(go.Heatmap(
        z=mat_plot.values, x=list(mat_plot.columns), y=list(mat_plot.index),
        colorscale="Turbo",
        hovertemplate="%{y}<br>%{x}<br>论文数:%{z}<extra></extra>"))
    fig.update_layout(margin=dict(l=10, r=10, t=10, b=30))
    fig.update_xaxes(type="category")
    style_fig(fig, height=max(360, 26 * len(mat_plot)))
    st.plotly_chart(fig, width="stretch", key=ctx.k("tl", "heat"))

    # 折线图:展示全部选中的主体,按论文量排序
    mat_top = mat.loc[totals.index]   # 保留变量名,后面不用改;就是全量
    st.subheader(f"全部 {len(mat_top)} 个{dim_col} · 逐期走势")
    long_df = (mat_top.T.reset_index()
               .melt(id_vars="快照", var_name=dim_col, value_name="论文数"))
    fig = px.line(long_df, x="快照", y="论文数", color=dim_col,
                  markers=True, labels={"论文数": "论文数"})
    fig.update_xaxes(type="category", categoryorder="array",
                     categoryarray=list(mat.columns))
    style_fig(fig, height=420)
    st.plotly_chart(fig, width="stretch", key=ctx.k("tl", "line"))

    with st.expander("查看 / 导出明细数据表"):
        st.dataframe(mat, width="stretch")
        st.download_button("导出时间轴数据(CSV)",
                           mat.to_csv().encode("utf-8-sig"),
                           f"{ctx.module.id}_timeline_{entity}.csv", "text/csv",
                           key=ctx.k("tl", "csv"))
