from pathlib import Path
import shutil
import subprocess
import unittest


class WebV11SoloAndMindmapTest(unittest.TestCase):
    def test_v11_solo_workbench_mindmap_quick_notes_and_inline_signer(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("Node required")
        root = Path(__file__).parents[1]
        result = subprocess.run(
            [
                node,
                str(root / "tests" / "web_v11_solo_and_mindmap_test.cjs"),
                str(root / "src" / "project_compass" / "web" / "app.js"),
            ],
            capture_output=True,
            text=True,
            encoding="utf8",
            timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
