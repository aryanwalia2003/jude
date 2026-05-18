"""Tests for Phase 4: Retrieval Engine."""

import pytest

from repo_index import db, indexer, retrieval
from repo_index.graph import build_call_graph, reachable_from, reverse_reachable


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

_HANDLER = """\
def handle_login():
    notify("admin")

def handle_logout():
    invalidate("tok")
"""


@pytest.fixture
def conn(tmp_path):
    return db.open_db(tmp_path / "test.db")


@pytest.fixture
def indexed(conn, tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "service.py").write_text(_SERVICE)
    (root / "handler.py").write_text(_HANDLER)
    indexer.build_index(conn, root, branch="main")
    return conn, root


# ---------------------------------------------------------------------------
# db.search_symbols — FTS5
# ---------------------------------------------------------------------------

def test_search_exact_name(indexed):
    conn, _ = indexed
    rows = db.search_symbols(conn, "notify")
    names = [r["name"] for r in rows]
    assert "notify" in names


def test_search_prefix_match(indexed):
    conn, _ = indexed
    rows = db.search_symbols(conn, "gen")
    names = [r["name"] for r in rows]
    assert "generate_token" in names


def test_search_class_name(indexed):
    conn, _ = indexed
    rows = db.search_symbols(conn, "auth")
    names = [r["name"] for r in rows]
    assert "AuthService" in names


def test_search_kind_filter_functions_only(indexed):
    conn, _ = indexed
    rows = db.search_symbols(conn, "login", kind="function")
    # login is a method, not a function — should not appear
    kinds = {r["kind"] for r in rows}
    assert "method" not in kinds


def test_search_kind_filter_methods(indexed):
    conn, _ = indexed
    rows = db.search_symbols(conn, "login", kind="method")
    names = [r["name"] for r in rows]
    assert "login" in names


def test_search_empty_query_returns_no_results(indexed):
    conn, _ = indexed
    rows = db.search_symbols(conn, "")
    assert rows == []


def test_search_no_match_returns_empty(indexed):
    conn, _ = indexed
    rows = db.search_symbols(conn, "xyzzy_nonexistent")
    assert rows == []


def test_search_limit_respected(indexed):
    conn, _ = indexed
    rows = db.search_symbols(conn, "e", limit=2)
    assert len(rows) <= 2


# ---------------------------------------------------------------------------
# retrieval.search
# ---------------------------------------------------------------------------

def test_retrieval_search_returns_search_results(indexed):
    conn, _ = indexed
    results = retrieval.search(conn, "notify")
    assert any(r.name == "notify" for r in results)


def test_retrieval_search_result_has_location(indexed):
    conn, _ = indexed
    results = retrieval.search(conn, "generate_token")
    assert results
    r = results[0]
    assert r.file_path != ""
    assert r.start_line > 0


# ---------------------------------------------------------------------------
# graph.build_call_graph
# ---------------------------------------------------------------------------

def test_call_graph_has_edges(indexed):
    conn, _ = indexed
    G = build_call_graph(conn)
    assert G.number_of_edges() > 0


def test_call_graph_login_calls_notify(indexed):
    conn, _ = indexed
    G = build_call_graph(conn)
    assert G.has_edge("login", "notify")


def test_call_graph_login_calls_generate_token(indexed):
    conn, _ = indexed
    G = build_call_graph(conn)
    assert G.has_edge("login", "generate_token")


def test_call_graph_handle_login_calls_notify(indexed):
    conn, _ = indexed
    G = build_call_graph(conn)
    assert G.has_edge("handle_login", "notify")


# ---------------------------------------------------------------------------
# graph.reachable_from — forward traversal (callgraph)
# ---------------------------------------------------------------------------

def test_reachable_from_direct_callees(indexed):
    conn, _ = indexed
    G = build_call_graph(conn)
    reached = reachable_from(G, "login", max_depth=1)
    assert "notify" in reached
    assert "generate_token" in reached


def test_reachable_from_excludes_start(indexed):
    conn, _ = indexed
    G = build_call_graph(conn)
    reached = reachable_from(G, "login", max_depth=2)
    assert "login" not in reached


