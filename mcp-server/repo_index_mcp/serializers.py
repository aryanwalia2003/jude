"""Convert internal types to JSON-serializable dicts."""

import sqlite3

from repo_index.retrieval import RetrievalContext, SearchResult


def row_to_dict(row: sqlite3.Row) -> dict:
    return dict(row)


def rows_to_dicts(rows: list[sqlite3.Row]) -> list[dict]:
    return [dict(r) for r in rows]


def search_result_to_dict(result: SearchResult) -> dict:
    data = {
        "name": result.name,
        "kind": result.kind,
        "file_path": result.file_path,
        "start_line": result.start_line,
        "end_line": result.end_line,
        "score": result.composite_score,
    }
    if result.audit:
        data["audit"] = {
            "rank": result.audit.rank_position,
            "score": result.audit.composite_score,
            "factors": [
                {
                    "name": f.name,
                    "value": f.value,
                    "weight": f.weight,
                    "contribution": f.contribution,
                }
                for f in result.audit.factors
            ],
        }
    return data


def context_to_dict(ctx: RetrievalContext) -> dict:
    data = {
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
    if ctx.impact_audit:
        data["impact_audit"] = {
            "score": ctx.impact_audit.composite_score,
            "factors": [
                {
                    "name": f.name,
                    "value": f.value,
                    "weight": f.weight,
                    "contribution": f.contribution,
                }
                for f in ctx.impact_audit.factors
            ],
        }
    return data
