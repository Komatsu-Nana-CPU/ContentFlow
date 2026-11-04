"""只读检查Git公开候选；可显式更新逐文件清单，不暂存/提交。"""

import argparse
import json
from pathlib import Path
import re
import subprocess
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]


def git(*args: str) -> bytes:
    result = subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, check=True)
    return result.stdout


def check() -> dict:
    candidates = sorted(set(p.decode("utf-8") for p in git("ls-files", "--cached", "--others", "--exclude-standard", "-z").split(b"\0") if p))
    banned = []
    sensitive = []
    large = []
    missing = []
    local_only = []
    known = set(candidates)
    patterns = [re.compile(r"\bsk-[A-Za-z0-9_-]{24,}"), re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}"),
                re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
                re.compile(r"(?:姓名|学号)\s*[：:]\s*[^\s，,；;。`]{2,}"),
                re.compile(r"(?<![A-Za-z0-9])0[0-9]{8}(?![A-Za-z0-9])")]
    for name in candidates:
        path = ROOT / name
        if not path.is_file():
            banned.append(name)
            continue
        parts = Path(name).parts
        private_name = ((path.name.startswith(".env") and path.name != ".env.example")
                        or path.name.startswith(("config.local.", "secrets.", "credentials"))
                        or path.name == "config.toml" and name != ".streamlit/config.toml")
        if any(p in {"runtime", "storage", ".venv", ".bootstrap", ".uv-cache", ".tools", "__pycache__"} for p in parts) or path.suffix.lower() in {".docx", ".pdf", ".mp4", ".mp3", ".wav", ".sqlite", ".sqlite3", ".db", ".log", ".zip", ".pem", ".key"} or private_name or name.startswith("docs/课程项目报告") or name == "docs/报告证据核验清单.md":
            banned.append(name)
        if path.stat().st_size > 5 * 1024 * 1024:
            large.append(name)
        if private_name or path.suffix not in {".py", ".md", ".txt", ".json", ".toml"}:
            continue
        content = path.read_text(encoding="utf-8-sig")
        if any(p.search(content) for p in patterns):
            sensitive.append(name)
        if path.suffix != ".md":
            continue
        for target in re.findall(r"\]\(([^)]+)\)", content):
            target = unquote(target.split("#", 1)[0].strip("<>"))
            if not target or "://" in target or target.startswith("mailto:"):
                continue
            destination = (path.parent / target).resolve()
            if not destination.is_relative_to(ROOT):
                local_only.append({"document": name, "target": target})
                continue
            relative = destination.relative_to(ROOT).as_posix()
            if relative not in known:
                (local_only if destination.exists() else missing).append({"document": name, "target": target})
    return {"candidate_files": candidates, "candidate_count": len(candidates), "forbidden_paths": banned,
            "limited_sensitive_pattern_paths": sensitive, "files_over_5MiB": large,
            "missing_local_links": missing, "links_to_local_only_files": local_only,
            "tracked_count": len([p for p in git("ls-files", "-z").split(b"\0") if p]),
            "staged_count": len(git("diff", "--cached", "--name-only").splitlines()),
            "remotes_count": len(git("remote").splitlines()),
            "scope": "Git candidates and limited patterns only; no credentials/config values read, no automatic staging or publication; cannot guarantee all secrets detected"}


def main() -> int:
    parser = argparse.ArgumentParser(description="检查公开候选文件，不读取私有配置")
    parser.add_argument("--write-list", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = check()
    passed = not any(report[k] for k in ("forbidden_paths", "limited_sensitive_pattern_paths", "files_over_5MiB", "missing_local_links", "links_to_local_only_files"))
    report["passed"] = passed
    if args.write_list and passed:
        (ROOT / "docs/公开文件清单.txt").write_text("\n".join(report["candidate_files"]) + "\n", encoding="utf-8")
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "candidate_files"}, ensure_ascii=False, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
