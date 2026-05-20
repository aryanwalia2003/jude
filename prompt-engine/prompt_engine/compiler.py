"""Prompt compiler — assembles a PromptPlan from a Task. No LLM involved."""

from __future__ import annotations

from typing import Optional

from typing import TYPE_CHECKING

from .contracts import get_contract
from .policy import PolicyRegistry, build_registry
from .taxonomy import Constraint, Mode, TaskType
from .task import ContextBudget, PromptBlock, PromptPlan, Task
from .budget import enforce_budget
from .config import EngineConfig

if TYPE_CHECKING:
    from .retrieval import ContextBundle


# Priority constants for prompt block ordering
_P_SYSTEM = 10
_P_TASK = 20
_P_CONSTRAINTS = 30
_P_CONTEXT = 40
_P_OUTPUT_CONTRACT = 50
_P_VERIFICATION = 60


# ---------------------------------------------------------------------------
# System policy block
# ---------------------------------------------------------------------------

_SYSTEM_POLICY = """\
You are an expert software engineer operating inside a structured coding workflow.

CORE RULES
- Operate within the stated task scope. Do not fix adjacent issues.
- Do not invent facts. State all assumptions explicitly.
- Match the patterns already in this codebase. Do not import foreign conventions.
- Do not rename, reformat, or reorganize unless required by the task.
- Produce the smallest change that satisfies the goal.
- Every claim must be grounded in the provided context."""

_MODE_ADDENDA: dict[Mode, str] = {
    Mode.SURGICAL: "SURGICAL MODE: Minimize the diff. One focused change. No scope creep.",
    Mode.DEEP: "DEEP MODE: Gather full understanding before acting. Consider second-order effects.",
    Mode.FAST: "FAST MODE: Be concise. Compact output. Skip optional sections.",
    Mode.SAFE: "SAFE MODE: Conservative changes only. Flag any behavioral risk. Prefer doing less.",
    Mode.EXPLORE: "EXPLORE MODE: Present 2–3 candidate approaches with trade-offs before committing.",
    Mode.STRICT: "STRICT MODE: All assumptions must be explicit. Required fields are mandatory.",
    Mode.MINIMAL: "MINIMAL MODE: Ultra-compact. Omit optional fields. Use the smallest context.",
    Mode.ARCHITECTURAL: "ARCHITECTURAL MODE: Focus on design boundaries, invariants, and module ownership.",
    Mode.DEBUG: "DEBUG MODE: Root-cause first. Gather evidence before proposing any fix.",
    Mode.REWRITE: "REWRITE MODE: You may reshape internals. State what is intentionally changed.",
    Mode.MAINTAIN: "MAINTAIN MODE: Preserve repo consistency above all. Low churn. Follow conventions.",
}


def _system_block(task: Task, registry: Optional[PolicyRegistry] = None) -> PromptBlock:
    parts = [_SYSTEM_POLICY]
    mode_note = _MODE_ADDENDA.get(task.mode)
    if mode_note:
        parts.append(mode_note)
    if registry:
        policy_text = registry.compile_for(task.task_type)
        if policy_text:
            parts.append(policy_text)
    return PromptBlock(
        role="system",
        content="\n\n".join(parts),
        priority=_P_SYSTEM,
        source="system_policy",
    )


# ---------------------------------------------------------------------------
# Task block
# ---------------------------------------------------------------------------

def _task_block(task: Task) -> PromptBlock:
    lines = [f"TASK: {task.task_type.value.upper()}"]
    if task.sub_type:
        lines.append(f"Subtype: {task.sub_type.value}")
    lines.append(f"Goal: {task.raw_intent}")
    if task.scope:
        lines.append(f"Scope: {task.scope}")
    lines.append(f"Mode: {task.mode.value}")
    lines.append(f"Risk level: {task.risk_level.value}")
    return PromptBlock(
        role="task",
        content="\n".join(lines),
        priority=_P_TASK,
        source="task_normalization",
    )


# ---------------------------------------------------------------------------
# Constraints block
# ---------------------------------------------------------------------------

def _constraints_block(task: Task) -> PromptBlock:
    if not task.constraints:
        return PromptBlock(role="constraints", content="", priority=_P_CONSTRAINTS, included=False, source="none")

    from .taxonomy import CONSTRAINT_DESCRIPTIONS
    lines = ["CONSTRAINTS"]
    for c in task.constraints:
        desc = CONSTRAINT_DESCRIPTIONS.get(c, c.value)
        lines.append(f"- {desc}")
    return PromptBlock(
        role="constraints",
        content="\n".join(lines),
        priority=_P_CONSTRAINTS,
        source="task_constraints",
    )


