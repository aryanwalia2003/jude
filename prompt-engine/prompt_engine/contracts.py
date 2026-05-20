"""Output contracts — the structured shape each task type must produce."""

from dataclasses import dataclass, field
from .taxonomy import TaskType


@dataclass(frozen=True)
class OutputField:
    name: str
    description: str
    required: bool = True


@dataclass(frozen=True)
class OutputContract:
    task_type: TaskType
    fields: tuple[OutputField, ...]
    preamble: str = ""

    def required_fields(self) -> list[OutputField]:
        return [f for f in self.fields if f.required]

    def optional_fields(self) -> list[OutputField]:
        return [f for f in self.fields if not f.required]

    def as_prompt_block(self) -> str:
        lines = ["OUTPUT FORMAT"]
        lines.append("Your response must include all required fields below.")
        lines.append("")
        for i, f in enumerate(self.fields, 1):
            marker = "" if f.required else " (optional)"
            lines.append(f"{i}. {f.name}{marker}: {f.description}")
        return "\n".join(lines)


_BUGFIX = OutputContract(
    task_type=TaskType.BUGFIX,
    fields=(
        OutputField("symptom", "What was observed — the visible broken behavior"),
        OutputField("root_cause", "The actual code-level cause of the bug"),
        OutputField("trigger", "The exact conditions that reproduce the issue"),
        OutputField("affected_code_paths", "Files, functions, and call chains involved"),
        OutputField("fix_strategy", "Why this specific fix is correct and minimal"),
        OutputField("patch", "The code change — diffs or file sections"),
        OutputField("tests", "Test(s) that verify the fix and prevent regression"),
        OutputField("regression_risks", "What related behavior could break"),
        OutputField("assumptions", "Anything you inferred that isn't explicit in the code", required=False),
    ),
)

_FEATURE = OutputContract(
    task_type=TaskType.FEATURE,
    fields=(
        OutputField("goal", "What the feature achieves and why"),
        OutputField("design_choice", "The approach chosen and why over alternatives"),
        OutputField("affected_interfaces", "Public APIs, contracts, or boundaries touched"),
        OutputField("patch", "The implementation — diffs or file sections"),
        OutputField("tests", "Tests covering the new behavior and edge cases"),
        OutputField("migration_notes", "DB/schema/data changes needed", required=False),
        OutputField("compatibility_notes", "Impact on existing callers or consumers"),
        OutputField("risks", "What could go wrong"),
    ),
)

_REFACTOR = OutputContract(
    task_type=TaskType.REFACTOR,
    fields=(
        OutputField("current_shape", "How the code is structured now"),
        OutputField("target_shape", "How it should be structured after"),
        OutputField("migration_path", "Step-by-step changes required"),
        OutputField("patch", "The code change"),
        OutputField("compatibility", "Preserved vs changed behavior"),
        OutputField("risk_analysis", "What could regress or break"),
        OutputField("tests", "Tests that confirm behavior is preserved"),
    ),
)

_TEST_GENERATION = OutputContract(
    task_type=TaskType.TEST_GENERATION,
    fields=(
        OutputField("coverage_plan", "Which cases are covered: happy path, edge cases, failure modes"),
        OutputField("fixtures", "Test data and setup needed"),
        OutputField("tests", "The test code"),
        OutputField("gaps", "Cases that are hard to test statically or need integration setup", required=False),
    ),
)

_DEBUGGING = OutputContract(
    task_type=TaskType.DEBUGGING,
    fields=(
        OutputField("reproduction", "How to reproduce the problem"),
        OutputField("evidence", "Log output, stack traces, or code paths that point to the cause"),
        OutputField("likely_cause", "The most probable root cause"),
        OutputField("uncertainty", "What you don't know or can't confirm statically"),
        OutputField("next_steps", "Concrete investigation or fix steps"),
        OutputField("patch_if_applicable", "A fix if the cause is clear enough", required=False),
    ),
)

