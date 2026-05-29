"""Go AST parser — extracts symbols, imports, and call graph using Tree-sitter."""

import hashlib

from tree_sitter import Node
from tree_sitter_language_pack import get_language
from tree_sitter import Parser

from .base import BaseParser, ImportAliasRecord, ParseResult, RelationRecord, SymbolRecord


_LANG = get_language("go")


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


class GoParser(BaseParser):
    @property
    def language(self) -> str:
        return "go"

    @property
    def extensions(self) -> set[str]:
        return {".go"}

    def parse(self, source: bytes, file_path: str, module: str = "") -> ParseResult:
        parser = Parser(_LANG)
        tree = parser.parse(source)
        result = ParseResult()
        self._walk(tree.root_node, source, file_path, result, module=module)
        return result

    def _walk(
        self,
        node: Node,
        source: bytes,
        file_path: str,
        result: ParseResult,
        module: str,
    ) -> None:
        if node.type == "function_declaration":
            self._extract_function(node, source, file_path, result, module)

        elif node.type == "method_declaration":
            self._extract_method(node, source, file_path, result, module)

        elif node.type == "type_declaration":
            self._extract_type(node, source, file_path, result, module)

        elif node.type == "import_declaration":
            self._extract_import(node, result)

        else:
            for child in node.children:
                self._walk(child, source, file_path, result, module)

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
        kind = "function"
        sym_hash = _symbol_hash(source, node.start_point[0], node.end_point[0])
        fqid = f"{module}.{name}" if module else ""

        result.symbols.append(
            SymbolRecord(
                name=name,
                kind=kind,
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

    def _extract_method(
        self,
        node: Node,
        source: bytes,
        file_path: str,
        result: ParseResult,
        module: str,
    ) -> None:
        name_node = _find_child(node, "field_identifier")
        if not name_node:
            return

        name = _text(name_node)
        owner = ""

        # The receiver is in the first parameter_list
        for child in node.children:
            if child.type == "parameter_list":
                for param_decl in child.children:
                    if param_decl.type == "parameter_declaration":
                        receiver_type = self._extract_receiver_type(param_decl)
                        if receiver_type:
                            owner = receiver_type
                        break
                break

        start_line = node.start_point[0] + 1
        end_line = node.end_point[0] + 1
        sym_hash = _symbol_hash(source, node.start_point[0], node.end_point[0])
        fqid = f"{module}.{owner}.{name}" if module and owner else ""

        result.symbols.append(
            SymbolRecord(
                name=name,
                kind="method",
                start_line=start_line,
                end_line=end_line,
                hash=sym_hash,
                fqid=fqid,
                module=module,
                owner=owner,
            )
        )

        body = _find_child(node, "block")
        if body:
            self._extract_calls(body, name, result)

    def _extract_receiver_type(self, param_decl: Node) -> str | None:
        for child in param_decl.children:
            if child.type == "type_identifier":
                return _text(child)
            if child.type == "pointer_type":
                for subchild in child.children:
                    if subchild.type == "type_identifier":
                        return _text(subchild)
        return None

    def _extract_type(
        self,
        node: Node,
        source: bytes,
        file_path: str,
        result: ParseResult,
        module: str,
    ) -> None:
        spec = _find_child(node, "type_spec")
        if not spec:
            return

        name_node = spec.child_by_field_name("name")
        if not name_node:
            return

        name = _text(name_node)
        start_line = node.start_point[0] + 1
        end_line = node.end_point[0] + 1
        sym_hash = _symbol_hash(source, node.start_point[0], node.end_point[0])
        fqid = f"{module}.{name}" if module else ""

        kind = "class"
        result.symbols.append(
            SymbolRecord(
                name=name,
                kind=kind,
                start_line=start_line,
                end_line=end_line,
                hash=sym_hash,
                fqid=fqid,
                module=module,
                owner="",
            )
        )

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
        # First, try to find import_spec_list (for grouped imports)
        spec_list = _find_child(node, "import_spec_list")
        if spec_list:
            for child in spec_list.children:
                if child.type == "import_spec":
                    self._process_import_spec(child, result)
        else:
            # Handle direct import_spec children
            for child in node.children:
                if child.type == "import_spec":
                    self._process_import_spec(child, result)

    def _process_import_spec(self, spec: Node, result: ParseResult) -> None:
        path_node = None

        for child in spec.children:
            if child.type == "interpreted_string_literal":
                path_node = child
                break

        if not path_node:
            return

        # Extract the import path from the string literal
        import_path = ""
        for child in path_node.children:
            if child.type == "interpreted_string_literal_content":
                import_path = _text(child)
                break

        if not import_path:
            import_path = _text(path_node).strip('"')

        if import_path:
            alias = import_path.split("/")[-1]
            result.relations.append(
                RelationRecord(from_symbol="<module>", relation="IMPORTS", to_name=import_path)
            )
            result.import_aliases.append(
                ImportAliasRecord(alias=alias, source_module=import_path, source_name="")
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

    if func_node.type == "selector_expression":
        field = func_node.child_by_field_name("field")
        operand = func_node.child_by_field_name("operand")
        if field:
            field_name = _text(field)
            if operand and operand.type == "identifier":
                return (field_name, f"{_text(operand)}.{field_name}")
            return (field_name, field_name)

    return None
