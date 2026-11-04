from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from contentflow.domain import FlowError
from contentflow.http_client import ApiError
from contentflow.repository import Repository
from contentflow.settings import Settings
from contentflow.workflow import Workflow
from test_domain_settings import sample

TASK = "243f9893-0914-4b26-8057-dcff096c97d2"


class WorkflowTests(unittest.TestCase):
    def test_storage_failure_persists_and_retry_only_downloads_same_task(self):
        for failure in (OSError("private-storage-location"), FlowError("download_storage", "成片保存失败，请重试下载。")):
            with self.subTest(failure=type(failure).__name__):
                # 独立草稿/任务，每次仅一次模拟POST；重建工作流验证重启可恢复。
                draft = self.repo.new_draft("森林", sample())
                digest = self.repo.confirm(draft, "森林", sample(), "pixabay")
                self.client.reset_mock()
                job = self.flow.submit(draft, digest)
                self.client.status.return_value = {"task_id": TASK, "state": 1, "progress": 100, "videos": [f"/tasks/{TASK}/final-1.mp4"]}
                self.client.download.side_effect = failure
                failed = self.flow.poll(job["id"])
                self.assertEqual(failed["state"], "download_failed")
                self.assertEqual(failed["progress"], 100)
                self.assertEqual(failed["task_id"], TASK)
                self.assertNotIn("private", failed["error"])
                self.assertEqual(Repository(self.repo.path).job(job["id"])["state"], "download_failed")
                recovered = Workflow(self.settings, Repository(self.repo.path), self.client, self.materials)
                # 重试仍失败时也保持可重试；从不重新提交。
                self.assertEqual(recovered.retry_download(job["id"])["state"], "download_failed")
                path = self.settings.data_dir / "videos" / (TASK + ".mp4")
                self.client.download.side_effect = None
                self.client.download.return_value = (path, {"bytes": 100})
                self.assertEqual(recovered.retry_download(job["id"])["state"], "complete")
                self.client.submit.assert_called_once()
                self.assertEqual(self.client.download.call_count, 3)
                self.assertTrue(all(call.args[0] == TASK for call in self.client.status.call_args_list))

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.repo = Repository(self.root / "flow.sqlite")
        self.settings = Settings(root=self.root, pixabay_ready=True, edge_ready=True)
        self.client = Mock()
        self.client.submit.return_value = TASK
        self.client.material_sources.return_value = []
        self.materials = Mock()
        self.materials.search.return_value = {"source": "pixabay", "status": "passed", "matched_count": 4}
        self.flow = Workflow(self.settings, self.repo, self.client, self.materials)
        self.draft_id = self.repo.new_draft("森林", sample())
        self.digest = self.repo.confirm(self.draft_id, "森林", sample(), "pixabay")

    def test_confirmation_missing_key_and_duplicate_never_post(self):
        with self.assertRaises(FlowError):
            self.flow.submit(self.draft_id, "edited content")
        with self.assertRaises(FlowError):
            Workflow(replace(self.settings, pixabay_ready=False), self.repo, self.client).submit(self.draft_id, self.digest)
        self.client.submit.assert_not_called()
        first = self.flow.submit(self.draft_id, self.digest)
        with self.assertRaises(FlowError):
            self.flow.submit(self.draft_id, self.digest)
        self.client.submit.assert_called_once()
        self.assertEqual(Repository(self.repo.path).job(first["id"])["task_id"], TASK)

    def test_uncertain_post_holds_lock_and_is_not_resent_on_poll(self):
        self.client.submit.side_effect = ApiError("network", "timeout", True)
        result = self.flow.submit(self.draft_id, self.digest)
        self.assertEqual(result["state"], "uncertain")
        self.flow.poll(result["id"])
        self.client.submit.assert_called_once()
        self.client.status.assert_not_called()

    def test_concurrent_claim_only_one_job(self):
        def reserve():
            try:
                return Repository(self.repo.path).reserve(self.draft_id, self.digest)["id"]
            except FlowError:
                return None
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: reserve(), range(2)))
        self.assertEqual(sum(r is not None for r in results), 1)

    def test_completed_download_and_failure_mapping(self):
        job = self.flow.submit(self.draft_id, self.digest)
        self.client.status.return_value = {"task_id": TASK, "state": 1, "progress": 100, "videos": [f"/tasks/{TASK}/final-1.mp4"]}
        path = self.settings.data_dir / "videos" / (TASK + ".mp4")
        self.client.download.return_value = (path, {"duration_seconds": 20, "width": 1080, "height": 1920, "bytes": 100})
        done = self.flow.poll(job["id"])
        self.assertEqual(done["state"], "complete")
        self.flow.poll(job["id"])
        self.client.submit.assert_called_once()
        self.client.download.assert_called_once()

    def test_no_results_network_and_backend_restart(self):
        job = self.flow.submit(self.draft_id, self.digest)
        self.client.status.side_effect = ApiError("network", "网络失败")
        self.assertEqual(self.flow.poll(job["id"])["state"], "processing")
        self.client.status.side_effect = None
        self.client.status.return_value = {"task_id": TASK, "state": -1, "failed_stage": "materials", "progress": 40, "error": "https://secret.invalid?key=private"}
        failed = self.flow.poll(job["id"])
        self.assertEqual(failed["state"], "failed")
        self.assertIn("在线素材", failed["error"])
        self.assertNotIn("private", failed["error"])

    def test_404_retains_id_and_marks_uncertain(self):
        job = self.flow.submit(self.draft_id, self.digest)
        self.client.status.side_effect = ApiError("http_404", "未找到")
        result = self.flow.poll(job["id"])
        self.assertEqual(result["state"], "uncertain")
        self.assertEqual(result["task_id"], TASK)

    def test_changed_source_invalidates_review(self):
        with self.repo.connect() as db:
            db.execute("UPDATE drafts SET source=? WHERE id=?", ("pexels", self.draft_id))
        with self.assertRaises(FlowError):
            self.flow.submit(self.draft_id, self.digest)
        self.client.submit.assert_not_called()

    def test_explicit_new_draft_retry_needs_review_and_preserves_snapshot(self):
        first = self.flow.submit(self.draft_id, self.digest)
        self.repo.update(first["id"], state="failed", error="素材失败")
        new_id = self.repo.new_draft("森林", sample())
        with self.assertRaises(FlowError):
            self.flow.submit(new_id, self.digest)
        new_digest = self.repo.confirm(new_id, "森林", sample(), "pixabay")
        second = self.flow.submit(new_id, new_digest)
        self.assertNotEqual(first["id"], second["id"])
        self.assertEqual(self.repo.job(first["id"])["state"], "failed")
        self.assertEqual(self.client.submit.call_count, 2)

    def test_no_pixabay_candidates_never_submits_or_falls_back(self):
        self.materials.search.return_value = {"source": "pixabay", "status": "no_results", "matched_count": 0}
        with self.assertRaises(FlowError):
            self.flow.submit(self.draft_id, self.digest)
        self.client.submit.assert_not_called()
        self.assertEqual(self.repo.jobs(), [])


if __name__ == "__main__":
    unittest.main()
