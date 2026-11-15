import json
from pathlib import Path
import unittest


class PluginManifestTests(unittest.TestCase):
    def test_manifest_and_mcp_config_are_portable_and_secret_free(self):
        root = Path(__file__).resolve().parents[1]
        manifest = json.loads((root / "plugin.json").read_text(encoding="utf-8"))
        config = json.loads((root / "mcp.json").read_text(encoding="utf-8"))

        self.assertEqual(manifest["mcpServers"], "./mcp.json")
        server = config["mcpServers"]["project-compass"]
        self.assertEqual(server["type"], "stdio")
        self.assertEqual(server["command"], "project-compass-mcp")
        serialized = json.dumps(config)
        self.assertNotIn("TYPESAFE_API_KEY", serialized)
        self.assertNotIn("Bearer ", serialized)
        self.assertIn("SET_IN_HOST_ENVIRONMENT", serialized)

    def test_version_and_honesty_across_manifests(self):
        import re

        root = Path(__file__).resolve().parents[1]
        pyproject_text = (root / "pyproject.toml").read_text(encoding="utf-8")
        try:
            import tomllib

            expected_version = tomllib.loads(pyproject_text)["project"]["version"]
        except ImportError:
            match = re.search(r'^version\s*=\s*"([^"]+)"', pyproject_text, re.MULTILINE)
            self.assertIsNotNone(match)
            expected_version = match.group(1)
        manifest = json.loads((root / "plugin.json").read_text(encoding="utf-8"))
        server = json.loads((root / "server.json").read_text(encoding="utf-8"))
        index_html = (root / "src" / "project_compass" / "web" / "index.html").read_text(encoding="utf-8")

        self.assertEqual(expected_version, "1.0.0")
        self.assertEqual(manifest["version"], expected_version)
        self.assertEqual(server["version"], expected_version)
        self.assertIn("v1.0", index_html)
        self.assertNotIn("your-org", json.dumps(server))
        self.assertNotIn("0.15s", server["description"])


if __name__ == "__main__":
    unittest.main()
