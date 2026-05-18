# AI Repository Intelligence System — Project Context

## Vision

We are building a local-first AI-native repository intelligence system.

This is NOT:
- a chatbot wrapper
- naive RAG
- embeddings-only retrieval
- “chat with repo”

This IS:
- persistent repository intelligence infrastructure
- AST-aware indexing
- semantic code understanding
- branch-aware memory
- retrieval substrate for AI coding agents

The system should eventually function like:

- a compiler-aware memory system
- a semantic operating system for repositories
- a persistent intelligence daemon for AI agents

The focus is:
- repository understanding
- structural intelligence
- semantic compression
- retrieval quality
- incremental indexing
- long-term reusable context

NOT prompt engineering.

---

# Existing User Environment

The user already has a highly optimized terminal-first AI workflow.

## Existing Tooling

Environment already includes:
- tmux workflows
- fzf workflows
- fd
- ripgrep
- custom shell ergonomics
- Claude Code
- Antigravity
- AI skills system
- repo discovery scripts

The environment is highly terminal-native.

---

# Existing AI OS Structure

The user already built:
- reusable Claude skills
- orchestration commands
- repo analysis scripts
- debugging workflows
- test workflows
- architecture analysis tooling

Examples:
- cmap
- ccontext
- cdeps
- cboot
- cfail
- cmissing
- cpr
- cswagger

These currently work using:
- grep
- fd
- shell orchestration
- runtime context gathering

The system is already very strong ergonomically.

The weakness:
- ephemeral context
- no persistent graph
- no AST awareness
- no semantic cache
- no branch-aware reuse
- repeated repo scanning

The next evolution is:
existing scripts become thin clients over a persistent intelligence daemon.

---

# Architectural Philosophy

Core principle:

FACTS != INTERPRETATION

Layer 1 stores:
- raw structural facts
- AST entities
- imports
- symbols
- call graphs
- relations

Layer 2 stores:
- semantic summaries
- architectural understanding
- workflows
- invariants
- subsystem responsibilities

Layer 2 is DERIVED DATA.
Layer 1 is SOURCE OF TRUTH.

---

# Long-Term Architecture

## Layer 1 — Structural Intelligence

This layer maintains:
- AST trees
- symbol extraction
- imports
- definitions
- call graphs
- dependency graphs
- lexical indexes
- file hashes
- symbol hashes

This layer must support:
- incremental parsing
- branch-aware invalidation
- fast retrieval
- graph traversal

No LLM required for most structural queries.

---

## Layer 2 — Semantic Knowledge Cache

This layer maintains:
- function summaries
- module summaries
- subsystem summaries
- architectural invariants
- workflow descriptions
- risk maps
- semantic embeddings

This is generated incrementally from Layer 1.

This layer is:
- compressed
- semantic
- regeneratable
- hash-aware

---

# Current Goal

We are currently implementing:

## Phase 0 — Infrastructure Foundation

Installed:
- Rust
- Cargo
- LLVM
- libclang
- SQLite
- Tree-sitter CLI
- uv
- Python tooling

Environment variables:
- LIBCLANG_PATH configured
- Cargo PATH configured

This enables:
- AST parsing
- native tooling compilation
- parser infrastructure

---

# Current Workspace

Workspace:
~/ai-infra/repo-index

Tech stack:
- Python orchestration
- Tree-sitter parsing
- SQLite persistence
- Rich terminal UI
- Typer CLI
- NetworkX experimentation

Installed Python deps:
- tree-sitter
- tree-sitter-language-pack
- rich
- typer
- networkx

---

# Immediate Current Work

We are currently learning and implementing:
- AST parsing
- AST traversal
- symbol extraction
- structural code understanding

Initial playground examples:
- parsing Python source
- walking syntax trees
- extracting functions/classes

This is the beginning of:
- repository indexing
- structural intelligence
- compiler-style repo understanding

---

# Planned Near-Term Roadmap

## Phase 1 — Symbol Indexer

Build:
- repo scanner
- AST extraction
- symbol extraction
- import extraction
- call graph
- SQLite persistence

CLI examples:
- repo-index build
- repo-index symbol AuthService
- repo-index callers refresh_token

---

## Phase 2 — Incremental Indexing

Add:
- filesystem watcher
- hash invalidation
- incremental parsing
- partial graph rebuilds

Goal:
avoid full reindexing.

---

## Phase 3 — Branch-Aware Intelligence

Store:
- file hashes
- symbol hashes
- branch snapshots

Goal:
reuse indexing across branches.

Only changed symbols/files should invalidate.

This is a major architectural differentiator.

---

## Phase 4 — Retrieval Engine

Hybrid retrieval:
- lexical search
- AST graph traversal
- semantic retrieval
- dependency traversal

Goal:
context assembly BEFORE LLM reasoning.

---

## Phase 5 — Semantic Summarization

Generate:
- module summaries
- subsystem summaries
- architecture summaries
- workflow descriptions

Hierarchy:
function -> module -> subsystem -> repo

---

## Phase 6 — MCP Integration

Expose repository intelligence via MCP.

Capabilities:
- symbol lookup
- dependency analysis
- graph traversal
- semantic retrieval
- architectural explanations

This allows:
- Claude Code
- Cursor
- Codex
- other agents

to share the same persistent intelligence layer.

---

# Important Design Principles

## 1. Infrastructure First

Do NOT jump to:
- agents
- autonomous loops
- fancy prompting
- LangChain abstractions

The substrate comes first.

---

## 2. AST > Embeddings

Embeddings are supplementary.

Primary intelligence comes from:
- syntax trees
- graph structure
- symbol relationships
- compiler-style analysis

---

## 3. Incremental Everything

Never rebuild entire repo unnecessarily.

Everything should support:
- hash invalidation
- partial recomputation
- event-driven updates

---

## 4. Persistent Intelligence

Current scripts are ephemeral.

Target architecture:
persistent repository memory.

---

## 5. Event-Driven Architecture

Internal events:
- FILE_CHANGED
- SYMBOL_UPDATED
- SUMMARY_INVALIDATED
- BRANCH_SWITCHED

This enables:
- incremental recomputation
- async pipelines
- future multi-agent support

---

# Recommended Storage Architecture

Initial stack:
- SQLite
- FTS5
- Tree-sitter
- ripgrep
- local embeddings later

No premature distributed systems.

---

# Initial Planned Schema

## symbols

- id
- name
- kind
- file_path
- start_line
- end_line
- hash
- language

## relations

- from_id
- relation
- to_id

Examples:
- IMPORTS
- CALLS
- DEFINES
- INHERITS
- USES

## files

- path
- content_hash
- branch
- last_indexed_at

## summaries

- symbol_id
- level
- summary
- embedding
- based_on_hash

---

# Existing Scripts Context

Current scripts:
- cboot
- cmap
- ccontext
- cdeps
- cfail
- cpr
- cmissing
- cswagger

Current behavior:
grep + shell orchestration.

Future behavior:
query persistent repository intelligence daemon.

Example:
OLD:
rg "^import"

NEW:
repo-index query imports

---

# Long-Term Vision

Eventually the system should support:
- semantic CI
- architecture drift detection
- dead code analysis
- impact analysis
- autonomous debugging
- multi-agent shared memory
- architectural reasoning
- semantic repository onboarding

The system should evolve into:
an AI-native repository operating system.