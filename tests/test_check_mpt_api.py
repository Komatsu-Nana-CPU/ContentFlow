"""模拟 HTTP 响应，不依赖 MoneyPrinterTurbo 或外部网络。"""

import io
import http.client
import json
import socket
import ssl
import unittest
from unittest.mock import Mock
from urllib.error import HTTPError, URLError

from scripts.check_mpt_api import (
    MAX_DOCUMENT_BYTES,
    NoRedirect,
    check_api,
    main,
    openapi_url,
)


def valid_document():
    # 手写期望接口，避免直接复制实现常量导致测试随错误一起变化。
    return {"openapi": "3.1.0", "paths": {
        "/api/v1/scripts": {"post": {}},
        "/api/v1/video_materials": {"post": {}, "get": {}},
        "/api/v1/videos": {"post": {}},
        "/api/v1/tasks/{task_id}": {"get": {}},
        "/api/v1/download/{file_path}": {"get": {}},
        "/api/v1/stream/{file_path}": {"get": {}},
    }}


def fake_opener(body, status=200):
    response = io.BytesIO(body)
    response.status = status
    return Mock(open=Mock(return_value=response))


class CheckerTests(unittest.TestCase):
    def test_success_uses_only_one_get(self):
        opener = fake_opener(json.dumps(valid_document()).encode())
        self.assertEqual(check_api("http://localhost:8080/", opener=opener).code, 0)
        opener.open.assert_called_once()
        request = opener.open.call_args.args[0]
        self.assertEqual(request.get_method(), "GET")
        self.assertEqual(request.full_url, "http://localhost:8080/openapi.json")
        self.assertIsNone(request.data)
        self.assertFalse(request.has_header("X-api-key"))

    def test_proxy_prefix(self):
        self.assertEqual(openapi_url("https://example.org/mpt/"), "https://example.org/mpt/openapi.json")

    def test_missing_path_and_wrong_method(self):
        for kind in ("missing", "method", "malformed"):
            doc = valid_document()
            doc["paths"]["/api/v1/videos"] = {"get": {}} if kind == "method" else {"post": None}
            if kind == "missing":
                del doc["paths"]["/api/v1/videos"]
            result = check_api("http://localhost", opener=fake_opener(json.dumps(doc).encode()))
            self.assertEqual(result.code, 8)
            self.assertTrue(any("缺失" in text and "视频生成" in text for text in result.messages))

    def test_invalid_documents(self):
        for body in (b"<html>login</html>", b"[]", b"{}", b'\xff',
                     b'{"openapi":"3.1.0","paths":[]}', b'{"swagger":"2.0","paths":{}}'):
            with self.subTest(body=body):
                self.assertEqual(check_api("http://localhost", opener=fake_opener(body)).code, 7)

    def test_oversized_response(self):
        self.assertEqual(check_api("http://localhost", opener=fake_opener(b" " * (MAX_DOCUMENT_BYTES + 1))).code, 7)

    def test_http_failures_hide_body_and_url(self):
        for status in (301, 401, 403, 404, 500):
            error = HTTPError("http://localhost/private", status, "private-content", {}, io.BytesIO(b"private-content"))
            result = check_api("http://localhost", opener=Mock(open=Mock(side_effect=error)))
            self.assertEqual(result.code, 6)
            self.assertNotIn("private-content", str(result))
            self.assertNotIn("/private", str(result))

    def test_network_failures(self):
        for error, expected in (
            (ConnectionRefusedError(10061, "hidden"), 3),
            (socket.gaierror(-2, "hidden"), 4),
            (TimeoutError("hidden"), 5),
            (PermissionError(10013, "hidden"), 9),
            (OSError(101, "hidden"), 4),
            (ssl.SSLError("hidden"), 4),
        ):
            with self.subTest(expected=expected, error=type(error)):
                result = check_api("http://localhost", opener=Mock(open=Mock(side_effect=URLError(error))))
                self.assertEqual(result.code, expected)
                self.assertNotIn("hidden", str(result))

    def test_direct_timeout(self):
        self.assertEqual(check_api("http://localhost", opener=Mock(open=Mock(side_effect=TimeoutError()))).code, 5)

    def test_broken_http_response(self):
        opener = Mock(open=Mock(side_effect=http.client.IncompleteRead(b"private-content")))
        result = check_api("http://localhost", opener=opener)
        self.assertEqual(result.code, 4)
        self.assertNotIn("private-content", str(result))

    def test_non_200_response(self):
        self.assertEqual(check_api("http://localhost", opener=fake_opener(b"", 204)).code, 6)

    def test_invalid_configuration_never_sends_request(self):
        for url in ("file:///tmp/a", "http://user:placeholder@localhost", "http://localhost?token=placeholder",
                    "http://localhost/#fragment", "http://localhost:bad", "http://localhost:99999",
                    "http://localhost:0", "http://localhost\n", "http://localhost\\path", "http://"):
            opener = Mock()
            result = check_api(url, opener=opener)
            self.assertEqual(result.code, 2)
            opener.open.assert_not_called()
            self.assertNotIn("placeholder", str(result))

    def test_invalid_timeouts(self):
        for timeout in (0, -1, float("nan"), float("inf")):
            opener = Mock()
            self.assertEqual(check_api("http://localhost", timeout, opener).code, 2)
            opener.open.assert_not_called()

    def test_redirect_is_not_followed(self):
        self.assertIsNone(NoRedirect().redirect_request(None, None, 302, "", {}, "http://other"))

    def test_cli_exit_code_and_chinese_output(self):
        from unittest.mock import patch
        from scripts.check_mpt_api import CheckResult
        with patch("scripts.check_mpt_api.check_api", return_value=CheckResult(8, ("接口缺失",))), patch("sys.stdout", new_callable=io.StringIO) as out:
            self.assertEqual(main([]), 8)
            self.assertIn("接口缺失", out.getvalue())


if __name__ == "__main__":
    unittest.main()
