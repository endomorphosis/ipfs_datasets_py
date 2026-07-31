"""Immutable snapshot store interfaces for monetary-flow graphs.

Stores never mutate a published :class:`GraphSnapshot`.  Updates are new
snapshot identities.  Content identity is deterministic and content-addressed.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from .model import (
    CryptoFlowValidationError,
    GraphSnapshot,
    merge_provider_ids,
)


class SnapshotStoreError(LookupError):
    """Raised when a snapshot cannot be found or a write violates immutability."""


@runtime_checkable
class GraphSnapshotStore(Protocol):
    """Protocol for immutable GraphSnapshot persistence."""

    def put(self, snapshot: GraphSnapshot, *, overwrite: bool = False) -> str:
        """Persist a snapshot; returns the store key (snapshot_id)."""
        ...

    def get(self, snapshot_id: str) -> GraphSnapshot:
        """Fetch a snapshot by id; fails closed if missing."""
        ...

    def get_by_digest(self, graph_digest: str) -> GraphSnapshot:
        """Fetch the first snapshot whose graph digest matches."""
        ...

    def list_ids(self) -> tuple[str, ...]:
        """Return sorted snapshot identifiers."""
        ...

    def contains(self, snapshot_id: str) -> bool:
        ...


@dataclass
class InMemoryGraphSnapshotStore:
    """Process-local immutable snapshot store.

    Stored snapshots are deep-copied via ``to_dict``/``from_dict`` so callers
    cannot mutate store contents through shared object graphs.  Overwriting an
    existing ``snapshot_id`` fails closed unless ``overwrite=True``.
    """

    _by_id: dict[str, GraphSnapshot] = field(default_factory=dict, init=False, repr=False)
    _by_digest: dict[str, str] = field(default_factory=dict, init=False, repr=False)

    def put(self, snapshot: GraphSnapshot, *, overwrite: bool = False) -> str:
        if not isinstance(snapshot, GraphSnapshot):
            raise CryptoFlowValidationError("snapshot must be a GraphSnapshot")
        if snapshot.snapshot_id in self._by_id and not overwrite:
            raise SnapshotStoreError(
                f"snapshot_id already present and immutable: {snapshot.snapshot_id}"
            )
        # Materialize an independent copy for store isolation.
        stored = GraphSnapshot.from_dict(snapshot.to_dict())
        if stored.identity.digest != snapshot.identity.digest:
            raise CryptoFlowValidationError(
                "snapshot round-trip changed content identity"
            )
        self._by_id[stored.snapshot_id] = stored
        self._by_digest[stored.graph_digest] = stored.snapshot_id
        return stored.snapshot_id

    def get(self, snapshot_id: str) -> GraphSnapshot:
        if not isinstance(snapshot_id, str) or not snapshot_id.strip():
            raise CryptoFlowValidationError("snapshot_id must be a non-empty string")
        try:
            stored = self._by_id[snapshot_id]
        except KeyError as exc:
            raise SnapshotStoreError(f"snapshot not found: {snapshot_id}") from exc
        # Return an independent copy.
        return GraphSnapshot.from_dict(stored.to_dict())

    def get_by_digest(self, graph_digest: str) -> GraphSnapshot:
        if not isinstance(graph_digest, str) or not graph_digest.strip():
            raise CryptoFlowValidationError("graph_digest must be a non-empty string")
        try:
            snapshot_id = self._by_digest[graph_digest]
        except KeyError as exc:
            raise SnapshotStoreError(
                f"no snapshot for graph_digest: {graph_digest}"
            ) from exc
        return self.get(snapshot_id)

    def list_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._by_id))

    def contains(self, snapshot_id: str) -> bool:
        return snapshot_id in self._by_id

    def providers_union(self) -> tuple[str, ...]:
        """Union of covered providers across all stored snapshots."""
        groups = [s.covered_providers for s in self._by_id.values()]
        return merge_provider_ids(*groups)

    def completeness_index(self) -> Mapping[str, str]:
        """Map snapshot_id -> completeness status value."""
        return {
            sid: snap.completeness.value for sid, snap in sorted(self._by_id.items())
        }


__all__ = [
    "GraphSnapshotStore",
    "InMemoryGraphSnapshotStore",
    "SnapshotStoreError",
]
