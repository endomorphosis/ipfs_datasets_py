"""Public storage-neutral semantic-state producer API.

Importing this package only exposes the closed facade.  It does not create a
store, open a network connection, start a scheduler, or perform persistence.
"""

from ipfs_datasets_py.logic.software_contracts.semantic_state.api import (
    SEMANTIC_STATE_API_SCHEMA,
    SEMANTIC_STATE_BLOCK_READER_INTERFACE,
    SEMANTIC_STATE_PRODUCER_INTERFACE,
    SEMANTIC_STATE_VIEW_INTERFACE,
    CorruptBlockError,
    MissingBlockError,
    SemanticStateApiError,
    SemanticStateBlockReader,
    SemanticStateView,
    UnknownSymbolError,
    VerifiedSemanticStateView,
    assess_capsule_freshness,
    build_semantic_state,
    compare_test_selection_oracle,
    compile_semantic_capsule,
    extend_semantic_invalidation,
    open_semantic_state,
    read_required_source,
    select_tests_and_proofs,
    verify_semantic_state_bundle,
    view_semantic_state_bundle,
)
from ipfs_datasets_py.logic.software_contracts.semantic_state.models import (
    SemanticCapsule,
    SemanticStateBundle,
    SemanticStateRoot,
    SymbolMerkleNode,
)

__all__ = [
    # Interface constants
    "SEMANTIC_STATE_API_SCHEMA",
    "SEMANTIC_STATE_BLOCK_READER_INTERFACE",
    "SEMANTIC_STATE_PRODUCER_INTERFACE",
    "SEMANTIC_STATE_VIEW_INTERFACE",
    # Protocols / view
    "SemanticStateBlockReader",
    "SemanticStateView",
    "VerifiedSemanticStateView",
    # Errors
    "SemanticStateApiError",
    "MissingBlockError",
    "CorruptBlockError",
    "UnknownSymbolError",
    # Durable value types commonly bound by the facade
    "SemanticStateBundle",
    "SemanticStateRoot",
    "SemanticCapsule",
    "SymbolMerkleNode",
    # Core assembly
    "build_semantic_state",
    "verify_semantic_state_bundle",
    "open_semantic_state",
    "view_semantic_state_bundle",
    # Capsule / freshness / source
    "compile_semantic_capsule",
    "assess_capsule_freshness",
    "read_required_source",
    # Invalidation / selection / oracle
    "extend_semantic_invalidation",
    "select_tests_and_proofs",
    "compare_test_selection_oracle",
]
