import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from contentflow.repository import Repository
from contentflow.deepseek import Generation
from test_domain_settings import sample

ROOT = Path(__file__).resolve().parents[1]


class AppTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.environment = patch.dict(os.environ, {"CONTENTFLOW_ROOT": str(self.root), "CONTENTFLOW_MPT_DIR": str(self.root / "no-upstream"), "DEEPSEEK_API_KEY": "", "MPT_API_KEY": ""})
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def test_missing_keys_block_generation_without_network(self):
        with patch("contentflow.deepseek.HttpClient") as http:
            app = AppTest.from_file(str(ROOT / "app.py")).run(timeout=15)
            self.assertEqual(len(app.exception), 0)
            buttons = {b.label: b for b in app.button}
            self.assertTrue(buttons["生成脚本与画面关键词"].disabled)
            http.assert_not_called()

    def test_edit_invalidates_approval_and_source_is_online(self):
        repo = Repository(self.root / "runtime/contentflow/contentflow.sqlite3")
        identity = repo.new_draft("森林", sample())
        repo.confirm(identity, "森林", sample(), "pixabay")
        app = AppTest.from_file(str(ROOT / "app.py")).run(timeout=15)
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(app.selectbox(key="edit_source").value, "pixabay")
        app.text_area(key="edit_script").set_value("修改后的中文旁白，仍需再次人工确认。").run()
        self.assertEqual(len(app.exception), 0)
        self.assertFalse(app.checkbox(key="review_check").value)
        self.assertTrue(next(b for b in app.button if b.label == "开始生成视频").disabled)

    def test_mocked_full_ui_review_submit_progress_and_download(self):
        upstream = self.root / "no-upstream"
        upstream.mkdir()
        (upstream / "config.toml").write_text('[app]\ndeepseek_api_key="test-private-model-placeholder"\npixabay_api_keys=["test-stock-placeholder"]\nsubtitle_provider="edge"\n', encoding="utf-8")
        task_id = "243f9893-0914-4b26-8057-dcff096c97d2"
        path = self.root / "runtime/contentflow/videos" / (task_id + ".mp4")
        path.parent.mkdir(parents=True)
        path.write_bytes(b"mock-mp4-for-ui-test-only")
        with patch("contentflow.deepseek.generate_content", return_value=Generation(sample(), {"total_tokens": 100}, "deepseek-flash")) as generate, patch("contentflow.mpt.MptClient") as client_type, patch("contentflow.materials.MaterialsService") as materials_type:
            materials_type.return_value.search.return_value = {"source": "pixabay", "status": "passed", "matched_count": 4}
            client = client_type.return_value
            client.submit.return_value = task_id
            client.status.return_value = {"task_id": task_id, "state": 1, "progress": 100, "videos": [f"/tasks/{task_id}/final-1.mp4"]}
            client.download.return_value = (path, {"duration_seconds": 20.0, "width": 1080, "height": 1920, "bytes": 12345})
            client.material_sources.return_value = []
            app = AppTest.from_file(str(ROOT / "app.py")).run(timeout=15)
            app.text_input(key="new_topic").set_value("森林").run()
            next(b for b in app.button if b.label == "生成脚本与画面关键词").click().run()
            self.assertEqual(len(app.exception), 0)
            app.checkbox(key="review_check").check().run()
            next(b for b in app.button if b.label == "保存并确认审核").click().run()
            self.assertFalse(next(b for b in app.button if b.label == "开始生成视频").disabled)
            next(b for b in app.button if b.label == "开始生成视频").click().run(timeout=15)
            self.assertEqual(len(app.exception), 0)
            self.assertEqual(app.radio(key="page").value, "视频任务")
            self.assertEqual(len(app.get("video")), 1)
            self.assertEqual(len(app.get("download_button")), 1)
            # 新 AppTest 会话模拟刷新/重启，从 SQLite 恢复，不依赖已移除页面的控件树。
            refreshed = AppTest.from_file(str(ROOT / "app.py"))
            refreshed.session_state["page"] = "视频任务"
            refreshed.run(timeout=15)
            self.assertEqual(len(refreshed.exception), 0)
            self.assertEqual(len(refreshed.get("video")), 1)
            generate.assert_called_once()
            client.submit.assert_called_once()
            payload = client.submit.call_args.args[0]
            self.assertEqual(payload["video_source"], "pixabay")
            self.assertEqual(payload["video_terms"], list(sample().video_terms))


if __name__ == "__main__":
    unittest.main()
