# -*- coding: utf-8 -*-
"""前沿方向透视 · 5 个页面。

数据访问约定:完整数据(FrontsData)由 load() 存入 session_state,
页面通过 _data(ctx) 取回;ctx.snapshots / ctx.meta 为兼容层同款。
"""
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from common.registry import PageCtx
from common.ui import style_fig, safe_slider
from .data import (FrontsData, PAPER_THRESHOLD, SIM_THRESHOLD,
                   _match_pass, kw_label)

MAIN, ACCENT = "#0E5E52", "#C89B3C"
SRC_COLORS = {"延续": MAIN, "从长尾毕业": ACCENT, "全新出现": "#C44E52",
              "—(首期)": "#888888"}


# ================= 数据访问 & 页内小工具 =================
def _data(ctx: PageCtx) -> FrontsData:
    d = st.session_state.get(f"fronts_data_{ctx.module.id}")
    if d is None:
        st.error("数据未加载,请刷新页面。")
        st.stop()
    return d


def _snap_pick(ctx: PageCtx, page: str, data: FrontsData) -> str:
    """快照选择(默认最新一期),返回快照名。"""
    k = ctx.k(page, "snap")
    if st.session_state.get(k) not in data.snaps:
        st.session_state[k] = data.snaps[-1]
    return st.sidebar.selectbox("数据快照", data.snaps, key=k)


def _ensure_choice(key, options, prefer=None):
    cur = st.session_state.get(key)
    if cur in options:
        return
    st.session_state[key] = (prefer if prefer in options else options[0]) if options else None


def _head(df: pd.DataFrame) -> pd.DataFrame:
    return df[df["是否头部"]]


def _classify_pair(df_a: pd.DataFrame, df_b: pd.DataFrame):
    """任意两期对比(不要求相邻)。
    返回 (src_list, dest_list, best_ba, bj_ba):
      src_list  = 期B每行的来源(延续/从长尾毕业/全新出现)
      dest_list = 期A每行的去向(延续/退回长尾/彻底消失)
      best_ba/bj_ba = 期B每行 → 期A 的最佳相似度与行号(延续方向取期A规模用)"""
    _, best_ab, bj_ab = _match_pass(df_a, df_b, SIM_THRESHOLD)
    _, best_ba, bj_ba = _match_pass(df_b, df_a, SIM_THRESHOLD)

    src = []
    for j in range(len(df_b)):
        if best_ba[j] >= SIM_THRESHOLD:
            src.append("延续" if df_a.at[bj_ba[j], "是否头部"] else "从长尾毕业")
        else:
            src.append("全新出现")

    dest = []
    for i in range(len(df_a)):
        if best_ab[i] >= SIM_THRESHOLD:
            dest.append("延续" if df_b.at[bj_ab[i], "是否头部"] else "退回长尾")
        else:
            dest.append("彻底消失")
    return src, dest, best_ba, bj_ba


