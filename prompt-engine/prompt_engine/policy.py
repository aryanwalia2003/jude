"""Policy registry — repo-specific rules compiled into prompt blocks."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .taxonomy import TaskType


@dataclass
class PolicyRule:
    name: str
    description: str
    applies_to: list[TaskType]  # empty = applies to all
    text: str                   # verbatim text injected into the system block
    priority: int = 50


@dataclass
class PolicyRegistry:
    rules: list[PolicyRule] = field(default_factory=list)
    repo_policy_text: str = ""

    def add(self, rule: PolicyRule) -> None:
        self.rules.append(rule)

    def rules_for(self, task_type: TaskType) -> list[PolicyRule]:
        return [
            r for r in sorted(self.rules, key=lambda x: x.priority)
            if not r.applies_to or task_type in r.applies_to
        ]

    def compile_for(self, task_type: TaskType) -> str:
        parts = []
        if self.repo_policy_text:
            parts.append(f"REPOSITORY POLICY\n{self.repo_policy_text}")
        rules = self.rules_for(task_type)
        if rules:
            rule_text = "\n".join(f"- {r.text}" for r in rules)
            parts.append(f"ADDITIONAL RULES\n{rule_text}")
        return "\n\n".join(parts)


# Built-in universal rules — always active
_UNIVERSAL_RULES: list[PolicyRule] = [
    PolicyRule(
        name="anti_slop",
        description="Prevent generic advice and unnecessary changes",
        applies_to=[],
        text="Do not give generic advice unconnected to this specific codebase.",
        priority=10,
    ),
    PolicyRule(
        name="no_speculation",
        description="Prohibit invented or unverified facts",
        applies_to=[],
        text="Do not invent facts. State uncertainty explicitly.",
        priority=10,
    ),
    PolicyRule(
        name="repo_native",
        description="Prefer existing repo patterns over generic best practices",
        applies_to=[],
        text="Match the patterns already present in the repository. Do not introduce foreign conventions.",
        priority=20,
    ),
    PolicyRule(
        name="no_churn",
        description="Prevent unnecessary file and rename churn",
        applies_to=[],
        text="Do not touch files unrelated to the task. Do not rename unless the name is causing the bug.",
        priority=20,
    ),
    PolicyRule(
        name="bounded_scope",
        description="Enforce task scope boundaries",
        applies_to=[],
        text="Stay within the stated task scope. If you notice adjacent issues, mention them but do not fix them.",
        priority=20,
    ),
]


def build_registry(repo_policy_text: str = "") -> PolicyRegistry:
    registry = PolicyRegistry(repo_policy_text=repo_policy_text)
    for rule in _UNIVERSAL_RULES:
        registry.add(rule)
    return registry


def load_policy_from_file(path: Path) -> str:
    """Load repo-specific policy text from a markdown or text file."""
    if not path.exists():
        return ""
    return path.read_text().strip()
