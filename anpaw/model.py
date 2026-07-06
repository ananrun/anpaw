from __future__ import annotations

"""模型层。

这里保留两种模型：
- RuleModel：本地规则模型，主要作为教学兜底。
- KiloChatModel：OpenAI-compatible 云端模型客户端。

真实 QwenPaw 会有 ProviderManager、多个 Provider 类、模型能力缓存等。
AnPaw 只保留“把消息发到 /chat/completions 并解析模型决策”的最小骨架。
"""

import json
import logging
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Literal

from .config import ModelConfig
from .messages import ToolObservation
from .skills import Skill

logger = logging.getLogger("anpaw.model")


DecisionType = Literal["tool", "final"]


@dataclass
class ModelDecision:
    """模型对下一步动作的决策。

    type == "tool" 表示要调用工具；
    type == "final" 表示可以直接回复用户。
    """

    type: DecisionType
    content: str
    tool_name: str | None = None
    arguments: dict | None = None


class RuleModel:
    """本地规则模型。

    它不是真正的大模型，只用于：
    - 没有云端时演示 agent-loop
    - 让计算/时间/note 这类意图有可预测行为
    """

    def decide(
        self,
        user_text: str,
        skills: dict[str, Skill],
        observations: list[ToolObservation],
    ) -> ModelDecision:
        # 如果已经有工具观察结果，规则模型直接整理成 final。
        if observations:
            lines = [
                f"我已经完成工具调用：{obs.tool_name} -> {obs.result}"
                for obs in observations
            ]
            return ModelDecision(type="final", content="\n".join(lines))

        # 简单识别算式，决定调用 calculator 工具。
        expression = _extract_expression(user_text)
        if expression:
            return ModelDecision(
                type="tool",
                content="需要先用 calculator 得到精确结果。",
                tool_name="calculator",
                arguments={"expression": expression},
            )

        # 简单识别时间意图，决定调用 time 工具。
        if "时间" in user_text or "几点" in user_text:
            return ModelDecision(
                type="tool",
                content="需要调用 time 工具读取当前时间。",
                tool_name="time",
                arguments={},
            )

        # 简单识别记笔记意图，决定调用 note 工具。
        if "记录" in user_text or "note" in user_text:
            return ModelDecision(
                type="tool",
                content="需要把用户内容写入 note。",
                tool_name="note",
                arguments={"text": user_text},
            )

        # 如果命中 Skill，只返回一个学习说明。
        # 真实项目会把 Skill 内容注入模型上下文。
        matched = _match_skill(user_text, skills)
        if matched:
            answer = (
                f"已匹配 skill: {matched.name}\n\n"
                f"Skill 说明：{matched.description}\n\n"
                f"这里会把 SKILL.md 注入上下文，让模型按它的工作流完成任务。"
            )
            return ModelDecision(type="final", content=answer)

        return ModelDecision(
            type="final",
            content=_small_talk_answer(user_text),
        )


