"""有限超时、不重定向、不回显服务器正文的 HTTP 边界。"""

import json
from http.client import HTTPException
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener

from contentflow.domain import FlowError
from scripts.check_mpt_api import NoRedirect, network_failure


class ApiError(FlowError):
    def __init__(self, code: str, message: str, uncertain: bool = False):
        super().__init__(code, message)
        self.uncertain = uncertain


class HttpClient:
    def __init__(self, opener=None):
        self.opener = opener or build_opener(ProxyHandler({}), NoRedirect())

    def request(self, url: str, *, body=None, headers=None, timeout=30, limit=2_000_000) -> bytes:
        if any(not isinstance(v, str) or any(ord(c) < 32 or ord(c) > 126 for c in v) for v in (headers or {}).values()):
            raise ApiError("config", "请求头配置无效，请检查本机凭证格式；未发出请求。")
        method = "POST" if body is not None else "GET"
        data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
        request = Request(url, data=data, method=method, headers={"Accept": "application/json", **({"Content-Type": "application/json"} if data is not None else {}), **(headers or {})})
        try:
            with self.opener.open(request, timeout=timeout) as response:
                if response.status != 200:
                    raise ApiError("http", "服务响应状态异常。", method == "POST")
                value = response.read(limit + 1)
                if len(value) > limit:
                    raise ApiError("response", "服务响应超过允许大小。", method == "POST")
                return value
        except HTTPError as error:
            code = error.code
            message = {401: "服务密钥无效或未授权。", 402: "现有账户余额不足，请停止调用；不会自动充值。", 403: "服务拒绝访问，请检查账户权限或网络。", 404: "服务未找到该接口或任务，请检查版本或重启情况。", 429: "服务限流或任务队列已满，请稍后手动重试。"}.get(code, "服务暂时失败，请检查后端；不会自动重发。")
            raise ApiError(f"http_{code}", message, method == "POST" and code >= 500) from None
        except (URLError, TimeoutError, OSError, HTTPException) as error:
            result = network_failure(getattr(error, "reason", error))
            raise ApiError("network", result.messages[0].replace("[失败] ", "").replace("[受限] ", ""), method == "POST") from None
        except (ValueError, TypeError, UnicodeError):
            raise ApiError("config", "请求配置或服务编码异常；不会展示凭证或原始响应。", method == "POST") from None

    def json(self, url: str, **kwargs) -> dict:
        try:
            value = json.loads(self.request(url, **kwargs))
        except (ValueError, UnicodeError):
            raise ApiError("response", "服务未返回有效 JSON。", kwargs.get("body") is not None) from None
        if not isinstance(value, dict):
            raise ApiError("response", "服务返回结构异常。", kwargs.get("body") is not None)
        return value
