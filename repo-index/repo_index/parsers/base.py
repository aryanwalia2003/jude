"""Abstract base for all language parsers."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class SymbolRecord:
    name: str
    kind: str        # function | class | method | module
    start_line: int
    end_line: int
    hash: str = ""
    fqid: str = ""   # fully-qualified identifier: module.Class.name
    module: str = "" # dotted module path derived from file path
    owner: str = ""  # owning class name (methods only)


@dataclass
class ImportAliasRecord:
    alias: str          # local name used in the file
    source_module: str  # dotted module path
    source_name: str    # "" for `import module`; specific name for `from x import y`

    @property
    def fqid(self) -> str:
        return f"{self.source_module}.{self.source_name}" if self.source_name else self.source_module


@dataclass
class RelationRecord:
    from_symbol: str
    relation: str        # IMPORTS | CALLS | INHERITS | DEFINES
    to_name: str
    call_expression: str = ""  # full dotted call ("jwt.validate") for resolution pass


@dataclass
class ParseResult:
    symbols: list[SymbolRecord] = field(default_factory=list)
    relations: list[RelationRecord] = field(default_factory=list)
    import_aliases: list[ImportAliasRecord] = field(default_factory=list)


class BaseParser(ABC):
    @property
    @abstractmethod
    def language(self) -> str: ...

    @property
    @abstractmethod
    def extensions(self) -> set[str]: ...

    @abstractmethod
    def parse(self, source: bytes, file_path: str, module: str = "") -> ParseResult: ...
