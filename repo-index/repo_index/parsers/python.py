"""Python AST parser — extracts symbols, imports, and call graph using Tree-sitter."""

import hashlib

from tree_sitter import Node
from tree_sitter_language_pack import get_language
from tree_sitter import Parser

from .base import BaseParser, ImportAliasRecord, ParseResult, RelationRecord, SymbolRecord


_LANG = get_language("python")


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


class PythonParser(BaseParser):
    @property
    def language(self) -> str:
        return "python"

    @property
    def extensions(self) -> set[str]:
        return {".py"}

    def parse(self, source: bytes, file_path: str, module: str = "") -> ParseResult:
        parser = Parser(_LANG)
        tree = parser.parse(source)
        result = ParseResult()
        self._walk(tree.root_node, source, file_path, result, parent_class=None, module=module)
        return result

    def _walk(
        self,
        node: Node,
        source: bytes,
        file_path: str,
        result: ParseResult,
        parent_class: str | None,
        module: str,
    ) -> None:
        if node.type == "function_definition":
            self._extract_function(node, source, file_path, result, parent_class, module)

        elif node.type == "class_definition":
            self._extract_class(node, source, file_path, result, module)

        elif node.type == "decorated_definition":
            inner = _find_child(node, "function_definition", "class_definition")
            if inner:
                self._walk(inner, source, file_path, result, parent_class, module)

        elif node.type in ("import_statement", "import_from_statement"):
            self._extract_import(node, result)

        else:
            for child in node.children:
                self._walk(child, source, file_path, result, parent_class, module)

    def _extract_function(
        self,
        node: Node,
        source: bytes,
        file_path: str,
        result: ParseResult,
        parent_class: str | None,
        module: str,
    ) -> None:
        name_node = _find_child(node, "identifier")
        if not name_node:
            return

        name = _text(name_node)
        start_line = node.start_point[0] + 1
        end_line = node.end_point[0] + 1
        kind = "method" if parent_class else "function"
        sym_hash = _symbol_hash(source, node.start_point[0], node.end_point[0])

        fqid = ""
        if module:
            fqid = f"{module}.{parent_class}.{name}" if parent_class else f"{module}.{name}"

        result.symbols.append(
            SymbolRecord(
                name=name, kind=kind, start_line=start_line, end_line=end_line,
                hash=sym_hash, fqid=fqid, module=module, owner=parent_class or "",
            )
        )

        if parent_class:
            result.relations.append(
                RelationRecord(from_symbol=name, relation="DEFINES", to_name=parent_class)
            )

        body = _find_child(node, "block")
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
        name_node = _find_child(node, "identifier")
        if not name_node:
            return

        name = _text(name_node)
        start_line = node.start_point[0] + 1
        end_line = node.end_point[0] + 1
        sym_hash = _symbol_hash(source, node.start_point[0], node.end_point[0])
        fqid = f"{module}.{name}" if module else ""

        result.symbols.append(
            SymbolRecord(
                name=name, kind="class", start_line=start_line, end_line=end_line,
                hash=sym_hash, fqid=fqid, module=module, owner="",
            )
        )

        bases = _find_child(node, "argument_list")
        if bases:
            for base in bases.children:
                if base.type == "identifier":
                    result.relations.append(
                        RelationRecord(from_symbol=name, relation="INHERITS", to_name=_text(base))
                    )

        body = _find_child(node, "block")
        if body:
            for child in body.children:
                self._walk(child, source, file_path, result, parent_class=name, module=module)

    def _extract_calls(self, body: Node, owner: str, result: ParseResult) -> None:
        for node in _iter_all(body):
            if node.type == "call":
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
        if node.type == "import_statement":
            for child in node.children:
                if child.type == "dotted_name":
                    mod = _text(child)
                    result.relations.append(
                        RelationRecord(from_symbol="<module>", relation="IMPORTS", to_name=mod)
                    )
                    result.import_aliases.append(
                        ImportAliasRecord(
                            alias=mod.split(".")[-1],
                            source_module=mod,
                            source_name="",
                        )
                    )
                elif child.type == "aliased_import":
                    name_node = child.child_by_field_name("name")
                    alias_node = child.child_by_field_name("alias")
                    if name_node:
                        mod = _text(name_node)
                        alias = _text(alias_node) if alias_node else mod.split(".")[-1]
                        result.relations.append(
                            RelationRecord(from_symbol="<module>", relation="IMPORTS", to_name=mod)
                        )
                        result.import_aliases.append(
                            ImportAliasRecord(alias=alias, source_module=mod, source_name="")
                        )

        elif node.type == "import_from_statement":
            module = ""
            saw_module = False
            for child in node.children:
                if child.type == "dotted_name":
                    if not saw_module:
                        module = _text(child)
                        saw_module = True
                    elif module:
                        name = _text(child)
                        result.import_aliases.append(
                            ImportAliasRecord(alias=name, source_module=module, source_name=name)
                        )
                elif child.type == "aliased_import" and module:
                    name_node = child.child_by_field_name("name")
                    alias_node = child.child_by_field_name("alias")
                    if name_node:
                        imported_name = _text(name_node)
                        alias = _text(alias_node) if alias_node else imported_name
                        result.import_aliases.append(
                            ImportAliasRecord(
                                alias=alias, source_module=module, source_name=imported_name
                            )
                        )
                elif child.type == "wildcard_import" and module:
                    result.import_aliases.append(
                        ImportAliasRecord(alias="*", source_module=module, source_name="*")
                    )

            if module:
                result.relations.append(
                    RelationRecord(from_symbol="<module>", relation="IMPORTS", to_name=module)
                )


def _iter_all(node: Node):
    yield node
    for child in node.children:
        yield from _iter_all(child)


def _resolve_callee(func_node: Node) -> tuple[str, str] | None:
    """Return (simple_name, call_expression) for a call target node."""
    if func_node.type == "identifier":
        name = _text(func_node)
        return (name, name)
    if func_node.type == "attribute":
        attr = func_node.child_by_field_name("attribute")
        obj = func_node.child_by_field_name("object")
        if attr:
            attr_name = _text(attr)
            if obj and obj.type == "identifier":
                return (attr_name, f"{_text(obj)}.{attr_name}")
            return (attr_name, attr_name)
    return None
