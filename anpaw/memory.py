from __future__ import annotations

"""学习版会话记忆。

这里用内存列表承载当前运行态，并同步到 Workspace 下的 JSON 文件。
真实 QwenPaw 会有会话文件、上下文压缩、向量检索、长期记忆等机制。
AnPaw 保留一个很小的关键词检索入口，供 agent-loop 通过工具主动查询。
"""

import json
import re
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

    def search(self, query: str, max_results: int = 3) -> str:
        """按关键词检索当前 Workspace 的会话记忆。

        这是教学版的轻量实现：不做向量化，只用文本包含和 token 重叠打分。
        它被注册成 `memory_search` 工具，让模型像 QwenPaw 一样通过工具结果
        获得记忆，而不是让 Runner 把历史消息硬塞进每次 prompt。
        """
        query = query.strip()
        max_results = max(1, min(int(max_results or 3), 8))
        if not query or not self.messages:
            return "未找到相关记忆。"

        query_terms = _terms(query)
        ranked: list[tuple[int, Message]] = []
        for message in self.messages:
            text = message.text.strip()
            if not text or text == query:
                continue
            haystack = text.lower()
            score = 0
            if query.lower() in haystack:
                score += 6
            score += len(query_terms & _terms(text))
            if score:
                ranked.append((score, message))

        ranked.sort(key=lambda item: (item[0], item[1].created_at), reverse=True)
        if not ranked:
            return "未找到相关记忆。"

        lines = []
        for _, message in ranked[:max_results]:
            snippet = message.text.replace("\n", " ").strip()
            if len(snippet) > 180:
                snippet = snippet[:177] + "..."
            lines.append(f"- {message.role} @ {message.created_at}: {snippet}")
        return "\n".join(lines)


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


def _terms(text: str) -> set[str]:
    """提取中英文混合文本的粗粒度关键词。"""
    lowered = text.lower()
    words = set(re.findall(r"[a-z0-9_]{2,}", lowered))
    chinese_terms: set[str] = set()
    for chunk in re.findall(r"[\u4e00-\u9fff]+", lowered):
        chinese_terms.update(chunk)
        if len(chunk) == 1:
            chinese_terms.add(chunk)
        else:
            chinese_terms.update(chunk[index : index + 2] for index in range(len(chunk) - 1))
    return words | chinese_terms
