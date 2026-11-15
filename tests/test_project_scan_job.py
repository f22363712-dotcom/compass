from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from project_compass.project_scan_job import ProjectScanJob


class ProjectScanJobTests(unittest.TestCase):
    def test_scan_job_reaches_complete_and_persists_workspace(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); project = root / "project"; project.mkdir(); (project / "README.md").write_text("# demo", encoding="utf-8")
            job = ProjectScanJob(root / "state")
            self.assertEqual(job.start(project)["state"], "running")
            for _ in range(50):
                if job.status()["state"] == "complete": break
                time.sleep(0.02)
            result = job.status()
            self.assertEqual(result["state"], "complete")
            self.assertGreaterEqual(result["evidence_count"], 1)

    def test_failed_scan_can_be_retried(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); project = root / "project"; project.mkdir(); (project / "README.md").write_text("# demo", encoding="utf-8")
            job = ProjectScanJob(root / "state")
            with patch("project_compass.project_scan_job.scan_project", side_effect=[OSError("temporary read failure"), []]):
                job.start(project)
                for _ in range(50):
                    if job.status()["state"] == "failed": break
                    time.sleep(0.02)
                self.assertEqual(job.status()["state"], "failed")
                job.start(project)
                for _ in range(50):
                    if job.status()["state"] == "complete": break
                    time.sleep(0.02)
                self.assertEqual(job.status()["state"], "complete")


if __name__ == "__main__":
    unittest.main()
