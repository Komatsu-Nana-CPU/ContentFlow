r"""启动：.venv\Scripts\python.exe -m streamlit run app.py --server.address 127.0.0.1"""

import json
from pathlib import Path

import streamlit as st

from contentflow.deepseek import generate_content
from contentflow.domain import Content, FlowError, fingerprint
from contentflow.mpt import MptClient
from contentflow.materials import MaterialsService, MESSAGES
from contentflow.repository import ACTIVE, Repository
from contentflow.settings import load_settings, save_credentials
from contentflow.workflow import Workflow

st.set_page_config(page_title="ContentFlow · AI 视频工作台", page_icon="▶", layout="wide")
st.markdown("""<style>
.stApp {background:#f7f9fc} .block-container {max-width:1140px;padding-top:2.5rem}
h1,h2,h3 {color:#132442} div[data-testid="stMetric"] {background:white;border:1px solid #e3e8f0;border-radius:12px;padding:16px}
</style>""", unsafe_allow_html=True)


@st.cache_resource
def repository(path: str) -> Repository:
    return Repository(Path(path))


def credentials(settings):
    st.sidebar.markdown("### 本机服务设置")
    st.sidebar.caption("密钥仅保存在本机私有配置；不要在聊天中发送。")
    st.sidebar.write("DeepSeek Flash：" + ("已配置" if settings.deepseek_key else "未配置"))
    st.sidebar.write("Pixabay：" + ("已配置" if settings.pixabay_ready else "未配置"))
    with st.sidebar.expander("填写或更新密钥"):
        st.caption("留空保留已有值。保存素材 Key 后需要重启视频服务；请通知开发助手处理。")
        with st.form("private_credentials", clear_on_submit=True):
            deepseek = st.text_input("DeepSeek API Key", type="password")
            pixabay = st.text_input("Pixabay API Key", type="password")
            save = st.form_submit_button("保存到本机")
        if save:
            try:
                if any(job["state"] in ACTIVE for job in repo.jobs()):
                    raise FlowError("busy", "任务执行或核对期间不能更换服务凭证。")
                needs_restart = save_credentials(settings, deepseek, "", pixabay)
                st.session_state["settings_notice"] = "配置已保存；素材密钥变更后请重启视频服务。" if needs_restart else "配置已保存。"
                st.rerun()
            except FlowError as error:
                st.error(str(error))
    if st.session_state.get("settings_notice"):
        st.sidebar.info(st.session_state["settings_notice"])
    st.sidebar.link_button("Pixabay API 说明", "https://pixabay.com/api/docs/")
    st.sidebar.caption("本轮唯一在线来源为 Pixabay。Pexels、Coverr 和收费生成服务不启用。")
    if st.sidebar.button("检查视频服务"):
        try:
            client.check_schema()
            st.sidebar.success("本机 MoneyPrinterTurbo 1.3.6 接口可访问。")
        except FlowError as error:
            st.sidebar.error(str(error))
    with st.sidebar.expander("独立验证 Pixabay 搜索"):
        term = st.text_input("英文测试关键词", value="waterfall", max_chars=80, key="probe_term")
        if st.button("验证 Pixabay 搜索", disabled=not settings.pixabay_ready):
            try:
                with st.spinner("检查 Pixabay…"):
                    result = materials.search([term.strip()])
                if result["status"] == "passed":
                    st.success(f"检索到 {result['matched_count']} 个可用候选；未创建视频任务。")
                else:
                    st.warning(MESSAGES.get(result["status"], "搜索返回异常，请检查配置或网络。"))
            except FlowError as error:
                st.error(str(error))


