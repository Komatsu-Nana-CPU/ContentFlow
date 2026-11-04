"""配置机器路径；仅显式初始化时新建上游私有配置，不覆盖既有文件。"""

import argparse
import json
from pathlib import Path
import sys
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contentflow.domain import FlowError
from contentflow.settings import ROOT, atomic_private_write, local_url


def configure(root: Path, mpt_dir: Path, font_path: Path, ffmpeg_path: Path | None,
              base_url: str, init_mpt_config: bool = False) -> None:
    base_url = local_url(base_url)
    mpt_dir = mpt_dir.expanduser().resolve()
    font_path = font_path.expanduser().resolve()
    if not (mpt_dir / "main.py").is_file() or not font_path.is_file():
        raise FlowError("config", "请检查上游目录中的 main.py 和已安装中文字体路径。")
    if ffmpeg_path is not None:
        ffmpeg_path = ffmpeg_path.expanduser().resolve()
        if not ffmpeg_path.is_file():
            raise FlowError("config", "指定的 FFmpeg 文件不存在。")
    upstream = mpt_dir / "config.toml"
    if init_mpt_config:
        # x 模式避免意外覆盖；已有配置不读取、不复制、不输出。
        import toml
        address = urlsplit(base_url)
        value = {"listen_host": address.hostname, "listen_port": address.port or 80,
                 "app": {"llm_provider": "deepseek", "deepseek_model_name": "deepseek-flash",
                         "deepseek_base_url": "https://api.deepseek.com", "deepseek_api_key": "",
                         "pixabay_api_keys": [], "subtitle_provider": "edge", "max_concurrent_tasks": 1, "enable_redis": False,
                         "upload_post_enabled": False, "upload_post_auto_upload": False}}
        if ffmpeg_path:
            value["app"]["ffmpeg_path"] = str(ffmpeg_path)
        with upstream.open("x", encoding="utf-8") as handle:
            handle.write(toml.dumps(value))
    destination = root / "config.local.json"
    value = json.loads(destination.read_text(encoding="utf-8")) if destination.exists() else {}
    value.update(mpt_dir=str(mpt_dir), font_path=str(font_path), mpt_url=base_url,
                 ffmpeg_path=str(ffmpeg_path) if ffmpeg_path else "")
    atomic_private_write(destination, json.dumps(value, ensure_ascii=False, indent=2))


def main() -> int:
    parser = argparse.ArgumentParser(description="配置 ContentFlow 机器路径，不接收或显示密钥")
    parser.add_argument("--mpt-dir", type=Path, required=True)
    parser.add_argument("--font-path", type=Path, required=True)
    parser.add_argument("--ffmpeg-path", type=Path)
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--init-mpt-config", action="store_true", help="仅首次新建上游配置，已存在则停止；上游端口默认8080")
    args = parser.parse_args()
    try:
        configure(ROOT, args.mpt_dir, args.font_path, args.ffmpeg_path, args.base_url, args.init_mpt_config)
    except FileExistsError:
        print("已有 MoneyPrinterTurbo config.toml，未覆盖；请去掉 --init-mpt-config 后重试。")
        return 2
    except (OSError, ValueError, TypeError, FlowError):
        print("本机配置未完成，请检查目录、字体、地址、配置格式和写权限；不展示配置内容。")
        return 2
    print("机器路径已保存到被 Git 忽略的 config.local.json；未打印或复制任何密钥。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
