from __future__ import annotations

"""Skill 加载器。

Skill 在这里不是 Python 函数，而是 `skills/*/SKILL.md` 里的说明文档。
真实 QwenPaw 会把 Skill 内容注入模型上下文，让模型按说明工作。
"""

import re
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


def rank_skills(user_text: str, skills: dict[str, Skill], limit: int = 3) -> list[dict]:
    """给当前用户消息生成可解释的 Skill 候选列表。

    真实 QwenPaw 主要依赖模型/Toolkit 上下文选择 Skill。AnPaw 为了教学可见性，
    在本地额外做一个轻量关键词打分，把“哪些 Skill 被认为相关”打印到控制台
    和 trace。这个分数只用于观察，不强行决定模型行为。
    """
    query_terms = _terms(user_text)
    ranked: list[tuple[int, dict]] = []
    for skill in skills.values():
        haystack = f"{skill.name}\n{skill.description}\n{skill.body}"
        skill_terms = _terms(haystack)
        overlap = sorted(query_terms & skill_terms)
        score = len(overlap)
        if skill.name.lower() in user_text.lower():
            score += 5
            overlap.insert(0, skill.name)
        if score:
            ranked.append(
                (
                    score,
                    {
                        "name": skill.name,
                        "score": score,
                        "description": skill.description,
                        "matched_terms": overlap[:8],
                    },
                ),
            )

    ranked.sort(key=lambda item: (-item[0], item[1]["name"]))
    return [item for _, item in ranked[:limit]]


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


def _terms(text: str) -> set[str]:
    """提取中英文混合关键词，供教学版 Skill 候选打分。"""
    lowered = text.lower()
    terms = set(re.findall(r"[a-z0-9_]{2,}", lowered))
    for chunk in re.findall(r"[\u4e00-\u9fff]+", lowered):
        terms.update(char for char in chunk if char in {"写", "算", "数", "改", "问", "搜", "记"})
        if len(chunk) > 1:
            terms.update(chunk[index : index + 2] for index in range(len(chunk) - 1))
    stop_terms = {
        "一个",
        "一段",
        "关于",
        "项目",
        "真实",
        "学习",
        "使用",
        "方式",
        "当前",
        "需要",
        "说明",
    }
    return terms - stop_terms
