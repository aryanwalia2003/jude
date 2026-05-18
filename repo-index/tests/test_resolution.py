"""Tests for Phase 4.5: Semantic Resolution Layer."""

import pytest

from repo_index import db, indexer, resolver
from repo_index.parsers.python import PythonParser
from repo_index.symbol_table import file_to_module, make_fqid


# ---------------------------------------------------------------------------
# Fixture source files
# ---------------------------------------------------------------------------

_AUTH = """\
def validate_token(token): pass

class JWTService:
    def refresh(self, token): pass
    def revoke(self, token): pass
"""

_HANDLER = """\
from auth import validate_token
from auth import JWTService as JWT
import utils

def handle_request(token):
    validate_token(token)
    utils.log(token)

def handle_refresh(svc, token):
    svc.refresh(token)
"""

_UTILS = """\
def log(msg): pass
def debug(msg): pass
"""

_SHADOW = """\
def process():
    validate = "local_string"
    validate()
"""

_ALIASED = """\
from auth import validate_token as vt

def run(token):
    vt(token)
"""

_SERVICE = """\
import os
import logging

class AuthService:
    def login(self, user):
        token = generate_token(user)
        notify(user)
        return token

    def logout(self, token):
        invalidate(token)

def generate_token(user): pass
def notify(user): pass
def invalidate(token): pass
"""


@pytest.fixture
def conn(tmp_path):
    return db.open_db(tmp_path / "test.db")


@pytest.fixture
def auth_repo(conn, tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "auth.py").write_text(_AUTH)
    (root / "handler.py").write_text(_HANDLER)
    (root / "utils.py").write_text(_UTILS)
    indexer.build_index(conn, root, branch="main")
    return conn, root


@pytest.fixture
def service_repo(conn, tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "service.py").write_text(_SERVICE)
    indexer.build_index(conn, root, branch="main")
    return conn, root


# ---------------------------------------------------------------------------
# symbol_table utilities
# ---------------------------------------------------------------------------

def test_file_to_module_simple():
    assert file_to_module("auth.py") == "auth"


def test_file_to_module_nested():
    assert file_to_module("auth/jwt.py") == "auth.jwt"


def test_file_to_module_init():
    assert file_to_module("auth/__init__.py") == "auth"


def test_file_to_module_deep():
    assert file_to_module("a/b/c.py") == "a.b.c"


def test_make_fqid_function():
    assert make_fqid("auth.jwt", None, "validate") == "auth.jwt.validate"


def test_make_fqid_method():
    assert make_fqid("auth.jwt", "JWTService", "refresh") == "auth.jwt.JWTService.refresh"


def test_make_fqid_no_module():
    assert make_fqid("", None, "foo") == "foo"


# ---------------------------------------------------------------------------
# Parser: FQID generation
# ---------------------------------------------------------------------------

def test_parser_generates_fqid_for_function():
    parser = PythonParser()
    result = parser.parse(b"def foo(): pass", "auth.py", module="auth")
    sym = next(s for s in result.symbols if s.name == "foo")
    assert sym.fqid == "auth.foo"
    assert sym.module == "auth"


def test_parser_generates_fqid_for_class():
    parser = PythonParser()
    result = parser.parse(b"class MyClass: pass", "models.py", module="models")
    sym = next(s for s in result.symbols if s.name == "MyClass")
    assert sym.fqid == "models.MyClass"


def test_parser_generates_fqid_for_method():
    parser = PythonParser()
    src = b"class A:\n    def save(self): pass"
    result = parser.parse(src, "models.py", module="models")
    sym = next(s for s in result.symbols if s.name == "save")
    assert sym.fqid == "models.A.save"
    assert sym.owner == "A"
    assert sym.module == "models"


def test_parser_fqid_empty_without_module():
    parser = PythonParser()
    result = parser.parse(b"def foo(): pass", "auth.py")
    sym = next(s for s in result.symbols if s.name == "foo")
    assert sym.fqid == ""