# ================= 📊 数据总览 =================
def render_overview(ctx: PageCtx):
    data = _data(ctx)
    snap = _snap_pick(ctx, "ov", data)
    d = data.snapshots[snap]
    head = _head(d)

    st.markdown(f"### 📊 数据总览 · {snap}")
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("方向总数", f"{len(d):,}")
    m2.metric(f"头部方向(≥{PAPER_THRESHOLD}篇)", f"{len(head):,}")
    m3.metric("头部占比", f"{len(head) / len(d):.1%}" if len(d) else "—")
    m4.metric("论文总量", f"{int(d['论文数'].sum()):,}")

    # ---- 各期规模走势 ----
    st.subheader("各期规模走势")
    meta = data.meta.reset_index()
    fig = go.Figure()
    fig.add_bar(x=meta["快照"], y=meta["方向数"], name="方向总数",
                marker_color="#C0C0C0")
    fig.add_scatter(x=meta["快照"], y=meta["头部方向数"], name="头部方向数",
                    mode="lines+markers", line=dict(color=MAIN, width=3))
    fig.update_xaxes(type="category")
    style_fig(fig, height=340)
    st.plotly_chart(fig, width="stretch", key=ctx.k("ov", "size"))

    c1, c2 = st.columns(2)
    with c1:
        t = meta.dropna(subset=["头部匹配率"])
        if len(t) > 1:
            fig = px.line(t, x="快照", y="头部匹配率", markers=True,
                          title="相邻期头部方向匹配率(软对齐可信度)")
            fig.update_yaxes(tickformat=".0%")
        else:
            fig = px.bar(meta, x="快照", y=["头部方向数", "长尾方向数"],
                         title="头部 / 长尾 方向数(仅一期,无跨期曲线)")
        style_fig(fig, height=320)
        st.plotly_chart(fig, width="stretch", key=ctx.k("ov", "match"))
    with c2:
        t = meta.dropna(subset=["与上期词汇重合率"])
        if len(t) > 1:
            fig = px.line(t, x="快照", y="与上期词汇重合率", markers=True,
                          title="相邻期词汇重合率(前沿换血速度)")
            fig.update_yaxes(tickformat=".0%")
        else:
            fig = px.bar(meta, x="快照", y="方向数", title="方向数(仅一期)")
        style_fig(fig, height=320)
        st.plotly_chart(fig, width="stretch", key=ctx.k("ov", "vocab"))

    # ---- 学科 × 快照 热力图(头部方向数) ----
    st.subheader("学科 × 快照 热力图(头部方向数)")
    mat = pd.DataFrame({s: _head(v).groupby("学科").size()
                        for s, v in data.snapshots.items()}).fillna(0)
    order = mat.sum(axis=1).sort_values(ascending=False).index
    mat = mat.loc[order].iloc[::-1]
    fig = go.Figure(go.Heatmap(z=mat.values, x=list(mat.columns), y=mat.index,
                               colorscale="Turbo",
                               hovertemplate="%{y}<br>%{x}<br>头部方向:%{z}<extra></extra>"))
    fig.update_layout(margin=dict(l=10, r=10, t=10, b=140))
    fig.update_xaxes(tickangle=-45)
    style_fig(fig, height=max(420, 24 * len(mat)))
    st.plotly_chart(fig, width="stretch", key=ctx.k("ov", "heat"))

    st.subheader("各期统计概览")
    st.dataframe(data.meta, width="stretch")


