# -*- coding: utf-8 -*-
"""从 GitHub Release 下载数据资产的公共工具。"""
import os

import requests
import streamlit as st


def download_from_release(url: str, dest: str) -> bool:
    """从 GitHub Release 下载文件到本地 dest,.part 临时文件防半截。
    成功返回 True;失败返回 False(交给上传兜底)。"""
    try:
        os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
        tmp = dest + ".part"
        with st.spinner(f"📥 首次运行,正在下载数据文件 {os.path.basename(dest)}…"):
            with requests.get(url, stream=True, timeout=300) as r:
                r.raise_for_status()
                with open(tmp, "wb") as f:
                    for chunk in r.iter_content(1 << 20):
                        f.write(chunk)
        os.replace(tmp, dest)
        return True
    except Exception as e:
        if os.path.exists(dest + ".part"):
            os.remove(dest + ".part")
        st.warning(f"自动下载失败({e}),请在左侧手动上传数据文件。")
        return False
