"""Core task data model — typed internal representation of a developer's intent."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Optional

from .taxonomy import TaskType, SubType, Mode, Constraint, RiskLevel


@dataclass
class ContextBudget:
    max_tokens: int = 8000
    retrieval_depth: int = 2
    summary_depth: str = "module"        # symbol | module | subsystem
    code_chunk_lines: int = 150
    include_tests: bool = True
    include_history: bool = True
    include_imports: bool = True
    output_verbosity: str = "normal"     # compact | normal | verbose

    def scale_for_mode(self, mode: Mode) -> "ContextBudget":
        """Return a new budget adjusted for the given mode."""
        overrides: dict = {}
        if mode == Mode.MINIMAL:
            overrides = dict(max_tokens=3000, retrieval_depth=1, output_verbosity="compact")
        elif mode == Mode.FAST:
            overrides = dict(max_tokens=4000, retrieval_depth=1, output_verbosity="compact")
        elif mode == Mode.DEEP:
            overrides = dict(max_tokens=16000, retrieval_depth=4, summary_depth="subsystem")
        elif mode == Mode.ARCHITECTURAL:
            overrides = dict(max_tokens=12000, retrieval_depth=3, summary_depth="subsystem")
        elif mode == Mode.SURGICAL:
            overrides = dict(max_tokens=6000, retrieval_depth=2)
        elif mode == Mode.SAFE:
            overrides = dict(max_tokens=10000, retrieval_depth=3, include_tests=True)
        elif mode == Mode.STRICT:
            overrides = dict(max_tokens=10000, retrieval_depth=3, output_verbosity="verbose")
        return ContextBudget(
            max_tokens=overrides.get("max_tokens", self.max_tokens),
            retrieval_depth=overrides.get("retrieval_depth", self.retrieval_depth),
            summary_depth=overrides.get("summary_depth", self.summary_depth),
            code_chunk_lines=overrides.get("code_chunk_lines", self.code_chunk_lines),
            include_tests=overrides.get("include_tests", self.include_tests),
            include_history=overrides.get("include_history", self.include_history),
            include_imports=overrides.get("include_imports", self.include_imports),
            output_verbosity=overrides.get("output_verbosity", self.output_verbosity),
        )


@dataclass
class RetrievalPlan:
    query: str
    priority_categories: list[str] = field(default_factory=list)
    file_targets: list[str] = field(default_factory=list)
    symbol_targets: list[str] = field(default_factory=list)
    test_targets: list[str] = field(default_factory=list)
    summary_targets: list[str] = field(default_factory=list)
    excluded_targets: list[str] = field(default_factory=list)
    git_history: bool = False
    include_call_chains: bool = True

    def describe(self) -> list[str]:
        lines = []
        for i, cat in enumerate(self.priority_categories, 1):
            lines.append(f"  Priority {i}: {cat}")
        if self.excluded_targets:
            lines.append(f"  Excluded:   {', '.join(self.excluded_targets)}")
        return lines


@dataclass
class VerificationPlan:
    required_checks: list[str] = field(default_factory=list)
    optional_checks: list[str] = field(default_factory=list)
    warning_conditions: list[str] = field(default_factory=list)
    acceptance_criteria: list[str] = field(default_factory=list)

    def describe(self) -> list[str]:
        lines = []
        if self.required_checks:
            lines.append("  Required:  " + ", ".join(self.required_checks))
        if self.optional_checks:
            lines.append("  Optional:  " + ", ".join(self.optional_checks))
        if self.warning_conditions:
            lines.append("  Warnings:  " + ", ".join(self.warning_conditions))
        return lines


@dataclass
class PromptBlock:
    role: str          # system | task | constraints | context | output_contract | verification
    content: str
    priority: int = 50
    token_estimate: int = 0
    included: bool = True
    omit_reason: Optional[str] = None
    source: str = ""   # which rule or preset caused this block

    def __post_init__(self) -> None:
        if not self.token_estimate:
            self.token_estimate = max(1, len(self.content) // 4)


@dataclass
class PromptPlan:
    blocks: list[PromptBlock] = field(default_factory=list)
    budget: Optional[ContextBudget] = None

    def total_tokens(self) -> int:
        return sum(b.token_estimate for b in self.blocks if b.included)

    def included_blocks(self) -> list[PromptBlock]:
        return sorted(
            (b for b in self.blocks if b.included),
            key=lambda b: b.priority,
        )

    def compile(self) -> str:
        return "\n\n".join(b.content for b in self.included_blocks())

    def to_messages(self) -> list[dict]:
        system_parts = [b.content for b in self.included_blocks() if b.role == "system"]
        user_parts = [b.content for b in self.included_blocks() if b.role != "system"]
        messages = []
        if system_parts:
            messages.append({"role": "system", "content": "\n\n".join(system_parts)})
        if user_parts:
            messages.append({"role": "user", "content": "\n\n".join(user_parts)})
        return messages

    def budget_report(self) -> list[str]:
        lines = []
        for b in self.included_blocks():
            lines.append(f"  {b.role:<20} {b.token_estimate:>5} tokens  [{b.source}]")
        lines.append(f"  {'TOTAL':<20} {self.total_tokens():>5} tokens")
        if self.budget:
            pct = int(self.total_tokens() / self.budget.max_tokens * 100)
            lines.append(f"  Budget: {self.total_tokens()}/{self.budget.max_tokens} ({pct}%)")
        return lines


@dataclass
class Task:
    raw_intent: str
    task_type: TaskType
    sub_type: Optional[SubType] = None
    mode: Mode = Mode.SURGICAL
    scope: Optional[str] = None
    constraints: list[Constraint] = field(default_factory=list)
    risk_level: RiskLevel = RiskLevel.MEDIUM
    confidence: float = 1.0
    classification_evidence: list[str] = field(default_factory=list)
    output_contract: Optional[object] = None
    retrieval_plan: Optional[RetrievalPlan] = None
    context_budget: Optional[ContextBudget] = None
    verification_plan: Optional[VerificationPlan] = None
    session_state: dict = field(default_factory=dict)
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])

    @property
    def normalized_intent(self) -> str:
        parts = [self.task_type.value]
        if self.sub_type:
            parts.append(f"({self.sub_type.value})")
        parts.append(f'"{self.raw_intent}"')
        if self.scope:
            parts.append(f"scope={self.scope}")
        return " ".join(parts)
