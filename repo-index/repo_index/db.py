"""SQLite persistence layer — Layer 1 structural facts only."""

import sqlite3
from contextlib import contextmanager
from pathlib import Path


_META_CURRENT_BRANCH = "current_branch"
_META_SCHEMA_VERSION = "schema_version"
_META_REPO_ROOT = "repo_root"
_SCHEMA_VERSION = "2"

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS files (
    path        TEXT    PRIMARY KEY,
    content_hash TEXT   NOT NULL,
    branch      TEXT    DEFAULT '',
    language    TEXT    NOT NULL,
    last_indexed_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS symbols (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    name             TEXT    NOT NULL,
    kind             TEXT    NOT NULL,
    file_path        TEXT    NOT NULL,
    start_line       INTEGER NOT NULL,
    end_line         INTEGER NOT NULL,
    hash             TEXT    NOT NULL,
    language         TEXT    NOT NULL,
    fqid             TEXT    NOT NULL DEFAULT '',
    module           TEXT    NOT NULL DEFAULT '',
    owner_symbol_id  INTEGER,
    FOREIGN KEY (file_path) REFERENCES files(path),
    FOREIGN KEY (owner_symbol_id) REFERENCES symbols(id)
);

CREATE TABLE IF NOT EXISTS relations (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    from_id         INTEGER NOT NULL,
    relation        TEXT    NOT NULL,
    to_name         TEXT    NOT NULL,
    to_symbol_id    INTEGER,
    confidence      REAL    NOT NULL DEFAULT 0.0,
    call_expression TEXT    NOT NULL DEFAULT '',
    FOREIGN KEY (from_id) REFERENCES symbols(id),
    FOREIGN KEY (to_symbol_id) REFERENCES symbols(id)
);

CREATE TABLE IF NOT EXISTS modules (
    id   INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    path TEXT UNIQUE NOT NULL
);

CREATE TABLE IF NOT EXISTS import_aliases (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path     TEXT    NOT NULL,
    alias         TEXT    NOT NULL,
    source_module TEXT    NOT NULL,
    source_name   TEXT    NOT NULL DEFAULT '',
    resolved_fqid TEXT    NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_symbols_name      ON symbols(name);
CREATE INDEX IF NOT EXISTS idx_symbols_file      ON symbols(file_path);
CREATE INDEX IF NOT EXISTS idx_symbols_kind      ON symbols(kind);
CREATE INDEX IF NOT EXISTS idx_symbols_fqid      ON symbols(fqid);
CREATE INDEX IF NOT EXISTS idx_relations_from    ON relations(from_id);
CREATE INDEX IF NOT EXISTS idx_relations_to_name ON relations(to_name);
CREATE INDEX IF NOT EXISTS idx_relations_to_sym  ON relations(to_symbol_id);
CREATE INDEX IF NOT EXISTS idx_import_aliases_fp ON import_aliases(file_path);
CREATE INDEX IF NOT EXISTS idx_import_aliases_al ON import_aliases(alias, file_path);

CREATE VIRTUAL TABLE IF NOT EXISTS symbols_fts USING fts5(
    name,
    kind,
    file_path,
    content='symbols',
    content_rowid='id'
);

CREATE TRIGGER IF NOT EXISTS symbols_ai AFTER INSERT ON symbols BEGIN
    INSERT INTO symbols_fts(rowid, name, kind, file_path)
    VALUES (new.id, new.name, new.kind, new.file_path);
END;

CREATE TRIGGER IF NOT EXISTS symbols_ad AFTER DELETE ON symbols BEGIN
    INSERT INTO symbols_fts(symbols_fts, rowid, name, kind, file_path)
    VALUES ('delete', old.id, old.name, old.kind, old.file_path);
END;
"""

# Columns added in schema v2 to existing tables (pre-v2 DBs need migration)
_V2_ALTERS = [
    "ALTER TABLE symbols ADD COLUMN fqid TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE symbols ADD COLUMN module TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE symbols ADD COLUMN owner_symbol_id INTEGER",
    "ALTER TABLE relations ADD COLUMN to_symbol_id INTEGER",
    "ALTER TABLE relations ADD COLUMN confidence REAL NOT NULL DEFAULT 0.0",
    "ALTER TABLE relations ADD COLUMN call_expression TEXT NOT NULL DEFAULT ''",
]


def open_db(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(SCHEMA)
    _apply_migrations(conn)
    return conn


def _apply_migrations(conn: sqlite3.Connection) -> None:
    version = get_meta(conn, _META_SCHEMA_VERSION) or "1"
    if version < _SCHEMA_VERSION:
        _migrate_to_v2(conn)


def _migrate_to_v2(conn: sqlite3.Connection) -> None:
    for stmt in _V2_ALTERS:
        try:
            conn.execute(stmt)
            conn.commit()
        except sqlite3.OperationalError:
            pass  # column already exists (idempotent)
    set_meta(conn, _META_SCHEMA_VERSION, _SCHEMA_VERSION)
    conn.commit()


@contextmanager
def transaction(conn: sqlite3.Connection):
    with conn:
        yield conn


def upsert_file(
    conn: sqlite3.Connection, path: str, content_hash: str, language: str, branch: str = ""
) -> None:
    import time
    conn.execute(
        """INSERT INTO files (path, content_hash, branch, language, last_indexed_at)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(path) DO UPDATE SET
               content_hash=excluded.content_hash,
               branch=excluded.branch,
               language=excluded.language,
               last_indexed_at=excluded.last_indexed_at""",
        (path, content_hash, branch, language, int(time.time())),
    )


def get_file_hash(conn: sqlite3.Connection, path: str) -> str | None:
    row = conn.execute("SELECT content_hash FROM files WHERE path = ?", (path,)).fetchone()
    return row["content_hash"] if row else None


def delete_file(conn: sqlite3.Connection, path: str) -> None:
    """Remove a file record and all its symbols/relations from the index."""
    delete_file_symbols(conn, path)
    conn.execute("DELETE FROM modules WHERE path = ?", (path,))
    conn.execute("DELETE FROM files WHERE path = ?", (path,))


def delete_file_symbols(conn: sqlite3.Connection, path: str) -> None:
    symbol_ids = [
        row["id"]
        for row in conn.execute("SELECT id FROM symbols WHERE file_path = ?", (path,)).fetchall()
    ]
    for sid in symbol_ids:
        conn.execute("DELETE FROM relations WHERE from_id = ?", (sid,))
    conn.execute("DELETE FROM symbols WHERE file_path = ?", (path,))
    conn.execute("DELETE FROM import_aliases WHERE file_path = ?", (path,))


def insert_symbol(
    conn: sqlite3.Connection,
    name: str,
    kind: str,
    file_path: str,
    start_line: int,
    end_line: int,
    symbol_hash: str,
    language: str,
    fqid: str = "",
    module: str = "",
) -> int:
    cur = conn.execute(
        """INSERT INTO symbols (name, kind, file_path, start_line, end_line, hash, language, fqid, module)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (name, kind, file_path, start_line, end_line, symbol_hash, language, fqid, module),
    )
    return cur.lastrowid


def insert_relation(
    conn: sqlite3.Connection,
    from_id: int,
    relation: str,
    to_name: str,
    call_expression: str = "",
) -> None:
    conn.execute(
        "INSERT INTO relations (from_id, relation, to_name, call_expression) VALUES (?, ?, ?, ?)",
        (from_id, relation, to_name, call_expression),
    )


def query_symbol(conn: sqlite3.Connection, name: str) -> list[sqlite3.Row]:
    return conn.execute(
        """SELECT s.*, f.last_indexed_at
           FROM symbols s JOIN files f ON s.file_path = f.path
           WHERE s.name = ?
           ORDER BY s.file_path, s.start_line""",
        (name,),
    ).fetchall()


def query_symbol_by_fqid(conn: sqlite3.Connection, fqid: str) -> sqlite3.Row | None:
    return conn.execute(
        """SELECT s.*, f.last_indexed_at
           FROM symbols s JOIN files f ON s.file_path = f.path
           WHERE s.fqid = ?""",
        (fqid,),
    ).fetchone()


def query_callers(conn: sqlite3.Connection, name: str) -> list[sqlite3.Row]:
    return conn.execute(
        """SELECT s.name as caller, s.kind, s.file_path, s.start_line
           FROM relations r
           JOIN symbols s ON r.from_id = s.id
           WHERE r.relation = 'CALLS' AND r.to_name = ?
           ORDER BY s.file_path, s.start_line""",
        (name,),
    ).fetchall()


def query_imports(conn: sqlite3.Connection, file_path: str) -> list[sqlite3.Row]:
    return conn.execute(
        """SELECT r.to_name as import_name
           FROM symbols s JOIN relations r ON s.id = r.from_id
           WHERE s.file_path = ? AND r.relation = 'IMPORTS'
           ORDER BY r.to_name""",
        (file_path,),
    ).fetchall()


def query_import_aliases(conn: sqlite3.Connection, file_path: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM import_aliases WHERE file_path = ? ORDER BY alias",
        (file_path,),
    ).fetchall()


def query_owned_symbols(conn: sqlite3.Connection, class_name: str) -> list[sqlite3.Row]:
    """Return symbols owned by a class (i.e. its methods), looked up via owner_symbol_id."""
    class_row = conn.execute(
        "SELECT id FROM symbols WHERE name = ? AND kind = 'class' LIMIT 1",
        (class_name,),
    ).fetchone()
    if not class_row:
        return []
    return conn.execute(
        """SELECT name, kind, fqid, start_line, end_line
           FROM symbols
           WHERE owner_symbol_id = ?
           ORDER BY start_line""",
        (class_row["id"],),
    ).fetchall()


def query_module_symbols(conn: sqlite3.Connection, module_name: str) -> list[sqlite3.Row]:
    return conn.execute(
        """SELECT name, kind, fqid, start_line, end_line
           FROM symbols
           WHERE module = ? AND kind != 'module'
           ORDER BY kind, name""",
        (module_name,),
    ).fetchall()


def upsert_module(conn: sqlite3.Connection, name: str, path: str) -> None:
    if not name:
        return
    conn.execute(
        "INSERT INTO modules (name, path) VALUES (?, ?) "
        "ON CONFLICT(name) DO UPDATE SET path=excluded.path",
        (name, path),
    )


def get_meta(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )


def get_current_branch(conn: sqlite3.Connection) -> str:
    return get_meta(conn, _META_CURRENT_BRANCH) or ""


def set_current_branch(conn: sqlite3.Connection, branch: str) -> None:
    set_meta(conn, _META_CURRENT_BRANCH, branch)


def get_repo_root(conn: sqlite3.Connection) -> str | None:
    return get_meta(conn, _META_REPO_ROOT)


def set_repo_root(conn: sqlite3.Connection, root: str) -> None:
    set_meta(conn, _META_REPO_ROOT, root)
    conn.commit()


def delete_orphaned_files(conn: sqlite3.Connection, known_paths: set[str]) -> int:
    """Remove index entries for files that no longer exist on disk. Returns count removed."""
    all_indexed = {row["path"] for row in conn.execute("SELECT path FROM files").fetchall()}
    orphans = all_indexed - known_paths
    for path in orphans:
        delete_file(conn, path)
    return len(orphans)


def query_branch_stats(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        """SELECT f.branch, COUNT(DISTINCT f.path) as files, COUNT(s.id) as symbols
           FROM files f LEFT JOIN symbols s ON s.file_path = f.path
           GROUP BY f.branch
           ORDER BY files DESC""",
    ).fetchall()


def search_symbols(
    conn: sqlite3.Connection,
    query: str,
    kind: str | None = None,
    limit: int = 20,
) -> list[sqlite3.Row]:
    """FTS5 BM25 search over symbol names. kind filters to function/class/method/etc."""
    fts_query = _to_fts_query(query)
    if kind:
        sql = """
            SELECT s.id, s.name, s.kind, s.file_path, s.start_line, s.end_line,
                   bm25(symbols_fts) AS score
            FROM symbols_fts
            JOIN symbols s ON symbols_fts.rowid = s.id
            WHERE symbols_fts MATCH ? AND s.kind = ?
            ORDER BY score
            LIMIT ?"""
        return conn.execute(sql, (fts_query, kind, limit)).fetchall()
    sql = """
        SELECT s.id, s.name, s.kind, s.file_path, s.start_line, s.end_line,
               bm25(symbols_fts) AS score
        FROM symbols_fts
        JOIN symbols s ON symbols_fts.rowid = s.id
        WHERE symbols_fts MATCH ?
        ORDER BY score
        LIMIT ?"""
    return conn.execute(sql, (fts_query, limit)).fetchall()


def search_symbols_ranked(
    conn: sqlite3.Connection,
    query: str,
    kind: str | None = None,
    limit: int = 20,
) -> list[sqlite3.Row]:
    """FTS5 search enriched with caller_count and file recency for multi-signal re-ranking.

    Returns up to limit*2 candidates so the caller can re-rank and trim to limit.
    """
    fts_query = _to_fts_query(query)
    kind_clause = "AND s.kind = ?" if kind else ""
    sql = f"""
        SELECT s.id, s.name, s.kind, s.file_path, s.start_line, s.end_line,
               bm25(symbols_fts) AS bm25_score,
               COALESCE(f.last_indexed_at, 0) AS last_indexed_at,
               (SELECT COUNT(*) FROM relations r2
                WHERE r2.to_name = s.name AND r2.relation = 'CALLS') AS caller_count
        FROM symbols_fts
        JOIN symbols s ON symbols_fts.rowid = s.id
        LEFT JOIN files f ON s.file_path = f.path
        WHERE symbols_fts MATCH ?
        {kind_clause}
        ORDER BY bm25_score
        LIMIT ?"""
    params: list = [fts_query]
    if kind:
        params.append(kind)
    params.append(limit * 2)
    return conn.execute(sql, params).fetchall()


def _to_fts_query(raw: str) -> str:
    tokens = raw.strip().split()
    if not tokens:
        return '""'
    return " ".join(f'"{t}"*' for t in tokens)


def resolution_stats(conn: sqlite3.Connection) -> dict:
    total = conn.execute(
        "SELECT COUNT(*) FROM relations WHERE relation IN ('CALLS', 'INHERITS')"
    ).fetchone()[0]
    resolved_count = conn.execute(
        "SELECT COUNT(*) FROM relations WHERE to_symbol_id IS NOT NULL "
        "AND relation IN ('CALLS', 'INHERITS')"
    ).fetchone()[0]
    row = conn.execute(
        """SELECT
            SUM(CASE WHEN confidence >= 0.9 THEN 1 ELSE 0 END)                        AS high,
            SUM(CASE WHEN confidence >= 0.7 AND confidence < 0.9 THEN 1 ELSE 0 END)   AS medium,
            SUM(CASE WHEN confidence > 0.0 AND confidence < 0.7 THEN 1 ELSE 0 END)    AS low,
            SUM(CASE WHEN to_symbol_id IS NULL THEN 1 ELSE 0 END)                     AS unresolved
           FROM relations WHERE relation IN ('CALLS', 'INHERITS')"""
    ).fetchone()
    return {
        "total": total,
        "resolved": resolved_count,
        "unresolved": total - resolved_count,
        "high_confidence": row["high"] or 0,
        "medium_confidence": row["medium"] or 0,
        "low_confidence": row["low"] or 0,
    }


def stats(conn: sqlite3.Connection) -> dict:
    return {
        "files": conn.execute("SELECT COUNT(*) FROM files").fetchone()[0],
        "symbols": conn.execute("SELECT COUNT(*) FROM symbols").fetchone()[0],
        "relations": conn.execute("SELECT COUNT(*) FROM relations").fetchone()[0],
        "by_kind": {
            row["kind"]: row["cnt"]
            for row in conn.execute(
                "SELECT kind, COUNT(*) as cnt FROM symbols GROUP BY kind ORDER BY cnt DESC"
            ).fetchall()
        },
        "by_language": {
            row["language"]: row["cnt"]
            for row in conn.execute(
                "SELECT language, COUNT(*) as cnt FROM symbols GROUP BY language ORDER BY cnt DESC"
            ).fetchall()
        },
    }
