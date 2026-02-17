"""
Constraint System for Knowledge Graphs

This module provides constraint enforcement (UNIQUE, EXISTENCE, TYPE).
"""

import logging
from enum import Enum
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Callable

logger = logging.getLogger(__name__)


class ConstraintType(Enum):
    """Types of constraints."""
    UNIQUE = "unique"  # Property value must be unique
    EXISTENCE = "existence"  # Property must exist
    TYPE = "type"  # Property must have specific type
    CUSTOM = "custom"  # Custom validation function


@dataclass
class ConstraintDefinition:
    """
    Definition of a constraint.
    
    Attributes:
        name: Unique constraint name
        constraint_type: Type of constraint
        properties: Properties the constraint applies to
        label: Optional label/type filter
        options: Constraint-specific options
    """
    name: str
    constraint_type: ConstraintType
    properties: List[str] = field(default_factory=list)
    label: Optional[str] = None
    options: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ConstraintViolation:
    """
    Represents a constraint violation.
    
    Attributes:
        constraint_name: Name of violated constraint
        entity_id: ID of entity violating constraint
        message: Description of violation
    """
    constraint_name: str
    entity_id: str
    message: str


class UniqueConstraint:
    """
    Enforces uniqueness of property values.
    
    No two entities can have the same value for the constrained property.
    """
    
    def __init__(
        self,
        name: str,
        property_name: str,
        label: Optional[str] = None
    ):
        """
        Initialize unique constraint.
        
        Args:
            name: Constraint name
            property_name: Property to constrain
            label: Optional label filter
        """
        self.definition = ConstraintDefinition(
            name=name,
            constraint_type=ConstraintType.UNIQUE,
            properties=[property_name],
            label=label
        )
        self.property_name = property_name
        
        # Track values and which entities have them
        self.value_map: Dict[Any, str] = {}
    
    def validate(self, entity: Dict[str, Any]) -> Optional[ConstraintViolation]:
        """
        Validate entity against constraint.
        
        Args:
            entity: Entity to validate
            
        Returns:
            ConstraintViolation if violated, None if valid
        """
        # Check label filter
        if self.definition.label:
            if entity.get("type") != self.definition.label:
                return None
        
        # Check if property exists
        properties = entity.get("properties", {})
        if self.property_name not in properties:
            return None
        
        value = properties[self.property_name]
        entity_id = entity["id"]
        
        # Check for duplicate
        if value in self.value_map:
            existing_id = self.value_map[value]
            if existing_id != entity_id:
                return ConstraintViolation(
                    constraint_name=self.definition.name,
                    entity_id=entity_id,
                    message=f"Property '{self.property_name}' value '{value}' "
                           f"already exists on entity {existing_id}"
                )
        
        return None
    
    def register(self, entity: Dict[str, Any]):
        """
        Register entity value.
        
        Args:
            entity: Entity to register
        """
        properties = entity.get("properties", {})
        if self.property_name in properties:
            value = properties[self.property_name]
            self.value_map[value] = entity["id"]


class ExistenceConstraint:
    """
    Enforces that a property must exist.
    
    Entities of specified type must have the constrained property.
    """
    
    def __init__(
        self,
        name: str,
        property_name: str,
        label: str
    ):
        """
        Initialize existence constraint.
        
        Args:
            name: Constraint name
            property_name: Property that must exist
            label: Label/type to apply constraint to
        """
        self.definition = ConstraintDefinition(
            name=name,
            constraint_type=ConstraintType.EXISTENCE,
            properties=[property_name],
            label=label
        )
        self.property_name = property_name
    
    def validate(self, entity: Dict[str, Any]) -> Optional[ConstraintViolation]:
        """
        Validate entity against constraint.
        
        Args:
            entity: Entity to validate
            
        Returns:
            ConstraintViolation if violated, None if valid
        """
        # Check if constraint applies to this entity
        if entity.get("type") != self.definition.label:
            return None
        
        # Check if property exists
        properties = entity.get("properties", {})
        if self.property_name not in properties:
            return ConstraintViolation(
                constraint_name=self.definition.name,
                entity_id=entity["id"],
                message=f"Required property '{self.property_name}' is missing"
            )
        
        # Check if value is not None/empty
        value = properties[self.property_name]
        if value is None or value == "":
            return ConstraintViolation(
                constraint_name=self.definition.name,
                entity_id=entity["id"],
                message=f"Required property '{self.property_name}' is empty"
            )
        
        return None
    
    def register(self, entity: Dict[str, Any]):
        """Register entity with this constraint.
        
        Note: This is intentionally a no-op. Property existence constraints are
        validated lazily at check time rather than eagerly at registration time.
        This allows for flexible entity creation workflows where properties may
        be added after initial registration.
        
        Args:
            entity: Entity to register (unused)
        """
        pass  # Intentionally empty - validation is lazy


