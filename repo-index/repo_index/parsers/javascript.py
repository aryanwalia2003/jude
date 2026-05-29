"""JavaScript/TypeScript AST parser — extracts symbols, imports, and call graph using Tree-sitter."""

import hashlib

from tree_sitter import Node
from tree_sitter_language_pack import get_language
from tree_sitter import Parser

from .base import BaseParser, ImportAliasRecord, ParseResult, RelationRecord, SymbolRecord


_LANG_JS = get_language("javascript")
_LANG_TS = get_language("typescript")


def _text(node: Node) -> str:
    return node.text.decode("utf-8", errors="replace") if node.text else ""


def _find_child(node: Node, *types: str) -> Node | None:
    for child in node.children:
        if child.type in types:
            return child
    return None


def _symbol_hash(source: bytes, start_line: int, end_line: int) -> str:
    chunk = b"\n".join(source.split(b"\n")[start_line:end_line])
    return hashlib.sha1(chunk).hexdigest()[:16]


class JavaScriptParser(BaseParser):
    @property
    def language(self) -> str:
        return "javascript"

    @property
    def extensions(self) -> set[str]:
        return {".js", ".jsx", ".mjs", ".cjs"}

    def parse(self, source: bytes, file_path: str, module: str = "") -> ParseResult:
        parser = Parser(_LANG_JS)
        tree = parser.parse(source)
        result = ParseResult()
        self._walk(tree.root_node, source, file_path, result, module=module, parent_class=None)
        return result

    def _walk(
        self,
        node: Node,
        source: bytes,
        file_path: str,
        result: ParseResult,
        module: str,
        parent_class: str | None,
    ) -> None:
        if node.type == "function_declaration":
            self._extract_function(node, source, file_path, result, module)

        elif node.type == "class_declaration":
            self._extract_class(node, source, file_path, result, module)

        elif node.type == "function" and parent_class:
            self._extract_method(node, source, file_path, result, module, parent_class)

        elif node.type == "method_definition":
            self._extract_method(node, source, file_path, result, module, parent_class)

        elif node.type == "arrow_function" and parent_class:
            self._extract_arrow_function(node, source, file_path, result, module, parent_class)

        elif node.type in ("import_statement", "import"):
            self._extract_import(node, result)

        elif node.type in ("export_statement", "export"):
            self._extract_export(node, source, file_path, result, module)

        else:
            for child in node.children:
                self._walk(child, source, file_path, result, module, parent_class)

    def _extract_function(
        self,
        node: Node,
        source: bytes,
        file_path: str,
        result: ParseResult,
        module: str,
    ) -> None:
        name_node = node.child_by_field_name("name")
        if not name_node:
            return

        name = _text(name_node)
        start_line = node.start_point[0] + 1
        end_line = node.end_point[0] + 1
        sym_hash = _symbol_hash(source, node.start_point[0], node.end_point[0])
        fqid = f"{module}.{name}" if module else ""

        result.symbols.append(
            SymbolRecord(
                name=name,
                kind="function",
                start_line=start_line,
                end_line=end_line,
                hash=sym_hash,
                fqid=fqid,
                module=module,
                owner="",
            )
        )

        body = node.child_by_field_name("body")
        if body:
            self._extract_calls(body, name, result)

    def _extract_class(
        self,
        node: Node,
        source: bytes,
        file_path: str,
        result: ParseResult,
        module: str,
    ) -> None:
        name_node = node.child_by_field_name("name")
        if not name_node:
            return

        name = _text(name_node)
        start_line = node.start_point[0] + 1
        end_line = node.end_point[0] + 1
        sym_hash = _symbol_hash(source, node.start_point[0], node.end_point[0])
        fqid = f"{module}.{name}" if module else ""

        result.symbols.append(
            SymbolRecord(
                name=name,
                kind="class",
                start_line=start_line,
                end_line=end_line,
                hash=sym_hash,
                fqid=fqid,
                module=module,
                owner="",
            )
        )

        body = node.child_by_field_name("body")
        if body:
            for child in body.children:
                self._walk(child, source, file_path, result, module, parent_class=name)

    def _extract_method(
        self,
        node: Node,
        source: bytes,
        file_path: str,
        result: ParseResult,
        module: str,
        parent_class: str,
    ) -> None:
        name_node = node.child_by_field_name("name")
        if not name_node:
            name_node = node.child_by_field_name("key")
        if not name_node:
            return

        name = _text(name_node).strip('"\'')
        start_line = node.start_point[0] + 1
        end_line = node.end_point[0] + 1
        sym_hash = _symbol_hash(source, node.start_point[0], node.end_point[0])
        fqid = f"{module}.{parent_class}.{name}" if module else ""

        result.symbols.append(
            SymbolRecord(
                name=name,
                kind="method",
                start_line=start_line,
                end_line=end_line,
                hash=sym_hash,
                fqid=fqid,
                module=module,
                owner=parent_class,
            )
        )

        body = node.child_by_field_name("body")
        if body:
            self._extract_calls(body, name, result)

    def _extract_arrow_function(
        self,
        node: Node,
        source: bytes,
        file_path: str,
        result: ParseResult,
        module: str,
        parent_class: str,
    ) -> None:
        start_line = node.start_point[0] + 1
        end_line = node.end_point[0] + 1
        sym_hash = _symbol_hash(source, node.start_point[0], node.end_point[0])

        body = node.child_by_field_name("body")
        if body:
            self._extract_calls(body, f"{parent_class}.<arrow>", result)

    def _extract_calls(self, body: Node, owner: str, result: ParseResult) -> None:
        for node in _iter_all(body):
            if node.type == "call_expression":
                func_node = node.child_by_field_name("function")
                if not func_node:
                    continue
                resolved = _resolve_callee(func_node)
                if resolved:
                    simple_name, call_expr = resolved
                    result.relations.append(
                        RelationRecord(
                            from_symbol=owner,
                            relation="CALLS",
                            to_name=simple_name,
                            call_expression=call_expr,
                        )
                    )

    def _extract_import(self, node: Node, result: ParseResult) -> None:
        source_node = node.child_by_field_name("source")
        if not source_node:
            return

        source = _text(source_node).strip('"\'')

        for child in node.children:
            if child.type == "import_specifier":
                name_node = child.child_by_field_name("name")
                alias_node = child.child_by_field_name("alias")
                if name_node:
                    name = _text(name_node)
                    alias = _text(alias_node) if alias_node else name
                    result.import_aliases.append(
                        ImportAliasRecord(alias=alias, source_module=source, source_name=name)
                    )

            elif child.type == "namespace_import":
                name_node = child.child_by_field_name("name")
                if name_node:
                    alias = _text(name_node)
                    result.import_aliases.append(
                        ImportAliasRecord(alias=alias, source_module=source, source_name="*")
                    )

        result.relations.append(
            RelationRecord(from_symbol="<module>", relation="IMPORTS", to_name=source)
        )

    def _extract_export(
        self,
        node: Node,
        source: bytes,
        file_path: str,
        result: ParseResult,
        module: str,
    ) -> None:
        for child in node.children:
            if child.type == "function_declaration":
                self._extract_function(child, source, file_path, result, module)
            elif child.type == "class_declaration":
                self._extract_class(child, source, file_path, result, module)


