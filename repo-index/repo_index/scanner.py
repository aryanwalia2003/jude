"""File discovery using fd with ripgrep fallback."""

import subprocess
from pathlib import Path

from .parsers import get_parser


_SKIP_DIRS = {
    ".git", ".hg", ".svn", "node_modules", "__pycache__",
    ".venv", "venv", "env", ".env", "dist", "build",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", "target",
    ".tox", "coverage", ".coverage",
}

_SUPPORTED_EXTENSIONS = {".py"}  # grows as parsers are added


def is_indexable(path: Path) -> bool:
    """True if path has a supported extension and is not inside a skip directory."""
    return (
        path.suffix.lower() in _SUPPORTED_EXTENSIONS
        and not any(part in _SKIP_DIRS for part in path.parts)
    )


def discover_files(root: Path) -> list[Path]:
    """Return all indexable source files under root, sorted."""
    try:
        return _discover_with_fd(root)
    except FileNotFoundError:
        return _discover_with_pathlib(root)


def _discover_with_fd(root: Path) -> list[Path]:
    ext_args = []
    for ext in _SUPPORTED_EXTENSIONS:
        ext_args += ["--extension", ext.lstrip(".")]

    exclude_args = []
    for d in _SKIP_DIRS:
        exclude_args += ["--exclude", d]

    result = subprocess.run(
        ["fd", "--type", "f", "--follow", *ext_args, *exclude_args, ".", str(root)],
        capture_output=True,
        text=True,
        check=True,
    )
    return sorted(Path(p) for p in result.stdout.splitlines() if p.strip())


def _discover_with_pathlib(root: Path) -> list[Path]:
    files = []
    for ext in _SUPPORTED_EXTENSIONS:
        for path in root.rglob(f"*{ext}"):
            if not any(skip in path.parts for skip in _SKIP_DIRS):
                files.append(path)
    return sorted(files)
