from __future__ import annotations

"""消息和 Trace 数据结构。

这些 dataclass 是整个学习项目里各层传递数据的“共同语言”。
真实 QwenPaw/AgentScope 的消息结构会更复杂，支持多模态、工具块、元数据等。
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class Message:
    """基础消息。"""

    text: str
    role: str
    metadata: dict = field(default_factory=dict)
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
    )


@dataclass
class UserMessage(Message):
    """用户消息。"""

    role: str = "user"


@dataclass
class AssistantMessage(Message):
    """助手消息。"""

    role: str = "assistant"


@dataclass
class ToolObservation:
    """工具执行后的观察结果。

    Agent 会把它送回模型，让模型基于工具结果继续推理。
    """

    tool_name: str
    arguments: dict
    result: str


@dataclass
class TraceEvent:
    """页面右侧“运行链路”的一个事件。"""

    stage: str
    detail: str
    data: dict = field(default_factory=dict)