def editor():
    st.subheader("选题与脚本")
    topic = st.text_input("视频主题", max_chars=120, placeholder="例如：雨后森林中的一次清晨散步", key="new_topic")
    active = any(j["state"] in ACTIVE for j in repo.jobs())
    if st.button("生成脚本与画面关键词", type="primary", disabled=not topic.strip() or not settings.deepseek_key or active):
        try:
            with st.spinner("DeepSeek Flash 正在生成，目标 15–30 秒…"):
                generated = generate_content(topic, settings.deepseek_key)
            identity = repo.new_draft(topic.strip(), generated.content, generated.usage)
            st.session_state["draft_choice"] = identity
            st.rerun()
        except FlowError as error:
            st.error(str(error))
    if not settings.deepseek_key:
        st.info("请先在左侧填写已有的 DeepSeek Key，配置完成后才能生成脚本。")
    drafts = repo.drafts()
    if not drafts:
        st.caption("生成后在这里编辑标题、旁白和四个英文画面关键词，再确认提交。")
        return
    labels = {d["id"]: json.loads(d["content"])["title"] for d in drafts}
    selected = st.selectbox("草稿记录", list(labels), format_func=labels.get, key="draft_choice")
    draft = repo.draft(selected)
    content = json.loads(draft["content"])
    if st.session_state.get("editing_draft") != selected:
        st.session_state.update(editing_draft=selected, edit_topic=draft["topic"], edit_title=content["title"], edit_script=content["script"], edit_terms="\n".join(content["video_terms"]), edit_source="pixabay", review_check=False, editing_fingerprint=None)
    if draft["source"] != "pixabay":
        st.info("此历史草稿原素材源已停用。现显示 Pixabay，须重新审核后才能提交；旧任务记录不变。")
    if st.session_state.get("edit_source") != "pixabay":
        st.session_state["edit_source"] = "pixabay"
        st.session_state["review_check"] = False
    left, right = st.columns([1.25, 1])
    with left:
        current_topic = st.text_input("本条草稿主题", key="edit_topic", max_chars=120)
        title = st.text_input("视频标题", key="edit_title", max_chars=100)
        script = st.text_area("中文旁白", key="edit_script", height=180, max_chars=1500)
        estimated = sum("\u4e00" <= c <= "\u9fff" for c in script) / 4.5
        st.caption(f"口播估算约 {estimated:.0f} 秒，实际以配音为准；建议目标 15–30 秒。")
    with right:
        terms = st.text_area("英文画面关键词（每行一个，共四个）", key="edit_terms", height=160)
        source = st.selectbox("在线素材来源", ["pixabay"], format_func=lambda _: "Pixabay（本轮默认）", key="edit_source", disabled=True)
        st.caption("关键词应是具体可见画面，按旁白叙事顺序排列。素材按顺序检索和剪辑，不保证逐字语义对齐。")
        if not settings.source_ready(source):
            st.warning("所选素材服务未配置 Key，视频提交已暂停；不会退回本地 MP4。")
    try:
        current = Content.parse({"title": title, "script": script, "video_terms": terms.splitlines()})
        digest = fingerprint(current_topic, current, source)
    except FlowError as error:
        current, digest = None, None
        st.warning(str(error))
    if st.session_state.get("editing_fingerprint") != digest:
        st.session_state["review_check"] = False
        st.session_state["editing_fingerprint"] = digest
    reviewed = st.checkbox("我已审核标题、旁白、画面关键词顺序和素材来源", key="review_check")
    if st.button("保存并确认审核", disabled=not reviewed or current is None):
        try:
            repo.confirm(selected, current_topic.strip(), current, source)
            st.success("当前内容已确认。任何修改都需要重新确认。")
        except FlowError as error:
            st.error(str(error))
    draft = repo.draft(selected)
    confirmed = digest is not None and draft["reviewed_hash"] == digest
    if current is not None:
        if st.button("检查 Pixabay 素材", disabled=not settings.pixabay_ready):
            try:
                with st.spinner("正在按当前四个关键词检索 Pixabay，已有结果优先使用缓存…"):
                    preview = materials.search(current.video_terms)
                st.session_state["material_preview"] = {"terms": list(current.video_terms), "report": preview}
            except FlowError as error:
                st.error(str(error))
        preview = st.session_state.get("material_preview", {})
        if preview.get("terms") == list(current.video_terms):
            result = preview["report"]
            st.metric("符合竖屏条件的素材候选", result["matched_count"])
            st.caption("按候选视频去重统计；不是最终使用数量。成功检索缓存 24 小时。")
            for row in result.get("terms", []):
                st.write(f"{row['search_term']}：{row['candidate_count']} 个")
            if result["status"] != "passed":
                st.warning(MESSAGES.get(result["status"], "素材请求或返回结构异常，请检查后端。"))
        else:
            st.caption("当前素材候选数量：尚未查询。开始生成前会自动检索，不会将未查询显示为 0。")
    if confirmed:
        st.success("当前审核快照有效，可开始在线素材视频生成。")
    else:
        st.caption("当前内容尚未确认，或编辑后审核已失效。")
    if st.button("开始生成视频", type="primary", disabled=not confirmed or not settings.source_ready(source) or active):
        try:
            with st.spinner("正在向本机视频服务提交一次任务…"):
                job = flow.submit(selected, digest)
            st.session_state["job_choice"] = job["id"]
            st.session_state["navigate_to"] = "视频任务"
            st.rerun()
        except FlowError as error:
            st.error(str(error))


LABELS = {"submitting": "正在提交", "processing": "正在生成", "uncertain": "需要核对", "failed": "生成失败", "download_failed": "成片下载待处理", "complete": "已完成"}


