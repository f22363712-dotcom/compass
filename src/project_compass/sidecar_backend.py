"""Standalone HTTP dashboard backend for Antigravity Sidecar child mode and cross-agent daemon mode."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import threading
import time
from typing import Callable

from .cli import _review_callback
from .host_adapter import _LIVE_SERVER_FILENAME, parse_workspace_uri
from .local_plugin import cold_start_bootstrap_workspace
from .onboarding import load_workspace_derived_context
from .project_refresh import ProjectRescan
from .project_scan_job import ProjectScanJob
from .project_workspace import ProjectWorkspace
from .sample_data import sample_events
from .transcript_watcher import AutoTranscriptIntake, infer_primary_human_member
from .web_server import DashboardHTTPServer, create_dashboard_server


def build_sidecar_server(
    project_path: str | Path,
    *,
    host: str = "127.0.0.1",
    port: int = 0,
    workspace_root: str | Path | None = None,
    sidecar_internal_secret: str | None = None,
    activity_callback: Callable[[], None] | None = None,
) -> DashboardHTTPServer:
    """Create a full Compass DashboardHTTPServer bound to ``project_path`` with cold-start doc bootstrap."""
    resolved = parse_workspace_uri(project_path)
    if not resolved.exists() or not resolved.is_dir():
        raise ValueError(f"project directory does not exist: {resolved}")
    if os.environ.get("SAMPLE_MODE", "").strip().lower() == "true":
        return create_dashboard_server(
            sample_events(),
            host=host,
            port=int(port),
            project_path=str(resolved),
            sample_mode=True,
            sidecar_internal_secret=sidecar_internal_secret,
            activity_callback=activity_callback,
        )
    ws_root = Path(workspace_root).expanduser().resolve() if workspace_root else (resolved / ".project-memory")
    ws = ProjectWorkspace(ws_root, resolved)
    events, _ = cold_start_bootstrap_workspace(ws)
    confirmed, history, fact_reviews = ws.load_review_state() if ws.exists() else ([], [], [])
    review_cb, confirmed, history, fact_reviews = _review_callback(
        events,
        ws,
        str(resolved),
        confirmed,
        history,
        fact_reviews,
    )
    rescan_helper = ProjectRescan(ws, events, extract_docs=True)
    human_member = infer_primary_human_member(events, history)
    auto_intake = AutoTranscriptIntake(
        resolved,
        ws,
        member_id=human_member,
        initial_events=events,
        include_tools=True,
    )
    initial_intake_status = auto_intake.initial_status(events)
    derived_ctx = load_workspace_derived_context(ws)
    return create_dashboard_server(
        events,
        host=host,
        port=int(port),
        project_path=str(resolved),
        confirmed_relations=confirmed,
        review_history=history,
        fact_reviews=fact_reviews,
        review_callback=review_cb,
        refresh_callback=lambda: auto_intake.sync(events, min_interval_sec=0.0),
        intake_status=initial_intake_status,
        sample_mode=False,
        rescan_callback=rescan_helper.refresh,
        workspace_root=ws_root,
        project_scan_job=ProjectScanJob(ws_root),
        derived_context=derived_ctx,
        auto_doc_sync=rescan_helper.sync_if_docs_changed,
        auto_transcript_sync=lambda: auto_intake.sync(events, min_interval_sec=1.5),
        pre_transcript_discover=auto_intake.pre_discover,
        sidecar_internal_secret=sidecar_internal_secret,
        activity_callback=activity_callback,
    )


def _remove_marker_if_owned(marker: Path, *, port: int) -> None:
    try:
        if not marker.is_file():
            return
        data = json.loads(marker.read_text(encoding="utf-8"))
        if int(data.get("pid") or 0) == os.getpid() and int(data.get("port") or 0) == port:
            marker.unlink(missing_ok=True)
    except (OSError, ValueError, json.JSONDecodeError):
        pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Compass sidecar or daemon web backend")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--sidecar-child", action="store_true", help="Bind loopback port 0 and exit cleanly when stdin hits EOF")
    mode.add_argument("--daemon", action="store_true", help="Run idle-bounded background web dashboard daemon")
    parser.add_argument("--project-path", default=".", help="Initial project directory or file:// URI")
    parser.add_argument("--workspace-root", default=None, help="Optional workspace root directory")
    parser.add_argument("--port", type=int, default=8787, help="Port to listen on in --daemon mode")
    parser.add_argument("--idle-timeout", type=int, default=21600, help="Seconds of inactivity before --daemon exits cleanly")
    args = parser.parse_args(argv)

    last_activity = [time.monotonic()]
    activity_lock = threading.Lock()

    def touch_activity() -> None:
        with activity_lock:
            last_activity[0] = time.monotonic()

    secret = os.environ.get("COMPASS_SIDECAR_INTERNAL_SECRET") or None
    bind_port = 0 if args.sidecar_child else int(args.port)
    initial_project_path = args.project_path
    if args.sidecar_child:
        try:
            resolved_initial = parse_workspace_uri(initial_project_path)
            if not resolved_initial.exists() or not resolved_initial.is_dir():
                fallback = Path.cwd().resolve()
                print(
                    f"[compass-sidecar] warning: initial project directory missing ({resolved_initial}); falling back to {fallback}",
                    file=sys.stderr,
                )
                initial_project_path = str(fallback)
        except ValueError:
            fallback = Path.cwd().resolve()
            initial_project_path = str(fallback)
    server = build_sidecar_server(
        initial_project_path,
        host="127.0.0.1",
        port=bind_port,
        workspace_root=args.workspace_root,
        sidecar_internal_secret=secret,
        activity_callback=touch_activity,
    )
    actual_port = int(server.server_address[1])

    if args.sidecar_child:
        def watch_parent_stdin() -> None:
            try:
                stream = getattr(sys.stdin, "buffer", sys.stdin)
                while True:
                    chunk = stream.read(1)
                    if not chunk:
                        break
            except Exception:
                pass
            try:
                server.shutdown()
            except Exception:
                pass

        watcher = threading.Thread(target=watch_parent_stdin, daemon=True)
        watcher.start()
        print(json.dumps({"port": actual_port, "pid": os.getpid()}), flush=True)
        try:
            server.serve_forever()
        finally:
            server.server_close()
        return 0

    # --daemon mode
    ws_root = server.workspace_root or (parse_workspace_uri(args.project_path) / ".project-memory")
    ws_root.mkdir(parents=True, exist_ok=True)
    marker = ws_root / _LIVE_SERVER_FILENAME
    tmp_marker = marker.with_suffix(f".json.tmp.{os.getpid()}")
    tmp_marker.write_text(
        json.dumps(
            {
                "pid": os.getpid(),
                "port": actual_port,
                "url": f"http://127.0.0.1:{actual_port}/",
                "project_path": server.dashboard_project_path,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    os.replace(tmp_marker, marker)

    stop_idle = threading.Event()
    idle_limit = max(2, int(args.idle_timeout))

    def watch_idle() -> None:
        poll_interval = min(5.0, max(0.25, idle_limit / 10.0))
        while not stop_idle.wait(poll_interval):
            with activity_lock:
                elapsed = time.monotonic() - last_activity[0]
            if elapsed >= idle_limit:
                try:
                    server.shutdown()
                except Exception:
                    pass
                return

    idle_thread = threading.Thread(target=watch_idle, daemon=True)
    idle_thread.start()
    print(f"http://127.0.0.1:{actual_port}/", flush=True)
    try:
        server.serve_forever()
    finally:
        stop_idle.set()
        _remove_marker_if_owned(marker, port=actual_port)
        current_ws_root = getattr(server, "workspace_root", None)
        if current_ws_root:
            current_marker = Path(current_ws_root) / _LIVE_SERVER_FILENAME
            if current_marker != marker:
                _remove_marker_if_owned(current_marker, port=actual_port)
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
