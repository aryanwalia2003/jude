"""Output serialization with deterministic audit trails.

Combines task output fields with retrieval + impact audits for full traceability.
"""

from dataclasses import asdict
from datetime import datetime
from typing import Any, Optional

from .taxonomy import TaskType
from .validator import OutputValidator, ValidationResult


def serialize_task_output(
    task_type: TaskType,
    output_fields: dict[str, Any],
    retrieval_audit: Optional[dict] = None,
    impact_audit: Optional[dict] = None,
    validation_result: Optional[ValidationResult] = None,
    schema_version: str = "1.0",
) -> dict:
    """Serialize task output with full audit trail.

    Args:
        task_type: Type of task
        output_fields: Dict of output field values
        retrieval_audit: Optional ranking audit from context retrieval
        impact_audit: Optional impact/blast radius audit
        validation_result: Optional validation result
        schema_version: Version identifier for schema

    Returns:
        Structured output dict with audits and metadata
    """
    result = {
        "task_type": task_type.name,
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "schema_version": schema_version,
        "output": output_fields,
    }

    if retrieval_audit:
        result["retrieval_audit"] = retrieval_audit

    if impact_audit:
        result["impact_audit"] = impact_audit

    if validation_result:
        result["validation"] = {
            "is_valid": validation_result.is_valid,
            "required_fields_present": len(validation_result.present_required),
            "optional_fields_present": len(validation_result.present_optional),
            "missing_required": validation_result.missing_required,
            "unknown_fields": validation_result.unknown_fields,
            "errors": validation_result.errors,
            "warnings": validation_result.warnings,
        }

    return result


def serialize_with_validation(
    task_type: TaskType,
    output_fields: dict[str, Any],
    retrieval_audit: Optional[dict] = None,
    impact_audit: Optional[dict] = None,
    strict: bool = False,
    schema_version: str = "1.0",
) -> tuple[dict, ValidationResult]:
    """Serialize output and validate in one step.

    Args:
        task_type: Type of task
        output_fields: Dict of output field values
        retrieval_audit: Optional ranking audit
        impact_audit: Optional impact audit
        strict: If True, forbid unknown fields
        schema_version: Schema version

    Returns:
        Tuple of (serialized_output, validation_result)
    """
    validation = OutputValidator.validate(task_type, output_fields, strict=strict)

    output = serialize_task_output(
        task_type=task_type,
        output_fields=output_fields,
        retrieval_audit=retrieval_audit,
        impact_audit=impact_audit,
        validation_result=validation,
        schema_version=schema_version,
    )

    return output, validation


def format_audit_for_output(audit_data: Optional[Any]) -> Optional[dict]:
    """Format audit trail data for JSON serialization.

    Converts dataclass audit objects to dicts.

    Args:
        audit_data: RankingAudit or similar dataclass

    Returns:
        Dict representation or None
    """
    if audit_data is None:
        return None

    if isinstance(audit_data, dict):
        return audit_data

    if hasattr(audit_data, '__dataclass_fields__'):
        return asdict(audit_data)

    return None


def compact_output(serialized: dict) -> dict:
    """Remove optional/verbose fields for compact output.

    Args:
        serialized: Full serialized output

    Returns:
        Compact version (only required fields + core output)
    """
    compact = {
        "task_type": serialized["task_type"],
        "output": serialized["output"],
    }

    if "retrieval_audit" in serialized:
        compact["retrieval_audit"] = serialized["retrieval_audit"]

    return compact


def verbose_output(serialized: dict) -> dict:
    """Enhance output with additional context (pass-through for now).

    Args:
        serialized: Serialized output

    Returns:
        Same as input (can be extended later)
    """
    return serialized
