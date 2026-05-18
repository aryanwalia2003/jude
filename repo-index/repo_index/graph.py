"""NetworkX call graph built from the relations table.

The graph is built on demand — no persistent caching. For large repos
this is fast enough; add caching at the call site if needed.

Edge A → B means: A CALLS B.
"""

import sqlite3
from collections import deque

import networkx as nx


def build_call_graph(conn: sqlite3.Connection) -> nx.DiGraph:
    """Directed graph of CALLS relations. Nodes are symbol names."""
    G: nx.DiGraph = nx.DiGraph()
    rows = conn.execute(
        """SELECT s.name AS caller, r.to_name AS callee
           FROM relations r
           JOIN symbols s ON r.from_id = s.id
           WHERE r.relation = 'CALLS' AND s.kind != 'module'"""
    ).fetchall()
    for row in rows:
        G.add_edge(row["caller"], row["callee"])
    return G


def reachable_from(G: nx.DiGraph, start: str, max_depth: int) -> list[str]:
    """BFS forward from start (what start transitively calls). Excludes start itself."""
    return _bfs(G, start, max_depth, reverse=False)


def reverse_reachable(G: nx.DiGraph, start: str, max_depth: int) -> list[str]:
    """BFS backward from start (who transitively calls start — impact/blast radius)."""
    return _bfs(G, start, max_depth, reverse=True)


def _bfs(G: nx.DiGraph, start: str, max_depth: int, reverse: bool) -> list[str]:
    if start not in G:
        return []
    graph = G.reverse(copy=False) if reverse else G
    visited: set[str] = {start}
    result: list[str] = []
    queue: deque[tuple[str, int]] = deque([(start, 0)])
    while queue:
        node, depth = queue.popleft()
        if depth >= max_depth:
            continue
        for neighbor in graph.successors(node):
            if neighbor not in visited:
                visited.add(neighbor)
                result.append(neighbor)
                queue.append((neighbor, depth + 1))
    return result
