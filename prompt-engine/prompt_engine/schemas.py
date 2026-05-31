"""JSON schema generation from OutputContract.

Deterministic conversion of OutputContract → JSON Schema 5.0.
Same contract always produces identical schema (reproducible).
"""

from .contracts import OutputContract, OutputField
from .taxonomy import TaskType


def to_json_schema(contract: OutputContract) -> dict:
    """Convert OutputContract to JSON Schema.

    Args:
        contract: OutputContract defining required/optional fields

    Returns:
        JSON Schema object that describes the contract
    """
    properties = {}
    required = []

    for field in contract.fields:
        properties[field.name] = {
            "type": "string",
            "description": field.description,
        }
        if field.required:
            required.append(field.name)

    schema = {
        "type": "object",
        "title": f"{contract.task_type.name} Output",
        "description": contract.preamble or f"Output schema for {contract.task_type.name} tasks",
        "properties": properties,
        "required": sorted(required),  # Deterministic ordering
        "additionalProperties": True,
    }

    return schema


def to_json_schema_strict(contract: OutputContract) -> dict:
    """Strict variant: forbids unknown fields.

    Args:
        contract: OutputContract

    Returns:
        JSON Schema with additionalProperties: false
    """
    schema = to_json_schema(contract)
    schema["additionalProperties"] = False
    return schema


def schema_for_task_type(task_type: TaskType) -> dict:
    """Get JSON schema for a task type.

    Args:
        task_type: TaskType enum

    Returns:
        JSON Schema for that task type's output
    """
    from .contracts import get_contract
    contract = get_contract(task_type)
    return to_json_schema(contract)


def get_field_descriptions(contract: OutputContract) -> dict[str, str]:
    """Extract field descriptions as reference.

    Args:
        contract: OutputContract

    Returns:
        Dict mapping field name → description
    """
    return {f.name: f.description for f in contract.fields}


def get_required_fields(contract: OutputContract) -> list[str]:
    """Get required field names (deterministically sorted).

    Args:
        contract: OutputContract

    Returns:
        Sorted list of required field names
    """
    return sorted([f.name for f in contract.fields if f.required])


def get_optional_fields(contract: OutputContract) -> list[str]:
    """Get optional field names (deterministically sorted).

    Args:
        contract: OutputContract

    Returns:
        Sorted list of optional field names
    """
    return sorted([f.name for f in contract.fields if not f.required])


def schema_to_prompt_text(schema: dict) -> str:
    """Format schema as human-readable prompt text.

    Args:
        schema: JSON Schema dict

    Returns:
        Formatted text for inclusion in prompts
    """
    lines = [f"SCHEMA: {schema.get('title', 'Output')}"]
    if schema.get('description'):
        lines.append(f"Description: {schema['description']}")
    lines.append("")

    props = schema.get('properties', {})
    required = set(schema.get('required', []))

    for field_name in sorted(props.keys()):
        field_def = props[field_name]
        marker = "(required)" if field_name in required else "(optional)"
        desc = field_def.get('description', 'No description')
        lines.append(f"- {field_name} {marker}: {desc}")

    return "\n".join(lines)
