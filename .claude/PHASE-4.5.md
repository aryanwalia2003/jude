````md id="kgj5v8"
# Phase 4.5 — Semantic Resolution Layer

## Overview

Current repo-index architecture successfully extracts:
- symbols
- imports
- calls
- inheritance relations
- file-level dependencies

However, relations are currently unresolved:

```sql
relations.to_name TEXT
````

This means:

* references are name-based only
* graph edges are ambiguous
* call relationships are not semantically accurate

Phase 4.5 introduces:

> true symbol resolution

This transforms the system from:

* syntax-aware indexing

into:

* semantic code intelligence.

---

# Goals

The semantic resolution layer must:

1. resolve symbol references to actual symbols
2. create stable fully-qualified symbol identities
3. model namespaces and ownership
4. disambiguate calls/imports
5. support cross-file semantic traversal
6. prepare the graph for semantic summarization
7. improve retrieval accuracy dramatically

---

# Current Problem

Current relation model:

```sql
relations(
    from_id,
    relation,
    to_name
)
```

Example:

```python
foo()
```

Current graph:

```text
CALLS -> "foo"
```

This is ambiguous because:

* multiple functions may be named `foo`
* imported aliases exist
* methods may shadow globals
* local scope may override imports
* module-qualified calls exist

The system currently knows:

* syntax

but not:

* semantic identity

---

# Target State

The system should eventually represent:

```text
repo.auth.jwt.validate_token
```

instead of:

```text
validate_token
```

Graph edges should point to:

* actual symbol IDs
* not unresolved strings

---

# Core Concepts

## 1. Fully Qualified Symbol IDs (FQSI)

Every symbol must have a globally unique semantic identity.

### Format

```text
<repo>.<module>.<class?>.<symbol>
```

Examples:

```text
dashboard.auth.jwt.validate_token
dashboard.auth.jwt.JWTService.refresh
dashboard.orders.models.Order.save
```

---

## 2. Namespace Hierarchy

The graph must model ownership hierarchy.

Example:

```text
module
  └── class
        └── method
```

This hierarchy becomes first-class graph structure.

---

## 3. Scope Resolution

The resolver must understand:

* local scope
* module scope
* class scope
* imported symbols
* aliases
* shadowing

Example:

```python
from utils import foo

def bar():
    foo()
```

Resolver should connect:

* `foo()` call
  → imported `utils.foo`

NOT:

* random symbol named `foo`

---

## 4. Import Resolution

The system must resolve:

```python
import x
from x import y
from x import y as z
```

into actual module/symbol references.

---

# Phase 4.5 Deliverables

---

# Deliverable 1 — Stable Symbol IDs

## Current

```python
SymbolRecord(
    name="validate",
    kind="function"
)
```

## New

```python
ResolvedSymbol(
    fqid="dashboard.auth.jwt.validate",
    name="validate",
    module="dashboard.auth.jwt",
    owner="dashboard.auth.jwt",
    kind="function"
)
```

---

# Deliverable 2 — Ownership Graph

Add explicit ownership edges:

```text
MODULE_OWNS
CLASS_OWNS
DEFINES
```

Example:

```text
dashboard.auth.jwt
    MODULE_OWNS
        validate_token

JWTService
    CLASS_OWNS
        refresh