class TypeConstraint:
    """
    Enforces that a property has a specific type.
    
    Property values must match the specified Python type.
    """
    
    def __init__(
        self,
        name: str,
        property_name: str,
        expected_type: type,
        label: Optional[str] = None
    ):
        """
        Initialize type constraint.
        
        Args:
            name: Constraint name
            property_name: Property to constrain
            expected_type: Expected Python type
            label: Optional label filter
        """
        self.definition = ConstraintDefinition(
            name=name,
            constraint_type=ConstraintType.TYPE,
            properties=[property_name],
            label=label,
            options={"expected_type": expected_type.__name__}
        )
        self.property_name = property_name
        self.expected_type = expected_type
    
    def validate(self, entity: Dict[str, Any]) -> Optional[ConstraintViolation]:
        """
        Validate entity against constraint.
        
        Args:
            entity: Entity to validate
            
        Returns:
            ConstraintViolation if violated, None if valid
        """
        # Check label filter
        if self.definition.label:
            if entity.get("type") != self.definition.label:
                return None
        
        # Check if property exists
        properties = entity.get("properties", {})
        if self.property_name not in properties:
            return None
        
        value = properties[self.property_name]
        
        # Check type
        if not isinstance(value, self.expected_type):
            return ConstraintViolation(
                constraint_name=self.definition.name,
                entity_id=entity["id"],
                message=f"Property '{self.property_name}' has type {type(value).__name__}, "
                       f"expected {self.expected_type.__name__}"
            )
        
        return None
    
    def register(self, entity: Dict[str, Any]):
        """Register entity with this constraint.
        
        Note: This is intentionally a no-op. Type constraints are validated
        lazily at check time rather than eagerly at registration time. This
        allows for flexible entity creation and modification workflows.
        
        Args:
            entity: Entity to register (unused)
        """
        pass  # Intentionally empty - validation is lazy


class CustomConstraint:
    """
    Custom validation constraint using a function.
    """
    
    def __init__(
        self,
        name: str,
        validation_fn: Callable[[Dict[str, Any]], Optional[str]],
        label: Optional[str] = None
    ):
        """
        Initialize custom constraint.
        
        Args:
            name: Constraint name
            validation_fn: Function that takes entity and returns error message or None
            label: Optional label filter
        """
        self.definition = ConstraintDefinition(
            name=name,
            constraint_type=ConstraintType.CUSTOM,
            label=label
        )
        self.validation_fn = validation_fn
    
    def validate(self, entity: Dict[str, Any]) -> Optional[ConstraintViolation]:
        """
        Validate entity against constraint.
        
        Args:
            entity: Entity to validate
            
        Returns:
            ConstraintViolation if violated, None if valid
        """
        # Check label filter
        if self.definition.label:
            if entity.get("type") != self.definition.label:
                return None
        
        # Run custom validation
        error_msg = self.validation_fn(entity)
        
        if error_msg:
            return ConstraintViolation(
                constraint_name=self.definition.name,
                entity_id=entity["id"],
                message=error_msg
            )
        
        return None
    
    def register(self, entity: Dict[str, Any]):
        """Register entity with this constraint.
        
        Note: This is intentionally a no-op. Custom constraints are validated
        lazily at check time rather than eagerly at registration time. This
        allows constraints to be evaluated in context with the latest entity state.
        
        Args:
            entity: Entity to register (unused)
        """
        pass  # Intentionally empty - validation is lazy


