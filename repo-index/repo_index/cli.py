"""repo-index CLI — build, query, inspect the symbol index."""

import os
import signal
from datetime import datetime
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table
from rich import box

from . import db, git, indexer, retrieval, resolver
from .events import EventKind, FileEvent
from .watcher import FileWatcher
from . import cli_metrics

app = typer.Typer(help="Repository intelligence — AST-aware symbol index.", add_completion=False)
app.add_typer(cli_metrics.app, name="metrics")
console = Console()

_DB_DIR = Path.home() / ".local" / "share" / "repo-index"
_DEFAULT_DB = _DB_DIR / "index.db"


def _db_path(db_file: Optional[Path], cwd: Optional[Path] = None) -> Path:
    """Resolve DB path. Priority: explicit flag > REPO_INDEX_DB env > git-root name > default."""
    if db_file:
        return db_file
    env = os.environ.get("REPO_INDEX_DB")
    if env:
        return Path(env)
    repo_root = git.git_root(cwd or Path.cwd())
    if repo_root:
        return _DB_DIR / f"{repo_root.name}.db"
    return _DEFAULT_DB


@app.command()
def build(
    path: Path = typer.Argument(Path("."), help="Repository root to index."),
    db_file: Optional[Path] = typer.Option(None, "--db", help="Path to SQLite DB."),
) -> None:
    """Scan and index a repository."""
    root = path.resolve()
    if not root.is_dir():
        console.print(f"[red]Not a directory:[/red] {root}")
        raise typer.Exit(1)

    db_path = _db_path(db_file, cwd=root)
    conn = db.open_db(db_path)

    branch = git.current_branch(root)
    branch_label = f" [dim]({branch})[/dim]" if branch else ""
    console.print(f"Indexing [cyan]{root}[/cyan]{branch_label} → [dim]{db_path}[/dim]")

    with console.status("Scanning and parsing..."):
        stats = indexer.build_index(conn, root, branch=branch or None)
    db.set_repo_root(conn, str(root))

    table = Table(box=box.SIMPLE, show_header=False)
    table.add_column("key", style="dim")
    table.add_column("value", style="bold green")
    if stats.branch:
        table.add_row("Branch", f"[magenta]{stats.branch}[/magenta]")
    table.add_row("Files scanned", str(stats.scanned))
    table.add_row("Files indexed", str(stats.indexed))
    table.add_row("Files skipped (unchanged)", str(stats.skipped))
    if stats.removed:
        table.add_row("Orphans removed", f"[yellow]{stats.removed}[/yellow]")
    table.add_row("Symbols added", str(stats.symbols_added))
    table.add_row("Relations added", str(stats.relations_added))
    if stats.errors:
        table.add_row("Errors", f"[red]{stats.errors}[/red]")
    console.print(table)


@app.command()
def symbol(
    name: str = typer.Argument(..., help="Symbol name to look up."),
    db_file: Optional[Path] = typer.Option(None, "--db", help="Path to SQLite DB."),
) -> None:
    """Look up a symbol by name."""
    conn = db.open_db(_db_path(db_file))
    rows = db.query_symbol(conn, name)

    if not rows:
        console.print(f"[yellow]No symbol found:[/yellow] {name}")
        raise typer.Exit(1)

    table = Table(title=f"Symbol: {name}", box=box.ROUNDED)
    table.add_column("Kind", style="cyan")
    table.add_column("File", style="green")
    table.add_column("Lines", justify="right")
    table.add_column("Language")

    for row in rows:
        table.add_row(
            row["kind"],
            row["file_path"],
            f"{row['start_line']}–{row['end_line']}",
            row["language"],
        )

    console.print(table)


@app.command()
def callers(
    name: str = typer.Argument(..., help="Function name to find callers of."),
    db_file: Optional[Path] = typer.Option(None, "--db", help="Path to SQLite DB."),
) -> None:
    """Find all callers of a function."""
    conn = db.open_db(_db_path(db_file))
    rows = db.query_callers(conn, name)

    if not rows:
        console.print(f"[yellow]No callers found for:[/yellow] {name}")
        raise typer.Exit(1)

    table = Table(title=f"Callers of: {name}", box=box.ROUNDED)
    table.add_column("Caller", style="cyan")
    table.add_column("Kind")
    table.add_column("File", style="green")
    table.add_column("Line", justify="right")

    for row in rows:
        table.add_row(row["caller"], row["kind"], row["file_path"], str(row["start_line"]))

    console.print(table)


