"""在原上游环境调用 Pixabay；只接收计数、诊断码和公开来源信息。"""

import hashlib
import json
from pathlib import Path
import subprocess
import time
import re

from contentflow.domain import FlowError
from contentflow.settings import Settings, atomic_private_write

MESSAGES = {
    "missing_key": "Pixabay Key 尚未配置，请在本机填写。",
    "invalid_key": "Pixabay 拒绝了当前 Key，请核对本机配置和账户权限。",
    "network_error": "Pixabay 网络连接失败，请检查网络或既有代理；没有换源。",
    "network_challenge": "Pixabay 返回网络验证拦截，不能靠重复请求解决，请检查当前网络。",
    "rate_limited": "Pixabay 请求频率已受限，请等待后手动重试。",
    "request_rejected": "Pixabay 拒绝请求，请核查 Key 权限、网络和请求条件。",
    "no_results": "Pixabay 没有返回这些关键词的视频，请修改具体画面关键词。",
    "no_matching_videos": "Pixabay 有结果，但没有满足 1.3.6 竖屏/分辨率/最小时长筛选的视频。",
}


class MaterialsService:
    def __init__(self, settings: Settings, runner=None, clock=None):
        self.settings = settings
        self.runner = runner or subprocess.run
        self.clock = clock or time.time

    def search(self, terms: tuple[str, ...] | list[str]) -> dict:
        if not self.settings.pixabay_ready:
            raise FlowError("missing_key", MESSAGES["missing_key"])
        terms = list(terms)
        if not 1 <= len(terms) <= 4 or any(not isinstance(t, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9 ,'\-]{1,79}", t) for t in terms):
            raise FlowError("terms", "请提供 1–4 个有效的英文画面关键词，每个 2–80 字符。")
        key = hashlib.sha256(json.dumps(terms).encode()).hexdigest()
        directory = self.settings.data_dir / "material_search"
        directory.mkdir(parents=True, exist_ok=True)
        cached = directory / (key + ".json")
        try:
            if cached.exists():
                report = json.loads(cached.read_text(encoding="utf-8"))
                age = self.clock() - report["saved_at"]
                ttl = 86400 if report["status"] in {"passed", "no_results", "no_matching_videos"} else 30
                if 0 <= age < ttl:
                    return {**report, "preview_cache_hit": True}
        except (OSError, ValueError, KeyError, TypeError):
            pass
        input_path = directory / (key + ".input.json")
        atomic_private_write(input_path, json.dumps({"video_terms": terms}))
        python = self.settings.mpt_python
        script = Path(__file__).resolve().parents[1] / "scripts/probe_pixabay.py"
        try:
            completed = self.runner([str(python), "-X", "utf8", "-B", str(script), "--mpt-dir", str(self.settings.mpt_dir), "--terms-file", str(input_path)], capture_output=True, encoding="utf-8", timeout=120)
            report = json.loads(completed.stdout)
            if not isinstance(report, dict) or report.get("source") != "pixabay" or type(report.get("matched_count")) is not int:
                raise ValueError("Invalid probe response")
        except (OSError, subprocess.TimeoutExpired, ValueError, TypeError):
            raise FlowError("material_probe", "素材检索进程不可用或超时，未创建视频任务；请检查本机上游环境。") from None
        report = {**report, "saved_at": self.clock(), "preview_cache_hit": False}
        atomic_private_write(cached, json.dumps(report, ensure_ascii=False))
        return report


def require_materials(report: dict) -> None:
    if report.get("status") != "passed" or report.get("matched_count", 0) < 1:
        raise FlowError("materials", MESSAGES.get(report.get("status"), "Pixabay 返回结构或下载兼容性异常，请检查素材诊断；未切换其他服务。"))
