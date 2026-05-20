"""Context budget management — token allocation and prioritization."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .task import ContextBudget, PromptBlock, PromptPlan


_CHARS_PER_TOKEN = 4


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // _CHARS_PER_TOKEN)


@dataclass
class BudgetAllocation:
    system_policy: int
    task_block: int
    constraints: int
    context_placeholder: int
    output_contract: int
    verification: int

    @property
    def total(self) -> int:
        return (
            self.system_policy
            + self.task_block
            + self.constraints
            + self.context_placeholder
            + self.output_contract
            + self.verification
        )


def allocate(budget: ContextBudget) -> BudgetAllocation:
    """Distribute token budget across prompt sections."""
    total = budget.max_tokens
    return BudgetAllocation(
        system_policy=int(total * 0.08),
        task_block=int(total * 0.05),
        constraints=int(total * 0.10),
        context_placeholder=int(total * 0.55),  # largest — actual repo context
        output_contract=int(total * 0.12),
        verification=int(total * 0.10),
    )


def enforce_budget(plan: PromptPlan) -> PromptPlan:
    """Mark low-priority blocks as excluded if over budget."""
    if not plan.budget:
        return plan

    max_tokens = plan.budget.max_tokens
    included = sorted(
        [b for b in plan.blocks if b.included],
        key=lambda b: b.priority,
    )
    running = 0
    for block in included:
        if running + block.token_estimate > max_tokens:
            block.included = False
            block.omit_reason = f"budget exceeded ({running}/{max_tokens} used)"
        else:
            running += block.token_estimate

    return plan


def compression_summary(plan: PromptPlan) -> list[str]:
    """Describe what was included vs excluded and why."""
    lines = []
    for b in plan.blocks:
        status = "✓" if b.included else "✗"
        reason = f"  [{b.omit_reason}]" if b.omit_reason else ""
        lines.append(f"  {status} {b.role:<22} ~{b.token_estimate:>4} tokens{reason}")
    if plan.budget:
        used = plan.total_tokens()
        cap = plan.budget.max_tokens
        pct = int(used / cap * 100)
        lines.append(f"\n  Total: {used}/{cap} tokens ({pct}%)")
    return lines
