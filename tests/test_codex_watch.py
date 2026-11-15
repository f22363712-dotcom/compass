from pathlib import Path
import json
import tempfile
import unittest

from project_compass.codex_plugin_bridge import CodexPluginBridge
from project_compass.codex_watch import CodexWatchRunner
from project_compass.plugin_protocol import ProjectContext


THREAD = "11111111-1111-4111-8111-111111111111"


class FakeAdapter:
    def __init__(self, context):
        self.context = context
        self.ids = []

    def append_event(self, event):
        self.ids.append(event.id)
        return {"appended": 1, "ids": [event.id]}


class CodexWatchTests(unittest.TestCase):
    def test_once_runner_reports_bridge_result(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            project.mkdir()
            sessions = root / "sessions"
            sessions.mkdir()
            path = sessions / f"rollout-{THREAD}.jsonl"
            rows = [
                {"type": "session_meta", "payload": {"id": THREAD, "cwd": str(project)}},
                {"type": "response_item", "timestamp": "2026-10-31T08:00:00Z", "payload": {"type": "message", "role": "assistant", "channel": "final", "content": [{"type": "output_text", "text": "Watcher event"}]}},
            ]
            path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
            context = ProjectContext.for_project(project, "alice", THREAD, "codex")
            adapter = FakeAdapter(context)
            bridge = CodexPluginBridge(adapter, sessions, project, THREAD, "alice")

            result = CodexWatchRunner(bridge, interval=0.001).run_once()

            self.assertEqual(result["submitted"], 1)
            self.assertEqual(len(adapter.ids), 1)
