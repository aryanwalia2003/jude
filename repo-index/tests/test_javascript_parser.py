"""Tests for the JavaScript/TypeScript Tree-sitter parsers."""

import pytest
from repo_index.parsers.javascript import JavaScriptParser, TypeScriptParser


@pytest.fixture
def js_parser():
    return JavaScriptParser()


@pytest.fixture
def ts_parser():
    return TypeScriptParser()


def parse_js(parser, source: str):
    return parser.parse(source.encode(), "test.js")


def parse_ts(parser, source: str):
    return parser.parse(source.encode(), "test.ts")


def symbol_names(result):
    return [s.name for s in result.symbols]


def relations_of(result, relation):
    return [(r.from_symbol, r.to_name) for r in result.relations if r.relation == relation]


class TestJavaScript:
    def test_extracts_function(self, js_parser):
        result = parse_js(js_parser, "function hello() { return 'hi'; }")
        assert "hello" in symbol_names(result)
        assert next(s for s in result.symbols if s.name == "hello").kind == "function"

    def test_extracts_class(self, js_parser):
        result = parse_js(
            js_parser,
            "class Button extends React.Component {\n    render() { return null; }\n}",
        )
        assert "Button" in symbol_names(result)
        assert next(s for s in result.symbols if s.name == "Button").kind == "class"

    def test_extracts_method(self, js_parser):
        result = parse_js(
            js_parser,
            "class Counter {\n    increment() { this.count++; }\n}",
        )
        kinds = {s.name: s.kind for s in result.symbols}
        assert kinds.get("increment") == "method"

    def test_method_owner(self, js_parser):
        result = parse_js(
            js_parser,
            "class Button {\n    click() { }\n}",
        )
        click_method = next(s for s in result.symbols if s.name == "click")
        assert click_method.owner == "Button"

    def test_import_default(self, js_parser):
        result = parse_js(js_parser, "import React from 'react';")
        imports = [to for (_, to) in relations_of(result, "IMPORTS")]
        assert "react" in imports

    def test_import_named(self, js_parser):
        result = parse_js(js_parser, "import { Component } from 'react';")
        imports = [to for (_, to) in relations_of(result, "IMPORTS")]
        assert "react" in imports

    def test_call_extraction(self, js_parser):
        result = parse_js(
            js_parser,
            "function main() {\n    console.log('hi');\n    helper();\n}",
        )
        calls = relations_of(result, "CALLS")
        assert len(calls) > 0

    def test_function_line_numbers(self, js_parser):
        result = parse_js(
            js_parser,
            "const x = 1;\n\nfunction foo() {\n    return 42;\n}\n",
        )
        foo = next(s for s in result.symbols if s.name == "foo")
        assert foo.start_line >= 3
        assert foo.end_line > foo.start_line


class TestTypeScript:
    def test_extracts_function(self, ts_parser):
        result = parse_ts(ts_parser, "function hello(): string { return 'hi'; }")
        assert "hello" in symbol_names(result)
        assert next(s for s in result.symbols if s.name == "hello").kind == "function"

    def test_extracts_interface(self, ts_parser):
        result = parse_ts(
            ts_parser,
            "interface IButton {\n    onClick(): void;\n}",
        )
        assert "IButton" in symbol_names(result)
        assert next(s for s in result.symbols if s.name == "IButton").kind == "class"

    def test_extracts_class(self, ts_parser):
        result = parse_ts(
            ts_parser,
            "class Button implements IButton {\n    onClick() { }\n}",
        )
        assert "Button" in symbol_names(result)

    def test_extracts_method(self, ts_parser):
        result = parse_ts(
            ts_parser,
            "class UserService {\n    getUser(id: number): User { return null; }\n}",
        )
        kinds = {s.name: s.kind for s in result.symbols}
        assert kinds.get("getUser") == "method"

    def test_import_named(self, ts_parser):
        result = parse_ts(ts_parser, "import { Component } from 'react';")
        imports = [to for (_, to) in relations_of(result, "IMPORTS")]
        assert "react" in imports

    def test_type_annotation(self, ts_parser):
        result = parse_ts(
            ts_parser,
            "type Props = { label: string; };\nfunction Button(props: Props) { }",
        )
        assert "Button" in symbol_names(result)
