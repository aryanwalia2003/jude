"""Parser registry — maps file extensions to language parsers."""

from pathlib import Path

from .base import BaseParser, ParseResult
from .python import PythonParser
from .go import GoParser
from .javascript import JavaScriptParser, TypeScriptParser

_PARSERS: list[BaseParser] = [
    PythonParser(),
    GoParser(),
    JavaScriptParser(),
    TypeScriptParser(),
]

_EXT_MAP: dict[str, BaseParser] = {
    ext: parser
    for parser in _PARSERS
    for ext in parser.extensions
}


def get_parser(file_path: str | Path) -> BaseParser | None:
    suffix = Path(file_path).suffix.lower()
    return _EXT_MAP.get(suffix)


__all__ = ["get_parser", "BaseParser", "ParseResult"]