@app.command()
def imports(
    file: str = typer.Argument(..., help="File path (relative to indexed root) to inspect imports."),
    db_file: Optional[Path] = typer.Option(None, "--db", help="Path to SQLite DB."),
) -> None:
    """List all imports in a file."""
    conn = db.open_db(_db_path(db_file))
    rows = db.query_imports(conn, file)

    if not rows:
        console.print(f"[yellow]No imports found for:[/yellow] {file}")
        raise typer.Exit(1)

    table = Table(title=f"Imports: {file}", box=box.ROUNDED)
    table.add_column("Module", style="cyan")
    for row in rows:
        table.add_row(row["import_name"])
    console.print(table)


@app.command()
def stats(
    db_file: Optional[Path] = typer.Option(None, "--db", help="Path to SQLite DB."),
) -> None:
    """Show index statistics."""
    conn = db.open_db(_db_path(db_file))
    s = db.stats(conn)

    console.print(f"\n[bold]Index Stats[/bold]")
    console.print(f"  Files:     [green]{s['files']}[/green]")
    console.print(f"  Symbols:   [green]{s['symbols']}[/green]")
    console.print(f"  Relations: [green]{s['relations']}[/green]")

    if s["by_kind"]:
        console.print("\n[dim]By kind:[/dim]")
        for kind, count in s["by_kind"].items():
            console.print(f"  {kind:<12} {count}")

    if s["by_language"]:
        console.print("\n[dim]By language:[/dim]")
        for lang, count in s["by_language"].items():
            console.print(f"  {lang:<12} {count}")


@app.command()
def watch(
    path: Path = typer.Argument(Path("."), help="Repository root to watch."),
    db_file: Optional[Path] = typer.Option(None, "--db", help="Path to SQLite DB."),
    skip_build: bool = typer.Option(False, "--skip-build", help="Skip initial full build."),
) -> None:
    """Watch a repository and incrementally update the index on changes."""
    root = path.resolve()
    if not root.is_dir():
        console.print(f"[red]Not a directory:[/red] {root}")
        raise typer.Exit(1)

    db_path = _db_path(db_file)
    conn = db.open_db(db_path)

    if not skip_build:
        console.print(f"Building initial index for [cyan]{root}[/cyan]...")
        with console.status("Scanning..."):
            s = indexer.build_index(conn, root)
        console.print(
            f"  [green]✓[/green] {s.indexed} indexed, {s.skipped} skipped, "
            f"{s.symbols_added} symbols, {s.relations_added} relations"
        )

    _kind_label = {
        EventKind.CREATED:  ("[green]CREATED [/green]", "+"),
        EventKind.MODIFIED: ("[cyan]MODIFIED[/cyan]", "~"),
        EventKind.DELETED:  ("[red]DELETED [/red]", "-"),
        EventKind.MOVED:    ("[yellow]MOVED   [/yellow]", "→"),
    }

    def on_event(event: FileEvent, stats: "indexer.IndexStats | None") -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        label, icon = _kind_label[event.kind]
        rel = event.path.relative_to(root) if event.path.is_relative_to(root) else event.path
        msg = f"[dim]{ts}[/dim] {label} {icon} [green]{rel}[/green]"
        if event.dest:
            dest_rel = event.dest.relative_to(root) if event.dest.is_relative_to(root) else event.dest
            msg += f" → [cyan]{dest_rel}[/cyan]"
        if stats and stats.symbols_added:
            msg += f" [dim]({stats.symbols_added} symbols)[/dim]"
        console.print(msg)

    console.print(f"\nWatching [cyan]{root}[/cyan] — press [bold]Ctrl+C[/bold] to stop\n")

    with FileWatcher(conn, root, on_event=on_event):
        try:
            signal.pause()
        except (KeyboardInterrupt, AttributeError):
            # AttributeError: Windows has no signal.pause()
            import time
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                pass

    console.print("\n[dim]Watcher stopped.[/dim]")


@app.command()
def search(
    query: str = typer.Argument(..., help="Search query (FTS5, prefix-matched)."),
    kind: Optional[str] = typer.Option(None, "--kind", help="Filter by kind: function, class, method, module."),
    limit: int = typer.Option(20, "--limit", help="Max results."),
    db_file: Optional[Path] = typer.Option(None, "--db"),
) -> None:
    """Full-text search across all indexed symbols."""
    conn = db.open_db(_db_path(db_file))
    results = retrieval.search(conn, query, kind=kind, limit=limit)

    if not results:
        console.print(f"[yellow]No results for:[/yellow] {query}")
        raise typer.Exit(1)

    table = Table(title=f"Search: {query!r}", box=box.ROUNDED)
    table.add_column("Symbol", style="cyan")
    table.add_column("Kind")
    table.add_column("File", style="green")
    table.add_column("Lines", justify="right")

    for r in results:
        table.add_row(r.name, r.kind, r.file_path, f"{r.start_line}–{r.end_line}")

    console.print(table)


