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
from .decoder import (
    INTENT_IR_SCHEMA_REGISTRY,
    INTENT_IR_V0_1_TO_V1_MIGRATION_ID,
    IntentIRDecodeError,
    IntentIRMigrationResult,
    MigrationDiagnostic,
    MigrationSeverity,
    decode_intent_ir,
    decode_intent_ir_with_migration,
    migrate_intent_ir,
)
from .protocols import (
    IntentArtifactStore,
    IntentFormalizer,
    IntentGraphProjector,
    IntentNormalizer,
)
from .schema import (
    INTENT_IR_COLLECTION_SCHEMA,
    INTENT_IR_COLLECTION_SEMANTICS,
    INTENT_IR_SCHEMA_VERSION,
    LEGACY_INTENT_IR_SCHEMA_VERSION,
    CollectionSemantics,
    ControlEdgeKind,
    GroundingKind,
    IntentAction,
    IntentControlEdge,
    IntentIRDocument,
    IntentIRValidationError,
    IntentKind,
    IntentModality,
    IntentStatement,
    NodeGrounding,
    ReviewStatus,
    SourceRef,
    SourceSpan,
    StatementKind,
    validate_intent_ir,
)

__all__ = [
    "INTENT_IR_COLLECTION_SCHEMA",
    "INTENT_IR_COLLECTION_SEMANTICS",
    "INTENT_IR_SCHEMA_REGISTRY",
    "INTENT_IR_SCHEMA_VERSION",
    "INTENT_IR_V0_1_TO_V1_MIGRATION_ID",
    "LEGACY_INTENT_IR_SCHEMA_VERSION",
    "CollectionSemantics",
    "ControlEdgeKind",
    "GroundingKind",
    "IntentAction",
    "IntentArtifactStore",
    "IntentControlEdge",
    "IntentFormalizer",
    "IntentGraphProjector",
    "IntentIRDecodeError",
    "IntentIRDocument",
    "IntentIRMigrationResult",
    "IntentIRValidationError",
    "IntentKind",
    "IntentModality",
    "IntentNormalizer",
    "IntentStatement",
    "MigrationDiagnostic",
    "MigrationSeverity",
    "NodeGrounding",
    "ReviewStatus",
    "SourceRef",
    "SourceSpan",
    "StatementKind",
    "canonical_intent_ir_bytes",
    "canonical_intent_ir_json",
    "decode_intent_ir",
    "decode_intent_ir_with_migration",
    "intent_ir_sha256",
    "migrate_intent_ir",
    "validate_intent_ir",
]
