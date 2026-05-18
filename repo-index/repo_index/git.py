"""Git integration — branch detection and repository discovery."""

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
