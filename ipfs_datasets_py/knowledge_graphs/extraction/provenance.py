"""Knowledge Graph Provenance Chain.

Content-addressed, tamper-evident provenance tracking for knowledge graph
mutations.  Each event references its predecessor by SHA-256 CID, forming an
immutable append-only chain that can be serialised as JSONL and verified for
tampering offline.

This is the "Blockchain integration for provenance" deferred v4.0+ roadmap
feature delivered in v3.22.29.

Example::

    from ipfs_datasets_py.knowledge_graphs.extraction import KnowledgeGraph

    kg = KnowledgeGraph("research")
    pchain = kg.enable_provenance()

    alice = kg.add_entity("person", "Alice", confidence=0.9)
    kg.add_relationship("knows", alice, kg.add_entity("person", "Bob"))

    # Inspect provenance
    print(pchain.depth)          # 3 events
    print(pchain.latest_cid)     # SHA-256-derived CID of the last event

    # Verify tamper-evidence
    is_valid, errors = pchain.verify_chain()
    assert is_valid

    # Serialise / restore
    jsonl = pchain.to_jsonl()
    restored = ProvenanceChain.from_jsonl(jsonl)
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Event type enum
# ---------------------------------------------------------------------------

class ProvenanceEventType(str, Enum):
    """Types of provenance events recorded in the chain."""
    ENTITY_CREATED = "entity_created"
    ENTITY_MODIFIED = "entity_modified"
    ENTITY_REMOVED = "entity_removed"
    RELATIONSHIP_CREATED = "relationship_created"
    RELATIONSHIP_REMOVED = "relationship_removed"
    GRAPH_SNAPSHOT = "graph_snapshot"
    GRAPH_RESTORED = "graph_restored"


# ---------------------------------------------------------------------------
# ProvenanceEvent dataclass
# ---------------------------------------------------------------------------

@dataclass
class ProvenanceEvent:
    """A single immutable event in the provenance chain.

    Attributes:
        event_type (ProvenanceEventType): The kind of mutation that occurred.
        timestamp (float): Unix timestamp of the event.
        entity_id (Optional[str]): The affected entity ID (if applicable).
        relationship_id (Optional[str]): The affected relationship ID (if
            applicable).
        data (Dict[str, Any]): Arbitrary event metadata (entity type, name,
            confidence, changes, etc.).
        previous_cid (Optional[str]): The CID of the immediately preceding
            event, or ``None`` for the genesis event.
        cid (str): Content-address of this event (auto-computed from all
            fields above using SHA-256).  Set automatically in
            ``__post_init__``.
    """

    event_type: ProvenanceEventType
    timestamp: float
    entity_id: Optional[str]
    relationship_id: Optional[str]
    data: Dict[str, Any]
    previous_cid: Optional[str]
    cid: str = field(default="")

    def __post_init__(self) -> None:
        if not self.cid:
            self.cid = self._compute_cid()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _compute_cid(self) -> str:
        """Derive a deterministic CID from event content.

        The CID is constructed as ``"bafk"`` followed by the first 48 hex
        characters of the SHA-256 digest of the JSON-serialised event fields
        (excluding the *cid* field itself).

        Returns:
            str: The computed CID string.
        """
        payload = {
            "event_type": self.event_type.value,
            "timestamp": self.timestamp,
            "entity_id": self.entity_id,
            "relationship_id": self.relationship_id,
            "data": self.data,
            "previous_cid": self.previous_cid,
        }
        serialised = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(serialised.encode("utf-8")).hexdigest()
        return "bafk" + digest[:48]

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """Serialise this event to a plain JSON-safe dictionary.

        Returns:
            Dict[str, Any]: The serialised event.
        """
        return {
            "event_type": self.event_type.value,
            "timestamp": self.timestamp,
            "entity_id": self.entity_id,
            "relationship_id": self.relationship_id,
            "data": self.data,
            "previous_cid": self.previous_cid,
            "cid": self.cid,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ProvenanceEvent":
        """Reconstruct a :class:`ProvenanceEvent` from a serialised dict.

        Note:
            The stored ``cid`` value is preserved as-is; no recomputation is
            performed.  Call :meth:`ProvenanceChain.verify_chain` to confirm
            integrity.

        Args:
            d (Dict[str, Any]): As produced by :meth:`to_dict`.

        Returns:
            ProvenanceEvent: The reconstructed event.
        """
        evt = cls.__new__(cls)
        evt.event_type = ProvenanceEventType(d["event_type"])
        evt.timestamp = float(d["timestamp"])
        evt.entity_id = d.get("entity_id")
        evt.relationship_id = d.get("relationship_id")
        evt.data = dict(d.get("data") or {})
        evt.previous_cid = d.get("previous_cid")
        evt.cid = d.get("cid", "")
        return evt


# ---------------------------------------------------------------------------
# ProvenanceChain
# ---------------------------------------------------------------------------

class ProvenanceChain:
    """Append-only, content-addressed provenance chain for a knowledge graph.

    Each call to one of the ``record_*`` methods appends a new
    :class:`ProvenanceEvent` to the chain.  Events are linked by their
    ``previous_cid`` field, forming an immutable hash-chain that can be
    verified for tampering with :meth:`verify_chain`.

    The chain can be serialised to JSONL format with :meth:`to_jsonl` and
    restored with :meth:`from_jsonl`.

    Example::

        chain = ProvenanceChain()
        chain.record_entity_created("e1", "person", "Alice", confidence=0.9)
        chain.record_entity_created("e2", "person", "Bob", confidence=0.8)
        chain.record_relationship_created("r1", "knows", "e1", "e2")

        is_valid, errors = chain.verify_chain()
        assert is_valid and errors == []

        jsonl = chain.to_jsonl()
        restored = ProvenanceChain.from_jsonl(jsonl)
        assert restored.depth == chain.depth
    """

    def __init__(self) -> None:
        self._events: List[ProvenanceEvent] = []
        # entity_id  → list of event indices (positions in _events)
        self._entity_index: Dict[str, List[int]] = {}
        # relationship_id → list of event indices
        self._relationship_index: Dict[str, List[int]] = {}

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def latest_cid(self) -> Optional[str]:
        """CID of the most recent event, or ``None`` if the chain is empty."""
        return self._events[-1].cid if self._events else None

    @property
    def depth(self) -> int:
        """Number of events recorded in this chain."""
        return len(self._events)

    # ------------------------------------------------------------------
    # Internal append helper
    # ------------------------------------------------------------------

    def _append(
        self,
        event_type: ProvenanceEventType,
        entity_id: Optional[str],
        relationship_id: Optional[str],
        data: Dict[str, Any],
    ) -> ProvenanceEvent:
        """Create and append a new event.

        Args:
            event_type: The type of the event.
            entity_id: Optional affected entity ID.
            relationship_id: Optional affected relationship ID.
            data: Arbitrary event metadata.

        Returns:
            ProvenanceEvent: The newly appended event.
        """
        evt = ProvenanceEvent(
            event_type=event_type,
            timestamp=time.time(),
            entity_id=entity_id,
            relationship_id=relationship_id,
            data=data,
            previous_cid=self.latest_cid,
        )
        idx = len(self._events)
        self._events.append(evt)
        if entity_id is not None:
            self._entity_index.setdefault(entity_id, []).append(idx)
        if relationship_id is not None:
            self._relationship_index.setdefault(relationship_id, []).append(idx)
        return evt

    # ------------------------------------------------------------------
    # Entity recording
    # ------------------------------------------------------------------

    def record_entity_created(
        self,
        entity_id: str,
        entity_type: str,
        name: str,
        confidence: float = 1.0,
        properties: Optional[Dict[str, Any]] = None,
    ) -> ProvenanceEvent:
        """Record the creation of a new entity.

        Args:
            entity_id (str): The entity's unique identifier.
            entity_type (str): The entity type label.
            name (str): The entity name.
            confidence (float): Extraction confidence.
            properties (Dict, optional): Additional entity properties.

        Returns:
            ProvenanceEvent: The recorded event.
        """
        return self._append(
            ProvenanceEventType.ENTITY_CREATED,
            entity_id=entity_id,
            relationship_id=None,
            data={
                "entity_type": entity_type,
                "name": name,
                "confidence": confidence,
                "properties": properties or {},
            },
        )

    def record_entity_modified(
        self,
        entity_id: str,
        changes: Dict[str, Any],
    ) -> ProvenanceEvent:
        """Record the modification of an existing entity.

        Args:
            entity_id (str): The entity's unique identifier.
            changes (Dict[str, Any]): A dict of field→new_value pairs
                describing what changed.

        Returns:
            ProvenanceEvent: The recorded event.
        """
        return self._append(
            ProvenanceEventType.ENTITY_MODIFIED,
            entity_id=entity_id,
            relationship_id=None,
            data={"changes": changes},
        )

    def record_entity_removed(self, entity_id: str) -> ProvenanceEvent:
        """Record the removal of an entity.

        Args:
            entity_id (str): The entity's unique identifier.

        Returns:
            ProvenanceEvent: The recorded event.
        """
        return self._append(
            ProvenanceEventType.ENTITY_REMOVED,
            entity_id=entity_id,
            relationship_id=None,
            data={},
        )

    # ------------------------------------------------------------------
    # Relationship recording
    # ------------------------------------------------------------------

    def record_relationship_created(
        self,
        relationship_id: str,
        relationship_type: str,
        source_id: str,
        target_id: str,
        confidence: float = 1.0,
    ) -> ProvenanceEvent:
        """Record the creation of a new relationship.

        Args:
            relationship_id (str): The relationship's unique identifier.
            relationship_type (str): The relationship type label.
            source_id (str): Source entity ID.
            target_id (str): Target entity ID.
            confidence (float): Extraction confidence.

        Returns:
            ProvenanceEvent: The recorded event.
        """
        return self._append(
            ProvenanceEventType.RELATIONSHIP_CREATED,
            entity_id=None,
            relationship_id=relationship_id,
            data={
                "relationship_type": relationship_type,
                "source_id": source_id,
                "target_id": target_id,
                "confidence": confidence,
            },
        )

    def record_relationship_removed(self, relationship_id: str) -> ProvenanceEvent:
        """Record the removal of a relationship.

        Args:
            relationship_id (str): The relationship's unique identifier.

        Returns:
            ProvenanceEvent: The recorded event.
        """
        return self._append(
            ProvenanceEventType.RELATIONSHIP_REMOVED,
            entity_id=None,
            relationship_id=relationship_id,
            data={},
        )

    # ------------------------------------------------------------------
    # Graph-level recording
    # ------------------------------------------------------------------

    def record_graph_snapshot(self, snapshot_name: str) -> ProvenanceEvent:
        """Record a graph snapshot event.

        Args:
            snapshot_name (str): The snapshot name.

        Returns:
            ProvenanceEvent: The recorded event.
        """
        return self._append(
            ProvenanceEventType.GRAPH_SNAPSHOT,
            entity_id=None,
            relationship_id=None,
            data={"snapshot_name": snapshot_name},
        )

    def record_graph_restored(self, snapshot_name: str) -> ProvenanceEvent:
        """Record a graph restore event.

        Args:
            snapshot_name (str): The snapshot name that was restored.

        Returns:
            ProvenanceEvent: The recorded event.
        """
        return self._append(
            ProvenanceEventType.GRAPH_RESTORED,
            entity_id=None,
            relationship_id=None,
            data={"snapshot_name": snapshot_name},
        )

    # ------------------------------------------------------------------
    # History queries
    # ------------------------------------------------------------------

    def get_history(
        self,
        entity_id: Optional[str] = None,
        relationship_id: Optional[str] = None,
    ) -> List[ProvenanceEvent]:
        """Return all events related to a specific entity or relationship.

        If both *entity_id* and *relationship_id* are ``None`` the full
        event list is returned.

        Args:
            entity_id (str, optional): Filter to events touching this entity.
            relationship_id (str, optional): Filter to events touching this
                relationship.

        Returns:
            List[ProvenanceEvent]: Matching events in chronological order.
        """
        if entity_id is None and relationship_id is None:
            return list(self._events)
        if entity_id is not None:
            indices = self._entity_index.get(entity_id, [])
            return [self._events[i] for i in indices]
        # relationship_id only
        indices = self._relationship_index.get(relationship_id, [])
        return [self._events[i] for i in indices]

    # ------------------------------------------------------------------
    # Verification
    # ------------------------------------------------------------------

    def verify_chain(self) -> Tuple[bool, List[str]]:
        """Verify the integrity of the hash chain.

        For each event the method recomputes the CID from its content and
        checks that:

        1. The recomputed CID matches the stored ``cid`` field.
        2. The ``previous_cid`` field matches the ``cid`` of the preceding
           event (or is ``None`` for the genesis event).

        Returns:
            Tuple[bool, List[str]]: A ``(is_valid, errors)`` pair where
            *is_valid* is ``True`` when no errors were found and *errors*
            is a list of human-readable problem descriptions.
        """
        errors: List[str] = []
        prev_cid: Optional[str] = None
        for idx, evt in enumerate(self._events):
            # Check previous_cid linkage
            if evt.previous_cid != prev_cid:
                errors.append(
                    f"Event {idx}: previous_cid mismatch — "
                    f"expected {prev_cid!r}, got {evt.previous_cid!r}"
                )
            # Recompute and compare CID
            expected_cid = evt._compute_cid()
            if evt.cid != expected_cid:
                errors.append(
                    f"Event {idx}: CID tampered — "
                    f"expected {expected_cid!r}, got {evt.cid!r}"
                )
            prev_cid = evt.cid
        return (len(errors) == 0), errors

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_jsonl(self) -> str:
        """Serialise the entire chain to JSONL (one JSON object per line).

        Returns:
            str: The JSONL-formatted provenance chain.
        """
        lines = [json.dumps(evt.to_dict(), separators=(",", ":")) for evt in self._events]
        return "\n".join(lines)

    @classmethod
    def from_jsonl(cls, text: str) -> "ProvenanceChain":
        """Reconstruct a :class:`ProvenanceChain` from JSONL text.

        Args:
            text (str): As produced by :meth:`to_jsonl`.

        Returns:
            ProvenanceChain: The restored chain.  CIDs are taken from the
            serialised data without recomputation.
        """
        chain = cls()
        for line in text.strip().splitlines():
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            evt = ProvenanceEvent.from_dict(d)
            idx = len(chain._events)
            chain._events.append(evt)
            if evt.entity_id is not None:
                chain._entity_index.setdefault(evt.entity_id, []).append(idx)
            if evt.relationship_id is not None:
                chain._relationship_index.setdefault(evt.relationship_id, []).append(idx)
        return chain