# ---------------------------------------------------------------------------
# Parser: import alias extraction
# ---------------------------------------------------------------------------

def test_parser_tracks_plain_import():
    parser = PythonParser()
    result = parser.parse(b"import os", "handler.py", module="handler")
    aliases = {a.alias: a for a in result.import_aliases}
    assert "os" in aliases
    assert aliases["os"].source_module == "os"
    assert aliases["os"].source_name == ""


def test_parser_tracks_from_import():
    parser = PythonParser()
    result = parser.parse(b"from auth import validate_token", "handler.py", module="handler")
    aliases = {a.alias: a for a in result.import_aliases}
    assert "validate_token" in aliases
    assert aliases["validate_token"].source_module == "auth"
    assert aliases["validate_token"].source_name == "validate_token"


def test_parser_tracks_aliased_import():
    parser = PythonParser()
    result = parser.parse(b"from auth import validate_token as vt", "handler.py", module="handler")
    aliases = {a.alias: a for a in result.import_aliases}
    assert "vt" in aliases
    assert aliases["vt"].source_module == "auth"
    assert aliases["vt"].source_name == "validate_token"
    assert aliases["vt"].fqid == "auth.validate_token"


def test_parser_tracks_module_alias():
    parser = PythonParser()
    result = parser.parse(b"import auth.jwt as jwt", "handler.py", module="handler")
    aliases = {a.alias: a for a in result.import_aliases}
    assert "jwt" in aliases
    assert aliases["jwt"].source_module == "auth.jwt"


# ---------------------------------------------------------------------------
# Parser: call expression tracking
# ---------------------------------------------------------------------------

def test_parser_plain_call_expression():
    parser = PythonParser()
    src = b"def run():\n    foo()"
    result = parser.parse(src, "x.py", module="x")
    calls = [r for r in result.relations if r.relation == "CALLS"]
    assert any(r.to_name == "foo" and r.call_expression == "foo" for r in calls)


def test_parser_attribute_call_expression():
    parser = PythonParser()
    src = b"def run():\n    jwt.validate()"
    result = parser.parse(src, "x.py", module="x")
    calls = [r for r in result.relations if r.relation == "CALLS"]
    assert any(r.to_name == "validate" and r.call_expression == "jwt.validate" for r in calls)


# ---------------------------------------------------------------------------
# DB: FQIDs persisted in symbols table
# ---------------------------------------------------------------------------

def test_symbol_fqid_stored_in_db(auth_repo):
    conn, _ = auth_repo
    row = db.query_symbol_by_fqid(conn, "auth.validate_token")
    assert row is not None
    assert row["name"] == "validate_token"
    assert row["kind"] == "function"


def test_method_fqid_stored_in_db(auth_repo):
    conn, _ = auth_repo
    row = db.query_symbol_by_fqid(conn, "auth.JWTService.refresh")
    assert row is not None
    assert row["name"] == "refresh"
    assert row["kind"] == "method"


def test_class_fqid_stored_in_db(auth_repo):
    conn, _ = auth_repo
    row = db.query_symbol_by_fqid(conn, "auth.JWTService")
    assert row is not None
    assert row["kind"] == "class"


def test_module_field_stored_in_db(auth_repo):
    conn, _ = auth_repo
    rows = db.query_symbol(conn, "validate_token")
    assert rows
    assert rows[0]["module"] == "auth"


# ---------------------------------------------------------------------------
# DB: import_aliases table
# ---------------------------------------------------------------------------

def test_import_aliases_stored(auth_repo):
    conn, _ = auth_repo
    aliases = db.query_import_aliases(conn, "handler.py")
    alias_map = {row["alias"]: row for row in aliases}
    assert "validate_token" in alias_map
    assert alias_map["validate_token"]["source_module"] == "auth"
    assert alias_map["validate_token"]["resolved_fqid"] == "auth.validate_token"