class ConstraintManager:
    """
    Manages constraints for the knowledge graph.
    """
    
    def __init__(self):
        """Initialize constraint manager."""
        self.constraints: Dict[str, Any] = {}
    
    def add_unique_constraint(
        self,
        property_name: str,
        label: Optional[str] = None,
        name: Optional[str] = None
    ) -> str:
        """
        Add unique constraint.
        
        Args:
            property_name: Property to constrain
            label: Optional label filter
            name: Optional constraint name
            
        Returns:
            Constraint name
        """
        if name is None:
            name = f"unique_{property_name}"
            if label:
                name += f"_{label}"
        
        constraint = UniqueConstraint(name, property_name, label)
        self.constraints[name] = constraint
        logger.info(f"Added unique constraint: {name}")
        return name
    
    def add_existence_constraint(
        self,
        property_name: str,
        label: str,
        name: Optional[str] = None
    ) -> str:
        """
        Add existence constraint.
        
        Args:
            property_name: Property that must exist
            label: Label to apply constraint to
            name: Optional constraint name
            
        Returns:
            Constraint name
        """
        if name is None:
            name = f"exists_{property_name}_{label}"
        
        constraint = ExistenceConstraint(name, property_name, label)
        self.constraints[name] = constraint
        logger.info(f"Added existence constraint: {name}")
        return name
    
    def add_type_constraint(
        self,
        property_name: str,
        expected_type: type,
        label: Optional[str] = None,
        name: Optional[str] = None
    ) -> str:
        """
        Add type constraint.
        
        Args:
            property_name: Property to constrain
            expected_type: Expected type
            label: Optional label filter
            name: Optional constraint name
            
        Returns:
            Constraint name
        """
        if name is None:
            name = f"type_{property_name}_{expected_type.__name__}"
            if label:
                name += f"_{label}"
        
        constraint = TypeConstraint(name, property_name, expected_type, label)
        self.constraints[name] = constraint
        logger.info(f"Added type constraint: {name}")
        return name
    
    def add_custom_constraint(
        self,
        name: str,
        validation_fn: Callable[[Dict[str, Any]], Optional[str]],
        label: Optional[str] = None
    ) -> str:
        """
        Add custom constraint.
        
        Args:
            name: Constraint name
            validation_fn: Validation function
            label: Optional label filter
            
        Returns:
            Constraint name
        """
        constraint = CustomConstraint(name, validation_fn, label)
        self.constraints[name] = constraint
        logger.info(f"Added custom constraint: {name}")
        return name
    
    def remove_constraint(self, name: str) -> bool:
        """
        Remove a constraint.
        
        Args:
            name: Constraint name
            
        Returns:
            True if removed, False if not found
        """
        if name in self.constraints:
            del self.constraints[name]
            logger.info(f"Removed constraint: {name}")
            return True
        return False
    
    def validate(self, entity: Dict[str, Any]) -> List[ConstraintViolation]:
        """
        Validate entity against all constraints.
        
        Args:
            entity: Entity to validate
            
        Returns:
            List of constraint violations
        """
        violations = []
        
        for constraint in self.constraints.values():
            violation = constraint.validate(entity)
            if violation:
                violations.append(violation)
        
        return violations
    
    def register(self, entity: Dict[str, Any]):
        """
        Register entity with all constraints.
        
        Args:
            entity: Entity to register
        """
        for constraint in self.constraints.values():
            constraint.register(entity)
    
    def list_constraints(self) -> List[ConstraintDefinition]:
        """
        List all constraints.
        
        Returns:
            List of constraint definitions
        """
        return [c.definition for c in self.constraints.values()]


__all__ = [
    "ConstraintType",
    "ConstraintDefinition",
    "ConstraintViolation",
    "UniqueConstraint",
    "ExistenceConstraint",
    "TypeConstraint",
    "CustomConstraint",
    "ConstraintManager",
]
