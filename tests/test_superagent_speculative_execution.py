"""Tests for Slice 3: Conflict detection speculative validation & candidate recommendation."""
import unittest
from datetime import datetime, timezone

import sys
from project_compass.models import EvidenceEvent
from project_compass.projections import build_views, run_silent_speculative_sandbox


class SuperagentSpeculativeExecutionTests(unittest.TestCase):
    def test_conflict_speculative_recommendation_based_on_test_passing(self):
        # Alice's fact is backed by a passed test (exit_code=0)
        # Bob's fact is backed by a failed test (exit_code=1)
        events = [
            EvidenceEvent(
                "ev-alice",
                "session-alice",
                "alice",
                "test_result",
                "Tests PASSED for feature-x",
                datetime(2026, 10, 24, 10, 0, tzinfo=timezone.utc),
                {
                    "exit_code": 0,
                    "facts": [{"kind": "task", "subject_key": "task.feature_x", "value": "feature-x is verified"}],
                },
            ),
            EvidenceEvent(
                "ev-bob",
                "session-bob",
                "bob",
                "test_result",
                "Tests FAILED for feature-x",
                datetime(2026, 10, 24, 9, 0, tzinfo=timezone.utc),
                {
                    "exit_code": 1,
                    "facts": [{"kind": "task", "subject_key": "task.feature_x", "value": "feature-x is broken"}],
                },
            ),
        ]

        views = build_views(events)
        conflicts = views["team"]["conflicts"]
        self.assertEqual(len(conflicts), 1)

        conflict = conflicts[0]
        self.assertEqual(conflict["subject_key"], "task.feature_x")
        self.assertIn("speculative_recommendation", conflict)

        rec = conflict["speculative_recommendation"]
        # Alice should be recommended because exit_code == 0 and more recent
        self.assertEqual(rec["recommended_value"], "feature-x is verified")
        self.assertEqual(rec["confidence"], "high")
        self.assertEqual(rec["evidence_ids"], ["ev-alice"])
        self.assertIn("若采纳 alice 的提议", rec["hypothetical_resolution"])

        # Check side annotations
        sides = {s["author"]: s for s in conflict["sides"]}
        self.assertEqual(sides["alice"]["speculative_status"], "recommended")
        self.assertEqual(sides["bob"]["speculative_status"], "alternative")
        self.assertGreater(sides["alice"]["speculative_score"], sides["bob"]["speculative_score"])
        self.assertTrue(any("经由测试/验证执行通过" in r for r in sides["alice"]["speculative_reasons"]))
        self.assertTrue(any("执行失败" in r for r in sides["bob"]["speculative_reasons"]))

    def test_conflict_speculative_recommendation_with_accepted_fact(self):
        # When a fact was accepted by team owner, it should receive high speculative bonus
        events = [
            EvidenceEvent(
                "ev-1",
                "session-1",
                "alice",
                "assistant_message",
                "Deploy to AWS",
                datetime(2026, 10, 24, tzinfo=timezone.utc),
                {"facts": [{"kind": "decision", "subject_key": "cloud.provider", "value": "AWS"}]},
            ),
            EvidenceEvent(
                "ev-2",
                "session-2",
                "bob",
                "assistant_message",
                "Deploy to GCP",
                datetime(2026, 10, 24, tzinfo=timezone.utc),
                {"facts": [{"kind": "decision", "subject_key": "cloud.provider", "value": "GCP"}]},
            ),
        ]
        from project_compass.fact_engine import derive_facts
        facts = derive_facts(events)
        alice_fact = next(f for f in facts if f.value == "AWS")

        views = build_views(events, accepted_fact_ids=[alice_fact.id])
        conflicts = views["team"]["conflicts"]
        self.assertEqual(len(conflicts), 1)
        rec = conflicts[0]["speculative_recommendation"]
        self.assertEqual(rec["recommended_value"], "AWS")
        self.assertEqual(rec["confidence"], "high")

    def test_conflict_speculative_recommendation_tie_handling(self):
        # Two identical facts with same score, same timestamp, no tests
        events = [
            EvidenceEvent(
                "ev-1",
                "session-1",
                "alice",
                "assistant_message",
                "Option A",
                datetime(2026, 10, 24, 12, tzinfo=timezone.utc),
                {"facts": [{"kind": "decision", "subject_key": "opt", "value": "Option A"}]},
            ),
            EvidenceEvent(
                "ev-2",
                "session-2",
                "bob",
                "assistant_message",
                "Option B",
                datetime(2026, 10, 24, 12, tzinfo=timezone.utc),
                {"facts": [{"kind": "decision", "subject_key": "opt", "value": "Option B"}]},
            ),
        ]
        views = build_views(events)
        conflicts = views["team"]["conflicts"]
        self.assertEqual(len(conflicts), 1)
        rec = conflicts[0]["speculative_recommendation"]
        self.assertTrue(rec["tie"])
        self.assertEqual(rec["confidence"], "low")
        self.assertEqual(rec["recommended_value"], "平局待定")
        self.assertEqual(rec["evidence_ids"], [])
        for side in conflicts[0]["sides"]:
            self.assertEqual(side["speculative_status"], "alternative")

    def test_run_silent_speculative_sandbox_success(self):
        result = run_silent_speculative_sandbox(
            runner_cmd=[sys.executable, "-c", "import sys; sys.exit(0)"],
            timeout=10,
        )
        self.assertTrue(result["verified"])
        self.assertEqual(result["exit_code"], 0)
        self.assertTrue(result["silent"])
        self.assertIn("100% green", result["summary"])

    def test_run_silent_speculative_sandbox_failure(self):
        result = run_silent_speculative_sandbox(
            runner_cmd=[sys.executable, "-c", "import sys; sys.exit(1)"],
            timeout=10,
        )
        self.assertFalse(result["verified"])
        self.assertEqual(result["exit_code"], 1)
        self.assertTrue(result["silent"])

    def test_run_silent_speculative_sandbox_timeout(self):
        result = run_silent_speculative_sandbox(
            runner_cmd=[sys.executable, "-c", "import time; time.sleep(5)"],
            timeout=1,
        )
        self.assertFalse(result["verified"])
        self.assertEqual(result["exit_code"], -1)
        self.assertTrue(result["silent"])
        self.assertIn("timed out", result["summary"])

    def test_fact_speculative_verified_flag(self):
        events = [
            EvidenceEvent(
                "ev-test-pass",
                "session-pass",
                "alice",
                "test_result",
                "Unit tests passed",
                datetime(2026, 10, 24, 10, tzinfo=timezone.utc),
                {
                    "exit_code": 0,
                    "facts": [{"kind": "task", "subject_key": "task.auth", "value": "OAuth implemented"}],
                },
            ),
            EvidenceEvent(
                "ev-chat-untested",
                "session-chat",
                "bob",
                "assistant_message",
                "I think auth is done",
                datetime(2026, 10, 24, 11, tzinfo=timezone.utc),
                {
                    "facts": [{"kind": "task", "subject_key": "task.untested", "value": "Untested idea"}],
                },
            ),
        ]
        views = build_views(events)
        team_facts = {f["id"]: f for f in views["team"]["facts"]}
        alice_fact = next(f for f in team_facts.values() if f["value"] == "OAuth implemented")
        bob_fact = next(f for f in team_facts.values() if f["value"] == "Untested idea")

        self.assertTrue(alice_fact["speculative_verified"])
        self.assertFalse(bob_fact["speculative_verified"])

        # Also verify personal view has the flag
        alice_personal_fact = next(f for f in views["personal"]["alice"]["facts"] if f["value"] == "OAuth implemented")
        self.assertTrue(alice_personal_fact["speculative_verified"])

        bob_personal_fact = next(f for f in views["personal"]["bob"]["facts"] if f["value"] == "Untested idea")
        self.assertFalse(bob_personal_fact["speculative_verified"])


if __name__ == "__main__":
    unittest.main()