def task_panel(identity: str):
    job = repo.job(identity)
    if job["state"] in {"processing", "submitting"}:
        previous = job["state"]
        job = flow.poll(identity)
        if job["state"] != previous:
            st.rerun()
    st.subheader(LABELS.get(job["state"], "未知状态"))
    st.progress(job["progress"] / 100)
    st.caption("整体进度由视频服务提供，可能跳跃；不会根据进度猜测具体处理阶段。")
    if job["task_id"]:
        st.code(job["task_id"], language=None)
    search = json.loads(job["metadata"] or "{}").get("material_search")
    if search:
        st.metric("提交前已检索的素材候选", search["matched_count"])
    if job["error"]:
        st.warning(job["error"])
    if st.button("刷新此任务状态", key="poll_" + identity, disabled=not job["task_id"] or job["state"] not in {"processing", "uncertain"}):
        flow.poll(identity, manual=True)
        st.rerun()
    if job["state"] == "download_failed" and st.button("重试下载已有成片", key="download_" + identity):
        try:
            flow.retry_download(identity)
            st.rerun()
        except FlowError as error:
            st.error(str(error))
    if job["state"] == "uncertain" and not job["task_id"]:
        st.info("提交结果不确定，禁止重发。请在后端核对任务 ID，再绑定到此记录。")
        with st.expander("绑定已经核对的上游任务"):
            task_id = st.text_input("上游任务 ID", key="bind_" + identity)
            verified = st.checkbox("我已核对该 ID 属于本次审核内容", key="bind_check_" + identity)
            if st.button("绑定并查询，不创建新任务", key="bind_button_" + identity, disabled=not verified):
                try:
                    flow.reconcile(identity, task_id.strip())
                    st.rerun()
                except FlowError as error:
                    st.error(str(error))
            if st.button("查看后端最近任务", key="list_" + identity):
                try:
                    st.dataframe([{k: row.get(k) for k in ("task_id", "state", "progress")} for row in client.tasks() if isinstance(row, dict)], hide_index=True)
                except FlowError as error:
                    st.error(str(error))
            absent = st.checkbox("我已核对后端，确认此次提交没有创建任务", key="absent_" + identity)
            if st.button("结束此次本机核对", key="resolve_" + identity, disabled=not absent):
                repo.update(identity, state="failed", error="用户已核对后端确认未创建任务；仅结束本机尝试，没有取消或重发任何后端任务。")
                st.rerun()
    if job["state"] == "complete":
        show_video(job)
    if job["state"] == "failed" and st.button("复制内容到新草稿，重新审核后再尝试", key="copy_" + identity):
        snapshot = json.loads(job["snapshot"])
        draft_id = repo.new_draft(snapshot["topic"], Content.parse(snapshot["content"]), source="pixabay")
        st.session_state["draft_choice"] = draft_id
        st.session_state["navigate_to"] = "选题与脚本"
        st.rerun()


def show_video(job):
    path = (settings.data_dir / job["file_path"]).resolve() if job["file_path"] else None
    if path is None or not path.is_relative_to(settings.data_dir.resolve()) or not path.is_file():
        st.warning("本机成片文件不存在，请检查下载目录。")
        return
    metadata = json.loads(job["metadata"] or "{}")
    st.video(str(path))
    a, b, c = st.columns(3)
    a.metric("实际时长", f"{metadata.get('duration_seconds', 0):.2f} 秒")
    b.metric("分辨率", f"{metadata.get('width', '?')} × {metadata.get('height', '?')}")
    c.metric("文件大小", f"{metadata.get('bytes', 0) / 1048576:.2f} MiB")
    st.download_button("下载 MP4", data=path.read_bytes(), file_name="contentflow_" + job["task_id"] + ".mp4", mime="video/mp4", key="save_" + job["id"])
    source = json.loads(job["snapshot"])["source"]
    st.link_button("视频素材来源：" + source.title(), "https://www.pexels.com/" if source == "pexels" else "https://pixabay.com/")
    with st.expander("查看实际素材来源与搜索词"):
        sources = metadata.get("material_sources", [])
        if not sources:
            st.caption("后端未提供可展示的素材来源清单，相关性仍需实际观看确认。")
        for index, item in enumerate(sources):
            st.write(f"{index + 1}. {item['search_term']} · {item['creator'] or '未提供作者'}")
            if item["source_page"]:
                st.link_button("原始素材页", item["source_page"], key=f"source_{job['id']}_{index}")


def main():
    global settings, repo, client, flow, materials
    st.title("ContentFlow")
    st.caption("从一个主题，到一条有画面的中文短视频")
    try:
        settings = load_settings()
        repo = repository(str(settings.data_dir / "contentflow.sqlite3"))
        client = MptClient(settings)
        materials = MaterialsService(settings)
        flow = Workflow(settings, repo, client, materials)
    except FlowError as error:
        st.error(str(error))
        return
    credentials(settings)
    if "navigate_to" in st.session_state:
        st.session_state["page"] = st.session_state.pop("navigate_to")
    page = st.sidebar.radio("工作区", ["选题与脚本", "视频任务", "成片"], key="page")
    if page == "选题与脚本":
        editor()
    elif page == "视频任务":
        jobs = repo.jobs()
        if not jobs:
            st.info("还没有视频任务。先生成并审核脚本，再提交。")
            return
        labels = {j["id"]: json.loads(j["snapshot"])["content"]["title"] + " · " + LABELS[j["state"]] for j in jobs}
        identity = st.selectbox("任务记录", list(labels), format_func=labels.get, key="job_choice")
        panel = st.fragment(task_panel, run_every="3s" if repo.job(identity)["state"] in {"processing", "submitting"} else None)
        panel(identity)
    else:
        completed = [j for j in repo.jobs() if j["state"] == "complete"]
        if not completed:
            st.info("生成成功并下载后，成片会出现在这里。")
        for job in completed:
            st.subheader(json.loads(job["snapshot"])["content"]["title"])
            show_video(job)


if __name__ == "__main__":
    main()