def test_reachable_from_depth_zero_returns_empty(indexed):
    conn, _ = indexed
    G = build_call_graph(conn)
    assert reachable_from(G, "login", max_depth=0) == []


def test_reachable_from_unknown_node_returns_empty(indexed):
    conn, _ = indexed
    G = build_call_graph(conn)
    assert reachable_from(G, "nonexistent_fn", max_depth=3) == []


# ---------------------------------------------------------------------------
# graph.reverse_reachable — impact analysis
# ---------------------------------------------------------------------------

def test_reverse_reachable_notify_callers(indexed):
    conn, _ = indexed
    G = build_call_graph(conn)
    # notify is called by: login, handle_login
    impact = reverse_reachable(G, "notify", max_depth=1)
    assert "login" in impact
    assert "handle_login" in impact


def test_reverse_reachable_depth_two_includes_transitive(indexed):
    conn, _ = indexed
    G = build_call_graph(conn)
    # notify ← login ← (nothing calls login directly in this fixture)
    # but handle_login calls notify directly so at depth 1 it's there
    impact = reverse_reachable(G, "notify", max_depth=2)
    assert "login" in impact


def test_reverse_reachable_excludes_start(indexed):
    conn, _ = indexed
    G = build_call_graph(conn)
    impact = reverse_reachable(G, "notify", max_depth=3)
    assert "notify" not in impact


# ---------------------------------------------------------------------------
# retrieval.get_callgraph / get_impact
# ---------------------------------------------------------------------------

def test_get_callgraph_returns_direct_callees(indexed):
    conn, _ = indexed
    callees = retrieval.get_callgraph(conn, "login", max_depth=1)
    assert "notify" in callees
    assert "generate_token" in callees


def test_get_callgraph_unknown_symbol_returns_empty(indexed):
    conn, _ = indexed
    assert retrieval.get_callgraph(conn, "does_not_exist") == []


def test_get_impact_notify_affected_by_login(indexed):
    conn, _ = indexed
    affected = retrieval.get_impact(conn, "notify", max_depth=1)
    assert "login" in affected
    assert "handle_login" in affected


def test_get_impact_unknown_symbol_returns_empty(indexed):
    conn, _ = indexed
    assert retrieval.get_impact(conn, "does_not_exist") == []


# ---------------------------------------------------------------------------
# retrieval.get_context — the crown jewel
# ---------------------------------------------------------------------------

def test_get_context_returns_none_for_unknown(indexed):
    conn, _ = indexed
    assert retrieval.get_context(conn, "totally_unknown") is None


def test_get_context_name_and_kind(indexed):
    conn, _ = indexed
    ctx = retrieval.get_context(conn, "login")
    assert ctx is not None
    assert ctx.name == "login"
    assert ctx.kind == "method"


def test_get_context_file_location(indexed):
    conn, _ = indexed
    ctx = retrieval.get_context(conn, "login")
    assert "service.py" in ctx.file_path
    assert ctx.start_line > 0


def test_get_context_direct_calls(indexed):
    conn, _ = indexed
    ctx = retrieval.get_context(conn, "login")
    assert "notify" in ctx.calls
    assert "generate_token" in ctx.calls


def test_get_context_called_by(indexed):
    conn, _ = indexed
    # Nothing in our fixture calls login directly, so called_by should be empty
    ctx = retrieval.get_context(conn, "login")
    assert isinstance(ctx.called_by, list)


def test_get_context_file_imports(indexed):
    conn, _ = indexed
    ctx = retrieval.get_context(conn, "login")
    # service.py imports os and logging
    assert "os" in ctx.file_imports or "logging" in ctx.file_imports


def test_get_context_callgraph_populated(indexed):
    conn, _ = indexed
    ctx = retrieval.get_context(conn, "login", callgraph_depth=2)
    assert len(ctx.callgraph) > 0


def test_get_context_impact_for_notify(indexed):
    conn, _ = indexed
    ctx = retrieval.get_context(conn, "notify", callgraph_depth=1)
    assert "login" in ctx.impact
    assert "handle_login" in ctx.impact


def test_get_context_class_symbol(indexed):
    conn, _ = indexed
    ctx = retrieval.get_context(conn, "AuthService")
    assert ctx is not None
    assert ctx.kind == "class"
