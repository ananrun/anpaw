from __future__ import annotations

"""单 Agent 工作区。

Workspace 是 Agent 的“运行容器”。它把记忆、工具、技能和 Runner 组合在一起。
真实 QwenPaw 的 Workspace 还会管理 MCP、渠道、Cron、Context Manager 等服务。
"""

from pathlib import Path
import logging

from .console import flow
from .memory import Memory
from .messages import TraceEvent
from .runner import AgentRunner
from .skills import SkillLoader
from .tools import create_builtin_tools

logger = logging.getLogger("anpaw.workspace")


class Workspace:
    """一个 agent_id 对应一个 Workspace。"""

    def __init__(
        self,
        agent_id: str,
        root_dir: Path,
        trace: list[TraceEvent] | None = None,
    ) -> None:
        flow("Workspace", "创建工作区对象", agent=agent_id)
        self.agent_id = agent_id
        # 每个 Agent 拥有自己的 workspace 目录，避免状态串在一起。
        self.workspace_dir = root_dir / "workspace" / agent_id
        self.skills_dir = root_dir / "skills"
        self.workspace_dir.mkdir(parents=True, exist_ok=True)
        if trace is not None:
            trace.append(
                TraceEvent(
                    stage="workspace_init",
                    detail="create workspace object and directory",
                    data={
                        "agent_id": agent_id,
                        "workspace_dir": str(self.workspace_dir),
                    },
                ),
            )

        # 学习版把会话记忆持久化到每个 Workspace 的 JSON 文件里。
        self.memory = Memory(path=self.workspace_dir / "session.json")
        self.memory.load()
        if trace is not None:
            trace.append(
                TraceEvent(
                    stage="memory_load",
                    detail="load workspace session memory",
                    data={
                        "agent_id": agent_id,
                        "path": str(self.memory.path),
                        "messages": len(self.memory.messages),
                    },
                ),
            )

        # 内置工具和 Skill 在 Workspace 创建时装配。
        # memory_search 工具会通过这里拿到当前 Workspace 的会话记忆。
        self.tools = create_builtin_tools(self.workspace_dir, memory=self.memory)
        if trace is not None:
            trace.append(
                TraceEvent(
                    stage="tool_register",
                    detail="register builtin tools",
                    data={"agent_id": agent_id, "tools": self.tools.names()},
                ),
            )
        self.skills = SkillLoader(self.skills_dir).load()
        if trace is not None:
            trace.append(
                TraceEvent(
                    stage="skill_load",
                    detail="load skills from SKILL.md",
                    data={"agent_id": agent_id, "skills": list(self.skills)},
                ),
            )
        flow(
            "Workspace",
            "已装配工具和 Skills",
            tools=self.tools.names(),
            skills=list(self.skills),
        )

        # Runner 是一次请求的编排器。
        self.runner = AgentRunner(
            agent_id=agent_id,
            memory=self.memory,
            tools=self.tools,
            skills=self.skills,
        )
        if trace is not None:
            trace.append(
                TraceEvent(
                    stage="runner_ready",
                    detail="create AgentRunner",
                    data={
                        "agent_id": agent_id,
                        "session_id": self.runner.session_id,
                    },
                ),
            )
        logger.info(
            "workspace created agent=%s skills=%s tools=%s",
            agent_id,
            list(self.skills),
            self.tools.names(),
        )

    def start(self, trace: list[TraceEvent] | None = None) -> None:
        """启动 Workspace。

        学习版只创建目录并记录 trace；
        真实项目会在这里启动更多后台服务。
        """
        flow("Workspace", "启动工作区目录", path=self.workspace_dir)
        logger.info("workspace started agent=%s dir=%s", self.agent_id, self.workspace_dir)
        if trace is not None:
            trace.append(
                TraceEvent(
                    stage="workspace",
                    detail="start workspace services",
                    data={
                        "agent_id": self.agent_id,
                        "workspace_dir": str(self.workspace_dir),
                        "skills": list(self.skills),
                        "tools": self.tools.names(),
                    },
                ),
            )

    def stop(self) -> None:
        """停止 Workspace。

        这里留空，是为了保留真实项目的生命周期形状。
        """
        pass
