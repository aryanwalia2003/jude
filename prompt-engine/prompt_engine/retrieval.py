"""Retrieval bridge — queries repo-index and assembles real context for the prompt."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .budget import estimate_tokens
from .task import ContextBudget, RetrievalPlan

# Soft dependency — repo-index may not be installed in every env
try:
    from repo_index import db as _ri_db
    from repo_index import retrieval as _ri_retrieval
    from repo_index import git as _ri_git
    from repo_index.graph import build_call_graph_cached
    _AVAILABLE = True
except ImportError:
    _AVAILABLE = False

_DEFAULT_DB = Path.home() / ".local" / "share" / "repo-index" / "index.db"

_STOP_WORDS = frozenset(
    "a an the in for of to with and or not is are was were be been being "
    "have has had do does did will would could should may might "
    "this that these those it its from by at on".split()
)

# Context budget: context block gets ~55% of total token budget
_CONTEXT_BUDGET_RATIO = 0.55


@dataclass
class SymbolContext:
    name: str
    kind: str
    file_path: str
    start_line: int
    end_line: int
    fqid: str = ""
    module: str = ""
    calls: list[str] = field(default_factory=list)
    called_by: list[str] = field(default_factory=list)
    callgraph: list[str] = field(default_factory=list)
    imports: list[str] = field(default_factory=list)
    rank: int = 0
    relevance_score: float = 0.0


@dataclass
class ContextBundle:
    symbols: list[SymbolContext]
    git_diff: str
    raw_text: str               # assembled prompt-ready text
    token_estimate: int
    retrieval_notes: list[str]
    db_path: Optional[Path] = None
    recently_changed_symbols: list[str] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not self.symbols and not self.git_diff

    @property
    def symbol_count(self) -> int:
        return len(self.symbols)


def retrieve(
    plan: RetrievalPlan,
    budget: ContextBudget,
    db_path: Optional[Path] = None,
    repo_root: Optional[Path] = None,
) -> ContextBundle:
    """Fetch repo context from the index. Returns an empty bundle if unavailable."""
    notes: list[str] = []

    if not _AVAILABLE:
        notes.append("repo-index not installed — run: pip install -e ../repo-index")
        return _empty(notes)

    resolved_db = db_path or _resolve_db(repo_root)
    if not resolved_db.exists():
        notes.append(f"no index at {resolved_db} — run: repo-index build .")
        return _empty(notes, db_path=resolved_db)

    conn = _ri_db.open_db(resolved_db)
    count = conn.execute("SELECT COUNT(*) FROM symbols").fetchone()[0]
    if count == 0:
        notes.append("index is empty — run: repo-index build .")
        return _empty(notes, db_path=resolved_db)

    notes.append(f"index: {count} symbols at {resolved_db}")

    # 1. Collect recently changed symbols from git (implicit retrieval targets)
    root = repo_root or Path.cwd()
    recently_changed: list[str] = _recently_changed_symbols(root, notes)

    # 2. Find relevant symbols
    symbols = _fetch_symbols(conn, plan, budget, notes, recently_changed=recently_changed)

    # 3. Git diff + commit log if requested
    git_diff = ""
    if plan.git_history:
        git_diff = _git_diff(root, plan.query, notes)

    # 4. Assemble and budget-cap
    raw_text = _format(symbols, git_diff, plan)
    token_cap = int(budget.max_tokens * _CONTEXT_BUDGET_RATIO)
    if estimate_tokens(raw_text) > token_cap:
        raw_text = _trim(raw_text, token_cap)
        notes.append(f"context trimmed to fit ~{token_cap}-token budget")

    return ContextBundle(
        symbols=symbols,
        git_diff=git_diff,
        raw_text=raw_text,
        token_estimate=estimate_tokens(raw_text),
        retrieval_notes=notes,
        db_path=resolved_db,
        recently_changed_symbols=recently_changed,
    )


# ---------------------------------------------------------------------------
# Symbol retrieval
# ---------------------------------------------------------------------------

def _fetch_symbols(
    conn,
    plan: RetrievalPlan,
    budget: ContextBudget,
    notes: list[str],
    recently_changed: list[str] | None = None,
) -> list[SymbolContext]:
    depth = min(budget.retrieval_depth, 4)
    max_syms = 4 if budget.max_tokens < 5000 else 7

    # Build the call graph once for the whole batch — reused by every get_context() call
    G = build_call_graph_cached(conn)

    # Priority 1: explicit symbol targets from the plan (full depth)
    explicit: list[SymbolContext] = []
    for name in plan.symbol_targets:
        ctx = _ri_retrieval.get_context(conn, name, callgraph_depth=depth, graph=G)
        if ctx:
            sym = _to_sym(ctx, rank=len(explicit) + 1, score=1.0)
            explicit.append(sym)
        else:
            notes.append(f"symbol '{name}' not found in index")

    seen: set[str] = {s.name for s in explicit}

    # Priority 2: recently-changed symbols as implicit targets (supporting depth)
    git_syms: list[SymbolContext] = []
    if recently_changed:
        git_budget = max(0, min(2, max_syms - len(explicit)))
        supporting_depth = max(1, depth - 1)
        for name in recently_changed[:git_budget * 2]:
            if name in seen or len(git_syms) >= git_budget:
                continue
            ctx = _ri_retrieval.get_context(conn, name, callgraph_depth=supporting_depth, graph=G)
            if ctx:
                rank = len(explicit) + len(git_syms) + 1
                git_syms.append(_to_sym(ctx, rank=rank, score=0.7))
                seen.add(name)

    if git_syms:
        notes.append(f"added {len(git_syms)} recently-changed symbol(s) as context")

    # Priority 3: FTS search for remaining budget (supporting depth for non-rank-1)
    remaining = max_syms - len(explicit) - len(git_syms)
    search_results: list[SymbolContext] = []
    if remaining > 0 and plan.query:
        is_first = not explicit and not git_syms
        search_results = _search(conn, plan.query, depth, remaining, notes, G, is_first_batch=is_first)

    # Merge, preserving priority order
    deduped = list(explicit) + list(git_syms)
    for s in search_results:
        if s.name not in seen:
            seen.add(s.name)
            deduped.append(s)

    # Assign final ranks to any unranked symbols
    for i, s in enumerate(deduped):
        if s.rank == 0:
            s.rank = i + 1

    # Strip callgraph from supporting symbols (rank > 1) when call chains not needed
    if not plan.include_call_chains:
        for s in deduped:
            s.callgraph = []
    elif len(deduped) > 1:
        # Rank-1 keeps full callgraph; others get a trimmed version to save budget
        for s in deduped[1:]:
            s.callgraph = s.callgraph[:4]

    return deduped


def _search(
    conn,
    query: str,
    depth: int,
    limit: int,
    notes: list[str],
    graph,
    is_first_batch: bool = False,
) -> list[SymbolContext]:
    """Ranked FTS search, falling back to individual keywords if full query misses."""
    results = _ri_retrieval.search(conn, query, limit=limit)
    if results:
        return _hydrate(conn, results, depth, graph, is_first_batch=is_first_batch)

    # Fall back to individual significant keywords
    keywords = _keywords(query)
    for kw in keywords:
        results = _ri_retrieval.search(conn, kw, limit=limit)
        if results:
            notes.append(f"no results for '{query}', matched on '{kw}'")
            return _hydrate(conn, results, depth, graph, is_first_batch=is_first_batch)

    notes.append(f"no symbols found for '{query}' or its keywords {keywords}")
    return []


def _hydrate(conn, search_results, depth: int, graph, is_first_batch: bool = False) -> list[SymbolContext]:
    """Fetch full context for each search result, reusing the shared graph.

    The first result in a first-batch gets full depth; subsequent results get supporting depth.
    """
    out = []
    supporting_depth = max(1, depth - 1)
    for i, r in enumerate(search_results):
        sym_depth = depth if (is_first_batch and i == 0) else supporting_depth
        ctx = _ri_retrieval.get_context(conn, r.name, callgraph_depth=sym_depth, graph=graph)
        if ctx:
            rank = i + 1
            score = getattr(r, "composite_score", 0.0)
            out.append(_to_sym(ctx, rank=rank, score=score))
    return out


def _to_sym(ctx, rank: int = 0, score: float = 0.0) -> SymbolContext:
    return SymbolContext(
        name=ctx.name,
        kind=ctx.kind,
        file_path=ctx.file_path,
        start_line=ctx.start_line,
        end_line=ctx.end_line,
        calls=ctx.calls,
        called_by=ctx.called_by,
        callgraph=ctx.callgraph,
        imports=ctx.file_imports,
        rank=rank,
        relevance_score=score,
    )


# ---------------------------------------------------------------------------
# Git diff
# ---------------------------------------------------------------------------

def _recently_changed_symbols(root: Path, notes: list[str]) -> list[str]:
    """Return symbol names extracted from git diff since HEAD~3, silently returning [] on failure."""
    if not _AVAILABLE:
        return []
    try:
        if not _ri_git.is_git_repo(root):
            return []
        names = _ri_git.extract_changed_symbol_names(root)
        if names:
            notes.append(f"git: {len(names)} recently-changed symbol(s) detected")
        return names
    except Exception:
        return []


def _git_diff(root: Path, scope: str, notes: list[str]) -> str:
    """Return a compact git section: changed-file stats + recent commit log."""
    parts: list[str] = []
    try:
        # Stat-only diff for last 3 commits
        stat = subprocess.run(
            ["git", "diff", "--stat", "HEAD~3", "HEAD"],
            cwd=root, capture_output=True, text=True, timeout=5,
        )
        if stat.returncode != 0 or not stat.stdout.strip():
            stat = subprocess.run(
                ["git", "diff", "--stat"],
                cwd=root, capture_output=True, text=True, timeout=5,
            )
        if stat.stdout.strip():
            scope_keywords = _keywords(scope)
            lines = stat.stdout.strip().splitlines()
            relevant = [ln for ln in lines if any(kw.lower() in ln.lower() for kw in scope_keywords)]
            if not relevant:
                relevant = lines[:8]
            parts.append("Changed files:\n" + "\n".join(f"  {ln}" for ln in relevant[:10]))
    except (subprocess.TimeoutExpired, FileNotFoundError):
        notes.append("git not available for diff")

    # Recent commit log
    if _AVAILABLE:
        try:
            log = _ri_git.commit_log_summary(root, n=5)
            if log:
                parts.append("Recent commits:\n" + "\n".join(f"  {ln}" for ln in log.splitlines()))
        except Exception:
            pass

    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------

def _format(symbols: list[SymbolContext], git_diff: str, plan: RetrievalPlan) -> str:
    if not symbols and not git_diff:
        return f"CONTEXT\nQuery: {plan.query}\n[No symbols found in index matching this query.]"

    parts = [f"CONTEXT\nQuery: {plan.query}\n"]

    if symbols:
        parts.append(f"Symbols ({len(symbols)} found):")
        parts.append("─" * 60)
        for sym in symbols:
            parts.append(_format_symbol(sym))
        parts.append("─" * 60)

    if git_diff:
        parts.append("")
        parts.append(git_diff)

    return "\n".join(parts)


def _format_symbol(sym: SymbolContext) -> str:
    rank_tag = f"  #rank:{sym.rank}" if sym.rank else ""
    lines = [f"\n{sym.name}  [{sym.kind}]  {sym.file_path}:{sym.start_line}–{sym.end_line}{rank_tag}"]
    if sym.fqid:
        lines.append(f"  fqid:      {sym.fqid}")
    if sym.module:
        lines.append(f"  module:    {sym.module}")
    if sym.calls:
        calls_str = ", ".join(sym.calls[:8])
        if len(sym.calls) > 8:
            calls_str += f"  (+{len(sym.calls) - 8} more)"
        lines.append(f"  calls:     {calls_str}")
    if sym.called_by:
        callers_str = ", ".join(sym.called_by[:6])
        if len(sym.called_by) > 6:
            callers_str += f"  (+{len(sym.called_by) - 6} more)"
        lines.append(f"  called_by: {callers_str}")
    if sym.imports:
        lines.append(f"  imports:   {', '.join(sym.imports[:6])}")
    if sym.callgraph:
        lines.append("  call graph:")
        for hop in sym.callgraph[:8]:
            lines.append(f"    → {hop}")
    return "\n".join(lines)


def _trim(text: str, token_cap: int) -> str:
    """Hard-trim text to fit within token cap."""
    char_cap = token_cap * 4
    if len(text) <= char_cap:
        return text
    trimmed = text[:char_cap]
    # Trim to last newline so we don't cut mid-line
    last_nl = trimmed.rfind("\n")
    if last_nl > char_cap // 2:
        trimmed = trimmed[:last_nl]
    return trimmed + "\n\n[... context trimmed to fit token budget ...]"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _keywords(text: str) -> list[str]:
    """Extract significant keywords from a natural-language string."""
    words = re.findall(r"[a-zA-Z_][a-zA-Z0-9_]*", text)
    return [w for w in words if w.lower() not in _STOP_WORDS and len(w) > 2]


def _resolve_db(repo_root: Optional[Path]) -> Path:
    import os
    env = os.environ.get("REPO_INDEX_DB")
    if env:
        return Path(env)
    if repo_root:
        # Use the same per-repo naming convention as the CLI and MCP server
        db_dir = Path.home() / ".local" / "share" / "repo-index"
        # Resolve to git root if possible, then use its directory name
        if _AVAILABLE:
            git_r = _ri_git.git_root(repo_root)
            effective = git_r if git_r else repo_root
        else:
            effective = repo_root
        named = db_dir / f"{effective.name}.db"
        if named.exists():
            return named
    return _DEFAULT_DB


def _empty(notes: list[str], db_path: Optional[Path] = None) -> ContextBundle:
    return ContextBundle(
        symbols=[],
        git_diff="",
        raw_text="",
        token_estimate=0,
        retrieval_notes=notes,
        db_path=db_path,
        recently_changed_symbols=[],
    )
