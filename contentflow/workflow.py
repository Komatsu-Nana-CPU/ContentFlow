"""人工确认、单次提交、不确定结果与只读轮询。"""

from datetime import datetime, timezone
import json

from contentflow.domain import Content, FlowError, fingerprint, video_payload
from contentflow.http_client import ApiError
from contentflow.mpt import MptClient, safe_task_error
from contentflow.materials import MaterialsService, require_materials
from contentflow.repository import Repository
from contentflow.settings import Settings


class Workflow:
    def __init__(self, settings: Settings, repository: Repository, client: MptClient | None = None, materials: MaterialsService | None = None):
        self.settings = settings
        self.repo = repository
        self.client = client or MptClient(settings)
        self.materials = materials or MaterialsService(settings)

    def submit(self, draft_id: str, expected_hash: str) -> dict:
        draft = self.repo.draft(draft_id)
        if not self.settings.source_ready(draft["source"]):
            raise FlowError("missing_key", "所选在线素材 API Key 尚未配置，已暂停提交；不会退回本地素材。")
        if self.settings.auto_publish or not self.settings.edge_ready:
            raise FlowError("config", "后端必须关闭自动发布并使用 Edge 字幕，当前配置不满足要求。")
        content = Content.parse(json.loads(draft["content"]))
        if draft["reviewed_hash"] != expected_hash or fingerprint(draft["topic"], content, draft["source"]) != expected_hash:
            raise FlowError("approval", "请先审核当前内容。")
        payload = video_payload(draft["topic"], content, draft["source"], self.settings.font_path.as_posix())
        self.client.check_schema(payload)
        search = self.materials.search(content.video_terms)
        require_materials(search)
        job = self.repo.reserve(draft_id, expected_hash)
        self.repo.update(job["id"], metadata={"material_search": search})
        try:
            task_id = self.client.submit(payload)
        except ApiError as error:
            return self.repo.update(job["id"], state="uncertain" if error.uncertain else "failed", error=str(error))
        except Exception:
            return self.repo.update(job["id"], state="uncertain", error="提交结果未知，请核对上游任务，禁止自动重发。")
        return self.repo.update(job["id"], task_id=task_id, state="processing")

    def poll(self, job_id: str, manual: bool = False) -> dict:
        job = self.repo.job(job_id)
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(job["created_at"])).total_seconds()
        if job["state"] == "submitting" and age > 90:
            return self.repo.update(job_id, state="uncertain", error="提交进程可能已中断，请核对上游；没有自动重发。")
        if job["state"] not in {"processing", "uncertain", "download_failed"} or not job["task_id"]:
            return job
        if not manual and (job["state"] == "uncertain" or age > 900):
            if job["state"] == "processing":
                return self.repo.update(job_id, state="uncertain", error="轮询已达 15 分钟，后端任务可能仍在运行。请手动核对，不要重发。")
            return job
        try:
            data = self.client.status(job["task_id"])
        except ApiError as error:
            return self.repo.update(job_id, state="uncertain" if error.code == "http_404" else job["state"], error=str(error))
        except FlowError as error:
            return self.repo.update(job_id, state="uncertain", error=str(error))
        progress = data.get("progress", 0)
        progress = max(0, min(100, int(progress))) if isinstance(progress, (int, float)) else 0
        if data["state"] == -1:
            return self.repo.update(job_id, state="failed", error=safe_task_error(data), progress=progress)
        if data["state"] == 1:
            videos = data.get("videos")
            if not isinstance(videos, list) or not videos:
                return self.repo.update(job_id, state="download_failed", error="后端成功但没有成片引用，请核对任务。")
            try:
                path, metadata = self.client.download(job["task_id"], videos[0], self.settings.data_dir / "videos")
                metadata["material_sources"] = self.client.material_sources(job["task_id"])
                metadata["material_search"] = json.loads(job["metadata"] or "{}").get("material_search", {})
            except OSError:
                return self.repo.update(job_id, state="download_failed", progress=100, error="成片保存失败，请检查磁盘空间、目录权限或文件占用；修复后点击重试下载，不会重新提交视频任务。")
            except FlowError as error:
                return self.repo.update(job_id, state="download_failed", progress=100, error=str(error))
            return self.repo.update(job_id, state="complete", progress=100, file_path=str(path.relative_to(self.settings.data_dir)), metadata=metadata, error="")
        return self.repo.update(job_id, state="processing", progress=progress, error="")

    def retry_download(self, job_id: str) -> dict:
        job = self.repo.job(job_id)
        if job["state"] != "download_failed":
            raise FlowError("state", "当前任务无需重试下载。")
        # Only GET the already accepted task; never resubmit the generation.
        return self.poll(job_id, manual=True)

    def reconcile(self, job_id: str, task_id: str) -> dict:
        job = self.repo.job(job_id)
        if job["state"] != "uncertain" or job["task_id"]:
            raise FlowError("state", "只有缺失上游 ID 的待核对任务可以绑定。")
        self.client.status(task_id)
        self.repo.update(job_id, task_id=task_id, state="processing", error="")
        return self.poll(job_id, manual=True)
