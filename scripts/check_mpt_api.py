"""只读检查 MoneyPrinterTurbo OpenAPI；不读取凭证或调用生成接口。"""

import argparse
import errno
import http.client
import json
import math
import socket
import ssl
import sys
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener


MAX_DOCUMENT_BYTES = 4 * 1024 * 1024
REQUIRED_OPERATIONS = (
    ("/api/v1/scripts", "post", "脚本生成"),
    ("/api/v1/video_materials", "post", "素材上传"),
    ("/api/v1/video_materials", "get", "素材列表"),
    ("/api/v1/videos", "post", "视频生成"),
    ("/api/v1/tasks/{task_id}", "get", "任务查询"),
    ("/api/v1/download/{file_path}", "get", "成品下载"),
    ("/api/v1/stream/{file_path}", "get", "成品预览"),
)


@dataclass(frozen=True)
class CheckResult:
    code: int
    messages: tuple[str, ...]


class NoRedirect(HTTPRedirectHandler):
    """拒绝重定向，避免悄然检查其他地址或登录页。"""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def openapi_url(base_url: str) -> str:
    """服务地址允许反向代理前缀，禁止携带身份和查询参数。"""
    if any(ord(char) <= 32 or ord(char) == 127 for char in base_url):
        raise ValueError("地址包含空白或控制字符")
    parts = urlsplit(base_url)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        raise ValueError("必须是有效的 HTTP 或 HTTPS 服务地址")
    if parts.username is not None or parts.password is not None:
        raise ValueError("地址不得包含用户名或密码")
    if parts.query or parts.fragment:
        raise ValueError("地址不得包含查询参数或片段")
    if "\\" in base_url or parts.port == 0:
        raise ValueError("服务地址无效")
    # 访问 port 属性也会校验非数字及超范围端口。
    return urlunsplit((parts.scheme, parts.netloc,
                       parts.path.rstrip("/") + "/openapi.json", "", ""))


def network_failure(reason: object) -> CheckResult:
    if isinstance(reason, (TimeoutError, socket.timeout)):
        return CheckResult(5, ("[失败] 连接或读取超时；检查服务负载和网络。",))
    if isinstance(reason, socket.gaierror):
        return CheckResult(4, ("[失败] 域名解析失败；检查服务地址和 DNS。",))
    if isinstance(reason, ssl.SSLError):
        return CheckResult(4, ("[失败] TLS 校验或握手失败；不会关闭证书验证。",))
    number = getattr(reason, "errno", None)
    winerror = getattr(reason, "winerror", None)
    if (isinstance(reason, PermissionError)
            or number in {errno.EACCES, errno.EPERM, 10013}
            or winerror == 10013):
        return CheckResult(9, ("[受限] 网络访问被系统或沙箱权限阻止，无法判断服务状态。",))
    if (isinstance(reason, ConnectionRefusedError)
            or number in {errno.ECONNREFUSED, 10061} or winerror == 10061):
        return CheckResult(3, ("[失败] 连接被拒绝：服务可能未启动、端口错误或被防火墙拒绝。",))
    return CheckResult(4, ("[失败] 网络连接失败；检查路由、防火墙及服务地址。",))


def inspect_document(document: object) -> CheckResult:
    if not isinstance(document, dict):
        return CheckResult(7, ("[失败] OpenAPI 根节点不是对象。",))
    version = document.get("openapi")
    paths = document.get("paths")
    if not isinstance(version, str) or not version.startswith("3.") or not isinstance(paths, dict):
        return CheckResult(7, ("[失败] 描述不是支持的 OpenAPI 3 文档，或 paths 无效。",))
    messages = ["[通过] 服务可访问，已取得 OpenAPI 3 描述。"]
    missing = False
    for path, method, label in REQUIRED_OPERATIONS:
        item = paths.get(path)
        found = isinstance(item, dict) and isinstance(item.get(method), dict)
        missing |= not found
        messages.append(f"[{'通过' if found else '缺失'}] {label}：{method.upper()} {path}")
    messages.append("[说明] 仅验证接口声明；未验证鉴权、请求字段兼容性、配音或视频生成能力。")
    return CheckResult(8 if missing else 0, tuple(messages))


def check_api(base_url: str, timeout: float = 5.0, opener=None) -> CheckResult:
    try:
        url = openapi_url(base_url)
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("超时必须为有限正数")
    except (ValueError, TypeError):
        return CheckResult(2, ("[失败] 配置无效：使用不含凭证、查询参数的 HTTP(S) 地址及有限正数超时。",))
    # 不使用环境代理，避免自动读取代理凭证；HTTPS 仍采用标准证书校验。
    client = opener if opener is not None else build_opener(ProxyHandler({}), NoRedirect())
    request = Request(url, headers={"Accept": "application/json"}, method="GET")
    try:
        with client.open(request, timeout=timeout) as response:
            status = response.status
            if status != 200:
                return CheckResult(6, (f"[失败] OpenAPI 返回 HTTP {status}，尚未检查接口。",))
            raw = response.read(MAX_DOCUMENT_BYTES + 1)
        if len(raw) > MAX_DOCUMENT_BYTES:
            return CheckResult(7, ("[失败] OpenAPI 文档超过 4 MiB 限制。",))
        try:
            document = json.loads(raw)
        except (ValueError, UnicodeError, RecursionError):
            return CheckResult(7, ("[失败] OpenAPI 响应不是有效 JSON；未输出响应正文。",))
        return inspect_document(document)
    except HTTPError as exc:
        if exc.code in {401, 403}:
            message = f"[受限] 服务返回 HTTP {exc.code}：可能要求鉴权或被访问策略阻止；本工具不读取凭证。"
        elif exc.code == 404:
            message = "[失败] OpenAPI 返回 HTTP 404：检查服务前缀、是否为正确服务或是否关闭了 OpenAPI。"
        elif 300 <= exc.code < 400:
            message = "[失败] OpenAPI 返回重定向；请直接配置最终服务地址。"
        else:
            message = f"[失败] 服务返回 HTTP {exc.code}，尚未检查接口。"
        exc.close()
        return CheckResult(6, (message,))
    except URLError as exc:
        return network_failure(exc.reason)
    except OSError as exc:
        return network_failure(exc)
    except http.client.HTTPException:
        return CheckResult(4, ("[失败] HTTP 传输异常或响应不完整；未输出响应正文。",))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="只读检测 MoneyPrinterTurbo API，不创建视频任务。")
    parser.add_argument("--base-url", default="http://127.0.0.1:8080", help="服务根地址，可带反向代理前缀；不得包含凭证")
    parser.add_argument("--timeout", type=float, default=5.0, help="请求超时秒数，默认 5")
    args = parser.parse_args(argv)
    result = check_api(args.base_url, args.timeout)
    print("MoneyPrinterTurbo API 连通性检测（只读）")
    for message in result.messages:
        print(message)
    print(f"检测退出码：{result.code}")
    return result.code


if __name__ == "__main__":
    # Windows 重定向输出也使用 UTF-8，确保检测结果和帮助信息可读。
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
