"""FQID generation utilities — stable fully-qualified symbol identities."""

from pathlib import Path


def file_to_module(file_path: str) -> str:
    """Derive a dotted module name from a relative file path.

    repo_index/db.py  →  repo_index.db
    auth/jwt.py       →  auth.jwt
    auth/__init__.py  →  auth
    """
    p = Path(file_path)
    parts = list(p.parts)
    if parts and parts[-1].endswith(".py"):
        parts[-1] = parts[-1][:-3]
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def make_fqid(module: str, class_name: str | None, symbol_name: str) -> str:
    """Build a fully-qualified symbol identifier.

    make_fqid("auth.jwt", "JWTService", "refresh") → "auth.jwt.JWTService.refresh"
    make_fqid("auth.jwt", None, "validate_token")  → "auth.jwt.validate_token"
    """
    parts = [p for p in (module, class_name, symbol_name) if p]
    return ".".join(parts)
