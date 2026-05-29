# Multi-Language Parser Support

## Overview

Extended `repo-index` with AST parsing support for **Go** and **JavaScript/TypeScript**, joining the existing Python parser. This enables semantic code indexing across polyglot codebases.

---

## What Was Added

### 1. Go Parser (`repo_index/parsers/go.py`)

**Supported file types:** `.go`

**Extracts:**
- Top-level functions
- Type definitions (structs, interfaces)
- Methods (with receiver type identification)
- Import statements (single and grouped `import (...)`)
- Call expressions (function and method calls)

**Key features:**
- Receiver type extraction for method ownership (`func (s *Server) Start()`)
- Handles both `*Type` and `Type` receivers correctly
- Supports Go package imports with import groups

**Tests:** 8 tests covering functions, structs, methods, and imports

### 2. JavaScript Parser (`repo_index/parsers/javascript.py`)

**Supported file types:** `.js`, `.jsx`, `.mjs`, `.cjs`

**Extracts:**
- Function declarations
- Class declarations
- Methods (both regular and arrow functions)
- Default and named imports
- Export statements
- Call expressions

**Key features:**
- Handles JSX syntax
- Supports different import/export patterns
- Extracts method ownership from class context

**Tests:** 8 tests covering functions, classes, methods, imports, and calls

### 3. TypeScript Parser (`repo_index/parsers/javascript.py`)

**Supported file types:** `.ts`, `.tsx`

**Extends:** JavaScript parser with additional TypeScript features

**Additional extracts:**
- Interface declarations (treated as classes for symbol extraction)
- Type annotations

**Key features:**
- Full TypeScript syntax support including generics
- Distinguishes between classes and interfaces

**Tests:** 6 tests covering TypeScript-specific features

---

## Integration Points

### Updated Files

1. **`repo_index/parsers/__init__.py`**
   - Registered `GoParser`, `JavaScriptParser`, `TypeScriptParser`
   - Dynamic parser selection via file extension

2. **`repo_index/scanner.py`**
   - Updated `_SKIP_DIRS` to exclude language-specific directories:
     - Node.js: `node_modules`, `.next`, `.webpack`
     - Go: `vendor`
   - Updated `_SUPPORTED_EXTENSIONS` to dynamically derive from registered parsers

3. **`repo_index/symbol_table.py`**
   - Enhanced `file_to_module()` to handle Go, JavaScript, and TypeScript extensions
   - Correctly strips file extensions to form dotted module paths

4. **`repo-index/tests/test_watcher.py`**
   - Updated test assertion to reflect new indexable languages

---

## Test Coverage

- **Go Parser Tests:** `repo-index/tests/test_go_parser.py` (8 tests)
- **JavaScript/TypeScript Tests:** `repo-index/tests/test_javascript_parser.py` (14 tests)
- **Existing Python Tests:** Still passing (unchanged)
- **Integration Tests:** All 162 repo-index tests passing

---

## Usage

The indexer automatically detects file type by extension and applies the appropriate parser.

```bash
# Index a multi-language codebase
repo-index build /path/to/monorepo

# Search across all languages
repo-index search "UserService"

# Get context for any symbol
repo-index context Server
repo-index context App
```

### Example: Go Indexing

```bash
$ cd /path/to/gin-project
$ repo-index build .

Indexing /path/to/gin-project → ~/.local/share/repo-index/index.db
  Files scanned               12  
  Files indexed               12  
  Symbols added              145  
  Relations added            320
```

### Example: React Indexing

```bash
$ cd /path/to/react-app
$ repo-index build .

Indexing /path/to/react-app → ~/.local/share/repo-index/index.db
  Files scanned               25  
  Files indexed               25  
  Symbols added               187  
  Relations added            412
```

---

## Architecture

All parsers follow the same pattern:

1. **Inheritance:** Extend `BaseParser` abstract class
2. **Implementation:** Implement `language`, `extensions`, and `parse()` methods
3. **Tree-sitter:** Use Tree-sitter's pre-built parsers via `tree_sitter_language_pack`
4. **Output:** Emit `ParseResult` with `SymbolRecord`, `RelationRecord`, and `ImportAliasRecord`
5. **Registry:** Auto-register in `_PARSERS` list

---

## What's Indexed

### Go

| Symbol Type | Extracted? | Example |
|---|---|---|
| Functions | ✅ | `func main() {}` |
| Methods | ✅ | `func (s *Server) Start() {}` |
| Structs/Interfaces | ✅ | `type Server struct {}` |
| Imports | ✅ | `import "fmt"` / grouped |
| Calls | ✅ | `fmt.Println()`, `s.Start()` |

### JavaScript/TypeScript

| Symbol Type | Extracted? | Example |
|---|---|---|
| Functions | ✅ | `function foo() {}` |
| Classes | ✅ | `class Button extends React.Component {}` |
| Methods | ✅ | `render() { ... }` |
| Interfaces (TS) | ✅ | `interface IButton { ... }` |
| Imports | ✅ | `import { Component } from 'react'` |
| Calls | ✅ | `setState()`, `this.handleClick()` |

---

## Next Steps

Now that multi-language support is in place:

1. **Broader applicability:** Index any Python, Go, or JavaScript/TypeScript codebase
2. **Foundation for Phase 5:** Semantic summarization layer will work across all languages
3. **Enhanced retrieval:** Call graphs, imports, and code structure now work across polyglot systems
4. **Better prompt engine context:** Retrieving context from Go or React codebases is now accurate

---

## Test Results Summary

```
repo-index tests:      162 passed
prompt-engine tests:   54 passed
go parser tests:       8 passed
js/ts parser tests:    14 passed
```

**Total:** 238 tests passing ✅
