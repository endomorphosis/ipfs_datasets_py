"""Immutable record types for the durable graph catalog."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Mapping, Optional


def _freeze_meta(meta: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    if meta is None:
        return {}
    if not isinstance(meta, Mapping):
        raise TypeError("metadata must be a mapping")
    # Shallow copy; values must already be JSON-safe.
    return {str(k): v for k, v in meta.items()}


@dataclass(frozen=True, slots=True)
class GraphRecord:
    """Persisted graph identity and lifecycle state."""

    tenant: str
    graph_id: str
    storage_profile: str
    graph_kind: str
    status: str  # active | tombstoned
    created_at: str
    updated_at: str
    default_branch: str = "main"
    tombstoned_at: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "metadata", _freeze_meta(self.metadata))

    @property
    def uri(self) -> str:
        return f"kg://{self.tenant}/{self.graph_id}"

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["uri"] = self.uri
        return d


@dataclass(frozen=True, slots=True)
class BranchRecord:
    """Named mutable branch whose head points at an immutable revision."""

    tenant: str
    graph_id: str
    branch: str
    head_revision: str
    status: str  # active | tombstoned
    created_at: str
    updated_at: str
    tombstoned_at: Optional[str] = None

    @property
    def uri(self) -> str:
        return f"kg://{self.tenant}/{self.graph_id}/branches/{self.branch}"

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["uri"] = self.uri
        return d


@dataclass(frozen=True, slots=True)
class RevisionRecord:
    """Immutable revision control-plane record (payload lives in storage)."""

    tenant: str
    graph_id: str
    revision_id: str
    parent_revision: Optional[str]
    storage_profile: str
    created_at: str
    manifest_cid: Optional[str] = None
    manifest_json: Optional[str] = None
    pin_root: Optional[str] = None
    checksum: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "metadata", _freeze_meta(self.metadata))

    @property
    def uri(self) -> str:
        return f"kg://{self.tenant}/{self.graph_id}/revisions/{self.revision_id}"

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["uri"] = self.uri
        return d


@dataclass(frozen=True, slots=True)
class LeaseRecord:
    """Graph-scoped writer lease with fencing epoch."""

    tenant: str
    graph_id: str
    branch: str
    lease_id: str
    holder: str
    epoch: int
    expires_at: str
    created_at: str
    renewed_at: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class IdempotencyRecord:
    """Durable idempotency outcome for create/CAS/delete retries."""

    key: str
    tenant: str
    graph_id: str
    operation: str
    request_hash: str
    response_json: str
    created_at: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class PinRootRecord:
    """Explicit pin root for GC safety of a revision."""

    tenant: str
    graph_id: str
    revision_id: str
    root_cid: str
    pin_kind: str
    created_at: str
    pin_id: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class TombstoneRecord:
    """Tombstone for a graph or branch."""

    entity_type: str  # graph | branch
    tenant: str
    graph_id: str
    tombstoned_at: str
    branch: Optional[str] = None
    reason: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class GraphDescription:
    """describe() payload: catalog metadata + branch heads."""

    tenant: str
    graph_id: str
    uri: str
    storage_profile: str
    graph_kind: str
    status: str
    default_branch: str
    head_revision: Optional[str]
    branches: tuple[Dict[str, Any], ...]
    created_at: str
    updated_at: str
    tombstoned_at: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "metadata", _freeze_meta(self.metadata))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tenant": self.tenant,
            "graph_id": self.graph_id,
            "uri": self.uri,
            "storage_profile": self.storage_profile,
            "graph_kind": self.graph_kind,
            "status": self.status,
            "default_branch": self.default_branch,
            "head_revision": self.head_revision,
            "branches": list(self.branches),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "tombstoned_at": self.tombstoned_at,
            "metadata": dict(self.metadata),
        }


__all__ = [
    "GraphRecord",
    "BranchRecord",
    "RevisionRecord",
    "LeaseRecord",
    "IdempotencyRecord",
    "PinRootRecord",
    "TombstoneRecord",
    "GraphDescription",
]
