"""Deterministic intent classifier — no LLM, pure keyword/pattern scoring."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from .taxonomy import TaskType, SubType, Mode, Constraint, RiskLevel
from .task import Task, ContextBudget, RetrievalPlan, VerificationPlan
from .contracts import get_contract


# ---------------------------------------------------------------------------
# Keyword tables — (pattern, weight) pairs per TaskType
# ---------------------------------------------------------------------------

_TASK_KEYWORDS: dict[TaskType, list[tuple[str, float]]] = {
    TaskType.BUGFIX: [
        (r"\bfix\b", 0.9), (r"\bbug\b", 0.8), (r"\bbroken\b", 0.8), (r"\bcrash\b", 0.8),
        (r"\bfails?\b", 0.7), (r"\berror\b", 0.6), (r"\bwrong\b", 0.5), (r"\bincorrect\b", 0.6),
        (r"\bregression\b", 0.8), (r"\bexception\b", 0.6), (r"\bpanic\b", 0.7),
        (r"\bnot working\b", 0.7), (r"\bissue\b", 0.4), (r"\bdefect\b", 0.7),
    ],
    TaskType.FEATURE: [
        (r"\badd\b", 0.7), (r"\bimplement\b", 0.8), (r"\bcreate\b", 0.6), (r"\bbuild\b", 0.6),
        (r"\bnew\b", 0.5), (r"\bfeature\b", 0.9), (r"\bsupport\b", 0.5), (r"\benable\b", 0.6),
        (r"\ballow\b", 0.5), (r"\bintroduce\b", 0.7), (r"\bextend\b", 0.6),
    ],
    TaskType.REFACTOR: [
        (r"\brefactor\b", 1.0), (r"\bclean(?: up)?\b", 0.6), (r"\bextract\b", 0.7),
        (r"\bsimplify\b", 0.7), (r"\breorganize\b", 0.7), (r"\bmodularize\b", 0.8),
        (r"\bsplit\b", 0.5), (r"\bmove\b", 0.4), (r"\breshape\b", 0.7),
        (r"\bdecouple\b", 0.8), (r"\brename\b", 0.5), (r"\bconsolidate\b", 0.7),
    ],
    TaskType.TEST_GENERATION: [
        (r"\btest\b", 0.8), (r"\bspec\b", 0.7), (r"\bcoverage\b", 0.7), (r"\bassert\b", 0.6),
        (r"\bunit test\b", 0.9), (r"\bintegration test\b", 0.9), (r"\bwrite tests?\b", 0.9),
        (r"\bgenerate tests?\b", 0.9), (r"\badd tests?\b", 0.8),
    ],
    TaskType.DEBUGGING: [
        (r"\bdebug\b", 0.9), (r"\binvestigate\b", 0.8), (r"\bdiagnose\b", 0.9),
        (r"\btrace\b", 0.6), (r"\bwhy\b", 0.5), (r"\bflak[ey]\b", 0.8),
        (r"\bintermittent\b", 0.8), (r"\broot cause\b", 0.9), (r"\bslow\b", 0.4),
    ],
    TaskType.EXPLANATION: [
        (r"\bexplain\b", 0.9), (r"\bwhat (?:does|is)\b", 0.7), (r"\bhow does\b", 0.8),
        (r"\bdescribe\b", 0.7), (r"\bunderstand\b", 0.6), (r"\bwalk me through\b", 0.8),
        (r"\bwhat(?:'s| is) happening\b", 0.7),
    ],
    TaskType.OPTIMIZATION: [
        (r"\boptimize\b", 0.9), (r"\bperformance\b", 0.7), (r"\bslow\b", 0.6),
        (r"\bfast(?:er)?\b", 0.6), (r"\blatency\b", 0.8), (r"\bthroughput\b", 0.8),
        (r"\bcache\b", 0.5), (r"\bspeed up\b", 0.8), (r"\bmemory\b", 0.5),
        (r"\bprofile\b", 0.8), (r"\bbottleneck\b", 0.9),
    ],
    TaskType.MIGRATION: [
        (r"\bmigrat\w*\b", 0.9), (r"\bupgrade\b", 0.6), (r"\bport\b", 0.5),
        (r"\bmove (?:to|from)\b", 0.6), (r"\btransition\b", 0.7), (r"\bbackfill\b", 0.8),
    ],
    TaskType.CODE_REVIEW: [
        (r"\breview\b", 0.9), (r"\baudit\b", 0.8), (r"\bcheck\b", 0.4),
        (r"\binspect\b", 0.6), (r"\blook at\b", 0.4), (r"\bfeedback\b", 0.6),
    ],
    TaskType.SECURITY: [
        (r"\bsecurity\b", 0.9), (r"\bvulnerabilit\w*\b", 0.9), (r"\bauth\w*\b", 0.5),
        (r"\binjection\b", 0.9), (r"\bsecret\b", 0.6), (r"\bexposure\b", 0.7),
        (r"\bpermission\b", 0.5), (r"\bsanitiz\w*\b", 0.7), (r"\bxss\b", 0.9),
        (r"\bsqli\b", 0.9), (r"\bcsrf\b", 0.9),
    ],
    TaskType.PERFORMANCE: [
        (r"\bperformance\b", 0.9), (r"\bprofile\b", 0.8), (r"\bbenchmark\b", 0.8),
        (r"\bp99\b", 0.9), (r"\blatency\b", 0.8), (r"\bthroughput\b", 0.8),
    ],
    TaskType.OBSERVABILITY: [
        (r"\blog(?:ging)?\b", 0.7), (r"\bmetric\b", 0.8), (r"\btrace\b", 0.7),
        (r"\balert\b", 0.7), (r"\bmonitor\b", 0.7), (r"\binstrument\b", 0.8),
        (r"\bdashboard\b", 0.6),
    ],
    TaskType.DOCUMENTATION: [
        (r"\bdoc(?:s|ument)?\b", 0.8), (r"\breadme\b", 0.8), (r"\bcomment\b", 0.5),
        (r"\bdocstring\b", 0.9), (r"\bwrite up\b", 0.6), (r"\bchangelog\b", 0.8),
    ],
    TaskType.CLEANUP: [
        (r"\bclean ?up\b", 0.8), (r"\bdead code\b", 0.9), (r"\bunused\b", 0.7),
        (r"\bobsolete\b", 0.7), (r"\bremove\b", 0.5), (r"\bdelete\b", 0.4),
        (r"\bprune\b", 0.7), (r"\btodo\b", 0.4),
    ],
    TaskType.RELIABILITY: [
        (r"\breliab\w*\b", 0.9), (r"\bretry\b", 0.7), (r"\bcircuit breaker\b", 0.9),
        (r"\bidempoten\w*\b", 0.9), (r"\bfailover\b", 0.8), (r"\bfault toleran\w*\b", 0.9),
        (r"\btimeout\b", 0.6), (r"\berror handling\b", 0.7),
    ],
}

# SubType keyword tables — evaluated within the context of the parent TaskType
_SUBTYPE_KEYWORDS: dict[TaskType, list[tuple[str, SubType, float]]] = {
    TaskType.BUGFIX: [
        (r"\bduplicate\b", SubType.DUPLICATE_EVENT, 1.0),
        (r"\btwice\b", SubType.DUPLICATE_EVENT, 0.9),
        (r"\bdouble\b", SubType.DUPLICATE_EVENT, 0.8),
        (r"\brace\b", SubType.RACE_CONDITION, 1.0),
        (r"\bconcurren\w*\b", SubType.RACE_CONDITION, 0.8),
        (r"\bdeadlock\b", SubType.RACE_CONDITION, 0.9),
        (r"\bnull\b", SubType.NULL_HANDLING, 0.9),
        (r"\bnone\b", SubType.NULL_HANDLING, 0.7),
        (r"\bregression\b", SubType.REGRESSION, 1.0),
        (r"\bbroke after\b", SubType.REGRESSION, 0.9),
        (r"\bstate\b", SubType.INCORRECT_STATE, 0.6),
        (r"\bstale\b", SubType.INCORRECT_STATE, 0.8),
        (r"\bedge case\b", SubType.EDGE_CASE_FAILURE, 0.9),
        (r"\bboundary\b", SubType.EDGE_CASE_FAILURE, 0.7),
    ],
    TaskType.FEATURE: [
        (r"\bendpoint\b", SubType.ENDPOINT, 0.9),
        (r"\broute\b", SubType.ENDPOINT, 0.7),
        (r"\bapi\b", SubType.ENDPOINT, 0.6),
        (r"\bwebhook\b", SubType.WEBHOOK, 1.0),
        (r"\bcache\b", SubType.CACHE_LAYER, 0.8),
        (r"\bcli\b", SubType.CLI_COMMAND, 0.9),
        (r"\bcommand\b", SubType.CLI_COMMAND, 0.6),
        (r"\bjob\b", SubType.BACKGROUND_JOB, 0.7),
        (r"\bworker\b", SubType.BACKGROUND_JOB, 0.8),
        (r"\bqueue\b", SubType.BACKGROUND_JOB, 0.7),
    ],
    TaskType.DEBUGGING: [
        (r"\bflak[ey]\b", SubType.TEST_FLAKE, 1.0),
        (r"\bintermittent\b", SubType.INTERMITTENT_ISSUE, 0.9),
        (r"\bslow\b", SubType.PERF_BOTTLENECK, 0.7),
        (r"\bintegration\b", SubType.INTEGRATION_FAILURE, 0.7),
    ],
}

# Mode keyword table
_MODE_KEYWORDS: list[tuple[str, Mode, float]] = [
    (r"\bsurgical\b", Mode.SURGICAL, 1.0),
    (r"\bminimal\b", Mode.MINIMAL, 0.9),
    (r"\bsmall(est)? (?:change|fix|diff)\b", Mode.SURGICAL, 0.8),
    (r"\bdeep\b", Mode.DEEP, 1.0),
    (r"\bthorough\b", Mode.DEEP, 0.8),
    (r"\bbroader?\b", Mode.DEEP, 0.6),
    (r"\bsafe\b", Mode.SAFE, 1.0),
    (r"\bconservative\b", Mode.SAFE, 0.9),
    (r"\bcareful\b", Mode.SAFE, 0.7),
    (r"\bfast\b", Mode.FAST, 0.8),
    (r"\bquick\b", Mode.FAST, 0.7),
    (r"\bexplore\b", Mode.EXPLORE, 1.0),
    (r"\bstrict\b", Mode.STRICT, 1.0),
    (r"\barchitectur\w*\b", Mode.ARCHITECTURAL, 0.8),
    (r"\bdesign\b", Mode.ARCHITECTURAL, 0.5),
    (r"\brewrite\b", Mode.REWRITE, 1.0),
    (r"\bmaintain\b", Mode.MAINTAIN, 0.9),
    (r"\bpreserve\b", Mode.MAINTAIN, 0.6),
]

# Default modes by task type
_DEFAULT_MODES: dict[TaskType, Mode] = {
    TaskType.BUGFIX: Mode.SURGICAL,
    TaskType.FEATURE: Mode.DEEP,
    TaskType.REFACTOR: Mode.SAFE,
    TaskType.TEST_GENERATION: Mode.SURGICAL,
    TaskType.DEBUGGING: Mode.DEBUG,
    TaskType.EXPLANATION: Mode.DEEP,
    TaskType.OPTIMIZATION: Mode.DEEP,
    TaskType.MIGRATION: Mode.SAFE,
    TaskType.CODE_REVIEW: Mode.STRICT,
    TaskType.ARCHITECTURE: Mode.ARCHITECTURAL,
    TaskType.DOCUMENTATION: Mode.MINIMAL,
    TaskType.CLEANUP: Mode.SURGICAL,
    TaskType.SECURITY: Mode.STRICT,
    TaskType.PERFORMANCE: Mode.DEEP,
    TaskType.RELIABILITY: Mode.SAFE,
    TaskType.OBSERVABILITY: Mode.SURGICAL,
}

# Default constraints by task type
_DEFAULT_CONSTRAINTS: dict[TaskType, list[Constraint]] = {
    TaskType.BUGFIX: [
        Constraint.MINIMAL_DIFF,
        Constraint.PRESERVE_PUBLIC_API,
        Constraint.NO_UNRELATED_REFACTORS,
        Constraint.REQUIRE_TESTS,
        Constraint.REQUIRE_EXPLANATION,
        Constraint.REQUIRE_RISK_ANALYSIS,
        Constraint.FOLLOW_EXISTING_PATTERNS,
        Constraint.NO_SPECULATIVE_CLEANUP,
    ],
    TaskType.FEATURE: [
        Constraint.FOLLOW_EXISTING_PATTERNS,
        Constraint.REQUIRE_TESTS,
        Constraint.REQUIRE_EXPLANATION,
        Constraint.NO_UNNECESSARY_ABSTRACTIONS,
        Constraint.AVOID_NEW_DEPENDENCIES,
    ],
    TaskType.REFACTOR: [
        Constraint.PRESERVE_PUBLIC_API,
        Constraint.PRESERVE_BEHAVIOR,
        Constraint.NO_UNRELATED_REFACTORS,
        Constraint.REQUIRE_TESTS,
        Constraint.REQUIRE_RISK_ANALYSIS,
        Constraint.KEEP_FILE_CHURN_LOW,
        Constraint.FOLLOW_EXISTING_PATTERNS,
    ],
    TaskType.TEST_GENERATION: [
        Constraint.FOLLOW_EXISTING_PATTERNS,
        Constraint.REQUIRE_EXPLANATION,
        Constraint.PREFER_EXISTING_HELPERS,
    ],
    TaskType.DEBUGGING: [
        Constraint.NO_GUESSING,
        Constraint.REQUIRE_EXPLANATION,
        Constraint.REQUIRE_RISK_ANALYSIS,
    ],
    TaskType.EXPLANATION: [
        Constraint.NO_GUESSING,
        Constraint.REQUIRE_EXPLANATION,
    ],
    TaskType.OPTIMIZATION: [
        Constraint.PRESERVE_BEHAVIOR,
        Constraint.NO_PERFORMANCE_REGRESSION,
        Constraint.REQUIRE_EXPLANATION,
        Constraint.REQUIRE_RISK_ANALYSIS,
    ],
    TaskType.MIGRATION: [
        Constraint.NO_BACKWARD_COMPAT_BREAK,
        Constraint.NO_SCHEMA_CHANGE_WITHOUT_MIGRATION,
        Constraint.REQUIRE_EXPLANATION,
        Constraint.REQUIRE_RISK_ANALYSIS,
    ],
    TaskType.CODE_REVIEW: [
        Constraint.NO_GUESSING,
        Constraint.REQUIRE_EXPLANATION,
    ],
    TaskType.SECURITY: [
        Constraint.NO_SECURITY_REGRESSION,
        Constraint.NO_GUESSING,
        Constraint.REQUIRE_EXPLANATION,
        Constraint.REQUIRE_RISK_ANALYSIS,
        Constraint.PRESERVE_BEHAVIOR,
    ],
    TaskType.REFACTOR: [
        Constraint.PRESERVE_PUBLIC_API,
        Constraint.PRESERVE_BEHAVIOR,
        Constraint.NO_UNRELATED_REFACTORS,
        Constraint.REQUIRE_TESTS,
        Constraint.REQUIRE_RISK_ANALYSIS,
        Constraint.KEEP_FILE_CHURN_LOW,
    ],
}

# Extra constraints added by mode
_MODE_EXTRA_CONSTRAINTS: dict[Mode, list[Constraint]] = {
    Mode.SURGICAL: [Constraint.MINIMAL_DIFF, Constraint.NO_GUESSING, Constraint.KEEP_FILE_CHURN_LOW],
    Mode.SAFE: [Constraint.PRESERVE_BEHAVIOR, Constraint.NO_BEHAVIORAL_SURPRISES, Constraint.REQUIRE_RISK_ANALYSIS],
    Mode.STRICT: [Constraint.REQUIRE_EXPLANATION, Constraint.REQUIRE_RISK_ANALYSIS, Constraint.NO_GUESSING],
    Mode.MINIMAL: [Constraint.MINIMIZE_TOKEN_USAGE, Constraint.MINIMAL_DIFF],
    Mode.MAINTAIN: [Constraint.FOLLOW_EXISTING_PATTERNS, Constraint.KEEP_FILE_CHURN_LOW, Constraint.AVOID_RENAMES_UNLESS_NEEDED],
    Mode.REWRITE: [],
}

# Context priorities by task type
_RETRIEVAL_PRIORITIES: dict[TaskType, list[str]] = {
    TaskType.BUGFIX: [
        "recent git diffs near the affected scope",
        "call chains through the failure path",
        "tests around the failure path",
        "related state transitions and side effects",
        "likely regression zones",
    ],
    TaskType.FEATURE: [
        "similar existing implementations in the repo",
        "API contracts and public interfaces",
        "related services and domain models",
        "existing test patterns",
    ],
    TaskType.REFACTOR: [
        "public interfaces and call sites",
        "dependency graph of affected symbols",
        "architecture boundaries",
        "compatibility risks",
    ],
    TaskType.TEST_GENERATION: [
        "source function and its signature",
        "edge cases and failure modes",
        "similar existing tests and fixtures",
        "branch coverage targets",
    ],
    TaskType.DEBUGGING: [
        "logs and stack traces",
        "runtime behavior and state",
        "recent edits near the failure",
        "reproduction steps",
    ],
    TaskType.OPTIMIZATION: [
        "profiling data and hotspots",
        "loops and allocation sites",
        "query plans and contention points",
    ],
    TaskType.MIGRATION: [
        "schema definitions and constraints",
        "dual-write patterns in the repo",
        "rollback and backfill needs",
    ],
    TaskType.CODE_REVIEW: [
        "diff or changed files",
        "related tests",
        "public interfaces touched",
    ],
    TaskType.EXPLANATION: [
        "target code and its immediate callers",
        "data flow through the module",
        "architecture context",
    ],
    TaskType.SECURITY: [
        "affected code paths",
        "input validation and sanitization",
        "auth and permission checks",
    ],
}

_EXCLUDED_CONTEXT: dict[TaskType, list[str]] = {
    TaskType.BUGFIX: ["unrelated modules", "broad architecture docs", "full-file dumps"],
    TaskType.TEST_GENERATION: ["unrelated services", "infrastructure config"],
    TaskType.EXPLANATION: ["implementation details beyond the scope of the question"],
}

# Verification checks by task type
_VERIFICATION_REQUIRED: dict[TaskType, list[str]] = {
    TaskType.BUGFIX: ["targeted regression test", "patch scope sanity", "no behavioral surprise"],
    TaskType.FEATURE: ["new tests pass", "no interface break", "no unrelated churn"],
    TaskType.REFACTOR: ["behavior preserved", "tests still pass", "interface unchanged"],
    TaskType.TEST_GENERATION: ["tests are self-contained", "edge cases covered"],
    TaskType.DEBUGGING: ["reproduction confirmed", "evidence cited"],
    TaskType.MIGRATION: ["rollback plan present", "dual-write if needed", "no data loss path"],
    TaskType.SECURITY: ["attack vector closed", "no new surface exposed"],
}

_VERIFICATION_WARNINGS: dict[TaskType, list[str]] = {
    TaskType.BUGFIX: [">3 files changed", "missing test", "ambiguous assumption", "unrelated rename"],
    TaskType.FEATURE: [">5 files changed", "no test", "new dependency added"],
    TaskType.REFACTOR: ["public API changed", "test deleted", "too many files"],
    TaskType.SECURITY: ["untested code path", "assumption about user input"],
}

# Risk level by task type
_DEFAULT_RISK: dict[TaskType, RiskLevel] = {
    TaskType.BUGFIX: RiskLevel.MEDIUM,
    TaskType.FEATURE: RiskLevel.MEDIUM,
    TaskType.REFACTOR: RiskLevel.MEDIUM,
    TaskType.TEST_GENERATION: RiskLevel.LOW,
    TaskType.DEBUGGING: RiskLevel.LOW,
    TaskType.EXPLANATION: RiskLevel.LOW,
    TaskType.OPTIMIZATION: RiskLevel.MEDIUM,
    TaskType.MIGRATION: RiskLevel.HIGH,
    TaskType.CODE_REVIEW: RiskLevel.LOW,
    TaskType.SECURITY: RiskLevel.HIGH,
    TaskType.DATA_MIGRATION: RiskLevel.CRITICAL,
    TaskType.ARCHITECTURE: RiskLevel.HIGH,
    TaskType.CLEANUP: RiskLevel.LOW,
}


@dataclass
class ClassificationScore:
    task_type: TaskType
    score: float
    evidence: list[str]


@dataclass
class IntentResult:
    task_type: TaskType
    sub_type: Optional[SubType]
    mode: Mode
    scope: Optional[str]
    confidence: float
    evidence: list[str]
    candidates: list[ClassificationScore]  # top alternatives if confidence is low

    @property
    def is_ambiguous(self) -> bool:
        return self.confidence < 0.4


def _tokenize(text: str) -> str:
    return text.lower()


def _score_task_types(text: str) -> list[ClassificationScore]:
    normalized = _tokenize(text)
    scores: dict[TaskType, tuple[float, list[str]]] = {}

    for task_type, patterns in _TASK_KEYWORDS.items():
        total = 0.0
        evidence = []
        for pattern, weight in patterns:
            if re.search(pattern, normalized):
                total += weight
                readable = pattern.replace(r'\b', '').replace(r'\w*', '…')
                evidence.append(f"'{readable}' → {weight:.1f}")
        if total > 0:
            scores[task_type] = (total, evidence)

    if not scores:
        return [ClassificationScore(TaskType.BUGFIX, 0.1, ["no keyword match — defaulting to bugfix"])]

    max_score = max(s for s, _ in scores.values())
    results = [
        ClassificationScore(task_type=tt, score=s / max_score, evidence=ev)
        for tt, (s, ev) in scores.items()
    ]
    return sorted(results, key=lambda x: x.score, reverse=True)


def _detect_subtype(text: str, task_type: TaskType) -> Optional[SubType]:
    normalized = _tokenize(text)
    patterns = _SUBTYPE_KEYWORDS.get(task_type, [])
    best: Optional[tuple[float, SubType]] = None
    for pattern, subtype, weight in patterns:
        if re.search(pattern, normalized):
            if best is None or weight > best[0]:
                best = (weight, subtype)
    return best[1] if best else None


def _detect_mode_from_text(text: str) -> Optional[Mode]:
    normalized = _tokenize(text)
    best: Optional[tuple[float, Mode]] = None
    for pattern, mode, weight in _MODE_KEYWORDS:
        if re.search(pattern, normalized):
            if best is None or weight > best[0]:
                best = (weight, mode)
    return best[1] if best else None


def _extract_scope(text: str) -> Optional[str]:
    """Extract a scope hint from quoted text or 'in X' / 'for X' patterns."""
    quoted = re.findall(r'"([^"]+)"', text)
    if quoted:
        return quoted[0]
    in_for = re.search(r'\b(?:in|for|scope|module|service|package)\s+(?:the\s+)?([a-zA-Z_][a-zA-Z0-9_. /-]+)', text)
    if in_for:
        return in_for.group(1).strip()
    return None


def _build_constraints(task_type: TaskType, mode: Mode, extra: list[Constraint]) -> list[Constraint]:
    base = list(_DEFAULT_CONSTRAINTS.get(task_type, []))
    mode_extras = _MODE_EXTRA_CONSTRAINTS.get(mode, [])
    seen: set[Constraint] = set()
    result = []
    for c in base + mode_extras + extra:
        if c not in seen:
            seen.add(c)
            result.append(c)
    return result


def _build_retrieval_plan(task_type: TaskType, raw_intent: str, scope: Optional[str]) -> RetrievalPlan:
    query = scope or raw_intent
    priorities = _RETRIEVAL_PRIORITIES.get(task_type, ["relevant code context"])
    excluded = _EXCLUDED_CONTEXT.get(task_type, [])
    return RetrievalPlan(
        query=query,
        priority_categories=priorities,
        excluded_targets=excluded,
        git_history=task_type in (TaskType.BUGFIX, TaskType.DEBUGGING, TaskType.MIGRATION),
        include_call_chains=task_type in (TaskType.BUGFIX, TaskType.REFACTOR, TaskType.OPTIMIZATION),
    )


def _build_verification_plan(task_type: TaskType) -> VerificationPlan:
    return VerificationPlan(
        required_checks=_VERIFICATION_REQUIRED.get(task_type, ["output contract compliance"]),
        optional_checks=["style conformance", "token budget"],
        warning_conditions=_VERIFICATION_WARNINGS.get(task_type, ["scope exceeded"]),
        acceptance_criteria=[f"output matches {task_type.value} contract"],
    )


def classify(
    raw_intent: str,
    hint_task_type: Optional[TaskType] = None,
    hint_mode: Optional[Mode] = None,
    hint_scope: Optional[str] = None,
    extra_constraints: Optional[list[Constraint]] = None,
) -> IntentResult:
    """Classify developer intent into a typed IntentResult. No LLM involved."""
    scores = _score_task_types(raw_intent)

    if hint_task_type:
        task_type = hint_task_type
        confidence = 1.0
        evidence = [f"task_type forced by CLI verb: {hint_task_type.value}"]
        best_score = next((s for s in scores if s.task_type == task_type), None)
        if best_score:
            evidence += best_score.evidence
    else:
        top = scores[0]
        task_type = top.task_type
        confidence = min(top.score, 1.0)
        evidence = top.evidence

    sub_type = _detect_subtype(raw_intent, task_type)

    mode_from_text = _detect_mode_from_text(raw_intent)
    mode = hint_mode or mode_from_text or _DEFAULT_MODES.get(task_type, Mode.SURGICAL)
    if mode_from_text and not hint_mode:
        evidence.append(f"mode '{mode.value}' detected in text")
    elif hint_mode:
        evidence.append(f"mode '{mode.value}' set by flag")
    else:
        evidence.append(f"mode '{mode.value}' is default for {task_type.value}")

    scope = hint_scope or _extract_scope(raw_intent)

    return IntentResult(
        task_type=task_type,
        sub_type=sub_type,
        mode=mode,
        scope=scope,
        confidence=confidence,
        evidence=evidence,
        candidates=scores[:3],
    )


def build_task(
    raw_intent: str,
    hint_task_type: Optional[TaskType] = None,
    hint_mode: Optional[Mode] = None,
    hint_scope: Optional[str] = None,
    extra_constraints: Optional[list[Constraint]] = None,
    preserve_api: bool = False,
    no_tests: bool = False,
) -> Task:
    """Build a fully populated Task from raw developer intent."""
    intent = classify(
        raw_intent,
        hint_task_type=hint_task_type,
        hint_mode=hint_mode,
        hint_scope=hint_scope,
    )

    forced_extras = list(extra_constraints or [])
    if preserve_api:
        forced_extras.append(Constraint.PRESERVE_PUBLIC_API)

    constraints = _build_constraints(intent.task_type, intent.mode, forced_extras)

    if no_tests and Constraint.REQUIRE_TESTS in constraints:
        constraints.remove(Constraint.REQUIRE_TESTS)

    budget = ContextBudget().scale_for_mode(intent.mode)
    retrieval_plan = _build_retrieval_plan(intent.task_type, raw_intent, intent.scope)
    verification_plan = _build_verification_plan(intent.task_type)

    return Task(
        raw_intent=raw_intent,
        task_type=intent.task_type,
        sub_type=intent.sub_type,
        mode=intent.mode,
        scope=intent.scope,
        constraints=constraints,
        risk_level=_DEFAULT_RISK.get(intent.task_type, RiskLevel.MEDIUM),
        confidence=intent.confidence,
        classification_evidence=intent.evidence,
        output_contract=get_contract(intent.task_type),
        retrieval_plan=retrieval_plan,
        context_budget=budget,
        verification_plan=verification_plan,
    )
