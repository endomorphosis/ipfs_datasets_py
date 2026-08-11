"""Immutable snapshot store interfaces for monetary-flow graphs.

Stores never mutate a published :class:`GraphSnapshot`.  Updates are new
snapshot identities.  Content identity is deterministic and content-addressed.

DQK-059 routes producers through the authority port in shadow mode: the
in-memory / JSON store remains authoritative while DuckDB receives parity
receipts and durable shadow projections. Graph digests and CIDs are never
rewritten by the shadow path.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Optional, Protocol, runtime_checkable

from .model import (
    CryptoFlowValidationError,
    GraphSnapshot,
    merge_provider_ids,
)

logger = logging.getLogger(__name__)


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
    _shadow_authority: Any = field(default=None, init=False, repr=False)

    def attach_shadow_authority(self, authority: Any) -> None:
        """Bind DuckDB shadow authority (memory remains authoritative)."""

        self._shadow_authority = authority

    @property
    def shadow_authority(self) -> Any:
        return self._shadow_authority

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
        self._emit_shadow(stored, overwrite=overwrite)
        return stored.snapshot_id

    def _emit_shadow(self, snapshot: GraphSnapshot, *, overwrite: bool = False) -> None:
        shadow = self._shadow_authority
        # ``False`` is an explicit suppress token used by dual-write wrappers.
        if shadow is False:
            return
        if shadow is None:
            try:
                from ipfs_datasets_py.knowledge_graphs.catalog.store import (
                    get_graph_shadow_authority,
                )

                shadow = get_graph_shadow_authority()
            except Exception:
                shadow = None
        if shadow is None:
            return
        try:
            shadow.record_crypto_snapshot(snapshot, overwrite=overwrite)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "crypto-flow shadow quarantined (legacy ok) id=%s: %s",
                snapshot.snapshot_id,
                exc,
            )

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


@dataclass
class ShadowingGraphSnapshotStore:
    """Authority-port dual store: legacy authoritative, DuckDB shadow (DQK-059).

    Writes always commit to *legacy* first. DuckDB projection and parity
    receipts are best-effort and never replace legacy results.
    """

    legacy: GraphSnapshotStore
    shadow_authority: Any = None
    _receipts: list[Any] = field(default_factory=list, init=False, repr=False)

    def __post_init__(self) -> None:
        # Do not attach onto *legacy* — this wrapper owns dual-write so the
        # in-memory put does not double-emit shadow receipts.
        object.__setattr__(self, "_receipts", list(self._receipts))

    def attach_shadow_authority(self, authority: Any) -> None:
        self.shadow_authority = authority

    @property
    def mutation_receipts(self) -> list[Any]:
        if self.shadow_authority is not None:
            return [
                r
                for r in self.shadow_authority.list_mutation_receipts()
                if r.producer == "crypto_flows"
            ]
        return list(self._receipts)

    def put(
        self,
        snapshot: GraphSnapshot,
        *,
        overwrite: bool = False,
        operation_id: Optional[str] = None,
    ) -> str:
        # Suppress nested legacy auto-shadow so only this wrapper records once.
        prior = getattr(self.legacy, "_shadow_authority", None)
        if hasattr(self.legacy, "_shadow_authority"):
            self.legacy._shadow_authority = False
        try:
            key = self.legacy.put(snapshot, overwrite=overwrite)
        finally:
            if hasattr(self.legacy, "_shadow_authority"):
                self.legacy._shadow_authority = prior
        shadow = self.shadow_authority
        if shadow is None:
            try:
                from ipfs_datasets_py.knowledge_graphs.catalog.store import (
                    get_graph_shadow_authority,
                )

                shadow = get_graph_shadow_authority()
            except Exception:
                shadow = None
        if shadow is not None:
            try:
                receipt = shadow.record_crypto_snapshot(
                    snapshot, overwrite=overwrite, operation_id=operation_id
                )
                self._receipts.append(receipt)
            except Exception as exc:  # noqa: BLE001
                logger.warning("ShadowingGraphSnapshotStore shadow failed: %s", exc)
        return key

    def get(self, snapshot_id: str) -> GraphSnapshot:
        return self.legacy.get(snapshot_id)

    def get_by_digest(self, graph_digest: str) -> GraphSnapshot:
        return self.legacy.get_by_digest(graph_digest)

    def list_ids(self) -> tuple[str, ...]:
        return self.legacy.list_ids()

    def contains(self, snapshot_id: str) -> bool:
        return self.legacy.contains(snapshot_id)

    def history_parity(self) -> Mapping[str, Any]:
        """Compare full crypto-flow history identity legacy vs DuckDB."""

        shadow = self.shadow_authority
        if shadow is None:
            return {"matched": True, "count": 0, "entries": [], "authority": "legacy"}
        return shadow.crypto_history_parity(self.list_ids(), self.legacy)


__all__ = [
    "GraphSnapshotStore",
    "InMemoryGraphSnapshotStore",
    "ShadowingGraphSnapshotStore",
    "SnapshotStoreError",
]
