"""Retrieval engine — context assembly before LLM reasoning.

Three retrieval modes:
  search()      — multi-signal ranked FTS5 search across symbol names
  get_callgraph() — transitive callees (what does this depend on)
  get_impact()    — transitive callers (what breaks if this changes)
  get_context()   — full structured context for a symbol
"""

import math
import sqlite3
from dataclasses import dataclass, field

import networkx as nx

from . import db
from .graph import build_call_graph_cached, reachable_from, reverse_reachable


@dataclass
class SearchResult:
    name: str
    kind: str
    file_path: str
    start_line: int
    end_line: int
    bm25_score: float = 0.0
    caller_count: int = 0
    last_indexed_at: int = 0
    composite_score: float = 0.0


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
    """FTS search with multi-signal re-ranking: BM25 + caller-hub + recency + path-match."""
    rows = db.search_symbols_ranked(conn, query, kind=kind, limit=limit)
    if not rows:
        return []

    keywords = {t.lower() for t in query.split() if t}
    max_time = max((r["last_indexed_at"] for r in rows), default=1) or 1

    results: list[SearchResult] = []
    for row in rows:
        # BM25: FTS5 returns negative values — flip so higher = more relevant
        bm25 = -(row["bm25_score"])
        # Caller-hub: log-scaled number of callers — frequently-called symbols rank higher
        hub = math.log1p(row["caller_count"]) * 0.5
        # Recency: recently indexed files are more likely to be in-scope
        recency = (row["last_indexed_at"] / max_time) * 0.3
        # Path bonus: file path contains query keywords
        path_lower = row["file_path"].lower()
        path_bonus = 0.4 * sum(1 for kw in keywords if kw in path_lower)
        composite = bm25 + hub + recency + path_bonus
        results.append(SearchResult(
            name=row["name"],
            kind=row["kind"],
            file_path=row["file_path"],
            start_line=row["start_line"],
            end_line=row["end_line"],
            bm25_score=row["bm25_score"],
            caller_count=row["caller_count"],
            last_indexed_at=row["last_indexed_at"],
            composite_score=composite,
        ))

    results.sort(key=lambda r: r.composite_score, reverse=True)
    return results[:limit]


def get_callgraph(conn: sqlite3.Connection, name: str, max_depth: int = 3) -> list[str]:
    """Return names of symbols transitively called by name (BFS, depth-limited)."""
    G = build_call_graph_cached(conn)
    return reachable_from(G, name, max_depth)


def get_impact(conn: sqlite3.Connection, name: str, max_depth: int = 3) -> list[str]:
    """Return names of symbols that transitively call name (blast radius)."""
    G = build_call_graph_cached(conn)
    return reverse_reachable(G, name, max_depth)


def get_context(
    conn: sqlite3.Connection,
    name: str,
    callgraph_depth: int = 2,
    graph: nx.DiGraph | None = None,
) -> RetrievalContext | None:
    """Assemble full context for a symbol. Pass graph= to reuse a cached graph across batch calls."""
    rows = db.query_symbol(conn, name)
    if not rows:
        return None

    row = rows[0]
    G = graph if graph is not None else build_call_graph_cached(conn)

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
