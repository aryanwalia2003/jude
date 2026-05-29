"""Tests for the Go Tree-sitter parser."""

import pytest
from repo_index.parsers.go import GoParser


@pytest.fixture
def parser():
    return GoParser()


def parse(parser, source: str):
    return parser.parse(source.encode(), "test.go")


def symbol_names(result):
    return [s.name for s in result.symbols]


def relations_of(result, relation):
    return [(r.from_symbol, r.to_name) for r in result.relations if r.relation == relation]


def test_extracts_function(parser):
    result = parse(parser, "func HelloWorld() string {\n    return \"hello\"\n}")
    assert "HelloWorld" in symbol_names(result)
    assert next(s for s in result.symbols if s.name == "HelloWorld").kind == "function"


def test_extracts_type_struct(parser):
    result = parse(parser, "type User struct {\n    name string\n}")
    assert "User" in symbol_names(result)
    assert next(s for s in result.symbols if s.name == "User").kind == "class"


def test_extracts_method(parser):
    result = parse(
        parser,
        "type Server struct {}\n\nfunc (s *Server) Start() {\n    return\n}",
    )
    kinds = {s.name: s.kind for s in result.symbols}
    assert kinds.get("Start") == "method"


def test_method_owner(parser):
    result = parse(
        parser,
        "type Server struct {}\n\nfunc (s *Server) Start() {\n    return\n}",
    )
    start_method = next(s for s in result.symbols if s.name == "Start")
    assert start_method.owner == "Server"


def test_import_statement(parser):
    result = parse(parser, 'import "fmt"\nimport "os"')
    imports = [to for (_, to) in relations_of(result, "IMPORTS")]
    assert "fmt" in imports
    assert "os" in imports


def test_import_group(parser):
    result = parse(
        parser,
        'import (\n    "fmt"\n    "github.com/gin-gonic/gin"\n)',
    )
    imports = [to for (_, to) in relations_of(result, "IMPORTS")]
    assert "fmt" in imports
    assert "github.com/gin-gonic/gin" in imports


def test_call_extraction(parser):
    result = parse(
        parser,
        "func main() {\n    fmt.Println(\"hello\")\n    os.Exit(0)\n}",
    )
    calls = relations_of(result, "CALLS")
    assert len(calls) > 0


def test_function_line_numbers(parser):
    result = parse(parser, "package main\n\nfunc Foo() {\n    return\n}\n")
    foo = next(s for s in result.symbols if s.name == "Foo")
    assert foo.start_line >= 3
    assert foo.end_line > foo.start_line
