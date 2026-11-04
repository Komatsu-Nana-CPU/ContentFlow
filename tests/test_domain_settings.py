import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from contentflow.domain import Content, FlowError, fingerprint, video_payload
from contentflow.settings import Settings, load_settings, local_url, save_credentials


def sample():
    return Content.parse({"title": "森林", "script": "走进雨后的森林，阳光穿过树叶。", "video_terms": ["forest sunlight", "rain drops leaves", "forest trail", "green trees"]})


class DomainTests(unittest.TestCase):
    def test_validation_and_approval_fingerprint(self):
        value = sample()
        with self.assertRaises(FlowError):
            fingerprint("森林", value, "pexels")
        self.assertNotEqual(fingerprint("森林", value, "pixabay"), fingerprint("山林", value, "pixabay"))
        for change in ({"script": ""}, {"video_terms": ["nature"]}, {"video_terms": ["森林"] * 4}):
            with self.subTest(change=change), self.assertRaises(FlowError):
                Content.parse({**value.as_dict(), **change})

    def test_online_payload_preserves_order_and_has_no_paid_sources(self):
        payload = video_payload("森林", sample(), "pixabay")
        self.assertEqual(payload["video_terms"], list(sample().video_terms))
        self.assertTrue(payload["match_materials_to_script"])
        self.assertEqual(payload["video_concat_mode"], "sequential")
        self.assertNotIn("video_materials", payload)
        self.assertEqual(payload["bgm_type"], "")
        with self.assertRaises(FlowError):
            video_payload("森林", sample(), "wavespeed")

    def test_backend_address_never_allows_remote_credentials(self):
        for address in ("https://evil.test", "http://user:pass@localhost", "http://localhost?key=private", "http://localhost:0"):
            with self.subTest(address=address), self.assertRaises(FlowError):
                local_url(address)


class SettingsTests(unittest.TestCase):
    def test_machine_paths_use_sibling_config_and_environment_precedence(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {}, clear=True):
            root = Path(directory) / "ContentFlow"
            root.mkdir()
            self.assertEqual(load_settings(root=root).mpt_dir, root.parent / "MoneyPrinterTurbo")
            custom = root.parent / "custom-engine"
            font = root / "font.ttc"
            binary = root / "ffmpeg.exe"
            (root / "config.local.json").write_text(json.dumps({"mpt_dir": str(custom), "font_path": str(font), "ffmpeg_path": str(binary)}), encoding="utf-8")
            loaded = load_settings(root=root)
            self.assertEqual(loaded.mpt_python, custom / ".venv/Scripts/python.exe")
            self.assertEqual(loaded.ffmpeg_path, binary)
            payload = video_payload("森林", sample(), "pixabay", loaded.font_path.as_posix())
            self.assertEqual(payload["font_name"], font.as_posix())
            with patch.dict(os.environ, {"CONTENTFLOW_MPT_DIR": str(root), "CONTENTFLOW_FONT_PATH": str(root / "other.ttf"), "CONTENTFLOW_FFMPEG_PATH": str(root / "other.exe")}):
                env = load_settings(root=root)
                self.assertEqual(env.mpt_dir, root)
                self.assertEqual(env.font_path, root / "other.ttf")
                self.assertEqual(env.ffmpeg_path, root / "other.exe")

    def test_private_save_preserves_config_and_masks_repr(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {}, clear=True):
            root = Path(directory)
            (root / "config.toml").write_text('listen_host="127.0.0.1"\n[app]\nsubtitle_provider="edge"\nmax_concurrent_tasks=1\n', encoding="utf-8")
            settings = load_settings(root=root, mpt_dir=root)
            self.assertFalse(settings.pixabay_ready)
            self.assertTrue(save_credentials(settings, "test-private-llm", "", "test-private-stock"))
            loaded = load_settings(root=root, mpt_dir=root)
            self.assertTrue(loaded.pixabay_ready)
            self.assertEqual(loaded.deepseek_key, "test-private-llm")
            self.assertNotIn("test-private", repr(loaded))
            self.assertIn("max_concurrent_tasks = 1", (root / "config.toml").read_text())
            save_credentials(loaded, "", "", "")
            self.assertEqual(load_settings(root=root, mpt_dir=root).deepseek_key, loaded.deepseek_key)


if __name__ == "__main__":
    unittest.main()
