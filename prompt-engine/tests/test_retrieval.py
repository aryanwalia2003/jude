"""Tests for prompt_engine.retrieval — the repo-index bridge."""

import pytest
from pathlib import Path

from prompt_engine.retrieval import (
    ContextBundle,
    SymbolContext,
    _format,
    _format_symbol,
    _keywords,
    _trim,
    retrieve,
)
from prompt_engine.task import ContextBudget, RetrievalPlan


# ---------------------------------------------------------------------------
# Source fixtures
# ---------------------------------------------------------------------------

_AUTH = """\
import os

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
def indexed_db(tmp_path):
    """Populated repo-index DB returned as a Path."""
    from repo_index import db as ri_db, indexer

    db_path = tmp_path / "test.db"
    conn = ri_db.open_db(db_path)
    root = tmp_path / "repo"
    root.mkdir()
    (root / "auth.py").write_text(_AUTH)
    (root / "handler.py").write_text(_HANDLER)
    indexer.build_index(conn, root)
    conn.close()
    return db_path


@pytest.fixture
def empty_db(tmp_path):
    """DB with schema applied but no symbols."""
    from repo_index import db as ri_db

    db_path = tmp_path / "empty.db"
    ri_db.open_db(db_path).close()
    return db_path


@pytest.fixture
def budget():
    return ContextBudget()


@pytest.fixture
def plan():
    return RetrievalPlan(query="auth login", git_history=False)


# ---------------------------------------------------------------------------
# _keywords
# ---------------------------------------------------------------------------

def test_keywords_strips_stop_words():
    assert "the" not in _keywords("fix the bug")


def test_keywords_returns_significant_words():
    result = _keywords("auth login")
    assert "auth" in result
    assert "login" in result


def test_keywords_empty_string_returns_empty():
    assert _keywords("") == []


def test_keywords_excludes_short_words():
    result = _keywords("a is it")
    assert result == []


def test_keywords_preserves_identifiers():
    result = _keywords("generate_token AuthService")
    assert "generate_token" in result
    assert "AuthService" in result


def test_keywords_dedoes_not_include_stop_word_variants():
    result = _keywords("for the in to with")
    assert result == []


# ---------------------------------------------------------------------------
# retrieve — no index / empty index
# ---------------------------------------------------------------------------

def test_retrieve_missing_db_returns_empty_bundle(tmp_path, budget, plan):
    result = retrieve(plan, budget, db_path=tmp_path / "nonexistent.db")
    assert result.is_empty


def test_retrieve_missing_db_has_note(tmp_path, budget, plan):
    result = retrieve(plan, budget, db_path=tmp_path / "nonexistent.db")
    assert any("no index" in n.lower() or "repo-index build" in n for n in result.retrieval_notes)


def test_retrieve_empty_index_returns_empty_bundle(empty_db, budget, plan):
    result = retrieve(plan, budget, db_path=empty_db)
    assert result.is_empty


def test_retrieve_empty_index_has_note(empty_db, budget, plan):
    result = retrieve(plan, budget, db_path=empty_db)
    assert any("empty" in n.lower() or "build" in n.lower() for n in result.retrieval_notes)


def test_retrieve_returns_context_bundle(indexed_db, budget, plan):
    result = retrieve(plan, budget, db_path=indexed_db)
    assert isinstance(result, ContextBundle)


# ---------------------------------------------------------------------------
# retrieve — symbol hydration
# ---------------------------------------------------------------------------

def test_retrieve_finds_matching_symbols(indexed_db, budget, plan):
    result = retrieve(plan, budget, db_path=indexed_db)
    assert result.symbol_count > 0


def test_retrieve_symbol_has_name(indexed_db, budget, plan):
    result = retrieve(plan, budget, db_path=indexed_db)
    assert all(s.name for s in result.symbols)


def test_retrieve_symbol_has_file_path(indexed_db, budget, plan):
    result = retrieve(plan, budget, db_path=indexed_db)
    assert all(s.file_path for s in result.symbols)


def test_retrieve_symbol_has_line_numbers(indexed_db, budget, plan):
    result = retrieve(plan, budget, db_path=indexed_db)
    assert all(s.start_line >= 0 for s in result.symbols)


def test_retrieve_login_symbol_has_calls(indexed_db, budget):
    plan = RetrievalPlan(query="login", git_history=False)
    result = retrieve(plan, budget, db_path=indexed_db)
    login = next((s for s in result.symbols if s.name == "login"), None)
    assert login is not None
    assert "notify" in login.calls or "generate_token" in login.calls


def test_retrieve_login_symbol_has_callgraph(indexed_db, budget):
    plan = RetrievalPlan(query="login", git_history=False)
    result = retrieve(plan, budget, db_path=indexed_db)
    login = next((s for s in result.symbols if s.name == "login"), None)
    assert login is not None
    assert len(login.callgraph) > 0


def test_retrieve_notify_symbol_has_callers(indexed_db, budget):
    plan = RetrievalPlan(query="notify", git_history=False)
    result = retrieve(plan, budget, db_path=indexed_db)
    notify = next((s for s in result.symbols if s.name == "notify"), None)
    assert notify is not None
    assert "login" in notify.called_by or "handle_login" in notify.called_by


def test_retrieve_symbol_imports_populated(indexed_db, budget):
    plan = RetrievalPlan(query="login", git_history=False)
    result = retrieve(plan, budget, db_path=indexed_db)
    login = next((s for s in result.symbols if s.name == "login"), None)
    assert login is not None
    assert len(login.imports) > 0


# ---------------------------------------------------------------------------
# retrieve — keyword fallback
# ---------------------------------------------------------------------------

def test_retrieve_fallback_finds_symbols_via_keyword(indexed_db, budget):
    # "auth service login flow" won't match as a phrase — individual keywords should hit
    plan = RetrievalPlan(query="auth service login flow", git_history=False)
    result = retrieve(plan, budget, db_path=indexed_db)
    assert result.symbol_count > 0


def test_retrieve_fallback_adds_note(indexed_db, budget):
    plan = RetrievalPlan(query="xyzzy auth flow", git_history=False)
    result = retrieve(plan, budget, db_path=indexed_db)
    # "auth" keyword should match and a fallback note should be present
    assert any("matched on" in n.lower() or "no results" in n.lower() for n in result.retrieval_notes)


def test_retrieve_no_match_adds_note(indexed_db, budget):
    plan = RetrievalPlan(query="xyzzy_nonexistent_symbol", git_history=False)
    result = retrieve(plan, budget, db_path=indexed_db)
    assert any("no symbols found" in n.lower() for n in result.retrieval_notes)


# ---------------------------------------------------------------------------
# retrieve — explicit symbol_targets
# ---------------------------------------------------------------------------

def test_retrieve_explicit_symbol_target_found(indexed_db, budget):
    plan = RetrievalPlan(query="", symbol_targets=["generate_token"], git_history=False)
    result = retrieve(plan, budget, db_path=indexed_db)
    assert any(s.name == "generate_token" for s in result.symbols)


def test_retrieve_missing_symbol_target_adds_note(indexed_db, budget):
    plan = RetrievalPlan(query="", symbol_targets=["does_not_exist"], git_history=False)
    result = retrieve(plan, budget, db_path=indexed_db)
    assert any("not found" in n for n in result.retrieval_notes)


# ---------------------------------------------------------------------------
# retrieve — git_history flag
# ---------------------------------------------------------------------------

def test_retrieve_no_git_history_has_empty_diff(indexed_db, budget):
    plan = RetrievalPlan(query="login", git_history=False)
    result = retrieve(plan, budget, db_path=indexed_db)
    assert result.git_diff == ""


def test_retrieve_git_history_in_non_git_dir(indexed_db, budget, tmp_path):
    # tmp_path is not a git repo — should fail silently and add a note
    plan = RetrievalPlan(query="login", git_history=True)
    result = retrieve(plan, budget, db_path=indexed_db, repo_root=tmp_path)
    # Should not raise; diff may be empty or have a note about git
    assert isinstance(result.git_diff, str)


# ---------------------------------------------------------------------------
# retrieve — token budget enforcement
# ---------------------------------------------------------------------------

def test_retrieve_small_budget_trims_text(indexed_db):
    tiny = ContextBudget(max_tokens=100)
    plan = RetrievalPlan(query="login", git_history=False)
    result = retrieve(plan, tiny, db_path=indexed_db)
    assert result.token_estimate <= 100


def test_retrieve_trim_adds_note(indexed_db):
    tiny = ContextBudget(max_tokens=100)
    plan = RetrievalPlan(query="login", git_history=False)
    result = retrieve(plan, tiny, db_path=indexed_db)
    if result.token_estimate == 100:
        assert any("trimmed" in n.lower() for n in result.retrieval_notes)


def test_retrieve_raw_text_within_char_budget(indexed_db):
    tiny = ContextBudget(max_tokens=200)
    plan = RetrievalPlan(query="login", git_history=False)
    result = retrieve(plan, tiny, db_path=indexed_db)
    assert len(result.raw_text) <= 200 * 4 + 100  # chars, with small margin for trim marker


# ---------------------------------------------------------------------------
# retrieve — retrieval notes always present
# ---------------------------------------------------------------------------

def test_retrieve_notes_always_populated(indexed_db, budget, plan):
    result = retrieve(plan, budget, db_path=indexed_db)
    assert len(result.retrieval_notes) > 0


def test_retrieve_notes_include_index_stats(indexed_db, budget, plan):
    result = retrieve(plan, budget, db_path=indexed_db)
    assert any("symbol" in n.lower() for n in result.retrieval_notes)


# ---------------------------------------------------------------------------
# ContextBundle properties
# ---------------------------------------------------------------------------

def test_bundle_is_empty_true_when_no_content():
    b = ContextBundle(symbols=[], git_diff="", raw_text="", token_estimate=0, retrieval_notes=[])
    assert b.is_empty


def test_bundle_is_empty_false_when_symbols_present():
    sym = SymbolContext(name="foo", kind="function", file_path="a.py", start_line=1, end_line=5)
    b = ContextBundle(symbols=[sym], git_diff="", raw_text="x", token_estimate=1, retrieval_notes=[])
    assert not b.is_empty


def test_bundle_is_empty_false_when_diff_present():
    b = ContextBundle(symbols=[], git_diff="some diff", raw_text="x", token_estimate=1, retrieval_notes=[])
    assert not b.is_empty


def test_bundle_symbol_count_matches_list():
    syms = [
        SymbolContext(name="a", kind="function", file_path="f.py", start_line=1, end_line=2),
        SymbolContext(name="b", kind="class", file_path="f.py", start_line=5, end_line=10),
    ]
    b = ContextBundle(symbols=syms, git_diff="", raw_text="", token_estimate=0, retrieval_notes=[])
    assert b.symbol_count == 2


def test_bundle_symbol_count_empty():
    b = ContextBundle(symbols=[], git_diff="", raw_text="", token_estimate=0, retrieval_notes=[])
    assert b.symbol_count == 0


# ---------------------------------------------------------------------------
# _format_symbol
# ---------------------------------------------------------------------------

def _make_sym(**kwargs) -> SymbolContext:
    defaults = dict(name="foo", kind="function", file_path="pkg/a.py", start_line=10, end_line=20)
    defaults.update(kwargs)
    return SymbolContext(**defaults)


def test_format_symbol_contains_name():
    assert "foo" in _format_symbol(_make_sym())


def test_format_symbol_contains_kind():
    assert "function" in _format_symbol(_make_sym())


def test_format_symbol_contains_file_path():
    assert "pkg/a.py" in _format_symbol(_make_sym())


def test_format_symbol_contains_line_range():
    text = _format_symbol(_make_sym(start_line=10, end_line=20))
    assert "10" in text and "20" in text


def test_format_symbol_shows_calls():
    text = _format_symbol(_make_sym(calls=["bar", "baz"]))
    assert "bar" in text
    assert "baz" in text


def test_format_symbol_shows_callers():
    text = _format_symbol(_make_sym(called_by=["handler"]))
    assert "handler" in text


def test_format_symbol_shows_callgraph_hops():
    text = _format_symbol(_make_sym(callgraph=["bar", "baz"]))
    assert "bar" in text


def test_format_symbol_empty_calls_omits_calls_line():
    text = _format_symbol(_make_sym(calls=[]))
    assert "calls:" not in text


def test_format_symbol_empty_callers_omits_callers_line():
    text = _format_symbol(_make_sym(called_by=[]))
    assert "called_by:" not in text


def test_format_symbol_truncates_long_calls_list():
    text = _format_symbol(_make_sym(calls=[f"fn{i}" for i in range(20)]))
    assert "+12 more" in text or "more" in text


# ---------------------------------------------------------------------------
# _format
# ---------------------------------------------------------------------------

def test_format_contains_query():
    plan = RetrievalPlan(query="auth login", git_history=False)
    text = _format([], "", plan)
    assert "auth login" in text


def test_format_empty_symbols_and_no_diff_has_placeholder():
    plan = RetrievalPlan(query="foo", git_history=False)
    text = _format([], "", plan)
    assert "No symbols found" in text or "no symbols" in text.lower()


def test_format_with_symbols_shows_count():
    syms = [_make_sym(name="login"), _make_sym(name="logout")]
    plan = RetrievalPlan(query="auth", git_history=False)
    text = _format(syms, "", plan)
    assert "2" in text


def test_format_includes_git_diff_when_present():
    plan = RetrievalPlan(query="auth", git_history=False)
    text = _format([], "recent changes: auth.py", plan)
    assert "recent changes" in text.lower() or "auth.py" in text


# ---------------------------------------------------------------------------
# _trim
# ---------------------------------------------------------------------------

def test_trim_short_text_unchanged():
    text = "hello world"
    assert _trim(text, 1000) == text


def test_trim_long_text_is_truncated():
    text = "x" * 10000
    result = _trim(text, 100)
    assert len(result) < len(text)


def test_trim_result_fits_char_budget():
    text = "a" * 10000
    result = _trim(text, 100)
    # token cap * 4 chars + small trim marker
    assert len(result) < 600


def test_trim_appends_marker():
    text = "line\n" * 500
    result = _trim(text, 50)
    assert "trimmed" in result.lower() or "..." in result
