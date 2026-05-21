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

from .connection import db_for_repo, open_connection_for
from .serializers import context_to_dict, row_to_dict, rows_to_dicts, search_result_to_dict

mcp = FastMCP(
    "repo-index",
    instructions=(
        "Repository intelligence: AST-indexed symbols, call graphs, and dependency analysis. "
        "Call build_index(path) first if the index is empty or outdated. "
        "Pass repo_path to all tools to route queries to the correct per-repo index."
    ),
)


# ── Search ────────────────────────────────────────────────────────────────────

@mcp.tool()
def search_symbols(
    query: str,
    kind: str | None = None,
    limit: int = 20,
    repo_path: str | None = None,
) -> list[dict]:
    """Full-text search (FTS5, prefix-matched) over all indexed symbols.

    Args:
        query: Search terms, e.g. "parse_import" or "build index".
        kind: Optional kind filter — function, class, method, module.
        limit: Maximum results (default 20).
        repo_path: Repo root path to select which index to query.
    """
    conn = open_connection_for(repo_path)
    results = retrieval.search(conn, query, kind=kind, limit=limit)
    return [search_result_to_dict(r) for r in results]


# ── Symbol Lookup ─────────────────────────────────────────────────────────────

@mcp.tool()
def get_symbol(name: str, repo_path: str | None = None) -> list[dict]:
    """Look up all indexed occurrences of a symbol by exact name.

    Returns a list because the same name can appear in multiple files.
    Each entry includes: kind, file_path, start_line, end_line, language, fqid.

    Args:
        repo_path: Repo root path to select which index to query.
    """
    conn = open_connection_for(repo_path)
    return rows_to_dicts(db.query_symbol(conn, name))


@mcp.tool()
def get_symbol_by_fqid(fqid: str, repo_path: str | None = None) -> dict | None:
    """Look up a symbol by fully-qualified identifier (e.g. 'repo_index.db.open_db').

    Returns None if not found.

    Args:
        repo_path: Repo root path to select which index to query.
    """
    conn = open_connection_for(repo_path)
    row = db.query_symbol_by_fqid(conn, fqid)
    return row_to_dict(row) if row else None


@mcp.tool()
def get_callers(name: str, repo_path: str | None = None) -> list[dict]:
    """Find all symbols that directly call the given function or method.

    Returns: caller name, kind, file_path, start_line.

    Args:
        repo_path: Repo root path to select which index to query.
    """
    conn = open_connection_for(repo_path)
    return rows_to_dicts(db.query_callers(conn, name))


@mcp.tool()
def get_owned_symbols(class_name: str, repo_path: str | None = None) -> list[dict]:
    """Return all methods and attributes defined inside a class.

    Args:
        repo_path: Repo root path to select which index to query.
    """
    conn = open_connection_for(repo_path)
    return rows_to_dicts(db.query_owned_symbols(conn, class_name))


@mcp.tool()
def get_module_symbols(module_name: str, repo_path: str | None = None) -> list[dict]:
    """List all symbols in a module (e.g. 'repo_index.db').

    Excludes the module-level placeholder symbol itself.

    Args:
        repo_path: Repo root path to select which index to query.
    """
    conn = open_connection_for(repo_path)
    return rows_to_dicts(db.query_module_symbols(conn, module_name))


# ── Call Graph ────────────────────────────────────────────────────────────────

@mcp.tool()
def get_callgraph(
    name: str,
    max_depth: int = 3,
    repo_path: str | None = None,
) -> list[str]:
    """Return symbols transitively called by name — the dependency chain (BFS forward).

    Args:
        name: Starting symbol.
        max_depth: BFS depth limit (default 3).
        repo_path: Repo root path to select which index to query.
    """
    conn = open_connection_for(repo_path)
    return retrieval.get_callgraph(conn, name, max_depth=max_depth)


@mcp.tool()
def get_impact(
    name: str,
    max_depth: int = 3,
    repo_path: str | None = None,
) -> list[str]:
    """Return symbols that transitively call name — blast radius analysis (BFS backward).

    Use before changing a symbol to understand what else might break.

    Args:
        repo_path: Repo root path to select which index to query.
    """
    conn = open_connection_for(repo_path)
    return retrieval.get_impact(conn, name, max_depth=max_depth)


@mcp.tool()
def get_context(
    name: str,
    depth: int = 2,
    repo_path: str | None = None,
) -> dict | None:
    """Assemble full retrieval context for a symbol — ready for LLM reasoning.

    Returns: location, direct calls, direct callers, file imports,
             transitive callgraph, and impact (blast radius).
    Returns None if the symbol is not indexed.

    Args:
        repo_path: Repo root path to select which index to query.
    """
    conn = open_connection_for(repo_path)
    ctx = retrieval.get_context(conn, name, callgraph_depth=depth)
    return context_to_dict(ctx) if ctx else None


# ── Meta ──────────────────────────────────────────────────────────────────────

@mcp.tool()
def get_stats(repo_path: str | None = None) -> dict:
    """Return index statistics: file count, symbol count, relations, breakdown by kind and language.

    Args:
        repo_path: Repo root path to select which index to query.
    """
    conn = open_connection_for(repo_path)
    stats = db.stats(conn)
    stats["db_path"] = str(db_for_repo(repo_path) if repo_path else None)
    stats["repo_root"] = db.get_repo_root(conn) or ""
    return stats


@mcp.tool()
def list_files(repo_path: str | None = None) -> list[dict]:
    """List all indexed files with path, language, and content hash.

    Args:
        repo_path: Repo root path to select which index to query.
    """
    conn = open_connection_for(repo_path)
    rows = conn.execute(
        "SELECT path, language, content_hash, last_indexed_at FROM files ORDER BY path"
    ).fetchall()
    return rows_to_dicts(rows)


@mcp.tool()
def build_index(path: str = ".") -> dict:
    """Index a repository directory. Routes to the per-repo DB automatically.

    The DB is stored at ~/.local/share/repo-index/<repo-name>.db.
    Call this once per repo before querying. Pass the same path to all
    query tools as repo_path to target that index.

    Args:
        path: Path to the repository root (default: current directory).

    Returns: db_path, repo_root, scanned, indexed, skipped, removed,
             symbols_added, relations_added, errors.
    """
    root = Path(path).resolve()
    target_db = db_for_repo(str(root))
    conn = db.open_db(target_db)

    branch = git.current_branch(root)
    stats = indexer.build_index(conn, root, branch=branch or None)
    db.set_repo_root(conn, str(root))

    return {
        "db_path": str(target_db),
        "repo_root": str(root),
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
