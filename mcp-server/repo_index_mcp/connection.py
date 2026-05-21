"""DB connection management — per-repo routing with env-var and default fallbacks.

DB naming convention:
  ~/.local/share/repo-index/<repo-name>.db   (derived from repo root directory name)

Priority:
  1. Explicit repo_path argument  →  db_for_repo(repo_path)
  2. REPO_INDEX_DB env var        →  that path
  3. No context                   →  default index.db
"""

import os
import sqlite3
from pathlib import Path

from repo_index import db

_DB_DIR = Path.home() / ".local" / "share" / "repo-index"
_DEFAULT_DB_PATH = _DB_DIR / "index.db"


def resolve_db_path() -> Path:
    """Return the DB path from env var or global default."""
    env = os.environ.get("REPO_INDEX_DB")
    return Path(env) if env else _DEFAULT_DB_PATH


def db_for_repo(repo_path: str) -> Path:
    """Derive the DB path for a repo root.

    Uses the final path component as the DB name so that
    /home/user/projects/my-api  →  ~/.local/share/repo-index/my-api.db
    """
    root = Path(repo_path).resolve()
    return _DB_DIR / f"{root.name}.db"


def open_connection() -> sqlite3.Connection:
    """Open the default/env-configured DB."""
    return db.open_db(resolve_db_path())


def open_connection_for(repo_path: str | None = None) -> sqlite3.Connection:
    """Open the DB for repo_path, falling back to the default if None."""
    if repo_path:
        return db.open_db(db_for_repo(repo_path))
    return db.open_db(resolve_db_path())