# ================= 🔀 变迁全景 =================
def render_transition(ctx: PageCtx):
    data = _data(ctx)
    snaps = data.snaps
    if len(snaps) < 2:
        st.warning("至少需要两期快照才能做变迁分析。")
        return

    with st.sidebar:
        k_a, k_b = ctx.k("tr", "a"), ctx.k("tr", "b")
        if st.session_state.get(k_a) not in snaps:
            st.session_state[k_a] = snaps[-2]
        if st.session_state.get(k_b) not in snaps:
            st.session_state[k_b] = snaps[-1]
        if snaps.index(st.session_state[k_a]) >= snaps.index(st.session_state[k_b]):
            st.session_state[k_a], st.session_state[k_b] = \
                st.session_state[k_b], st.session_state[k_a]
        snap_a = st.selectbox("基准期", snaps, key=k_a)
        snap_b = st.selectbox("对比期", snaps, key=k_b)
        disc_f = st.multiselect("学科过滤(留空 = 全部)",
                                sorted({s for v in data.snapshots.values()
                                        for s in v["学科"].unique() if s}),
                                key=ctx.k("tr", "disc"))

    df_a = data.snapshots[snap_a].copy()
    df_b = data.snapshots[snap_b].copy()
    if disc_f:
        df_a = df_a[df_a["学科"].isin(disc_f)].reset_index(drop=True)
        df_b = df_b[df_b["学科"].isin(disc_f)].reset_index(drop=True)
    if df_a.empty or df_b.empty:
        st.warning("当前学科过滤条件下某一期没有方向数据。")
        return

    src, dest, best_ba, bj_ba = _classify_pair(df_a, df_b)
    df_b["来源"] = src
    df_a["去向"] = dest

    hb = _head(df_b)
    ha = _head(df_a)
    src_cnt = hb["来源"].value_counts()
    dest_cnt = ha["去向"].value_counts()

    st.markdown(f"### 🔀 变迁全景 · {snap_a} → {snap_b}")
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("延续(头部→头部)", f"{src_cnt.get('延续', 0):,}")
    m2.metric("从长尾毕业", f"{src_cnt.get('从长尾毕业', 0):,}")
    m3.metric("全新出现", f"{src_cnt.get('全新出现', 0):,}")
    m4.metric("退回长尾", f"{dest_cnt.get('退回长尾', 0):,}")
    m5.metric("彻底消失", f"{dest_cnt.get('彻底消失', 0):,}")

    c1, c2 = st.columns(2)
    with c1:
        flows = {"延续": src_cnt.get("延续", 0),
                 "从长尾毕业": src_cnt.get("从长尾毕业", 0),
                 "全新出现": src_cnt.get("全新出现", 0),
                 "退回长尾": dest_cnt.get("退回长尾", 0),
                 "彻底消失": dest_cnt.get("彻底消失", 0)}
        t = pd.Series(flows).sort_values(ascending=True)
        fig = px.bar(x=t.values, y=t.index, orientation="h",
                     labels={"x": "方向数量", "y": ""},
                     title=f"变迁五分类(期B头部 {len(hb)} / 期A头部 {len(ha)})")
        fig.update_traces(marker_color=[ACCENT if k in ("从长尾毕业", "全新出现")
                                        else MAIN for k in t.index])
        style_fig(fig, height=340)
        st.plotly_chart(fig, width="stretch", key=ctx.k("tr", "flow"))
    with c2:
        cont = hb[hb["来源"] == "延续"].copy()
        if len(cont):
            cont["期A论文数"] = [df_a.at[bj_ba[j], "论文数"] for j in cont.index]
            fig = px.scatter(cont, x="期A论文数", y="论文数",
                             hover_name=cont["关键词"].map(lambda s: kw_label(s, 40)),
                             title=f"延续方向规模变化({len(cont)} 个,对数轴)")
            lim = max(cont["期A论文数"].max(), cont["论文数"].max()) * 1.3
            fig.add_trace(go.Scatter(x=[1, lim], y=[1, lim], mode="lines",
                                     line=dict(dash="dash", color="gray"),
                                     name="规模不变"))
            fig.update_xaxes(type="log")
            fig.update_yaxes(type="log")
        else:
            fig = go.Figure()
            fig.update_layout(title="延续方向规模变化(无延续方向)")
        style_fig(fig, height=340)
        st.plotly_chart(fig, width="stretch", key=ctx.k("tr", "scale"))

    # ---- 新晋头部方向名单(新兴热点候选) ----
    new_head = hb[hb["来源"] != "延续"].sort_values("论文数", ascending=False)
    st.subheader(f"🌱 新晋头部方向({len(new_head)} 个)= 从长尾毕业 + 全新出现")
    st.caption("从长尾毕业 = 期A已有雏形但未达头部阈值;全新出现 = 期A中也找不到对应物"
               "(建议人工抽查,排除 Jaccard 同义词盲区)。")
    if len(new_head):
        show = new_head[["来源", "学科", "论文数", "总被引", "年份中位", "关键词"]].copy()
        show["关键词"] = show["关键词"].map(lambda s: kw_label(s, 120))
        st.dataframe(show, width="stretch", height=420, hide_index=True,
                     column_config={"关键词": st.column_config.TextColumn(
                         "关键词", width="large")})
        st.download_button("导出新晋头部方向",
                           new_head.to_csv(index=False).encode("utf-8-sig"),
                           f"new_heads_{snap_a}_{snap_b}.csv", "text/csv",
                           key=ctx.k("tr", "csv"))


