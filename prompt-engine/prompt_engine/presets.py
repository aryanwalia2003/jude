"""Presets and profiles — named configurations for common workflows."""

from dataclasses import dataclass, field
from typing import Optional

from .taxonomy import TaskType, Mode, Constraint


@dataclass(frozen=True)
class Preset:
    name: str                              # e.g. "bugfix/surgical"
    description: str
    task_type: TaskType
    mode: Mode
    extra_constraints: tuple[Constraint, ...] = ()
    remove_constraints: tuple[Constraint, ...] = ()
    context_depth: int = 2                 # retrieval_depth override
    no_tests: bool = False

    @property
    def short_name(self) -> str:
        return self.name.split("/")[-1]


@dataclass(frozen=True)
class Profile:
    name: str
    description: str
    mode_override: Optional[Mode] = None
    extra_constraints: tuple[Constraint, ...] = ()
    max_tokens_override: Optional[int] = None
    context_depth: int = 2


_PRESETS: dict[str, Preset] = {
    "bugfix/minimal": Preset(
        name="bugfix/minimal",
        description="Smallest possible bugfix. One file, one cause.",
        task_type=TaskType.BUGFIX,
        mode=Mode.SURGICAL,
        extra_constraints=(Constraint.MINIMAL_DIFF, Constraint.KEEP_FILE_CHURN_LOW),
        context_depth=1,
    ),
    "bugfix/safe": Preset(
        name="bugfix/safe",
        description="Conservative bugfix with strong verification.",
        task_type=TaskType.BUGFIX,
        mode=Mode.SAFE,
        extra_constraints=(Constraint.REQUIRE_RISK_ANALYSIS, Constraint.NO_BEHAVIORAL_SURPRISES),
        context_depth=3,
    ),
    "bugfix/deep": Preset(
        name="bugfix/deep",
        description="Deep root cause investigation before fixing.",
        task_type=TaskType.BUGFIX,
        mode=Mode.DEEP,
        context_depth=4,
    ),
    "feature/surgical": Preset(
        name="feature/surgical",
        description="Targeted feature addition, minimal scope.",
        task_type=TaskType.FEATURE,
        mode=Mode.SURGICAL,
        extra_constraints=(Constraint.NO_UNNECESSARY_ABSTRACTIONS, Constraint.AVOID_NEW_DEPENDENCIES),
    ),
    "feature/default": Preset(
        name="feature/default",
        description="Standard feature implementation.",
        task_type=TaskType.FEATURE,
        mode=Mode.DEEP,
        context_depth=3,
    ),
    "refactor/safe": Preset(
        name="refactor/safe",
        description="Behavior-preserving refactor with full verification.",
        task_type=TaskType.REFACTOR,
        mode=Mode.SAFE,
        extra_constraints=(Constraint.PRESERVE_PUBLIC_API, Constraint.NO_BEHAVIORAL_SURPRISES),
        context_depth=3,
    ),
    "refactor/compatibility": Preset(
        name="refactor/compatibility",
        description="Refactor that must maintain backward compatibility.",
        task_type=TaskType.REFACTOR,
        mode=Mode.SAFE,
        extra_constraints=(
            Constraint.NO_BACKWARD_COMPAT_BREAK,
            Constraint.PRESERVE_PUBLIC_API,
            Constraint.NO_API_SURFACE_GROWTH,
        ),
        context_depth=4,
    ),
    "debug/deep": Preset(
        name="debug/deep",
        description="Thorough debugging investigation.",
        task_type=TaskType.DEBUGGING,
        mode=Mode.DEBUG,
        context_depth=4,
    ),
    "test/coverage-first": Preset(
        name="test/coverage-first",
        description="Test generation focused on coverage and edge cases.",
        task_type=TaskType.TEST_GENERATION,
        mode=Mode.STRICT,
        context_depth=2,
    ),
    "security/strict": Preset(
        name="security/strict",
        description="Security fix with maximum scrutiny.",
        task_type=TaskType.SECURITY,
        mode=Mode.STRICT,
        extra_constraints=(
            Constraint.NO_SECURITY_REGRESSION,
            Constraint.NO_BEHAVIORAL_SURPRISES,
            Constraint.REQUIRE_RISK_ANALYSIS,
        ),
        context_depth=3,
    ),
    "migration/careful": Preset(
        name="migration/careful",
        description="Migration with rollback plan and dual-write strategy.",
        task_type=TaskType.MIGRATION,
        mode=Mode.SAFE,
        extra_constraints=(
            Constraint.NO_BACKWARD_COMPAT_BREAK,
            Constraint.NO_SCHEMA_CHANGE_WITHOUT_MIGRATION,
        ),
        context_depth=3,
    ),
    "review/strict": Preset(
        name="review/strict",
        description="Rigorous code review.",
        task_type=TaskType.CODE_REVIEW,
        mode=Mode.STRICT,
        extra_constraints=(Constraint.NO_GUESSING, Constraint.REQUIRE_EXPLANATION),
        context_depth=2,
    ),
}

