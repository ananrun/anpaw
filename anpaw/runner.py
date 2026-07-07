from __future__ import annotations

"""AgentRunner：一次用户请求的编排层。

Runner 不直接“思考”，也不直接调用工具。
它负责把一次请求整理成 Agent 可以执行的形式：
- 判断是否是内置命令
- 写入会话记忆，供 `/history` 查看和 JSON 持久化
- 构造环境上下文
- 解析 provider/model 配置
- 创建 SimpleAgent 并启动 agent-loop
"""

import logging
from uuid import uuid4

from .agent import AgentContext, SimpleAgent
from .config import load_model_config
from .console import flow
from .memory import Memory
from .messages import AssistantMessage, TraceEvent, UserMessage
from .model import KiloChatModel
from .skills import Skill
from .tools import ToolRegistry

logger = logging.getLogger("anpaw.runner")


class AgentRunner:
    """单个 Workspace 内的请求编排器。"""

    def __init__(
        self,
        agent_id: str,
        memory: Memory,
        tools: ToolRegistry,
        skills: dict[str, Skill],
    ) -> None:
        self.agent_id = agent_id
        self.memory = memory
        self.tools = tools
        self.skills = skills
        # 为了学习清晰，session_id 在 Runner 创建时生成。
        # 真实项目通常会从请求/会话系统里读取。
        self.session_id = uuid4().hex

    def run(
        self,
        message: UserMessage,
        api_key: str = "",
        provider_id: str = "",
        model: str = "",
        initial_trace: list[TraceEvent] | None = None,
    ) -> AssistantMessage:
        """运行一次用户消息。

        这是 AnPaw 的请求主线：
        command path 或 normal agent-loop path 二选一。
        """
        flow(
            "Runner",
            "开始编排本轮消息",
            session=self.session_id,
            text=message.text[:60],
            memory_messages=len(self.memory.messages),
        )
        trace: list[TraceEvent] = list(initial_trace or [])
        trace.append(
            TraceEvent(
                stage="runner",
                detail="received user message",
                data={
                    "agent_id": self.agent_id,
                    "session_id": self.session_id,
                    "message_preview": message.text[:120],
                    "memory_messages_before": len(self.memory.messages),
                },
            ),
        )
        # 先检查 `/skills`、`/history` 这类控制命令。
        # 命令不需要进入模型，也不会触发工具循环。
        trace.append(
            TraceEvent(
                stage="runner",
                detail="check built-in slash commands",
                data={
                    "supported": ["/clear", "/history", "/tools", "/skills"],
                    "is_command": message.text.strip().startswith("/"),
                },
            ),
        )
        command_response = self._try_command(message.text)
        if command_response:
            flow("Runner", "命中内置命令，跳过模型和工具循环", command=message.text.strip())
            logger.info("handled command agent=%s command=%s", self.agent_id, message.text.strip())
            command_response.metadata["trace"] = _trace_dicts(
                trace
                + [
                    TraceEvent(
                        stage="runner",
                        detail="handled as command",
                        data={"command": message.text.strip()},
                    ),
                ],
            )
            self.memory.add(message)
            self.memory.add(command_response)
            return command_response

        # 普通用户消息进入会话记忆。
        # 这份记忆会持久化到 session.json，并可通过 /history 查看；
        # 当前学习版还没有把历史消息检索后注入模型上下文。
        self.memory.add(message)
        flow("Memory", "用户消息已写入会话记忆", count=len(self.memory.messages))
        trace.append(
            TraceEvent(
                stage="memory",
                detail="stored user message in session memory",
                data={"memory_messages_after_user": len(self.memory.messages)},
            ),
        )

        # env_context 是给 Agent/模型看的运行环境摘要。
        # 它让模型知道当前 agent、session、可用 tools/skills。
        # 注意这里没有包含历史 Memory 内容。
        env = self._build_env_context()
        flow("Runner", "已构造 env_context，准备解析模型配置")
        trace.append(
            TraceEvent(
                stage="runner",
                detail="build environment context",
                data={
                    "env": env,
                    "tools": self.tools.names(),
                    "skills": list(self.skills),
                },
            ),
        )

        # 页面传入的 provider/model/key 会和环境变量/.env 合并。
        # 这里得到一次运行最终使用的 ModelConfig。
        model_config = load_model_config(
            api_key=api_key,
            provider_id=provider_id,
            model=model,
        )
        flow(
            "Provider",
            "模型配置解析完成",
            provider=model_config.provider,
            model=model_config.model,
            auth="with_key" if model_config.api_key else "no_key",
        )
        trace.append(
            TraceEvent(
                stage="provider",
                detail="resolve provider and model config",
                data={
                    "model": model_config.model,
                    "base_url": model_config.base_url,
                    "provider": model_config.provider,
                    "model_source": (
                        "cloud_with_key"
                        if model_config.api_key
                        else "cloud_free_no_key"
                    ),
                    "has_api_key": bool(model_config.api_key),
                },
            ),
        )
        logger.info(
            "runner invoking agent agent=%s provider=%s model=%s auth=%s",
            self.agent_id,
            model_config.provider,
            model_config.model,
            "with_key" if model_config.api_key else "no_key",
        )

        # Runner 到这里才真正创建 Agent。
        # 这样每次请求都能使用最新的模型选择、工具和技能配置。
        agent = SimpleAgent(
            context=AgentContext(
                agent_id=self.agent_id,
                session_id=self.session_id,
                env=env,
            ),
            model=KiloChatModel(model_config),
            tools=self.tools,
            skills=self.skills,
            trace=trace,
        )
        flow("Runner", "SimpleAgent 已创建，进入 agent-loop")
        response = agent.run(message)

        # 最终回复也进入记忆，形成一轮完整对话，并同步保存到 JSON。
        self.memory.add(response)
        flow("Memory", "助手回复已写入会话记忆", count=len(self.memory.messages))
        trace.append(
            TraceEvent(
                stage="memory",
                detail="stored assistant response in session memory",
                data={"memory_messages_after_assistant": len(self.memory.messages)},
            ),
        )
        response.metadata["trace"] = _trace_dicts(trace)
        return response

    def _try_command(self, text: str) -> AssistantMessage | None:
        """处理学习版内置命令。

        返回 None 表示不是命令，应该继续进入模型。
        """
        stripped = text.strip()
        if stripped == "/clear":
            self.memory.clear()
            return AssistantMessage(text="会话记忆已清空。")
        if stripped == "/history":
            return AssistantMessage(text=self.memory.render())
        if stripped == "/tools":
            return AssistantMessage(text=self.tools.describe())
        if stripped == "/skills":
            if not self.skills:
                return AssistantMessage(text="当前没有加载 skill。")
            lines = [
                f"- {skill.name}: {skill.description}"
                for skill in self.skills.values()
            ]
            return AssistantMessage(text="\n".join(lines))
        return None

    def _build_env_context(self) -> str:
        """构造简化版环境上下文。

        真实 QwenPaw 的 env context 会更丰富：
        工作目录、用户、频道、shell、Coding Mode 项目目录等。
        """
        return (
            f"agent_id={self.agent_id}\n"
            f"session_id={self.session_id}\n"
            f"loaded_skills={list(self.skills)}\n"
            f"tools={self.tools.names()}"
        )


def _trace_dicts(trace: list[TraceEvent]) -> list[dict]:
    return [
        {"stage": event.stage, "detail": event.detail, "data": event.data}
        for event in trace
    ]
