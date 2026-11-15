from __future__ import annotations

import json
from pathlib import Path
import shutil
import tempfile
import unittest

from project_compass.transcript_watcher import TranscriptWatcher
from project_compass.project_workspace import ProjectWorkspace


class TranscriptWatcherTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = Path(tempfile.mkdtemp(prefix="test_watcher_"))
        self.transcript_file = self.tmp_dir / "sessions" / "s1" / "logs" / "transcript.jsonl"
        self.transcript_file.parent.mkdir(parents=True, exist_ok=True)
        self.workspace_dir = self.tmp_dir / "ws"
        self.workspace_dir.mkdir(parents=True, exist_ok=True)
        self.workspace = ProjectWorkspace(self.workspace_dir, self.tmp_dir)
        self.workspace.save([])

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_line_incompleteness_protection_and_streaming_sync(self) -> None:
        events: list = []
        watcher = TranscriptWatcher(
            self.transcript_file,
            member_id="antigravity",
            session_id="s1",
            include_tools=True,
        )

        # 1. Initially empty file
        self.transcript_file.write_text("", encoding="utf-8")
        status = watcher.sync(self.workspace, events)
        self.assertTrue(status["enabled"])
        self.assertFalse(status["updated"])
        self.assertEqual(len(events), 0)

        # 2. Append first full line
        rec1 = {
            "source": "USER_EXPLICIT",
            "type": "USER_INPUT",
            "step_index": 1,
            "created_at": "2026-11-04T12:00:00Z",
            "content": "<USER_REQUEST>目标：交付高保真协作看板</USER_REQUEST>",
        }
        with self.transcript_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec1, ensure_ascii=False) + "\n")

        status = watcher.sync(self.workspace, events)
        self.assertTrue(status["updated"])
        self.assertEqual(status["new_events_count"], 1)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].kind, "user_message")

        # Verify candidate goal extraction in workspace
        saved_events = self.workspace.load()
        self.assertTrue(any("交付高保真协作看板" in str(e.content or e.metadata) for e in saved_events))

        # 3. Simulate streaming in-progress partial line (no trailing newline)
        with self.transcript_file.open("a", encoding="utf-8") as f:
            f.write('{"source": "MODEL", "type": "PLANNER_RESPONSE", "content": "已完成 Module 1')

        status = watcher.sync(self.workspace, events)
        self.assertFalse(status["updated"])
        self.assertEqual(status["new_events_count"], 0)
        self.assertTrue(status.get("pending_partial_line"))
        self.assertEqual(len(events), 1)  # No corrupt event added

        # 4. Stream finishes writing the rest of the line + newline
        with self.transcript_file.open("a", encoding="utf-8") as f:
            f.write(' 实时流式追加测试。", "step_index": 2, "created_at": "2026-11-04T12:01:00Z"}\n')

        status = watcher.sync(self.workspace, events)
        self.assertTrue(status["updated"])
        self.assertEqual(status["new_events_count"], 1)
        self.assertEqual(len(events), 2)
        self.assertEqual(events[1].kind, "assistant_message")
        self.assertIn("已完成 Module 1", events[1].content)

        # 5. Idempotent: repeated sync with no new writes does not add duplicates
        status = watcher.sync(self.workspace, events)
        self.assertFalse(status["updated"])
        self.assertEqual(status["new_events_count"], 0)
        self.assertEqual(len(events), 2)

    def test_corrupt_lines_ignored_and_file_not_found(self) -> None:
        missing_watcher = TranscriptWatcher(self.tmp_dir / "non_existent.jsonl")
        status = missing_watcher.sync()
        self.assertFalse(status["updated"])
        self.assertIn("does not exist", status.get("error", ""))

        # Corrupt line in file
        events: list = []
        watcher = TranscriptWatcher(self.transcript_file, member_id="antigravity")
        with self.transcript_file.open("w", encoding="utf-8") as f:
            f.write("NOT_A_JSON_STRING\n")
            f.write(json.dumps({"source": "USER_EXPLICIT", "type": "USER_INPUT", "step_index": 10, "content": "<USER_REQUEST>有效请求</USER_REQUEST>"}) + "\n")

        status = watcher.sync(self.workspace, events)
        self.assertTrue(status["updated"])
        self.assertEqual(status["new_events_count"], 1)
        self.assertEqual(len(events), 1)
        self.assertIn("有效请求", events[0].content)


if __name__ == "__main__":
    unittest.main()