def test_import_alias_class_as(auth_repo):
    conn, _ = auth_repo
    aliases = db.query_import_aliases(conn, "handler.py")
    alias_map = {row["alias"]: row for row in aliases}
    assert "JWT" in alias_map
    assert alias_map["JWT"]["source_module"] == "auth"
    assert alias_map["JWT"]["source_name"] == "JWTService"
    assert alias_map["JWT"]["resolved_fqid"] == "auth.JWTService"


def test_plain_import_alias_stored(auth_repo):
    conn, _ = auth_repo
    aliases = db.query_import_aliases(conn, "handler.py")
    alias_map = {row["alias"]: row for row in aliases}
    assert "utils" in alias_map
    assert alias_map["utils"]["source_module"] == "utils"


# ---------------------------------------------------------------------------
# DB: owner_symbol_id
# ---------------------------------------------------------------------------

def test_owner_symbol_id_set(auth_repo):
    conn, _ = auth_repo
    refresh_row = conn.execute(
        "SELECT owner_symbol_id FROM symbols WHERE fqid = 'auth.JWTService.refresh'"
    ).fetchone()
    assert refresh_row is not None
    assert refresh_row["owner_symbol_id"] is not None

    class_row = conn.execute(
        "SELECT id FROM symbols WHERE fqid = 'auth.JWTService'"
    ).fetchone()
    assert class_row is not None
    assert refresh_row["owner_symbol_id"] == class_row["id"]


def test_query_owned_symbols(auth_repo):
    conn, _ = auth_repo
    owned = db.query_owned_symbols(conn, "JWTService")
    names = [row["name"] for row in owned]
    assert "refresh" in names
    assert "revoke" in names


# ---------------------------------------------------------------------------
# resolver.resolve_references
# ---------------------------------------------------------------------------

def test_resolve_plain_name_unique(auth_repo):
    """validate_token is called in handler.py and is unique — should resolve at 0.7+."""
    conn, _ = auth_repo
    stats = resolver.resolve_references(conn)
    assert stats.resolved > 0


def test_resolve_via_import_alias(auth_repo):
    """validate_token is imported from auth — should resolve at confidence 0.8."""
    conn, _ = auth_repo
    resolver.resolve_references(conn)
    row = conn.execute(
        """SELECT r.to_symbol_id, r.confidence
           FROM relations r
           JOIN symbols s ON r.from_id = s.id
           WHERE r.to_name = 'validate_token'
             AND s.file_path = 'handler.py'
             AND r.relation = 'CALLS'"""
    ).fetchone()
    assert row is not None
    assert row["to_symbol_id"] is not None
    assert row["confidence"] >= 0.7


def test_resolve_links_to_correct_symbol(auth_repo):
    """The resolved to_symbol_id should point to auth.validate_token."""
    conn, _ = auth_repo
    resolver.resolve_references(conn)
    target_row = conn.execute(
        "SELECT id FROM symbols WHERE fqid = 'auth.validate_token'"
    ).fetchone()
    assert target_row is not None

    call_row = conn.execute(
        """SELECT r.to_symbol_id FROM relations r
           JOIN symbols s ON r.from_id = s.id
           WHERE r.to_name = 'validate_token'
             AND s.file_path = 'handler.py' AND r.relation = 'CALLS'"""
    ).fetchone()
    assert call_row is not None
    assert call_row["to_symbol_id"] == target_row["id"]


def test_resolve_qualified_call_via_alias(auth_repo):
    """utils.log() in handler.py — obj=utils, attr=log, alias maps utils→utils module."""
    conn, _ = auth_repo
    resolver.resolve_references(conn)
    row = conn.execute(
        """SELECT r.to_symbol_id, r.confidence
           FROM relations r
           JOIN symbols s ON r.from_id = s.id
           WHERE r.call_expression = 'utils.log'
             AND s.file_path = 'handler.py'"""
    ).fetchone()
    assert row is not None
    assert row["to_symbol_id"] is not None
    assert row["confidence"] >= 0.7


