"""Internal event vocabulary for the filesystem watcher pipeline."""

from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
import time


class EventKind(Enum):
    CREATED = auto()
    MODIFIED = auto()
    DELETED = auto()
    MOVED = auto()


@dataclass
class FileEvent:
    kind: EventKind
    path: Path
    dest: Path | None = None          # only set for MOVED
    timestamp: float = field(default_factory=time.monotonic)
