"""Tests for schema generation, validation, and serialization."""

import pytest
from prompt_engine.contracts import get_contract, OutputField
from prompt_engine.schemas import (
    to_json_schema,
    to_json_schema_strict,
    schema_for_task_type,
    get_required_fields,
    get_optional_fields,
    schema_to_prompt_text,
)
from prompt_engine.taxonomy import TaskType
from prompt_engine.validator import OutputValidator, ValidationResult
from prompt_engine.output_serializer import (
    serialize_task_output,
    serialize_with_validation,
    format_audit_for_output,
    compact_output,
)


class TestSchemaGeneration:
    """Test schema generation from OutputContract."""

    def test_schema_generation_basic(self):
        """Basic schema structure."""
        contract = get_contract(TaskType.DEBUGGING)
        schema = to_json_schema(contract)

        assert schema["type"] == "object"
        assert "properties" in schema
        assert "required" in schema
        assert len(schema["properties"]) > 0

    def test_schema_has_all_fields(self):
        """Schema includes all contract fields."""
        contract = get_contract(TaskType.DEBUGGING)
        schema = to_json_schema(contract)

        for field in contract.fields:
            assert field.name in schema["properties"]

    def test_schema_required_fields(self):
        """Schema correctly marks required fields."""
        contract = get_contract(TaskType.DEBUGGING)
        schema = to_json_schema(contract)

        required = get_required_fields(contract)
        assert set(schema["required"]) == set(required)

    def test_schema_additional_properties(self):
        """Non-strict schema allows additional properties."""
        contract = get_contract(TaskType.DEBUGGING)
        schema = to_json_schema(contract)
        assert schema["additionalProperties"] is True

    def test_schema_strict_forbids_additional(self):
        """Strict schema forbids unknown fields."""
        contract = get_contract(TaskType.DEBUGGING)
        schema = to_json_schema_strict(contract)
        assert schema["additionalProperties"] is False

    def test_schema_deterministic(self):
        """Same contract produces identical schema."""
        contract = get_contract(TaskType.BUGFIX)
        schema1 = to_json_schema(contract)
        schema2 = to_json_schema(contract)

        assert schema1 == schema2

    def test_schema_for_all_task_types(self):
        """Schemas can be generated for all task types."""
        for task_type in TaskType:
            schema = schema_for_task_type(task_type)
            assert schema["type"] == "object"
            assert "properties" in schema

    def test_required_fields_sorted(self):
        """Required fields are deterministically sorted."""
        required1 = get_required_fields(get_contract(TaskType.REFACTOR))
        required2 = get_required_fields(get_contract(TaskType.REFACTOR))

        assert required1 == required2
        assert required1 == sorted(required1)

    def test_optional_fields_sorted(self):
        """Optional fields are deterministically sorted."""
        optional1 = get_optional_fields(get_contract(TaskType.FEATURE))
        optional2 = get_optional_fields(get_contract(TaskType.FEATURE))

        assert optional1 == optional2
        assert optional1 == sorted(optional1)

    def test_schema_to_prompt_text(self):
        """Schema can be formatted as prompt text."""
        contract = get_contract(TaskType.DEBUGGING)
        schema = to_json_schema(contract)
        text = schema_to_prompt_text(schema)

        assert "SCHEMA" in text
        assert "required" in text.lower()
        assert "optional" in text.lower()


class TestOutputValidation:
    """Test output validation against schemas."""

    def test_validation_passes_with_all_required(self):
        """Validation passes when all required fields present."""
        output = {
            "reproduction": "Steps to reproduce",
            "evidence": "Stack trace",
            "likely_cause": "Root cause",
            "uncertainty": "Unknown factors",
            "next_steps": "What to do",
        }
        result = OutputValidator.validate(TaskType.DEBUGGING, output)

        assert result.is_valid is True
        assert len(result.missing_required) == 0

    def test_validation_fails_missing_required(self):
        """Validation fails when required fields missing."""
        output = {
            "reproduction": "Steps to reproduce",
        }
        result = OutputValidator.validate(TaskType.DEBUGGING, output)

        assert result.is_valid is False
        assert len(result.missing_required) > 0

    def test_missing_fields_detection(self):
        """Missing required fields are detected."""
        output = {"reproduction": "..."}
        missing = OutputValidator.get_missing_fields(TaskType.DEBUGGING, output)

        assert len(missing) > 0
        assert "evidence" in missing
        assert "likely_cause" in missing

    def test_unknown_fields_not_detected_by_default(self):
        """Unknown fields allowed by default."""
        output = {
            "reproduction": "...",
            "evidence": "...",
            "likely_cause": "...",
            "uncertainty": "...",
            "next_steps": "...",
            "unknown_field": "...",
        }
        result = OutputValidator.validate(TaskType.DEBUGGING, output, strict=False)

        assert result.is_valid is True
        assert len(result.unknown_fields) == 0

    def test_unknown_fields_detected_strict(self):
        """Unknown fields detected in strict mode."""
        output = {
            "reproduction": "...",
            "evidence": "...",
            "likely_cause": "...",
            "next_steps": "...",
            "unknown_field": "...",
        }
        result = OutputValidator.validate(TaskType.DEBUGGING, output, strict=True)

        assert result.is_valid is False
        assert "unknown_field" in result.unknown_fields

    def test_validation_result_bool(self):
        """ValidationResult is truthy when valid."""
        valid_result = ValidationResult(is_valid=True, task_type=TaskType.DEBUGGING)
        invalid_result = ValidationResult(is_valid=False, task_type=TaskType.DEBUGGING)

        assert bool(valid_result) is True
        assert bool(invalid_result) is False

    def test_validation_summary(self):
        """Validation result summary is readable."""
        output = {"reproduction": "..."}
        result = OutputValidator.validate(TaskType.DEBUGGING, output)
        summary = OutputValidator.summary(result)

        assert "FAIL" in summary
        assert "DEBUGGING" in summary
        assert "Missing Required" in summary


