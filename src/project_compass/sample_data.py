from datetime import datetime, timedelta, timezone

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
                    {"kind": "decision", "subject_key": "arch.storage", "value": "采用本地追加式 JSON 状态存储与显式负责人确认机制"},
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


def showcase_sample_events() -> list[EvidenceEvent]:
    """Return a jargon-free Chinese showcase project for 30-second first-time demos (--demo)."""
    base = datetime(2026, 11, 20, 9, 0, tzinfo=timezone.utc)
    return [
        EvidenceEvent(
            "demo-e1",
            "session-podcast",
            "小陈",
            "user_message",
            "项目目标：做一个个人播客笔记与剪藏小工具，自动把播客长音频转成带时间戳的金句卡片，本地离线可搜索。",
            base,
            {
                "synthetic": True,
                "demo_title": "个人播客笔记与剪藏小工具",
                "source_ref": "chat://podcast-demo/1",
                "facts": [
                    {
                        "kind": "goal",
                        "subject_key": "project.goal",
                        "value": "自动把播客长音频转成带时间戳的金句卡片，本地离线可搜索",
                        "short_title": "播客长音频转离线金句卡片",
                    },
                ],
            },
        ),
        EvidenceEvent(
            "demo-e2",
            "session-podcast",
            "小陈",
            "user_message",
            "方案选型：本地用 SQLite 保存音频索引与时间戳笔记，离线也能秒查原文上下文。",
            base + timedelta(minutes=8),
            {
                "synthetic": True,
                "source_ref": "chat://podcast-demo/2",
                "facts": [
                    {
                        "kind": "decision",
                        "subject_key": "arch.storage",
                        "value": "本地用 SQLite 保存音频索引与时间戳笔记，方便离线全文检索",
                        "short_title": "本地 SQLite 存索引与时间轴",
                    },
                ],
            },
        ),
        EvidenceEvent(
            "demo-e3",
            "session-podcast",
            "小陈",
            "assistant_message",
            "语音转写方案有两种备选需要对比选型：方案 A 用本地 Whisper.cpp 离线运行，方案 B 调用免费云端 API（留待确认选择哪条）。",
            base + timedelta(minutes=15),
            {
                "synthetic": True,
                "member_id": "小陈",
                "source_ref": "chat://podcast-demo/3",
                "facts": [
                    {
                        "kind": "decision",
                        "subject_key": "arch.asr",
                        "value": "语音转写备选：本地 Whisper.cpp vs 免费云端 API",
                        "short_title": "对比：本地 Whisper vs 云端 API",
                    },
                ],
            },
        ),
        EvidenceEvent(
            "demo-e4",
            "session-podcast",
            "小陈",
            "user_message",
            "前提条件假设：60 分钟单集播客音频在普通轻薄本上 3 分钟内能完成本地转写，目前尚未实测验证。",
            base + timedelta(minutes=22),
            {
                "synthetic": True,
                "source_ref": "chat://podcast-demo/4",
                "facts": [
                    {
                        "kind": "assumption",
                        "subject_key": "premise.asr_speed",
                        "value": "假设 60 分钟单集音频在轻薄本 3 分钟内转完（待实测）",
                        "short_title": "假设：60 分钟音频 3 分钟转完",
                    },
                ],
            },
        ),
        EvidenceEvent(
            "demo-e5",
            "session-podcast",
            "小陈",
            "user_message",
            "已排除把音频同步到第三方网盘，因为外链容易失效且有隐私顾虑，明确不采用网盘方案。",
            base + timedelta(minutes=30),
            {
                "synthetic": True,
                "source_ref": "chat://podcast-demo/5",
                "facts": [
                    {
                        "kind": "decision",
                        "subject_key": "arch.cloud_drive",
                        "value": "已排除把音频同步到第三方网盘，因为外链容易失效且有隐私顾虑",
                        "short_title": "已排除：第三方网盘同步",
                    },
                ],
            },
        ),
        EvidenceEvent(
            "demo-e6",
            "session-podcast",
            "小陈",
            "user_message",
            "当前下一步：先做小宇宙单集链接解析，并跑通 3 分钟试听切片与金句提取验证。",
            base + timedelta(minutes=40),
            {
                "synthetic": True,
                "source_ref": "chat://podcast-demo/6",
                "facts": [
                    {
                        "kind": "task",
                        "subject_key": "project.next_step",
                        "value": "先做小宇宙单集链接解析与 3 分钟试听切片验证",
                        "short_title": "小宇宙链接解析与 3 分钟验证",
                        "status": "active",
                    },
                ],
            },
        ),
        EvidenceEvent(
            "demo-e7",
            "session-podcast",
            "小陈",
            "file_change",
            "已新建单集链接与 RSS 节目元信息解析模块 src/podcast_clipper/rss_parser.py。",
            base + timedelta(minutes=46),
            {
                "synthetic": True,
                "member_id": "小陈",
                "source_ref": "src/podcast_clipper/rss_parser.py",
                "files": ["src/podcast_clipper/rss_parser.py"],
            },
        ),
        EvidenceEvent(
            "demo-e8",
            "session-podcast",
            "小陈",
            "test_result",
            "3 passed in 0.42s — 小宇宙单集标题、时长与音频流解析基础测试通过",
            base + timedelta(minutes=48),
            {
                "synthetic": True,
                "member_id": "小陈",
                "source_ref": "tests/test_rss_parser.py",
                "exit_code": 0,
            },
        ),
    ]