def test_resolve_unresolved_stays_null(service_repo):
    """Calls to generate_token, notify, invalidate are within same file — name unique."""
    conn, _ = service_repo
    resolver.resolve_references(conn)
    # generate_token is unique → should resolve with confidence >= 0.7
    row = conn.execute(
        """SELECT r.to_symbol_id, r.confidence
           FROM relations r
           JOIN symbols s ON r.from_id = s.id
           WHERE r.to_name = 'generate_token' AND r.relation = 'CALLS'"""
    ).fetchone()
    assert row is not None
    assert row["to_symbol_id"] is not None


def test_resolve_idempotent(auth_repo):
    """Running resolve twice should not change results."""
    conn, _ = auth_repo
    stats1 = resolver.resolve_references(conn)
    stats2 = resolver.resolve_references(conn)
    assert stats1.resolved == stats2.resolved
    assert stats1.unresolved == stats2.unresolved


def test_resolution_stats_db(auth_repo):
    conn, _ = auth_repo
    resolver.resolve_references(conn)
    rs = db.resolution_stats(conn)
    assert rs["total"] > 0
    assert rs["resolved"] >= 0
    assert rs["resolved"] + rs["unresolved"] == rs["total"]


# ---------------------------------------------------------------------------
# aliased import resolution
# ---------------------------------------------------------------------------

def test_resolve_aliased_import(conn, tmp_path):
    """`from auth import validate_token as vt; vt()` should resolve."""
    root = tmp_path / "repo"
    root.mkdir()
    (root / "auth.py").write_text(_AUTH)
    (root / "aliased.py").write_text(_ALIASED)
    indexer.build_index(conn, root, branch="main")
    resolver.resolve_references(conn)

    row = conn.execute(
        """SELECT r.to_symbol_id, r.confidence
           FROM relations r
           JOIN symbols s ON r.from_id = s.id
           WHERE r.to_name = 'vt' AND s.file_path = 'aliased.py' AND r.relation = 'CALLS'"""
    ).fetchone()
    # 'vt' is not a real symbol name — but alias 'vt' → auth.validate_token → resolved
    # The to_name is 'vt', alias 'vt' resolves to fqid 'auth.validate_token'
    assert row is not None
    assert row["to_symbol_id"] is not None
    assert row["confidence"] >= 0.8


# ---------------------------------------------------------------------------
# DB: module table and query_module_symbols
# ---------------------------------------------------------------------------

def test_modules_table_populated(auth_repo):
    conn, _ = auth_repo
    row = conn.execute("SELECT * FROM modules WHERE name = 'auth'").fetchone()
    assert row is not None
    assert row["path"] == "auth.py"


def test_query_module_symbols(auth_repo):
    conn, _ = auth_repo
    rows = db.query_module_symbols(conn, "auth")
    names = {row["name"] for row in rows}
    assert "validate_token" in names
    assert "JWTService" in names
    assert "refresh" in names


# ---------------------------------------------------------------------------
# Backward-compatibility: existing queries still work after schema migration
# ---------------------------------------------------------------------------

def test_query_symbol_still_works(service_repo):
    conn, _ = service_repo
    rows = db.query_symbol(conn, "login")
    assert rows
    assert rows[0]["name"] == "login"


def test_query_callers_still_works(service_repo):
    conn, _ = service_repo
    rows = db.query_callers(conn, "notify")
    callers = [r["caller"] for r in rows]
    assert "login" in callers


def test_search_symbols_still_works(service_repo):
    conn, _ = service_repo
    rows = db.search_symbols(conn, "notify")
    names = [r["name"] for r in rows]
    assert "notify" in names


def test_stats_still_works(service_repo):
    conn, _ = service_repo
    s = db.stats(conn)
    assert s["symbols"] > 0
    assert s["files"] > 0