@app.command()
def deps(
    name: str = typer.Argument(..., help="Symbol name to trace dependencies for."),
    depth: int = typer.Option(3, "--depth", help="BFS depth limit."),
    db_file: Optional[Path] = typer.Option(None, "--db"),
) -> None:
    """Show what a symbol transitively calls (dependency chain)."""
    conn = db.open_db(_db_path(db_file))
    callees = retrieval.get_callgraph(conn, name, max_depth=depth)

    if not callees:
        console.print(f"[yellow]{name}[/yellow] makes no tracked calls (or is not indexed).")
        raise typer.Exit(0)

    table = Table(title=f"Dependencies of: {name} (depth {depth})", box=box.ROUNDED)
    table.add_column("Calls (transitively)", style="cyan")
    for c in callees:
        table.add_row(c)
    console.print(table)


@app.command()
def impact(
    name: str = typer.Argument(..., help="Symbol name to analyse blast radius for."),
    depth: int = typer.Option(3, "--depth", help="BFS depth limit."),
    db_file: Optional[Path] = typer.Option(None, "--db"),
) -> None:
    """Show what would break if a symbol changes (reverse call graph)."""
    conn = db.open_db(_db_path(db_file))
    callers = retrieval.get_impact(conn, name, max_depth=depth)

    if not callers:
        console.print(f"[yellow]{name}[/yellow] has no tracked callers (or is not indexed).")
        raise typer.Exit(0)

    table = Table(title=f"Impact of changing: {name} (depth {depth})", box=box.ROUNDED)
    table.add_column("Would be affected", style="red")
    for c in callers:
        table.add_row(c)
    console.print(table)


@app.command()
def context(
    name: str = typer.Argument(..., help="Symbol name to assemble context for."),
    depth: int = typer.Option(2, "--depth", help="Call graph traversal depth."),
    db_file: Optional[Path] = typer.Option(None, "--db"),
) -> None:
    """Assemble full retrieval context for a symbol — ready for LLM consumption."""
    from rich.panel import Panel
    from rich.text import Text

    conn = db.open_db(_db_path(db_file))
    ctx = retrieval.get_context(conn, name, callgraph_depth=depth)

    if ctx is None:
        console.print(f"[yellow]Symbol not found:[/yellow] {name}")
        raise typer.Exit(1)

    lines = [
        f"[bold cyan]{ctx.name}[/bold cyan]  [dim]{ctx.kind}[/dim]",
        f"[green]{ctx.file_path}[/green]  lines {ctx.start_line}–{ctx.end_line}",
        "",
    ]

    if ctx.calls:
        lines.append(f"[bold]Direct calls:[/bold]  {', '.join(ctx.calls)}")
    if ctx.called_by:
        lines.append(f"[bold]Called by:[/bold]     {', '.join(ctx.called_by)}")
    if ctx.file_imports:
        lines.append(f"[bold]File imports:[/bold]  {', '.join(ctx.file_imports)}")

    if ctx.callgraph:
        lines.append("")
        lines.append(f"[bold]Call graph[/bold] (depth {depth}):")
        for sym in ctx.callgraph:
            lines.append(f"  → {sym}")

    if ctx.impact:
        lines.append("")
        lines.append(f"[bold]Impact[/bold] (would break if changed):")
        for sym in ctx.impact:
            lines.append(f"  ← {sym}")

    console.print(Panel("\n".join(lines), title="Retrieval Context", border_style="dim"))


@app.command()
def branch(
    path: Path = typer.Argument(Path("."), help="Repository root."),
    db_file: Optional[Path] = typer.Option(None, "--db", help="Path to SQLite DB."),
) -> None:
    """Show current branch and per-branch index statistics."""
    root = path.resolve()
    conn = db.open_db(_db_path(db_file))

    current = db.get_current_branch(conn)
    detected = git.current_branch(root)

    if detected:
        label = f"[magenta]{detected}[/magenta]"
        if current and current != detected:
            label += f" [yellow](index is on {current} — run build to sync)[/yellow]"
    else:
        label = f"[dim]{current or 'unknown (not a git repo)'}[/dim]"

    console.print(f"\nCurrent branch: {label}\n")

    rows = db.query_branch_stats(conn)
    if not rows:
        console.print("[dim]Nothing indexed yet.[/dim]")
        return

    table = Table(title="Index by Branch", box=box.ROUNDED)
    table.add_column("Branch", style="magenta")
    table.add_column("Files", justify="right")
    table.add_column("Symbols", justify="right")

    for row in rows:
        b = row["branch"] or "[dim]unknown[/dim]"
        marker = " ◀" if row["branch"] == current else ""
        table.add_row(b + marker, str(row["files"]), str(row["symbols"]))

    console.print(table)


