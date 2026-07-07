from __future__ import annotations

"""模型层。

这里保留一个 OpenAI-compatible 云端模型客户端。

真实 QwenPaw 会有 ProviderManager、多个 Provider 类、模型能力缓存等。
AnPaw 只保留“把消息发到 /chat/completions，并把模型输出解析成
tool_use/final 决策”的最小骨架。
"""

import json
import logging
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Literal

from .config import ModelConfig
from .console import flow
from .messages import ToolObservation
from .skills import Skill

logger = logging.getLogger("anpaw.model")


DecisionType = Literal["tool_use", "final"]


@dataclass
class ModelDecision:
    """模型对下一步动作的决策。

    type == "tool_use" 表示要调用工具；
    type == "final" 表示可以直接回复用户。
    """

    type: DecisionType
    content: str
    tool_name: str | None = None
    arguments: dict | None = None
    matched_skills: list[str] | None = None


class KiloChatModel:
    """OpenAI-compatible 云端模型客户端。

    名字沿用早期实现，实际也支持 OpenCode。
    只要 Provider 暴露 `/chat/completions`，这里就能调用。
    """

    def __init__(self, config: ModelConfig) -> None:
        self.config = config

        # 以下字段供 trace 展示，不参与业务逻辑。
        self.last_call: dict = {}
        self.last_raw_response: str = ""
        self.last_error: str = ""

    def decide(
        self,
        user_text: str,
        skills: dict[str, Skill],
        skill_matches: list[dict] | None,
        observations: list[ToolObservation],
    ) -> ModelDecision:
        """让云端模型决定下一步是 tool_use 还是 final。"""
        flow(
            "Model",
            "准备让模型决策",
            provider=self.config.provider,
            model=self.config.model,
            tool_results=len(observations),
        )
        self.last_call = {}
        self.last_raw_response = ""
        self.last_error = ""
        system = _decision_prompt(skills)

        # observation 是本轮 agent-loop 里的 tool_result。
        # 历史 Memory 不会被 Runner 全量塞进 prompt；模型需要时可以主动
        # 调用 memory_search 工具，再从 tool_result 中获得相关记忆。
        obs_text = "\n".join(
            f"- tool_result {obs.tool_name}({obs.arguments}) -> {obs.result}"
            for obs in observations
        ) or "无"
        skill_match_text = "\n".join(
            "- {name}: score={score}, matched_terms={terms}, description={description}".format(
                name=item.get("name"),
                score=item.get("score"),
                terms=item.get("matched_terms"),
                description=item.get("description"),
            )
            for item in (skill_matches or [])
        ) or "无"
        content = (
            f"用户消息：\n{user_text}\n\n"
            f"本地 Skill 候选（只作参考，最终是否使用由你决定）：\n{skill_match_text}\n\n"
            f"本轮已有 tool_result：\n{obs_text}\n\n"
            "只返回一个 JSON 对象。"
        )

        try:
            raw = self.chat(
                [
                    {"role": "system", "content": system},
                    {"role": "user", "content": content},
                ],
            )
            self.last_raw_response = raw
            # 约定云端模型返回 JSON，再解析成 ModelDecision。
            flow("Model", "模型原始输出预览", raw=raw[:160])
            return _parse_decision(raw)
        except Exception as exc:
            # 学习版选择把模型错误转成 final 消息显示给用户，
            # 这样页面不会崩，也能在 trace 里看到错误。
            self.last_error = str(exc)
            logger.warning("model decision failed provider=%s model=%s error=%s", self.config.provider, self.config.model, exc)
            flow("Model", "模型调用或解析失败", error=str(exc))
            return ModelDecision(
                type="final",
                content=(
                    "云端模型调用失败，已停止本轮。\n\n"
                    f"错误：{exc}\n\n"
                    "这些免费 Provider 通常无需 Key，但可能会遇到公共池限流。"
                    "你可以稍后重试、换一个模型，或在页面右上角填写自己的 Key。"
                ),
            )

    def chat(self, messages: list[dict], temperature: float = 0.2) -> str:
        """调用 OpenAI-compatible `/chat/completions`。"""
        url = f"{self.config.base_url}/chat/completions"
        flow(
            "ModelHTTP",
            "发送 chat/completions 请求",
            url=url,
            model=self.config.model,
            auth="with_key" if self.config.api_key else "no_key",
            messages=len(messages),
        )
        payload = {
            "model": self.config.model,
            "messages": messages,
            "temperature": temperature,
        }
        data = json.dumps(payload).encode("utf-8")
        headers = {
            "content-type": "application/json",
            "accept": "application/json",
            "user-agent": "AnPaw-Learning/1.0",
        }
        # 免费 Provider 通常允许不带 Key。
        # 如果用户填了 Key，则带 Bearer 头使用自己的额度。
        if self.config.api_key:
            headers["authorization"] = f"Bearer {self.config.api_key}"
        self.last_call = {
            "provider": self.config.provider,
            "model": self.config.model,
            "url": url,
            "auth": "with_key" if self.config.api_key else "no_key",
            "messages": len(messages),
            "temperature": temperature,
            "request_bytes": len(data),
        }
        logger.info(
            "model HTTP request provider=%s model=%s auth=%s messages=%s",
            self.config.provider,
            self.config.model,
            self.last_call["auth"],
            len(messages),
        )
        request = urllib.request.Request(
            url,
            data=data,
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            logger.warning("model HTTP error status=%s body=%s", exc.code, body[:500])
            flow("ModelHTTP", "请求失败", status=exc.code, body=body[:200])
            raise RuntimeError(f"HTTP {exc.code}: {body}") from exc
        content = body["choices"][0]["message"]["content"]
        logger.info("model HTTP response provider=%s model=%s chars=%s", self.config.provider, self.config.model, len(content or ""))
        flow("ModelHTTP", "收到模型响应", chars=len(content or ""))
        return content


def _decision_prompt(skills: dict[str, Skill]) -> str:
    """构造给云端模型的系统提示词。

    这里列出可用工具和 Skill 摘要，并强制要求模型返回 JSON。
    是否匹配工具、Skill、Memory，都是云端模型基于提示词决定。
    Memory 通过 memory_search 工具进入 agent-loop，而不是由 Runner
    自动注入整段历史。
    """
    skill_lines = "\n".join(
        f"- {skill.name}: {skill.description}" for skill in skills.values()
    )
    return (
        "你是一个教学版 Agent Runtime 里的模型决策器。\n"
        "你只能在两种动作中选择一种：调用工具，或给出最终回答。\n\n"
        "可用工具：\n"
        "- calculator：计算算术表达式，参数 {\"expression\": \"...\"}\n"
        "- time：获取当前本地时间，参数 {}\n"
        "- memory_search：检索当前 agent 的会话记忆，参数 {\"query\": \"...\", \"max_results\": 3}\n"
        "- note：追加笔记，参数 {\"text\": \"...\"}\n\n"
        f"可用 Skills：\n{skill_lines or '无'}\n\n"
        "只返回严格 JSON，不要返回 markdown。格式如下：\n"
        "{\"type\":\"tool_use\",\"content\":\"为什么调用这个工具\","
        "\"name\":\"calculator\",\"input\":{\"expression\":\"2+2\"},"
        "\"matched_skills\":[\"calculator\"]}\n"
        "{\"type\":\"final\",\"content\":\"answer\",\"matched_skills\":[\"writer\"]}\n\n"
        "决策规则：\n"
        "1. 如果用户问题需要历史上下文，先调用 memory_search。\n"
        "2. 如果用户请求计算、时间或记笔记，优先调用对应工具。\n"
        "3. 如果某个 Skill 与任务相关，把 Skill 名称写入 matched_skills。\n"
        "4. 如果本轮已有足够的 tool_result，通常返回 final。\n"
        "5. 不要编造工具结果；需要工具结果时必须先返回 tool_use。"
    )


def _parse_decision(raw: str) -> ModelDecision:
    """把模型返回的 JSON 文本解析成 ModelDecision。"""
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?|```$", "", cleaned, flags=re.I).strip()
    if not cleaned.startswith("{"):
        match = re.search(r"\{.*\}", cleaned, flags=re.S)
        if match:
            cleaned = match.group(0)
    data = json.loads(cleaned)
    kind = data.get("type")
    if kind in {"tool_use", "tool"}:
        tool_name = data.get("name") or data.get("tool_name") or ""
        arguments = data.get("input")
        if arguments is None:
            arguments = data.get("arguments")
        return ModelDecision(
            type="tool_use",
            content=str(data.get("content") or ""),
            tool_name=str(tool_name),
            arguments=dict(arguments or {}),
            matched_skills=_parse_matched_skills(data),
        )
    return ModelDecision(
        type="final",
        content=str(data.get("content") or raw),
        matched_skills=_parse_matched_skills(data),
    )


def _parse_matched_skills(data: dict) -> list[str]:
    """兼容模型可能返回的 skills/matched_skills 字段。"""
    raw = data.get("matched_skills")
    if raw is None:
        raw = data.get("skills")
    if isinstance(raw, str):
        return [raw]
    if isinstance(raw, list):
        return [str(item) for item in raw if str(item).strip()]
    return []
