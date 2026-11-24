from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from project_compass.mcp_setup import (
    default_config_path,
    generate_config,
    diagnose_environment,
    main as setup_main,
)


class McpSetupTest(unittest.TestCase):
    def test_generate_claude_config(self) -> None:
        cfg = generate_config("claude", project_path="C:/Demo/Project", member_id="claude-code")
        self.assertIn("mcpServers", cfg)
        self.assertIn("project-compass", cfg["mcpServers"])
        server = cfg["mcpServers"]["project-compass"]
        self.assertEqual(server["command"], "python")
        self.assertIn("project_compass.mcp_server", server["args"])
        self.assertIn("PROJECT_COMPASS_AGENT_TOKEN", server["env"])

    def test_generate_cursor_config(self) -> None:
        cfg = generate_config("cursor", project_path="C:/Demo/Project")
        self.assertIn("mcpServers", cfg)
        self.assertIn("project-compass", cfg["mcpServers"])

    def test_generate_antigravity_config(self) -> None:
        cfg = generate_config("antigravity", project_path="C:/Demo/Project")
        self.assertEqual(cfg["name"], "project-compass")
        self.assertEqual(cfg["protocol"], "mcp-stdio")
        self.assertIn("project_compass.mcp_server", cfg["args"])

    def test_unsupported_client_raises(self) -> None:
        with self.assertRaises(ValueError):
            generate_config("unknown_agent", project_path=".")

    def test_diagnose_environment(self) -> None:
        diag = diagnose_environment(".")
        self.assertTrue(isinstance(diag["healthy"], bool))
        self.assertTrue(len(diag["checks"]) >= 6)
        check_names = [c["name"] for c in diag["checks"]]
        self.assertIn("python_version", check_names)
        self.assertIn("project_directory", check_names)
        self.assertIn("compass_mcp_cli", check_names)
        self.assertIn("node_runtime", check_names)
        self.assertIn("antigravity_sidecar_plugin", check_names)
        parsed_ts = datetime.fromisoformat(diag["timestamp"])
        self.assertIsNotNone(parsed_ts.tzinfo)

    def test_cli_doctor_and_stdout(self) -> None:
        ret = setup_main(["--doctor"])
        self.assertEqual(ret, 0)

        ret = setup_main(["--client", "claude", "--project-path", "."])
        self.assertEqual(ret, 0)

    def test_antigravity_default_config_path_prefers_modern_gemini_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fake_home = Path(tmp)
            with patch("project_compass.mcp_setup.Path.home", return_value=fake_home):
                self.assertEqual(
                    default_config_path("antigravity"),
                    fake_home / ".gemini" / "antigravity" / "mcp_config.json",
                )
                (fake_home / ".gemini" / "config").mkdir(parents=True, exist_ok=True)
                self.assertEqual(
                    default_config_path("antigravity"),
                    fake_home / ".gemini" / "config" / "mcp_config.json",
                )


if __name__ == "__main__":
    unittest.main()
