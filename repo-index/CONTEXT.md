# repo-index — Project Context

Local-first, AST-aware repository intelligence system. Persistent symbol index
with incremental updates, branch awareness, and a retrieval engine for
pre-LLM context assembly.

---

## Status

| Phase | Description | Status |
|-------|-------------|--------|
| 0 | Infrastructure (Rust, Tree-sitter, SQLite, Python tooling) | Done |
| 1 | Symbol Indexer — AST extraction, SQLite persistence, CLI | Done |
| 2 | Filesystem Watcher — event-driven incremental updates | Done |
| 3 | Branch-Aware Indexing — git detection, orphan cleanup | Done |
| 4 | Retrieval Engine — FTS5 search, call graph, blast radius, context assembly | Done |
| 4.5 | Semantic Resolution — FQIDs, import alias tracking, cross-file resolution | Done |
| 5 | Semantic Summarization — LLM-generated summaries per symbol | Planned |
| 6 | MCP Server — expose intelligence layer to Claude Code / Cursor | Planned |

**Tests:** 140 passing across 6 test files.  
**Install:** `pip install -e ~/ai-infra/repo-index`  
**Binary:** `repo-index` (entry point: `repo_index.cli:app`)  
**DB default:** `~/.local/share/repo-index/index.db`  
**DB override:** `REPO_INDEX_DB` env var or `--db <path>` on any command

---

## File Structure

```
repo-index/
├── pyproject.toml
├── repo_index/
│   ├── __init__.py
│   ├── cli.py          CLI — all Typer commands
│   ├── db.py           SQLite layer — schema v2, all queries
│   ├── events.py       FileEvent / EventKind dataclasses
│   ├── git.py          Git branch detection
│   ├── graph.py        NetworkX call graph builder + BFS traversal
│   ├── indexer.py      Orchestrates scan → parse → persist
│   ├── resolver.py     Post-index semantic resolution pass
│   ├── retrieval.py    Retrieval engine — search, callgraph, impact, context
│   ├── scanner.py      File discovery (fd + pathlib fallback)
│   ├── scopes.py       Lexical scope stack + ImportAlias dataclass
│   ├── symbol_table.py FQID generation utilities (file_to_module, make_fqid)
│   └── parsers/
│       ├── __init__.py Parser registry (ext → parser)
│       ├── base.py     SymbolRecord, ImportAliasRecord, RelationRecord, ParseResult, BaseParser
│       └── python.py   Tree-sitter Python parser — scope-aware, FQIDs, alias tracking
└── tests/
    ├── test_python_parser.py   (21 tests)
    ├── test_indexer.py         (8 tests)
    ├── test_watcher.py         (21 tests)
    ├── test_branch.py          (24 tests)
    ├── test_retrieval.py       (34 tests — includes graph tests)
    └── test_resolution.py      (40 tests — Phase 4.5)
```

---

## Dependencies

```toml
typer>=0.9
rich>=13
tree-sitter>=0.21
tree-sitter-language-pack>=0.0.1
networkx>=3
watchdog>=4
```

Python 3.10+. SQLite 3.x (stdlib). No external DB.

---

## Database Schema

