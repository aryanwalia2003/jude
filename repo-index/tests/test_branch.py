"""Tests for Phase 3: branch-aware indexing."""

import subprocess
from pathlib import Path

import pytest

from repo_index import db, indexer
from repo_index import git as gitmod


# ---------------------------------------------------------------------------
# git.current_branch
# ---------------------------------------------------------------------------

def test_current_branch_returns_empty_outside_git_repo(tmp_path):
    assert gitmod.current_branch(tmp_path) == ""


def test_is_git_repo_false_outside_git(tmp_path):
    assert not gitmod.is_git_repo(tmp_path)


def test_git_root_none_outside_git(tmp_path):
    assert gitmod.git_root(tmp_path) is None


def _init_git_repo(path: Path, branch: str = "main") -> None:
    subprocess.run(["git", "init", "-b", branch, str(path)], check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], check=True, capture_output=True, cwd=str(path))
    subprocess.run(["git", "config", "user.name", "Test"], check=True, capture_output=True, cwd=str(path))


def test_current_branch_reads_main(tmp_path):
    _init_git_repo(tmp_path, branch="main")
    assert gitmod.current_branch(tmp_path) == "main"


def test_current_branch_reads_feature_branch(tmp_path):
    _init_git_repo(tmp_path, branch="feature/auth")
    assert gitmod.current_branch(tmp_path) == "feature/auth"


def test_is_git_repo_true_inside_git(tmp_path):
    _init_git_repo(tmp_path)
    assert gitmod.is_git_repo(tmp_path)


def test_git_root_finds_repo_root(tmp_path):
    _init_git_repo(tmp_path)
    nested = tmp_path / "a" / "b"
    nested.mkdir(parents=True)
    assert gitmod.git_root(nested) == tmp_path


def test_current_branch_detected_from_nested_path(tmp_path):
    _init_git_repo(tmp_path, branch="develop")
    nested = tmp_path / "src"
    nested.mkdir()
    assert gitmod.current_branch(nested) == "develop"


# ---------------------------------------------------------------------------
# db: meta table
# ---------------------------------------------------------------------------

@pytest.fixture
def conn(tmp_path):
    return db.open_db(tmp_path / "test.db")


def test_get_meta_returns_none_when_absent(conn):
    assert db.get_meta(conn, "nonexistent") is None


def test_set_and_get_meta_roundtrip(conn):
    db.set_meta(conn, "current_branch", "main")
    assert db.get_meta(conn, "current_branch") == "main"


def test_set_meta_overwrites_existing(conn):
    db.set_meta(conn, "current_branch", "main")
    db.set_meta(conn, "current_branch", "feature/x")
    assert db.get_meta(conn, "current_branch") == "feature/x"


def test_get_current_branch_defaults_empty(conn):
    assert db.get_current_branch(conn) == ""


def test_set_current_branch(conn):
    db.set_current_branch(conn, "main")
    assert db.get_current_branch(conn) == "main"


# ---------------------------------------------------------------------------
# db: orphan cleanup
# ---------------------------------------------------------------------------

@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "a.py").write_text("def alpha(): pass\n")
    (root / "b.py").write_text("def beta(): pass\n")
    return root


def test_delete_orphaned_files_removes_missing_paths(conn, repo):
    indexer.build_index(conn, repo, branch="main")
    # Simulate branch switch where b.py doesn't exist
    known = {"a.py"}
    removed = db.delete_orphaned_files(conn, known)
    assert removed == 1
    assert db.query_symbol(conn, "beta") == []
    assert db.query_symbol(conn, "alpha") != []


def test_delete_orphaned_files_removes_nothing_when_all_present(conn, repo):
    indexer.build_index(conn, repo, branch="main")
    known = {"a.py", "b.py"}
    removed = db.delete_orphaned_files(conn, known)
    assert removed == 0


def test_delete_orphaned_files_returns_count(conn, repo):
    indexer.build_index(conn, repo, branch="main")
    removed = db.delete_orphaned_files(conn, set())
    assert removed == 2


# ---------------------------------------------------------------------------
# indexer: branch recorded + orphan cleanup on build
# ---------------------------------------------------------------------------

def test_build_index_records_branch(conn, repo):
    indexer.build_index(conn, repo, branch="main")
    rows = conn.execute("SELECT branch FROM files").fetchall()
    assert all(r["branch"] == "main" for r in rows)


def test_build_index_stats_carries_branch(conn, repo):
    stats = indexer.build_index(conn, repo, branch="feature/ui")
    assert stats.branch == "feature/ui"


def test_build_index_updates_branch_label_on_switch(conn, repo):
    indexer.build_index(conn, repo, branch="main")
    # Same files, different branch — no content change → skipped, but branch updated
    stats = indexer.build_index(conn, repo, branch="feature/x")
    assert stats.skipped == 2
    rows = conn.execute("SELECT branch FROM files").fetchall()
    assert all(r["branch"] == "feature/x" for r in rows)


def test_build_index_removes_orphans_after_branch_switch(conn, repo):
    """Files present on main but absent on feature branch are purged."""
    indexer.build_index(conn, repo, branch="main")

    # Simulate branch switch: b.py doesn't exist in new branch
    (repo / "b.py").unlink()
    stats = indexer.build_index(conn, repo, branch="feature/no-b")

    assert stats.removed == 1
    assert db.query_symbol(conn, "beta") == []
    assert db.query_symbol(conn, "alpha") != []


def test_build_index_reuses_symbols_for_unchanged_files(conn, repo):
    """Unchanged files are skipped — no re-parse — even when branch changes."""
    indexer.build_index(conn, repo, branch="main")
    stats = indexer.build_index(conn, repo, branch="feature/y")
    # Both files unchanged — both skipped, zero symbols re-added
    assert stats.skipped == 2
    assert stats.symbols_added == 0


def test_build_index_reindexes_changed_file_on_branch(conn, repo):
    """A file changed on the new branch is re-indexed."""
    indexer.build_index(conn, repo, branch="main")
    (repo / "a.py").write_text("def new_alpha(): pass\n")
    stats = indexer.build_index(conn, repo, branch="feature/changed-a")
    assert stats.indexed == 1
    assert stats.skipped == 1
    assert db.query_symbol(conn, "new_alpha") != []
    assert db.query_symbol(conn, "alpha") == []


# ---------------------------------------------------------------------------
# db: branch stats query
# ---------------------------------------------------------------------------

def test_query_branch_stats_returns_rows(conn, repo):
    indexer.build_index(conn, repo, branch="main")
    rows = db.query_branch_stats(conn)
    assert len(rows) == 1
    assert rows[0]["branch"] == "main"
    assert rows[0]["files"] == 2


def test_query_branch_stats_empty_when_nothing_indexed(conn):
    rows = db.query_branch_stats(conn)
    assert rows == []
