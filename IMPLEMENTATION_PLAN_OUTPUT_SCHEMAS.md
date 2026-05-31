# Implementation Plan: Output Schema Enforcement

**Goal:** Deterministic, structured output across all verb commands (analyze, debug, fix, refactor, etc.)

---

## Current State

✅ **contracts.py** — OutputContract dataclass already defines required/optional fields for 11 task types
✅ **compiler.py** — Uses contracts to embed output format in prompts as text blocks
✅ **task.py** — Task and PromptPlan data models exist

❌ **Missing:** 
- JSON schema generation from OutputContract
- Runtime output validation
- Structured JSON serialization with ranking audit
- Schema versioning

---

## Architecture

### 1. Schema Generator (`schemas.py`)
**Responsibility:** Convert OutputContract → JSON Schema 5.0

```python
class OutputSchemaGenerator:
    def to_json_schema(contract: OutputContract) -> dict
    def to_json_schema_strict(contract: OutputContract) -> dict  # Forbids unknown fields
    def validate_against_schema(output: dict, schema: dict) -> tuple[bool, list[str]]
```

**Input:** OutputContract from contracts.py
**Output:** JSON Schema that can validate task outputs

### 2. Validator Module (`validator.py`)
**Responsibility:** Validate task outputs against schemas

```python
class OutputValidator:
    def validate_task_output(task_type: TaskType, output: dict) -> ValidationResult
    def enforce_required_fields(output: dict, required: list[str]) -> list[str]
    def get_missing_fields(output: dict, contract: OutputContract) -> list[str]

@dataclass
class ValidationResult:
    is_valid: bool
    errors: list[str]
    warnings: list[str]
    missing_required: list[str]
    unknown_fields: list[str]
```

### 3. Serializer Enhancement (`output_serializer.py`)
**Responsibility:** Serialize task output with ranking audit + structured fields

```python
class TaskOutputSerializer:
    def serialize_task_output(
        task_type: TaskType,
        fields: dict,
        retrieval_audit: Optional[RankingAudit],
        impact_audit: Optional[RankingAudit],
        validation_result: Optional[ValidationResult]
    ) -> dict
```

**Output structure:**
```json
{
  "task_type": "debugging",
  "timestamp": "2026-05-31T11:30:00Z",
  "schema_version": "1.0",
  "output": {
    "reproduction": "...",
    "evidence": "...",
    "likely_cause": "...",
    "next_steps": "..."
  },
  "context_audit": {
    "symbols_retrieved": 5,
    "ranking_factors": [...],
    "top_symbol": "emit_sync",
    "top_symbol_score": 6.234
  },
  "impact_audit": {
    "affected_symbols": 67,
    "module_spread": 5,
    "factors": [...]
  },
  "validation": {
    "is_valid": true,
    "required_fields_present": true,
    "schema_version": "1.0"
  }
}
```

### 4. Compiler Integration (`compiler.py` update)
**Change:** Include JSON schema in prompt when STRICT mode is enabled

```python
def _schema_block(task: Task) -> PromptBlock:
    schema = _generate_output_schema(task.task_type)
    return PromptBlock(
        role="system",
        content=_format_schema_for_prompt(schema),
        priority=_P_OUTPUT_SCHEMA,
        source="output_schema",
    )
```

When compiling STRICT mode:
- Include OutputContract fields as natural language
- Optionally include JSON schema for reference
- Add validation instruction

### 5. Test Suite (`tests/test_schemas.py`)
**Coverage:**
- Schema generation for all 11 task types ✓
- Required vs optional field handling ✓
- Validation success/failure cases ✓
- Missing required field detection ✓
- Unknown field detection ✓
- Deterministic schema output (same contract → same schema) ✓
- Audit trail serialization ✓

---

## Integration Points

### With Ranking + Audit Trail
The serializer combines:
1. **Task output fields** (from OutputContract)
2. **Retrieval audit** (which symbols were retrieved, why)
3. **Impact audit** (blast radius scoring)
4. **Validation result** (did output meet schema?)

Result: **Full traceability** — user sees both the answer AND why those symbols were selected AND why the output is valid.

### With Prompt Compiler
- STRICT mode automatically includes schema
- SAFE mode enforces validation before returning
- DEEP mode includes full audit trail
- MINIMAL mode strips optional fields

### With prompt-engine CLI
```bash
ai debug emit_sync --mode strict  # Includes schema validation
ai analyze file.py --output json  # Returns structured JSON
```

---

## Deliverables

1. **`prompt_engine/schemas.py`** (200 lines)
   - OutputSchemaGenerator
   - to_json_schema(contract) → dict
   - to_json_schema_strict() variant

2. **`prompt_engine/validator.py`** (250 lines)
   - OutputValidator
   - ValidationResult dataclass
   - enforce_required_fields()
   - get_missing_fields()

3. **`prompt_engine/output_serializer.py`** (200 lines)
   - TaskOutputSerializer
   - serialize_task_output()
   - combine with RankingAudit

4. **Update `compiler.py`** (50 lines)
   - _schema_block() function
   - Integration with STRICT/SAFE modes
   - Schema prompt formatting

5. **Tests `tests/test_schemas.py`** (400 lines)
   - Test all 11 task types
   - Validation coverage
   - Determinism tests
   - Audit integration tests

---

## Determinism Guarantees

✓ **Same contract** → **Same JSON schema** (deterministic, no randomness)
✓ **Same schema** → **Same validation** (boolean logic only)
✓ **Same task output** → **Same serialization** (no variance)
✓ **Same ranking** → **Same audit trail** (from ranking.py)

Result: **Full end-to-end determinism** — analyze task → same context → same output schema → same validation → same serialized JSON.

---

## Success Criteria

1. ✅ All 11 OutputContract types have JSON schemas
2. ✅ Validation catches missing required fields
3. ✅ Unknown fields are detected (optional)
4. ✅ Audit trail embedded in serialized output
5. ✅ 90%+ test coverage for schema/validator modules
6. ✅ STRICT mode enforces schema at compilation time
7. ✅ CLI outputs deterministic JSON
8. ✅ Schemas are version-tracked

---

## Files to Create/Modify

### Create
- `prompt-engine/prompt_engine/schemas.py`
- `prompt-engine/prompt_engine/validator.py`
- `prompt-engine/prompt_engine/output_serializer.py`
- `prompt-engine/tests/test_schemas.py`

### Modify
- `prompt-engine/prompt_engine/compiler.py` (add schema block)
- `prompt-engine/prompt_engine/__init__.py` (export new modules)

### No Changes Needed
- `contracts.py` (already well-structured)
- `task.py` (already has PromptPlan)
- `ranking.py` (from previous work)