```sql
-- Key-value store for index-level state (e.g. current_branch)
CREATE TABLE meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- One record per file path (path is PK — one record regardless of branch)
CREATE TABLE files (
    path             TEXT    PRIMARY KEY,
    content_hash     TEXT    NOT NULL,   -- SHA1 of file bytes
    branch           TEXT    DEFAULT '', -- branch last indexed on
    language         TEXT    NOT NULL,
    last_indexed_at  INTEGER NOT NULL    -- unix timestamp
);

-- Extracted symbols (v2: fqid, module, owner_symbol_id added in Phase 4.5)
CREATE TABLE symbols (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    name             TEXT    NOT NULL,
    kind             TEXT    NOT NULL,   -- function | class | method | module
    file_path        TEXT    NOT NULL REFERENCES files(path),
    start_line       INTEGER NOT NULL,
    end_line         INTEGER NOT NULL,
    hash             TEXT    NOT NULL,   -- SHA1 of symbol source lines
    language         TEXT    NOT NULL,
    fqid             TEXT    NOT NULL DEFAULT '',  -- module.Class.name
    module           TEXT    NOT NULL DEFAULT '',  -- dotted module path
    owner_symbol_id  INTEGER REFERENCES symbols(id)  -- owning class (methods)
);

-- Directional relations between symbols (v2: to_symbol_id, confidence, call_expression added)
CREATE TABLE relations (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    from_id         INTEGER NOT NULL REFERENCES symbols(id),
    relation        TEXT    NOT NULL,     -- IMPORTS | CALLS | INHERITS | DEFINES
    to_name         TEXT    NOT NULL,     -- unresolved target name (always set)
    to_symbol_id    INTEGER REFERENCES symbols(id),  -- resolved ID (NULL if unresolved)
    confidence      REAL    NOT NULL DEFAULT 0.0,    -- 0.0–1.0
    call_expression TEXT    NOT NULL DEFAULT ''      -- full dotted call for resolution
);

-- One record per indexed module (file_path → dotted name)
CREATE TABLE modules (
    id   INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,   -- e.g. "auth.jwt"
    path TEXT UNIQUE NOT NULL    -- e.g. "auth/jwt.py"
);

-- Import aliases per file (from x import y as z)
CREATE TABLE import_aliases (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path     TEXT    NOT NULL,
    alias         TEXT    NOT NULL,        -- local name in file
    source_module TEXT    NOT NULL,        -- module imported from
    source_name   TEXT    NOT NULL DEFAULT '',  -- "" for `import module`
    resolved_fqid TEXT    NOT NULL DEFAULT ''   -- pre-computed FQID
);

-- FTS5 for BM25 full-text search over symbol names
CREATE VIRTUAL TABLE symbols_fts USING fts5(
    name, kind, file_path,
    content='symbols', content_rowid='id'
);
-- Maintained by INSERT/DELETE triggers on symbols
```

**Indexes:** `symbols(name)`, `symbols(file_path)`, `symbols(kind)`, `symbols(fqid)`,
`relations(from_id)`, `relations(to_name)`, `relations(to_symbol_id)`,
`import_aliases(file_path)`, `import_aliases(alias, file_path)`.

**Schema version:** stored in `meta['schema_version']`. Pre-4.5 DBs auto-migrate via `ALTER TABLE`.

**Pragmas:** WAL journal, NORMAL sync, foreign keys ON.

---

## Module Reference

### `db.py` — persistence layer

All raw SQL lives here. No business logic.

```python
open_db(db_path: Path) -> Connection
transaction(conn) -> ContextManager          # with db.transaction(conn): ...

# files
upsert_file(conn, path, content_hash, language, branch="")
get_file_hash(conn, path) -> str | None
delete_file(conn, path)                      # removes symbols + relations + import_aliases
delete_file_symbols(conn, path)              # symbols + relations + import_aliases, keeps file row
delete_orphaned_files(conn, known_paths: set[str]) -> int  # returns count removed

# symbols
insert_symbol(conn, name, kind, file_path, start_line, end_line, hash, language,
              fqid="", module="") -> int
insert_relation(conn, from_id, relation, to_name, call_expression="")

# queries
query_symbol(conn, name) -> list[Row]           # exact name match
query_symbol_by_fqid(conn, fqid) -> Row | None  # exact FQID match
query_callers(conn, name) -> list[Row]           # symbols with CALLS → name
query_imports(conn, file_path) -> list[Row]      # IMPORTS relations for a file
query_import_aliases(conn, file_path) -> list[Row]  # alias table for a file
query_owned_symbols(conn, class_name) -> list[Row]  # methods owned by a class
query_module_symbols(conn, module_name) -> list[Row] # all non-module symbols in module

# modules
upsert_module(conn, name, path)

# FTS5 search
search_symbols(conn, query, kind=None, limit=20) -> list[Row]
# query is user text; internally converted to FTS5 prefix match: "tok"*

# meta / branch
get_meta(conn, key) -> str | None
set_meta(conn, key, value)
get_current_branch(conn) -> str
set_current_branch(conn, branch)
query_branch_stats(conn) -> list[Row]        # per-branch file + symbol counts

# stats
stats(conn) -> dict                          # files, symbols, relations, by_kind, by_language
```

---

### `parsers/base.py` — parser contracts

