"""DB connection management — honours REPO_INDEX_DB env var, falls back to CLI default."""

import os
import sqlite3
from pathlib import Path

from repo_index import db

_DEFAULT_DB_PATH = Path.home() / ".local" / "share" / "repo-index" / "index.db"


def resolve_db_path() -> Path:
    env = os.environ.get("REPO_INDEX_DB")
    return Path(env) if env else _DEFAULT_DB_PATH


def open_connection() -> sqlite3.Connection:
    return db.open_db(resolve_db_path())
