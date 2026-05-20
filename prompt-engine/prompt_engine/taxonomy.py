"""Core taxonomy — task types, modes, constraints, risk levels."""

from enum import Enum


class TaskType(str, Enum):
    BUGFIX = "bugfix"
    FEATURE = "feature"
    REFACTOR = "refactor"
    TEST_GENERATION = "test_generation"
    DEBUGGING = "debugging"
    EXPLANATION = "explanation"
    OPTIMIZATION = "optimization"
    MIGRATION = "migration"
    CODE_REVIEW = "code_review"
    ARCHITECTURE = "architecture"
    DOCUMENTATION = "documentation"
    CLEANUP = "cleanup"
    SECURITY = "security"
    PERFORMANCE = "performance"
    RELIABILITY = "reliability"
    OBSERVABILITY = "observability"
    DEPENDENCY_UPDATE = "dependency_update"
    DATA_MIGRATION = "data_migration"
    API_CHANGE = "api_change"
    CLI_CHANGE = "cli_change"
    CONFIG_CHANGE = "config_change"
    BUILD_FIX = "build_fix"
    RELEASE_SUPPORT = "release_support"


class SubType(str, Enum):
    # bugfix
    RACE_CONDITION = "race_condition"
    NULL_HANDLING = "null_handling"
    DUPLICATE_EVENT = "duplicate_event"
    INCORRECT_STATE = "incorrect_state"
    EDGE_CASE_FAILURE = "edge_case_failure"
    REGRESSION = "regression"
    # feature
    ENDPOINT = "endpoint"
    BACKGROUND_JOB = "background_job"
    CLI_COMMAND = "cli_command"
    UI_FLOW = "ui_flow"
    WEBHOOK = "webhook"
    CACHE_LAYER = "cache_layer"
    # refactor
    INTERNAL_CLEANUP = "internal_cleanup"
    INTERFACE_SIMPLIFICATION = "interface_simplification"
    MODULARIZATION = "modularization"
    EXTRACTION = "extraction"
    DEPRECATION = "deprecation"
    # debugging
    RUNTIME_ERROR = "runtime_error"
    TEST_FLAKE = "test_flake"
    PERF_BOTTLENECK = "perf_bottleneck"
    INTERMITTENT_ISSUE = "intermittent_issue"
    INTEGRATION_FAILURE = "integration_failure"


class Mode(str, Enum):
    SURGICAL = "surgical"
    DEEP = "deep"
    FAST = "fast"
    SAFE = "safe"
    EXPLORE = "explore"
    STRICT = "strict"
    MINIMAL = "minimal"
    ARCHITECTURAL = "architectural"
    DEBUG = "debug"
    REWRITE = "rewrite"
    MAINTAIN = "maintain"


class Constraint(str, Enum):
    MINIMAL_DIFF = "minimal_diff"
    PRESERVE_PUBLIC_API = "preserve_public_api"
    NO_UNNECESSARY_ABSTRACTIONS = "no_unnecessary_abstractions"
    NO_UNRELATED_REFACTORS = "no_unrelated_refactors"
    FOLLOW_EXISTING_PATTERNS = "follow_existing_patterns"
    PRESERVE_BEHAVIOR = "preserve_behavior"
    MINIMIZE_TOKEN_USAGE = "minimize_token_usage"
    KEEP_FILE_CHURN_LOW = "keep_file_churn_low"
    AVOID_RENAMES_UNLESS_NEEDED = "avoid_renames_unless_needed"
    AVOID_NEW_DEPENDENCIES = "avoid_new_dependencies"
    REQUIRE_TESTS = "require_tests"
    REQUIRE_EXPLANATION = "require_explanation"
    REQUIRE_RISK_ANALYSIS = "require_risk_analysis"
    NO_GUESSING = "no_guessing"
    NO_SPECULATIVE_CLEANUP = "no_speculative_cleanup"
    PREFER_EXISTING_HELPERS = "prefer_existing_helpers"
    PREFER_LOCAL_CHANGES = "prefer_local_changes"
    AVOID_GLOBAL_STATE = "avoid_global_state"
    AVOID_CROSS_MODULE_SPILL = "avoid_cross_module_spill"
    NO_SCHEMA_CHANGE_WITHOUT_MIGRATION = "no_schema_change_without_migration"
    NO_BACKWARD_COMPAT_BREAK = "no_backward_compat_break"
    NO_API_SURFACE_GROWTH = "no_api_surface_growth"
    NO_LOGGING_NOISE = "no_logging_noise"
    NO_BEHAVIORAL_SURPRISES = "no_behavioral_surprises"
    NO_PERFORMANCE_REGRESSION = "no_performance_regression"
    NO_SECURITY_REGRESSION = "no_security_regression"
    NO_DEAD_CODE_INTRODUCTION = "no_dead_code_introduction"


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


