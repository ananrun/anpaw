from __future__ import annotations

"""学习版会话记忆。

这里用内存列表承载当前运行态，并可选同步到 Workspace 下的 JSON 文件。
真实 QwenPaw 会有会话文件、上下文压缩、长期记忆等机制。
"""

import json
from dataclasses import dataclass, field
from pathlib import Path

from .console import flow
from .messages import AssistantMessage, Message, UserMessage


@dataclass
class Memory:
    """保存当前 Workspace 中的最近消息。"""

    messages: list[Message] = field(default_factory=list)
    path: Path | None = None

    def load(self) -> None:
        """从 JSON 文件加载会话记忆。"""
        if self.path is None or not self.path.exists():
            return
        data = json.loads(self.path.read_text(encoding="utf-8"))
        self.messages = [_message_from_dict(item) for item in data.get("messages", [])]
        flow("Memory", "已从 JSON 加载会话记忆", path=self.path, count=len(self.messages))

    def add(self, message: Message) -> None:
        """追加一条消息。"""
        self.messages.append(message)
        self.save()

    def clear(self) -> None:
        """清空会话记忆。"""
        self.messages.clear()
        self.save()

    def save(self) -> None:
        """把当前会话记忆保存成 JSON。"""
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "messages": [_message_to_dict(message) for message in self.messages],
        }
        self.path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def render(self, limit: int = 8) -> str:
        """把最近消息渲染给 `/history` 命令查看。"""
        recent = self.messages[-limit:]
        if not recent:
            return "(empty)"
        return "\n".join(f"{msg.role}: {msg.text}" for msg in recent)


def _message_to_dict(message: Message) -> dict:
    """转成适合持久化的干净 JSON。"""
    metadata = dict(message.metadata)
    metadata.pop("trace", None)
    return {
        "role": message.role,
        "text": message.text,
        "metadata": metadata,
        "created_at": message.created_at,
    }


def _message_from_dict(data: dict) -> Message:
    """从 JSON 恢复消息对象。"""
    role = str(data.get("role") or "assistant")
    cls = UserMessage if role == "user" else AssistantMessage
    return cls(
        text=str(data.get("text") or ""),
        metadata=dict(data.get("metadata") or {}),
        created_at=str(data.get("created_at") or ""),
    )
