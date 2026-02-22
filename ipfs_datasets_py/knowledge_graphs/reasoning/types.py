"""
Data types for cross-document reasoning.

This module defines the core data structures used in the cross-document
reasoning process:

- ``InformationRelationType`` – enum of relation categories between documents
- ``DocumentNode`` – a document or text chunk in the reasoning graph
- ``EntityMediatedConnection`` – an entity-mediated link between two documents
- ``CrossDocReasoning`` – container for a complete reasoning process

These types are re-exported from :mod:`cross_document_reasoning` for backward
compatibility, so existing code that imports them from there continues to work.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

try:
    import numpy as np
    _NpNdarray = np.ndarray
except ImportError:  # numpy is optional — type hints remain as strings
    np = None  # type: ignore[assignment]
    _NpNdarray = None  # type: ignore[assignment,misc]


class InformationRelationType(Enum):
    """Types of relations between pieces of information across documents."""

    COMPLEMENTARY = "complementary"   # Information that adds to or extends other information
    SUPPORTING = "supporting"         # Information that confirms or backs up other information
    CONTRADICTING = "contradicting"   # Information that conflicts with other information
    ELABORATING = "elaborating"       # Information that provides more detail on other information
    PREREQUISITE = "prerequisite"     # Information needed to understand other information
    CONSEQUENCE = "consequence"       # Information that follows from other information
    ALTERNATIVE = "alternative"       # Information that provides a different perspective
    UNCLEAR = "unclear"               # Relationship cannot be determined


@dataclass
class DocumentNode:
    """Represents a document or chunk of text in the reasoning process."""

    id: str
    content: str
    source: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    vector: Optional[np.ndarray] = None
    relevance_score: float = 0.0
    entities: List[str] = field(default_factory=list)


@dataclass
class EntityMediatedConnection:
    """Represents a connection between documents mediated by an entity."""

    entity_id: str
    entity_name: str
    entity_type: str
    source_doc_id: str
    target_doc_id: str
    relation_type: InformationRelationType
    connection_strength: float
    context: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CrossDocReasoning:
    """Represents a cross-document reasoning process."""

    id: str
    query: str
    query_embedding: Optional[np.ndarray] = None
    documents: List[DocumentNode] = field(default_factory=list)
    entity_connections: List[EntityMediatedConnection] = field(default_factory=list)
    traversal_paths: List[List[str]] = field(default_factory=list)
    reasoning_depth: str = "moderate"  # "basic", "moderate", or "deep"
    answer: Optional[str] = None
    confidence: float = 0.0
    reasoning_trace_id: Optional[str] = None


__all__ = [
    "InformationRelationType",
    "DocumentNode",
    "EntityMediatedConnection",
    "CrossDocReasoning",
]
