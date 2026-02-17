# Knowledge Graph Constraints

Constraint system for enforcing data integrity and validation rules on knowledge graph entities and relationships.

## Overview

The constraints module provides a flexible framework for defining and enforcing validation rules on knowledge graph data. Constraints can validate property existence, types, uniqueness, and custom business logic.

## Key Features

- **Property Existence** - Require specific properties on entities
- **Type Validation** - Enforce property type constraints
- **Uniqueness** - Ensure property values are unique across entities
- **Custom Constraints** - Define domain-specific validation logic
- **Lazy Validation** - Constraints checked at validation time, not registration time
- **Flexible Management** - Add, remove, and query constraints dynamically

## Core Classes

### `ConstraintDefinition`
Defines a constraint with name, type, target, and parameters.

```python
from ipfs_datasets_py.knowledge_graphs.constraints import ConstraintDefinition

constraint = ConstraintDefinition(
    name="email_required",
    constraint_type="PROPERTY_EXISTENCE",
    entity_type="User",
    property_name="email"
)
```

### `PropertyExistenceConstraint`
Ensures required properties are present and non-empty.

```python
from ipfs_datasets_py.knowledge_graphs.constraints import PropertyExistenceConstraint

constraint = PropertyExistenceConstraint(definition)
violation = constraint.check(entity)  # Returns None if valid, ConstraintViolation if invalid
```

### `TypeConstraint`
Validates that properties have the expected Python type.

```python
from ipfs_datasets_py.knowledge_graphs.constraints import TypeConstraint

# Ensure 'age' property is an integer
constraint = TypeConstraint(definition, expected_type=int)
```

### `CustomConstraint`
Applies custom validation logic via a function.

```python
from ipfs_datasets_py.knowledge_graphs.constraints import CustomConstraint

def validate_email(entity):
    email = entity['properties'].get('email', '')
    if '@' not in email:
        return "Email must contain '@' symbol"
    return None

constraint = CustomConstraint(definition, validator_func=validate_email)
```

### `ConstraintManager`
Central manager for adding, removing, and applying constraints.

```python
from ipfs_datasets_py.knowledge_graphs.constraints import ConstraintManager

manager = ConstraintManager()

# Add constraint
manager.add_constraint(constraint)

# Validate entity
violations = manager.validate_entity(entity)
for violation in violations:
    print(f"Constraint '{violation.constraint_name}' violated: {violation.message}")

# Remove constraint
manager.remove_constraint("email_required")
```

## Usage Examples

### Example 1: Basic Property Validation

```python
from ipfs_datasets_py.knowledge_graphs.constraints import (
    ConstraintManager,
    ConstraintDefinition,
    PropertyExistenceConstraint
)

# Create manager
manager = ConstraintManager()

# Define constraint: Users must have an email
email_def = ConstraintDefinition(
    name="user_email_required",
    constraint_type="PROPERTY_EXISTENCE",
    entity_type="User",
    property_name="email"
)
email_constraint = PropertyExistenceConstraint(email_def)
manager.add_constraint(email_constraint)

# Validate entity
user = {
    "id": "user123",
    "type": "User",
    "properties": {"name": "Alice"}
}

violations = manager.validate_entity(user)
if violations:
    print(f"Validation failed: {violations[0].message}")
    # Output: "Required property 'email' is missing"
```

### Example 2: Type Constraints

```python
from ipfs_datasets_py.knowledge_graphs.constraints import TypeConstraint

# Age must be an integer
age_def = ConstraintDefinition(
    name="age_type_check",
    constraint_type="TYPE",
    entity_type="User",
    property_name="age"
)
age_constraint = TypeConstraint(age_def, expected_type=int)
manager.add_constraint(age_constraint)

# Validate
user = {
    "id": "user456",
    "type": "User",
    "properties": {"email": "bob@example.com", "age": "25"}  # String, not int!
}

violations = manager.validate_entity(user)
if violations:
    print(violations[0].message)
    # Output: "Property 'age' has type str, expected int"
```

### Example 3: Custom Business Logic

```python
from ipfs_datasets_py.knowledge_graphs.constraints import CustomConstraint

def validate_age_range(entity):
    """Ensure age is between 0 and 150."""
    age = entity['properties'].get('age')
    if age is not None:
        if not (0 <= age <= 150):
            return f"Age {age} is out of valid range (0-150)"
    return None

age_range_def = ConstraintDefinition(
    name="age_range_check",
    constraint_type="CUSTOM",
    entity_type="User",
    property_name="age"
)
age_range_constraint = CustomConstraint(age_range_def, validator_func=validate_age_range)
manager.add_constraint(age_range_constraint)
```

## Design Patterns

### Lazy Validation

Constraints use **lazy validation** - they are not checked at entity registration time, but only when explicitly validated via `validate_entity()` or `validate_all()`. This allows flexible entity creation workflows:

```python
# Create entity with incomplete data
entity = {"id": "temp123", "type": "User", "properties": {}}

# Register with constraint manager (no validation yet)
constraint.register(entity)  # No-op

# Add properties gradually
entity["properties"]["email"] = "user@example.com"
entity["properties"]["age"] = 30

# Validate when ready
violations = manager.validate_entity(entity)
```

### Constraint Composition

Multiple constraints can be applied to the same entity type:

```python
manager.add_constraint(email_required)
manager.add_constraint(age_type_check)
manager.add_constraint(age_range_check)

# All constraints checked together
violations = manager.validate_entity(user)
```

## API Reference

### ConstraintViolation

Returned when a constraint is violated:

```python
@dataclass
class ConstraintViolation:
    constraint_name: str  # Name of violated constraint
    entity_id: str        # ID of entity that violated constraint
    message: str          # Human-readable error message
```

### ConstraintManager Methods

- `add_constraint(constraint)` - Add a constraint to the manager
- `remove_constraint(constraint_name)` - Remove a constraint by name
- `get_constraint(constraint_name)` - Retrieve a constraint by name
- `get_constraints_for_entity_type(entity_type)` - Get all constraints for an entity type
- `validate_entity(entity)` - Validate a single entity, returns list of violations
- `validate_all(entities)` - Validate multiple entities, returns dict of violations

## See Also

- [Knowledge Graph Core](../core/README.md) - Core knowledge graph functionality
- [Query Engine](../query/README.md) - Query execution with constraint checking
- [Migration Guide](../migration/README.md) - Schema migration preserves constraints

## Future Enhancements

- **Relationship Constraints** - Validate relationships between entities
- **Cardinality Constraints** - Enforce min/max relationship counts
- **Cross-Entity Constraints** - Validate relationships across multiple entities
- **Constraint Dependencies** - Define prerequisite constraints
- **Async Validation** - Support for async validator functions