# ---------------------------------------------------------------------------
# Context block — placeholder or filled from retrieval
# ---------------------------------------------------------------------------

def _context_block(task: Task, bundle: "ContextBundle | None" = None) -> PromptBlock:
    if bundle is not None and not bundle.is_empty:
        return PromptBlock(
            role="context",
            content=bundle.raw_text,
            priority=_P_CONTEXT,
            token_estimate=bundle.token_estimate,
            source="repo_index_retrieval",
        )

    if not task.retrieval_plan:
        return PromptBlock(
            role="context",
            content="CONTEXT\n[No retrieval plan. Context will be provided inline.]",
            priority=_P_CONTEXT,
            source="none",
        )
    rp = task.retrieval_plan
    lines = ["CONTEXT", f"Query: {rp.query}"]
    if rp.priority_categories:
        lines.append("\nPriority context to provide:")
        for i, cat in enumerate(rp.priority_categories, 1):
            lines.append(f"  {i}. {cat}")
    if rp.excluded_targets:
        lines.append(f"\nExclude: {', '.join(rp.excluded_targets)}")
    lines.append("\n[Paste the relevant code, diffs, logs, or symbols here.]")
    return PromptBlock(
        role="context",
        content="\n".join(lines),
        priority=_P_CONTEXT,
        source="retrieval_plan_placeholder",
    )


# ---------------------------------------------------------------------------
# Output contract block
# ---------------------------------------------------------------------------

def _output_contract_block(task: Task) -> PromptBlock:
    contract = task.output_contract or get_contract(task.task_type)
    content = contract.as_prompt_block()

    if task.mode in (Mode.FAST, Mode.MINIMAL):
        required_only = contract.required_fields()
        lines = ["OUTPUT FORMAT (compact — required fields only)"]
        for i, f in enumerate(required_only, 1):
            lines.append(f"{i}. {f.name}: {f.description}")
        content = "\n".join(lines)

    return PromptBlock(
        role="output_contract",
        content=content,
        priority=_P_OUTPUT_CONTRACT,
        source=f"contract/{task.task_type.value}",
    )


# ---------------------------------------------------------------------------
# Verification block
# ---------------------------------------------------------------------------

def _verification_block(task: Task) -> PromptBlock:
    if not task.verification_plan:
        return PromptBlock(
            role="verification",
            content="",
            priority=_P_VERIFICATION,
            included=False,
            source="none",
        )
    vp = task.verification_plan

    if task.mode in (Mode.FAST, Mode.MINIMAL):
        return PromptBlock(
            role="verification",
            content="",
            priority=_P_VERIFICATION,
            included=False,
            omit_reason="omitted in fast/minimal mode",
            source="mode_policy",
        )

    lines = ["VERIFICATION REQUIREMENTS"]
    if vp.required_checks:
        lines.append("Required: " + ", ".join(vp.required_checks))
    if vp.acceptance_criteria:
        lines.append("Acceptance: " + "; ".join(vp.acceptance_criteria))
    if vp.warning_conditions:
        lines.append("Flag a warning if: " + "; ".join(vp.warning_conditions))
    return PromptBlock(
        role="verification",
        content="\n".join(lines),
        priority=_P_VERIFICATION,
        source="verification_plan",
    )


# ---------------------------------------------------------------------------
# Main compile function
# ---------------------------------------------------------------------------

def compile_task(
    task: Task,
    config: Optional[EngineConfig] = None,
    registry: Optional[PolicyRegistry] = None,
    bundle: "ContextBundle | None" = None,
) -> PromptPlan:
    """Compile a Task into an ordered, budgeted PromptPlan. No LLM involved."""
    if registry is None:
        policy_text = config.repo_policy if config else ""
        registry = build_registry(policy_text)

    blocks: list[PromptBlock] = [
        _system_block(task, registry),
        _task_block(task),
        _constraints_block(task),
        _context_block(task, bundle),
        _output_contract_block(task),
        _verification_block(task),
    ]

    plan = PromptPlan(blocks=blocks, budget=task.context_budget)

    if task.context_budget:
        plan = enforce_budget(plan)

    return plan
