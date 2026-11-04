"""只在本机读取指定凭证，不回显，不自动读取 .env。"""

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import tempfile
import tomllib
from urllib.parse import urlsplit

from contentflow.domain import FlowError

ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Settings:
    root: Path = ROOT
    mpt_dir: Path = ROOT.parent / "MoneyPrinterTurbo"
    mpt_url: str = "http://127.0.0.1:8080"
    deepseek_key: str = field(default="", repr=False)
    mpt_key: str = field(default="", repr=False)
    pexels_ready: bool = False
    pixabay_ready: bool = False
    edge_ready: bool = False
    auto_publish: bool = False
    font_path: Path = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts/msyhbd.ttc"
    ffmpeg_path: Path | None = None

    @property
    def mpt_python(self) -> Path:
        return self.mpt_dir / ".venv/Scripts/python.exe"

    @property
    def data_dir(self) -> Path:
        return self.root / "runtime/contentflow"

    def source_ready(self, source: str) -> bool:
        return source == "pixabay" and self.pixabay_ready


def local_url(value: str) -> str:
    if not isinstance(value, str) or any(ord(c) <= 32 or ord(c) == 127 for c in value):
        raise FlowError("config", "视频服务地址含无效字符。")
    try:
        p = urlsplit(value)
        valid = p.scheme == "http" and p.hostname in {"127.0.0.1", "localhost", "::1"} and p.port != 0
        valid = valid and p.username is None and p.password is None and not (p.query or p.fragment or p.path.strip("/"))
    except ValueError:
        valid = False
    if not valid:
        raise FlowError("config", "视频服务必须为不含凭证、路径或查询参数的本机 HTTP 地址。")
    return value.rstrip("/")


def _key_present(value: object) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    return isinstance(value, list) and any(isinstance(v, str) and v.strip() for v in value)


def load_settings(root: Path = ROOT, mpt_dir: Path | None = None) -> Settings:
    root = Path(os.environ.get("CONTENTFLOW_ROOT", str(root))).resolve()
    try:
        path = root / "config.local.json"
        local = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        mpt_dir = Path(mpt_dir or os.environ.get("CONTENTFLOW_MPT_DIR") or local.get("mpt_dir") or root.parent / "MoneyPrinterTurbo").expanduser().resolve()
        upstream = mpt_dir / "config.toml"
        app = tomllib.loads(upstream.read_text(encoding="utf-8")).get("app", {}) if upstream.exists() else {}
        font_path = os.environ.get("CONTENTFLOW_FONT_PATH") or local.get("font_path") or str(Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts/msyhbd.ttc")
        ffmpeg_path = os.environ.get("CONTENTFLOW_FFMPEG_PATH") or local.get("ffmpeg_path") or app.get("ffmpeg_path")
        return Settings(
            root=root, mpt_dir=mpt_dir,
            mpt_url=local_url(local.get("mpt_url", "http://127.0.0.1:8080")),
            deepseek_key=os.environ.get("DEEPSEEK_API_KEY", "") or local.get("deepseek_api_key", "") or app.get("deepseek_api_key", ""),
            mpt_key=os.environ.get("MPT_API_KEY", "") or app.get("api_key", ""),
            pexels_ready=_key_present(app.get("pexels_api_keys")),
            pixabay_ready=_key_present(app.get("pixabay_api_keys")),
            edge_ready=app.get("subtitle_provider", "edge") == "edge",
            auto_publish=bool(app.get("upload_post_enabled") or app.get("upload_post_auto_upload")),
            font_path=Path(font_path).expanduser().resolve(),
            ffmpeg_path=Path(ffmpeg_path).expanduser().resolve() if ffmpeg_path else None,
        )
    except (OSError, ValueError, TypeError):
        raise FlowError("config", "本机私有配置无法解析，请检查配置文件格式；不会展示其中内容。") from None


def atomic_private_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".private-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def save_credentials(settings: Settings, deepseek: str, pexels: str, pixabay: str) -> bool:
    """空输入保留旧值；只在用户点击保存时写入指定私有配置。"""
    import toml

    if any("\n" in key or "\r" in key for key in (deepseek, pexels, pixabay)):
        raise FlowError("config", "密钥不能包含换行。")
    try:
        config_path = settings.mpt_dir / "config.toml"
        value = tomllib.loads(config_path.read_text(encoding="utf-8"))
        app = value.setdefault("app", {})
        if deepseek.strip():
            app.update(deepseek_api_key=deepseek.strip(), llm_provider="deepseek", deepseek_model_name="deepseek-flash")
        if pexels.strip():
            app["pexels_api_keys"] = [pexels.strip()]
        if pixabay.strip():
            app["pixabay_api_keys"] = [pixabay.strip()]
        if any(k.strip() for k in (deepseek, pexels, pixabay)):
            atomic_private_write(config_path, toml.dumps(value))
        return bool(pexels.strip() or pixabay.strip())
    except (OSError, ValueError, TypeError):
        raise FlowError("config", "保存本机配置失败；未显示凭证。请检查部署目录及写入权限。") from None
