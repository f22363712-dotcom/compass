from datetime import datetime, timezone

from .models import EvidenceEvent


def sample_events() -> list[EvidenceEvent]:
    timestamp = datetime(2026, 10, 23, 8, 0, tzinfo=timezone.utc)
    return [
        EvidenceEvent(
            "e1",
            "session-a",
            "dev-a",
            "agent_message",
            "明确项目目标与存储选型：交付本地协作证据看板黄金路径，并围绕只读摘要、结构化待办与联调状态持续推进。",
            timestamp,
            {
                "synthetic": True,
                "source_ref": "docs/sample-session-a.md",
                "facts": [
                    {"kind": "goal", "subject_key": "project.goal", "value": "交付证据看板黄金路径"},
                    {"kind": "decision", "subject_key": "arch.storage", "value": "采用本地追加式 JSON 状态存储与显式负责人裁决机制"},
                    {"kind": "task", "subject_key": "task.golden-path", "value": "完成本地看板数据接通与端到端联调", "status": "active"},
                ],
            },
        ),
        EvidenceEvent(
            "e2",
            "session-b",
            "dev-b",
            "agent_message",
            "报告任务阻塞现状与前提提醒：联调分支因契约字段尚未对齐暂时阻塞；当前工作区为离线合成演示样例，不代表真实项目验收。",
            timestamp,
            {
                "synthetic": True,
                "source_ref": "docs/sample-session-b.md",
                "facts": [
                    {"kind": "task", "subject_key": "task.golden-path", "value": "完成本地看板数据接通与端到端联调", "status": "blocked"},
                    {"kind": "assumption", "subject_key": "assumption.sample", "value": "当前演示使用离线合成样例，不代表真实项目验收或外部服务已连接"},
                ],
            },
        ),
    ]
