from __future__ import annotations

"""SimpleAgent：最小可读的 Agent Loop。

真实 QwenPaw 使用 AgentScope ReActAgent。
AnPaw 用这个小类展示同一个核心思想：

reason -> act -> observe -> reason -> final

模型先决定是否调用工具；
工具结果作为 observation 再喂回模型；
直到模型返回 final 或达到最大轮数。
"""

import logging
from dataclasses import dataclass

from .console import flow
from .messages import AssistantMessage, ToolObservation, TraceEvent, UserMessage
from .model import KiloChatModel, RuleModel
from .skills import Skill
from .tools import ToolRegistry

logger = logging.getLogger("anpaw.agent")


@dataclass
class AgentContext:
    """一次 Agent 运行时需要知道的上下文。"""

    agent_id: str
    session_id: str
    env: str


class SimpleAgent:
    """学习版 Agent 执行核心。"""

    def __init__(
        self,
        context: AgentContext,
        model: ModelLike,
        tools: ToolRegistry,
        skills: dict[str, Skill],
        max_iters: int = 4,
        trace: list[TraceEvent] | None = None,
    ) -> None:
        self.context = context
        self.model = model
        self.tools = tools
        self.skills = skills
        self.max_iters = max_iters
        self.trace = trace if trace is not None else []

    def run(self, message: UserMessage) -> AssistantMessage:
        """执行 agent-loop。

        observations 保存每次工具调用的返回值。
        每一轮模型都会看到当前用户消息和已有 observations。
        """
        flow(
            "Agent",
            "初始化运行时",
            max_iters=self.max_iters,
            tools=self.tools.names(),
            skills=list(self.skills),
        )
        observations: list[ToolObservation] = []
        self.trace.append(
            TraceEvent(
                stage="agent",
                detail="initialize SimpleAgent runtime",
                data={
                    "agent_id": self.context.agent_id,
                    "session_id": self.context.session_id,
                    "max_iters": self.max_iters,
                    "tools": self.tools.names(),
                    "skills": list(self.skills),
                },
            ),
        )

        for step in range(1, self.max_iters + 1):
            # 1. Reason：询问模型下一步做什么。
            flow("Agent", "Reason: 询问模型下一步动作", step=step, observations=len(observations))
            logger.info("agent loop step=%s observations=%s", step, len(observations))
            self.trace.append(
                TraceEvent(
                    stage="agent-loop",
                    detail=f"step {step}: ask model to decide",
                    data={"observations": len(observations)},
                ),
            )
            decision = self.model.decide(
                user_text=message.text,
                skills=self.skills,
                observations=observations,
            )
            flow(
                "Agent",
                "模型返回决策",
                step=step,
                type=decision.type,
                tool=decision.tool_name,
                content=decision.content[:80],
            )

            # 记录模型 HTTP 调用细节，便于在页面右侧学习模型层行为。
            call_info = getattr(self.model, "last_call", None)
            if call_info:
                self.trace.append(
                    TraceEvent(
                        stage="model-http",
                        detail="cloud chat completion request",
                        data=call_info,
                    ),
                )
            raw_preview = getattr(self.model, "last_raw_response", "")
            if raw_preview:
                self.trace.append(
                    TraceEvent(
                        stage="model-http",
                        detail="raw model response preview",
                        data={"raw_preview": raw_preview[:500]},
                    ),
                )
            model_error = getattr(self.model, "last_error", "")
            if model_error:
                self.trace.append(
                    TraceEvent(
                        stage="model-http",
                        detail="model call or JSON parsing failed",
                        data={"error": model_error[:800]},
                    ),
                )
            self.trace.append(
                TraceEvent(
                    stage="model",
                    detail=f"decision: {decision.type}",
                    data={
                        "content": decision.content,
                        "tool_name": decision.tool_name,
                        "arguments": decision.arguments or {},
                    },
                ),
            )

            if decision.type == "final":
                # 2a. Final：模型认为任务完成，直接返回给用户。
                flow("Agent", "Final: 模型认为可以直接回复，结束循环", step=step)
                logger.info("agent final step=%s", step)
                self.trace.append(
                    TraceEvent(
                        stage="final",
                        detail="return final assistant message",
                        data={
                            "step": step,
                            "answer_preview": decision.content[:300],
                        },
                    ),
                )
                return AssistantMessage(
                    text=f"[step {step}] {decision.content}",
                    metadata={"steps": step, "trace": _trace_dicts(self.trace)},
                )

            assert decision.tool_name is not None
            assert decision.arguments is not None
            # 2b. Act：模型选择了工具，Agent 负责真正执行工具。
            flow(
                "Agent",
                "Act: 调用工具",
                step=step,
                tool=decision.tool_name,
                arguments=decision.arguments,
            )
            logger.info("agent tool call name=%s args=%s", decision.tool_name, decision.arguments)
            self.trace.append(
                TraceEvent(
                    stage="tool",
                    detail=f"run {decision.tool_name}",
                    data={"arguments": decision.arguments},
                ),
            )
            result = self.tools.run(decision.tool_name, decision.arguments)

            # 3. Observe：工具执行结果不会直接当最终答案，
            # 而是作为 observation 交给下一轮模型继续推理。
            observations.append(
                ToolObservation(
                    tool_name=decision.tool_name,
                    arguments=decision.arguments,
                    result=result,
                ),
            )
            flow("Agent", "Observe: 工具结果将交给下一轮模型", step=step, result=result[:120])
            self.trace.append(
                TraceEvent(
                    stage="observation",
                    detail=f"{decision.tool_name} returned",
                    data={
                        "result": result,
                        "will_send_back_to_model": True,
                    },
                ),
            )

        # 达到最大轮数仍未 final 时，停止本轮，避免无限循环。
        flow("Agent", "达到最大轮数，停止本轮", max_iters=self.max_iters)
        return AssistantMessage(
            text="达到最大循环次数，任务被停止。",
            metadata={
                "steps": self.max_iters,
                "stopped": True,
                "trace": _trace_dicts(self.trace),
            },
        )


ModelLike = RuleModel | KiloChatModel


def _trace_dicts(trace: list[TraceEvent]) -> list[dict]:
    return [
        {"stage": event.stage, "detail": event.detail, "data": event.data}
        for event in trace
    ]
