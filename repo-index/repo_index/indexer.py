"""Orchestrates scan → parse → persist. Incremental by content hash."""

import hashlib
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from . import db, git
from .parsers import get_parser
from .parsers.base import ImportAliasRecord, ParseResult, RelationRecord, SymbolRecord
from .scanner import discover_files
from .symbol_table import file_to_module


@dataclass
class IndexStats:
    scanned: int = 0
    indexed: int = 0
    skipped: int = 0
    symbols_added: int = 0
    relations_added: int = 0
    errors: int = 0
    removed: int = 0   # orphan files purged on branch switch
    branch: str = ""


def index_single_file(conn: sqlite3.Connection, path: Path, root: Path) -> IndexStats:
    """Re-index one file. Used by the watcher on CREATED/MODIFIED/MOVED-dest events."""
    branch = db.get_current_branch(conn)
    stats = IndexStats(scanned=1, branch=branch)
    with db.transaction(conn):
        result = _index_file(conn, path, root, branch)
    if result is None:
        stats.skipped = 1
    elif result is False:
        stats.errors = 1
    else:
        stats.indexed = 1
        stats.symbols_added, stats.relations_added = result
    return stats


def remove_indexed_file(conn: sqlite3.Connection, path: Path, root: Path) -> None:
    """Remove a file and all its symbols from the index."""
    rel_path = str(path.relative_to(root))
    with db.transaction(conn):
        db.delete_file(conn, rel_path)


def build_index(conn: sqlite3.Connection, root: Path, branch: str | None = None) -> IndexStats:
    if branch is None:
        branch = git.current_branch(root)

    files = discover_files(root)
    known_paths = {str(p.relative_to(root)) for p in files}
    stats = IndexStats(scanned=len(files), branch=branch)

    with db.transaction(conn):
        db.set_current_branch(conn, branch)
        for path in files:
            result = _index_file(conn, path, root, branch)
            if result is None:
                stats.skipped += 1
            elif result is False:
                stats.errors += 1
            else:
                stats.indexed += 1
                stats.symbols_added += result[0]
                stats.relations_added += result[1]
        stats.removed = db.delete_orphaned_files(conn, known_paths)

    return stats


def _index_file(
    conn: sqlite3.Connection, path: Path, root: Path, branch: str = ""
) -> tuple[int, int] | None | bool:
    parser = get_parser(path)
    if not parser:
        return None

    try:
        source = path.read_bytes()
    except OSError:
        return False

    content_hash = hashlib.sha1(source).hexdigest()
    rel_path = str(path.relative_to(root))

    if db.get_file_hash(conn, rel_path) == content_hash:
        db.upsert_file(conn, rel_path, content_hash, parser.language, branch)
        return None

    module = file_to_module(rel_path)

    db.delete_file_symbols(conn, rel_path)
    db.upsert_file(conn, rel_path, content_hash, parser.language, branch)
    db.upsert_module(conn, module, rel_path)

    result: ParseResult = parser.parse(source, rel_path, module=module)
    sym_ids = _persist_symbols(conn, result.symbols, rel_path, parser.language)
    _persist_import_aliases(conn, result.import_aliases, rel_path)
    rel_count = _persist_relations(conn, result.relations, sym_ids, rel_path, module)

    return len(result.symbols), rel_count


def _persist_symbols(
    conn: sqlite3.Connection,
    symbols: list[SymbolRecord],
    file_path: str,
    language: str,
) -> dict[str, int]:
    name_to_id: dict[str, int] = {}
    fqid_to_id: dict[str, int] = {}

    for sym in symbols:
        sid = db.insert_symbol(
            conn,
            name=sym.name,
            kind=sym.kind,
            file_path=file_path,
            start_line=sym.start_line,
            end_line=sym.end_line,
            symbol_hash=sym.hash,
            language=language,
            fqid=sym.fqid,
            module=sym.module,
        )
        name_to_id[sym.name] = sid
        if sym.fqid:
            fqid_to_id[sym.fqid] = sid

    # Wire owner_symbol_id for methods using FQID-based parent lookup
    for sym in symbols:
        if sym.owner and sym.fqid and sym.fqid in fqid_to_id:
            owner_fqid = sym.fqid.rsplit(".", 1)[0]  # strip last component
            owner_id = fqid_to_id.get(owner_fqid)
            if owner_id:
                conn.execute(
                    "UPDATE symbols SET owner_symbol_id = ? WHERE id = ?",
                    (owner_id, fqid_to_id[sym.fqid]),
                )

    return name_to_id


def _persist_import_aliases(
    conn: sqlite3.Connection,
    aliases: list[ImportAliasRecord],
    file_path: str,
) -> None:
    for a in aliases:
        rfqid = f"{a.source_module}.{a.source_name}" if a.source_name else a.source_module
        conn.execute(
            """INSERT INTO import_aliases
               (file_path, alias, source_module, source_name, resolved_fqid)
               VALUES (?, ?, ?, ?, ?)""",
            (file_path, a.alias, a.source_module, a.source_name, rfqid),
        )


def _persist_relations(
    conn: sqlite3.Connection,
    relations: list[RelationRecord],
    sym_ids: dict[str, int],
    file_path: str,
    module: str = "",
) -> int:
    count = 0
    module_id = sym_ids.get("<module>")

    for rel in relations:
        if rel.from_symbol == "<module>":
            if not module_id:
                module_id = db.insert_symbol(
                    conn,
                    name="<module>",
                    kind="module",
                    file_path=file_path,
                    start_line=0,
                    end_line=0,
                    symbol_hash="",
                    language="python",
                    fqid=module,
                    module=module,
                )
                sym_ids["<module>"] = module_id
            from_id = module_id
        else:
            from_id = sym_ids.get(rel.from_symbol)

        if from_id is None:
            continue

        db.insert_relation(conn, from_id, rel.relation, rel.to_name, rel.call_expression)
        count += 1

    return count
