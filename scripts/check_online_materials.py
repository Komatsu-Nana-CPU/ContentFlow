"""通过本机固定 MPT 素材服务做真实搜索/下载；必须用其独立 Python。"""

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import uuid


def main() -> int:
    parser = argparse.ArgumentParser(description="真实核验 MPT 1.3.6 免费在线素材流程，不创建视频或调用 LLM")
    parser.add_argument("--source", choices=["pixabay"], default="pixabay")
    parser.add_argument("--term", default="forest sunlight")
    parser.add_argument("--mpt-dir", type=Path, default=Path(os.environ.get("CONTENTFLOW_MPT_DIR") or Path(__file__).resolve().parents[2] / "MoneyPrinterTurbo"))
    parser.add_argument("--output", type=Path, default=Path("docs/evidence/round006_material_probe.json"))
    args = parser.parse_args()
    sys.path.insert(0, str(args.mpt_dir))
    from app.config import config
    from app.models.schema import VideoAspect, VideoConcatMode
    from app.services import material
    from loguru import logger

    logger.remove()
    logs = []

    def safe_log(message):
        raw = message.record["message"]
        logs.append({"level": message.record["level"].name, "message": re.sub(r"(?:https?|wss?)://\S+", "[URL omitted]", raw)})

    logger.add(safe_log, level="INFO")
    report = {"at": datetime.now(timezone(timedelta(hours=8))).isoformat(), "upstream_version": config.project_version, "source": args.source, "search_term": args.term, "real_network_search_executed": False, "real_download_executed": False}
    key = config.app.get(args.source + "_api_keys")
    present = bool(key.strip()) if isinstance(key, str) else isinstance(key, list) and any(isinstance(k, str) and k.strip() for k in key)
    if not present:
        report.update(status="blocked_missing_key", message="尚未配置所选免费素材 API Key，未发请求；未切换本地素材或其他服务。")
        result = 2
    elif config.project_version != "1.3.6":
        report.update(status="blocked_version", message="不是已固定的 1.3.6，已停止。")
        result = 2
    else:
        report["real_network_search_executed"] = True
        try:
            paths = material.download_videos(task_id="contentflow-probe-" + uuid.uuid4().hex, search_terms=[args.term], source=args.source, video_aspect=VideoAspect.portrait, video_concat_mode=VideoConcatMode.sequential, audio_duration=1, max_clip_duration=5, match_script_order=True)
            report["real_download_executed"] = bool(paths)
            report["files"] = [{"name": Path(p).name, "bytes": Path(p).stat().st_size, "sha256": hashlib.sha256(Path(p).read_bytes()).hexdigest()} for p in paths]
            report["status"] = "passed" if paths else "no_usable_materials_or_network_failure"
            report["limitation"] = "上游对无结果和部分网络/API 错误均返回空列表，需要结合脱敏日志判别，不能将空列表一律归因于关键词。"
            result = 0 if paths else 1
        except Exception as exc:
            report.update(status="failed", error_type=type(exc).__name__)
            result = 1
    report["logs"] = logs
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "logs"}, ensure_ascii=False, indent=2))
    return result


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
