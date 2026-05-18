"""Integration tests for the indexer and DB layer."""

import sqlite3
from pathlib import Path

import pytest

from repo_index import db, indexer


@pytest.fixture
def conn(tmp_path):
    return db.open_db(tmp_path / "test.db")


@pytest.fixture
def repo(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "service.py").write_text(
        "import os\n\nclass AuthService:\n    def login(self, user):\n        validate(user)\n        return True\n\ndef validate(x): pass\n"
    )
    (src / "util.py").write_text("def helper(): pass\n")
    return src


def test_build_indexes_all_files(conn, repo):
    stats = indexer.build_index(conn, repo)
    assert stats.scanned == 2
    assert stats.indexed == 2
    assert stats.skipped == 0


def test_symbols_are_persisted(conn, repo):
    indexer.build_index(conn, repo)
    rows = db.query_symbol(conn, "AuthService")
    assert len(rows) == 1
    assert rows[0]["kind"] == "class"


def test_callers_are_found(conn, repo):
    indexer.build_index(conn, repo)
    callers = db.query_callers(conn, "validate")
    assert any(r["caller"] == "login" for r in callers)


def test_imports_are_found(conn, repo):
    indexer.build_index(conn, repo)
    rows = db.query_imports(conn, "service.py")
    import_names = [r["import_name"] for r in rows]
    assert "os" in import_names


def test_incremental_skip(conn, repo):
    indexer.build_index(conn, repo)
    stats2 = indexer.build_index(conn, repo)
    assert stats2.skipped == 2
    assert stats2.indexed == 0


def test_incremental_reindex_on_change(conn, repo):
    indexer.build_index(conn, repo)
    (repo / "util.py").write_text("def helper(): pass\ndef new_fn(): pass\n")
    stats2 = indexer.build_index(conn, repo)
    assert stats2.indexed == 1
    assert stats2.skipped == 1


def test_stats_counts(conn, repo):
    indexer.build_index(conn, repo)
    s = db.stats(conn)
    assert s["files"] == 2
    assert s["symbols"] > 0
    assert "function" in s["by_kind"] or "class" in s["by_kind"]


def test_reindex_removes_old_symbols(conn, repo):
    indexer.build_index(conn, repo)
    (repo / "util.py").write_text("def replaced(): pass\n")
    indexer.build_index(conn, repo)
    assert db.query_symbol(conn, "helper") == []
    assert db.query_symbol(conn, "replaced") != []
