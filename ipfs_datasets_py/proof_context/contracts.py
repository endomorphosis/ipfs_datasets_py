"""Closed v0.1 contracts for the datasets proof-context port."""

from __future__ import annotations

from typing import Final

PORT_SCHEMA: Final[str] = "ipfs-datasets.proof-context.v0.1"
PORT_INTERFACE: Final[str] = "DatasetsProofContextProvider@0.1"
PRODUCER_REPOSITORY: Final[str] = "endomorphosis/ipfs_datasets_py"

STATUSES: Final[tuple[str, ...]] = (
    "fresh",
    "stale",
    "opaque",
    "insufficient",
    "unavailable",
    "sufficient",
)

CANONICAL_CAPABILITIES: Final[tuple[tuple[str, str, str], ...]] = (
    (
        "Incremental Semantic Index",
        "ipfs_datasets_py.logic.software_contracts.semantic_index.index",
        "IncrementalSemanticIndex",
    ),
    (
        "Semantic Capsule Compiler",
        "ipfs_datasets_py.logic.software_contracts.semantic_state.capsules",
        "compile_semantic_capsule",
    ),
    (
        "ContextPack View",
        "ipfs_datasets_py.logic.software_contracts.semantic_governor.sufficiency",
        "ContextPackView",
    ),
    (
        "Context sufficiency",
        "ipfs_datasets_py.logic.software_contracts.semantic_governor.sufficiency",
        "evaluate_context_sufficiency",
    ),
    (
        "Semantic state assembly",
        "ipfs_datasets_py.logic.software_contracts.semantic_state.api",
        "build_semantic_state",
    ),
)


class ProofContextError(RuntimeError):
    """Base fail-closed error for the datasets v0.1 port."""

    reason: str = "invalid"

    def __init__(self, message: str, *, reason: str | None = None) -> None:
        super().__init__(message)
        if reason is not None:
            self.reason = reason


class StaleContextError(ProofContextError):
    reason = "stale"


class UnavailableContextError(ProofContextError):
    reason = "unavailable"


class OpaqueSourceRequiredError(ProofContextError):
    reason = "opaque"


class InsufficientContextError(ProofContextError):
    reason = "insufficient"


class CompatibilityError(ProofContextError):
    reason = "incompatible"