```python
@dataclass
class SymbolRecord:
    name: str; kind: str; start_line: int; end_line: int; hash: str
    fqid: str = ""    # module.Class.name  (Phase 4.5)
    module: str = ""  # dotted module path (Phase 4.5)
    owner: str = ""   # owning class name for methods (Phase 4.5)

@dataclass
class ImportAliasRecord:           # Phase 4.5
    alias: str          # local name (alias)
    source_module: str  # dotted module path
    source_name: str    # "" for `import module`
    # .fqid property: source_module.source_name or source_module

@dataclass
class RelationRecord:
    from_symbol: str   # "<module>" for file-level imports
    relation: str      # IMPORTS | CALLS | INHERITS | DEFINES
    to_name: str
    call_expression: str = ""  # full dotted call "obj.method" (Phase 4.5)

@dataclass
class ParseResult:
    symbols: list[SymbolRecord]
    relations: list[RelationRecord]
    import_aliases: list[ImportAliasRecord]  # Phase 4.5

class BaseParser(ABC):
    language: str          # "python"
    extensions: set[str]   # {".py"}
    parse(source: bytes, file_path: str, module: str = "") -> ParseResult
```

---

### `parsers/python.py` — Tree-sitter Python parser

Extracts from Python source:
- `function_definition` → `SymbolRecord(kind="function", fqid="module.name")`
- `class_definition` → `SymbolRecord(kind="class", fqid="module.Name")`
- Methods inside classes → `SymbolRecord(kind="method", fqid="module.Class.name", owner="Class")` + `DEFINES` relation
- Class bases → `INHERITS` relation
- `import_statement` / `import_from_statement` → `IMPORTS` relation + `ImportAliasRecord` entries
- `call` nodes → `CALLS` relation with `call_expression` ("obj.method" for attribute calls)
- Decorated definitions are unwrapped transparently

Symbol hash = SHA1 of the source lines spanning the symbol (first 16 hex chars).

---

### `scanner.py` — file discovery

```python
_SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", ...}
_SUPPORTED_EXTENSIONS = {".py"}   # grows as parsers are added

is_indexable(path: Path) -> bool
    # True if: extension in supported AND no part of path is in skip dirs

discover_files(root: Path) -> list[Path]
    # Uses fd --type f --extension py --exclude <skip_dirs>
    # Falls back to pathlib rglob if fd not found
```

---

### `git.py` — branch detection

```python
git_root(path: Path) -> Path | None   # walks up to find .git/
is_git_repo(path: Path) -> bool
current_branch(root: Path) -> str
    # Reads .git/HEAD directly (fast path)
    # Falls back to: git branch --show-current
    # Returns "" outside a git repo
    # Returns short SHA (12 chars) in detached HEAD state
```

---

### `indexer.py` — orchestration

```python
@dataclass
class IndexStats:
    scanned: int; indexed: int; skipped: int
    symbols_added: int; relations_added: int
    errors: int; removed: int; branch: str

build_index(conn, root, branch=None) -> IndexStats
    # 1. git.current_branch(root) if branch not provided
    # 2. discover_files(root)
    # 3. For each file: _index_file (skip if hash unchanged, else re-parse)
    # 4. delete_orphaned_files — removes files no longer on disk (branch switch)
    # Wraps everything in one transaction

index_single_file(conn, path, root) -> IndexStats
    # Used by FileWatcher on CREATED/MODIFIED events
    # Reads current branch from meta table

remove_indexed_file(conn, path, root)
    # Used by FileWatcher on DELETED events
```

**Incremental invariant:** `_index_file` hashes the file bytes. If the hash matches the stored hash the file is skipped (branch label still updated). If different, symbols are fully deleted and re-parsed. AST output is deterministic from content — same content on two branches = zero re-parse work.

---

### `events.py` — event types

```python
class EventKind(Enum):
    CREATED; MODIFIED; DELETED; MOVED

@dataclass
class FileEvent:
    kind: EventKind
    path: Path
    dest: Path | None   # only for MOVED
    timestamp: float
```

---

### `watcher.py` — filesystem watcher

