from __future__ import annotations

"""Skill 加载器。

Skill 在这里不是 Python 函数，而是 `skills/*/SKILL.md` 里的说明文档。
真实 QwenPaw 会把 Skill 内容注入模型上下文，让模型按说明工作。
"""

from dataclasses import dataclass
from pathlib import Path


@dataclass
class Skill:
    """一个从 SKILL.md 读取出来的能力说明。"""

    name: str
    description: str
    body: str
    path: Path


class SkillLoader:
    """扫描 skills 目录并读取所有 SKILL.md。"""

    def __init__(self, skills_dir: Path) -> None:
        self.skills_dir = skills_dir

    def load(self) -> dict[str, Skill]:
        """返回 `{skill_name: Skill}`。"""
        skills: dict[str, Skill] = {}
        if not self.skills_dir.exists():
            return skills

        for skill_md in self.skills_dir.glob("*/SKILL.md"):
            name = skill_md.parent.name
            body = skill_md.read_text(encoding="utf-8")
            description = _first_description(body)
            skills[name] = Skill(
                name=name,
                description=description,
                body=body,
                path=skill_md.parent,
            )
        return skills


def _first_description(markdown: str) -> str:
    """从 SKILL.md 中提取一行简短描述。"""
    for line in markdown.splitlines():
        if line.lower().startswith("description:"):
            return line.split(":", 1)[1].strip()
    for line in markdown.splitlines():
        line = line.strip("# ").strip()
        if line:
            return line
    return "No description"
