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
    help="Deterministic prompt engine — compile developer intent into structured AI instructions.",
    add_completion=True,
    no_args_is_help=True,
)
show_app = typer.Typer(help="Discover available task types, modes, constraints, and presets.", no_args_is_help=True)
app.add_typer(show_app, name="show")

console = Console()
err = Console(stderr=True)

# ---------------------------------------------------------------------------
# Shared flag definitions
# ---------------------------------------------------------------------------

_MODE_HELP = "Reasoning mode: surgical|deep|fast|safe|explore|strict|minimal|architectural|debug|rewrite|maintain"
_SCOPE_HELP = "Scope hint — module, service, or file name"
_PRESET_HELP = "Named preset, e.g. bugfix/surgical or refactor/safe"
_PROFILE_HELP = "Profile: fast|balanced|strict|architectural|experimental"


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
        preserve_api: bool = typer.Option(False, "--preserve-api", help="Add preserve_public_api constraint"),
        no_tests: bool = typer.Option(False, "--no-tests", help="Remove require_tests constraint"),
        dry_run: bool = typer.Option(False, "--dry-run", help="Show compiled plan without invoking LLM"),
        explain: bool = typer.Option(False, "--explain", help="Explain classification and context choices"),
        compact: bool = typer.Option(False, "--compact", help="Output compiled prompt only"),
        strict: bool = typer.Option(False, "--strict", help="Apply strict mode"),
        safe: bool = typer.Option(False, "--safe", help="Apply safe mode"),
        no_retrieve: bool = typer.Option(False, "--no-retrieve", help="Skip repo-index retrieval"),
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
_make_task_command(TaskType.BUGFIX, "fix", "Fix a bug — root cause, minimal patch, tests")
_make_task_command(TaskType.FEATURE, "feat", "Implement a new feature")
_make_task_command(TaskType.REFACTOR, "ref", "Refactor code without changing behavior")
_make_task_command(TaskType.TEST_GENERATION, "test", "Generate tests for a function or module")
_make_task_command(TaskType.DEBUGGING, "debug", "Investigate and diagnose a problem")
_make_task_command(TaskType.EXPLANATION, "explain", "Explain how code works")
_make_task_command(TaskType.OPTIMIZATION, "opt", "Optimize for performance")
_make_task_command(TaskType.MIGRATION, "migrate", "Plan a migration")
_make_task_command(TaskType.CODE_REVIEW, "review", "Review code for issues")
_make_task_command(TaskType.SECURITY, "secure", "Fix or audit a security issue")
_make_task_command(TaskType.CLEANUP, "clean", "Remove dead code and obsolete patterns")
_make_task_command(TaskType.OBSERVABILITY, "observe", "Add logging, metrics, or tracing")


# ---------------------------------------------------------------------------
# Generic `ai run` — natural language without a verb
# ---------------------------------------------------------------------------

@app.command(name="run", help="Run any task from natural language — task type inferred automatically.")
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
    no_retrieve: bool = typer.Option(False, "--no-retrieve", help="Skip repo-index retrieval"),
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

@app.command(name="plan", help="Show the full task plan for a goal (alias for 'run --explain').")
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


@app.command(name="inspect", help="Show what prompt would be compiled for a goal.")
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
