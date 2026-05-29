"""ai — deterministic prompt engine CLI."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

import typer
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .compiler import compile_task
from .config import EngineConfig, load_config, write_default_config
from .contracts import get_contract
from .intent import IntentResult, build_task, classify
from .policy import build_registry
from .retrieval import ContextBundle, retrieve
from .presets import (
    CLI_VERB_ALIASES,
    get_preset,
    get_profile,
    list_presets,
    list_profiles,
)
from .task import Task
from .taxonomy import (
    CONSTRAINT_DESCRIPTIONS,
    MODE_DESCRIPTIONS,
    TASK_TYPE_DESCRIPTIONS,
    Constraint,
    Mode,
    TaskType,
)

app = typer.Typer(
    help=(
        "Deterministic prompt engine — compile developer intent into structured AI instructions.\n\n"
        "The engine classifies your natural-language goal, pulls relevant symbols from the repo\n"
        "index (via repo-index), enforces task-appropriate constraints, and emits a structured,\n"
        "budget-capped prompt. No LLM is invoked by the engine itself.\n\n"
        "Quick start:\n\n"
        "  ai fix  'null pointer in UserService.getById when id is 0'\n"
        "  ai feat 'add rate limiting to the /auth/token endpoint'\n"
        "  ai run  'the search returns stale results after reindex'\n\n"
        "Most useful flags:\n\n"
        "  --explain    Show task plan: classification, context pulled, constraints active\n"
        "  --dry-run    Show the fully compiled prompt (all blocks assembled)\n"
        "  --compact    Print the raw prompt string — pipe to clipboard or LLM\n"
        "  --preset     Apply a named config  (run 'ai show presets' for the full list)\n"
        "  --mode       Override the reasoning mode  (run 'ai show modes' for the full list)\n\n"
        "Discovery:\n\n"
        "  ai show tasks        All task types and descriptions\n"
        "  ai show modes        All reasoning modes\n"
        "  ai show presets      All named presets\n"
        "  ai show profiles     All execution profiles\n"
        "  ai show constraints  All constraints and their meaning\n"
        "  ai show policy       Active universal rules + any repo-local policy"
    ),
    add_completion=True,
    no_args_is_help=True,
)
show_app = typer.Typer(
    help=(
        "Discover task types, modes, constraints, presets, profiles, and active policy.\n\n"
        "Commands:\n\n"
        "  ai show tasks        Full list of task types with descriptions\n"
        "  ai show task <name>  Default mode, constraints, and output contract for one type\n"
        "  ai show modes        All reasoning modes and what they change\n"
        "  ai show constraints  Every constraint and its meaning\n"
        "  ai show presets      Named configurations (bugfix/safe, refactor/compatibility, ...)\n"
        "  ai show profiles     Cross-cutting execution profiles (fast, strict, architectural, ...)\n"
        "  ai show policy       Universal rules always active + any repo-local policy"
    ),
    no_args_is_help=True,
)
app.add_typer(show_app, name="show")

console = Console()
err = Console(stderr=True)

# ---------------------------------------------------------------------------
# Shared flag definitions
# ---------------------------------------------------------------------------

_MODE_HELP = (
    "Reasoning mode — controls context depth, constraints, and output verbosity.\n"
    "Values:\n"
    "  surgical     Smallest possible change, minimal context  (default for fix, ref, clean)\n"
    "  deep         Full context gathering, second-order effects  (default for feat, opt)\n"
    "  fast         Compact output, reduced context  (skips optional contract fields)\n"
    "  safe         Conservative changes, strong verification, flag every risk\n"
    "  explore      Present 2-3 candidate approaches before committing\n"
    "  strict       Explicit assumptions, verbose output, guardrails on\n"
    "  minimal      Ultra-compact — bare minimum context and output\n"
    "  architectural  Design-boundary and invariant focus\n"
    "  debug        Root-cause first, evidence-driven  (default for 'ai debug')\n"
    "  rewrite      Free to reshape internals; higher change scope accepted\n"
    "  maintain     Bias toward repo consistency and low churn"
)
_SCOPE_HELP = (
    "Scope hint — module, service, or file name.\n"
    "Guides the symbol retrieval query and helps the classifier narrow context.\n"
    "Examples: --scope payments  --scope 'auth middleware'  --scope user_service.py"
)
_PRESET_HELP = (
    "Named preset bundling task type + mode + extra constraints.\n"
    "Examples: bugfix/minimal  bugfix/safe  bugfix/deep  refactor/safe\n"
    "         refactor/compatibility  test/coverage-first  security/strict\n"
    "         migration/careful  review/strict  feature/surgical\n"
    "Run 'ai show presets' for the full list."
)
_PROFILE_HELP = (
    "Execution profile applied on top of the task type.\n"
    "Values: fast | balanced | strict | architectural | experimental\n"
    "Run 'ai show profiles' for descriptions."
)


def _parse_mode(value: Optional[str]) -> Optional[Mode]:
    if not value:
        return None
    try:
        return Mode(value.lower())
    except ValueError:
        err.print(f"[red]Unknown mode:[/red] {value!r}  (run 'ai show modes' to list them)")
        raise typer.Exit(1)


def _load_cfg() -> EngineConfig:
    return load_config(Path.cwd())


# ---------------------------------------------------------------------------
# _render_plan — rich output for explain/dry-run
# ---------------------------------------------------------------------------

def _render_plan(
    task: Task,
    intent: IntentResult,
    dry_run: bool = False,
    bundle: ContextBundle | None = None,
) -> None:
    from .budget import compression_summary
    from .compiler import compile_task

    plan = compile_task(task, bundle=bundle)
    cfg = _load_cfg()

    # Task plan panel
    t = Table.grid(padding=(0, 2))
    t.add_column(style="dim", justify="right")
    t.add_column()
    t.add_row("Intent", f'[cyan]"{task.raw_intent}"[/cyan]')
    t.add_row("Task type", f"[bold]{task.task_type.value}[/bold]")
    if task.sub_type:
        t.add_row("Subtype", task.sub_type.value)
    t.add_row("Mode", f"[magenta]{task.mode.value}[/magenta]")
    t.add_row("Risk", task.risk_level.value)
    conf_color = "green" if task.confidence >= 0.7 else "yellow" if task.confidence >= 0.4 else "red"
    t.add_row("Confidence", f"[{conf_color}]{task.confidence:.2f}[/{conf_color}]")
    if task.scope:
        t.add_row("Scope", task.scope)
    console.print(Panel(t, title="[bold]Task Plan[/bold]", border_style="cyan"))

    # Classification evidence
    if intent.evidence:
        ev_lines = "\n".join(f"  • {e}" for e in intent.evidence)
        console.print(Panel(ev_lines, title="[bold]Classification Evidence[/bold]", border_style="dim"))

    # Constraints
    if task.constraints:
        ct = Table(box=box.SIMPLE, show_header=False, padding=(0, 1))
        ct.add_column(style="green", width=32)
        ct.add_column(style="dim")
        for c in task.constraints:
            desc = CONSTRAINT_DESCRIPTIONS.get(c, "")
            ct.add_row(f"✓ {c.value}", desc)
        console.print(Panel(ct, title=f"[bold]Constraints ({len(task.constraints)})[/bold]", border_style="yellow"))

    # Context plan — show retrieval results if available, otherwise show plan
    if bundle is not None and not bundle.is_empty:
        lines = [f"[green]✓ {bundle.symbol_count} symbol(s) retrieved[/green]"]
        for sym in bundle.symbols:
            lines.append(f"  [cyan]{sym.name}[/cyan]  [{sym.kind}]  [dim]{sym.file_path}:{sym.start_line}–{sym.end_line}[/dim]")
            if sym.calls:
                lines.append(f"    calls: [dim]{', '.join(sym.calls[:5])}[/dim]")
            if sym.called_by:
                lines.append(f"    called_by: [dim]{', '.join(sym.called_by[:5])}[/dim]")
        if bundle.git_diff:
            lines.append(f"\n  [dim]{bundle.git_diff}[/dim]")
        for note in bundle.retrieval_notes:
            lines.append(f"  [dim]note: {note}[/dim]")
        console.print(Panel("\n".join(lines), title=f"[bold]Context — Retrieved ({bundle.token_estimate} tokens)[/bold]", border_style="green"))
    elif bundle is not None and bundle.is_empty:
        notes_text = "\n".join(f"  [yellow]• {n}[/yellow]" for n in bundle.retrieval_notes)
        console.print(Panel(notes_text or "  No context retrieved.", title="[bold]Context — No Results[/bold]", border_style="yellow"))
    elif task.retrieval_plan:
        rp = task.retrieval_plan
        rp_lines = "\n".join(rp.describe())
        console.print(Panel(rp_lines, title="[bold]Context Plan (not yet retrieved)[/bold]", border_style="blue"))

    # Output contract
    contract = get_contract(task.task_type)
    ct2 = Table(box=box.SIMPLE, show_header=False, padding=(0, 1))
    ct2.add_column(style="cyan", width=24)
    ct2.add_column(style="dim")
    for f in contract.fields:
        req = "" if f.required else " [dim](optional)[/dim]"
        ct2.add_row(f.name + req, f.description)
    console.print(Panel(ct2, title=f"[bold]Output Contract: {task.task_type.value}[/bold]", border_style="magenta"))

    # Verification
    if task.verification_plan:
        vp = task.verification_plan
        vp_lines = "\n".join(task.verification_plan.describe())
        console.print(Panel(vp_lines, title="[bold]Verification Plan[/bold]", border_style="red"))

    # Token budget
    budget_lines = "\n".join(compression_summary(plan))
    console.print(Panel(budget_lines, title="[bold]Token Budget[/bold]", border_style="dim"))

    # Ambiguity warning
    if intent.is_ambiguous and len(intent.candidates) > 1:
        alts = ", ".join(f"{c.task_type.value} ({c.score:.2f})" for c in intent.candidates[1:3])
        console.print(f"\n[yellow]⚠ Low confidence ({task.confidence:.2f}). Alternatives: {alts}[/yellow]")
        console.print("  Use [bold]--type[/bold] to force a task type if classification is wrong.")

    if dry_run:
        console.print("\n[dim]─── Compiled prompt (dry run) ───[/dim]\n")
        console.print(plan.compile())


# ---------------------------------------------------------------------------
# Generic task runner
# ---------------------------------------------------------------------------

def _run_task(
    goal: str,
    task_type_hint: Optional[TaskType],
    mode_str: Optional[str],
    scope: Optional[str],
    preset_name: Optional[str],
    profile_name: Optional[str],
    preserve_api: bool,
    no_tests: bool,
    dry_run: bool,
    explain: bool,
    compact: bool,
    strict: bool,
    safe_flag: bool,
    no_retrieve: bool = False,
) -> None:
    cfg = _load_cfg()

    mode_val: Optional[Mode] = None

    if preset_name:
        preset = get_preset(preset_name)
        if not preset:
            err.print(f"[red]Unknown preset:[/red] {preset_name!r}  (run 'ai show presets' to list)")
            raise typer.Exit(1)
        task_type_hint = task_type_hint or preset.task_type
        mode_val = mode_val or preset.mode

    if profile_name:
        profile = get_profile(profile_name)
        if not profile:
            err.print(f"[red]Unknown profile:[/red] {profile_name!r}  (run 'ai show profiles' to list)")
            raise typer.Exit(1)
        if profile.mode_override and not mode_val:
            mode_val = profile.mode_override

    if safe_flag:
        mode_val = mode_val or Mode.SAFE
    if strict:
        mode_val = mode_val or Mode.STRICT

    mode_val = _parse_mode(mode_str) or mode_val

    intent = classify(
        goal,
        hint_task_type=task_type_hint,
        hint_mode=mode_val,
        hint_scope=scope,
    )

    task = build_task(
        raw_intent=goal,
        hint_task_type=task_type_hint,
        hint_mode=mode_val,
        hint_scope=scope,
        preserve_api=preserve_api,
        no_tests=no_tests,
    )

    # Retrieve context from repo-index unless explicitly skipped
    bundle: ContextBundle | None = None
    if not no_retrieve and task.retrieval_plan and task.context_budget:
        bundle = retrieve(
            plan=task.retrieval_plan,
            budget=task.context_budget,
            repo_root=Path.cwd(),
        )

    if explain or dry_run:
        _render_plan(task, intent, dry_run=dry_run, bundle=bundle)
        return

    if compact:
        _print_compact(task, bundle)
        return

    _render_plan(task, intent, dry_run=True, bundle=bundle)


def _print_compact(task: Task, bundle: ContextBundle | None = None) -> None:
    from .compiler import compile_task
    plan = compile_task(task, bundle=bundle)
    console.print(plan.compile())


# ---------------------------------------------------------------------------
# Shared options factory
# ---------------------------------------------------------------------------

def _common_opts(func):
    """Decorator that adds shared options to a command function."""
    import functools

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        return func(*args, **kwargs)

    return wrapper


# ---------------------------------------------------------------------------
# Task commands
# ---------------------------------------------------------------------------

_TASK_COMMAND_KWARGS = dict(no_args_is_help=True)


def _make_task_command(task_type: TaskType, name: str, help_text: str):
    @app.command(name=name, help=help_text)
    def _cmd(
        goal: str = typer.Argument(..., help="What to accomplish (natural language)"),
        mode: Optional[str] = typer.Option(None, "--mode", "-m", help=_MODE_HELP),
        scope: Optional[str] = typer.Option(None, "--scope", "-s", help=_SCOPE_HELP),
        preset: Optional[str] = typer.Option(None, "--preset", help=_PRESET_HELP),
        profile: Optional[str] = typer.Option(None, "--profile", help=_PROFILE_HELP),
        preserve_api: bool = typer.Option(False, "--preserve-api", help="Enforce that no public interface or exported symbol is changed (adds preserve_public_api constraint)."),
        no_tests: bool = typer.Option(False, "--no-tests", help="Allow output without tests — removes the require_tests constraint."),
        dry_run: bool = typer.Option(False, "--dry-run", help="Print the fully compiled prompt (all blocks: system, task, constraints, context, contract, verification). Does not call any LLM."),
        explain: bool = typer.Option(False, "--explain", help="Show task plan only: classification evidence, confidence, constraints, retrieved symbols, output contract. Does not print the compiled prompt."),
        compact: bool = typer.Option(False, "--compact", help="Print only the raw compiled prompt string — useful for piping to a clipboard tool or LLM CLI."),
        strict: bool = typer.Option(False, "--strict", help="Apply strict mode — explicit assumptions, verbose output, no guessing. Shortcut for --mode strict."),
        safe: bool = typer.Option(False, "--safe", help="Apply safe mode — conservative changes, flag every risk. Shortcut for --mode safe."),
        no_retrieve: bool = typer.Option(False, "--no-retrieve", help="Skip the repo-index symbol lookup. Useful when the index is stale, unavailable, or you want to provide context manually in the prompt."),
    ) -> None:
        _run_task(
            goal=goal,
            task_type_hint=task_type,
            mode_str=mode,
            scope=scope,
            preset_name=preset,
            profile_name=profile,
            preserve_api=preserve_api,
            no_tests=no_tests,
            dry_run=dry_run,
            explain=explain,
            compact=compact,
            strict=strict,
            safe_flag=safe,
            no_retrieve=no_retrieve,
        )

    _cmd.__name__ = f"cmd_{name}"
    return _cmd


# Register verb commands
_make_task_command(TaskType.BUGFIX, "fix",
    "Fix a bug — minimal patch, root cause, regression test.\n\n"
    "Default mode: surgical  |  Risk: medium\n"
    "Default constraints: minimal_diff, preserve_public_api, no_unrelated_refactors,\n"
    "  require_tests, require_risk_analysis, follow_existing_patterns\n"
    "Output contract fields: symptom, root_cause, trigger, affected_code_paths,\n"
    "  fix_strategy, patch, tests, regression_risks\n\n"
    "Presets: bugfix/minimal  bugfix/safe  bugfix/deep\n\n"
    "Examples:\n"
    "  ai fix 'null pointer in UserService.getById when id is 0'\n"
    "  ai fix 'payment double-charge on retry' --preset bugfix/safe\n"
    "  ai fix 'race condition in session cache' --mode deep --explain\n"
    "  ai fix 'auth regression in v2.3' --scope auth --dry-run"
)
_make_task_command(TaskType.FEATURE, "feat",
    "Implement a new feature — design decision, tests, compatibility notes.\n\n"
    "Default mode: deep  |  Risk: medium\n"
    "Default constraints: follow_existing_patterns, require_tests,\n"
    "  no_unnecessary_abstractions, avoid_new_dependencies\n"
    "Output contract fields: goal, design_choice, affected_interfaces, patch,\n"
    "  tests, compatibility_notes, risks\n\n"
    "Presets: feature/surgical  feature/default\n\n"
    "Examples:\n"
    "  ai feat 'add rate limiting to the /auth/token endpoint'\n"
    "  ai feat 'webhook delivery retry with exponential backoff' --preset feature/surgical\n"
    "  ai feat 'background job for stale session cleanup' --scope session --mode deep\n"
    "  ai feat 'add --verbose flag to the build command' --preserve-api"
)
_make_task_command(TaskType.REFACTOR, "ref",
    "Refactor code without changing observable behavior.\n\n"
    "Default mode: safe  |  Risk: medium\n"
    "Default constraints: preserve_public_api, preserve_behavior, no_unrelated_refactors,\n"
    "  require_tests, require_risk_analysis, keep_file_churn_low\n"
    "Output contract fields: current_shape, target_shape, migration_path, patch,\n"
    "  compatibility, risk_analysis, tests\n\n"
    "Presets: refactor/safe  refactor/compatibility\n\n"
    "Examples:\n"
    "  ai ref 'extract payment logic from OrderService into PaymentService'\n"
    "  ai ref 'simplify the retrieval pipeline into a single fetch() call'\n"
    "  ai ref 'decouple auth middleware from route handlers' --preset refactor/compatibility\n"
    "  ai ref 'consolidate the three DB helpers into db_utils' --scope db --mode safe"
)
_make_task_command(TaskType.TEST_GENERATION, "test",
    "Generate tests for a function or module — coverage plan, fixtures, edge cases.\n\n"
    "Default mode: surgical  |  Risk: low\n"
    "Default constraints: follow_existing_patterns, require_explanation,\n"
    "  prefer_existing_helpers\n"
    "Output contract fields: coverage_plan, fixtures, tests, gaps (optional)\n\n"
    "Presets: test/coverage-first\n\n"
    "Examples:\n"
    "  ai test 'generate tests for the retrieval bridge'\n"
    "  ai test 'write unit tests for search_symbols_ranked' --scope repo_index\n"
    "  ai test 'integration tests for the /auth/token endpoint' --preset test/coverage-first\n"
    "  ai test 'edge cases for _trim() in retrieval.py' --no-retrieve"
)
_make_task_command(TaskType.DEBUGGING, "debug",
    "Investigate and diagnose a problem — evidence-first, root cause, next steps.\n\n"
    "Default mode: debug  |  Risk: low\n"
    "Default constraints: no_guessing, require_explanation, require_risk_analysis\n"
    "Output contract fields: reproduction, evidence, likely_cause, uncertainty,\n"
    "  next_steps, patch_if_applicable (optional)\n\n"
    "Presets: debug/deep\n\n"
    "Examples:\n"
    "  ai debug 'flaky timeout in the websocket handler'\n"
    "  ai debug 'intermittent 500 on /api/search — only under concurrent load'\n"
    "  ai debug 'why does the graph cache miss on every second call?' --scope graph\n"
    "  ai debug 'deadlock in session store under high write concurrency' --preset debug/deep"
)
_make_task_command(TaskType.EXPLANATION, "explain",
    "Explain how code works — summary, key concepts, data flow, gotchas.\n\n"
    "Default mode: deep  |  Risk: low\n"
    "Default constraints: no_guessing, require_explanation\n"
    "Output contract fields: summary, key_concepts, data_flow, invariants (opt), gotchas (opt)\n\n"
    "Examples:\n"
    "  ai explain 'how does the composite ranking score work'\n"
    "  ai explain 'what does build_call_graph_cached do and why is it keyed by id(conn)'\n"
    "  ai explain 'walk me through the prompt compilation pipeline'\n"
    "  ai explain 'how does _resolve_db pick which .db file to open' --scope retrieval"
)
_make_task_command(TaskType.OPTIMIZATION, "opt",
    "Optimize for performance — identify bottleneck, measure, patch, state trade-offs.\n\n"
    "Default mode: deep  |  Risk: medium\n"
    "Default constraints: preserve_behavior, no_performance_regression,\n"
    "  require_explanation, require_risk_analysis\n"
    "Output contract fields: bottleneck, evidence, fix_strategy, patch,\n"
    "  expected_gain, risks\n\n"
    "Examples:\n"
    "  ai opt 'reduce allocations in the hot path of search_symbols_ranked'\n"
    "  ai opt 'the FTS5 query is slow on large indexes' --scope db\n"
    "  ai opt 'build_call_graph rebuilds on every MCP call' --mode surgical\n"
    "  ai opt 'retrieval bridge is hitting the DB 7x per task' --preset debug/deep"
)
_make_task_command(TaskType.MIGRATION, "migrate",
    "Plan a migration — dual-write strategy, rollback plan, backfill, risk analysis.\n\n"
    "Default mode: safe  |  Risk: high\n"
    "Default constraints: no_backward_compat_break, no_schema_change_without_migration,\n"
    "  require_explanation, require_risk_analysis\n"
    "Output contract fields: scope, compatibility_constraints, migration_steps,\n"
    "  rollback_plan, backfill_needs, risks, patch\n\n"
    "Presets: migration/careful\n\n"
    "Examples:\n"
    "  ai migrate 'move from SQLite FTS4 to FTS5'\n"
    "  ai migrate 'rename repo_root column in meta table' --preset migration/careful\n"
    "  ai migrate 'move from FastMCP 0.x to 1.x API' --scope mcp_server\n"
    "  ai migrate 'replace the per-connection graph cache with a module-level LRU'"
)
_make_task_command(TaskType.CODE_REVIEW, "review",
    "Review code for issues — severity-ranked findings, rationale, suggested fixes.\n\n"
    "Default mode: strict  |  Risk: low\n"
    "Default constraints: no_guessing, require_explanation\n"
    "Output contract fields: issues_found, severity_summary, rationale,\n"
    "  suggested_changes, non_issues, confidence\n\n"
    "Presets: review/strict\n\n"
    "Examples:\n"
    "  ai review 'check the new FTS5 migration for safety'\n"
    "  ai review 'audit the MCP server tools for input validation'\n"
    "  ai review 'look at the graph cache changes before merging' --preset review/strict\n"
    "  ai review 'check the new /auth endpoint for security issues' --scope auth"
)
_make_task_command(TaskType.SECURITY, "secure",
    "Fix or audit a security issue — attack vector, patch, verification.\n\n"
    "Default mode: strict  |  Risk: high\n"
    "Default constraints: no_security_regression, no_guessing, require_explanation,\n"
    "  require_risk_analysis, preserve_behavior\n"
    "Output contract fields: vulnerability, attack_vector, affected_paths,\n"
    "  fix_strategy, patch, verification, related_risks (optional)\n\n"
    "Presets: security/strict\n\n"
    "Examples:\n"
    "  ai secure 'SQL injection in the symbol search query'\n"
    "  ai secure 'JWT secret is logged in debug output'\n"
    "  ai secure 'audit input validation on all MCP tool parameters' --preset security/strict\n"
    "  ai secure 'path traversal in repo_path parameter of open_connection_for' --scope mcp"
)
_make_task_command(TaskType.CLEANUP, "clean",
    "Remove dead code, unused imports, stale TODOs, and obsolete patterns.\n\n"
    "Default mode: surgical  |  Risk: low\n"
    "Default constraints: follow_existing_patterns, no_speculative_cleanup\n"
    "Output contract fields: summary, changes, rationale, risks\n\n"
    "Examples:\n"
    "  ai clean 'remove dead code in the indexer module'\n"
    "  ai clean 'delete unused imports across the prompt_engine package'\n"
    "  ai clean 'clear stale TODO comments in retrieval.py' --scope retrieval\n"
    "  ai clean 'remove the legacy _graph_cache fallback after the new cache landed'"
)
_make_task_command(TaskType.OBSERVABILITY, "observe",
    "Add logging, metrics, tracing, or alerting — structured, low-noise, meaningful.\n\n"
    "Default mode: surgical  |  Risk: low\n"
    "Default constraints: no_logging_noise, follow_existing_patterns\n"
    "Output contract fields: summary, changes, rationale, risks\n\n"
    "Examples:\n"
    "  ai observe 'add structured logging to the MCP server tools'\n"
    "  ai observe 'instrument retrieve() with latency and symbol-count metrics'\n"
    "  ai observe 'add a warning log when the graph cache is rebuilt' --scope graph\n"
    "  ai observe 'log retrieval notes at DEBUG level in the prompt engine'"
)


# ---------------------------------------------------------------------------
# Generic `ai run` — natural language without a verb
# ---------------------------------------------------------------------------

@app.command(name="run", help=(
    "Run any task — task type inferred automatically from the goal text.\n\n"
    "The classifier scores your goal against keyword tables for all task types and picks\n"
    "the highest match. Use --explain to see the score and evidence. Use --type to override\n"
    "if classification is wrong.\n\n"
    "Use a verb command (fix, feat, ref, ...) when you know the task type — it gives better\n"
    "defaults and a more specific output contract. Use 'ai run' for ambiguous or compound goals.\n\n"
    "Examples:\n"
    "  ai run 'the payment webhook is firing twice'\n"
    "  ai run 'add caching to the search endpoint' --type feat --scope search\n"
    "  ai run 'slow query on user listing' --type opt --mode deep\n"
    "  ai run 'auth middleware needs rate limiting and better logging' --explain\n\n"
    "Valid --type values: bugfix, feature, refactor, test_generation, debugging, explanation,\n"
    "  optimization, migration, code_review, security, cleanup, observability, performance,\n"
    "  reliability, architecture, documentation  (run 'ai show tasks' for the full list)"
))
def cmd_run(
    goal: str = typer.Argument(..., help="Natural language intent"),
    task_type: Optional[str] = typer.Option(None, "--type", "-t", help="Force task type"),
    mode: Optional[str] = typer.Option(None, "--mode", "-m", help=_MODE_HELP),
    scope: Optional[str] = typer.Option(None, "--scope", "-s", help=_SCOPE_HELP),
    preset: Optional[str] = typer.Option(None, "--preset", help=_PRESET_HELP),
    profile: Optional[str] = typer.Option(None, "--profile", help=_PROFILE_HELP),
    preserve_api: bool = typer.Option(False, "--preserve-api"),
    no_tests: bool = typer.Option(False, "--no-tests"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    explain: bool = typer.Option(False, "--explain"),
    compact: bool = typer.Option(False, "--compact"),
    strict: bool = typer.Option(False, "--strict"),
    safe: bool = typer.Option(False, "--safe"),
    no_retrieve: bool = typer.Option(False, "--no-retrieve", help="Skip the repo-index symbol lookup. Useful when the index is stale, unavailable, or you want to supply context manually."),
) -> None:
    hint: Optional[TaskType] = None
    if task_type:
        mapped = CLI_VERB_ALIASES.get(task_type.lower())
        if mapped:
            hint = mapped
        else:
            try:
                hint = TaskType(task_type.lower())
            except ValueError:
                err.print(f"[red]Unknown task type:[/red] {task_type!r}  (run 'ai show tasks' to list)")
                raise typer.Exit(1)
    _run_task(
        goal=goal,
        task_type_hint=hint,
        mode_str=mode,
        scope=scope,
        preset_name=preset,
        profile_name=profile,
        preserve_api=preserve_api,
        no_tests=no_tests,
        dry_run=dry_run,
        explain=explain,
        compact=compact,
        strict=strict,
        safe_flag=safe,
        no_retrieve=no_retrieve,
    )


# ---------------------------------------------------------------------------
# Diagnostic commands
# ---------------------------------------------------------------------------

@app.command(name="plan", help=(
    "Show the task plan for a goal — classification evidence, confidence, constraints,\n"
    "retrieved context, output contract, and token budget. Does not print the compiled prompt.\n\n"
    "Use this to verify the engine classified your intent correctly before running a full task.\n"
    "For the compiled prompt, use 'ai inspect' or add --dry-run to any verb command.\n\n"
    "Examples:\n"
    "  ai plan 'refactor the payment service'\n"
    "  ai plan 'add rate limiting to auth' --type feat --scope auth\n"
    "  ai plan 'race condition in session store' --type bugfix --mode deep"
))
def cmd_plan(
    goal: str = typer.Argument(...),
    task_type: Optional[str] = typer.Option(None, "--type", "-t"),
    mode: Optional[str] = typer.Option(None, "--mode", "-m"),
    scope: Optional[str] = typer.Option(None, "--scope", "-s"),
    preset: Optional[str] = typer.Option(None, "--preset"),
) -> None:
    hint = CLI_VERB_ALIASES.get((task_type or "").lower())
    m = _parse_mode(mode)
    intent = classify(goal, hint_task_type=hint, hint_mode=m, hint_scope=scope)
    task = build_task(goal, hint_task_type=hint, hint_mode=m, hint_scope=scope)
    bundle = _auto_retrieve(task)
    _render_plan(task, intent, dry_run=False, bundle=bundle)


@app.command(name="inspect", help=(
    "Show the complete compiled prompt for a goal — all blocks assembled, budget-capped,\n"
    "ready to be fed to an LLM. Includes the task plan panel above the prompt.\n\n"
    "Equivalent to running any verb command with --dry-run.\n"
    "Use --compact to print only the raw prompt string without the plan panels.\n\n"
    "Examples:\n"
    "  ai inspect 'fix the null pointer in UserService'\n"
    "  ai inspect 'add rate limiting' --type feat --no-retrieve\n"
    "  ai inspect 'refactor payment service' --type ref --mode safe --compact"
))
def cmd_inspect(
    goal: str = typer.Argument(...),
    task_type: Optional[str] = typer.Option(None, "--type", "-t"),
    mode: Optional[str] = typer.Option(None, "--mode", "-m"),
    scope: Optional[str] = typer.Option(None, "--scope", "-s"),
    no_retrieve: bool = typer.Option(False, "--no-retrieve"),
) -> None:
    hint = CLI_VERB_ALIASES.get((task_type or "").lower())
    m = _parse_mode(mode)
    intent = classify(goal, hint_task_type=hint, hint_mode=m, hint_scope=scope)
    task = build_task(goal, hint_task_type=hint, hint_mode=m, hint_scope=scope)
    bundle = None if no_retrieve else _auto_retrieve(task)
    _render_plan(task, intent, dry_run=True, bundle=bundle)


# ---------------------------------------------------------------------------
# Retrieval helper
# ---------------------------------------------------------------------------

def _auto_retrieve(task: Task) -> ContextBundle | None:
    """Run retrieval silently; return None on hard failure."""
    if not task.retrieval_plan or not task.context_budget:
        return None
    try:
        return retrieve(plan=task.retrieval_plan, budget=task.context_budget, repo_root=Path.cwd())
    except Exception:
        return None


# ---------------------------------------------------------------------------
# `ai show` subcommands
# ---------------------------------------------------------------------------

@show_app.command(name="tasks", help="List all task types.")
def show_tasks() -> None:
    t = Table(title="Task Types", box=box.ROUNDED)
    t.add_column("Type", style="cyan", width=22)
    t.add_column("Description")
    for tt, desc in TASK_TYPE_DESCRIPTIONS.items():
        t.add_column_width = 50
        t.add_row(tt.value, desc)
    console.print(t)


@show_app.command(name="task", help="Show details for a specific task type.")
def show_task(name: str = typer.Argument(..., help="Task type name")) -> None:
    try:
        tt = TaskType(name.lower())
    except ValueError:
        mapped = CLI_VERB_ALIASES.get(name.lower())
        if not mapped:
            err.print(f"[red]Unknown task type:[/red] {name!r}")
            raise typer.Exit(1)
        tt = mapped

    desc = TASK_TYPE_DESCRIPTIONS.get(tt, "")
    contract = get_contract(tt)

    console.print(Panel(
        f"[bold cyan]{tt.value}[/bold cyan]\n{desc}",
        title="Task Type",
        border_style="cyan",
    ))

    # Default constraints
    from .intent import _DEFAULT_CONSTRAINTS, _DEFAULT_MODES
    default_mode = _DEFAULT_MODES.get(tt, Mode.SURGICAL)
    console.print(f"  Default mode: [magenta]{default_mode.value}[/magenta]\n")

    defaults = _DEFAULT_CONSTRAINTS.get(tt, [])
    if defaults:
        ct = Table(box=box.SIMPLE, show_header=False)
        ct.add_column(style="green", width=36)
        ct.add_column(style="dim")
        for c in defaults:
            ct.add_row(f"  {c.value}", CONSTRAINT_DESCRIPTIONS.get(c, ""))
        console.print(Panel(ct, title="Default Constraints", border_style="yellow"))

    # Output contract
    ct2 = Table(box=box.SIMPLE, show_header=False)
    ct2.add_column(style="cyan", width=26)
    ct2.add_column(style="dim")
    for f in contract.fields:
        req = "" if f.required else " [dim](opt)[/dim]"
        ct2.add_row(f"  {f.name}{req}", f.description)
    console.print(Panel(ct2, title="Output Contract", border_style="magenta"))


@show_app.command(name="modes", help="List all reasoning modes.")
def show_modes() -> None:
    t = Table(title="Reasoning Modes", box=box.ROUNDED)
    t.add_column("Mode", style="magenta", width=16)
    t.add_column("Description")
    for mode, desc in MODE_DESCRIPTIONS.items():
        t.add_row(mode.value, desc)
    console.print(t)


@show_app.command(name="constraints", help="List all constraints.")
def show_constraints() -> None:
    t = Table(title="Constraints", box=box.ROUNDED)
    t.add_column("Constraint", style="green", width=38)
    t.add_column("Description")
    for c, desc in CONSTRAINT_DESCRIPTIONS.items():
        t.add_row(c.value, desc)
    console.print(t)


@show_app.command(name="presets", help="List all built-in presets.")
def show_presets() -> None:
    t = Table(title="Presets", box=box.ROUNDED)
    t.add_column("Preset", style="cyan", width=26)
    t.add_column("Task type", style="dim", width=18)
    t.add_column("Mode", style="magenta", width=12)
    t.add_column("Description")
    for p in list_presets():
        t.add_row(p.name, p.task_type.value, p.mode.value, p.description)
    console.print(t)


@show_app.command(name="profiles", help="List all execution profiles.")
def show_profiles() -> None:
    t = Table(title="Profiles", box=box.ROUNDED)
    t.add_column("Profile", style="cyan", width=16)
    t.add_column("Mode", style="magenta", width=14)
    t.add_column("Description")
    for p in list_profiles():
        mode = p.mode_override.value if p.mode_override else "[dim]task default[/dim]"
        t.add_row(p.name, mode, p.description)
    console.print(t)


@show_app.command(name="policy", help="Show the active policy for the current repo.")
def show_policy() -> None:
    cfg = _load_cfg()
    lines = []
    if cfg.repo_policy:
        lines.append(f"[bold]Repo policy:[/bold]\n{cfg.repo_policy}")
    else:
        lines.append("[dim]No repo-specific policy loaded. Add one in .prompt-engine.toml[/dim]")
    if cfg.always_on_constraints:
        lines.append(f"\n[bold]Always-on constraints:[/bold] {', '.join(cfg.always_on_constraints)}")
    if cfg.disabled_constraints:
        lines.append(f"\n[bold]Disabled constraints:[/bold] {', '.join(cfg.disabled_constraints)}")

    from .policy import _UNIVERSAL_RULES
    rule_text = "\n".join(f"  • [{r.name}] {r.text}" for r in _UNIVERSAL_RULES)
    lines.append(f"\n[bold]Universal rules (always active):[/bold]\n{rule_text}")
    console.print(Panel("\n".join(lines), title="Active Policy", border_style="dim"))


# ---------------------------------------------------------------------------
# Init command
# ---------------------------------------------------------------------------

@app.command(name="init", help="Write a default global config file.")
def cmd_init(
    force: bool = typer.Option(False, "--force", help="Overwrite existing config"),
) -> None:
    from .config import _GLOBAL_CONFIG_PATH
    if _GLOBAL_CONFIG_PATH.exists() and not force:
        console.print(f"[yellow]Config already exists:[/yellow] {_GLOBAL_CONFIG_PATH}")
        console.print("  Use [bold]--force[/bold] to overwrite.")
        return
    write_default_config()
    console.print(f"[green]✓[/green] Config written to [cyan]{_GLOBAL_CONFIG_PATH}[/cyan]")


if __name__ == "__main__":
    app()
