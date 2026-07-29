"""Lightweight graph fragment models for v2 shard publish/query (KGP-014).

These types intentionally avoid the legacy ``IPLDKnowledgeGraph`` / broken
``data_transformation`` import path. The publisher and runtime operate on plain
JSON-serializable fragments that map cleanly onto CAR payloads and index
buckets described by :mod:`manifest`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Iterator, Mapping, MutableMapping, Optional, Sequence


@dataclass(frozen=True, slots=True)
class EntityRecord:
    """One graph entity owned by exactly one physical shard after routing."""

    entity_id: str
    entity_type: str
    name: Optional[str] = None
    properties: Mapping[str, Any] = field(default_factory=dict)
    cid: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.entity_id,
            "type": self.entity_type,
            "name": self.name,
            "properties": dict(self.properties) if self.properties else None,
            "cid": self.cid,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "EntityRecord":
        props = data.get("properties")
        return cls(
            entity_id=str(data["id"]),
            entity_type=str(data.get("type") or data.get("entity_type") or ""),
            name=data.get("name"),
            properties=dict(props) if isinstance(props, Mapping) else {},
            cid=data.get("cid"),
        )


@dataclass(frozen=True, slots=True)
class RelationshipRecord:
    """One directed edge; may be intra-shard or cross-shard after routing."""

    relationship_id: str
    relationship_type: str
    source_id: str
    target_id: str
    properties: Mapping[str, Any] = field(default_factory=dict)
    confidence: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.relationship_id,
            "type": self.relationship_type,
            "source_id": self.source_id,
            "target_id": self.target_id,
            "properties": dict(self.properties) if self.properties else None,
            "confidence": self.confidence,
        }

    def to_neighbor_dict(
        self,
        *,
        cross_shard: bool = False,
        peer_physical_shard_id: Optional[str] = None,
    ) -> dict[str, Any]:
        out: dict[str, Any] = {
            "relationship_type": self.relationship_type,
            "source_id": self.source_id,
            "target_id": self.target_id,
            "relationship_id": self.relationship_id,
            "cross_shard": bool(cross_shard),
        }
        if peer_physical_shard_id is not None:
            out["peer_physical_shard_id"] = peer_physical_shard_id
        if self.properties:
            out["properties"] = dict(self.properties)
        return out

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RelationshipRecord":
        props = data.get("properties")
        return cls(
            relationship_id=str(
                data.get("id") or data.get("relationship_id") or ""
            ),
            relationship_type=str(
                data.get("type") or data.get("relationship_type") or ""
            ),
            source_id=str(data["source_id"]),
            target_id=str(data["target_id"]),
            properties=dict(props) if isinstance(props, Mapping) else {},
            confidence=float(data.get("confidence", 1.0)),
        )


@dataclass
class GraphFragment:
    """Mutable in-memory graph used as the publish/query working set."""

    name: str = "graph"
    entities: MutableMapping[str, EntityRecord] = field(default_factory=dict)
    relationships: MutableMapping[str, RelationshipRecord] = field(default_factory=dict)

    def add_entity(
        self,
        entity_id: str,
        entity_type: str,
        *,
        name: Optional[str] = None,
        properties: Optional[Mapping[str, Any]] = None,
        cid: Optional[str] = None,
    ) -> EntityRecord:
        rec = EntityRecord(
            entity_id=str(entity_id),
            entity_type=str(entity_type),
            name=name,
            properties=dict(properties or {}),
            cid=cid,
        )
        self.entities[rec.entity_id] = rec
        return rec

    def add_relationship(
        self,
        relationship_id: str,
        relationship_type: str,
        source_id: str,
        target_id: str,
        *,
        properties: Optional[Mapping[str, Any]] = None,
        confidence: float = 1.0,
    ) -> RelationshipRecord:
        rec = RelationshipRecord(
            relationship_id=str(relationship_id),
            relationship_type=str(relationship_type),
            source_id=str(source_id),
            target_id=str(target_id),
            properties=dict(properties or {}),
            confidence=float(confidence),
        )
        self.relationships[rec.relationship_id] = rec
        return rec

    def entity_types(self) -> list[str]:
        return sorted({e.entity_type for e in self.entities.values() if e.entity_type})

    def relationship_types(self) -> list[str]:
        return sorted(
            {r.relationship_type for r in self.relationships.values() if r.relationship_type}
        )

    def iter_entities(self) -> Iterator[EntityRecord]:
        for eid in sorted(self.entities.keys()):
            yield self.entities[eid]

    def iter_relationships(self) -> Iterator[RelationshipRecord]:
        for rid in sorted(self.relationships.keys()):
            yield self.relationships[rid]

    def to_payload_dict(self, *, physical_shard_id: str) -> dict[str, Any]:
        return {
            "v": 2,
            "physical_shard_id": physical_shard_id,
            "entities": [e.to_dict() for e in self.iter_entities()],
            "relationships": [r.to_dict() for r in self.iter_relationships()],
        }

    @classmethod
    def from_payload_dict(cls, data: Mapping[str, Any]) -> "GraphFragment":
        frag = cls(name=str(data.get("physical_shard_id") or "shard"))
        for raw in data.get("entities") or ():
            if isinstance(raw, Mapping):
                ent = EntityRecord.from_dict(raw)
                frag.entities[ent.entity_id] = ent
        for raw in data.get("relationships") or ():
            if isinstance(raw, Mapping):
                rel = RelationshipRecord.from_dict(raw)
                if rel.relationship_id:
                    frag.relationships[rel.relationship_id] = rel
        return frag

    @classmethod
    def from_entities_and_relationships(
        cls,
        entities: Iterable[EntityRecord | Mapping[str, Any]],
        relationships: Iterable[RelationshipRecord | Mapping[str, Any]] = (),
        *,
        name: str = "graph",
    ) -> "GraphFragment":
        frag = cls(name=name)
        for item in entities:
            ent = item if isinstance(item, EntityRecord) else EntityRecord.from_dict(item)
            frag.entities[ent.entity_id] = ent
        for item in relationships:
            rel = (
                item
                if isinstance(item, RelationshipRecord)
                else RelationshipRecord.from_dict(item)
            )
            frag.relationships[rel.relationship_id] = rel
        return frag


__all__ = [
    "EntityRecord",
    "RelationshipRecord",
    "GraphFragment",
]
