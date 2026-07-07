from __future__ import annotations

"""多 Agent 管理器。

真实 QwenPaw 支持多个 agent_id，每个 Agent 有独立 Workspace。
这里保留最核心的机制：按 agent_id 懒加载 Workspace，并缓存起来复用。
"""

from pathlib import Path
import logging

from .console import flow
from .messages import TraceEvent
from .workspace import Workspace

logger = logging.getLogger("anpaw.manager")


class MultiAgentManager:
    """进程内的 Workspace 注册表。"""

    def __init__(self, root_dir: Path) -> None:
        self.root_dir = root_dir
        # key 是 agent_id，value 是已经启动的 Workspace。
        self.agents: dict[str, Workspace] = {}

    def get_agent(
        self,
        agent_id: str,
        trace: list[TraceEvent] | None = None,
    ) -> Workspace:
        """获取某个 Agent 的 Workspace。

        第一次请求某个 agent_id 时创建 Workspace；
        后续请求直接复用，模拟 QwenPaw 的懒加载行为。
        """
        message = f"根据 agent_id={agent_id!r} 查找 Workspace"
        flow("Manager", message, loaded_agents=list(self.agents))
        logger.info(message)
        if trace is not None:
            trace.append(
                TraceEvent(
                    stage="manager",
                    detail="resolve workspace by agent_id",
                    data={
                        "agent_id": agent_id,
                        "loaded_agents": list(self.agents),
                    },
                ),
            )
        if agent_id in self.agents:
            message = f"命中缓存，复用已加载 Workspace: {agent_id}"
            flow("Manager", message)
            logger.info(message)
            if trace is not None:
                trace.append(
                    TraceEvent(
                        stage="workspace",
                        detail="reuse loaded workspace",
                        data={
                            "agent_id": agent_id,
                            "workspace_dir": str(
                                self.agents[agent_id].workspace_dir,
                            ),
                        },
                    ),
                )
            return self.agents[agent_id]

        # 没加载过的 agent_id 会在这里创建独立工作区。
        if trace is not None:
            trace.append(
                TraceEvent(
                    stage="manager",
                    detail="workspace not loaded, create it lazily",
                    data={"agent_id": agent_id},
                ),
            )
        message = f"未找到 Workspace，开始懒加载: {agent_id}"
        flow("Manager", message)
        logger.info(message)
        workspace = Workspace(agent_id=agent_id, root_dir=self.root_dir, trace=trace)
        workspace.start(trace=trace)
        self.agents[agent_id] = workspace
        message = f"Workspace 已加载并缓存: {agent_id}"
        flow("Manager", message)
        logger.info(message)
        return workspace

    def list_loaded_agents(self) -> list[str]:
        return list(self.agents)
