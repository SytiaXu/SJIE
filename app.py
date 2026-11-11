# coding: utf-8 -*-
"""学科建设观测 · 入口。两级导航：观测域 → 页面。此处不含业务逻辑。"""
import streamlit as st
import streamlit_authenticator as st_auth

from common.ui import setup_page
from common.registry import PageCtx
from hpaper import HOT, HIGHLY
from njtech import NJTECH
from fronts import FRONTS

# 域注册表：侧边栏一级导航顺序即此字典顺序。
DOMAINS: dict[str, object] = {
    f"{m.icon} {m.title}": m for m in (NJTECH, HOT, HIGHLY, FRONTS)
}

APP_TITLE = "学科建设智能评估"


# ---------- Query 参数工具（兼容新旧版 Streamlit） ----------
def _get_param(key):
    """读取 URL query 参数，返回字符串或 None"""
    if hasattr(st, "query_params"):          # Streamlit >= 1.30
        return st.query_params.get(key)
    params = st.experimental_get_query_params()  # 旧版
    return (params.get(key) or [None])[0]


def _clear_logout_param():
    """清掉 URL 上的 ?logout=true，避免刷新后又触发登出"""
    if hasattr(st, "query_params"):
        try:
            del st.query_params["logout"]
        except Exception:
            pass
    else:
        st.experimental_set_query_params()


# ---------- 登出逻辑 ----------
def handle_logout_request(authenticator):
    if _get_param("logout") != "true":
        return

    cookie_name = st.secrets["auth"]["cookie_name"]

    # 1. 清 session（用 pop，别留 None 值）
    for k in ("logout", "name", "username", "authentication_status"):
        st.session_state.pop(k, None)

    # 2. 用 HTML 组件执行 JS 删 cookie
    st.iframe(
        f"""
        <script>
          document.cookie = "{cookie_name}=; Max-Age=0; path=/;";
          document.cookie = "{cookie_name}=; Max-Age=0; path=" + location.pathname;
        </script>
        """,
        height=1,
    )

    # 3. 清掉 URL 上的 ?logout=true
    _clear_logout_param()

    # 4. 关键：不立刻 rerun！
    #    停在中间页，给浏览器时间执行删除脚本
    st.success("✅ 已安全退出")
    if st.button("🔄 重新登录"):
        st.rerun()
    st.stop()   # 阻断后面的 login() 和业务代码


# ---------- UI 组件 ----------
def render_logout_corner(name):
    """固定在页面右上角的用户名 + 退出链接"""
    st.markdown(
        f"""
        <div style="
            position: fixed;
            top: 14px;
            right: 24px;
            z-index: 9999;
            font-size: 0.85rem;
        ">
            <span style="color: #9ca3af;">👤 {name}&nbsp;·&nbsp;</span>
            <a href="?logout=true"
               style="
                   color: #ff4b4b;
                   text-decoration: none;
                   font-weight: 600;
                   padding: 4px 10px;
                   border-radius: 6px;
                   transition: background 0.2s;
               "
               onmouseover="this.style.background='rgba(255,75,75,0.08)'"
               onmouseout="this.style.background='transparent'">
                退出
            </a>
        </div>
        """,
        unsafe_allow_html=True,
    )


def build_authenticator():
    """从 secrets 读取配置并构建 authenticator"""
    config = st.secrets["auth"]

    credentials = {
        "usernames": {
            user["username"]: {
                "name": user["name"],
                "password": user["hashed_password"],
            }
            for user in config["users"]
        }
    }

    return st_auth.Authenticate(
        credentials,
        config["cookie_name"],
        config["cookie_key"],
        config["cookie_expiry_days"],
    )


# ---------- 主流程 ----------
def main():
    # 1. 页面配置（必须是最早的 st 命令）
    setup_page(APP_TITLE)
    st.markdown("## 🏆 学科建设智能评估 Subject Judgment Intelligence Evaluation")

    # 2. 先处理"退出"请求（必须在 login 之前）
    authenticator = build_authenticator()
    handle_logout_request(authenticator)

    # 3. 登录
    try:
        # 新版 API
        authenticator.login()
        auth_status = st.session_state.get("authentication_status")
        name = st.session_state.get("name")
    except TypeError:
        # 旧版 API
        name, auth_status, username = authenticator.login("登录", "main")

    # 4. 未登录：阻断一切业务内容
    if auth_status is False:
        st.error("用户名或密码错误")
        st.stop()
    elif auth_status is None:
        st.warning("请输入用户名和密码")
        st.stop()

    # 5. 已登录：右上角显示 用户名 + 退出
    render_logout_corner(name)

    # ================= 6. 一级导航：观测域 =================
    with st.sidebar:
        st.markdown("### 🧭 观测域")
        domain_name = st.radio("域", list(DOMAINS), label_visibility="collapsed")
        module = DOMAINS[domain_name]
        st.caption(f"当前域：{module.icon} {module.title}")
        st.divider()

    # ================= 7. 加载数据（惰性：切到该域才读） =================
    try:
        snapshots, meta = module.load()
    except Exception as e:
        st.error(f"「{module.title}」数据加载失败：{e}")
        st.stop()

    # ================= 8. 二级导航：页面 =================
    with st.sidebar:
        st.markdown("### 📑 页面")
        page_name = st.radio("页面", list(module.pages), label_visibility="collapsed")
        st.divider()

    # ================= 9. 渲染 =================
    ctx = PageCtx(module=module, snapshots=snapshots, meta=meta)
    module.pages[page_name](ctx)


if __name__ == "__main__":
    main()
