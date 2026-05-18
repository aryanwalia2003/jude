"""Filesystem watcher — event-driven incremental index updates.

Architecture:
  watchdog Observer  →  _DebouncedHandler  →  Queue  →  _worker thread  →  indexer
  (OS inotify/FSEvents)   (per-path debounce)           (single DB writer)
"""

import queue
import sqlite3
import threading
from pathlib import Path

from watchdog.events import (
    FileSystemEventHandler,
    EVENT_TYPE_CREATED,
    EVENT_TYPE_DELETED,
    EVENT_TYPE_MODIFIED,
    EVENT_TYPE_MOVED,
)
from watchdog.observers import Observer

from . import indexer
from .events import EventKind, FileEvent
from .scanner import is_indexable


_DEBOUNCE_SECONDS = 0.3
_WORKER_POLL_SECONDS = 0.5


def _to_event_kind(watchdog_type: str) -> EventKind:
    return {
        EVENT_TYPE_CREATED:  EventKind.CREATED,
        EVENT_TYPE_MODIFIED: EventKind.MODIFIED,
        EVENT_TYPE_DELETED:  EventKind.DELETED,
        EVENT_TYPE_MOVED:    EventKind.MOVED,
    }[watchdog_type]


class _DebouncedHandler(FileSystemEventHandler):
    """Converts watchdog events → FileEvents, coalescing rapid writes per path."""

    def __init__(self, event_queue: queue.Queue, debounce: float = _DEBOUNCE_SECONDS) -> None:
        super().__init__()
        self._queue = event_queue
        self._debounce = debounce
        self._timers: dict[str, threading.Timer] = {}
        self._lock = threading.Lock()

    def on_any_event(self, raw) -> None:
        if raw.is_directory:
            return

        path = Path(raw.src_path)
        dest = Path(raw.dest_path) if raw.event_type == EVENT_TYPE_MOVED else None

        if not is_indexable(path) and (dest is None or not is_indexable(dest)):
            return

        event = FileEvent(kind=_to_event_kind(raw.event_type), path=path, dest=dest)
        self._debounce_enqueue(str(path), event)

    def _debounce_enqueue(self, key: str, event: FileEvent) -> None:
        with self._lock:
            existing = self._timers.get(key)
            if existing:
                existing.cancel()
            timer = threading.Timer(self._debounce, self._queue.put, args=[event])
            self._timers[key] = timer
            timer.start()

    def flush(self) -> None:
        """Cancel all pending timers and fire them immediately. Used in tests."""
        with self._lock:
            for timer in self._timers.values():
                timer.cancel()
                # call the function directly (timer.function / timer.args)
                if timer.args:
                    timer.function(*timer.args)
            self._timers.clear()


class FileWatcher:
    """Watches a directory tree and keeps the index up to date."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        root: Path,
        on_event: "Callable[[FileEvent, indexer.IndexStats | None], None] | None" = None,
    ) -> None:
        self._conn = conn
        self._root = root
        self._on_event = on_event
        self._queue: queue.Queue[FileEvent] = queue.Queue()
        self._stop = threading.Event()
        self._handler = _DebouncedHandler(self._queue)
        self._observer = Observer()
        self._observer.schedule(self._handler, str(root), recursive=True)
        self._worker_thread = threading.Thread(target=self._worker, daemon=True, name="repo-index-worker")

    def start(self) -> None:
        self._observer.start()
        self._worker_thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._observer.stop()
        self._observer.join()
        self._worker_thread.join(timeout=2)

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *_):
        self.stop()

    def _worker(self) -> None:
        while not self._stop.is_set():
            try:
                event = self._queue.get(timeout=_WORKER_POLL_SECONDS)
            except queue.Empty:
                continue
            stats = self._process(event)
            if self._on_event:
                self._on_event(event, stats)
            self._queue.task_done()

    def _process(self, event: FileEvent) -> "indexer.IndexStats | None":
        if event.kind in (EventKind.CREATED, EventKind.MODIFIED):
            if is_indexable(event.path):
                return indexer.index_single_file(self._conn, event.path, self._root)

        elif event.kind == EventKind.DELETED:
            if is_indexable(event.path):
                indexer.remove_indexed_file(self._conn, event.path, self._root)

        elif event.kind == EventKind.MOVED:
            if is_indexable(event.path):
                indexer.remove_indexed_file(self._conn, event.path, self._root)
            if event.dest and is_indexable(event.dest):
                return indexer.index_single_file(self._conn, event.dest, self._root)

        return None
