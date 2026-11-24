"""Regression tests verifying accept -> withdraw -> re-accept across HTTP dashboard & MCP paths."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from project_compass.cli import _review_callback
from project_compass.local_plugin import WorkspaceMCPAdapter
from project_compass.models import EvidenceEvent
from project_compass.plugin_protocol import ProjectContext
from project_compass.project_workspace import ProjectWorkspace
from project_compass.web_server import create_dashboard_server


class WithdrawAcceptedFactTests(unittest.TestCase):
    def _seed_workspace(self, root: Path) -> tuple[ProjectWorkspace, Path]:
        proj = root / "proj"
        proj.mkdir()
        ws = ProjectWorkspace(root / "ws", proj)
        now = datetime.now(timezone.utc)
        ev = EvidenceEvent(
            id="ev-withdraw-1",
            session_id="s1",
            author="fang",
            kind="user_message",
            content="决定：确认后支持撤回且不删除原始记录",
            observed_at=now,
            metadata={
                "member_id": "fang",
                "role": "user",
                "facts": [
                    {
                        "kind": "decision",
                        "subject_key": "ux.withdraw",
                        "value": "确认后支持撤回且不删除原始记录",
                    }
                ],
            },
        )
        ws.save([ev])
        return ws, proj

    def test_http_accept_withdraw_and_reaccept_preserves_history(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ws, proj = self._seed_workspace(Path(tmp))
            events = ws.load()
            c, h, r = ws.load_review_state()
            review_cb, c, h, r = _review_callback(events, ws, str(proj), c, h, r)
            srv = create_dashboard_server(
                events,
                port=0,
                project_path=str(proj),
                confirmed_relations=c,
                review_history=h,
                fact_reviews=r,
                review_callback=review_cb,
            )
            thread = threading.Thread(target=srv.serve_forever, daemon=True)
            thread.start()
            try:
                base = f"http://127.0.0.1:{srv.server_address[1]}"

                def req(path: str, body: dict | None = None) -> dict:
                    data = json.dumps(body).encode("utf-8") if body is not None else None
                    headers = {"Content-Type": "application/json"} if body is not None else {}
                    request = Request(base + path, data=data, headers=headers, method="POST" if body else "GET")
                    with urlopen(request, timeout=5) as resp:
                        return json.loads(resp.read().decode("utf-8"))

                st0 = req("/api/state")
                fid = next(f["id"] for f in st0["team"]["facts"] if f["status"] == "proposed")

                # Duplicate accept blocked before withdraw
                st_acc = req("/api/review", {"action": "accept_fact", "fact_id": fid, "reviewer": "fang"})
                self.assertEqual(next(f["status"] for f in st_acc["team"]["facts"] if f["id"] == fid), "accepted")
                with self.assertRaises(HTTPError) as dup_ctx:
                    req("/api/review", {"action": "accept_fact", "fact_id": fid, "reviewer": "fang"})
                self.assertEqual(dup_ctx.exception.code, 400)
                dup_ctx.exception.close()

                # Withdraw removes accepted projection while keeping raw events & review logs
                st_wd = req(
                    "/api/review",
                    {"action": "reject_fact", "fact_id": fid, "reviewer": "fang", "note": "从已确认中撤回"},
                )
                self.assertNotEqual(next(f["status"] for f in st_wd["team"]["facts"] if f["id"] == fid), "accepted")
                self.assertTrue(any(item.get("fact_id") == fid and item.get("action") == "accept_fact" for item in st_wd["fact_reviews"]))
                self.assertEqual([x.get("action") for x in st_wd["review_history"] if x.get("fact_id") == fid], ["accept_fact", "reject_fact"])
                self.assertEqual(len(ws.load()), 1)

                # Re-accept restores accepted status & appends 3rd history entry
                st_re = req("/api/review", {"action": "accept_fact", "fact_id": fid, "reviewer": "fang"})
                self.assertEqual(next(f["status"] for f in st_re["team"]["facts"] if f["id"] == fid), "accepted")
                self.assertEqual(
                    [x.get("action") for x in st_re["review_history"] if x.get("fact_id") == fid],
                    ["accept_fact", "reject_fact", "accept_fact"],
                )
                self.assertEqual(len(ws.load()), 1)
            finally:
                srv.shutdown()
                srv.server_close()
                thread.join(timeout=2)

    def test_mcp_accept_withdraw_and_reaccept_matches_http(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ws, proj = self._seed_workspace(Path(tmp))
            ctx = ProjectContext.for_project(proj, "fang", "s1", "antigravity")
            adapter = WorkspaceMCPAdapter(ws, ctx)

            wb0 = adapter.dispatch("workbench.open", {"_skip_bootstrap": True})
            fid = wb0["pending_items"][0]["fact_id"]

            wb_acc = adapter.dispatch("workbench.action", {"action": "accept_fact", "fact_id": fid})
            self.assertTrue(any(i["fact_id"] == fid for i in wb_acc["accepted_items"]))
            with self.assertRaises(ValueError):
                adapter.dispatch("workbench.action", {"action": "accept_fact", "fact_id": fid})

            wb_wd = adapter.dispatch(
                "workbench.action",
                {"action": "reject_fact", "fact_id": fid, "note": "从已确认中撤回"},
            )
            self.assertFalse(any(i["fact_id"] == fid for i in wb_wd["accepted_items"]))
            self.assertFalse(any(i["fact_id"] == fid for i in wb_wd["pending_items"]))
            self.assertEqual(len(ws.load()), 1)

            wb_re = adapter.dispatch("workbench.action", {"action": "accept_fact", "fact_id": fid})
            self.assertTrue(any(i["fact_id"] == fid for i in wb_re["accepted_items"]))
            _, hist, _ = ws.load_review_state()
            self.assertEqual([x.get("action") for x in hist if x.get("fact_id") == fid], ["accept_fact", "reject_fact", "accept_fact"])
            self.assertEqual(len(ws.load()), 1)


if __name__ == "__main__":
    unittest.main()
