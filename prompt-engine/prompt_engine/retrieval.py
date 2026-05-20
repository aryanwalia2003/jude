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


@dataclass
class ContextBundle:
    symbols: list[SymbolContext]
    git_diff: str
    raw_text: str               # assembled prompt-ready text
    token_estimate: int
    retrieval_notes: list[str]
    db_path: Optional[Path] = None

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

    # 1. Find relevant symbols
    symbols = _fetch_symbols(conn, plan, budget, notes)

    # 2. Git diff if requested
    git_diff = ""
    if plan.git_history:
        git_diff = _git_diff(repo_root or Path.cwd(), plan.query, notes)

    # 3. Assemble and budget-cap
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
    )


# ---------------------------------------------------------------------------
# Symbol retrieval
# ---------------------------------------------------------------------------

def _fetch_symbols(conn, plan: RetrievalPlan, budget: ContextBudget, notes: list[str]) -> list[SymbolContext]:
    depth = min(budget.retrieval_depth, 4)
    max_syms = 4 if budget.max_tokens < 5000 else 7

    # Priority 1: explicit symbol targets from the plan
    explicit: list[SymbolContext] = []
    for name in plan.symbol_targets:
        ctx = _ri_retrieval.get_context(conn, name, callgraph_depth=depth)
        if ctx:
            explicit.append(_to_sym(ctx))
        else:
            notes.append(f"symbol '{name}' not found in index")

    # Priority 2: FTS search for remaining budget
    remaining = max_syms - len(explicit)
    search_results: list[SymbolContext] = []
    if remaining > 0 and plan.query:
        search_results = _search(conn, plan.query, depth, remaining, notes)

    # Deduplicate by name, explicit targets take precedence
    seen: set[str] = {s.name for s in explicit}
    deduped = list(explicit)
    for s in search_results:
        if s.name not in seen:
            seen.add(s.name)
            deduped.append(s)

    # If include_call_chains is False, strip callgraph
    if not plan.include_call_chains:
        for s in deduped:
            s.callgraph = []

    return deduped


def _search(conn, query: str, depth: int, limit: int, notes: list[str]) -> list[SymbolContext]:
    """Search FTS, falling back to individual keywords if full query misses."""
    results = _ri_retrieval.search(conn, query, limit=limit)
    if results:
        return _hydrate(conn, results, depth)

    # Fall back to individual significant keywords
    keywords = _keywords(query)
    for kw in keywords:
        results = _ri_retrieval.search(conn, kw, limit=limit)
        if results:
            notes.append(f"no results for '{query}', matched on '{kw}'")
            return _hydrate(conn, results, depth)

    notes.append(f"no symbols found for '{query}' or its keywords {keywords}")
    return []


def _hydrate(conn, search_results, depth: int) -> list[SymbolContext]:
    """Fetch full context for each search result."""
    out = []
    for r in search_results:
        ctx = _ri_retrieval.get_context(conn, r.name, callgraph_depth=depth)
        if ctx:
            out.append(_to_sym(ctx))
    return out


def _to_sym(ctx) -> SymbolContext:
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
    )


# ---------------------------------------------------------------------------
# Git diff
# ---------------------------------------------------------------------------

def _git_diff(root: Path, scope: str, notes: list[str]) -> str:
    """Return a compact git diff showing recent changes near the scope."""
    try:
        # Stat-only diff for last 3 commits — shows which files changed
        stat = subprocess.run(
            ["git", "diff", "--stat", "HEAD~3", "HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if stat.returncode != 0 or not stat.stdout.strip():
            # Fall back to unstaged diff
            stat = subprocess.run(
                ["git", "diff", "--stat"],
                cwd=root, capture_output=True, text=True, timeout=5,
            )
        if not stat.stdout.strip():
            return ""

        # Filter to files plausibly related to the scope
        scope_keywords = _keywords(scope)
        lines = stat.stdout.strip().splitlines()
        relevant = [ln for ln in lines if any(kw.lower() in ln.lower() for kw in scope_keywords)]
        if not relevant:
            relevant = lines[:8]  # show at most 8 most recent changes if no match

        return "Recent changes:\n" + "\n".join(f"  {ln}" for ln in relevant[:10])
    except (subprocess.TimeoutExpired, FileNotFoundError):
        notes.append("git not available for diff")
        return ""


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
    lines = [f"\n{sym.name}  [{sym.kind}]  {sym.file_path}:{sym.start_line}–{sym.end_line}"]
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
    return _DEFAULT_DB


def _empty(notes: list[str], db_path: Optional[Path] = None) -> ContextBundle:
    return ContextBundle(
        symbols=[],
        git_diff="",
        raw_text="",
        token_estimate=0,
        retrieval_notes=notes,
        db_path=db_path,
    )
