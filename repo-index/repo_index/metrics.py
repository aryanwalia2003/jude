"""Code metrics and architecture health analysis — pure SQL + NetworkX, no LLM."""

import sqlite3
from dataclasses import dataclass
from typing import Optional

import networkx as nx

from . import graph


@dataclass
class SymbolMetric:
    """Per-symbol structural metrics."""

    name: str
    kind: str  # function | class | method | module
    file_path: str
    module: str
    start_line: int
    end_line: int
    line_count: int  # end_line - start_line + 1
    fan_in: int  # number of callers
    fan_out: int  # number of callees
    method_count: int  # methods owned (classes only)


@dataclass
class ModuleCoupling:
    """Cross-module dependency strength."""

    from_module: str
    to_module: str
    call_count: int  # number of cross-module CALLS edges


def symbol_metrics(conn: sqlite3.Connection) -> list[SymbolMetric]:
    """Compute metrics for all symbols: line counts, fan-in/out, method counts.

    Returns all symbols with their structural metrics. Module-level sentinels excluded.
    """
    cursor = conn.cursor()

    # Build three aggregations: fan_in, fan_out, method_count
    # Then LEFT JOIN them all to symbols table
    sql = """
    WITH fan_in_counts AS (
        SELECT to_symbol_id, COUNT(*) as fan_in
        FROM relations
        WHERE relation = 'CALLS' AND to_symbol_id IS NOT NULL
        GROUP BY to_symbol_id
    ),
    fan_out_counts AS (
        SELECT from_id, COUNT(*) as fan_out
        FROM relations
        WHERE relation = 'CALLS'
        GROUP BY from_id
    ),
    method_counts AS (
        SELECT owner_symbol_id, COUNT(*) as method_count
        FROM symbols
        WHERE owner_symbol_id IS NOT NULL
        GROUP BY owner_symbol_id
    )
    SELECT
        s.id, s.name, s.kind, s.file_path, s.module, s.start_line, s.end_line,
        (s.end_line - s.start_line + 1) as line_count,
        COALESCE(fi.fan_in, 0) as fan_in,
        COALESCE(fo.fan_out, 0) as fan_out,
        COALESCE(mc.method_count, 0) as method_count
    FROM symbols s
    LEFT JOIN fan_in_counts fi ON fi.to_symbol_id = s.id
    LEFT JOIN fan_out_counts fo ON fo.from_id = s.id
    LEFT JOIN method_counts mc ON mc.owner_symbol_id = s.id
    WHERE s.kind != 'module'
    ORDER BY s.name
    """

    cursor.execute(sql)
    rows = cursor.fetchall()

    return [
        SymbolMetric(
            name=row[1],
            kind=row[2],
            file_path=row[3],
            module=row[4],
            start_line=row[5],
            end_line=row[6],
            line_count=row[7],
            fan_in=row[8],
            fan_out=row[9],
            method_count=row[10],
        )
        for row in rows
    ]


def hotspots(conn: sqlite3.Connection, top_n: int = 10) -> list[SymbolMetric]:
    """Return top N most-called symbols (highest fan-in).

    These are central hubs in the codebase — good targets for refactoring
    because changes propagate widely.
    """
    all_metrics = symbol_metrics(conn)
    # Filter out builtins and sort by fan_in descending
    filtered = [
        m
        for m in all_metrics
        if m.name not in ("print", "error", "console", "render", "stringify")
        and m.module != ""
    ]
    sorted_by_fan_in = sorted(filtered, key=lambda m: m.fan_in, reverse=True)
    return sorted_by_fan_in[:top_n]


def dead_code(conn: sqlite3.Connection) -> list[SymbolMetric]:
    """Return all functions/methods with zero callers.

    Excludes: main, __init__, constructors, obvious framework handlers.
    User decides what's truly dead.
    """
    all_metrics = symbol_metrics(conn)

    # Exclude known safe symbols
    excluded_names = {
        "main",
        "__init__",
        "init",
        "constructor",
        "render",
        "handler",
        "test",
        "__main__",
    }
    excluded_suffixes = ("Handler", "handler", "Test", "test")

    dead = [
        m
        for m in all_metrics
        if m.fan_in == 0
        and m.kind in ("function", "method")
        and m.name not in excluded_names
        and not any(m.name.endswith(suffix) for suffix in excluded_suffixes)
    ]

    return sorted(dead, key=lambda m: m.line_count, reverse=True)