# ================= 🧪 学科主页 =================
def render_disc(ctx: PageCtx):
    data = _data(ctx)
    snap = _snap_pick(ctx, "dp", data)
    d = data.snapshots[snap]
    disc_opts = sorted(s for s in d["学科"].unique() if s)
    if not disc_opts:
        st.warning("当前快照没有学科数据。")
        return
    _ensure_choice(ctx.k("dp", "disc"), disc_opts)
    disc = st.sidebar.selectbox("选择学科", disc_opts, key=ctx.k("dp", "disc"))
    top_n = safe_slider("气泡图展示方向数", 60, 25, key=ctx.k("dp", "topn"))

    sub = d[d["学科"] == disc]
    h = _head(sub).sort_values("论文数", ascending=False)
    st.markdown(f"### 🧪 「{disc}」· {snap} · 头部方向 {len(h)} 个"
                f"(全量 {len(sub)})")
    if h.empty:
        st.info("该学科本期没有头部方向。")
        return

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("头部方向数", f"{len(h):,}")
    m2.metric("论文总量", f"{int(h['论文数'].sum()):,}")
    m3.metric("总被引", f"{int(h['总被引'].sum()):,}")
    m4.metric("篇均引用(头部)", f"{h['篇均引用'].mean():.1f}")

    c1, c2 = st.columns([3, 2])
    with c1:
        h_lab = h.head(top_n).copy()
        h_lab["标签"] = h_lab["关键词"].map(lambda s: kw_label(s, 40))
        fig = px.scatter(h_lab, x="年份中位", y="篇均引用", size="论文数",
                         color="来源", hover_name="标签", size_max=45,
                         color_discrete_map=SRC_COLORS,
                         labels={"年份中位": "发表年份中位数"},
                         title=f"头部方向全景(展示前 {len(h_lab)} 个,来源着色)")
        style_fig(fig, height=480)
        st.plotly_chart(fig, width="stretch", key=ctx.k("dp", "bub"))
    with c2:
        h2 = h.copy()
        h2["规模排名"] = h2["论文数"].rank(ascending=False, method="min")
        h2["影响排名"] = h2["篇均引用"].rank(ascending=False, method="min")
        fig = px.scatter(h2, x="规模排名", y="影响排名",
                         hover_name=h2["关键词"].map(lambda s: kw_label(s, 40)),
                         title="规模排名 × 影响排名<br>"
                               "<sup>左下=又大又强 · 右下=小而精 · 左上=大而不强</sup>")
        nn = len(h2)
        fig.add_trace(go.Scatter(x=[1, nn], y=[1, nn], mode="lines",
                                 line=dict(dash="dash", color="gray"),
                                 name="排名一致"))
        fig.update_yaxes(autorange="reversed")
        style_fig(fig, height=480)
        st.plotly_chart(fig, width="stretch", key=ctx.k("dp", "rank"))

    st.subheader("头部方向排行(按论文数,前 20)")
    t = h.head(20).iloc[::-1]
    fig = px.bar(x=t["论文数"], y=t["关键词"].map(lambda s: kw_label(s, 45)),
                 orientation="h", labels={"x": "论文数", "y": ""},
                 color=t["来源"], color_discrete_map=SRC_COLORS)
    style_fig(fig, height=max(380, 30 * len(t)))
    st.plotly_chart(fig, width="stretch", key=ctx.k("dp", "bar"))


# ================= 🧭 轨迹追踪 =================
def _traj_detail(data: FrontsData, tid: int) -> pd.DataFrame:
    """某条轨迹在各期的明细(贪心一对一保证每期至多一行)。"""
    rows = []
    for t, s in enumerate(data.snaps):
        hit = data.snapshots[s][data.snapshots[s]["traj_id"] == tid]
        if len(hit):
            r = hit.iloc[0]
            rows.append({"快照": s, "序号": t, "论文数": r["论文数"],
                         "总被引": r["总被引"], "篇均引用": r["篇均引用"],
                         "是否头部": r["是否头部"], "关键词": r["关键词"]})
    return pd.DataFrame(rows)