_PROFILES: dict[str, Profile] = {
    "fast": Profile(
        name="fast",
        description="Minimize tokens and response time. Compact output.",
        mode_override=Mode.FAST,
        max_tokens_override=4000,
        context_depth=1,
    ),
    "balanced": Profile(
        name="balanced",
        description="Default balance of thoroughness and speed.",
        context_depth=2,
    ),
    "strict": Profile(
        name="strict",
        description="Strong guardrails. Explicit assumptions. Verbose output.",
        mode_override=Mode.STRICT,
        extra_constraints=(
            Constraint.NO_GUESSING,
            Constraint.REQUIRE_EXPLANATION,
            Constraint.REQUIRE_RISK_ANALYSIS,
        ),
        context_depth=3,
    ),
    "architectural": Profile(
        name="architectural",
        description="Design-boundary and invariant focused.",
        mode_override=Mode.ARCHITECTURAL,
        context_depth=4,
        max_tokens_override=14000,
    ),
    "experimental": Profile(
        name="experimental",
        description="Higher risk tolerance, more exploratory output.",
        mode_override=Mode.EXPLORE,
        context_depth=3,
    ),
}

# Verb aliases for the CLI
CLI_VERB_ALIASES: dict[str, TaskType] = {
    "fix": TaskType.BUGFIX,
    "bug": TaskType.BUGFIX,
    "bugfix": TaskType.BUGFIX,
    "feat": TaskType.FEATURE,
    "feature": TaskType.FEATURE,
    "add": TaskType.FEATURE,
    "ref": TaskType.REFACTOR,
    "refactor": TaskType.REFACTOR,
    "test": TaskType.TEST_GENERATION,
    "tests": TaskType.TEST_GENERATION,
    "dbg": TaskType.DEBUGGING,
    "debug": TaskType.DEBUGGING,
    "explain": TaskType.EXPLANATION,
    "why": TaskType.EXPLANATION,
    "opt": TaskType.OPTIMIZATION,
    "optimize": TaskType.OPTIMIZATION,
    "perf": TaskType.PERFORMANCE,
    "migrate": TaskType.MIGRATION,
    "migration": TaskType.MIGRATION,
    "review": TaskType.CODE_REVIEW,
    "secure": TaskType.SECURITY,
    "security": TaskType.SECURITY,
    "observe": TaskType.OBSERVABILITY,
    "docs": TaskType.DOCUMENTATION,
    "doc": TaskType.DOCUMENTATION,
    "clean": TaskType.CLEANUP,
    "cleanup": TaskType.CLEANUP,
    "reliable": TaskType.RELIABILITY,
}


def get_preset(name: str) -> Optional[Preset]:
    return _PRESETS.get(name)


def get_profile(name: str) -> Optional[Profile]:
    return _PROFILES.get(name)


def list_presets() -> list[Preset]:
    return list(_PRESETS.values())


def list_profiles() -> list[Profile]:
    return list(_PROFILES.values())
