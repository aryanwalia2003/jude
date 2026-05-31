# AI Infrastructure — Claude Integration Guide

This repository contains deterministic AI infrastructure for code analysis without LLM dependencies.

## Key Features

### Deterministic Context Ranking

All symbol searches use **deterministic multi-factor ranking** with full audit trails:

**Ranking factors (5 total):**
1. **Text relevance** (weight 2.0) — FTS5 BM25 score
2. **Call frequency** (weight 1.5) — log-scaled fan-in (# callers)
3. **Recency** (weight 0.8) — last indexed timestamp
4. **Name match** (weight 0.5) — query keywords in symbol name
5. **Code hub score** (weight 0.3) — structural metrics (fan-in)

**Why it matters:**
- Same query always produces same ranking (reproducible)
- Audit trail shows why each symbol ranked where it did
- No randomness, no ML variance — pure algorithms

### Audit Trail in Search Results

Every `search_symbols()` result includes:
```json
{
  "name": "emit_sync",
  "kind": "function",
  "file_path": "lib/events.py",
  "score": 6.234,
  "audit": {
    "rank": 1,
    "factors": [
      {
        "name": "call_frequency",
        "value": 3.51,
        "weight": 1.5,
        "contribution": 5.27
      }
    ]
  }
}
```

**Use the audit trail to:**
- Understand why symbols ranked high/low
- Identify architectural hubs (high call_frequency)
- Debug retrieval when context seems wrong
- Validate ranking behavior across sessions

### Impact Scoring

Context retrieval includes **impact audit** showing blast radius:
- How many transitive callers exist (impact count)
- How many modules are affected (module spread)
- Full factor breakdown with contributions

## How to Use

### Via MCP (Claude/Agents)

When you ask Claude to debug a symbol:
```
"Debug why emit_sync is not working"
```

Claude calls `search_symbols("emit_sync")` → gets ranked results with audit trails → understands:
- `emit_sync` is a hub (84% score from call_frequency)
- 67 callers depend on it
- Which related functions (`_emit_internal`, etc.) matter most

### Via CLI

```bash
# Basic search
crank emit_sync

# With audit trail showing factor breakdown
crank --audit emit_sync

# Custom limit
crank --limit 20 emit_sync

# Specific repo
crank --repo ~/myrepo emit_sync
```

### Via Python API

```python
from repo_index import db, retrieval

conn = db.open_db(".repo-index.db")
results = retrieval.search(conn, "emit_sync", limit=10)

for r in results:
    print(f"{r.name}: score={r.composite_score:.3f}")
    if r.audit:
        for factor in r.audit.factors:
            print(f"  {factor.name}: {factor.contribution:.3f}")
```

## Configuration

Ranking weights are tunable in `repo-index/repo_index/ranking.py`:

```python
WEIGHT_TEXT_RELEVANCE = 2.0    # Increase to prioritize text matches
WEIGHT_CALL_FREQUENCY = 1.5    # Increase to prioritize hubs
WEIGHT_RECENCY = 0.8
WEIGHT_NAME_MATCH = 0.5
WEIGHT_CODE_HUB = 0.3

WEIGHT_IMPACT_COUNT = 2.0      # Blast radius: impact size
WEIGHT_MODULE_SPREAD = 1.0     # Blast radius: cross-module reach
```

Adjust and re-run `repo-index build` to see immediate, deterministic impact.

## Workflow Enhancement

### Before (Without Ranking + Audit)
1. Ask Claude to debug `emit_sync`
2. Claude guesses at context, might miss important callers
3. Same question next week retrieves different symbols
4. No visibility into why context was chosen

### After (With Deterministic Ranking)
1. Ask Claude to debug `emit_sync`
2. Claude gets all 67 callers ranked by importance
3. Audit trail shows why (call_frequency = 84% contribution)
4. Same question next week retrieves same symbols, same order
5. Claude can reason about "why did the system prioritize THIS symbol?"

## Output Schema Enforcement

Task outputs are validated against **JSON schemas** derived from OutputContract:

**Example output for `debug emit_sync`:**
```json
{
  "task_type": "debugging",
  "timestamp": "2026-05-31T11:30:00Z",
  "schema_version": "1.0",
  "output": {
    "reproduction": "Call emit_sync with no listeners",
    "evidence": "Stack trace shows undefined callback",
    "likely_cause": "Missing null check in _emit_internal",
    "uncertainty": "Whether this affects all call sites",
    "next_steps": "Add guard clause, run full test suite"
  },
  "context_audit": {
    "symbols_retrieved": 67,
    "top_symbol": "emit_sync",
    "top_symbol_score": 6.234
  },
  "validation": {
    "is_valid": true,
    "required_fields_present": true,
    "schema_version": "1.0"
  }
}
```

**Why it matters:**
- ✅ **Deterministic** — Same task + same context = same schema + same validation
- ✅ **Auditable** — Every field traced to ranking audit
- ✅ **Structured** — JSON parseable, not freeform text
- ✅ **Reproducible** — STRICT mode enforces schema at compilation time

**Integration with modes:**
- `--mode strict` — Enforces schema validation
- `--mode safe` — Validates before returning output
- `--mode deep` — Includes full audit trail + impact analysis
- `--output json` — Returns structured JSON with schemas

## Files

### Ranking & Context
- `repo-index/repo_index/ranking.py` — Multi-factor scoring + audit trails
- `repo-index/repo_index/retrieval.py` — Context assembly with ranking
- `mcp-server/repo_index_mcp/serializers.py` — JSON serialization of audit data

### Output Schemas & Validation
- `prompt-engine/prompt_engine/schemas.py` — JSON schema generation from OutputContract
- `prompt-engine/prompt_engine/validator.py` — Output validation against schemas
- `prompt-engine/prompt_engine/output_serializer.py` — Serialization with audits

### Tools & Docs
- `~/.claude/scripts/crank` — CLI for ranking inspection with `--audit` flag
- `~/.claude/DETERMINISTIC-RANKING.md` — Ranking feature documentation
- `IMPLEMENTATION_PLAN_OUTPUT_SCHEMAS.md` — Output schema architecture

## Testing

```bash
# Verify ranking + audit trail
crank --audit parse

# Run all tests (retrieval + schemas)
pytest prompt-engine/tests/
```

**Test coverage:**
- 54 retrieval tests (ranking + context)
- 27 schema tests (generation + validation + serialization)
- All 81 tests passing ✓
