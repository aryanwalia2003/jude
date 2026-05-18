"""Tests for the Python Tree-sitter parser."""

import pytest
from repo_index.parsers.python import PythonParser


@pytest.fixture
def parser():
    return PythonParser()


def parse(parser, source: str):
    return parser.parse(source.encode(), "test.py")


def symbol_names(result):
    return [s.name for s in result.symbols]


def relations_of(result, relation):
    return [(r.from_symbol, r.to_name) for r in result.relations if r.relation == relation]


def test_extracts_top_level_function(parser):
    result = parse(parser, "def foo(x): return x")
    assert "foo" in symbol_names(result)
    assert result.symbols[0].kind == "function"


def test_extracts_class(parser):
    result = parse(parser, "class MyService:\n    pass")
    assert "MyService" in symbol_names(result)
    assert next(s for s in result.symbols if s.name == "MyService").kind == "class"


def test_extracts_method_inside_class(parser):
    result = parse(parser, "class Foo:\n    def bar(self): pass")
    kinds = {s.name: s.kind for s in result.symbols}
    assert kinds.get("bar") == "method"


def test_method_defines_relation(parser):
    result = parse(parser, "class Foo:\n    def bar(self): pass")
    defines = relations_of(result, "DEFINES")
    assert ("bar", "Foo") in defines


def test_class_inherits_relation(parser):
    result = parse(parser, "class Child(Base):\n    pass")
    inherits = relations_of(result, "INHERITS")
    assert ("Child", "Base") in inherits


def test_import_statement(parser):
    result = parse(parser, "import os\nimport sys")
    imports = [to for (_, to) in relations_of(result, "IMPORTS")]
    assert "os" in imports
    assert "sys" in imports


def test_import_from_statement(parser):
    result = parse(parser, "from pathlib import Path")
    imports = [to for (_, to) in relations_of(result, "IMPORTS")]
    assert "pathlib" in imports


def test_call_extraction(parser):
    result = parse(parser, "def foo():\n    bar()\n    baz()")
    calls = relations_of(result, "CALLS")
    callees = [to for (_, to) in calls]
    assert "bar" in callees
    assert "baz" in callees


def test_function_line_numbers(parser):
    result = parse(parser, "x = 1\n\ndef foo():\n    pass\n")
    foo = next(s for s in result.symbols if s.name == "foo")
    assert foo.start_line == 3
    assert foo.end_line == 4


def test_decorated_function(parser):
    result = parse(parser, "@property\ndef value(self): return 1")
    assert "value" in symbol_names(result)


def test_nested_calls_inside_method(parser):
    src = "class A:\n    def run(self):\n        do_something()\n        helper()\n"
    result = parse(parser, src)
    calls = relations_of(result, "CALLS")
    callees = [to for (_, to) in calls]
    assert "do_something" in callees
    assert "helper" in callees


def test_empty_file(parser):
    result = parse(parser, "")
    assert result.symbols == []
    assert result.relations == []


def test_symbol_hash_is_populated(parser):
    result = parse(parser, "def foo():\n    pass\n")
    foo = next(s for s in result.symbols if s.name == "foo")
    assert foo.hash != ""