```

---

# Deliverable 3 — Import Resolution Engine

Build resolver capable of:

## Resolve:

```python
from auth.jwt import validate
validate()
```

to:

```text
dashboard.auth.jwt.validate
```

---

## Resolve aliases:

```python
from auth.jwt import validate as v
v()
```

---

## Resolve module calls:

```python
import auth.jwt
auth.jwt.validate()
```

---

# Deliverable 4 — Resolved Relations

Current:

```sql
relations.to_name
```

New schema:

```sql
relations.to_symbol_id
```

OR:

```sql
relations(
    from_symbol_id,
    relation,
    to_symbol_id,
    unresolved_name
)
```

Important:
keep unresolved fallback support.

Dynamic languages cannot always resolve statically.

---

# Deliverable 5 — Scope Tracking

The parser must track:

* current module
* current class
* current function
* imported aliases
* local definitions

during traversal.

---

# Deliverable 6 — Module Graph

Add explicit module-level graph:

```text
module A imports module B
module A depends on module C
module A exposes symbol X
```

This becomes:

* architecture graph
* dependency graph
* subsystem graph foundation

---

# Deliverable 7 — Resolution Confidence

Not all references can resolve statically.

Add confidence metadata:

```python
ResolvedRelation(
    confidence=1.0
)
```

Examples:

| Confidence | Meaning                   |
| ---------- | ------------------------- |
| 1.0        | exact semantic resolution |
| 0.8        | likely resolved           |
| 0.5        | heuristic match           |
| 0.0        | unresolved                |

---

# Required Schema Changes

---

## symbols

Add:

```sql
fqid TEXT UNIQUE
module TEXT
owner_symbol_id INTEGER NULL
```

---

## relations

Add:

```sql
to_symbol_id INTEGER NULL
unresolved_name TEXT NULL
confidence REAL DEFAULT 1.0
```

---

## modules

Optional but recommended:

```sql
CREATE TABLE modules (
    id INTEGER PRIMARY KEY,
    name TEXT UNIQUE,
    path TEXT UNIQUE
);
```

---

# Parser Responsibilities

Parsers must now extract:

* symbol declarations
* ownership hierarchy
* imports
* aliases
* namespace structure
* lexical scopes

NOT just flat symbols.

---

# Python Parser Requirements

Must support:

## Functions

```python
def x():
```

---

## Classes

```python
class User:
```

---

## Methods

```python
class User:
    def save():
```

---

## Imports

```python
import os
from x import y
from x import y as z
```

---

## Calls

```python
foo()
obj.save()
module.foo()
```

---

## Decorators

```python
@router.get
```

Need decorator ownership preserved.

---

# Retrieval Improvements Expected

After semantic resolution:

## Current

Search:

```text
who calls save
```

May return:

* many unrelated saves

---

## After Phase 4.5

Search:

```text
who calls dashboard.models.User.save
```

Returns:

* exact callers
* exact blast radius
* exact dependency graph

Huge retrieval quality improvement.

---

# Architectural Importance

Phase 4.5 is the transition from:

```text
syntax graph
```

to:

```text
semantic graph
```

This is one of the most important milestones in the entire system.

---

# Explicit Non-Goals (For This Phase)

Do NOT implement yet:

* embeddings
* LLM summarization
* semantic search
* runtime tracing
* type inference
* data flow analysis
* SSA/CFG construction
* dynamic execution tracing

This phase is purely:

* static semantic resolution

---

# Suggested Internal Architecture

```text
AST Parse
    ↓
Scope Tracker
    ↓
Import Resolver
    ↓
Symbol Table Builder
    ↓
Reference Resolver
    ↓
Resolved Semantic Graph
```

---

# Suggested Internal Components

## resolver.py

Responsibilities:

* scope resolution
* import resolution
* alias handling
* symbol lookup

---

## symbol_table.py

Responsibilities:

* fqid generation
* namespace ownership
* module registry
* lookup indexes

---

## scopes.py

Responsibilities:

* lexical scope stack
* local symbol tracking
* current context management

---

# Suggested CLI Additions

```bash
repo-index resolve validate
repo-index fqid dashboard.auth.jwt.validate
repo-index ownership JWTService
repo-index module dashboard.auth.jwt
```

---

# Testing Requirements

Must test:

* imported calls
* aliases
* shadowing
* nested scopes
* methods vs globals
* duplicate symbol names
* cross-file imports
* unresolved references
* branch consistency

---

# Success Criteria

Phase 4.5 is successful when:

1. most call edges resolve to exact symbols
2. graph ambiguity drops significantly
3. retrieval becomes semantically accurate
4. ownership hierarchy exists
5. imports resolve across files/modules
6. fully-qualified symbol identity becomes stable

At this point the system becomes:

* true semantic repository intelligence
* not merely AST extraction.

```
```
