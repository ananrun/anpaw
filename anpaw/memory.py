from __future__ import annotations

"""学习版会话记忆。

这里故意只做内存列表，方便看懂。
真实 QwenPaw 会有会话文件、上下文压缩、长期记忆等机制。
"""

from dataclasses import dataclass, field

from .messages import Message


@dataclass
class Memory:
    """保存当前 Workspace 中的最近消息。"""

    messages: list[Message] = field(default_factory=list)

    def add(self, message: Message) -> None:
        """追加一条消息。"""
        self.messages.append(message)

    def clear(self) -> None:
        """清空会话记忆。"""
        self.messages.clear()

    def render(self, limit: int = 8) -> str:
        """把最近消息渲染给 `/history` 命令查看。"""
        recent = self.messages[-limit:]
        if not recent:
            return "(empty)"
        return "\n".join(f"{msg.role}: {msg.text}" for msg in recent)
