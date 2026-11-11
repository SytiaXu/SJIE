# -*- coding: utf-8 -*-
"""论文类观测（热点 / 高被引）· 数据层。一份代码，路径参数化。"""
import io
import os
import re
import requests

import pandas as pd
import streamlit as st

from common.download import download_from_release

TOP_UNI_N = 100   # 高校下拉/列表默认只展示发文量前 100 的高校

COL_MAP = {"id": "论文ID", "title": "题名", "published": "年份", "xk": "学科", "学校": "高校"}
PROV_KEYS = ("province", "省份", "省市", "省")


def fmt_snap(name) -> str:
    """sheet 名 → 展示名：202503 → 2025-03，20250315 → 2025-03-15。"""
    s = str(name).strip()
    if re.fullmatch(r"\d{6}", s):
        return f"{s[:4]}-{s[4:]}"
    if re.fullmatch(r"\d{8}", s):
        return f"{s[:4]}-{s[4:6]}-{s[6:]}"
    return s


def _normalize_sheet(raw: pd.DataFrame) -> pd.DataFrame:
    df = raw.copy()
    df.columns = [str(c).strip().lower() for c in df.columns]
    missing = set(COL_MAP) - set(df.columns)
    if missing:
        raise ValueError(f"工作表缺少列：{sorted(missing)}（实际列：{list(df.columns)}）")
    prov_col = next((c for c in df.columns if c in PROV_KEYS), None)
    if prov_col is None:
        raise ValueError(f"缺少省市列（支持：{PROV_KEYS}，实际列：{list(df.columns)}）")
    df = (df.rename(columns={**COL_MAP, prov_col: "省市"})
            [["高校", "省市", "学科", "题名", "论文ID", "年份"]]
            .dropna(subset=["论文ID", "题名", "高校", "学科", "省市"]))
    df["省市"] = df["省市"].astype(str).str.strip()
    if pd.api.types.is_datetime64_any_dtype(df["年份"]):
        df["年份"] = df["年份"].dt.year
    else:
        df["年份"] = pd.to_numeric(df["年份"].astype(str).str.extract(r"(\d{4})")[0],
                                   errors="coerce")
    df["年份"] = df["年份"].astype("Int64")
    df = df.dropna(subset=["年份"])
    df["论文ID"] = df["论文ID"].astype(str).str.strip()
    df["题名"] = df["题名"].astype(str).str.strip()
    dup = int(df.duplicated(subset=["论文ID"]).sum())
    if dup:
        df = df.drop_duplicates(subset=["论文ID"], keep="first")
    df.attrs["removed_duplicates"] = dup
    return df


@st.cache_data(show_spinner="正在读取 Excel…（可能需要数分钟）")
def _load_snapshots(source, _tag=""):
    if isinstance(source, (bytes, bytearray)):
        source = io.BytesIO(source)
    sheets = pd.read_excel(source, sheet_name=None, engine="openpyxl")
    data, meta = {}, []
    for name, raw in sheets.items():
        snap = _normalize_sheet(raw)
        key = fmt_snap(name)
        data[key] = snap
        meta.append({"快照": key, "论文数": len(snap),
                     "去重删除": snap.attrs.get("removed_duplicates", 0),
                     "高校数": snap["高校"].nunique(),
                     "学科数": snap["学科"].nunique(),
                     "省份数": snap["省市"].nunique()})
    if not data:
        raise ValueError("Excel 里没有任何可用的工作表。")
    data = dict(sorted(data.items()))
    return data, pd.DataFrame(meta).set_index("快照")


def load_paper_snapshots(excel_path: str, upload_label: str, domain_id: str,
                         release_url: str | None = None):
    """本地文件优先;没有则从 GitHub Release 下载;再不行侧边栏上传兜底。"""
    if os.path.exists(excel_path):
        return _load_snapshots(excel_path, _tag=os.path.getmtime(excel_path))

    if release_url and download_from_release(release_url, excel_path):
        return _load_snapshots(excel_path, _tag=os.path.getmtime(excel_path))

    up = st.sidebar.file_uploader(upload_label, type=["xlsx"], key=f"upload_{domain_id}")
    if up is None:
        st.info(f"未找到 `{excel_path}`,请稍候自动下载完成,或在左侧手动上传 Excel。")
        st.stop()
    return _load_snapshots(up.getvalue())