@app.command()
def resolve(
    db_file: Optional[Path] = typer.Option(None, "--db", help="Path to SQLite DB."),
) -> None:
    """Resolve symbol references — link call targets to actual symbol IDs."""
    conn = db.open_db(_db_path(db_file))
    with console.status("Resolving references..."):
        stats = resolver.resolve_references(conn)

    table = Table(box=box.SIMPLE, show_header=False)
    table.add_column("key", style="dim")
    table.add_column("value", style="bold")
    table.add_row("Total resolvable relations", str(stats.total_relations))
    table.add_row("Resolved (confidence ≥ 0.7)", f"[green]{stats.resolved}[/green]")
    table.add_row("Partially resolved", f"[yellow]{stats.partially_resolved}[/yellow]")
    table.add_row("Unresolved", f"[dim]{stats.unresolved}[/dim]")
    console.print(table)

    rs = db.resolution_stats(conn)
    if rs["total"]:
        pct = int(rs["resolved"] / rs["total"] * 100)
        console.print(
            f"\n[dim]Resolution coverage:[/dim] [bold]{pct}%[/bold]  "
            f"high=[green]{rs['high_confidence']}[/green]  "
            f"medium=[yellow]{rs['medium_confidence']}[/yellow]  "
            f"low=[dim]{rs['low_confidence']}[/dim]  "
            f"unresolved=[red]{rs['unresolved']}[/red]"
        )


@app.command(name="fqid")
def fqid_cmd(
    name: str = typer.Argument(..., help="Fully-qualified symbol ID to look up."),
    db_file: Optional[Path] = typer.Option(None, "--db", help="Path to SQLite DB."),
) -> None:
    """Look up a symbol by its fully-qualified identifier."""
    conn = db.open_db(_db_path(db_file))
    row = db.query_symbol_by_fqid(conn, name)

    if not row:
        console.print(f"[yellow]No symbol found for FQID:[/yellow] {name}")
        raise typer.Exit(1)

    table = Table(title=f"FQID: {name}", box=box.ROUNDED)
    table.add_column("Field", style="dim")
    table.add_column("Value")
    table.add_row("Name", f"[cyan]{row['name']}[/cyan]")
    table.add_row("Kind", row["kind"])
    table.add_row("Module", f"[green]{row['module']}[/green]")
    table.add_row("File", row["file_path"])
    table.add_row("Lines", f"{row['start_line']}–{row['end_line']}")
    console.print(table)


@app.command()
def ownership(
    name: str = typer.Argument(..., help="Class name to show owned symbols for."),
    db_file: Optional[Path] = typer.Option(None, "--db", help="Path to SQLite DB."),
) -> None:
    """Show symbols owned by a class (methods defined inside it)."""
    conn = db.open_db(_db_path(db_file))
    rows = db.query_owned_symbols(conn, name)

    if not rows:
        console.print(f"[yellow]No owned symbols found for:[/yellow] {name}")
        raise typer.Exit(1)

    table = Table(title=f"Ownership: {name}", box=box.ROUNDED)
    table.add_column("Symbol", style="cyan")
    table.add_column("Kind")
    table.add_column("FQID", style="dim")
    table.add_column("Lines", justify="right")
    for row in rows:
        table.add_row(row["name"], row["kind"], row["fqid"] or "", f"{row['start_line']}–{row['end_line']}")
    console.print(table)


@app.command(name="module")
def module_cmd(
    name: str = typer.Argument(..., help="Module name to inspect (e.g. auth.jwt)."),
    db_file: Optional[Path] = typer.Option(None, "--db", help="Path to SQLite DB."),
) -> None:
    """Show all symbols in a module."""
    conn = db.open_db(_db_path(db_file))
    rows = db.query_module_symbols(conn, name)

    if not rows:
        console.print(f"[yellow]No symbols found for module:[/yellow] {name}")
        raise typer.Exit(1)

    table = Table(title=f"Module: {name}", box=box.ROUNDED)
    table.add_column("Symbol", style="cyan")
    table.add_column("Kind")
    table.add_column("FQID", style="dim")
    table.add_column("Lines", justify="right")
    for row in rows:
        table.add_row(row["name"], row["kind"], row["fqid"] or "", f"{row['start_line']}–{row['end_line']}")
    console.print(table)


@app.command()
def files(
    db_file: Optional[Path] = typer.Option(None, "--db", help="Path to SQLite DB."),
) -> None:
    """List all indexed files."""
    conn = db.open_db(_db_path(db_file))
    rows = conn.execute(
        "SELECT path, language, content_hash, last_indexed_at FROM files ORDER BY path"
    ).fetchall()

    if not rows:
        console.print("[yellow]No files indexed yet.[/yellow]")
        raise typer.Exit(1)

    table = Table(title="Indexed Files", box=box.ROUNDED)
    table.add_column("Path", style="green")
    table.add_column("Language")
    table.add_column("Hash", style="dim")

    for row in rows:
        table.add_row(row["path"], row["language"], row["content_hash"][:12] + "…")

    console.print(table)
