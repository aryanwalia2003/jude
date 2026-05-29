"""Metrics CLI sub-app — code health and architecture analysis commands."""

from pathlib import Path
from typing import Literal, Optional

import typer
from rich.console import Console
from rich.table import Table
from rich import box

from . import db, metrics

console = Console()

app = typer.Typer(help="Code metrics and architecture health.", add_completion=False)


def _db_path(db_file: Optional[Path], cwd: Path = Path.cwd()) -> Path:
    """Resolve DB path. Auto-detects existing databases.

    Priority: explicit flag > REPO_INDEX_DB env > repo-local DB > git-root name DB > default.

    Auto-detection:
    1. Check for repo-index.db in repo root (project-local)
    2. Check for <git-root-name>.db in ~/.local/share/repo-index/ (global indexed)
    3. Fall back to default ~/.local/share/repo-index/index.db
    """
    import os
    from . import git

    if db_file:
        return db_file

    if env_db := os.getenv("REPO_INDEX_DB"):
        return Path(env_db)

    try:
        git_root = git.git_root(cwd)
        if git_root:
            # Check for repo-local database first
            local_db = git_root / "repo-index.db"
            if local_db.exists():
                return local_db

            # Check for git-root-named DB in global location
            db_dir = Path.home() / ".local/share/repo-index"
            global_db = db_dir / f"{git_root.name}.db"
            if global_db.exists():
                return global_db

            # Return derived path (will be created on first index)
            return global_db
    except Exception:
        pass

    return Path.home() / ".local/share/repo-index" / "index.db"


@app.command()
def health(
    db_file: Optional[Path] = typer.Option(None, "--db", help="Path to SQLite DB."),
) -> None:
    """Show overall repository health dashboard."""
    conn = db.open_db(_db_path(db_file))
    summary = metrics.health_summary(conn)

    console.print("\n[bold]Repository Health Dashboard[/bold]\n")

    # Overall stats
    console.print(f"  Total symbols:     [green]{summary['total_symbols']}[/green]")
    console.print(f"  Dead code items:   [yellow]{summary['dead_code_count']}[/yellow]")
    console.print(f"  God objects:       [yellow]{summary['god_objects_count']}[/yellow]")
    console.print(f"  Module cycles:     [red]{summary['circular_deps_count']}[/red]")
    console.print(f"  Cross-module deps: [cyan]{summary['coupling_edges_count']}[/cyan]")

    # Top hotspots
    if summary["hotspots_top_5"]:
        console.print("\n[dim]Top 5 hotspots (most called):[/dim]")
        for m in summary["hotspots_top_5"]:
            console.print(f"  {m.name:<30} {m.fan_in:>3} callers")

    # Longest functions
    if summary["longest_functions_top_5"]:
        console.print("\n[dim]Top 5 longest functions:[/dim]")
        for m in summary["longest_functions_top_5"]:
            console.print(f"  {m.name:<30} {m.line_count:>3} lines")

    # Top coupling
    if summary["coupling_top_5"]:
        console.print("\n[dim]Top 5 module dependencies:[/dim]")
        for c in summary["coupling_top_5"]:
            console.print(f"  {c.from_module} → {c.to_module:<30} {c.call_count:>2} calls")

    console.print()


@app.command()
def hotspots(
    top: int = typer.Option(10, "--top", "-n", help="Number of top hotspots to show."),
    db_file: Optional[Path] = typer.Option(None, "--db", help="Path to SQLite DB."),
) -> None:
    """Show most-called symbols (hotspots in the codebase)."""
    conn = db.open_db(_db_path(db_file))
    items = metrics.hotspots(conn, top_n=top)

    if not items:
        console.print("[dim]No hotspots found.[/dim]")
        return

    table = Table(box=box.SIMPLE, show_header=True)
    table.add_column("Symbol", style="cyan")
    table.add_column("Kind")
    table.add_column("File", style="dim")
    table.add_column("Callers", justify="right")
    table.add_column("Callees", justify="right")
    table.add_column("Lines", justify="right")

    for m in items:
        table.add_row(
            m.name,
            m.kind,
            m.file_path,
            str(m.fan_in),
            str(m.fan_out),
            str(m.line_count),
        )

    console.print("\n")
    console.print(table)
    console.print()