# Human-readable descriptions for --explain and --show output
TASK_TYPE_DESCRIPTIONS: dict[TaskType, str] = {
    TaskType.BUGFIX: "Fix a defect — minimal change, root cause analysis, targeted tests",
    TaskType.FEATURE: "Add new functionality — design choice, compatibility, tests",
    TaskType.REFACTOR: "Restructure code without changing behavior — interface preservation",
    TaskType.TEST_GENERATION: "Write tests for existing code — coverage, edge cases, fixtures",
    TaskType.DEBUGGING: "Investigate and diagnose a problem — root cause, evidence, next steps",
    TaskType.EXPLANATION: "Understand code — how it works, why it's structured this way",
    TaskType.OPTIMIZATION: "Improve performance — hotspots, allocations, query plans",
    TaskType.MIGRATION: "Move code, schemas, or data — dual-write, rollback, backfill",
    TaskType.CODE_REVIEW: "Audit code quality — issues, severity, suggestions",
    TaskType.ARCHITECTURE: "Analyze or redesign system boundaries — invariants, ownership",
    TaskType.DOCUMENTATION: "Write or update documentation — accuracy, completeness",
    TaskType.CLEANUP: "Remove dead code, unused imports, obsolete TODOs",
    TaskType.SECURITY: "Fix or audit security issues — auth, injection, secrets, OWASP",
    TaskType.PERFORMANCE: "Profile and optimize — latency, throughput, resource usage",
    TaskType.RELIABILITY: "Improve error handling, retries, circuit breakers, idempotency",
    TaskType.OBSERVABILITY: "Add logging, metrics, tracing, alerting",
    TaskType.DEPENDENCY_UPDATE: "Upgrade or replace a dependency",
    TaskType.DATA_MIGRATION: "Migrate stored data — schema changes, backfills, rollbacks",
    TaskType.API_CHANGE: "Modify an API surface — versioning, compatibility, contracts",
    TaskType.CLI_CHANGE: "Modify a CLI interface — flags, output, UX",
    TaskType.CONFIG_CHANGE: "Modify configuration structure or defaults",
    TaskType.BUILD_FIX: "Fix build, CI, packaging, or tooling issues",
    TaskType.RELEASE_SUPPORT: "Prepare, tag, or support a release",
}

MODE_DESCRIPTIONS: dict[Mode, str] = {
    Mode.SURGICAL: "Smallest possible change. Laser-focused. No scope creep.",
    Mode.DEEP: "Broader understanding before action. Thorough context gathering.",
    Mode.FAST: "Token-lean, quick execution. Minimal deliberation.",
    Mode.SAFE: "Conservative changes. Stronger verification. No surprises.",
    Mode.EXPLORE: "Gather options before committing. Compare approaches.",
    Mode.STRICT: "Strong constraint adherence. Explicit assumptions. Guardrails on.",
    Mode.MINIMAL: "Ultra-compact context and output. Bare minimum.",
    Mode.ARCHITECTURAL: "Focus on design boundaries, invariants, ownership.",
    Mode.DEBUG: "Root-cause oriented. Evidence-first. No premature fixes.",
    Mode.REWRITE: "Willing to reshape internals. Higher change scope accepted.",
    Mode.MAINTAIN: "Bias toward repo consistency and low churn.",
}

CONSTRAINT_DESCRIPTIONS: dict[Constraint, str] = {
    Constraint.MINIMAL_DIFF: "Make the smallest possible change that satisfies the goal.",
    Constraint.PRESERVE_PUBLIC_API: "Do not change any public interface or exported symbol.",
    Constraint.NO_UNNECESSARY_ABSTRACTIONS: "No new abstractions unless directly required.",
    Constraint.NO_UNRELATED_REFACTORS: "Do not refactor code outside the task scope.",
    Constraint.FOLLOW_EXISTING_PATTERNS: "Match the patterns already used in this repo.",
    Constraint.PRESERVE_BEHAVIOR: "Do not change observable behavior unless that is the goal.",
    Constraint.MINIMIZE_TOKEN_USAGE: "Keep context and output compact.",
    Constraint.KEEP_FILE_CHURN_LOW: "Avoid touching files that don't need to change.",
    Constraint.AVOID_RENAMES_UNLESS_NEEDED: "Do not rename symbols unless required by the fix.",
    Constraint.AVOID_NEW_DEPENDENCIES: "Do not introduce new packages or libraries.",
    Constraint.REQUIRE_TESTS: "The output must include or reference tests.",
    Constraint.REQUIRE_EXPLANATION: "State what you changed and why.",
    Constraint.REQUIRE_RISK_ANALYSIS: "State what could go wrong.",
    Constraint.NO_GUESSING: "Do not infer facts that aren't supported by evidence.",
    Constraint.NO_SPECULATIVE_CLEANUP: "No opportunistic cleanup or style fixes.",
    Constraint.PREFER_EXISTING_HELPERS: "Use existing utilities before writing new ones.",
    Constraint.PREFER_LOCAL_CHANGES: "Fix at the call site, not globally.",
    Constraint.AVOID_GLOBAL_STATE: "Do not introduce or expand global mutable state.",
    Constraint.AVOID_CROSS_MODULE_SPILL: "Changes should not leak across module boundaries.",
    Constraint.NO_SCHEMA_CHANGE_WITHOUT_MIGRATION: "Schema changes require a migration plan.",
    Constraint.NO_BACKWARD_COMPAT_BREAK: "Do not break existing callers or consumers.",
    Constraint.NO_API_SURFACE_GROWTH: "Do not expand the API surface without clear need.",
    Constraint.NO_LOGGING_NOISE: "Do not add noisy or low-signal log statements.",
    Constraint.NO_BEHAVIORAL_SURPRISES: "The system should behave identically from the outside.",
    Constraint.NO_PERFORMANCE_REGRESSION: "Do not introduce measurable slowdowns.",
    Constraint.NO_SECURITY_REGRESSION: "Do not weaken any security invariant.",
    Constraint.NO_DEAD_CODE_INTRODUCTION: "Do not leave unreachable or unused code.",
}
