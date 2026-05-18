"""Convert internal types to JSON-serializable dicts."""

import sqlite3

from repo_index.retrieval import RetrievalContext, SearchResult


def row_to_dict(row: sqlite3.Row) -> dict:
    return dict(row)


def rows_to_dicts(rows: list[sqlite3.Row]) -> list[dict]:
    return [dict(r) for r in rows]


def search_result_to_dict(result: SearchResult) -> dict:
    return {
        "name": result.name,
        "kind": result.kind,
        "file_path": result.file_path,
        "start_line": result.start_line,
        "end_line": result.end_line,
    }


def context_to_dict(ctx: RetrievalContext) -> dict:
    return {
        "name": ctx.name,
        "kind": ctx.kind,
        "file_path": ctx.file_path,
        "start_line": ctx.start_line,
        "end_line": ctx.end_line,
        "calls": ctx.calls,
        "called_by": ctx.called_by,
        "file_imports": ctx.file_imports,
        "callgraph": ctx.callgraph,
        "impact": ctx.impact,
    }