```
OS inotify / FSEvents
    ↓
_DebouncedHandler.on_any_event()
    filters: not directory, is_indexable()
    per-path 300ms debounce timer (coalesces rapid editor writes)
    ↓
queue.Queue[FileEvent]
    ↓
worker thread (_process) — single DB writer
    CREATED | MODIFIED → index_single_file()
    DELETED            → remove_indexed_file()
    MOVED              → remove(src) + index(dest)
```

```python
class FileWatcher:
    def __init__(conn, root, on_event=None)
    def start() / stop()
    # context manager: with FileWatcher(...) as w: ...
    # on_event(event: FileEvent, stats: IndexStats | None) — called after each processed event
```

---

### `graph.py` — call graph (NetworkX)

```python
build_call_graph(conn) -> nx.DiGraph
    # Edge A→B means A CALLS B
    # Built from relations WHERE relation='CALLS' AND kind != 'module'
    # Built on demand, no caching

reachable_from(G, start, max_depth) -> list[str]
    # BFS forward: what does `start` transitively call
    # Excludes start itself; stops at max_depth hops

reverse_reachable(G, start, max_depth) -> list[str]
    # BFS backward: who transitively calls `start` (blast radius)
    # Uses G.reverse()
```

---

### `retrieval.py` — retrieval engine

```python
@dataclass
class SearchResult:
    name: str; kind: str; file_path: str; start_line: int; end_line: int

@dataclass
class RetrievalContext:
    name: str; kind: str; file_path: str; start_line: int; end_line: int
    calls: list[str]        # direct callees
    called_by: list[str]    # direct callers
    file_imports: list[str] # module-level imports of the file
    callgraph: list[str]    # transitive callees (BFS, default depth 2)
    impact: list[str]       # transitive callers / blast radius (BFS, default depth 2)

search(conn, query, kind=None, limit=20) -> list[SearchResult]
    # FTS5 BM25 prefix search; kind filters to function/class/method/module

get_callgraph(conn, name, max_depth=3) -> list[str]
get_impact(conn, name, max_depth=3) -> list[str]

get_context(conn, name, callgraph_depth=2) -> RetrievalContext | None
    # Assembles all fields from: query_symbol, query_callers, query_imports,
    # build_call_graph + reachable_from + reverse_reachable
    # Returns None if symbol not found
```

`RetrievalContext` is the primary primitive for LLM context assembly — it
contains everything needed to reason about a symbol without reading source files.

---

### `symbol_table.py` — FQID generation utilities (Phase 4.5)

```python
file_to_module(file_path: str) -> str
    # "auth/jwt.py" → "auth.jwt",  "auth/__init__.py" → "auth"

make_fqid(module: str, class_name: str | None, symbol_name: str) -> str
    # make_fqid("auth.jwt", "JWTService", "refresh") → "auth.jwt.JWTService.refresh"
```

---

### `scopes.py` — lexical scope tracking (Phase 4.5)

```python
@dataclass
class ImportAlias:
    alias: str; source_module: str; source_name: str
    # .fqid property: source_module.source_name or source_module

class ScopeStack:
    def __init__(self, module: str)
    module: str                                   # current module name
    current_class: str | None                     # innermost class
    def push_class(name) / pop_class()
    def add_alias(alias, source_module, source_name="")
    def resolve_name(name) -> str | None           # alias → FQID or None
    def make_fqid(symbol_name) -> str             # FQID at current scope
    aliases: list[ImportAlias]
```

---

### `resolver.py` — semantic resolution pass (Phase 4.5)

```python
@dataclass
class ResolutionStats:
    total_relations: int   # CALLS + INHERITS relations processed
    resolved: int          # confidence >= 0.7
    partially_resolved: int # 0 < confidence < 0.7
    unresolved: int        # no match found

resolve_references(conn) -> ResolutionStats
    # Populates to_symbol_id + confidence for all CALLS/INHERITS relations.
    # Resolution priority:
    #   1.0 — exact FQID match (dotted to_name in fqid index)
    #   0.9 — qualified call via import alias (obj.method → alias[obj].method)
    #   0.8 — plain name via import alias (foo → alias[foo].fqid)
    #   0.7 — name-unique match (only one symbol with that name)
    #   0.5 — name-ambiguous (multiple symbols, first wins)
    #   0.0 — unresolved
    # Idempotent — safe to run multiple times.
```

