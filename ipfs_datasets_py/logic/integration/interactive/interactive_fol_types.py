"""
Interactive FOL Constructor Types

This module defines the type definitions, dataclasses, and data structures
used by the Interactive FOL Constructor system.

Extracted from interactive_fol_constructor.py to improve modularity and
prevent circular dependencies.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional

# Local imports for type hints
from ..bridges.symbolic_fol_bridge import LogicalComponents


@dataclass
class StatementRecord:
    """
    Record of a single statement in the interactive session.
    
    This dataclass stores all information about a statement added to
    the FOL construction session, including its text, logical analysis,
    and metadata.
    
    Attributes:
        id: Unique identifier for the statement
        text: Original natural language text
        timestamp: When the statement was added
        logical_components: Analyzed logical structure (quantifiers, predicates, etc.)
        fol_formula: Generated First-Order Logic formula
        confidence: Confidence score (0.0-1.0) for the conversion
        is_consistent: Whether the statement is consistent with the session
        dependencies: List of statement IDs this depends on
        tags: Categorization tags for the statement
    
    Example:
        >>> record = StatementRecord(
        ...     id="stmt-123",
        ...     text="All cats are animals",
        ...     timestamp=datetime.now(),
        ...     fol_formula="∀x(Cat(x) → Animal(x))",
        ...     confidence=0.95
        ... )
    """
    id: str
    text: str
    timestamp: datetime
    logical_components: Optional[LogicalComponents] = None
    fol_formula: Optional[str] = None
    confidence: float = 0.0
    is_consistent: Optional[bool] = None
    dependencies: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)


@dataclass
class SessionMetadata:
    """
    Metadata for an interactive FOL construction session.
    
    This dataclass tracks overall session statistics and metadata,
    providing insights into the quality and state of the logic being
    constructed.
    
    Attributes:
        session_id: Unique identifier for the session
        created_at: Timestamp of session creation
        last_modified: Timestamp of last modification
        total_statements: Total number of statements added
        consistent_statements: Number of consistent statements
        inconsistent_statements: Number of inconsistent statements
        average_confidence: Average confidence across all statements
        domain: Knowledge domain (e.g., "mathematics", "legal", "general")
        description: Optional human-readable description
        tags: Categorization tags for the session
    
    Example:
        >>> metadata = SessionMetadata(
        ...     session_id="session-abc",
        ...     created_at=datetime.now(),
        ...     last_modified=datetime.now(),
        ...     total_statements=10,
        ...     consistent_statements=9,
        ...     inconsistent_statements=1,
        ...     average_confidence=0.87,
        ...     domain="animals"
        ... )
    """
    session_id: str
    created_at: datetime
    last_modified: datetime
    total_statements: int
    consistent_statements: int
    inconsistent_statements: int
    average_confidence: float
    domain: str = "general"
    description: str = ""
    tags: List[str] = field(default_factory=list)
