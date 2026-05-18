"""Lexical scope tracking — import aliases, class/function context during traversal."""

from dataclasses import dataclass


@dataclass
class ImportAlias:
    alias: str           # local name used in the file
    source_module: str   # dotted module path (e.g. "auth.jwt")
    source_name: str     # "" for `import module`, specific name for `from x import y`

    @property
    def fqid(self) -> str:
        return f"{self.source_module}.{self.source_name}" if self.source_name else self.source_module


class ScopeStack:
    """Tracks class/function nesting and import aliases during AST traversal."""

    def __init__(self, module: str) -> None:
        self._module = module
        self._class_stack: list[str] = []
        self._aliases: dict[str, ImportAlias] = {}

    @property
    def module(self) -> str:
        return self._module

    @property
    def current_class(self) -> str | None:
        return self._class_stack[-1] if self._class_stack else None

    def push_class(self, name: str) -> None:
        self._class_stack.append(name)

    def pop_class(self) -> None:
        if self._class_stack:
            self._class_stack.pop()

    def add_alias(self, alias: str, source_module: str, source_name: str = "") -> None:
        self._aliases[alias] = ImportAlias(alias, source_module, source_name)

    def resolve_name(self, name: str) -> str | None:
        """Return the FQID for a local alias, or None if unknown."""
        a = self._aliases.get(name)
        return a.fqid if a else None

    @property
    def aliases(self) -> list[ImportAlias]:
        return list(self._aliases.values())

    def make_fqid(self, symbol_name: str) -> str:
        """FQID for a symbol defined at the current scope level."""
        if self.current_class:
            return f"{self._module}.{self.current_class}.{symbol_name}"
        return f"{self._module}.{symbol_name}"
