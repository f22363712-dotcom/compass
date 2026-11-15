import json
from pathlib import Path
import tempfile
import unittest

from project_compass.antigravity_adapter import AntigravityTranscriptAdapter


class AntigravityTranscriptAdapterTest(unittest.TestCase):
    def test_parses_user_assistant_and_tools_without_thinking(self):
        sample = "\n".join([
            json.dumps({
                "step_index": 0,
                "source": "USER_EXPLICIT",
                "type": "USER_INPUT",
                "created_at": "2026-11-04T06:01:18Z",
                "content": "<USER_REQUEST>\n请完成目标\n</USER_REQUEST>\n<METADATA>extra</METADATA>",
            }),
            json.dumps({
                "step_index": 1,
                "source": "MODEL",
                "type": "PLANNER_RESPONSE",
                "created_at": "2026-11-04T06:01:20Z",
                "thinking": "HIDDEN_SECRET_REASONING_DO_NOT_EXPOSE",
                "content": "好的，我已经完成梳理。",
                "tool_calls": [{"name": "run_command", "args": {"CommandLine": "python test.py"}}],
            }),
            json.dumps({
                "step_index": 2,
                "source": "MODEL",
                "type": "GENERIC",
                "created_at": "2026-11-04T06:01:25Z",
                "content": "All 5 tests passed.",
            }),
            json.dumps({
                "step_index": 3,
                "source": "SYSTEM",
                "type": "SYSTEM_MESSAGE",
                "created_at": "2026-11-04T06:01:26Z",
                "content": "System internal event",
            }),
        ])

        with tempfile.TemporaryDirectory() as directory:
            transcript = Path(directory) / "transcript.jsonl"
            transcript.write_text(sample, encoding="utf-8")

            events = AntigravityTranscriptAdapter.from_transcript(transcript, member_id="alice")
            self.assertEqual(len(events), 4)
            self.assertEqual([e.kind for e in events], ["user_message", "assistant_message", "tool_call", "tool_result"])
            self.assertEqual(events[0].author, "alice")
            self.assertEqual(events[0].content, "请完成目标")
            self.assertEqual(events[1].author, "antigravity")
            self.assertEqual(events[1].content, "好的，我已经完成梳理。")
            self.assertIn("python test.py", events[2].content)
            self.assertEqual(events[3].content, "All 5 tests passed.")

            for event in events:
                self.assertNotIn("HIDDEN_SECRET_REASONING", event.content)
                self.assertNotIn("thinking", event.metadata)
                self.assertIsNotNone(event.observed_at.tzinfo)

    def test_filters_sensitive_credentials(self):
        sample = json.dumps({
            "step_index": 0,
            "source": "USER_EXPLICIT",
            "type": "USER_INPUT",
            "created_at": "2026-11-04T06:01:18Z",
            "content": "my token is bearer super_secret_credential_token_12345",
        })
        with tempfile.TemporaryDirectory() as directory:
            transcript = Path(directory) / "transcript.jsonl"
            transcript.write_text(sample, encoding="utf-8")
            events = AntigravityTranscriptAdapter.from_transcript(transcript)
            self.assertEqual(events, [])

    def test_extracts_structured_goal_task_and_decision_candidates(self):
        sample = "\n".join([
            json.dumps({
                "step_index": 0,
                "source": "USER_EXPLICIT",
                "type": "USER_INPUT",
                "created_at": "2026-11-04T06:01:18Z",
                "content": "<USER_REQUEST>\n选C，注意在构建架构时，不要着急构建完整的，而是依据功能和我们的目标\n这个既然是看板，我们就要围绕人的视线聚焦和注意力聚焦来打造产品的形象\n</USER_REQUEST>",
            }),
            json.dumps({
                "step_index": 1,
                "source": "MODEL",
                "type": "PLANNER_RESPONSE",
                "created_at": "2026-11-04T06:01:20Z",
                "content": "**目标**：完成看板 1.0 视觉聚焦改版。\n已实现 Module 1（核心看板布局与注意力聚焦），并通过本地测试。",
            }),
        ])
        with tempfile.TemporaryDirectory() as directory:
            transcript = Path(directory) / "transcript.jsonl"
            transcript.write_text(sample, encoding="utf-8")
            events = AntigravityTranscriptAdapter.from_transcript(
                transcript, member_id="antigravity", include_tools=False
            )
            self.assertEqual(len(events), 2)
            user_facts = events[0].metadata.get("facts", [])
            assistant_facts = events[1].metadata.get("facts", [])
            self.assertEqual({f["kind"] for f in user_facts}, {"goal", "decision"})
            self.assertEqual({f["kind"] for f in assistant_facts}, {"goal", "task"})
            self.assertEqual(events[0].metadata["member_id"], "antigravity")
            self.assertEqual(events[1].metadata["member_id"], "antigravity")


if __name__ == "__main__":
    unittest.main()

