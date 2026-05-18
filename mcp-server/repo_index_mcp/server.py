"""MCP server — repo-index Layer 1 intelligence for AI agents.

Tools:
  Search:  search_symbols
  Symbols: get_symbol, get_symbol_by_fqid, get_callers, get_owned_symbols, get_module_symbols
  Graph:   get_callgraph, get_impact, get_context
  Meta:    get_stats, list_files, build_index
"""

from pathlib import Path

from mcp.server.fastmcp import FastMCP

from repo_index import db, git, indexer, retrieval

from .connection import open_connection
from .serializers import context_to_dict, row_to_dict, rows_to_dicts, search_result_to_dict

mcp = FastMCP(
    "repo-index",
    instructions=(
        "Repository intelligence: AST-indexed symbols, call graphs, and dependency analysis. "
        "Call build_index(path) first if the index is empty or outdated."
    ),
)


# ── Search ────────────────────────────────────────────────────────────────────

@mcp.tool()
def search_symbols(query: str, kind: str | None = None, limit: int = 20) -> list[dict]:
    """Full-text search (FTS5, prefix-matched) over all indexed symbols.

    Args:
        query: Search terms, e.g. "parse_import" or "build index".
        kind: Optional kind filter — function, class, method, module.
        limit: Maximum results (default 20).
    """
    conn = open_connection()
    results = retrieval.search(conn, query, kind=kind, limit=limit)
    return [search_result_to_dict(r) for r in results]


# ── Symbol Lookup ─────────────────────────────────────────────────────────────

@mcp.tool()
def get_symbol(name: str) -> list[dict]:
    """Look up all indexed occurrences of a symbol by exact name.

    Returns a list because the same name can appear in multiple files.
    Each entry includes: kind, file_path, start_line, end_line, language, fqid.
    """
    conn = open_connection()
    return rows_to_dicts(db.query_symbol(conn, name))


@mcp.tool()
def get_symbol_by_fqid(fqid: str) -> dict | None:
    """Look up a symbol by fully-qualified identifier (e.g. 'repo_index.db.open_db').

    Returns None if not found.
    """
    conn = open_connection()
    row = db.query_symbol_by_fqid(conn, fqid)
    return row_to_dict(row) if row else None


@mcp.tool()
def get_callers(name: str) -> list[dict]:
    """Find all symbols that directly call the given function or method.

    Returns: caller name, kind, file_path, start_line.
    """
    conn = open_connection()
    return rows_to_dicts(db.query_callers(conn, name))


@mcp.tool()
def get_owned_symbols(class_name: str) -> list[dict]:
    """Return all methods and attributes defined inside a class."""
    conn = open_connection()
    return rows_to_dicts(db.query_owned_symbols(conn, class_name))


@mcp.tool()
def get_module_symbols(module_name: str) -> list[dict]:
    """List all symbols in a module (e.g. 'repo_index.db').

    Excludes the module-level placeholder symbol itself.
    """
    conn = open_connection()
    return rows_to_dicts(db.query_module_symbols(conn, module_name))


# ── Call Graph ────────────────────────────────────────────────────────────────

@mcp.tool()
def get_callgraph(name: str, max_depth: int = 3) -> list[str]:
    """Return symbols transitively called by name — the dependency chain (BFS forward).

    Args:
        name: Starting symbol.
        max_depth: BFS depth limit (default 3).
    """
    conn = open_connection()
    return retrieval.get_callgraph(conn, name, max_depth=max_depth)


@mcp.tool()
def get_impact(name: str, max_depth: int = 3) -> list[str]:
    """Return symbols that transitively call name — blast radius analysis (BFS backward).

    Use before changing a symbol to understand what else might break.
    """
    conn = open_connection()
    return retrieval.get_impact(conn, name, max_depth=max_depth)


@mcp.tool()
def get_context(name: str, depth: int = 2) -> dict | None:
    """Assemble full retrieval context for a symbol — ready for LLM reasoning.

    Returns: location, direct calls, direct callers, file imports,
             transitive callgraph, and impact (blast radius).
    Returns None if the symbol is not indexed.
    """
    conn = open_connection()
    ctx = retrieval.get_context(conn, name, callgraph_depth=depth)
    return context_to_dict(ctx) if ctx else None


# ── Meta ──────────────────────────────────────────────────────────────────────

@mcp.tool()
def get_stats() -> dict:
    """Return index statistics: file count, symbol count, relations, breakdown by kind and language."""
    conn = open_connection()
    return db.stats(conn)


@mcp.tool()
def list_files() -> list[dict]:
    """List all indexed files with path, language, and content hash."""
    conn = open_connection()
    rows = conn.execute(
        "SELECT path, language, content_hash, last_indexed_at FROM files ORDER BY path"
    ).fetchall()
    return rows_to_dicts(rows)


@mcp.tool()
def build_index(path: str = ".") -> dict:
    """Index a repository directory. Call this first if the index is empty or outdated.

    Args:
        path: Path to the repository root (default: current directory).

    Returns: scanned, indexed, skipped, removed, symbols_added, relations_added, errors.
    """
    root = Path(path).resolve()
    conn = open_connection()
    branch = git.current_branch(root)
    stats = indexer.build_index(conn, root, branch=branch or None)
    return {
        "branch": stats.branch,
        "scanned": stats.scanned,
        "indexed": stats.indexed,
        "skipped": stats.skipped,
        "removed": stats.removed,
        "symbols_added": stats.symbols_added,
        "relations_added": stats.relations_added,
        "errors": stats.errors,
    }


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
