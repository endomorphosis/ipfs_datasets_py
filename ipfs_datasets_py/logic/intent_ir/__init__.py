"""Intent IR contracts and source adapters.

The package is intentionally dependency-light.  It defines the stable boundary
between untrusted skill corpora, GraphRAG projections, and formal-logic
compilers without selecting a model backend or executing source instructions.
"""

from .canonicalize import (
    canonical_intent_ir_bytes,
    canonical_intent_ir_json,
    intent_ir_sha256,
)
from .protocols import (
    IntentArtifactStore,
    IntentFormalizer,
    IntentGraphProjector,
    IntentNormalizer,
)
from .schema import (
    INTENT_IR_SCHEMA_VERSION,
    ControlEdgeKind,
    IntentAction,
    IntentControlEdge,
    IntentIRDocument,
    IntentIRValidationError,
    IntentKind,
    IntentModality,
    IntentStatement,
    ReviewStatus,
    SourceRef,
    SourceSpan,
    StatementKind,
    validate_intent_ir,
)

__all__ = [
    "INTENT_IR_SCHEMA_VERSION",
    "ControlEdgeKind",
    "IntentAction",
    "IntentArtifactStore",
    "IntentControlEdge",
    "IntentFormalizer",
    "IntentGraphProjector",
    "IntentIRDocument",
    "IntentIRValidationError",
    "IntentKind",
    "IntentModality",
    "IntentNormalizer",
    "IntentStatement",
    "ReviewStatus",
    "SourceRef",
    "SourceSpan",
    "StatementKind",
    "canonical_intent_ir_bytes",
    "canonical_intent_ir_json",
    "intent_ir_sha256",
    "validate_intent_ir",
]
