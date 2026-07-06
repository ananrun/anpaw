from __future__ import annotations

"""内置工具系统。

模型不能直接执行本地操作，只能“请求调用工具”。
Agent 收到 tool 决策后，会通过 ToolRegistry 找到对应函数并执行。
"""

import ast
import logging
import operator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable


ToolFn = Callable[..., str]
logger = logging.getLogger("anpaw.tools")


@dataclass
class Tool:
    """工具元信息和实际 Python 函数。"""

    name: str
    description: str
    fn: ToolFn


class ToolRegistry:
    """工具注册表。"""

    def __init__(self, workspace_dir: Path) -> None:
        self.workspace_dir = workspace_dir
        self._tools: dict[str, Tool] = {}

    def register(self, name: str, description: str, fn: ToolFn) -> None:
        """注册一个可被模型调用的工具。"""
        self._tools[name] = Tool(name=name, description=description, fn=fn)
        logger.info("registered tool name=%s", name)

    def get(self, name: str) -> Tool:
        """按名称获取工具。"""
        return self._tools[name]

    def describe(self) -> str:
        """返回工具说明，供 `/tools` 命令展示。"""
        return "\n".join(
            f"- {tool.name}: {tool.description}"
            for tool in self._tools.values()
        )

    def names(self) -> list[str]:
        """返回工具名称列表，供 trace/env_context 展示。"""
        return list(self._tools)

    def run(self, name: str, arguments: dict) -> str:
        """执行工具并返回字符串结果。"""
        print(f"[Tool] 调用工具 {name}，参数={arguments}")
        logger.info("run tool name=%s args=%s", name, arguments)
        tool = self.get(name)
        result = tool.fn(**arguments)
        logger.info("tool result name=%s result=%r", name, result[:200])
        print(f"[Tool] 工具 {name} 返回: {result[:120]!r}")
        return result


def create_builtin_tools(workspace_dir: Path) -> ToolRegistry:
    """创建学习版内置工具。"""
    registry = ToolRegistry(workspace_dir=workspace_dir)
    registry.register("calculator", "计算四则运算表达式", safe_calculate)
    registry.register("time", "获取当前本地时间", current_time)
    registry.register(
        "note",
        "把内容写入 workspace/notes.txt",
        lambda text: append_note(workspace_dir, text),
    )
    return registry


def current_time() -> str:
    """返回当前本地时间。"""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def append_note(workspace_dir: Path, text: str) -> str:
    """把文本追加到当前 Workspace 的 notes.txt。"""
    workspace_dir.mkdir(parents=True, exist_ok=True)
    path = workspace_dir / "notes.txt"
    with path.open("a", encoding="utf-8") as file:
        file.write(text.strip() + "\n")
    return f"已写入 {path}"


def safe_calculate(expression: str) -> str:
    """安全计算简单四则表达式。

    这里用 AST 白名单，而不是 eval，避免执行任意 Python 代码。
    """
    allowed = {
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.Div: operator.truediv,
        ast.USub: operator.neg,
    }

    def eval_node(node: ast.AST) -> float:
        if isinstance(node, ast.Expression):
            return eval_node(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        if isinstance(node, ast.UnaryOp) and type(node.op) in allowed:
            return allowed[type(node.op)](eval_node(node.operand))
        if isinstance(node, ast.BinOp) and type(node.op) in allowed:
            return allowed[type(node.op)](eval_node(node.left), eval_node(node.right))
        raise ValueError("只允许数字和 + - * /")

    tree = ast.parse(expression, mode="eval")
    value = eval_node(tree)
    return str(int(value) if value == int(value) else value)
