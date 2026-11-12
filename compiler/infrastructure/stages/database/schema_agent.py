"""Apply entity changes while preserving the accepted database schema."""

from copy import deepcopy

from infrastructure.stages.database.schema import apply_patch


FIELD_PROPERTIES = {
    "description": {"type": "string"},
    "type": {"type": "string", "enum": ["string", "integer", "number", "boolean", "date", "datetime", "uuid", "json"]},
    "nullable": {"type": "boolean"},
    "primary_key": {"type": "boolean"},
    "unique": {"type": "boolean"},
    "references": {"type": ["string", "null"]},
    "constraints": {"type": "array", "items": {"type": "string"}},
}

# ==================================
#  Tools for constructing db schema
# ==================================

def create_entity(schema: dict, name: str, entity: dict) -> None:
    """Create one complete entity, rejecting names that already exist."""
    if name in schema["entities"]:
        raise ValueError(f"Entity already exists: {name}; use update_entity")
    if not isinstance(entity.get("description"), str) or not isinstance(entity.get("fields"), dict):
        raise ValueError("A new entity requires description and fields")
    for field, definition in entity["fields"].items():
        missing = set(FIELD_PROPERTIES) - definition.keys()
        if missing:
            raise ValueError(f"New field {name}.{field} is missing properties: {sorted(missing)}")
    schema["entities"][name] = deepcopy(entity)


def update_entity(schema: dict, name: str, entity: dict) -> None:
    """Merge supplied properties and fields, preserving omitted definitions."""
    if name not in schema["entities"]:
        raise ValueError(f"Unknown entity: {name}; use create_entity")
    for field, definition in entity.get("fields", {}).items():
        if field not in schema["entities"][name]["fields"]:
            missing = set(FIELD_PROPERTIES) - definition.keys()
            if missing:
                raise ValueError(f"New field {name}.{field} is missing properties: {sorted(missing)}")
    updated = apply_patch(schema, {"entities": {name: entity}})
    schema["entities"][name] = updated["entities"][name]
