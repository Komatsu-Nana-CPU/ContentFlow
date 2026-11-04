"""仅适配已固定的 MoneyPrinterTurbo 1.3.6。"""

import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile
from urllib.parse import urlsplit

from contentflow.domain import FlowError
from contentflow.http_client import ApiError, HttpClient
from contentflow.settings import Settings, local_url


class MptClient:
    def __init__(self, settings: Settings, http: HttpClient | None = None):
        self.settings = settings
        self.base = local_url(settings.mpt_url)
        self.http = http or HttpClient()
        self.headers = {"x-api-key": settings.mpt_key} if settings.mpt_key else {}

    def check_schema(self, payload: dict | None = None) -> dict:
        doc = self.http.json(self.base + "/openapi.json", headers=self.headers, timeout=5)
        try:
            if doc["info"]["version"] != "1.3.6":
                raise FlowError("version", "视频服务版本不是已验证的 1.3.6，请先核对部署。")
            for path, method in (("/api/v1/videos", "post"), ("/api/v1/tasks/{task_id}", "get"), ("/api/v1/download/{file_path}", "get")):
                assert isinstance(doc["paths"][path][method], dict)
            if payload is not None:
                props = doc["components"]["schemas"]["TaskVideoRequest"]["properties"]
                assert not set(payload) - set(props)
        except (KeyError, TypeError, AssertionError):
            raise FlowError("schema", "视频接口与已核验 Schema 不一致，已禁止提交。") from None
        return doc

    def submit(self, payload: dict) -> str:
        value = self.http.json(self.base + "/api/v1/videos", body=payload, headers=self.headers, timeout=15)
        data = value.get("data")
        task_id = data.get("task_id") if isinstance(data, dict) else None
        if not isinstance(task_id, str) or not re.fullmatch(r"[a-f0-9-]{36}", task_id):
            raise ApiError("response", "提交响应未包含有效任务 ID，需要核对上游，禁止自动重发。", True)
        return task_id

    def status(self, task_id: str) -> dict:
        if not re.fullmatch(r"[a-f0-9-]{36}", task_id):
            raise FlowError("task_id", "任务标识格式无效。")
        value = self.http.json(self.base + "/api/v1/tasks/" + task_id, headers=self.headers, timeout=8)
        data = value.get("data", {})
        if not isinstance(data, dict) or data.get("task_id") != task_id or type(data.get("state")) is not int or data["state"] not in {-1, 1, 4}:
            raise FlowError("response", "任务状态结构异常，请核对后端，未重新提交。")
        return data

    def tasks(self) -> list[dict]:
        value = self.http.json(self.base + "/api/v1/tasks?page=1&page_size=100", headers=self.headers, timeout=8)
        data = value.get("data")
        if not isinstance(data, dict) or not isinstance(data.get("tasks"), list):
            raise FlowError("response", "后端任务列表结构异常。")
        return data["tasks"]

    def material_sources(self, task_id: str) -> list[dict]:
        """读取固定版本公开来源清单，绝不展示下载签名或完整 params。"""
        if not re.fullmatch(r"[a-f0-9-]{36}", task_id):
            return []
        path = self.settings.mpt_dir / "storage/tasks" / task_id / "script.json"

        def public_page(value):
            if not isinstance(value, str):
                return None
            try:
                p = urlsplit(value)
                if p.scheme != "https" or p.username or p.password or not p.hostname:
                    return None
                if not any(p.hostname == domain or p.hostname.endswith("." + domain) for domain in ("pexels.com", "pixabay.com")):
                    return None
                return p._replace(query="", fragment="").geturl()
            except ValueError:
                return None

        try:
            if not path.exists() or path.stat().st_size > 1_000_000:
                return []
            value = json.loads(path.read_text(encoding="utf-8"))
            sources = []
            for item in value.get("material_sources", [])[:30]:
                if not isinstance(item, dict) or item.get("provider") not in {"pexels", "pixabay"}:
                    continue
                creator = item.get("creator") or {}
                sources.append({"provider": item["provider"], "search_term": str(item.get("search_term", ""))[:100], "source_page": public_page(item.get("source_page")), "creator": str(creator.get("name", ""))[:100] if isinstance(creator, dict) else "", "creator_page": public_page(creator.get("profile_page")) if isinstance(creator, dict) else None})
            return sources
        except (OSError, ValueError, TypeError, AttributeError):
            return []

    def download(self, task_id: str, video_uri: str, directory: Path) -> tuple[Path, dict]:
        parsed = urlsplit(video_uri)
        if parsed.netloc and (parsed.netloc != urlsplit(self.base).netloc or parsed.scheme != "http"):
            raise FlowError("download", "拒绝下载来自其他服务的产物引用。")
        if parsed.query or parsed.fragment or not re.fullmatch(r"/tasks/" + re.escape(task_id) + r"/final-\d+\.mp4", parsed.path):
            raise FlowError("download", "成片路径不在当前任务的受管目录中。")
        data = self.http.request(self.base + "/api/v1/download/" + parsed.path.removeprefix("/tasks/"), headers=self.headers, timeout=60, limit=100_000_000)
        if not data or b"ftyp" not in data[:64]:
            raise FlowError("download", "下载结果不是可识别的 MP4。")
        path = directory / (task_id + ".mp4")
        temporary = None
        try:
            directory.mkdir(parents=True, exist_ok=True)
            # 同目录原子替换；写入失败时保留既有成片，避免留下半个 MP4。
            with tempfile.NamedTemporaryFile(dir=directory, prefix=task_id + "-", suffix=".part", delete=False) as handle:
                temporary = Path(handle.name)
                handle.write(data)
            temporary.replace(path)
        except OSError:
            raise FlowError("download_storage", "成片保存失败，请检查磁盘空间、目录权限或文件占用；修复后仅重试下载，不会重新生成视频。") from None
        finally:
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass  # 清理失败不能掩盖保存错误；临时文件仍在受管目录。
        metadata = {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
        binaries = [self.settings.ffmpeg_path] if self.settings.ffmpeg_path else list((self.settings.mpt_dir / ".venv/Lib/site-packages/imageio_ffmpeg/binaries").glob("ffmpeg*.exe"))
        if not binaries:
            raise FlowError("media", "已下载 MP4，但找不到验证用 FFmpeg；保留文件等待检查。")
        try:
            result = subprocess.run([str(binaries[0]), "-v", "info", "-nostdin", "-i", str(path), "-f", "null", "-"], capture_output=True, text=True, errors="replace", timeout=90)
            duration = re.search(r"Duration: (\d+):(\d+):(\d+(?:\.\d+)?)", result.stderr)
            size = re.search(r"Video:.*?\b(\d{2,5})x(\d{2,5})\b", result.stderr)
            if result.returncode or not duration or not size or "Audio:" not in result.stderr:
                raise FlowError("media", "MP4 音视频解码验证未通过，请保留任务排查。")
            metadata.update(duration_seconds=int(duration[1])*3600+int(duration[2])*60+float(duration[3]), width=int(size[1]), height=int(size[2]), decoded=True)
        except (OSError, subprocess.TimeoutExpired):
            raise FlowError("media", "成片解码超时或验证器不可用；保留已下载文件。") from None
        return path, metadata


def safe_task_error(data: dict) -> str:
    stage = data.get("failed_stage")
    labels = {"script": "脚本", "terms": "关键词", "audio": "中文配音", "materials": "在线素材搜索或下载", "video": "视频合成", "preflight": "后端预检"}
    label = labels.get(stage, "视频任务")
    return f"{label}失败。" + ("可能是无符合竖屏和时长条件的素材、配额或网络异常；请核对关键词和素材服务。" if stage == "materials" else "请检查后端依赖、服务权限和网络；不会自动切换服务或重发任务。")
