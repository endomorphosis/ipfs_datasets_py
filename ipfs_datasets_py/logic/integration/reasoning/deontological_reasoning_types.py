"""
Deontological Reasoning Types

This module defines the type definitions, dataclasses, and enumerations
used by the Deontological Reasoning system.

Extracted from deontological_reasoning.py to improve modularity and
prevent circular dependencies.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class DeonticModality(Enum):
    """
    Types of deontic modalities in legal/ethical reasoning.

    Attributes:
        OBLIGATION: Mandatory requirements (must, shall, required to)
        PERMISSION: Allowed actions (may, can, allowed to)
        PROHIBITION: Forbidden actions (must not, cannot, forbidden to)
        CONDITIONAL: Context-dependent obligations (if/then statements)
        EXCEPTION: Rules with exceptions (unless, except when)
        
    Example:
        >>> modality = DeonticModality.OBLIGATION
        >>> modality.value
        'obligation'
    """
    OBLIGATION = "obligation"      # must, shall, required to
    PERMISSION = "permission"      # may, can, allowed to
    PROHIBITION = "prohibition"    # must not, cannot, forbidden to
    CONDITIONAL = "conditional"    # if/then obligations
    EXCEPTION = "exception"        # unless, except when


class ConflictType(Enum):
    """
    Types of deontic conflicts that can be detected.

    Attributes:
        DIRECT_CONTRADICTION: Direct logical contradictions (X must do A, X must not do A)
        PERMISSION_PROHIBITION: Permission conflicts (X can do A, X cannot do A)
        OBLIGATION_PROHIBITION: Obligation vs prohibition conflicts (X must do A, X must not do A)
        CONDITIONAL_CONFLICT: Conflicting conditional rules (If P then X must A, If P then X must not A)
        JURISDICTIONAL: Conflicts between different legal jurisdictions
        TEMPORAL: Conflicts arising from rules changing over time
        HIERARCHICAL: Conflicts between different levels of authority
        
    Example:
        >>> conflict = ConflictType.DIRECT_CONTRADICTION
        >>> conflict.value
        'direct_contradiction'
    """
    DIRECT_CONTRADICTION = "direct_contradiction"      # X must do A, X must not do A
    PERMISSION_PROHIBITION = "permission_prohibition"  # X can do A, X cannot do A
    OBLIGATION_PROHIBITION = "obligation_prohibition"  # X must do A, X must not do A
    CONDITIONAL_CONFLICT = "conditional_conflict"      # If P then X must A, If P then X must not A
    JURISDICTIONAL = "jurisdictional"                  # Different rules in different contexts
    TEMPORAL = "temporal"                              # Rules change over time
    HIERARCHICAL = "hierarchical"                      # Higher/lower authority conflicts


@dataclass
class DeonticStatement:
    """
    Represents a deontic statement with modality, entity, and action.

    Attributes:
        id: Unique identifier for the statement
        entity: The entity/subject the statement applies to
        action: The action being regulated by the statement
        modality: Type of deontic modality (obligation, permission, etc.)
        source_document: Document identifier where statement was found
        source_text: Original text of the extracted statement
        confidence: Confidence score for extraction accuracy (0.0-1.0)
        context: Additional contextual information (jurisdiction, date, etc.)
        conditions: List of conditions that apply to the statement
        exceptions: List of exceptions to the statement
        document_id: Backwards-compatible alias for source_document
        
    Example:
        >>> stmt = DeonticStatement(
        ...     id="stmt-1",
        ...     entity="citizen",
        ...     action="pay taxes",
        ...     modality=DeonticModality.OBLIGATION,
        ...     source_text="All citizens must pay taxes"
        ... )
    """
    id: str
    entity: str                    # Who the statement applies to
    action: str                    # What action is being regulated
    modality: DeonticModality      # Type of deontic modality
    source_document: str = ""       # Document where statement was found
    source_text: str = ""           # Original text of the statement
    confidence: float = 1.0         # Confidence in extraction (0-1)
    context: Dict[str, Any] = field(default_factory=dict)  # Additional context
    document_id: Optional[str] = None  # Backwards-compatible alias
    conditions: List[str] = field(default_factory=list)  # Conditions for the statement
    exceptions: List[str] = field(default_factory=list)  # Exceptions to the statement

    def __post_init__(self) -> None:
        """Normalize entity and action text."""
        if isinstance(self.modality, str):
            normalized = self.modality.strip()
            if normalized in DeonticModality.__members__:
                self.modality = DeonticModality[normalized]
            else:
                lowered = normalized.lower()
                for modality in DeonticModality:
                    if modality.value == lowered:
                        self.modality = modality
                        break
                else:
                    raise ValueError(f"Unknown modality: {self.modality}")
        
        self.entity = self.entity.lower().strip()
        self.action = self.action.lower().strip()


@dataclass
class DeonticConflict:
    """
    Represents a detected conflict between deontic statements.

    Attributes:
        statement1: First conflicting deontic statement
        statement2: Second conflicting deontic statement
        conflict_type: Type of conflict detected
        severity: Severity level of the conflict (high, medium, low)
        explanation: Human-readable explanation of the conflict
        resolution_suggestions: Suggested ways to resolve the conflict
        context_overlap: Degree of context overlap between statements (0.0-1.0)
        
    Example:
        >>> conflict = DeonticConflict(
        ...     statement1=stmt1,
        ...     statement2=stmt2,
        ...     conflict_type=ConflictType.DIRECT_CONTRADICTION,
        ...     severity="high",
        ...     explanation="Direct contradiction detected"
        ... )
    """
    statement1: DeonticStatement
    statement2: DeonticStatement
    conflict_type: ConflictType
    severity: str = "medium"  # high, medium, low
    explanation: str = ""
    resolution_suggestions: List[str] = field(default_factory=list)
    context_overlap: float = 0.0  # 0-1, how much context overlaps
    id: str = ""  # Optional unique identifier for the conflict


# Export all types
__all__ = [
    'DeonticModality',
    'ConflictType',
    'DeonticStatement',
    'DeonticConflict',
]
