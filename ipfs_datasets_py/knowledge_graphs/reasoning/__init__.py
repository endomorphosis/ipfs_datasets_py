"""
Cross-document reasoning subpackage.

Modules:
- types: Core data types (InformationRelationType, DocumentNode, etc.)
- helpers: Traversal and LLM helper mixin (ReasoningHelpersMixin)
- cross_document: Main CrossDocumentReasoner class
"""

from .types import (
    InformationRelationType,
    DocumentNode,
    EntityMediatedConnection,
    CrossDocReasoning,
)

from .helpers import ReasoningHelpersMixin

from .cross_document import CrossDocumentReasoner

__all__ = [
    "InformationRelationType",
    "DocumentNode",
    "EntityMediatedConnection",
    "CrossDocReasoning",
    "ReasoningHelpersMixin",
    "CrossDocumentReasoner",
]
