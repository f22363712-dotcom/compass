import json
from threading import Thread
from urllib.request import Request, urlopen
from urllib.error import HTTPError
import unittest
from unittest.mock import patch
from pathlib import Path
import tempfile
import time
from dataclasses import replace
from datetime import datetime, timezone

from project_compass.dashboard import build_dashboard_state
from project_compass.derived_context import DerivedContext
from project_compass.evidence_linking import build_evidence_index, confirm_relation
from project_compass.fact_engine import derive_facts
from project_compass.sample_data import sample_events
from project_compass.project_workspace import ProjectWorkspace
from project_compass.project_scan_job import ProjectScanJob
from project_compass.web_server import create_dashboard_server


class DashboardTest(unittest.TestCase):
    def test_dashboard_exposes_derived_context_as_read_only_state(self):
        fixture = Path(__file__).parent / "fixtures" / "derived_context_minimal.json"
        context = DerivedContext.load(fixture, project_id="project-1")
        state = build_dashboard_state([], project_path="C:/project", derived_context=context)
        self.assertTrue(state["derived_context"]["enabled"])
        self.assertEqual(state["derived_context"]["origin"], "derived_context")
        self.assertEqual(state["derived_context"]["nodes"][0]["origin"], "derived_context")
        self.assertFalse(any(item.get("status") == "accepted" for item in state["derived_context"]["nodes"]))
        self.assertEqual(state["derived_context"]["direct_node_ids"], [])
        self.assertEqual(state["derived_context"]["related_node_ids"], [])

    def test_dashboard_projects_evidence_related_derived_context_nodes_and_edges(self):
        from project_compass.models import EvidenceEvent

        context = DerivedContext.from_dict(
            {
                "schema_version": 1,
                "project_id": "project-1",
                "source_ref": "src/main.py",
                "source_fingerprint": "sha256:abc",
                "observed_at": "2026-11-04T09:00:00+08:00",
                "nodes": [
                    {"id": "file:src/other.py", "kind": "file", "label": "src/other.py", "source_ref": "src/other.py"},
                    {"id": "file:src/main.py", "kind": "file", "label": "src/main.py", "source_ref": "src/main.py"},
                    {"id": "fn:helper", "kind": "function", "label": "helper", "source_ref": "src/helper.py"},
                ],
                "edges": [
                    {"id": "edge-call", "from_id": "file:src/main.py", "to_id": "fn:helper", "kind": "calls"}
                ],
            },
            project_id="project-1",
        )
        event = EvidenceEvent(
            "ev-main",
            "s1",
            "dev-a",
            "file_snapshot",
            "def main(): pass",
            datetime(2026, 11, 4, 1, tzinfo=timezone.utc),
            {"source_ref": "src\\main.py"},
        )
        state = build_dashboard_state([event], project_path="C:/project", derived_context=context)
        dc = state["derived_context"]
        self.assertEqual(dc["direct_node_ids"], ["file:src/main.py"])
        self.assertEqual(dc["related_node_ids"], ["file:src/main.py", "fn:helper"])
        self.assertEqual(dc["related_edge_ids"], ["edge-call"])
        self.assertEqual(dc["evidence_source_refs"], ["src/main.py"])

    def test_http_projects_lists_registered_workspaces(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); project = root / "alpha"; project.mkdir()
            workspace = ProjectWorkspace(root / "state", project); workspace.save([])
            server = create_dashboard_server([], host="127.0.0.1", port=0, project_path=str(project), workspace_root=root / "state")
            thread = Thread(target=server.serve_forever, daemon=True); thread.start()
            try:
                with urlopen(f"http://127.0.0.1:{server.server_address[1]}/api/projects") as response:
                    projects = json.loads(response.read().decode("utf-8"))
                self.assertEqual(projects[0]["project_name"], "alpha")
                self.assertEqual(projects[0]["project_id"], workspace.project_id)
            finally:
                server.shutdown(); server.server_close(); thread.join(timeout=2)
    def test_state_keeps_personal_team_and_relation_layers(self):
        payload = build_dashboard_state(sample_events())

        self.assertIn("personal", payload)
        self.assertIn("team", payload)
        self.assertIn("evidence", payload)
        self.assertIn("candidate_relations", payload)
        self.assertIn("confirmed_relations", payload)
        self.assertNotEqual(payload["personal"], payload["team"])
        self.assertIn("personal_activity", payload)
        self.assertTrue(payload["personal_activity"])
        self.assertTrue(payload["personal_activity"][0]["last_event_id"])
        self.assertIn("team_review_queue", payload)
        self.assertTrue(any(item["status"] == "conflicted" for item in payload["team_review_queue"]))

    def test_evidence_request_returns_to_personal_view_when_new_evidence_arrives(self):
        events = sample_events()
        fact = next(item for item in derive_facts(events) if item.subject_key == "task.golden-path")
        newer = replace(events[0], id="e3", content="补充了新的验证日志", observed_at=datetime(2026, 10, 24, 9, tzinfo=timezone.utc), metadata={})
        history = [{"action": "request_evidence", "fact_id": fact.id, "subject_key": fact.subject_key, "value": fact.value, "evidence_ids": list(fact.evidence_ids), "reviewer": "owner", "note": "缺少发布日志", "observed_at": "2026-10-24T08:30:00+00:00"}]
        payload = build_dashboard_state(events + [newer], review_history=history)
        self.assertEqual(payload["evidence_requests"][0]["status"], "ready_for_review")
        self.assertIn("e3", payload["evidence_requests"][0]["new_evidence_ids"])
        self.assertTrue(payload["personal"][fact.author]["evidence_requests"])
        requested = [item for item in payload["candidate_relations"] if item["basis"] == "requested-evidence"]
        self.assertTrue(requested)

    def test_http_api_serves_state_and_exact_evidence(self):
        events = sample_events()
        server = create_dashboard_server(events, host="127.0.0.1", port=0)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_address[1]}"
        try:
            with urlopen(base + "/api/state") as response:
                state = json.loads(response.read().decode("utf-8"))
            self.assertIn("team", state)
            self.assertIn("evidence", state)

            with urlopen(base + "/api/evidence?id=e1") as response:
                evidence = json.loads(response.read().decode("utf-8"))
            self.assertEqual(evidence["id"], "e1")
            self.assertIn("content", evidence)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_http_state_can_open_another_registered_project_read_only(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); first = root / "alpha"; second = root / "beta"; first.mkdir(); second.mkdir()
            state_root = root / "state"; ProjectWorkspace(state_root, first).save([]); second_ws = ProjectWorkspace(state_root, second); second_ws.save([])
            server = create_dashboard_server([], host="127.0.0.1", port=0, project_path=str(first), workspace_root=state_root)
            thread = Thread(target=server.serve_forever, daemon=True); thread.start()
            try:
                with urlopen(f"http://127.0.0.1:{server.server_address[1]}/api/state?project_id={second_ws.project_id}") as response:
                    payload = json.loads(response.read().decode("utf-8"))
                self.assertEqual(payload["project"]["name"], "beta")
                self.assertTrue(payload["project"]["read_only"])
            finally:
                server.shutdown(); server.server_close(); thread.join(timeout=2)

    def test_http_secondary_project_scopes_evidence_export_and_investigate(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); first = root / "alpha"; second = root / "beta"; first.mkdir(); second.mkdir()
            state_root = root / "state"
            ProjectWorkspace(state_root, first).save([])
            second_ws = ProjectWorkspace(state_root, second)
            second_ws.save(sample_events())
            server = create_dashboard_server([], host="127.0.0.1", port=0, project_path=str(first), workspace_root=state_root)
            thread = Thread(target=server.serve_forever, daemon=True); thread.start()
            base = f"http://127.0.0.1:{server.server_address[1]}"
            try:
                with urlopen(f"{base}/api/evidence?id=e1&project_id={second_ws.project_id}") as response:
                    evidence = json.loads(response.read().decode("utf-8"))
                self.assertEqual(evidence["id"], "e1")

                with urlopen(f"{base}/api/export?format=prd&project_id={second_ws.project_id}") as response:
                    prd_text = response.read().decode("utf-8")
                self.assertIn("beta", prd_text)
                self.assertIn("阶段 01", prd_text)

                req = Request(
                    f"{base}/api/investigate",
                    data=json.dumps({"question": "What database options exist?", "project_id": second_ws.project_id}).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urlopen(req) as response:
                    answer = json.loads(response.read().decode("utf-8"))
                self.assertTrue(answer.get("evidence_ids") or answer.get("findings") or answer.get("conflicts"))
                self.assertEqual(server.query_stats["total"], 0)

                null_pid_req = Request(
                    f"{base}/api/investigate",
                    data=json.dumps({"question": "goal?", "project_id": None}).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urlopen(null_pid_req) as response:
                    self.assertEqual(response.status, 200)

                null_q_req = Request(
                    f"{base}/api/investigate",
                    data=json.dumps({"question": None}).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with self.assertRaises(HTTPError) as null_q_err:
                    urlopen(null_q_req)
                self.assertEqual(null_q_err.exception.code, 400)

                for path, method, body in (
                    (f"/api/evidence?id=e1&project_id=missing", "GET", None),
                    (f"/api/export?project_id=missing", "GET", None),
                    ("/api/investigate", "POST", json.dumps({"question": "goal?", "project_id": "missing"}).encode("utf-8")),
                ):
                    r = Request(f"{base}{path}", data=body, headers=({"Content-Type": "application/json"} if body else {}), method=method)
                    with self.assertRaises(HTTPError) as err:
                        urlopen(r)
                    self.assertEqual(err.exception.code, 404)
            finally:
                server.shutdown(); server.server_close(); thread.join(timeout=2)

    def test_http_state_unknown_project_returns_404(self):
        server = create_dashboard_server([], host="127.0.0.1", port=0, project_path="C:/missing")
        thread = Thread(target=server.serve_forever, daemon=True); thread.start()
        try:
            with self.assertRaises(HTTPError) as error:
                urlopen(f"http://127.0.0.1:{server.server_address[1]}/api/state?project_id=missing")
            self.assertEqual(error.exception.code, 404)
        finally:
            server.shutdown(); server.server_close(); thread.join(timeout=2)

    def test_http_project_scan_registers_new_project(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); target = root / "new-project"; target.mkdir(); (target / "README.md").write_text("# New", encoding="utf-8")
            state_root = root / "state"
            server = create_dashboard_server([], host="127.0.0.1", port=0, project_path=str(target), workspace_root=state_root, project_scan_job=ProjectScanJob(state_root))
            thread = Thread(target=server.serve_forever, daemon=True); thread.start()
            try:
                request = Request(f"http://127.0.0.1:{server.server_address[1]}/api/projects/scan", data=json.dumps({"project_path": str(target)}).encode("utf-8"), headers={"Content-Type": "application/json"}, method="POST")
                with urlopen(request) as response:
                    self.assertEqual(response.status, 202)
                for _ in range(50):
                    with urlopen(f"http://127.0.0.1:{server.server_address[1]}/api/projects/scan-status") as response:
                        payload = json.loads(response.read().decode("utf-8"))
                    if payload["state"] == "complete": break
                    time.sleep(0.02)
                self.assertEqual(payload["state"], "complete")
                self.assertGreaterEqual(payload["evidence_count"], 1)
                self.assertTrue(ProjectWorkspace(state_root, target).exists())
            finally:
                server.shutdown(); server.server_close(); thread.join(timeout=2)

    def test_http_investigation_answers_from_team_truth_and_evidence(self):
        events = sample_events()
        selected = next(fact for fact in derive_facts(events) if fact.value.endswith("[active]"))
        server = create_dashboard_server(
            events,
            host="127.0.0.1",
            port=0,
            fact_reviews=[{"action": "accept_fact", "fact_id": selected.id, "subject_key": selected.subject_key, "reviewer": "owner"}],
        )
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_address[1]}"
        try:
            request = Request(
                base + "/api/investigate",
                data=json.dumps({"question": "Why is the project in its current state, and what should happen next?"}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urlopen(request) as response:
                answer = json.loads(response.read().decode("utf-8"))
            self.assertIn(selected.value, answer["active_tasks"])
            self.assertIn("e1", answer["evidence_ids"])
            self.assertEqual(answer["conflicts"][0]["sides"][0]["status"], "accepted")
            self.assertTrue(answer["next_action"])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_http_review_confirms_relation_and_rejects_blank_reviewer(self):
        events = sample_events()
        confirmed = []

        def review(action, relation_id, reviewer):
            if action != "confirm_relation":
                raise ValueError("unsupported review action")
            if not reviewer.strip():
                raise ValueError("reviewer is required")
            candidate = next(item for item in build_evidence_index(events).candidate_relations if item.id == relation_id)
            relation = confirm_relation(candidate, reviewer)
            confirmed.append({"relation_id": relation_id, "reviewer": reviewer})
            return build_dashboard_state(events, confirmed_relations=[relation], review_history=confirmed)

        server = create_dashboard_server(events, host="127.0.0.1", port=0, review_callback=review)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_address[1]}"
        try:
            with urlopen(base + "/api/state") as response:
                initial = json.loads(response.read().decode("utf-8"))
            relation_id = initial["candidate_relations"][0]["id"]
            request = Request(
                base + "/api/review",
                data=json.dumps({"relation_id": relation_id, "reviewer": "owner"}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urlopen(request) as response:
                payload = json.loads(response.read().decode("utf-8"))
            self.assertIn("team", payload)
            self.assertEqual(confirmed, [{"relation_id": relation_id, "reviewer": "owner"}])
            with urlopen(base + "/api/state") as response:
                current = json.loads(response.read().decode("utf-8"))
            self.assertEqual(current["review_history"], confirmed)
            self.assertEqual(len(current["confirmed_relations"]), 1)

            invalid = Request(
                base + "/api/review",
                data=json.dumps({"relation_id": relation_id, "reviewer": " "}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with self.assertRaises(HTTPError) as error:
                urlopen(invalid)
            self.assertEqual(error.exception.code, 400)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_http_accept_fact_updates_team_truth_and_keeps_conflict_history(self):
        events = sample_events()
        fact_reviews = []

        def review(action, fact_id, reviewer):
            if action != "accept_fact" or not reviewer.strip():
                raise ValueError("reviewer is required")
            fact_reviews.append({"action": action, "fact_id": fact_id, "reviewer": reviewer})
            return build_dashboard_state(events, fact_reviews=fact_reviews, review_history=fact_reviews)

        server = create_dashboard_server(events, host="127.0.0.1", port=0, review_callback=review)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_address[1]}"
        try:
            with urlopen(base + "/api/state") as response:
                initial = json.loads(response.read().decode("utf-8"))
            selected = next(item["id"] for item in initial["team"]["facts"] if item["status"] == "conflicted")
            request = Request(
                base + "/api/review",
                data=json.dumps({"action": "accept_fact", "fact_id": selected, "reviewer": "owner"}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urlopen(request) as response:
                reviewed = json.loads(response.read().decode("utf-8"))
            team_fact = next(item for item in reviewed["team"]["facts"] if item["id"] == selected)
            self.assertEqual(team_fact["status"], "accepted")
            self.assertEqual(len(reviewed["team"]["conflicts"]), 1)
            self.assertEqual(len(reviewed["review_history"]), 1)
            self.assertFalse(any(item["fact_id"] == selected for item in reviewed["team_review_queue"]))
            self.assertFalse(any(item["status"] == "conflicted" for item in reviewed["team_review_queue"]))
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_cli_web_flag_delegates_scanned_events_to_dashboard(self):
        from project_compass.cli import main

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "README.md").write_text("# Demo", encoding="utf-8")
            with patch("project_compass.cli.run_dashboard") as run_dashboard:
                result = main(["--scan", str(root), "--workspace-root", str(root / "state"), "--web", "--port", "8799"])

        self.assertEqual(result, 0)
        run_dashboard.assert_called_once()
        self.assertEqual(run_dashboard.call_args.kwargs["port"], 8799)
        self.assertEqual(run_dashboard.call_args.kwargs["project_path"], str(root.resolve()))

    def test_layered_view_contract_exposes_overview_process_and_source_layers(self):
        root=Path(__file__).parents[1]/'src/project_compass/web'
        html=(root/'index.html').read_text(encoding='utf8')
        app=(root/'app.js').read_text(encoding='utf8')
        self.assertIn('data-layer="overview"',html)
        self.assertIn('data-layer="process"',html)
        self.assertIn('data-layer="source"',html)
        self.assertIn('概览',html);self.assertIn('过程',html);self.assertIn('原文',html)
        self.assertIn('backfill',app)

    def test_dashboard_state_builds_timeline_chapters_and_thinking_line(self):
        events = sample_events()
        state = build_dashboard_state(events, project_path="C:/Projects/demo")
        team_chapters = state["team"].get("timeline_chapters", [])
        self.assertEqual([ch["sequence"] for ch in team_chapters], ["01", "02", "03", "04"])
        self.assertEqual(team_chapters[0]["chapter_id"], "ch-goal")
        self.assertGreater(team_chapters[0]["count"], 0)
        self.assertGreater(team_chapters[2]["count"], 0)

        thinking = state["team"].get("thinking_line", {})
        self.assertEqual(thinking["root"]["label"], "交付证据看板黄金路径")
        self.assertIn("e1", thinking["root"]["evidence_ids"])
        self.assertTrue(len(thinking["branches"]) >= 1)
        self.assertTrue(any(len(b.get("children", [])) >= 1 for b in thinking["branches"]))

        root = Path(__file__).parents[1] / "src/project_compass/web"
        html = (root / "index.html").read_text(encoding="utf-8")
        app = (root / "app.js").read_text(encoding="utf-8")
        self.assertIn('id="thinking-surface"', html)
        self.assertIn('id="chapter-timeline"', html)
        self.assertIn('id="thinking-line-canvas"', html)
        self.assertIn('id="citation-popover"', html)
        self.assertIn("showCitationPopover", app)
        self.assertIn("renderTimelineAndThinkingLine", app)

    def test_dashboard_state_builds_session_presence_and_handoff_brief(self):
        events = sample_events()
        state = build_dashboard_state(events, project_path="C:/Projects/demo")
        presence = state.get("session_presence", {})
        self.assertIn("team", presence)
        self.assertEqual(presence["team"]["id"], "team")
        self.assertGreaterEqual(presence["team"]["accepted_count"], 0)
        self.assertTrue(isinstance(presence.get("members"), list))
        self.assertTrue(len(presence["members"]) >= 1)

        brief = state.get("handoff_brief", {})
        self.assertEqual(brief["project_name"], "demo")
        self.assertIn("focus_goal", brief)
        self.assertIn("accepted_decisions", brief)
        self.assertIn("pending_candidates", brief)
        self.assertIn("open_todos", brief)
        self.assertIn("markdown", brief)
        self.assertIn("1-Minute Handoff Brief", brief["markdown"])

        root = Path(__file__).parents[1] / "src/project_compass/web"
        html = (root / "index.html").read_text(encoding="utf-8")
        app = (root / "app.js").read_text(encoding="utf-8")
        self.assertIn('id="session-presence-bar"', html)
        self.assertIn('id="handoff-modal"', html)
        self.assertIn('id="btn-handoff-brief"', html)
        self.assertIn("renderSessionPresence", app)
        self.assertIn("openHandoffBrief", app)
        self.assertIn("data-inline-review", app)

    def test_review_controls_never_invent_a_reviewer_identity(self):
        app = (Path(__file__).parents[1] / "src/project_compass/web/app.js").read_text(encoding="utf-8")
        self.assertNotIn("Lead Reviewer", app)
        self.assertNotIn('reviewer-input").value = reviewer', app)
        # v1.7: 团队模式空署名改为 toast 提示，各入口分别提示
        self.assertEqual(app.count("请先填写负责人姓名"), 6)

    def test_http_inline_review_contract_and_presence_mutation(self):
        from project_compass.project_workspace import ProjectWorkspace
        from project_compass.cli import _review_callback
        with tempfile.TemporaryDirectory() as temp_dir:
            proj_dir = Path(temp_dir) / "project"
            proj_dir.mkdir(parents=True, exist_ok=True)
            ws = ProjectWorkspace(Path(temp_dir) / "state", proj_dir)
            ws.save([])
            events = sample_events()
            confirmed, history, accepted = ws.load_review_state()
            callback, confirmed, history, accepted = _review_callback(events, ws, str(proj_dir), confirmed, history, accepted)
            server = create_dashboard_server(events, host="127.0.0.1", port=0, project_path=str(proj_dir), review_callback=callback)
            thread = Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                base_url = f"http://127.0.0.1:{server.server_address[1]}"
                # 1. 负向对抗：未提供 reviewer 时拒绝
                req_fail = Request(f"{base_url}/api/review", data=json.dumps({"action": "accept_fact", "fact_id": "f1", "reviewer": ""}).encode("utf-8"), headers={"Content-Type": "application/json"})
                try:
                    urlopen(req_fail)
                    self.fail("Expected 400 on empty reviewer")
                except HTTPError as exc:
                    self.assertEqual(exc.code, 400)
                    body = json.loads(exc.read().decode("utf-8"))
                    self.assertIn("reviewer is required", body.get("error", ""))

                # 获取一个初始未接受的 fact
                init_state = json.loads(urlopen(f"{base_url}/api/state").read().decode("utf-8"))
                target_fact = next(f for f in init_state["team"]["facts"] if f.get("status") != "accepted")
                target_id = target_fact["id"]
                initial_accepted_count = init_state["session_presence"]["team"]["accepted_count"]

                # 2. 正向秒批：提供合法 reviewer 晋升事实
                req_ok = Request(f"{base_url}/api/review", data=json.dumps({"action": "accept_fact", "fact_id": target_id, "reviewer": "RealOwner"}).encode("utf-8"), headers={"Content-Type": "application/json"})
                res = urlopen(req_ok)
                self.assertEqual(res.status, 200)
                state_after = json.loads(res.read().decode("utf-8"))
                accepted_f = next(f for f in state_after["team"]["facts"] if f["id"] == target_id)
                self.assertEqual(accepted_f["status"], "accepted")
                self.assertEqual(state_after["session_presence"]["team"]["accepted_count"], initial_accepted_count + 1)

                # 3. 幂等对抗：再次提交已被 accepted 的 fact，拒绝并保持安全
                try:
                    urlopen(req_ok)
                    self.fail("Expected 400 on already accepted fact")
                except HTTPError as exc:
                    self.assertEqual(exc.code, 400)
                    body = json.loads(exc.read().decode("utf-8"))
                    self.assertIn("fact already accepted", body.get("error", ""))

                # 4. DOM 结构契约：无 <button 嵌套 <button，内联按钮使用 data-target-id 避免冒泡
                app_js = (Path(__file__).parents[1] / "src/project_compass/web/app.js").read_text(encoding="utf-8")
                self.assertIn('data-target-id="${esc(goal.id)}"', app_js)
                self.assertIn('data-target-id="${esc(fact.id)}"', app_js)
                self.assertIn('role="button"', app_js)
            finally:
                server.shutdown()
                server.server_close()

    def test_http_transcript_watcher_live_ingestion_and_refresh(self):
        from project_compass.transcript_watcher import TranscriptWatcher
        from project_compass.web_server import DashboardHTTPServer
        from project_compass.cli import _review_callback
        from urllib.request import Request, urlopen
        from urllib.error import HTTPError
        import tempfile, shutil

        tmp_dir = Path(tempfile.mkdtemp(prefix="test_live_http_"))
        try:
            transcript_file = tmp_dir / "transcript.jsonl"
            transcript_file.write_text("", encoding="utf-8")
            workspace_dir = tmp_dir / "ws"
            workspace_dir.mkdir(parents=True, exist_ok=True)
            workspace = ProjectWorkspace(workspace_dir, tmp_dir)
            events = sample_events()
            workspace.save(events)

            watcher = TranscriptWatcher(transcript_file, member_id="antigravity", session_id="live_s1")

            def refresh_callback():
                status = watcher.sync(workspace, events)
                return {"enabled": True, **status}

            confirmed, history, accepted = workspace.load_review_state()
            callback, _, _, _ = _review_callback(events, workspace, str(tmp_dir), confirmed, history, accepted)

            server = DashboardHTTPServer(
                ("127.0.0.1", 0),
                events,
                project_path=str(tmp_dir),
                review_callback=callback,
                refresh_callback=refresh_callback,
            )
            thread = Thread(target=server.serve_forever, daemon=True)
            thread.start()

            base_url = f"http://127.0.0.1:{server.server_port}"
            try:
                # 1. 初始状态
                init_res = json.loads(urlopen(f"{base_url}/api/state").read().decode("utf-8"))
                initial_count = init_res["project"]["evidence_count"]

                # 2. 追加完整新事件并触发 /api/refresh
                rec = {
                    "source": "USER_EXPLICIT",
                    "type": "USER_INPUT",
                    "step_index": 101,
                    "created_at": "2026-11-05T08:00:00Z",
                    "content": "<USER_REQUEST>目标：实现真正的实时流式协同看板</USER_REQUEST>",
                }
                with transcript_file.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")

                req_refresh = Request(f"{base_url}/api/refresh", data=b"{}", headers={"Content-Type": "application/json"})
                ref_res = json.loads(urlopen(req_refresh).read().decode("utf-8"))
                self.assertEqual(ref_res["project"]["evidence_count"], initial_count + 1)
                self.assertTrue(any("实时流式协同看板" in str(f.get("value", "")) for f in ref_res["personal"]["antigravity"]["facts"]))

                # 3. 截断保护：写入不完整半截行，刷新不应增加任何脏事件
                with transcript_file.open("a", encoding="utf-8") as f:
                    f.write('{"source": "MODEL", "type": "PLANNER_RESPONSE", "content": "半截未完结')

                ref_res2 = json.loads(urlopen(req_refresh).read().decode("utf-8"))
                self.assertEqual(ref_res2["project"]["evidence_count"], initial_count + 1)

                # 4. 补全该行并换行，再次刷新，事件顺利被增量吸收
                with transcript_file.open("a", encoding="utf-8") as f:
                    f.write('的内容。", "step_index": 102, "created_at": "2026-11-05T08:01:00Z"}\n')

                ref_res3 = json.loads(urlopen(req_refresh).read().decode("utf-8"))
                self.assertEqual(ref_res3["project"]["evidence_count"], initial_count + 2)
            finally:
                server.shutdown()
                server.server_close()
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def test_sample_mode_never_exposes_host_registered_projects(self):
        from project_compass.web_server import DashboardHTTPServer
        from urllib.request import urlopen
        from urllib.error import HTTPError
        import tempfile, shutil

        tmp_dir = Path(tempfile.mkdtemp(prefix="test_sample_isolation_"))
        try:
            ws_root = tmp_dir / "ws"
            host_repo = tmp_dir / "PrivateHostRepo"
            host_repo.mkdir(parents=True, exist_ok=True)
            private_ws = ProjectWorkspace(ws_root, host_repo)
            private_ws.save(sample_events(), {"source": "scan"}, complete_scan=True)
            registered = ProjectWorkspace.list_registered(ws_root)
            self.assertTrue(any(p["project_name"] == "PrivateHostRepo" for p in registered))

            server = DashboardHTTPServer(
                ("127.0.0.1", 0),
                sample_events(),
                project_path=str(tmp_dir / "sample-proj"),
                sample_mode=True,
                workspace_root=ws_root,
            )
            thread = Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base_url = f"http://127.0.0.1:{server.server_port}"
            try:
                raw_body = urlopen(f"{base_url}/api/state").read().decode("utf-8")
                payload = json.loads(raw_body)
                self.assertTrue(payload["sample_mode"])
                self.assertEqual(payload["projects"], [])
                self.assertNotIn("PrivateHostRepo", raw_body)

                target_id = registered[0]["project_id"]
                with self.assertRaises(HTTPError) as ctx:
                    urlopen(f"{base_url}/api/state?project_id={target_id}")
                self.assertEqual(ctx.exception.code, 404)
            finally:
                server.shutdown()
                server.server_close()
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def test_speculative_verified_badge_does_not_hardcode_unverified_100_percent_green(self):
        app_js = (Path(__file__).parents[1] / "src/project_compass/web/app.js").read_text(encoding="utf-8")
        self.assertNotIn("100% 绿灯", app_js)
        self.assertIn("renderSpeculativeBadge", app_js)
        self.assertIn("renderSpeculativeDetail", app_js)


if __name__ == "__main__":
    unittest.main()