---

## CLI Commands

```
repo-index build   [PATH] [--db PATH]
    Scan and index a repository. Detects git branch automatically.
    Incremental — skips unchanged files by SHA1 hash.
    Runs orphan cleanup after scan (removes files not on disk).

repo-index watch   [PATH] [--db PATH] [--skip-build]
    Initial full build then watches for filesystem changes.
    Prints timestamped event log: CREATED/MODIFIED/DELETED/MOVED.

repo-index symbol  NAME   [--db PATH]
    Exact symbol name lookup. Shows kind, file, line range, language.

repo-index callers NAME   [--db PATH]
    Direct callers of a function/method.

repo-index imports FILE   [--db PATH]
    Module-level imports for a file (relative path from indexed root).

repo-index search  QUERY  [--db PATH] [--kind KIND] [--limit N]
    FTS5 BM25 prefix search. QUERY is whitespace-separated tokens,
    each matched as a prefix. --kind filters to function/class/method/module.

repo-index deps    NAME   [--db PATH] [--depth N]
    Transitive callees of a symbol (what it depends on).

repo-index impact  NAME   [--db PATH] [--depth N]
    Transitive callers of a symbol (blast radius if it changes).

repo-index context NAME   [--db PATH] [--depth N]
    Full RetrievalContext as a Rich panel: location, direct calls,
    called_by, file imports, transitive callgraph, impact.

repo-index resolve [--db PATH]
    Run the semantic resolution pass. Populates to_symbol_id + confidence
    for all CALLS/INHERITS relations. Idempotent. Shows resolution coverage.

repo-index fqid    FQID   [--db PATH]
    Look up a symbol by its fully-qualified ID (e.g. auth.jwt.validate_token).

repo-index ownership NAME [--db PATH]
    Show all methods owned by a class.

repo-index module  NAME   [--db PATH]
    List all symbols in a module (e.g. repo_index.db).

repo-index branch  [PATH] [--db PATH]
    Current branch vs indexed branch. Per-branch file/symbol table.

repo-index stats   [--db PATH]
    Index totals: files, symbols, relations, breakdown by kind/language.

repo-index files   [--db PATH]
    List all indexed files with language and content hash.
```

---

## Design Invariants

**FACTS != INTERPRETATION** — `db.py` stores raw structural facts only.
No LLM output, no summaries, no embeddings are in the current schema.

**Hash = truth** — A file is re-indexed only when its SHA1 changes.
Same content on different branches = zero re-parse work.

**Orphan cleanup on every build** — After scanning discovered files,
`delete_orphaned_files` removes any indexed path not in the current
filesystem snapshot. This is how branch switches take effect.

**Single writer** — `FileWatcher` uses one worker thread to drain its
queue. SQLite WAL mode + a single writer = no locking conflicts.

**Debounce** — `_DebouncedHandler` gives each path a 300ms timer,
cancelling and restarting on each new event. Editor flicker (vim swapfiles,
etc.) produces exactly one index update per save.

**Parser extensibility** — add a new `BaseParser` subclass in `parsers/`,
add its extension to `_SUPPORTED_EXTENSIONS` in `scanner.py`, register it
in `parsers/__init__.py`. Everything else works automatically.

---

## Planned: Phase 5 — Semantic Summarization

Schema addition:
```sql
CREATE TABLE summaries (
    symbol_id    INTEGER REFERENCES symbols(id),
    level        TEXT,    -- function | module | subsystem | repo
    summary      TEXT,
    embedding    BLOB,
    based_on_hash TEXT    -- invalidated when symbol hash changes
);
```

Generation hierarchy: function → module → subsystem → repo.
Summaries are **derived data** — regeneratable from Layer 1 facts.
They are invalidated when the symbol's `hash` changes.

---

## Planned: Phase 6 — MCP Server

Expose `retrieval.py` via the Model Context Protocol so Claude Code,
Cursor, Codex and other agents can share the same persistent intelligence
layer without re-scanning.

Capabilities to expose:
- `symbol_lookup(name)`
- `search(query, kind, limit)`
- `callgraph(name, depth)`
- `impact(name, depth)`
- `context(name)` → full `RetrievalContext`