class TypeScriptParser(JavaScriptParser):
    @property
    def language(self) -> str:
        return "typescript"

    @property
    def extensions(self) -> set[str]:
        return {".ts", ".tsx"}

    def parse(self, source: bytes, file_path: str, module: str = "") -> ParseResult:
        parser = Parser(_LANG_TS)
        tree = parser.parse(source)
        result = ParseResult()
        self._walk(tree.root_node, source, file_path, result, module=module, parent_class=None)
        return result

    def _walk(
        self,
        node: Node,
        source: bytes,
        file_path: str,
        result: ParseResult,
        module: str,
        parent_class: str | None,
    ) -> None:
        if node.type == "function_declaration":
            self._extract_function(node, source, file_path, result, module)

        elif node.type == "class_declaration":
            self._extract_class(node, source, file_path, result, module)

        elif node.type == "interface_declaration":
            self._extract_interface(node, source, file_path, result, module)

        elif node.type == "method_definition":
            self._extract_method(node, source, file_path, result, module, parent_class)

        elif node.type in ("import_statement", "import"):
            self._extract_import(node, result)

        elif node.type in ("export_statement", "export"):
            self._extract_export(node, source, file_path, result, module)

        else:
            for child in node.children:
                self._walk(child, source, file_path, result, module, parent_class)

    def _extract_interface(
        self,
        node: Node,
        source: bytes,
        file_path: str,
        result: ParseResult,
        module: str,
    ) -> None:
        name_node = node.child_by_field_name("name")
        if not name_node:
            return

        name = _text(name_node)
        start_line = node.start_point[0] + 1
        end_line = node.end_point[0] + 1
        sym_hash = _symbol_hash(source, node.start_point[0], node.end_point[0])
        fqid = f"{module}.{name}" if module else ""

        result.symbols.append(
            SymbolRecord(
                name=name,
                kind="class",
                start_line=start_line,
                end_line=end_line,
                hash=sym_hash,
                fqid=fqid,
                module=module,
                owner="",
            )
        )

        body = node.child_by_field_name("body")
        if body:
            for child in body.children:
                self._walk(child, source, file_path, result, module, parent_class=name)


def _iter_all(node: Node):
    yield node
    for child in node.children:
        yield from _iter_all(child)


def _resolve_callee(func_node: Node) -> tuple[str, str] | None:
    """Return (simple_name, call_expression) for a call target node."""
    if func_node.type == "identifier":
        name = _text(func_node)
        return (name, name)

    if func_node.type == "member_expression":
        property_node = func_node.child_by_field_name("property")
        object_node = func_node.child_by_field_name("object")
        if property_node:
            prop_name = _text(property_node)
            if object_node and object_node.type == "identifier":
                return (prop_name, f"{_text(object_node)}.{prop_name}")
            return (prop_name, prop_name)

    return None
