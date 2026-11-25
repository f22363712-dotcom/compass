from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from .evidence_store import EvidenceStore
from .env_loader import load_env_file
from .dashboard import build_dashboard_state
from .codex_extractor import CodexExtractor
from .evidence_linking import build_evidence_index, build_requested_evidence_relations, confirm_relation
from .fact_engine import derive_facts
from .investigator import investigate
from .sample_data import sample_events, showcase_sample_events
from .project_scanner import scan_project
from .project_workspace import ProjectWorkspace
from .projections import build_views
from .web_server import run_dashboard
from .native_codex import NativeCodexIntake
from .project_refresh import ProjectRescan
from .source_currentness import source_states, needs_source_review
from .extraction_jobs import ExtractionJobs
from .agent_inbox import AgentInbox
from .project_scan_job import ProjectScanJob


QUESTION = "Why is the project in its current state, and what should happen next?"
PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _log_model_usage(entry: dict) -> None:
    usage_path = PROJECT_ROOT / "logs/model-usage.jsonl"
    usage_path.parent.mkdir(parents=True, exist_ok=True)
    with usage_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _review_callback(events, project_workspace: ProjectWorkspace, project_path: str, confirmed_relations, review_history, fact_reviews):
    from .directions import DIRECTION_ACTIONS, direction_review_fields
    confirmed = list(confirmed_relations)
    history = list(review_history)
    accepted = list(fact_reviews)

    def review(action: str, target_id: str, reviewer: str, note: str = "") -> dict:
        if not reviewer.strip():
            raise ValueError("reviewer is required")
        next_confirmed = list(confirmed)
        next_history = list(history)
        next_accepted = list(accepted)
        if action == "confirm_relation":
            facts = derive_facts(events)
            index = build_evidence_index(events, facts).with_candidate_relations(build_requested_evidence_relations(events, facts, history))
            candidate = next((item for item in index.candidate_relations if item.id == target_id), None)
            if candidate is None:
                raise ValueError("candidate relation not found")
            relation = confirm_relation(candidate, reviewer)
            if any(existing.id == relation.id for existing in confirmed):
                raise ValueError("relation already confirmed")
            next_confirmed.append(relation)
            next_history.append({
                "action": action,
                "relation_id": relation.id,
                "fact_id": relation.fact_id,
                "evidence_id": relation.evidence_id,
                "reviewer": reviewer,
                "observed_at": datetime.now(timezone.utc).isoformat(),
                **({"note": note.strip()} if note.strip() else {}),
            })
        elif action in {"reject_fact", "request_evidence", "complete_fact"}:
            fact = next((item for item in derive_facts(events) if item.id == target_id), None)
            if fact is None:
                raise ValueError("fact not found")
            latest = next((item for item in reversed(history) if item.get("fact_id") == fact.id), None)
            if latest and latest.get("action") == action:
                raise ValueError("fact already has this review status")
            source_state = source_states(events, [fact])[fact.id]
            next_history.append({
                "action": action, "fact_id": fact.id, "subject_key": fact.subject_key,
                "kind": fact.kind.value, "value": fact.value,
                "evidence_ids": list(fact.evidence_ids), "source_ref": fact.source_ref,
                "source_state": source_state, "reviewer": reviewer,
                "observed_at": datetime.now(timezone.utc).isoformat(),
                **({"note": note.strip()} if note.strip() else {}),
            })
        elif action == "accept_fact" or action in DIRECTION_ACTIONS:
            fact = next((item for item in derive_facts(events) if item.id == target_id), None)
            if fact is None:
                raise ValueError("fact not found")
            if needs_source_review(source_states(events, [fact])[fact.id]):
                raise ValueError('source is superseded or unavailable; review the current source before promoting a fact')
            direction_fields=direction_review_fields(action,fact,accepted) if action in DIRECTION_ACTIONS else {}
            latest_accept_state = next(
                (
                    item for item in reversed(history)
                    if item.get("fact_id") == fact.id and item.get("action") != "confirm_relation"
                ),
                None,
            )
            already_accepted = (
                latest_accept_state.get("action") == "accept_fact"
                if latest_accept_state is not None
                else any(item.get("fact_id") == fact.id for item in accepted)
            )
            if action == 'accept_fact' and already_accepted:
                raise ValueError("fact already accepted")
            source_state = source_states(events, [fact])[fact.id]
            active_request = next((item for item in reversed(history) if item.get("fact_id") == fact.id and item.get("action") == "request_evidence"), None)
            resolved_relations = [relation for relation in confirmed if relation.fact_id == fact.id]
            review_entry = {
                "action": "accept_fact",
                "fact_id": fact.id,
                "subject_key": fact.subject_key,
                "kind": fact.kind.value,
                "value": fact.value,
                "evidence_ids": list(fact.evidence_ids),
                "source_ref": fact.source_ref,
                "source_state": source_state,
                "reviewer": reviewer,
                "observed_at": datetime.now(timezone.utc).isoformat(),
                **({"note": note.strip()} if note.strip() else {}),
                **direction_fields,
            }
            if active_request:
                review_entry.update({
                    "evidence_request_id": f"evidence-request-{fact.id}",
                    "resolved_relation_ids": [relation.id for relation in resolved_relations],
                    "resolved_evidence_ids": sorted({relation.evidence_id for relation in resolved_relations}),
                })
            next_accepted.append(dict(review_entry))
            next_history.append(dict(next_accepted[-1]))
            next_history[-1]['action']=action
        else:
            raise ValueError("unsupported review action")
        project_workspace.save_review_state(
            next_confirmed,
            next_history,
            next_accepted,
            merge_existing=True,
        )
        merged_rel, merged_hist, merged_acc = project_workspace.load_review_state()
        confirmed[:] = merged_rel
        history[:] = merged_hist
        accepted[:] = merged_acc
        return build_dashboard_state(events, project_path, confirmed, history, accepted)

    def sync_from_disk(fresh_relations=None, fresh_history=None, fresh_accepted=None) -> None:
        if fresh_relations is not None:
            confirmed[:] = list(fresh_relations)
        if fresh_history is not None:
            history[:] = list(fresh_history)
        if fresh_accepted is not None:
            accepted[:] = list(fresh_accepted)

    review.sync_from_disk = sync_from_disk
    return review, confirmed, history, accepted


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the Project Compass golden path")
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--sample", action="store_true")
    source.add_argument("--demo", action="store_true", help="Launch an interactive local demo web board with a Chinese showcase project")
    source.add_argument("--input", type=Path, help="JSON evidence array")
    source.add_argument("--codex-jsonl", type=Path, help="Codex public session events in JSONL")
    source.add_argument("--scan", type=Path, help="Scan an existing project directory")
    source.add_argument("--open", type=Path, help="Open a previously persisted project state")
    parser.add_argument("--antigravity-transcript", type=Path, help="Antigravity transcript.jsonl conversation log to import")
    parser.add_argument("--antigravity-tools", action="store_true", help="Opt into tool_call/tool_result records when importing an Antigravity transcript")
    parser.add_argument("--scan-codex-jsonl", type=Path, action="append", default=[], help="JSONL session to include with --scan")
    parser.add_argument("--state", type=Path, help="Optional persisted evidence state output")
    parser.add_argument("--evidence-index", action="store_true", help="Print evidence catalog and relation suggestions")
    parser.add_argument("--extract-codex", action="store_true", help="Explicitly extract a bounded candidate batch using saved Codex CLI auth")
    parser.add_argument('--enable-extraction', action='store_true', help='Enable bounded manual candidate jobs in the real web board')
    parser.add_argument('--auto-extract', action='store_true', help='Opt into automatic bounded candidate jobs; implies --enable-extraction')
    parser.add_argument('--extraction-max-batches', type=int, default=2, help='Maximum admitted live batches for this server start')
    parser.add_argument('--extraction-max-tokens', type=int, default=80000, help='Stop live admissions after this actual known-token threshold; a request may cross it')
    parser.add_argument("--member-id", help="Developer identity for public user/assistant collaboration")
    parser.add_argument("--codex-thread", help="Explicit native Codex thread UUID to capture")
    parser.add_argument('--agent-access-file', type=Path, help='Private project-bound Agent HTTP client config; requires a real web workspace')
    parser.add_argument('--codex-tools', action='store_true', help='Opt into bounded public exec text call/result pairs from the selected thread')
    parser.add_argument("--codex-sessions-root", type=Path, default=Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))) / "sessions", help="Native rollout root for the selected thread")
    parser.add_argument("--web", action="store_true", help="Start the local personal/team dashboard")
    parser.add_argument("--no-browser", action="store_true", help="Do not auto-open the system browser when starting --demo")
    parser.add_argument('--reason-preview',type=Path,help='Read a project-bound private reason experiment as a model-free, read-only preview')
    parser.add_argument('--derived-context', type=Path, help='Read a project-bound code-structure JSON as a read-only derived context')
    parser.add_argument('--extract-docs', action='store_true', help='Deterministically extract bounded candidate facts from scanned project docs')
    parser.add_argument('--with-code-index', action='store_true', help='Attach built-in Python AST code structure graph as read-only DerivedContext')
    parser.add_argument("--port", type=int, default=8787, help="Dashboard port for --web")
    parser.add_argument("--workspace-root", type=Path, default=Path(".project-memory"), help="Local root for persisted project states")
    parser.add_argument("--export-format", choices=["issue", "pr", "prd", "mindmap", "json"], help="Export cognitive assets (GitHub Issue, PR description, PRD, or Mermaid mindmap) and print to stdout")
    parser.add_argument("--index-code", action="store_true", help="Build AST code symbol & call graph summary for --scan/--open or current directory and exit")
    parser.add_argument("--list-projects", action="store_true", help="List persisted project workspaces and exit")
    parser.add_argument(
        "--env-file",
        type=Path,
        default=PROJECT_ROOT / ".env",
        help="Local credentials file; process environment variables take precedence",
    )
    args = parser.parse_args(argv)
    try:
        load_env_file(args.env_file)
        args.enable_extraction = args.enable_extraction or args.auto_extract
        if args.list_projects:
            print(json.dumps(ProjectWorkspace.list_registered(args.workspace_root), ensure_ascii=False, indent=2))
            return 0
        if not any((args.sample, args.demo, args.input, args.codex_jsonl, args.scan, args.open)):
            if os.environ.get('SAMPLE_MODE', '').strip().casefold() == 'true':
                args.sample = True
        if args.demo and not any((args.export_format, args.evidence_index, args.state)):
            args.web = True
        if args.index_code:
            if args.sample or args.demo:
                raise ValueError("--index-code cannot run with --sample or --demo")
            from .code_index import build_code_index, code_index_summary
            target_root = Path(args.scan or args.open or Path.cwd()).resolve()
            index_payload = build_code_index(target_root)
            print(
                json.dumps(
                    {
                        "project_path": str(target_root),
                        "summary": code_index_summary(index_payload),
                        "warnings": list(index_payload.get("warnings") or []),
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0
        if not any((args.sample, args.demo, args.input, args.codex_jsonl, args.scan, args.open)):
            parser.error('select a source (--sample, --demo, --input, --codex-jsonl, --scan, --open), or set SAMPLE_MODE=true')
        is_synthetic_sample = bool(args.sample or args.demo)
        if args.reason_preview and not (args.web and (args.scan or args.open)):
            raise ValueError('--reason-preview requires a real web workspace; sample mode cannot read private reason previews')
        if args.derived_context and not (args.web and (args.scan or args.open)):
            raise ValueError('--derived-context requires --web with --scan or --open')
        if args.with_code_index and not (args.scan or args.open):
            raise ValueError('--with-code-index requires --scan or --open')
        if args.extract_docs and is_synthetic_sample:
            raise ValueError('sample mode cannot enable model, sponsor or native project inputs')
        if is_synthetic_sample and (args.extract_codex or args.enable_extraction or args.codex_thread or args.codex_tools or args.scan_codex_jsonl or args.agent_access_file or args.reason_preview or args.derived_context or args.antigravity_transcript or args.extract_docs or args.with_code_index):
            raise ValueError('sample mode cannot enable model, sponsor or native project inputs')
        if args.agent_access_file and not (args.web and (args.scan or args.open)):
            raise ValueError('--agent-access-file requires --web and a real --scan or --open workspace')
        if args.enable_extraction:
            if not (args.web and (args.scan or args.open) and args.member_id and args.member_id.strip()):
                raise ValueError('--enable-extraction requires a real web project and explicit --member-id')
            if args.extract_codex or args.extraction_max_batches < 1 or args.extraction_max_tokens < 1:
                raise ValueError('choose one-shot or live extraction, with positive live budgets')
        if args.extract_codex and (not (args.scan or args.open) or not args.member_id or not args.member_id.strip()):
            raise ValueError("--extract-codex requires --scan or --open and an explicit --member-id")
        if args.codex_thread and (not (args.scan or args.open) or not args.member_id or not args.member_id.strip()):
            raise ValueError("--codex-thread requires --scan or --open and an explicit --member-id")
        if args.codex_tools and not args.codex_thread:
            raise ValueError('--codex-tools requires an explicitly selected --codex-thread')
        project_workspace = None
        project_path = None
        derived_context = None
        if args.sample or args.demo:
            events = showcase_sample_events() if args.demo else sample_events()
            if args.web:
                sample_ws_dir = args.workspace_root / ("demo" if args.demo else "sample")
                default_examples = PROJECT_ROOT / "examples"
                if args.demo or not default_examples.is_dir():
                    synthetic_proj_dir = args.workspace_root / ("demo-podcast-clipper" if args.demo else "sample-project")
                    synthetic_proj_dir.mkdir(parents=True, exist_ok=True)
                else:
                    synthetic_proj_dir = default_examples
                project_workspace = ProjectWorkspace(sample_ws_dir, synthetic_proj_dir)
                project_path = str(project_workspace.project_path)
                if args.demo:
                    try:
                        project_workspace.save(events, {"source": "demo", "synthetic": True})
                    except ValueError as exc:
                        if "already exists with different content" not in str(exc):
                            raise
                        import shutil

                        shutil.rmtree(project_workspace.state_path.parent, ignore_errors=True)
                        project_workspace = ProjectWorkspace(sample_ws_dir, synthetic_proj_dir)
                        project_workspace.save(events, {"source": "demo", "synthetic": True})
                elif not project_workspace.exists():
                    project_workspace.save(events, {"source": "sample", "synthetic": True})
                events = project_workspace.load()
        elif args.codex_jsonl:
            events = EvidenceStore.load_jsonl(args.codex_jsonl).list()
        elif args.scan:
            events = scan_project(args.scan, codex_paths=args.scan_codex_jsonl)
            project_workspace = ProjectWorkspace(args.workspace_root, args.scan)
            project_path = str(project_workspace.project_path)
            project_workspace.save(events, {"source": "scan"}, complete_scan=True)
            events = project_workspace.load()
        elif args.open:
            project_workspace = ProjectWorkspace(args.workspace_root, args.open)
            project_path = str(project_workspace.project_path)
            events = project_workspace.load()
        else:
            events = EvidenceStore.load(args.input).list()
        session_members: dict[str, str] = {}
        transcript_watcher = None
        if args.antigravity_transcript:
            from .transcript_watcher import TranscriptWatcher
            resolved_mem = (args.member_id or "antigravity").strip() or "antigravity"
            session_members["antigravity"] = resolved_mem
            transcript_watcher = TranscriptWatcher(
                args.antigravity_transcript,
                member_id=resolved_mem,
                include_tools=args.antigravity_tools,
                session_members=session_members,
                initial_events=events,
            )
            watch_status = transcript_watcher.sync(project_workspace, events)
            if project_workspace is not None and watch_status.get("new_events_count"):
                project_workspace.save(events)
        intake_status = {"enabled": False}
        def record_direction_candidates():
            from .direction_intake import record_direction_candidates as record
            from .user_task_intake import record_user_task_candidates
            direction=record(events,project_workspace,session_members=session_members)
            tasks=record_user_task_candidates(events,project_workspace,session_members=session_members)
            result = {**direction,**tasks,'updated':direction['updated'] or tasks['updated']}
            if args.extract_docs:
                from .doc_fact_intake import record_document_candidates
                docs = record_document_candidates(events, project_workspace)
                result = {**result, **docs, 'updated': result['updated'] or docs['updated']}
            return result
        refresh_callback = None
        if args.codex_thread:
            native_intake = NativeCodexIntake(args.codex_sessions_root, project_path, args.codex_thread, args.member_id, include_tools=args.codex_tools)
            session_members[args.codex_thread] = args.member_id.strip()
            def refresh_callback():
                status=native_intake.sync(project_workspace, events)
                direction=record_direction_candidates()
                return {**status,**direction,'updated':status.get('updated',False) or direction['updated']}
            intake_status = refresh_callback()
            session_members[args.codex_thread] = args.member_id.strip()
            print(json.dumps({"native_intake": intake_status}, ensure_ascii=False), file=sys.stderr)
        elif transcript_watcher is not None:
            def refresh_callback():
                status = transcript_watcher.sync(project_workspace, events)
                direction = record_direction_candidates()
                return {**status, **direction, 'updated': status.get('updated', False) or direction['updated']}
            intake_status = refresh_callback()
            print(json.dumps({"transcript_watcher": intake_status}, ensure_ascii=False), file=sys.stderr)
        else:
            def refresh_callback():
                return {'enabled':False,**record_direction_candidates()}
            intake_status=refresh_callback()
        if args.extract_codex:
            extractor = CodexExtractor(usage_logger=_log_model_usage, member_id=args.member_id.strip(),
                                       legacy_cache_dir=args.workspace_root / 'extraction-cache', session_members=session_members)
            proposals = extractor.extract(events, project_workspace.state_path.parent / 'extraction-cache')
            if proposals:
                project_workspace.save(proposals)
            events = project_workspace.load()
            extractor.acknowledge(events)
            print(json.dumps({"extraction": extractor.last_result, "proposals": len(proposals)}, ensure_ascii=False), file=sys.stderr)
        def _resolve_derived_context():
            if args.derived_context and project_workspace is not None:
                from .derived_context import DerivedContext
                return DerivedContext.load(args.derived_context, project_id=project_workspace.project_id, project_root=project_path)
            if args.with_code_index and project_workspace is not None:
                from .derived_context import DerivedContext
                from .onboarding import build_and_save_workspace_code_index
                code_payload = build_and_save_workspace_code_index(project_workspace)
                return DerivedContext.from_understand_anything(
                    code_payload,
                    project_id=project_workspace.project_id,
                    project_root=project_path,
                )
            if args.open and project_workspace is not None:
                from .onboarding import load_workspace_derived_context
                return load_workspace_derived_context(project_workspace)
            return None
        if args.web:
            if not (args.scan or args.open or args.sample or args.demo):
                raise ValueError("--web requires --scan, --open, --sample or --demo")
            if project_workspace is None:
                raise ValueError("web mode requires a persisted project workspace")
            confirmed_relations, review_history, fact_reviews = project_workspace.load_review_state()
            if args.demo and not fact_reviews:
                settled_keys = {"project.goal", "arch.storage", "project.next_step"}
                seeded = [
                    {
                        "action": "accept_fact",
                        "fact_id": f.id,
                        "subject_key": f.subject_key,
                        "kind": f.kind.value,
                        "value": f.value,
                        "evidence_ids": list(f.evidence_ids),
                        "source_ref": f.source_ref,
                        "reviewer": "小陈",
                        "observed_at": datetime.now(timezone.utc).isoformat(),
                    }
                    for f in derive_facts(events)
                    if f.subject_key in settled_keys
                ]
                fact_reviews = list(seeded)
                review_history = list(seeded)
            review_callback, confirmed_relations, review_history, fact_reviews = _review_callback(
                events, project_workspace, str(project_path), confirmed_relations, review_history, fact_reviews
            )
            reason_preview=None
            if args.reason_preview:
                from .reason_preview import ReasonPreview
                reason_preview=ReasonPreview.load(args.reason_preview,project_path,events)
            derived_context = _resolve_derived_context()
            rescan_helper = (
                ProjectRescan(project_workspace, events, extract_docs=bool(args.extract_docs))
                if not is_synthetic_sample
                else None
            )
            run_dashboard(
                events,
                project_path=str(project_path),
                port=args.port,
                confirmed_relations=confirmed_relations,
                review_history=review_history,
                fact_reviews=fact_reviews,
                review_callback=review_callback,
                refresh_callback=refresh_callback,
                intake_status=intake_status,
                sample_mode=is_synthetic_sample,
                rescan_callback=rescan_helper.refresh if rescan_helper else None,
                extraction_jobs=ExtractionJobs(project_workspace, events, args.member_id,
                    usage_logger=_log_model_usage, max_batches=args.extraction_max_batches,
                    max_tokens=args.extraction_max_tokens, automatic=args.auto_extract, session_members=session_members) if args.enable_extraction else None,
                agent_inbox=AgentInbox.from_file(args.agent_access_file, project_workspace, events) if args.agent_access_file else None,
                reason_preview=reason_preview,
                workspace_root=None if is_synthetic_sample else args.workspace_root,
                project_scan_job=None if is_synthetic_sample else ProjectScanJob(args.workspace_root),
                derived_context=derived_context,
                auto_doc_sync=(rescan_helper.sync_if_docs_changed if (rescan_helper and args.extract_docs) else None),
                **({"open_browser": True} if (args.demo and not args.no_browser) else {}),
            )
            return 0
        if args.export_format:
            from .dashboard import build_dashboard_state
            from .cognitive_export import export_state_by_format
            derived_context = _resolve_derived_context()
            confirmed, history, accepted = project_workspace.load_review_state() if project_workspace else ([], [], [])
            state = build_dashboard_state(
                events,
                project_path=project_path,
                confirmed_relations=confirmed,
                review_history=history,
                fact_reviews=accepted,
                session_members=session_members,
                derived_context=derived_context,
            )
            body, _, _ = export_state_by_format(state, args.export_format)
            print(body)
            return 0
        if args.evidence_index:
            facts = derive_facts(events)
            index = build_evidence_index(events, facts)
            if project_workspace is not None:
                persisted_relations, _, _ = project_workspace.load_review_state()
                index = index.with_confirmed_relations(persisted_relations)
            print(json.dumps(index.to_dict(), ensure_ascii=False, indent=2))
            return 0
        if args.scan:
            fact_reviews = project_workspace.load_review_state()[2] if project_workspace is not None else []
            accepted_fact_ids = [item["fact_id"] for item in fact_reviews if item.get("action") == "accept_fact"]
            print(json.dumps(build_views(events, accepted_fact_ids=accepted_fact_ids, session_members=session_members), ensure_ascii=False, indent=2))
            return 0
        if args.state:
            store = EvidenceStore(events)
            store.save(args.state)
        print(json.dumps(investigate(events, QUESTION).to_dict(), ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"invalid evidence JSON or state: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
