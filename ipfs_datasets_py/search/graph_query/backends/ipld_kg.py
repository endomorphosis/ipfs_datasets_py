from __future__ import annotations

import json
from typing import Any, Sequence

from ...graph_query.backend import (
    EntityHeader,
    GraphBackend,
    NeighborEdge,
    NeighborPage,
    ScanPage,
)
from ....data_transformation.ipld.knowledge_graph import IPLDKnowledgeGraph


class IPLDKnowledgeGraphBackend(GraphBackend):
    """Adapter to execute graph IR against an in-memory IPLDKnowledgeGraph.

    This is primarily for initial end-to-end wiring and tests.
    Sharded-CAR execution is implemented as a separate backend.
    """

    def __init__(self, kg: IPLDKnowledgeGraph):
        self._kg = kg

    def seed_exists(self, entity_id: str) -> bool:
        return self._kg.get_entity(entity_id) is not None

    def get_entity_headers(self, entity_ids: Sequence[str]) -> dict[str, EntityHeader]:
        out: dict[str, EntityHeader] = {}
        for eid in entity_ids:
            ent = self._kg.get_entity(eid)
            if ent is None:
                continue
            out[eid] = EntityHeader(
                id=ent.id,
                type=ent.type,
                name=ent.name,
                cid=getattr(ent, "cid", None),
                properties=dict(ent.properties) if ent.properties is not None else None,
            )
        return out

    def scan_type(
        self,
        entity_type: str,
        *,
        scope: Sequence[str] | None = None,
        limit: int = 100,
        cursor: str | None = None,
        shard_hints: Sequence[str] | None = None,
    ) -> ScanPage:
        # cursor/scope/shard_hints not used for this backend.
        entities = self._kg.get_entities_by_type(entity_type)
        entity_ids = [e.id for e in entities][: max(0, int(limit))]
        return ScanPage(entity_ids=entity_ids, next_cursor=None, shards_touched=1, shards_touched_ids=["__kg__"])

    def neighbors(
        self,
        entity_id: str,
        *,
        relationship_types: Sequence[str] | None = None,
        direction: str = "both",
        limit: int = 1000,
        cursor: str | None = None,
    ) -> NeighborPage:
        limit = max(0, int(limit))

        offset = 0
        if cursor:
            try:
                c = json.loads(cursor)
                if not isinstance(c, dict) or int(c.get("v", 1)) != 1:
                    raise ValueError("Invalid cursor")
                if c.get("entity_id") != entity_id:
                    raise ValueError("Cursor entity_id mismatch")
                if c.get("direction") != direction:
                    raise ValueError("Cursor direction mismatch")
                expected_types = list(relationship_types) if relationship_types is not None else None
                if c.get("relationship_types") != expected_types:
                    raise ValueError("Cursor relationship_types mismatch")
                offset = int(c.get("offset", 0))
            except Exception as e:
                raise ValueError("Invalid cursor") from e

        rels = self._kg.get_entity_relationships(
            entity_id,
            direction=direction,
            relationship_types=list(relationship_types) if relationship_types is not None else None,
        )

        if offset < 0:
            offset = 0
        if offset >= len(rels):
            return NeighborPage(edges=[], next_cursor=None, shards_touched=1, shards_touched_ids=["__kg__"])

        slice_rels = rels[offset : offset + limit]

        edges: list[NeighborEdge] = []
        for rel in slice_rels:
            edges.append(
                NeighborEdge(
                    relationship_type=rel.type,
                    source_id=rel.source_id,
                    target_id=rel.target_id,
                    relationship_id=rel.id,
                )
            )

        next_offset = offset + len(slice_rels)
        next_cursor = None
        if next_offset < len(rels) and len(slice_rels) > 0:
            next_cursor = json.dumps(
                {
                    "v": 1,
                    "entity_id": entity_id,
                    "direction": direction,
                    "relationship_types": list(relationship_types) if relationship_types is not None else None,
                    "offset": next_offset,
                }
            )

        return NeighborPage(edges=edges, next_cursor=next_cursor, shards_touched=1, shards_touched_ids=["__kg__"])
