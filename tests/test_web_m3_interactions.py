from pathlib import Path
import shutil
import subprocess
import unittest


class WebM3InteractionsTest(unittest.TestCase):
    def test_m3_swiss_ui_interactions_honesty_and_overlay_stack(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("Node required")
        root = Path(__file__).parents[1]
        result = subprocess.run(
            [
                node,
                str(root / "tests" / "web_m3_interactions_test.cjs"),
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