class KiloChatModel:
    """OpenAI-compatible 云端模型客户端。

    名字沿用早期实现，实际也支持 OpenCode。
    只要 Provider 暴露 `/chat/completions`，这里就能调用。
    """

    def __init__(self, config: ModelConfig) -> None:
        self.config = config
        self.fallback = RuleModel()

        # 以下字段供 trace 展示，不参与业务逻辑。
        self.last_call: dict = {}
        self.last_raw_response: str = ""
        self.last_error: str = ""

    def decide(
        self,
        user_text: str,
        skills: dict[str, Skill],
        observations: list[ToolObservation],
    ) -> ModelDecision:
        """让云端模型决定下一步是 tool 还是 final。"""
        print(
            f"[Model] 准备让模型决策 provider={self.config.provider} "
            f"model={self.config.model} observations={len(observations)}",
        )
        self.last_call = {}
        self.last_raw_response = ""
        self.last_error = ""
        system = _decision_prompt(skills)

        # observation 是上一轮工具调用结果。
        # 模型需要基于它判断是否已经可以 final。
        obs_text = "\n".join(
            f"- {obs.tool_name}({obs.arguments}) -> {obs.result}"
            for obs in observations
        ) or "(none)"
        content = (
            f"User message:\n{user_text}\n\n"
            f"Tool observations:\n{obs_text}\n\n"
            "Return only one JSON object."
        )

        try:
            raw = self.chat(
                [
                    {"role": "system", "content": system},
                    {"role": "user", "content": content},
                ],
            )
            self.last_raw_response = raw
            # 约定模型返回 JSON，再解析成 ModelDecision。
            print(f"[Model] 模型原始输出预览: {raw[:160]!r}")
            return _parse_decision(raw)
        except Exception as exc:
            # 学习版选择把模型错误转成 final 消息显示给用户。
            # 这样页面不会崩，也能在 trace 里看到错误。
            self.last_error = str(exc)
            logger.warning("model decision failed provider=%s model=%s error=%s", self.config.provider, self.config.model, exc)
            print(f"[Model] 模型调用或解析失败: {exc}")
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
        print(
            f"[ModelHTTP] POST {url} model={self.config.model} "
            f"auth={'with_key' if self.config.api_key else 'no_key'}",
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
            print(f"[ModelHTTP] 请求失败 HTTP {exc.code}: {body[:200]}")
            raise RuntimeError(f"HTTP {exc.code}: {body}") from exc
        content = body["choices"][0]["message"]["content"]
        logger.info("model HTTP response provider=%s model=%s chars=%s", self.config.provider, self.config.model, len(content or ""))
        print(f"[ModelHTTP] 收到响应 chars={len(content or '')}")
        return content


def _extract_expression(text: str) -> str | None:
    """从用户文本里提取简单四则运算表达式。"""
    if not any(word in text for word in ("计算", "算", "+", "-", "*", "/")):
        return None
    matches = re.findall(r"[0-9+\-*/().\s]+", text)
    expression = "".join(matches).strip()
    return expression if any(ch.isdigit() for ch in expression) else None


def _match_skill(text: str, skills: dict[str, Skill]) -> Skill | None:
    """用非常简单的规则匹配 Skill。

    真实 QwenPaw 会把可用 Skill 交给模型，让模型自己决定是否使用。
    """
    lowered = text.lower()
    for skill in skills.values():
        if skill.name.lower() in lowered:
            return skill
    if "写" in text or "文案" in text:
        return skills.get("writer")
    if "算" in text or "数学" in text:
        return skills.get("calculator")
    return None


def _small_talk_answer(text: str) -> str:
    """规则模型的普通回答兜底。"""
    stripped = text.strip()
    lowered = stripped.lower()
    if stripped in {"你好", "您好", "hi", "hello", "哈喽"}:
        return "你好，我在。当前没有检测到云端 API Key，所以先由本地简化模型回答。"
    if "你是谁" in stripped or "介绍一下" in stripped:
        return (
            "我是 AnPaw，一个用来学习 QwenPaw Agent 运行链路的精简实验体。"
            "我会展示消息如何经过 Runner、模型决策、工具调用、观察结果，再生成最终回复。"
        )
    if "普通问题" in stripped or "为什么" in stripped:
        return (
            "刚才普通问题没正常回答，是因为无 API Key 时走的是演示用规则模型，"
            "旧逻辑把未命中工具/skill 的输入都返回成了示例提示。现在这条路径已经改成普通回答。"
        )
    return (
        f"我收到你的问题了：{stripped}\n\n"
        "当前是本地简化模型 fallback，只能做基础回答和路由演示。"
        "填入云端 API Key 后，这类普通问题会交给你选择的模型生成。"
    )


def _decision_prompt(skills: dict[str, Skill]) -> str:
    """构造给云端模型的系统提示词。

    这里强制要求模型返回 JSON，方便学习 agent-loop 的状态转换。
    """
    skill_lines = "\n".join(
        f"- {skill.name}: {skill.description}" for skill in skills.values()
    )
    return (
        "You are the model inside a tiny teaching agent runtime.\n"
        "Choose either a tool call or a final answer.\n\n"
        "Available tools:\n"
        "- calculator: arithmetic expression, args {\"expression\": \"...\"}\n"
        "- time: current local time, args {}\n"
        "- note: append note, args {\"text\": \"...\"}\n\n"
        f"Available skills:\n{skill_lines or '(none)'}\n\n"
        "Return strict JSON only, no markdown. Shapes:\n"
        "{\"type\":\"tool\",\"content\":\"why\","
        "\"tool_name\":\"calculator\",\"arguments\":{\"expression\":\"2+2\"}}\n"
        "{\"type\":\"final\",\"content\":\"answer\"}\n\n"
        "If tool observations are present, usually return final. "
        "If the user asks arithmetic, time, or note-taking, call the matching "
        "tool first. If a skill is relevant, mention the matched skill in final."
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
    if kind == "tool":
        return ModelDecision(
            type="tool",
            content=str(data.get("content") or ""),
            tool_name=str(data.get("tool_name") or ""),
            arguments=dict(data.get("arguments") or {}),
        )
    return ModelDecision(type="final", content=str(data.get("content") or raw))
