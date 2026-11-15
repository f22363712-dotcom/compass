from pathlib import Path
import json
import tempfile
import unittest

from project_compass.codex_plugin_bridge import CodexPluginBridge
from project_compass.native_codex import NativeCodexIntake
from project_compass.plugin_protocol import ProjectContext
from project_compass.project_workspace import ProjectWorkspace


THREAD = "11111111-1111-4111-8111-111111111111"


class FakeAdapter:
    def __init__(self, context):
        self.context = context
        self.events = []

    def append_event(self, event):
        self.events.append(event)
        return {"appended": 1, "ids": [event.id]}


class CodexPluginBridgeTests(unittest.TestCase):
    def test_sync_submits_public_user_and_assistant_events_with_stable_ids(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            project.mkdir()
            sessions = root / "sessions"
            sessions.mkdir()
            path = sessions / f"rollout-{THREAD}.jsonl"
            rows = [
                {"type": "session_meta", "payload": {"id": THREAD, "cwd": str(project)}},
                {"type": "response_item", "timestamp": "2026-10-31T08:00:00Z", "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "Review the stage A plugin."}]}},
                {"type": "response_item", "timestamp": "2026-10-31T08:01:00Z", "payload": {"type": "message", "role": "assistant", "channel": "final", "content": [{"type": "output_text", "text": "Stage A plugin is ready for review."}]}},
            ]
            path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
            reader_workspace = ProjectWorkspace(root / "reader-state", project)
            reader_workspace.save([])
            context = ProjectContext.for_project(project, "alice", THREAD, "codex")
            adapter = FakeAdapter(context)

            bridge = CodexPluginBridge(adapter, sessions, project, THREAD, "alice")
            first = bridge.sync()
            second = bridge.sync()

            self.assertEqual(first["captured_messages"], 2)
            self.assertEqual(first["submitted"], 2)
            self.assertEqual(second["submitted"], 0)
            self.assertEqual(len(adapter.events), 2)
            self.assertEqual([event.kind for event in adapter.events], ["user_message", "assistant_message"])
            bridge.close()

    def test_second_tick_submits_only_a_new_rollout_message(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); project = root / "project"; project.mkdir(); sessions = root / "sessions"; sessions.mkdir()
            path = sessions / f"rollout-{THREAD}.jsonl"
            header = {"type": "session_meta", "payload": {"id": THREAD, "cwd": str(project)}}
            first = {"type": "response_item", "timestamp": "2026-10-31T08:00:00Z", "payload": {"type": "message", "role": "assistant", "channel": "final", "content": [{"type": "output_text", "text": "First tick"}]}}
            second = {"type": "response_item", "timestamp": "2026-10-31T08:01:00Z", "payload": {"type": "message", "role": "assistant", "channel": "final", "content": [{"type": "output_text", "text": "Second tick"}]}}
            path.write_text("\n".join(json.dumps(row) for row in (header, first)) + "\n", encoding="utf-8")
            context = ProjectContext.for_project(project, "alice", THREAD, "codex"); adapter = FakeAdapter(context)
            bridge = CodexPluginBridge(adapter, sessions, project, THREAD, "alice")

            self.assertEqual(bridge.sync()["submitted"], 1)
            path.write_text("\n".join(json.dumps(row) for row in (header, first, second)) + "\n", encoding="utf-8")

            result = bridge.sync()

            self.assertEqual(result["submitted"], 1)
            self.assertEqual(len(adapter.events), 2)
            self.assertEqual([event.content for event in adapter.events], ["First tick", "Second tick"])
            bridge.close()


if __name__ == "__main__":
    unittest.main()
