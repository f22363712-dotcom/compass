from pathlib import Path
import re
import unittest


WEB_ROOT = Path(__file__).parents[1] / "src" / "project_compass" / "web"


class WebAssetsTest(unittest.TestCase):
    def test_page_exposes_saved_project_list_surface(self):
        page = (Path(__file__).parents[1] / "src/project_compass/web/index.html").read_text(encoding="utf-8")
        script = (Path(__file__).parents[1] / "src/project_compass/web/app.js").read_text(encoding="utf-8")
        self.assertIn('id="project-list"', page)
        self.assertIn('/api/projects', script)
        self.assertIn('project_id', script)
        self.assertIn('id="project-scan-form"', page)
        self.assertIn('/api/projects/scan', script)
        self.assertIn('扫描仍在进行，可稍后刷新页面查看状态', script)
        self.assertIn('id="personal-activity-list"', page)
        self.assertIn('personal_activity', script)
        self.assertIn('evidence-request-list', page)
        self.assertIn('investigation-stats-list', page)
        self.assertIn('仅保留本次服务运行期间的查询', page)
        self.assertIn('stats-recent', script)
        self.assertIn('export-state', page)
        self.assertIn('/api/export', script)
        self.assertIn('clear-query-stats', page)
        self.assertIn('/api/query-stats/clear', script)
        self.assertIn('candidate-guidance', page)
        self.assertIn('evidenceOnly', script)
        self.assertIn('guidance-extract', script)
        self.assertIn('data-evidence-id', script)
        self.assertIn('id="personal-todo-list"', page)
        self.assertIn('kind === "task"', script)
        self.assertIn('fact.task_state', script)
        self.assertIn('id="personal-decision-list"', page)
        self.assertIn('fact.kind === "decision"', script)
        self.assertIn('item.member_id === state.member', script)
        self.assertIn('未关联证据', script)
        self.assertIn('derived-context-surface', page)
        self.assertIn('derived_context', script)
        self.assertIn('related_node_ids', script)
        self.assertIn('derived-context-edges', script)
        self.assertIn('证据直接来源', script)
        self.assertIn('证据关联结构', script)
    def test_page_exposes_lens_controls_and_evidence_drawer(self):
        html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")

        self.assertIn('data-lens="personal"', html)
        self.assertIn('data-lens="team"', html)
        self.assertIn('id="evidence-drawer"', html)
        self.assertIn('id="evidence-drawer" class="drawer"', html)
        self.assertIn('hidden', html)
        self.assertIn('src="/app.js"', html)

    def test_script_renders_candidate_and_confirmed_relation_labels(self):
        script = (WEB_ROOT / "app.js").read_text(encoding="utf-8")
        html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")

        self.assertIn("candidate", script)
        self.assertIn("confirmed", script)
        self.assertIn("/api/evidence?id=", script)
        self.assertIn("/api/review", script)
        self.assertIn("确认支持关系", script)
        self.assertIn("确认为团队事实", script)
        self.assertIn("review_history", script)
        self.assertIn("/api/investigate", script)
        self.assertIn("当前状态下复用的调查结果", script)
        self.assertIn("formatTime", script)
        self.assertIn("observed_at", script)
        self.assertIn("evidence-filter", html)
        self.assertIn("筛选证据", html)
        self.assertIn("查证据", html)

    def test_layout_allows_long_evidence_titles_without_page_overflow(self):
        css = (WEB_ROOT / "styles.css").read_text(encoding="utf-8")

        self.assertIn("grid-template-columns: 10px minmax(0, 1fr) auto", css)
        self.assertIn("min-width: 0", css)
        self.assertIn("overflow-x: hidden", css)
        self.assertIn(".evidence-item > span", css)

    def test_ui_style_guide_static_gates(self):
        html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
        css = (WEB_ROOT / "styles.css").read_text(encoding="utf-8")
        script = (WEB_ROOT / "app.js").read_text(encoding="utf-8")

        root_match = re.search(r":root\s*\{[^}]*\}", css, re.DOTALL)
        self.assertIsNotNone(root_match, "styles.css must define :root tokens")
        css_outside_root = css[:root_match.start()] + css[root_match.end():]
        css_outside_nc = re.sub(r"/\*.*?\*/", "", css_outside_root, flags=re.DOTALL)
        self.assertEqual(re.findall(r"#[0-9a-fA-F]{3,8}\b", css_outside_nc), [])

        css_nc = re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)
        for text in (html, css, script):
            self.assertIsNone(re.search(r"#0d6e52\b", text, re.IGNORECASE))
            self.assertEqual(text.count("100% 绿灯"), 0)

        for match in re.finditer(r"backdrop-filter\s*:\s*([^;]+);", css_nc, re.IGNORECASE):
            self.assertEqual(match.group(1).strip().lower(), "none")

        for match in re.finditer(r"box-shadow\s*:\s*([^;]+);", css_nc, re.IGNORECASE):
            val = match.group(1).strip()
            if val.lower() == "none":
                continue
            for shadow in val.split(","):
                tokens = [t for t in shadow.strip().split() if not t.startswith(("var(", "#", "rgb"))]
                nums = [t for t in tokens if t.lower() != "inset"]
                if len(nums) >= 3:
                    self.assertIn(nums[2].lower(), ("0", "0px", "0rem"), f"Blur shadow forbidden: {shadow}")

        root_rem_px = 16.0
        def _strip_media_wrappers(text: str) -> str:
            out = []
            i = 0
            stack = []
            while i < len(text):
                if text.startswith("@media", i):
                    brace = text.find("{", i)
                    if brace != -1:
                        stack.append("media")
                        i = brace + 1
                        continue
                ch = text[i]
                if ch == "{":
                    stack.append("rule")
                    out.append(ch)
                elif ch == "}":
                    kind = stack.pop() if stack else "rule"
                    if kind == "rule":
                        out.append(ch)
                else:
                    out.append(ch)
                i += 1
            return "".join(out)

        css_flat = _strip_media_wrappers(css_nc)
        for block in re.finditer(r"([^{}]+)\{([^}]+)\}", css_flat):
            sel_tokens = [s.strip().lower() for s in block.group(1).split(",")]
            body = block.group(2)
            if "html" in sel_tokens:
                rm = re.search(r"font-size\s*:\s*([0-9.]+)px", body, re.IGNORECASE)
                if rm:
                    root_rem_px = float(rm.group(1))
            if re.search(r"background(?:-color)?\s*:\s*var\(--orange\)\b", body, re.IGNORECASE):
                self.assertIsNone(
                    re.search(r"\bcolor\s*:\s*(?:var\(--ink-inverse\)|var\(--surface\)|white)\b", body, re.IGNORECASE),
                    f"Light ink forbidden on --orange background in {block.group(1).strip()}",
                )

        font_sizes_px = []
        for match in re.finditer(r"font-size\s*:\s*([0-9.]+)(px|rem)", css_nc, re.IGNORECASE):
            num = float(match.group(1))
            unit = match.group(2).lower()
            font_sizes_px.append(num if unit == "px" else num * root_rem_px)
        self.assertTrue(font_sizes_px and min(font_sizes_px) >= 12.0, f"Sub-12px font detected: {font_sizes_px}")

        self.assertEqual(re.findall(r"#[0-9a-fA-F]{3,8}\b", html), [])
        self.assertEqual(re.findall(r"#[0-9a-fA-F]{3,8}\b", script), [])
        self.assertIsNone(re.search(r'\bstyle\s*=\s*["\']', html, re.IGNORECASE))
        self.assertIsNone(re.search(r'\bstyle\s*=\s*["\']', script, re.IGNORECASE))

        self.assertEqual(len(re.findall(r"\bfetch\s*\(", script)), 1)
        self.assertIsNone(re.search(r"catch\s*(?:\([^)]*\))?\s*\{\s*\}", script))
        self.assertIsNone(re.search(r"\.catch\s*\(\s*(?:\([^)]*\)|[a-zA-Z_$][\w$]*)\s*=>\s*\{\s*\}\s*\)", script))

        html_ids = set(re.findall(r'\bid="([^"]+)"', html))
        js_ids = set(re.findall(r'document\.getElementById\(\s*[\'"]([^\'"]+)[\'"]\s*\)', script))
        for selector in re.findall(r'\bquerySelector(?:All)?\(\s*[\'"]([^\'"]+)[\'"]\s*\)', script):
            js_ids.update(re.findall(r"#([a-zA-Z_][\w-]*)", selector))
        dynamic_only = {"guidance-extract", "review-note"}
        self.assertEqual(sorted(js_ids - html_ids - dynamic_only), [])


if __name__ == "__main__":
    unittest.main()
