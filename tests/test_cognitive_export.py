from __future__ import annotations

import json
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.request import urlopen

from project_compass.cognitive_export import (
    export_github_issue,
    export_pull_request,
    export_prd,
    export_state_by_format,
)
from project_compass.dashboard import build_dashboard_state
from project_compass.sample_data import sample_events
from project_compass.project_workspace import ProjectWorkspace
from project_compass.web_server import DashboardHTTPServer


class CognitiveExportTest(unittest.TestCase):
    def setUp(self) -> None:
        self.mock_state = {
            "project": {"name": "TestApp", "goal": "实现双向认知资产流转", "evidence_count": 12},
            "handoff_brief": {
                "focus_goal": "实现双向认知资产流转",
                "accepted_decisions": ["采用纯原生 Python + Web 架构", "拒绝隐蔽覆盖冲突"],
                "open_todos": ["完成 M2 导出引擎", "编写 PBR 穿透审查报告"],
                "pending_candidates": ["候选题案 A", "候选题案 B"],
            },
            "session_presence": {
                "team": {"id": "team", "accepted_count": 5, "pending_count": 2},
                "members": [{"id": "antigravity"}, {"id": "claude"}],
            },
            "chapter_timeline": [
                {"id": "01", "title": "目标确立", "summary": "确立核心目标", "count": 3},
                {"id": "02", "title": "方案推进", "summary": "落地导出模块", "count": 9},
            ],
            "thinking_line": {
                "root": {"label": "实现双向认知资产流转"},
                "branches": [
                    {
                        "label": "支持 GitHub Issue 与 PR 自动流转",
                        "status": "accepted",
                        "children": [{"label": "通过纯 Markdown 语法保证通用性"}],
                    }
                ],
            },
            "evidence": [{"id": "e1"}],
        }

    def test_export_github_issue(self) -> None:
        md = export_github_issue(self.mock_state)
        self.assertIn("# [Project Issue] TestApp", md)
        self.assertIn("实现双向认知资产流转", md)
        self.assertIn("- [x] **决策**：采用纯原生 Python + Web 架构", md)
        self.assertIn("- [ ] 完成 M2 导出引擎", md)
        self.assertIn("- [ ] **待确认**：候选题案 A", md)
        self.assertIn("Total Evidence Items: 12", md)

    def test_export_pull_request(self) -> None:
        md = export_pull_request(self.mock_state)
        self.assertIn("## 🚀 PR: TestApp Feature Implementation", md)
        self.assertIn("实现双向认知资产流转", md)
        self.assertIn("- [ ] 完成 M2 导出引擎", md)
        self.assertNotIn("- [x] 完成 M2 导出引擎", md)
        self.assertIn("已确认事项数**：5 项", md)
        self.assertIn("`antigravity`, `claude`", md)
        self.assertIn("- [ ] 单元测试全部通过（待提交前本地实跑核对）", md)
        self.assertIn("- [ ] 遵循 IEEE TSE 2001 PBR 三视角代码审查无 P0/P1 缺陷", md)
        self.assertNotIn("100% 绿色通过", md)

    def test_export_real_dashboard_state_honesty_and_schema(self) -> None:
        real_state = build_dashboard_state(sample_events(), project_path=str(Path(__file__).parents[1]))
        pr_md = export_pull_request(real_state)
        self.assertIn("`dev-a`, `dev-b`", pr_md)
        self.assertNotIn("`Local Developer`", pr_md)
        for line in pr_md.splitlines():
            if "[blocked]" in line:
                self.assertTrue(line.startswith("- [ ] "), f"Blocked task marked completed: {line}")

        issue_md = export_github_issue(real_state)
        self.assertIn("[blocked]", issue_md)
        for line in issue_md.splitlines():
            if "[blocked]" in line:
                self.assertTrue(line.startswith("- [ ] "), f"Blocked issue item marked completed: {line}")

        prd_md = export_prd(real_state)
        self.assertIn("阶段 01：目标确立", prd_md)
        self.assertIn("目标根节点 (Goal Root)", prd_md)
        self.assertNotIn("_暂无阶段划分数据。_", prd_md)
        self.assertNotIn("_暂无结构化决策树。_", prd_md)

    def test_export_prd(self) -> None:
        md = export_prd(self.mock_state)
        self.assertIn("# 产品需求与技术规格说明书 (PRD / SPEC)", md)
        self.assertIn("阶段 01：目标确立 (3 项证据)", md)
        self.assertIn("阶段 02：方案推进 (9 项证据)", md)
        self.assertIn("目标根节点 (Goal Root)**：实现双向认知资产流转", md)
        self.assertIn("分支决策 [accepted]**：支持 GitHub Issue 与 PR 自动流转", md)
        self.assertIn("[已确认规范]**：采用纯原生 Python + Web 架构", md)

    def test_export_state_by_format_mapping(self) -> None:
        body_json, mime_json, fn_json = export_state_by_format(self.mock_state, "json")
        self.assertIn("application/json", mime_json)
        self.assertTrue(fn_json.endswith(".json"))

        body_issue, mime_issue, fn_issue = export_state_by_format(self.mock_state, "issue")
        self.assertIn("text/markdown", mime_issue)
        self.assertTrue(fn_issue.endswith("-github-issue.md"))

        body_pr, mime_pr, fn_pr = export_state_by_format(self.mock_state, "pr")
        self.assertIn("text/markdown", mime_pr)
        self.assertTrue(fn_pr.endswith("-pull-request.md"))

        body_prd, mime_prd, fn_prd = export_state_by_format(self.mock_state, "prd")
        self.assertIn("text/markdown", mime_prd)
        self.assertTrue(fn_prd.endswith("-prd-spec.md"))

    def test_http_export_socket_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            events = sample_events()
            server = DashboardHTTPServer(
                ("127.0.0.1", 0),
                events,
                project_path=tmp_dir,
            )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base_url = f"http://127.0.0.1:{server.server_port}"
            try:
                # 1. 默认 JSON 导出
                res_json = urlopen(f"{base_url}/api/export")
                self.assertEqual(res_json.status, 200)
                self.assertIn("application/json", res_json.headers.get("Content-Type", ""))
                payload = json.loads(res_json.read().decode("utf-8"))
                self.assertEqual(payload["schema_version"], 1)

                # 2. GitHub Issue 格式
                res_issue = urlopen(f"{base_url}/api/export?format=issue")
                self.assertEqual(res_issue.status, 200)
                self.assertIn("text/markdown", res_issue.headers.get("Content-Type", ""))
                self.assertIn("attachment; filename=", res_issue.headers.get("Content-Disposition", ""))
                issue_text = res_issue.read().decode("utf-8")
                self.assertIn("# [Project Issue]", issue_text)

                # 3. PR 描述格式
                res_pr = urlopen(f"{base_url}/api/export?format=pr")
                self.assertEqual(res_pr.status, 200)
                pr_text = res_pr.read().decode("utf-8")
                self.assertIn("## 🚀 PR:", pr_text)

                # 4. 完整 PRD 格式
                res_prd = urlopen(f"{base_url}/api/export?format=prd")
                self.assertEqual(res_prd.status, 200)
                prd_text = res_prd.read().decode("utf-8")
                self.assertIn("产品需求与技术规格说明书 (PRD / SPEC)", prd_text)
            finally:
                server.shutdown()
                server.server_close()

    def test_empty_project_exports_omit_compass_specific_placeholders(self) -> None:
        empty_state = build_dashboard_state([], project_path=None)
        issue_md = export_github_issue(empty_state)
        pr_md = export_pull_request(empty_state)
        prd_md = export_prd(empty_state)

        self.assertNotIn("落实当前模块黄金路径", issue_md)
        self.assertNotIn("src/project_compass/web/app.js", pr_md)
        self.assertNotIn("Local Developer", pr_md)
        self.assertNotIn("围绕人的视线聚焦", prd_md)
        self.assertNotIn("多 Agent 协作开发中日志海量冗余", prd_md)
        self.assertNotIn("基础数据管道与只读回放机制", prd_md)
        self.assertNotIn("完善各模块验收测试", prd_md)


if __name__ == "__main__":
    unittest.main()
