import io
import json
from pathlib import Path
import unittest
import tempfile
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError

from contentflow.deepseek import generate_content
from contentflow.domain import FlowError, video_payload
from contentflow.http_client import ApiError, HttpClient
from contentflow.mpt import MptClient, safe_task_error
from contentflow.settings import Settings
from test_domain_settings import sample


class Response(io.BytesIO):
    status = 200


class ClientTests(unittest.TestCase):
    def test_download_storage_errors_are_safe_and_preserve_existing_video(self):
        identity = "243f9893-0914-4b26-8057-dcff096c97d2"
        private_error = OSError("private-path-and-secret")
        for target in ("pathlib.Path.mkdir", "tempfile._TemporaryFileWrapper.write", "pathlib.Path.replace"):
            # 写入句柄的write通过真实临时文件代理注入，不依赖内部包装类属性。
            with self.subTest(stage=target), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                existing = root / (identity + ".mp4")
                existing.write_bytes(b"existing-approved-sample")
                http = Mock()
                http.request.return_value = b"\x00\x00\x00\x18ftypmp42test"
                client = MptClient(Settings(), http)
                if target.endswith(".write"):
                    original = tempfile.NamedTemporaryFile

                    def failing_file(**kwargs):
                        handle = original(**kwargs)
                        wrapper = Mock(wraps=handle)
                        wrapper.name = handle.name
                        wrapper.__enter__ = Mock(return_value=wrapper)
                        wrapper.__exit__ = Mock(side_effect=lambda *args: handle.close())
                        wrapper.write.side_effect = private_error
                        return wrapper

                    context = patch("contentflow.mpt.tempfile.NamedTemporaryFile", side_effect=failing_file)
                else:
                    context = patch(target, side_effect=private_error)
                with context, self.assertRaises(FlowError) as raised:
                    client.download(identity, f"/tasks/{identity}/final-1.mp4", root)
                self.assertEqual(raised.exception.code, "download_storage")
                self.assertNotIn("private", str(raised.exception))
                self.assertEqual(existing.read_bytes(), b"existing-approved-sample")
                self.assertEqual(list(root.glob("*.part")), [])
                http.request.assert_called_once()

    def test_single_flash_json_call_never_auto_retries(self):
        client = Mock()
        client.json.return_value = {"model": "deepseek-flash", "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(sample().as_dict())}}], "usage": {"total_tokens": 300}}
        result = generate_content("森林", "test-private-only", client)
        self.assertEqual(result.content, sample())
        body = client.json.call_args.kwargs["body"]
        self.assertEqual(body["model"], "deepseek-flash")
        self.assertEqual(body["thinking"], {"type": "disabled"})
        self.assertEqual(body["response_format"], {"type": "json_object"})
        self.assertLessEqual(body["max_tokens"], 1200)
        client.json.assert_called_once()

    def test_missing_key_invalid_output_pro_and_length_stop(self):
        client = Mock()
        with self.assertRaises(FlowError):
            generate_content("森林", "", client)
        client.json.assert_not_called()
        for choice, model in (({"finish_reason": "stop", "message": {"content": "not json"}}, "deepseek-flash"), ({"finish_reason": "length"}, "deepseek-flash"), ({"finish_reason": "stop", "message": {"content": json.dumps(sample().as_dict())}}, "deepseek-v4-pro")):
            client.reset_mock()
            client.json.return_value = {"choices": [choice], "model": model}
            with self.assertRaises(FlowError):
                generate_content("森林", "test-only", client)
            client.json.assert_called_once()

    def test_transport_hides_error_body_and_marks_uncertain(self):
        for exception in (HTTPError("http://localhost", 500, "test-private-secret", {}, io.BytesIO(b"private")), URLError(TimeoutError())):
            opener = Mock()
            opener.open.side_effect = exception
            with self.assertRaises(ApiError) as raised:
                HttpClient(opener).json("http://localhost", body={"test": True})
            self.assertTrue(raised.exception.uncertain)
            self.assertNotIn("private", str(raised.exception))
            opener.open.assert_called_once()

    def test_authorization_rejection_is_not_uncertain(self):
        opener = Mock()
        opener.open.side_effect = HTTPError("http://localhost", 401, "hidden", {}, None)
        with self.assertRaises(ApiError) as raised:
            HttpClient(opener).json("http://localhost", body={})
        self.assertFalse(raised.exception.uncertain)

    def test_invalid_credential_header_never_leaks_or_sends(self):
        opener = Mock()
        for value in ("Bearer test-private\nheader", "Bearer \u79d8\u5bc6"):
            with self.assertRaises(ApiError) as raised:
                HttpClient(opener).json("https://api.deepseek.com/chat/completions", headers={"Authorization": value}, body={})
            self.assertNotIn(value, str(raised.exception))
        opener.open.assert_not_called()

    def test_malformed_task_responses_are_controlled(self):
        http = Mock()
        http.json.return_value = {"data": "unexpected"}
        client = MptClient(Settings(), http)
        with self.assertRaises(ApiError) as raised:
            client.submit({})
        self.assertTrue(raised.exception.uncertain)
        with self.assertRaises(FlowError):
            client.status("243f9893-0914-4b26-8057-dcff096c97d2")

    def test_download_path_traversal_remote_and_wrong_task_rejected(self):
        http = Mock()
        client = MptClient(Settings(), http)
        identity = "243f9893-0914-4b26-8057-dcff096c97d2"
        for path in ("https://evil.test/tasks/" + identity + "/final-1.mp4", f"/tasks/{identity}/../../config.toml", "/tasks/wrong/final-1.mp4", f"/tasks/{identity}/final-1.mp4?key=private"):
            with self.assertRaises(FlowError):
                client.download(identity, path, Path("unused"))
        http.request.assert_not_called()

    def test_exact_version_and_payload_fields(self):
        http = Mock()
        http.json.return_value = {"info": {"version": "1.3.9"}}
        with self.assertRaises(FlowError):
            MptClient(Settings(), http).check_schema(video_payload("森林", sample(), "pixabay"))

    def test_source_manifest_whitelist_strips_credentials_and_queries(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            identity = "243f9893-0914-4b26-8057-dcff096c97d2"
            path = root / "storage/tasks" / identity / "script.json"
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps({"params": {"secret": "test-private-not-public"}, "material_sources": [{"provider": "pexels", "search_term": "forest trail", "source_page": "https://www.pexels.com/video/123/?key=test-private", "creator": {"name": "Author", "profile_page": "https://user:password@www.pexels.com/@test"}, "download_url": "https://example.invalid/private"}]}), encoding="utf-8")
            sources = MptClient(Settings(mpt_dir=root)).material_sources(identity)
            self.assertEqual(sources[0]["source_page"], "https://www.pexels.com/video/123/")
            self.assertIsNone(sources[0]["creator_page"])
            self.assertNotIn("test-private", json.dumps(sources))
            self.assertNotIn("download_url", sources[0])


if __name__ == "__main__":
    unittest.main()
