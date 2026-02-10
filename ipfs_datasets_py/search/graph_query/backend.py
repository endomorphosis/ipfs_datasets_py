from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Protocol, Sequence


Direction = Literal["outgoing", "incoming", "both"]


@dataclass(frozen=True)
class EntityHeader:
    id: str
    type: str
    name: str | None = None
    cid: str | None = None
    properties: dict[str, Any] | None = None


@dataclass(frozen=True)
class NeighborEdge:
    relationship_type: str
    source_id: str
    target_id: str
    relationship_id: str | None = None


@dataclass(frozen=True)
class ScanPage:
    entity_ids: list[str]
    next_cursor: str | None = None
    shards_touched: int = 0
    # Optional: concrete shard IDs touched while producing this page.
    # When provided, callers should prefer counting distinct IDs across pages.
    shards_touched_ids: list[str] | None = None


@dataclass(frozen=True)
class NeighborPage:
    edges: list[NeighborEdge]
    next_cursor: str | None = None
    shards_touched: int = 0
    # Optional: concrete shard IDs touched while producing this page.
    # When provided, callers should prefer counting distinct IDs across pages.
    shards_touched_ids: list[str] | None = None


class GraphBackend(Protocol):
    """Backend adapter interface for executing graph IR."""

    def get_entity_headers(self, entity_ids: Sequence[str]) -> dict[str, EntityHeader]:
        ...

    def seed_exists(self, entity_id: str) -> bool:
        ...

    def scan_type(
        self,
        entity_type: str,
        *,
        scope: Sequence[str] | None = None,
        limit: int = 100,
        cursor: str | None = None,
        shard_hints: Sequence[str] | None = None,
    ) -> ScanPage:
        ...

    def neighbors(
        self,
        entity_id: str,
        *,
        relationship_types: Sequence[str] | None = None,
        direction: Direction = "both",
        limit: int = 1000,
        cursor: str | None = None,
    ) -> NeighborPage:
        ...
