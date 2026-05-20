"""Layered config loader — global → user → repo → task-type → CLI flags."""

from __future__ import annotations

try:
    import tomllib
except ImportError:
    try:
        import tomli as tomllib  # type: ignore[no-redef]
    except ImportError:
        tomllib = None  # type: ignore[assignment]
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .taxonomy import TaskType, Mode, Constraint


_GLOBAL_CONFIG_PATH = Path.home() / ".config" / "prompt-engine" / "config.toml"
_REPO_CONFIG_NAMES = [".prompt-engine.toml", "prompt-engine.toml"]


@dataclass
class EngineConfig:
    default_mode: Optional[Mode] = None
    default_profile: str = "balanced"
    max_tokens: int = 8000
    context_depth: int = 2
    require_tests: bool = True
    no_guessing: bool = True
    follow_existing_patterns: bool = True
    repo_name: Optional[str] = None
    repo_root: Optional[str] = None
    # Per-task-type mode overrides
    task_mode_overrides: dict[str, str] = field(default_factory=dict)
    # Extra constraints always applied
    always_on_constraints: list[str] = field(default_factory=list)
    # Never add these constraints
    disabled_constraints: list[str] = field(default_factory=list)
    # Custom policy text appended to system block
    repo_policy: str = ""

    def effective_mode(self, task_type: TaskType, fallback: Optional[Mode] = None) -> Optional[Mode]:
        override = self.task_mode_overrides.get(task_type.value)
        if override:
            try:
                return Mode(override)
            except ValueError:
                pass
        return self.default_mode or fallback

    def resolved_constraints(self) -> tuple[list[Constraint], list[Constraint]]:
        """Returns (always_on, disabled)."""
        always_on = []
        for c in self.always_on_constraints:
            try:
                always_on.append(Constraint(c))
            except ValueError:
                pass
        disabled = []
        for c in self.disabled_constraints:
            try:
                disabled.append(Constraint(c))
            except ValueError:
                pass
        return always_on, disabled


def _load_toml(path: Path) -> dict:
    if not path.exists():
        return {}
    if tomllib is None:
        return {}
    try:
        with open(path, "rb") as f:
            return tomllib.load(f)
    except (Exception, OSError):
        return {}


def _merge(base: dict, override: dict) -> dict:
    result = dict(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(result.get(k), dict):
            result[k] = _merge(result[k], v)
        else:
            result[k] = v
    return result


def _dict_to_config(data: dict) -> EngineConfig:
    cfg = EngineConfig()
    if "default_mode" in data:
        try:
            cfg.default_mode = Mode(data["default_mode"])
        except ValueError:
            pass
    for field_name in (
        "default_profile", "max_tokens", "context_depth",
        "require_tests", "no_guessing", "follow_existing_patterns",
        "repo_name", "repo_root", "repo_policy",
    ):
        if field_name in data:
            setattr(cfg, field_name, data[field_name])
    if "task_mode_overrides" in data:
        cfg.task_mode_overrides = dict(data["task_mode_overrides"])
    if "always_on_constraints" in data:
        cfg.always_on_constraints = list(data["always_on_constraints"])
    if "disabled_constraints" in data:
        cfg.disabled_constraints = list(data["disabled_constraints"])
    return cfg


def load_config(repo_root: Optional[Path] = None) -> EngineConfig:
    """Load config by merging global, repo, and detected settings."""
    global_data = _load_toml(_GLOBAL_CONFIG_PATH)

    repo_data: dict = {}
    search_root = repo_root or Path.cwd()
    for name in _REPO_CONFIG_NAMES:
        candidate = search_root / name
        if candidate.exists():
            repo_data = _load_toml(candidate)
            break
        parent_candidate = search_root.parent / name
        if parent_candidate.exists():
            repo_data = _load_toml(parent_candidate)
            break

    merged = _merge(global_data, repo_data)
    cfg = _dict_to_config(merged)

    if repo_root and not cfg.repo_root:
        cfg.repo_root = str(repo_root)

    return cfg


def write_default_config(path: Path = _GLOBAL_CONFIG_PATH) -> None:
    """Write a commented default config file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    content = """\
# prompt-engine global config
# Override any of these in a repo-local .prompt-engine.toml

# default_mode = "surgical"   # surgical | deep | fast | safe | explore | strict
default_profile = "balanced"  # fast | balanced | strict | architectural | experimental

max_tokens = 8000
context_depth = 2
require_tests = true
no_guessing = true
follow_existing_patterns = true

# repo_policy = "Services are thin. Business logic lives in domain layer."

# Per-task-type mode overrides:
# [task_mode_overrides]
# bugfix = "surgical"
# feature = "deep"
# migration = "safe"

# Constraints always added regardless of task type:
# always_on_constraints = ["follow_existing_patterns", "no_guessing"]

# Constraints never added:
# disabled_constraints = ["require_tests"]
"""
    path.write_text(content)