@app.command("dead-code")
def dead_code(
    kind: Literal["function", "method", "all"] = typer.Option(
        "all", "--kind", help="Filter by symbol kind."
    ),
    db_file: Optional[Path] = typer.Option(None, "--db", help="Path to SQLite DB."),
) -> None:
    """Show functions/methods with zero callers (potential dead code)."""
    conn = db.open_db(_db_path(db_file))
    items = metrics.dead_code(conn)

    if kind != "all":
        items = [m for m in items if m.kind == kind]

    if not items:
        console.print("[green]No dead code detected.[/green]")
        return

    table = Table(box=box.SIMPLE, show_header=True)
    table.add_column("Symbol", style="yellow")
    table.add_column("Kind")
    table.add_column("File", style="dim")
    table.add_column("Start", justify="right")
    table.add_column("Lines", justify="right")

    for m in items[:50]:  # Limit to 50 rows
        table.add_row(
            m.name,
            m.kind,
            m.file_path,
            str(m.start_line),
            str(m.line_count),
        )

    console.print("\n")
    console.print(table)
    if len(items) > 50:
        console.print(f"\n[dim]…and {len(items) - 50} more[/dim]\n")
    else:
        console.print()


@app.command()
def functions(
    sort: Literal["lines", "callers", "callees"] = typer.Option(
        "lines", "--sort", help="Sort by metric."
    ),
    limit: int = typer.Option(20, "--limit", "-n", help="Max rows to show."),
    db_file: Optional[Path] = typer.Option(None, "--db", help="Path to SQLite DB."),
) -> None:
    """Show all functions/methods with their metrics."""
    conn = db.open_db(_db_path(db_file))
    all_items = metrics.symbol_metrics(conn)

    # Filter to functions/methods only
    items = [m for m in all_items if m.kind in ("function", "method")]

    # Sort
    if sort == "lines":
        items.sort(key=lambda m: m.line_count, reverse=True)
    elif sort == "callers":
        items.sort(key=lambda m: m.fan_in, reverse=True)
    else:  # callees
        items.sort(key=lambda m: m.fan_out, reverse=True)

    items = items[:limit]

    table = Table(box=box.SIMPLE, show_header=True)
    table.add_column("Symbol", style="cyan")
    table.add_column("Kind")
    table.add_column("Module", style="dim")
    table.add_column("Lines", justify="right")
    table.add_column("Callers", justify="right")
    table.add_column("Callees", justify="right")

    for m in items:
        table.add_row(
            m.name,
            m.kind,
            m.module or "—",
            str(m.line_count),
            str(m.fan_in),
            str(m.fan_out),
        )

    console.print("\n")
    console.print(table)
    console.print()


@app.command()
def coupling(
    limit: int = typer.Option(20, "--limit", "-n", help="Max rows to show."),
    db_file: Optional[Path] = typer.Option(None, "--db", help="Path to SQLite DB."),
) -> None:
    """Show cross-module dependencies (coupling graph)."""
    conn = db.open_db(_db_path(db_file))
    items = metrics.module_coupling(conn)[:limit]

    if not items:
        console.print("[green]No cross-module dependencies.[/green]")
        return

    table = Table(box=box.SIMPLE, show_header=True)
    table.add_column("From Module", style="cyan")
    table.add_column("To Module", style="cyan")
    table.add_column("Calls", justify="right")

    for m in items:
        table.add_row(m.from_module, m.to_module, str(m.call_count))

    console.print("\n")
    console.print(table)
    console.print()


@app.command()
def cycles(
    db_file: Optional[Path] = typer.Option(None, "--db", help="Path to SQLite DB."),
) -> None:
    """Detect circular module import dependencies."""
    conn = db.open_db(_db_path(db_file))
    cycles_list = metrics.circular_dependencies(conn)

    if not cycles_list:
        console.print("[green]No circular dependencies detected.[/green]")
        return

    console.print(f"\n[yellow]Found {len(cycles_list)} import cycle(s):[/yellow]\n")

    for i, cycle in enumerate(cycles_list, 1):
        cycle_str = " → ".join(cycle) + " → " + cycle[0]
        console.print(f"  [{i}] {cycle_str}")

    console.print()