def god_objects(conn: sqlite3.Connection, threshold: int = 10) -> list[SymbolMetric]:
    """Return classes with ≥ threshold methods.

    Classes that do too many things should be split.
    """
    all_metrics = symbol_metrics(conn)
    gods = [m for m in all_metrics if m.kind == "class" and m.method_count >= threshold]
    return sorted(gods, key=lambda m: m.method_count, reverse=True)


def long_functions(conn: sqlite3.Connection, threshold: int = 50) -> list[SymbolMetric]:
    """Return functions/methods with ≥ threshold lines.

    Long functions are harder to test and reason about.
    """
    all_metrics = symbol_metrics(conn)
    long = [
        m
        for m in all_metrics
        if m.kind in ("function", "method") and m.line_count >= threshold
    ]
    return sorted(long, key=lambda m: m.line_count, reverse=True)


def module_coupling(conn: sqlite3.Connection) -> list[ModuleCoupling]:
    """Return cross-module dependency graph: how many calls go between modules.

    High coupling indicates potential for extraction or API boundary definition.
    """
    cursor = conn.cursor()

    sql = """
    SELECT
        s_from.module as from_module,
        s_to.module as to_module,
        COUNT(*) as call_count
    FROM relations r
    JOIN symbols s_from ON s_from.id = r.from_id
    JOIN symbols s_to ON s_to.id = r.to_symbol_id
    WHERE r.relation = 'CALLS'
        AND s_from.module != s_to.module
        AND s_from.module != ''
        AND s_to.module != ''
    GROUP BY s_from.module, s_to.module
    ORDER BY call_count DESC
    """

    cursor.execute(sql)
    rows = cursor.fetchall()

    return [
        ModuleCoupling(
            from_module=row[0],
            to_module=row[1],
            call_count=row[2],
        )
        for row in rows
    ]


def circular_dependencies(
    conn: sqlite3.Connection,
) -> list[list[str]]:
    """Detect module-level import cycles.

    Builds a module import graph from IMPORTS relations and finds all cycles
    using NetworkX.

    Returns list of cycles; each cycle is a list of module names in the cycle.
    """
    cursor = conn.cursor()

    # Build module graph from import relations
    # Import relations marked with relation='IMPORTS' from file-level symbols
    sql = """
    SELECT DISTINCT
        s.file_path as from_file,
        r.to_name as import_target
    FROM relations r
    JOIN symbols s ON s.id = r.from_id
    WHERE r.relation = 'IMPORTS' AND s.name = '<module>'
    """

    cursor.execute(sql)
    import_edges = cursor.fetchall()

    # Map file paths to module names
    file_to_module = {}
    cursor.execute("SELECT path, name FROM modules")
    for file_path, module_name in cursor.fetchall():
        file_to_module[file_path] = module_name

    # Normalize import targets to module names
    # An import like "github.com/gin-gonic/gin" → package name is last part
    def normalize_import(target: str) -> str:
        """Extract module name from import path."""
        # For Go: github.com/user/repo → repo
        # For JS/TS: ./components/Button → components
        # For Python: pathlib → pathlib
        if "/" in target:
            return target.split("/")[-1]
        return target

    # Build DiGraph
    G = nx.DiGraph()

    for from_file, import_target in import_edges:
        if from_file not in file_to_module:
            continue
        from_module = file_to_module[from_file]
        to_module = normalize_import(import_target)

        if from_module != to_module:  # No self-loops
            G.add_edge(from_module, to_module)

    # Find all cycles
    try:
        cycles = list(nx.simple_cycles(G))
    except nx.NetworkXError:
        cycles = []

    # Return cycles sorted by length (longest first) then lexicographically
    return sorted(cycles, key=lambda c: (-len(c), c))


def health_summary(
    conn: sqlite3.Connection,
) -> dict:
    """Return a health summary: overall metrics + risk flags.

    Returns dict with:
    - total_symbols
    - dead_code_count
    - god_objects_count
    - circular_deps_count
    - hotspot_top_5
    - longest_function_top_5
    - coupling_edges_count
    """
    all_metrics = symbol_metrics(conn)
    dead = dead_code(conn)
    gods = god_objects(conn)
    cycles = circular_dependencies(conn)
    hotspot_list = hotspots(conn, top_n=5)
    long_list = long_functions(conn)[:5]
    coupling_list = module_coupling(conn)

    return {
        "total_symbols": len(all_metrics),
        "dead_code_count": len(dead),
        "god_objects_count": len(gods),
        "circular_deps_count": len(cycles),
        "hotspots_top_5": hotspot_list,
        "longest_functions_top_5": long_list,
        "coupling_edges_count": len(coupling_list),
        "coupling_top_5": coupling_list[:5],
    }