def render_traj(ctx: PageCtx):
    data = _data(ctx)
    traj, tl, snaps = data.traj, data.traj_tl, data.snaps

    with st.sidebar:
        st.divider()
        disc_f = st.multiselect("学科过滤(留空 = 全部)",
                                sorted(s for s in traj["学科"].unique() if s),
                                key=ctx.k("tj", "disc"))
        sort_by = st.selectbox("轨迹排序", ["跨度期数", "累计论文数", "峰值论文数"],
                               key=ctx.k("tj", "sort"))
        min_span = safe_slider("最少跨越期数", len(snaps), 2,
                               key=ctx.k("tj", "span"))
        top_n = safe_slider("热力图展示轨迹数", 200, 30,
                            key=ctx.k("tj", "topn"))

    cand = traj[traj["跨度期数"] >= min_span]
    if disc_f:
        cand = cand[cand["学科"].isin(disc_f)]
    if cand.empty:
        st.warning("当前筛选条件下没有轨迹。")
        return

    st.markdown("### 🧭 轨迹追踪(跨期软对齐链)")
    m1, m2, m3 = st.columns(3)
    m1.metric("轨迹总数", f"{len(traj):,}")
    m2.metric(f"跨 ≥{min_span} 期", f"{len(cand):,}")
    m3.metric("跨全期轨迹", f"{int((traj['跨度期数'] == len(snaps)).sum()):,}")
    st.caption("轨迹 = 相邻期贪心一对一匹配串成的演化链;"
               "链上最低相似度越低,后半段的可信度越差。")

    # ---- Top 轨迹 × 快照 热力图 ----
    top = cand.sort_values(sort_by, ascending=False).head(top_n)
    hm = tl.loc[top.index]
    labels = [f"#{i} · {kw_label(k, 28)}" for i, k in
              zip(top.index, top["最新关键词"])]
    fig = go.Figure(go.Heatmap(
        z=hm.values, x=list(hm.columns), y=labels,
        colorscale="Viridis", xgap=1, ygap=1,
        hovertemplate="%{y}<br>%{x}<br>论文数:%{z}<extra></extra>"))
    fig.update_layout(margin=dict(l=10, r=10, t=10, b=140))
    fig.update_xaxes(tickangle=-45)
    fig.update_yaxes(autorange="reversed")  # 让第一行(#1)显示在顶部
    style_fig(fig, height=max(420, 22 * len(hm)))
    st.plotly_chart(fig, width="stretch", key=ctx.k("tj", "heat"))
    st.caption("行 = 按所选口径排序的 Top 轨迹(标签取最新关键词);"
               "每格 = 该轨迹当期论文数,空白 = 该期缺席。")

    # ---- 单轨迹详情 ----
    st.divider()
    st.subheader("单轨迹详情")
    opt = top.sort_values(sort_by, ascending=False)
    opts = [f"#{i} · {kw_label(k, 40)}" for i, k in
            zip(opt.index, opt["最新关键词"])]
    _ensure_choice(ctx.k("tj", "tid"), opts)
    opt_ids = list(top.sort_values(sort_by, ascending=False).index)

    def _label(t):
        return f"#{t} · {traj.at[t, '最新关键词']}"

    tid = st.selectbox("选择轨迹(可直接输入关键词搜索)", opt_ids,
                       format_func=_label,
                       key=ctx.k("tj", "tid"), width="stretch")

    # 选中后完整展示,编号 + 全文都有
    st.markdown(f"**当前轨迹** ：#{tid}·{traj.at[tid, '最新关键词']}")
    row = traj.loc[tid]
    det = _traj_detail(data, tid)

    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("起始期", row["起始期"])
    m2.metric("结束期", row["结束期"])
    m3.metric("跨度期数", f"{int(row['跨度期数'])} / {len(snaps)}")
    m4.metric("峰值论文数", f"{int(row['峰值论文数']):,}")
    m5.metric("链上最低相似度", f"{row['链上最低相似度']:.2f}")

    # 轨迹曲线:论文数(线,断线=缺席)+ 头部阈值参考线
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=det["快照"], y=det["论文数"], mode="lines+markers",
        connectgaps=False, line=dict(color=MAIN, width=3),
        hovertemplate="%{x}<br>论文数:%{y}<extra></extra>", name="论文数"))
    fig.add_hline(y=PAPER_THRESHOLD, line_dash="dash", line_color="#999999",
                  annotation_text=f"头部阈值 {PAPER_THRESHOLD}",
                  annotation_position="top left")
    fig.update_xaxes(type="category")
    style_fig(fig, height=340)
    st.plotly_chart(fig, width="stretch", key=ctx.k("tj", "line"))
    st.caption("断线处 = 该期快照中无匹配方向(链中断,可能是聚类换血或匹配失败)。")

    # 各期关键词对照(看方向语义如何漂移)
    st.subheader(f"轨迹 #{tid} · 各期关键词对照")
    show = det[["快照", "论文数", "总被引", "是否头部", "关键词"]].copy()
    show["是否头部"] = show["是否头部"].map({True: "✓", False: ""})
    show["关键词"] = show["关键词"].map(lambda s: kw_label(s, 120))
    st.dataframe(show, width="stretch", height=320, hide_index=True,
                 column_config={"关键词": st.column_config.TextColumn(
                     "关键词", width="large")})
    st.download_button("导出该轨迹明细",
                       det.to_csv(index=False).encode("utf-8-sig"),
                       f"traj_{tid}.csv", "text/csv", key=ctx.k("tj", "csv"))


