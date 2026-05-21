"""Git integration — branch detection, repository discovery, and change analysis."""

import re
import subprocess
from pathlib import Path


def git_root(path: Path) -> Path | None:
    """Walk up from path to find the nearest .git directory."""
    for candidate in [path, *path.parents]:
        if (candidate / ".git").exists():
            return candidate
    return None


def is_git_repo(path: Path) -> bool:
    return git_root(path) is not None


def current_branch(root: Path) -> str:
    """Return the active branch name for the git repo at root.

    Reads .git/HEAD directly for speed. Falls back to subprocess.
    Returns '' when root is not inside a git repository.
    Returns the short SHA when in detached HEAD state.
    """
    repo = git_root(root)
    if repo is None:
        return ""

    head_path = repo / ".git" / "HEAD"
    try:
        content = head_path.read_text().strip()
    except OSError:
        return _branch_via_subprocess(root)

    if content.startswith("ref: refs/heads/"):
        return content[len("ref: refs/heads/"):]

    # Detached HEAD — content is the raw SHA
    return content[:12] if content else ""


def _branch_via_subprocess(root: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "branch", "--show-current"],
            capture_output=True,
            text=True,
            check=True,
            cwd=str(root),
        )
        return result.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return ""


def recently_changed_files(root: Path, n: int = 10) -> list[str]:
    """Return relative paths of files touched in the last n commits, newest first."""
    try:
        result = subprocess.run(
            ["git", "log", f"--max-count={n}", "--name-only", "--format="],
            cwd=str(root), capture_output=True, text=True, timeout=5,
        )
        if result.returncode != 0:
            return []
        files = [ln.strip() for ln in result.stdout.splitlines() if ln.strip()]
        return list(dict.fromkeys(files))  # deduplicate, preserve order
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return []


def commit_log_summary(root: Path, n: int = 5) -> str:
    """Return the last n commit messages as a compact one-line-per-commit string."""
    try:
        result = subprocess.run(
            ["git", "log", f"--max-count={n}", "--oneline"],
            cwd=str(root), capture_output=True, text=True, timeout=5,
        )
        if result.returncode != 0:
            return ""
        return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return ""


def extract_changed_symbol_names(root: Path, ref: str = "HEAD~3") -> list[str]:
    """Parse git diff to extract names of modified functions and classes since ref.

    Uses hunk headers (@@…@@ def/class name) and added definition lines.
    Returns deduplicated names in order of first appearance.
    """
    try:
        result = subprocess.run(
            ["git", "diff", ref, "HEAD", "--unified=0"],
            cwd=str(root), capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return []
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return []

    names: list[str] = []
    hunk_context_re = re.compile(
        r"@@[^@]*@@\s*(?:async\s+)?(?:def|class)\s+([A-Za-z_][A-Za-z0-9_]*)"
    )
    added_def_re = re.compile(
        r"^\+\s*(?:async\s+)?(?:def|class)\s+([A-Za-z_][A-Za-z0-9_]*)"
    )
    for line in result.stdout.splitlines():
        m = hunk_context_re.search(line) if line.startswith("@@") else None
        if m:
            names.append(m.group(1))
            continue
        m = added_def_re.match(line)
        if m:
            names.append(m.group(1))

    return list(dict.fromkeys(names))  # deduplicate, preserve order
