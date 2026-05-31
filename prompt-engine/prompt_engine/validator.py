"""Output validation against schemas.

Validates task outputs to ensure they meet contract requirements.
Deterministic: same output + same schema = same validation result.
"""

from dataclasses import dataclass, field as dc_field
from typing import Any

from .contracts import OutputContract, get_contract
from .schemas import get_required_fields, get_optional_fields
from .taxonomy import TaskType


@dataclass
class ValidationResult:
    """Structured validation outcome."""
    is_valid: bool
    task_type: TaskType
    errors: list[str] = dc_field(default_factory=list)
    warnings: list[str] = dc_field(default_factory=list)
    missing_required: list[str] = dc_field(default_factory=list)
    unknown_fields: list[str] = dc_field(default_factory=list)
    present_required: list[str] = dc_field(default_factory=list)
    present_optional: list[str] = dc_field(default_factory=list)

    def __bool__(self) -> bool:
        """Truthy if validation passed."""
        return self.is_valid


class OutputValidator:
    """Validates task outputs against schemas."""

    @staticmethod
    def validate(
        task_type: TaskType,
        output: dict[str, Any],
        strict: bool = False,
    ) -> ValidationResult:
        """Validate output against task type schema.

        Args:
            task_type: Type of task
            output: Output dict to validate
            strict: If True, forbid unknown fields

        Returns:
            ValidationResult with detailed feedback
        """
        contract = get_contract(task_type)
        result = ValidationResult(is_valid=True, task_type=task_type)

        # Check required fields
        required = get_required_fields(contract)
        optional = get_optional_fields(contract)
        all_allowed = set(required) | set(optional)

        output_keys = set(output.keys())
        missing = set(required) - output_keys
        unknown = output_keys - all_allowed if strict else set()

        if missing:
            result.is_valid = False
            result.missing_required = sorted(missing)
            result.errors.append(f"Missing required fields: {', '.join(sorted(missing))}")

        if unknown:
            result.is_valid = False
            result.unknown_fields = sorted(unknown)
            result.warnings.append(f"Unknown fields (strict mode): {', '.join(sorted(unknown))}")

        # Track present fields
        result.present_required = sorted(set(required) & output_keys)
        result.present_optional = sorted(set(optional) & output_keys)

        return result

    @staticmethod
    def get_missing_fields(
        task_type: TaskType,
        output: dict[str, Any],
    ) -> list[str]:
        """Get missing required fields.

        Args:
            task_type: Type of task
            output: Output dict

        Returns:
            Sorted list of missing required field names
        """
        contract = get_contract(task_type)
        required = get_required_fields(contract)
        missing = set(required) - set(output.keys())
        return sorted(missing)

    @staticmethod
    def get_unknown_fields(
        task_type: TaskType,
        output: dict[str, Any],
    ) -> list[str]:
        """Get fields not in schema.

        Args:
            task_type: Type of task
            output: Output dict

        Returns:
            Sorted list of unknown field names
        """
        contract = get_contract(task_type)
        required = set(get_required_fields(contract))
        optional = set(get_optional_fields(contract))
        allowed = required | optional
        unknown = set(output.keys()) - allowed
        return sorted(unknown)

    @staticmethod
    def enforce_required(
        task_type: TaskType,
        output: dict[str, Any],
    ) -> None:
        """Raise exception if required fields are missing.

        Args:
            task_type: Type of task
            output: Output dict to validate

        Raises:
            ValueError: If any required field is missing
        """
        missing = OutputValidator.get_missing_fields(task_type, output)
        if missing:
            raise ValueError(
                f"Missing required fields for {task_type.name}: {', '.join(missing)}"
            )

    @staticmethod
    def summary(result: ValidationResult) -> str:
        """Generate human-readable summary.

        Args:
            result: ValidationResult

        Returns:
            Formatted summary text
        """
        lines = [f"Validation: {'PASS' if result.is_valid else 'FAIL'}"]
        lines.append(f"Task Type: {result.task_type.name}")
        lines.append(f"Required Fields Present: {len(result.present_required)}")
        lines.append(f"Optional Fields Present: {len(result.present_optional)}")

        if result.missing_required:
            lines.append(f"Missing Required: {', '.join(result.missing_required)}")
        if result.unknown_fields:
            lines.append(f"Unknown Fields: {', '.join(result.unknown_fields)}")
        if result.errors:
            lines.append("Errors:")
            for err in result.errors:
                lines.append(f"  • {err}")
        if result.warnings:
            lines.append("Warnings:")
            for warn in result.warnings:
                lines.append(f"  • {warn}")

        return "\n".join(lines)
