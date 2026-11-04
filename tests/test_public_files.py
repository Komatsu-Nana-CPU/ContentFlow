from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import check_public_files as public


class PublicFilesTests(unittest.TestCase):
    def inspect(self, root, names):
        def git(*args):
            if args[:2] == ("ls-files", "--cached"):
                return ("\0".join(names) + "\0").encode("utf-8")
            return b""
        with patch.object(public, "ROOT", root), patch.object(public, "git", side_effect=git):
            return public.check()

    def test_tracked_private_files_flagged_without_reading_private_contents(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            secret = root / ".env.production"
            secret.write_bytes(b"\xff\xfe-private-config-not-utf8")
            report = self.inspect(root, [secret.name])
            self.assertEqual(report["forbidden_paths"], [secret.name])

    def test_runtime_links_detected_even_when_local_target_exists(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "runtime").mkdir()
            (root / "runtime/video.mp4").touch()
            (root / "README.md").write_text("[sample](runtime/video.mp4)", encoding="utf-8")
            report = self.inspect(root, ["README.md"])
            self.assertEqual(len(report["links_to_local_only_files"]), 1)

    def test_limited_secret_pattern_only_reports_path(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            value = "sk-" + "x" * 32
            (root / "example.txt").write_text(value, encoding="utf-8")
            report = self.inspect(root, ["example.txt"])
            self.assertEqual(report["limited_sensitive_pattern_paths"], ["example.txt"])
            self.assertNotIn(value, str(report))
