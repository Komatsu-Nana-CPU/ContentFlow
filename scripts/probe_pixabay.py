"""在 MPT 独立 Python 中核验真实 Pixabay 搜索；stdout 只输出脱敏 JSON。"""

import argparse
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
from urllib.parse import urlsplit


class Discard:
    def write(self, value):
        return len(value)

    def flush(self):
        pass


def public_page(value):
    if not isinstance(value, str):
        return None
    parsed = urlsplit(value)
    if parsed.scheme != "https" or parsed.username is not None or parsed.password is not None or not parsed.hostname or not (parsed.hostname == "pixabay.com" or parsed.hostname.endswith(".pixabay.com")):
        return None
    return parsed._replace(query="", fragment="").geturl()


def run_probe(mpt_dir: Path, terms: list[str], download_one: bool) -> dict:
    report = {"source": "pixabay", "at": datetime.now(timezone(timedelta(hours=8))).isoformat(), "status": "failed", "matched_count": 0, "search_network_calls": 0, "terms": [], "diagnostics": []}
    sys.path.insert(0, str(mpt_dir))
    from loguru import logger
    logger.remove()
    from app.config import config
    from app.models.schema import VideoAspect
    from app.services import material
    logger.remove()
    report["upstream_version"] = config.project_version
    if config.project_version != "1.3.6":
        return {**report, "status": "version_mismatch"}
    keys = config.app.get("pixabay_api_keys")
    present = bool(keys.strip()) if isinstance(keys, str) else isinstance(keys, list) and any(isinstance(k, str) and k.strip() for k in keys)
    if not present:
        return {**report, "status": "missing_key"}

    # Observe response metadata only; never retain request URLs, headers or response bodies.
    original_get = material.requests.get
    observations = []

    def observed_get(url, *args, **kwargs):
        parsed = urlsplit(url)
        is_search = parsed.hostname == "pixabay.com" and parsed.path == "/api/videos/"
        try:
            response = original_get(url, *args, **kwargs)
        except Exception as exc:
            if is_search:
                observations.append({"error_type": type(exc).__name__, "status": "network_error"})
            raise
        if is_search:
            status = int(response.status_code)
            observation = {"http_status": status}
            if material._is_cloudflare_challenge(response):
                observation["status"] = "network_challenge"
            elif status == 429:
                observation["status"] = "rate_limited"
            elif status in (400, 401, 403):
                body = response.text[:4096].lower()
                observation["status"] = "invalid_key" if ("key" in body and ("invalid" in body or "missing" in body)) or status == 401 else "request_rejected"
            elif status >= 400:
                observation["status"] = "http_error"
            else:
                try:
                    value = response.json()
                    if isinstance(value, dict) and isinstance(value.get("hits"), list):
                        observation.update(status="ok", returned_hits=len(value["hits"]))
                    else:
                        observation["status"] = "response_incompatible"
                except ValueError:
                    observation["status"] = "non_json_response"
            observations.append(observation)
        return response

    unique = {}
    material.requests.get = observed_get
    try:
        for term in terms:
            before = len(observations)
            items = material._search_videos_with_cache(provider="pixabay", search_videos=material.search_videos_pixabay, search_term=term, minimum_duration=5, video_aspect=VideoAspect.portrait)
            current = observations[before:]
            entry = {"search_term": term, "candidate_count": len(items), "upstream_cache_hit": not current}
            if current:
                entry["http"] = current[-1]
            report["terms"].append(entry)
            for item in items:
                unique.setdefault(item.url, item)
            failure = next((item["status"] for item in current if item["status"] != "ok"), None)
            if failure:
                report["status"] = failure
                break
        else:
            report["status"] = "passed" if unique else "no_matching_videos" if any(o.get("returned_hits", 0) for o in observations) else "no_results"
        report["matched_count"] = len(unique)
        report["search_network_calls"] = len(observations)
        if download_one and report["status"] == "passed":
            item = next(iter(unique.values()))
            parsed = urlsplit(item.url)
            if not parsed.hostname or not (parsed.hostname == "pixabay.com" or parsed.hostname.endswith(".pixabay.com")) or not parsed.path.lower().endswith(".mp4"):
                return {**report, "status": "download_url_incompatible"}
            saved = material.save_video(item.url)
            if not saved:
                return {**report, "status": "download_failed"}
            from moviepy import VideoFileClip
            with VideoFileClip(saved) as clip:
                clip.get_frame(0)
                report["download"] = {"relative_path": str(Path(saved).resolve().relative_to(mpt_dir.resolve())), "bytes": Path(saved).stat().st_size, "duration_seconds": clip.duration, "width": clip.w, "height": clip.h, "fps": clip.fps, "format": "mp4", "url_scheme": parsed.scheme, "url_host": parsed.hostname, "sha256": hashlib.sha256(Path(saved).read_bytes()).hexdigest(), "source_page": public_page(item.source_info.get("source_page")) if isinstance(item.source_info, dict) else None}
        return report
    finally:
        material.requests.get = original_get


def main() -> int:
    parser = argparse.ArgumentParser(description="固定 1.3.6 Pixabay 检索和单素材下载，不调用 LLM 或创建视频")
    parser.add_argument("--mpt-dir", type=Path, default=Path(os.environ.get("CONTENTFLOW_MPT_DIR") or Path(__file__).resolve().parents[2] / "MoneyPrinterTurbo"))
    parser.add_argument("--terms-file", type=Path, required=True)
    parser.add_argument("--download-one", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        terms = json.loads(args.terms_file.read_text(encoding="utf-8"))["video_terms"]
        import re
        if not isinstance(terms, list) or not 1 <= len(terms) <= 4 or any(not isinstance(t, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9 ,'\-]{1,79}", t) for t in terms):
            raise ValueError("Invalid terms")
        with redirect_stdout(Discard()), redirect_stderr(Discard()):
            report = run_probe(args.mpt_dir, terms, args.download_one)
    except Exception as exc:
        report = {"source": "pixabay", "status": "probe_error", "error_type": type(exc).__name__, "matched_count": 0}
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    print(text)
    return 0 if report["status"] == "passed" else 2 if report["status"] == "missing_key" else 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
