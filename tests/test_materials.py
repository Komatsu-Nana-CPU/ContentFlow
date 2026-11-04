from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock
import json

from contentflow.domain import FlowError
from contentflow.materials import MaterialsService, require_materials
from contentflow.settings import Settings


class MaterialsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.settings = Settings(root=Path(self.tmp.name), pixabay_ready=True)
        self.runner = Mock(return_value=Mock(stdout=json.dumps({"source": "pixabay", "status": "passed", "matched_count": 7})))

    def test_success_24_hour_cache_and_no_secret_on_command_line(self):
        clock = Mock(return_value=1000)
        service = MaterialsService(self.settings, self.runner, clock)
        self.assertEqual(service.search(["waterfall"])["matched_count"], 7)
        clock.return_value = 2000
        self.assertTrue(service.search(["waterfall"])["preview_cache_hit"])
        self.runner.assert_called_once()
        self.assertNotIn("key=", " ".join(self.runner.call_args.args[0]))
        clock.return_value = 100000
        service.search(["waterfall"])
        self.assertEqual(self.runner.call_count, 2)

    def test_missing_key_never_starts_process(self):
        service = MaterialsService(Settings(root=Path(self.tmp.name)), self.runner)
        with self.assertRaises(FlowError):
            service.search(["waterfall"])
        self.runner.assert_not_called()

    def test_timeout_and_invalid_response_are_sanitized(self):
        for value in (subprocess.TimeoutExpired("command", 120, stderr="private"), ValueError()):
            self.runner.side_effect = value
            with self.assertRaises(FlowError) as raised:
                MaterialsService(self.settings, self.runner).search(["waterfall"])
            self.assertNotIn("private", str(raised.exception))

    def test_distinct_safe_error_classifications(self):
        for status in ("invalid_key", "network_error", "rate_limited", "no_results", "no_matching_videos", "network_challenge"):
            with self.subTest(status=status), self.assertRaises(FlowError):
                require_materials({"status": status, "matched_count": 0})


if __name__ == "__main__":
    unittest.main()
