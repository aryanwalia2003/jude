"""Post-index semantic resolution pass.

Resolves CALLS/INHERITS relations from unresolved to_name strings to actual
symbol IDs, using import alias tables and FQID lookup indexes.

Resolution confidence levels:
  1.0  — exact FQID match (dotted to_name found directly in fqid index)
  0.9  — qualified call via import alias  (obj.method → alias[obj].method)
  0.8  — plain name via import alias      (foo → alias[foo].fqid)
  0.7  — name-unique match               (only one symbol with that name)
  0.5  — name-ambiguous match            (multiple symbols, best guess)
  0.0  — unresolved
"""

import sqlite3
from dataclasses import dataclass


@dataclass
class ResolutionStats:
    total_relations: int = 0
    resolved: int = 0          # confidence >= 0.7
    partially_resolved: int = 0  # 0 < confidence < 0.7
    unresolved: int = 0


def resolve_references(conn: sqlite3.Connection) -> ResolutionStats:
    """
    Populate to_symbol_id and confidence for all CALLS/INHERITS relations.
    Safe to run multiple times — updates all relations, not just NULL ones.
    """
    stats = ResolutionStats()

    fqid_index: dict[str, int] = {}
    name_index: dict[str, list[int]] = {}

    for row in conn.execute(
        "SELECT id, name, fqid FROM symbols WHERE kind != 'module'"
    ).fetchall():
        if row["fqid"]:
            fqid_index[row["fqid"]] = row["id"]
        name_index.setdefault(row["name"], []).append(row["id"])

    # file_path → { alias: resolved_fqid }
    file_aliases: dict[str, dict[str, str]] = {}
    for row in conn.execute(
        "SELECT file_path, alias, resolved_fqid FROM import_aliases"
    ).fetchall():
        file_aliases.setdefault(row["file_path"], {})[row["alias"]] = row["resolved_fqid"]

    relations = conn.execute(
        """SELECT r.id, r.to_name, r.call_expression, r.relation, s.file_path
           FROM relations r
           JOIN symbols s ON r.from_id = s.id
           WHERE r.relation IN ('CALLS', 'INHERITS')"""
    ).fetchall()

    stats.total_relations = len(relations)

    updates: list[tuple[int | None, float, int]] = []
    for rel in relations:
        aliases = file_aliases.get(rel["file_path"], {})
        sym_id, confidence = _resolve_one(
            to_name=rel["to_name"],
            call_expr=rel["call_expression"] or rel["to_name"],
            aliases=aliases,
            fqid_index=fqid_index,
            name_index=name_index,
        )
        updates.append((sym_id, confidence, rel["id"]))

        if sym_id is not None and confidence >= 0.7:
            stats.resolved += 1
        elif sym_id is not None:
            stats.partially_resolved += 1
        else:
            stats.unresolved += 1

    conn.executemany(
        "UPDATE relations SET to_symbol_id = ?, confidence = ? WHERE id = ?",
        updates,
    )
    conn.commit()
    return stats


def _resolve_one(
    to_name: str,
    call_expr: str,
    aliases: dict[str, str],
    fqid_index: dict[str, int],
    name_index: dict[str, list[int]],
) -> tuple[int | None, float]:
    # 1. Exact FQID from to_name (already dotted)
    if "." in to_name:
        if to_name in fqid_index:
            return fqid_index[to_name], 1.0

    # 2. Qualified call: "obj.attr" → resolve obj via alias, look up obj_fqid.attr
    if "." in call_expr:
        obj, attr = call_expr.split(".", 1)
        if obj in aliases:
            candidate = f"{aliases[obj]}.{attr}"
            if candidate in fqid_index:
                return fqid_index[candidate], 0.9

    # 3. Plain name via import alias
    if to_name in aliases:
        candidate = aliases[to_name]
        if candidate in fqid_index:
            return fqid_index[candidate], 0.8

    # 4. Name-only lookup
    matches = name_index.get(to_name, [])
    if len(matches) == 1:
        return matches[0], 0.7
    if matches:
        return matches[0], 0.5

    return None, 0.0