# ================= 📄 方向明细 =================
def render_papers(ctx: PageCtx):
    data = _data(ctx)
    snap = _snap_pick(ctx, "pp", data)
    d = data.snapshots[snap].copy()

    with st.sidebar:
        st.divider()
        disc = st.multiselect("学科", sorted(s for s in d["学科"].unique() if s),
                              key=ctx.k("pp", "disc"))
        src_sel = st.multiselect("来源", ["延续", "从长尾毕业", "全新出现"],
                                 key=ctx.k("pp", "src"))
        head_only = st.checkbox("只看头部方向", value=False,
                                key=ctx.k("pp", "head"))
        kw = st.text_input("关键词搜索", key=ctx.k("pp", "kw"))

    if disc:
        d = d[d["学科"].isin(disc)]
    if src_sel:
        d = d[d["来源"].isin(src_sel)]
    if head_only:
        d = d[d["是否头部"]]
    if kw:
        d = d[d["关键词"].str.contains(kw, case=False, na=False)]
    if d.empty:
        st.warning("当前筛选条件下没有方向。")
        return

    st.markdown(f"### 📄 方向明细 · {snap} · 共 {len(d):,} 个")
    show = d[["来源", "学科", "论文数", "总被引", "篇均引用",
              "年份中位", "是否头部", "traj_id", "关键词"]].copy()
    show["是否头部"] = show["是否头部"].map({True: "✓", False: ""})
    show["关键词"] = show["关键词"].map(lambda s: kw_label(s, 120))
    show = show.sort_values("论文数", ascending=False)
    st.dataframe(show, width="stretch", height=560, hide_index=True,
                 column_config={
                     "关键词": st.column_config.TextColumn("关键词", width="large"),
                     "traj_id": st.column_config.NumberColumn("轨迹ID", format="%d")})
    st.caption("traj_id = 跨期软对齐链编号,可在「🧭 轨迹追踪」页查其全期演化。")
    st.download_button("导出当前筛选结果",
                       d.to_csv(index=False).encode("utf-8-sig"),
                       f"fronts_{snap}.csv", "text/csv", key=ctx.k("pp", "csv"))
