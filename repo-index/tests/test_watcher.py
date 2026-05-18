"""Tests for Phase 2: event-driven incremental indexing.

We test the indexer entry points and event processing logic directly,
not the OS-level watchdog observer (which would be slow and environment-dependent).
"""

import queue
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from repo_index import db, indexer
from repo_index.events import EventKind, FileEvent
from repo_index.scanner import is_indexable
from repo_index.watcher import _DebouncedHandler, FileWatcher


# ---------------------------------------------------------------------------
# is_indexable
# ---------------------------------------------------------------------------

def test_python_file_is_indexable():
    assert is_indexable(Path("project/service.py"))


def test_non_python_file_is_not_indexable():
    assert not is_indexable(Path("project/README.md"))
    assert not is_indexable(Path("project/main.go"))


def test_file_in_skip_dir_is_not_indexable():
    assert not is_indexable(Path("project/__pycache__/service.cpython-310.pyc"))
    assert not is_indexable(Path("project/.venv/lib/site.py"))
    assert not is_indexable(Path("project/node_modules/thing.py"))


def test_file_in_nested_skip_dir_is_not_indexable():
    assert not is_indexable(Path("a/b/__pycache__/c.py"))


# ---------------------------------------------------------------------------
# index_single_file / remove_indexed_file
# ---------------------------------------------------------------------------

@pytest.fixture
def conn(tmp_path):
    return db.open_db(tmp_path / "test.db")


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "svc.py").write_text("def handle(): pass\n")
    return root


def test_index_single_file_creates_symbol(conn, repo):
    stats = indexer.index_single_file(conn, repo / "svc.py", repo)
    assert stats.indexed == 1
    assert db.query_symbol(conn, "handle") != []


def test_index_single_file_skips_unchanged(conn, repo):
    indexer.index_single_file(conn, repo / "svc.py", repo)
    stats = indexer.index_single_file(conn, repo / "svc.py", repo)
    assert stats.skipped == 1


def test_index_single_file_reindexes_on_change(conn, repo):
    indexer.index_single_file(conn, repo / "svc.py", repo)
    (repo / "svc.py").write_text("def new_fn(): pass\n")
    indexer.index_single_file(conn, repo / "svc.py", repo)
    assert db.query_symbol(conn, "new_fn") != []
    assert db.query_symbol(conn, "handle") == []


def test_remove_indexed_file_purges_symbols(conn, repo):
    indexer.index_single_file(conn, repo / "svc.py", repo)
    assert db.query_symbol(conn, "handle") != []
    indexer.remove_indexed_file(conn, repo / "svc.py", repo)
    assert db.query_symbol(conn, "handle") == []


def test_remove_indexed_file_purges_file_record(conn, repo):
    indexer.index_single_file(conn, repo / "svc.py", repo)
    indexer.remove_indexed_file(conn, repo / "svc.py", repo)
    assert db.get_file_hash(conn, "svc.py") is None


# ---------------------------------------------------------------------------
# _DebouncedHandler — event filtering and debounce coalescing
# ---------------------------------------------------------------------------

def _make_raw_event(event_type: str, src: str, is_dir: bool = False, dest: str = ""):
    raw = MagicMock()
    raw.event_type = event_type
    raw.src_path = src
    raw.dest_path = dest
    raw.is_directory = is_dir
    return raw


def test_handler_ignores_directory_events():
    q = queue.Queue()
    handler = _DebouncedHandler(q, debounce=0.05)
    handler.on_any_event(_make_raw_event("modified", "/repo/src", is_dir=True))
    time.sleep(0.1)
    assert q.empty()


def test_handler_ignores_non_indexable_files():
    q = queue.Queue()
    handler = _DebouncedHandler(q, debounce=0.05)
    handler.on_any_event(_make_raw_event("modified", "/repo/README.md"))
    time.sleep(0.1)
    assert q.empty()


