from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import threading
import time

from .codex_plugin_bridge import CodexPluginBridge
from .local_plugin import LocalPluginAdapter
from .plugin_protocol import ProjectContext


class CodexWatchRunner:
    def __init__(self, bridge, *, interval: float = 5.0):
        if interval <= 0:
            raise ValueError("watch interval must be positive")
        self.bridge = bridge
        self.interval = interval
        self.stop_event = threading.Event()

    def run_once(self) -> dict:
        return self.bridge.sync()

    def run_forever(self, emit=print) -> None:
        while not self.stop_event.is_set():
            try:
                emit(json.dumps(self.run_once(), ensure_ascii=False))
            except (OSError, ValueError, RuntimeError) as exc:
                emit(json.dumps({"error": "Codex watch tick failed", "detail": str(exc)}, ensure_ascii=False))
            self.stop_event.wait(self.interval)

    def stop(self) -> None:
        self.stop_event.set()
        self.bridge.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Continuously bridge a Codex rollout into ProjectCompass")
    parser.add_argument("--base-url", default=os.environ.get("PROJECT_COMPASS_BASE_URL"))
    parser.add_argument("--project-path", required=True)
    parser.add_argument("--sessions-root", type=Path, default=Path.home() / ".codex" / "sessions")
    parser.add_argument("--thread-id", required=True)
    parser.add_argument("--member-id", required=True)
    parser.add_argument("--agent", default="codex")
    parser.add_argument("--token-env", default="PROJECT_COMPASS_AGENT_TOKEN")
    parser.add_argument("--interval", type=float, default=5.0)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args(argv)
    token = os.environ.get(args.token_env)
    if not args.base_url or not token:
        parser.error("--base-url and the token environment variable are required")
    context = ProjectContext.for_project(args.project_path, args.member_id, args.thread_id, args.agent)
    adapter = LocalPluginAdapter(args.base_url, context, token)
    bridge = CodexPluginBridge(adapter, args.sessions_root, args.project_path, args.thread_id, args.member_id)
    runner = CodexWatchRunner(bridge, interval=args.interval)
    if args.once:
        print(json.dumps(runner.run_once(), ensure_ascii=False))
    else:
        runner.run_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