class TestOutputSerialization:
    """Test output serialization with audit trails."""

    def test_serialize_basic(self):
        """Basic serialization structure."""
        output = {
            "reproduction": "...",
            "evidence": "...",
            "likely_cause": "...",
            "next_steps": "...",
        }
        serialized = serialize_task_output(TaskType.DEBUGGING, output)

        assert serialized["task_type"] == "DEBUGGING"
        assert "timestamp" in serialized
        assert "schema_version" in serialized
        assert serialized["output"] == output

    def test_serialize_with_retrieval_audit(self):
        """Serialization includes retrieval audit."""
        output = {"reproduction": "..."}
        audit = {"symbols": 5, "top_score": 6.234}

        serialized = serialize_task_output(
            TaskType.DEBUGGING,
            output,
            retrieval_audit=audit,
        )

        assert serialized["retrieval_audit"] == audit

    def test_serialize_with_validation(self):
        """Serialization includes validation result."""
        output = {
            "reproduction": "...",
            "evidence": "...",
            "likely_cause": "...",
            "uncertainty": "...",
            "next_steps": "...",
        }

        serialized, result = serialize_with_validation(TaskType.DEBUGGING, output)

        assert result.is_valid is True
        assert "validation" in serialized
        assert serialized["validation"]["is_valid"] is True

    def test_serialize_deterministic_timestamp(self):
        """Timestamp is present in serialization."""
        output = {"reproduction": "..."}
        serialized = serialize_task_output(TaskType.DEBUGGING, output)

        assert "timestamp" in serialized
        assert "Z" in serialized["timestamp"]

    def test_compact_output_removes_audits(self):
        """Compact output strips audit data."""
        output = {
            "reproduction": "...",
            "evidence": "...",
            "likely_cause": "...",
            "next_steps": "...",
        }
        audit = {"symbols": 5}

        full = serialize_task_output(
            TaskType.DEBUGGING,
            output,
            retrieval_audit=audit,
        )
        compact = compact_output(full)

        assert "schema_version" not in compact
        assert "timestamp" not in compact
        assert "output" in compact
        assert "retrieval_audit" in compact

    def test_format_audit_none(self):
        """format_audit_for_output handles None."""
        result = format_audit_for_output(None)
        assert result is None

    def test_format_audit_dict(self):
        """format_audit_for_output passes through dicts."""
        audit = {"score": 5.0}
        result = format_audit_for_output(audit)
        assert result == audit


class TestEndToEndDeterminism:
    """Test full pipeline determinism."""

    def test_schema_generation_deterministic(self):
        """Full schema generation is deterministic."""
        schema1 = schema_for_task_type(TaskType.REFACTOR)
        schema2 = schema_for_task_type(TaskType.REFACTOR)

        assert schema1 == schema2

    def test_validation_deterministic(self):
        """Validation of same input is deterministic."""
        output = {
            "current_shape": "...",
            "target_shape": "...",
            "migration_path": "...",
            "patch": "...",
            "compatibility": "...",
            "risk_analysis": "...",
            "tests": "...",
        }

        result1 = OutputValidator.validate(TaskType.REFACTOR, output)
        result2 = OutputValidator.validate(TaskType.REFACTOR, output)

        assert result1.is_valid == result2.is_valid
        assert result1.missing_required == result2.missing_required

    def test_serialization_deterministic(self):
        """Serialization of same output is deterministic (except timestamp)."""
        output = {
            "reproduction": "...",
            "evidence": "...",
            "likely_cause": "...",
            "next_steps": "...",
        }

        serialized1 = serialize_task_output(TaskType.DEBUGGING, output)
        serialized2 = serialize_task_output(TaskType.DEBUGGING, output)

        # Same output and schema_version
        assert serialized1["output"] == serialized2["output"]
        assert serialized1["schema_version"] == serialized2["schema_version"]
        assert serialized1["task_type"] == serialized2["task_type"]
