"""Retrieval engine — context assembly before LLM reasoning.

Three retrieval modes:
  search()      — FTS5 lexical search across symbol names
  get_callgraph() — transitive callees (what does this depend on)
  get_impact()    — transitive callers (what breaks if this changes)
  get_context()   — full structured context for a symbol
"""

import sqlite3
from dataclasses import dataclass, field

from . import db
from .graph import build_call_graph, reachable_from, reverse_reachable


@dataclass
class SearchResult:
    name: str
    kind: str
    file_path: str
    start_line: int
    end_line: int


@dataclass
class RetrievalContext:
    """Assembled context for one symbol — ready to feed to an LLM."""
    name: str
    kind: str
    file_path: str
    start_line: int
    end_line: int
    calls: list[str] = field(default_factory=list)        # direct callees
    called_by: list[str] = field(default_factory=list)    # direct callers
    file_imports: list[str] = field(default_factory=list) # module-level imports
    callgraph: list[str] = field(default_factory=list)    # transitive callees (BFS)
    impact: list[str] = field(default_factory=list)       # transitive callers (BFS)


def search(
    conn: sqlite3.Connection,
    query: str,
    kind: str | None = None,
    limit: int = 20,
) -> list[SearchResult]:
    rows = db.search_symbols(conn, query, kind=kind, limit=limit)
    return [
        SearchResult(
            name=row["name"],
            kind=row["kind"],
            file_path=row["file_path"],
            start_line=row["start_line"],
            end_line=row["end_line"],
        )
        for row in rows
    ]


def get_callgraph(conn: sqlite3.Connection, name: str, max_depth: int = 3) -> list[str]:
    """Return names of symbols transitively called by name (BFS, depth-limited)."""
    G = build_call_graph(conn)
    return reachable_from(G, name, max_depth)


def get_impact(conn: sqlite3.Connection, name: str, max_depth: int = 3) -> list[str]:
    """Return names of symbols that transitively call name (blast radius)."""
    G = build_call_graph(conn)
    return reverse_reachable(G, name, max_depth)


def get_context(
    conn: sqlite3.Connection,
    name: str,
    callgraph_depth: int = 2,
) -> RetrievalContext | None:
    rows = db.query_symbol(conn, name)
    if not rows:
        return None

    row = rows[0]
    G = build_call_graph(conn)

    direct_calls = _direct_calls(conn, name)
    direct_callers = [r["caller"] for r in db.query_callers(conn, name)]
    imports = [r["import_name"] for r in db.query_imports(conn, row["file_path"])]

    return RetrievalContext(
        name=name,
        kind=row["kind"],
        file_path=row["file_path"],
        start_line=row["start_line"],
        end_line=row["end_line"],
        calls=direct_calls,
        called_by=direct_callers,
        file_imports=imports,
        callgraph=reachable_from(G, name, callgraph_depth),
        impact=reverse_reachable(G, name, callgraph_depth),
    )


def _direct_calls(conn: sqlite3.Connection, name: str) -> list[str]:
    rows = conn.execute(
        """SELECT DISTINCT r.to_name
           FROM relations r
           JOIN symbols s ON r.from_id = s.id
           WHERE s.name = ? AND r.relation = 'CALLS'
           ORDER BY r.to_name""",
        (name,),
    ).fetchall()
    return [row["to_name"] for row in rows]
