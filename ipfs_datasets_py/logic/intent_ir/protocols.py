"""Backend-neutral ports for the Intent IR pipeline.

Implementations may use the existing GraphRAG, IPLD, and modal autoencoder
packages.  Keeping those dependencies behind protocols prevents the schema
layer from importing heavyweight or optional model runtimes.
"""

from __future__ import annotations

from typing import Any, Mapping, Protocol, runtime_checkable

from .schema import IntentIRDocument


@runtime_checkable
class IntentNormalizer(Protocol):
    """Normalize one source record into validated Intent IR."""

    def normalize(self, record: Any) -> IntentIRDocument:
        """Return a source-grounded, non-executable Intent IR document."""


@runtime_checkable
class IntentGraphProjector(Protocol):
    """Project Intent IR into a bounded GraphRAG artifact."""

    def project(self, document: IntentIRDocument) -> Mapping[str, Any]:
        """Return a versioned graph projection bound to the Intent IR digest."""


@runtime_checkable
class IntentFormalizer(Protocol):
    """Compile Intent IR plus optional graph context into formal logic."""

    def formalize(
        self,
        document: IntentIRDocument,
        *,
        graph_projection: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        """Return a versioned logic projection and explicit diagnostics."""


@runtime_checkable
class IntentArtifactStore(Protocol):
    """Store canonical pipeline artifacts without embedding their bodies."""

    def put_bytes(self, payload: bytes, *, media_type: str) -> str:
        """Return a CID or other immutable content address."""


__all__ = [
    "IntentArtifactStore",
    "IntentFormalizer",
    "IntentGraphProjector",
    "IntentNormalizer",
]