def test_handler_enqueues_python_file_event():
    q = queue.Queue()
    handler = _DebouncedHandler(q, debounce=0.05)
    handler.on_any_event(_make_raw_event("modified", "/repo/svc.py"))
    event = q.get(timeout=1)
    assert event.kind == EventKind.MODIFIED
    assert event.path == Path("/repo/svc.py")


def test_handler_coalesces_rapid_events_for_same_path():
    q = queue.Queue()
    handler = _DebouncedHandler(q, debounce=0.1)
    for _ in range(5):
        handler.on_any_event(_make_raw_event("modified", "/repo/svc.py"))
    time.sleep(0.3)
    assert q.qsize() == 1


def test_handler_does_not_coalesce_different_paths():
    q = queue.Queue()
    handler = _DebouncedHandler(q, debounce=0.05)
    handler.on_any_event(_make_raw_event("modified", "/repo/a.py"))
    handler.on_any_event(_make_raw_event("modified", "/repo/b.py"))
    time.sleep(0.2)
    assert q.qsize() == 2


def test_handler_enqueues_deleted_event():
    q = queue.Queue()
    handler = _DebouncedHandler(q, debounce=0.05)
    handler.on_any_event(_make_raw_event("deleted", "/repo/svc.py"))
    event = q.get(timeout=1)
    assert event.kind == EventKind.DELETED


def test_handler_enqueues_moved_event_with_dest():
    q = queue.Queue()
    handler = _DebouncedHandler(q, debounce=0.05)
    handler.on_any_event(_make_raw_event("moved", "/repo/old.py", dest="/repo/new.py"))
    event = q.get(timeout=1)
    assert event.kind == EventKind.MOVED
    assert event.dest == Path("/repo/new.py")


# ---------------------------------------------------------------------------
# FileWatcher._process — dispatch logic
# ---------------------------------------------------------------------------

@pytest.fixture
def watcher_fixture(conn, repo):
    watcher = FileWatcher(conn, repo)
    return watcher, conn, repo


def test_process_created_indexes_file(watcher_fixture):
    watcher, conn, repo = watcher_fixture
    event = FileEvent(kind=EventKind.CREATED, path=repo / "svc.py")
    watcher._process(event)
    assert db.query_symbol(conn, "handle") != []


def test_process_modified_reindexes_file(watcher_fixture):
    watcher, conn, repo = watcher_fixture
    indexer.index_single_file(conn, repo / "svc.py", repo)
    (repo / "svc.py").write_text("def updated(): pass\n")
    event = FileEvent(kind=EventKind.MODIFIED, path=repo / "svc.py")
    watcher._process(event)
    assert db.query_symbol(conn, "updated") != []
    assert db.query_symbol(conn, "handle") == []


def test_process_deleted_removes_file(watcher_fixture):
    watcher, conn, repo = watcher_fixture
    indexer.index_single_file(conn, repo / "svc.py", repo)
    event = FileEvent(kind=EventKind.DELETED, path=repo / "svc.py")
    watcher._process(event)
    assert db.query_symbol(conn, "handle") == []


def test_process_moved_updates_index(watcher_fixture, tmp_path):
    watcher, conn, repo = watcher_fixture
    indexer.index_single_file(conn, repo / "svc.py", repo)
    dest = repo / "renamed.py"
    (repo / "svc.py").rename(dest)
    dest.write_text("def renamed_fn(): pass\n")
    event = FileEvent(kind=EventKind.MOVED, path=repo / "svc.py", dest=dest)
    watcher._process(event)
    assert db.query_symbol(conn, "handle") == []
    assert db.query_symbol(conn, "renamed_fn") != []


def test_process_ignores_non_indexable_created(watcher_fixture):
    watcher, conn, repo = watcher_fixture
    event = FileEvent(kind=EventKind.CREATED, path=repo / "notes.txt")
    watcher._process(event)
    s = db.stats(conn)
    assert s["symbols"] == 0
