"""在 MPT 独立环境内，以模拟 HTTP 验证固定源码，绝不访问真实素材 API。"""

from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

import os

MPT_DIR = Path(os.environ.get("CONTENTFLOW_MPT_DIR") or Path(__file__).resolve().parents[2] / "MoneyPrinterTurbo")
sys.path.insert(0, str(MPT_DIR))
from app.models.schema import VideoAspect
from app.services import material
import requests


class MaterialContractTests(unittest.TestCase):
    def call(self, value=None, error=None):
        response = Mock()
        response.json.return_value = value
        with patch.object(material, "get_api_key", return_value="test-placeholder-not-a-real-key"), patch.object(material.requests, "get", return_value=response, side_effect=error) as request:
            result = material.search_videos_pexels("forest sunlight", 5, VideoAspect.portrait)
            request.assert_called_once()
            self.assertEqual(request.call_args.kwargs["timeout"], (30, 60))
            return result

    def test_no_results_returns_empty(self):
        self.assertEqual(self.call({"videos": []}), [])

    def test_timeout_returns_empty_without_switching_service(self):
        self.assertEqual(self.call(error=requests.Timeout("simulated network timeout")), [])

    def test_auth_error_shaped_response_returns_empty(self):
        self.assertEqual(self.call({"error": "Unauthorized"}), [])

    def test_exact_rendition_filter_and_source_mapping(self):
        value = {"videos": [{"id": 123, "duration": 8, "url": "https://www.pexels.com/video/123/", "user": {"name": "Test Author", "url": "https://www.pexels.com/@example"}, "video_files": [{"width": 1080, "height": 1920, "link": "https://example.invalid/test.mp4"}]}]}
        items = self.call(value)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].source_info["search_term"], "forest sunlight")
        value["videos"][0]["video_files"][0]["width"] = 720
        value["videos"][0]["video_files"][0]["height"] = 1280
        self.assertEqual(self.call(value), [])


class PixabayContractTests(unittest.TestCase):
    def call(self, value=None, status=200, error=None, content_type="application/json"):
        response = Mock(status_code=status, headers={"content-type": content_type}, text=json_text(value))
        response.json.return_value = value
        with patch.object(material, "get_api_key", return_value="test-key-not-real"), patch.object(material.requests, "get", return_value=response, side_effect=error) as request:
            result = material.search_videos_pixabay("waterfall", 5, VideoAspect.portrait)
            request.assert_called_once()
            self.assertEqual(request.call_args.kwargs["timeout"], (30, 60))
            from urllib.parse import urlsplit, parse_qs
            parsed = urlsplit(request.call_args.args[0])
            self.assertEqual(parsed.path, "/api/videos/")
            self.assertEqual(parse_qs(parsed.query)["q"], ["waterfall"])
            return result

    def test_request_and_vertical_selection(self):
        value = {"hits": [{"id": 44, "duration": 10, "pageURL": "https://pixabay.com/videos/id-44/", "user": "Author", "user_id": 7, "videos": {"large": {"width": 1080, "height": 1920, "url": "https://cdn.pixabay.com/video/test.mp4"}}}]}
        self.assertEqual(len(self.call(value)), 1)
        value["hits"][0]["videos"]["large"].update(width=1920, height=1080)
        self.assertEqual(self.call(value), [])

    def test_empty_result(self):
        self.assertEqual(self.call({"hits": []}), [])

    def test_http_rejections_and_rate_limit(self):
        for status in (400, 401, 403, 429, 500):
            with self.subTest(status=status):
                self.assertEqual(self.call({}, status=status), [])

    def test_network_failure(self):
        self.assertEqual(self.call(error=requests.Timeout("simulated")), [])

    def test_non_json_reply(self):
        response = Mock(status_code=200, headers={"content-type": "text/plain"}, text="unexpected")
        response.json.side_effect = ValueError()
        with patch.object(material, "get_api_key", return_value="test-key-not-real"), patch.object(material.requests, "get", return_value=response):
            self.assertEqual(material.search_videos_pixabay("waterfall", 5, VideoAspect.portrait), [])


def json_text(value):
    import json
    return json.dumps(value)


class ProbePrivacyTests(unittest.TestCase):
    def probe(self, status, body, text):
        import importlib.util
        path = Path(__file__).with_name("probe_pixabay.py")
        spec = importlib.util.spec_from_file_location("pixabay_probe_contract", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        from app.config import config
        response = Mock(status_code=status, headers={"content-type": "application/json"}, text=text)
        response.json.return_value = body

        def search(**kwargs):
            return kwargs["search_videos"](kwargs["search_term"], kwargs["minimum_duration"], kwargs["video_aspect"])

        with patch.dict(config.app, {"pixabay_api_keys": ["test-confidential-placeholder"]}), patch.object(material.requests, "get", return_value=response), patch.object(material, "_search_videos_with_cache", side_effect=search):
            return module.run_probe(MPT_DIR, ["waterfall"], False)

    def test_error_is_classified_without_url_body_or_key(self):
        report = self.probe(400, {}, "invalid key test-confidential-placeholder")
        self.assertEqual(report["status"], "invalid_key")
        self.assertEqual(report["search_network_calls"], 1)
        self.assertNotIn("test-confidential-placeholder", json_text(report))
        self.assertNotIn("key=", json_text(report))

    def test_raw_hits_and_usable_hits_are_different(self):
        report = self.probe(200, {"hits": [{"id": 1, "duration": 10, "videos": {"large": {"width": 1920, "height": 1080, "url": "https://cdn.pixabay.com/unused.mp4"}}}]}, "{}")
        self.assertEqual(report["status"], "no_matching_videos")
        self.assertEqual(report["terms"][0]["http"]["returned_hits"], 1)
        self.assertEqual(report["matched_count"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
