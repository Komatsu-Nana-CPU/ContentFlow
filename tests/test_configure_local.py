import json
from pathlib import Path
import tempfile
import unittest

from scripts.configure_local import configure


class ConfigureTests(unittest.TestCase):
    def test_initial_config_is_local_and_existing_credentials_are_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            engine = root / "engine"
            engine.mkdir()
            (engine / "main.py").touch()
            font = root / "font.ttc"
            font.touch()
            configure(root, engine, font, None, "http://127.0.0.1:8080", True)
            original = (engine / "config.toml").read_bytes()
            self.assertIn(b'listen_host = "127.0.0.1"', original)
            self.assertIn(b'deepseek_model_name = "deepseek-flash"', original)
            with self.assertRaises(FileExistsError):
                configure(root, engine, font, None, "http://127.0.0.1:8080", True)
            configure(root, engine, font, None, "http://127.0.0.1:8080")
            self.assertEqual((engine / "config.toml").read_bytes(), original)
            local = json.loads((root / "config.local.json").read_text(encoding="utf-8"))
            self.assertEqual(local["mpt_dir"], str(engine))
            self.assertNotIn("api_key", local)
