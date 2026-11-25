"""Unit tests for the reusable Project Compass UX & Motion gate."""

from __future__ import annotations

from pathlib import Path
import shutil
import tempfile
import unittest

import scripts.ux_gate as ux_gate


REPO_ROOT = Path(__file__).resolve().parents[1]


class UXGateTests(unittest.TestCase):
    def _make_clean_fixture_repo(self, root: Path) -> None:
        web_dir = root / "src" / "project_compass" / "web"
        web_dir.mkdir(parents=True, exist_ok=True)
        (web_dir / "index.html").write_text("<!doctype html><html><body>OK</body></html>", encoding="utf-8")
        (web_dir / "app.js").write_text("function render() { return true; }\n", encoding="utf-8")
        css = """
:root {
  --motion-fast: 120ms;
  --motion-base: 200ms;
  --motion-slow: 320ms;
  --ease-out: cubic-bezier(0.22, 1, 0.36, 1);
  --ease-in-out: cubic-bezier(0.65, 0, 0.35, 1);
  --ease-exit: cubic-bezier(0.4, 0, 1, 1);
}
button {
  transition: transform var(--motion-fast) var(--ease-out), opacity var(--motion-base) var(--ease-out);
}
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { animation-duration: 0.01ms !important; transition-duration: 0.01ms !important; }
}
"""
        (web_dir / "styles.css").write_text(css, encoding="utf-8")
        (web_dir / "mcp_app.html").write_text(
            f"<!doctype html><html><head><style>{css}</style></head><body><script>const COMPASS_LOGO_SVG='';</script></body></html>",
            encoding="utf-8",
        )

    def test_real_repository_passes_ux_gate(self) -> None:
        errors = ux_gate.run_gate(REPO_ROOT)
        self.assertEqual(errors, [])

    def test_rejects_unallowlisted_legacy_term_and_allows_allowlisted_enum(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._make_clean_fixture_repo(root)
            app_js = root / "src" / "project_compass" / "web" / "app.js"
            app_js.write_text('const x = {"待定锚点": "还没定目标"};\n', encoding="utf-8")
            self.assertEqual(ux_gate.run_gate(root), [])

            app_js.write_text('const btn = "一键拍板";\n', encoding="utf-8")
            errors = ux_gate.run_gate(root)
            self.assertTrue(any("[banned-copy]" in e and "拍板" in e for e in errors), errors)

    def test_rejects_forbidden_layout_transition_and_missing_reduced_motion(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._make_clean_fixture_repo(root)
            css_path = root / "src" / "project_compass" / "web" / "styles.css"
            bad_css = """
:root { --motion-fast: 120ms; }
.card { transition: width 200ms ease, height 200ms ease; }
"""
            css_path.write_text(bad_css, encoding="utf-8")
            errors = ux_gate.run_gate(root)
            self.assertTrue(any("[motion-token]" in e for e in errors), errors)
            self.assertTrue(any("[reduced-motion]" in e for e in errors), errors)
            self.assertTrue(any("[forbidden-transition]" in e and "width" in e for e in errors), errors)

    def test_rejects_blocking_confirm_dialog_in_web_scripts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._make_clean_fixture_repo(root)
            app_js = root / "src" / "project_compass" / "web" / "app.js"
            app_js.write_text("function danger() { if (confirm('sure?')) return 1; }\n", encoding="utf-8")
            errors = ux_gate.run_gate(root)
            self.assertTrue(any("[blocking-dialog]" in e for e in errors), errors)

    def test_rejects_template_literal_comment_bypass_window_confirm_and_transition_all(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._make_clean_fixture_repo(root)
            app_js = root / "src" / "project_compass" / "web" / "app.js"
            app_js.write_text('const u = `compass://host`; window.confirm("sure?");\n', encoding="utf-8")
            css_path = root / "src" / "project_compass" / "web" / "styles.css"
            css_text = css_path.read_text(encoding="utf-8") + "\n.card { transition: all 120ms ease; }\n"
            css_path.write_text(css_text, encoding="utf-8")
            errors = ux_gate.run_gate(root)
            self.assertTrue(any("[blocking-dialog]" in e for e in errors), errors)
            self.assertTrue(any("[forbidden-transition]" in e and "'all'" in e for e in errors), errors)

    def test_rejects_keyframes_layout_prop_readme_copy_and_early_mcp_dialog(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._make_clean_fixture_repo(root)
            (root / "README.md").write_text("个人路线介绍\n", encoding="utf-8")
            css_path = root / "src" / "project_compass" / "web" / "styles.css"
            css_path.write_text(
                css_path.read_text(encoding="utf-8")
                + "\n@keyframes jump { from { top: 0px; } to { top: 10px; } }\n",
                encoding="utf-8",
            )
            (root / "src" / "project_compass" / "web" / "app.js").write_text(
                "const x = `hi ${window.confirm('x')}`;\n",
                encoding="utf-8",
            )
            mcp_path = root / "src" / "project_compass" / "web" / "mcp_app.html"
            mcp_css = (root / "src" / "project_compass" / "web" / "styles.css").read_text(encoding="utf-8").split("@keyframes")[0]
            mcp_path.write_text(
                f"<!doctype html><html><head><style>{mcp_css}</style></head><body><script>var uy=[];alert('early');var COMPASS_LOGO_SVG='';</script></body></html>",
                encoding="utf-8",
            )
            errors = ux_gate.run_gate(root)
            self.assertTrue(any("[banned-copy]" in e and "README.md" in e for e in errors), errors)
            self.assertTrue(any("[forbidden-keyframes]" in e and "top" in e for e in errors), errors)
            self.assertTrue(any("[blocking-dialog]" in e and "web/app.js" in e for e in errors), errors)
            self.assertTrue(any("[blocking-dialog]" in e and "web/mcp_app.html" in e for e in errors), errors)

    def test_main_exit_code_matches_gate_status(self) -> None:
        code = ux_gate.main(["--repo-root", str(REPO_ROOT)])
        self.assertEqual(code, 0)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._make_clean_fixture_repo(root)
            (root / "src" / "project_compass" / "web" / "index.html").write_text("<div>施工队列</div>", encoding="utf-8")
            allowlist_copy = root / "allow.json"
            shutil.copyfile(REPO_ROOT / "scripts" / "ux_gate_allowlist.json", allowlist_copy)
            bad_code = ux_gate.main(["--repo-root", str(root), "--allowlist", str(allowlist_copy)])
            self.assertEqual(bad_code, 1)


if __name__ == "__main__":
    unittest.main()