_EXPLANATION = OutputContract(
    task_type=TaskType.EXPLANATION,
    fields=(
        OutputField("summary", "One-paragraph plain-language explanation"),
        OutputField("key_concepts", "The main abstractions and how they relate"),
        OutputField("data_flow", "How data moves through the relevant code path"),
        OutputField("invariants", "Assumptions the code relies on", required=False),
        OutputField("gotchas", "Non-obvious behavior or footguns", required=False),
    ),
)

_OPTIMIZATION = OutputContract(
    task_type=TaskType.OPTIMIZATION,
    fields=(
        OutputField("bottleneck", "Where the performance problem actually is"),
        OutputField("evidence", "Profiling data, query plans, or benchmarks supporting this"),
        OutputField("fix_strategy", "The optimization approach and why it helps"),
        OutputField("patch", "The code change"),
        OutputField("expected_gain", "Estimated improvement"),
        OutputField("risks", "Trade-offs: correctness, readability, or other regressions"),
    ),
)

_MIGRATION = OutputContract(
    task_type=TaskType.MIGRATION,
    fields=(
        OutputField("scope", "What is being migrated"),
        OutputField("compatibility_constraints", "What must remain compatible during transition"),
        OutputField("migration_steps", "Ordered list of steps including dual-write if needed"),
        OutputField("rollback_plan", "How to reverse if something goes wrong"),
        OutputField("backfill_needs", "Whether existing data or state needs to be updated"),
        OutputField("risks", "What could fail and how to detect it"),
        OutputField("patch", "The implementation"),
    ),
)

_CODE_REVIEW = OutputContract(
    task_type=TaskType.CODE_REVIEW,
    fields=(
        OutputField("issues_found", "List of issues with severity: critical / warning / suggestion"),
        OutputField("severity_summary", "Count by severity level"),
        OutputField("rationale", "Why each issue matters"),
        OutputField("suggested_changes", "Concrete fixes for each issue"),
        OutputField("non_issues", "Things that look unusual but are intentional"),
        OutputField("confidence", "How confident you are in the analysis"),
    ),
)

_SECURITY = OutputContract(
    task_type=TaskType.SECURITY,
    fields=(
        OutputField("vulnerability", "What the security issue is"),
        OutputField("attack_vector", "How it could be exploited"),
        OutputField("affected_paths", "Code paths involved"),
        OutputField("fix_strategy", "The correct remediation"),
        OutputField("patch", "The code change"),
        OutputField("verification", "How to confirm the fix closes the vector"),
        OutputField("related_risks", "Other issues that may need attention", required=False),
    ),
)

_PERFORMANCE = OutputContract(
    task_type=TaskType.PERFORMANCE,
    fields=(
        OutputField("hotspot", "The specific function, query, or loop causing the issue"),
        OutputField("evidence", "Measurement data"),
        OutputField("fix_strategy", "Optimization approach"),
        OutputField("patch", "The code change"),
        OutputField("expected_gain", "Quantified improvement"),
        OutputField("risks", "Trade-offs"),
    ),
)

_DEFAULT = OutputContract(
    task_type=TaskType.CLEANUP,
    fields=(
        OutputField("summary", "What was done"),
        OutputField("changes", "Files and lines changed"),
        OutputField("rationale", "Why each change was made"),
        OutputField("risks", "Anything that could regress"),
    ),
)

_CONTRACTS: dict[TaskType, OutputContract] = {
    TaskType.BUGFIX: _BUGFIX,
    TaskType.FEATURE: _FEATURE,
    TaskType.REFACTOR: _REFACTOR,
    TaskType.TEST_GENERATION: _TEST_GENERATION,
    TaskType.DEBUGGING: _DEBUGGING,
    TaskType.EXPLANATION: _EXPLANATION,
    TaskType.OPTIMIZATION: _OPTIMIZATION,
    TaskType.MIGRATION: _MIGRATION,
    TaskType.CODE_REVIEW: _CODE_REVIEW,
    TaskType.SECURITY: _SECURITY,
    TaskType.PERFORMANCE: _PERFORMANCE,
}


def get_contract(task_type: TaskType) -> OutputContract:
    return _CONTRACTS.get(task_type, _DEFAULT)
