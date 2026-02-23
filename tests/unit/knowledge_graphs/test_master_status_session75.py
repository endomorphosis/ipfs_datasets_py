"""Session 75 tests — Provenance Chain (blockchain-style, content-addressed).

Covers:
- ProvenanceEventType enum
- ProvenanceEvent CID computation and from_dict/to_dict
- ProvenanceChain record_entity_created/modified/removed
- ProvenanceChain record_relationship_created/removed
- ProvenanceChain record_graph_snapshot/restored
- ProvenanceChain get_history (by entity, by relationship, all)
- ProvenanceChain verify_chain (valid chain and tampered chain)
- ProvenanceChain to_jsonl / from_jsonl round-trip
- KnowledgeGraph.enable_provenance / disable_provenance / .provenance
- Auto-recording in add_entity and add_relationship
- extraction/__init__.py exports
- Doc integrity (DEFERRED_FEATURES, ROADMAP, MASTER_STATUS, CHANGELOG)
- Version agreement
"""

from __future__ import annotations

import json
import os
import re

import pytest

_KG_DIR = os.path.join(
    os.path.dirname(__file__), "..", "..", "..",
    "ipfs_datasets_py", "knowledge_graphs",
)


def _read(relpath: str) -> str:
    with open(os.path.join(_KG_DIR, relpath), encoding="utf-8") as fh:
        return fh.read()


# ---------------------------------------------------------------------------
# ProvenanceEventType
# ---------------------------------------------------------------------------
class TestProvenanceEventType:
    def test_all_types_exist(self):
        from ipfs_datasets_py.knowledge_graphs.extraction.provenance import ProvenanceEventType
        assert ProvenanceEventType.ENTITY_CREATED.value == "entity_created"
        assert ProvenanceEventType.ENTITY_MODIFIED.value == "entity_modified"
        assert ProvenanceEventType.ENTITY_REMOVED.value == "entity_removed"
        assert ProvenanceEventType.RELATIONSHIP_CREATED.value == "relationship_created"
        assert ProvenanceEventType.RELATIONSHIP_REMOVED.value == "relationship_removed"
        assert ProvenanceEventType.GRAPH_SNAPSHOT.value == "graph_snapshot"
        assert ProvenanceEventType.GRAPH_RESTORED.value == "graph_restored"

    def test_str_enum(self):
        from ipfs_datasets_py.knowledge_graphs.extraction.provenance import ProvenanceEventType
        assert str(ProvenanceEventType.ENTITY_CREATED) in ("ProvenanceEventType.ENTITY_CREATED", "entity_created")
        assert ProvenanceEventType("entity_created") is ProvenanceEventType.ENTITY_CREATED


# ---------------------------------------------------------------------------
# ProvenanceEvent
# ---------------------------------------------------------------------------
class TestProvenanceEvent:
    def _make(self):
        from ipfs_datasets_py.knowledge_graphs.extraction.provenance import (
            ProvenanceEvent, ProvenanceEventType
        )
        return ProvenanceEvent(
            event_type=ProvenanceEventType.ENTITY_CREATED,
            timestamp=1_000_000.0,
            entity_id="e1",
            relationship_id=None,
            data={"entity_type": "person", "name": "Alice"},
            previous_cid=None,
        )

    def test_cid_auto_computed(self):
        evt = self._make()
        assert evt.cid.startswith("bafk")
        assert len(evt.cid) == 52  # "bafk" + 48 hex chars

    def test_cid_deterministic(self):
        evt1 = self._make()
        evt2 = self._make()
        assert evt1.cid == evt2.cid

    def test_cid_changes_with_data(self):
        from ipfs_datasets_py.knowledge_graphs.extraction.provenance import (
            ProvenanceEvent, ProvenanceEventType
        )
        evt1 = self._make()
        evt2 = ProvenanceEvent(
            event_type=ProvenanceEventType.ENTITY_CREATED,
            timestamp=1_000_000.0,
            entity_id="e2",  # different entity_id
            relationship_id=None,
            data={"entity_type": "person", "name": "Alice"},
            previous_cid=None,
        )
        assert evt1.cid != evt2.cid

    def test_to_dict_round_trip(self):
        from ipfs_datasets_py.knowledge_graphs.extraction.provenance import ProvenanceEvent
        evt = self._make()
        d = evt.to_dict()
        restored = ProvenanceEvent.from_dict(d)
        assert restored.cid == evt.cid
        assert restored.entity_id == evt.entity_id
        assert restored.previous_cid == evt.previous_cid

    def test_from_dict_preserves_cid(self):
        from ipfs_datasets_py.knowledge_graphs.extraction.provenance import ProvenanceEvent
        evt = self._make()
        d = evt.to_dict()
        d["cid"] = "tampered-cid"
        restored = ProvenanceEvent.from_dict(d)
        assert restored.cid == "tampered-cid"  # preserved without recomputation


# ---------------------------------------------------------------------------
# ProvenanceChain — basic recording
# ---------------------------------------------------------------------------
class TestProvenanceChainRecording:
    def test_empty_chain(self):
        from ipfs_datasets_py.knowledge_graphs.extraction.provenance import ProvenanceChain
        chain = ProvenanceChain()
        assert chain.depth == 0
        assert chain.latest_cid is None

    def test_record_entity_created(self):
        from ipfs_datasets_py.knowledge_graphs.extraction.provenance import (
            ProvenanceChain, ProvenanceEventType
        )
        chain = ProvenanceChain()
        evt = chain.record_entity_created("e1", "person", "Alice", confidence=0.9)
        assert chain.depth == 1
        assert evt.event_type == ProvenanceEventType.ENTITY_CREATED
        assert evt.entity_id == "e1"
        assert evt.previous_cid is None
        assert chain.latest_cid == evt.cid

    def test_record_entity_modified(self):
        from ipfs_datasets_py.knowledge_graphs.extraction.provenance import (
            ProvenanceChain, ProvenanceEventType
        )
        chain = ProvenanceChain()
        chain.record_entity_created("e1", "person", "Alice")
        prev = chain.latest_cid
        evt = chain.record_entity_modified("e1", {"name": "Alicia"})
        assert evt.event_type == ProvenanceEventType.ENTITY_MODIFIED
        assert evt.previous_cid == prev

    def test_record_entity_removed(self):
        from ipfs_datasets_py.knowledge_graphs.extraction.provenance import (
            ProvenanceChain, ProvenanceEventType
        )
        chain = ProvenanceChain()
        chain.record_entity_created("e1", "person", "Alice")
        evt = chain.record_entity_removed("e1")
        assert evt.event_type == ProvenanceEventType.ENTITY_REMOVED
        assert chain.depth == 2

    def test_record_relationship_created(self):
        from ipfs_datasets_py.knowledge_graphs.extraction.provenance import (
            ProvenanceChain, ProvenanceEventType
        )
        chain = ProvenanceChain()
        evt = chain.record_relationship_created("r1", "knows", "e1", "e2", confidence=0.8)
        assert evt.event_type == ProvenanceEventType.RELATIONSHIP_CREATED
        assert evt.relationship_id == "r1"
        assert evt.entity_id is None

    def test_record_relationship_removed(self):
        from ipfs_datasets_py.knowledge_graphs.extraction.provenance import (
            ProvenanceChain, ProvenanceEventType
        )
        chain = ProvenanceChain()
        chain.record_relationship_created("r1", "knows", "e1", "e2")
        evt = chain.record_relationship_removed("r1")
        assert evt.event_type == ProvenanceEventType.RELATIONSHIP_REMOVED

    def test_record_graph_snapshot_and_restored(self):
        from ipfs_datasets_py.knowledge_graphs.extraction.provenance import (
            ProvenanceChain, ProvenanceEventType
        )
        chain = ProvenanceChain()
        chain.record_graph_snapshot("snap_v1")
        evt = chain.record_graph_restored("snap_v1")
        assert chain.depth == 2
        assert evt.event_type == ProvenanceEventType.GRAPH_RESTORED
        assert evt.data["snapshot_name"] == "snap_v1"

    def test_chain_links_previous_cid(self):
        from ipfs_datasets_py.knowledge_graphs.extraction.provenance import ProvenanceChain
        chain = ProvenanceChain()
        e1 = chain.record_entity_created("e1", "person", "Alice")
        e2 = chain.record_entity_created("e2", "person", "Bob")
        e3 = chain.record_relationship_created("r1", "knows", "e1", "e2")
        assert e2.previous_cid == e1.cid
        assert e3.previous_cid == e2.cid


# ---------------------------------------------------------------------------
# ProvenanceChain — history queries
# ---------------------------------------------------------------------------
class TestProvenanceChainHistory:
    def test_get_history_all(self):
        from ipfs_datasets_py.knowledge_graphs.extraction.provenance import ProvenanceChain
        chain = ProvenanceChain()
        chain.record_entity_created("e1", "person", "Alice")
        chain.record_entity_created("e2", "person", "Bob")
        chain.record_relationship_created("r1", "knows", "e1", "e2")
        assert len(chain.get_history()) == 3

    def test_get_history_by_entity(self):
        from ipfs_datasets_py.knowledge_graphs.extraction.provenance import ProvenanceChain
        chain = ProvenanceChain()
        chain.record_entity_created("e1", "person", "Alice")
        chain.record_entity_created("e2", "person", "Bob")
        chain.record_entity_modified("e1", {"name": "Alicia"})
        history = chain.get_history(entity_id="e1")
        assert len(history) == 2
        assert all(e.entity_id == "e1" for e in history)

    def test_get_history_by_relationship(self):
        from ipfs_datasets_py.knowledge_graphs.extraction.provenance import ProvenanceChain
        chain = ProvenanceChain()
        chain.record_entity_created("e1", "person", "Alice")
        chain.record_relationship_created("r1", "knows", "e1", "e2")
        chain.record_relationship_removed("r1")
        history = chain.get_history(relationship_id="r1")
        assert len(history) == 2
        assert all(e.relationship_id == "r1" for e in history)

    def test_get_history_unknown_entity_empty(self):
        from ipfs_datasets_py.knowledge_graphs.extraction.provenance import ProvenanceChain
        chain = ProvenanceChain()
        assert chain.get_history(entity_id="does-not-exist") == []


# ---------------------------------------------------------------------------
# ProvenanceChain — verify_chain
# ---------------------------------------------------------------------------
class TestProvenanceChainVerify:
    def test_valid_chain(self):
        from ipfs_datasets_py.knowledge_graphs.extraction.provenance import ProvenanceChain
        chain = ProvenanceChain()
        chain.record_entity_created("e1", "person", "Alice")
        chain.record_entity_created("e2", "person", "Bob")
        chain.record_relationship_created("r1", "knows", "e1", "e2")
        is_valid, errors = chain.verify_chain()
        assert is_valid
        assert errors == []

    def test_empty_chain_valid(self):
        from ipfs_datasets_py.knowledge_graphs.extraction.provenance import ProvenanceChain
        chain = ProvenanceChain()
        is_valid, errors = chain.verify_chain()
        assert is_valid
        assert errors == []

    def test_tampered_cid_detected(self):
        from ipfs_datasets_py.knowledge_graphs.extraction.provenance import ProvenanceChain
        chain = ProvenanceChain()
        chain.record_entity_created("e1", "person", "Alice")
        chain.record_entity_created("e2", "person", "Bob")
        # Tamper the CID of the first event
        chain._events[0].cid = "bafk-tampered-cid-xxxx"
        is_valid, errors = chain.verify_chain()
        assert not is_valid
        assert len(errors) >= 1

    def test_tampered_previous_cid_detected(self):
        from ipfs_datasets_py.knowledge_graphs.extraction.provenance import ProvenanceChain
        chain = ProvenanceChain()
        chain.record_entity_created("e1", "person", "Alice")
        chain.record_entity_created("e2", "person", "Bob")
        # Tamper the previous_cid link of the second event
        chain._events[1].previous_cid = "bafk-wrong-link"
        is_valid, errors = chain.verify_chain()
        assert not is_valid
        assert any("previous_cid" in e for e in errors)


# ---------------------------------------------------------------------------
# ProvenanceChain — serialisation
# ---------------------------------------------------------------------------
class TestProvenanceChainSerialisation:
    def test_to_jsonl_line_count(self):
        from ipfs_datasets_py.knowledge_graphs.extraction.provenance import ProvenanceChain
        chain = ProvenanceChain()
        chain.record_entity_created("e1", "person", "Alice")
        chain.record_entity_created("e2", "person", "Bob")
        chain.record_relationship_created("r1", "knows", "e1", "e2")
        jsonl = chain.to_jsonl()
        lines = [l for l in jsonl.strip().splitlines() if l.strip()]
        assert len(lines) == 3

    def test_to_jsonl_valid_json_lines(self):
        from ipfs_datasets_py.knowledge_graphs.extraction.provenance import ProvenanceChain
        chain = ProvenanceChain()
        chain.record_entity_created("e1", "person", "Alice")
        jsonl = chain.to_jsonl()
        d = json.loads(jsonl.strip().splitlines()[0])
        assert "cid" in d
        assert "event_type" in d

    def test_from_jsonl_round_trip_depth(self):
        from ipfs_datasets_py.knowledge_graphs.extraction.provenance import ProvenanceChain
        chain = ProvenanceChain()
        chain.record_entity_created("e1", "person", "Alice")
        chain.record_entity_created("e2", "person", "Bob")
        chain.record_relationship_created("r1", "knows", "e1", "e2")
        jsonl = chain.to_jsonl()
        restored = ProvenanceChain.from_jsonl(jsonl)
        assert restored.depth == chain.depth

    def test_from_jsonl_verify_chain(self):
        from ipfs_datasets_py.knowledge_graphs.extraction.provenance import ProvenanceChain
        chain = ProvenanceChain()
        chain.record_entity_created("e1", "person", "Alice")
        chain.record_entity_created("e2", "person", "Bob")
        jsonl = chain.to_jsonl()
        restored = ProvenanceChain.from_jsonl(jsonl)
        is_valid, errors = restored.verify_chain()
        assert is_valid, f"Restored chain invalid: {errors}"

    def test_from_jsonl_entity_index(self):
        from ipfs_datasets_py.knowledge_graphs.extraction.provenance import ProvenanceChain
        chain = ProvenanceChain()
        chain.record_entity_created("e1", "person", "Alice")
        chain.record_entity_modified("e1", {"name": "Alicia"})
        jsonl = chain.to_jsonl()
        restored = ProvenanceChain.from_jsonl(jsonl)
        history = restored.get_history(entity_id="e1")
        assert len(history) == 2

    def test_from_jsonl_empty_string(self):
        from ipfs_datasets_py.knowledge_graphs.extraction.provenance import ProvenanceChain
        restored = ProvenanceChain.from_jsonl("")
        assert restored.depth == 0


# ---------------------------------------------------------------------------
# KnowledgeGraph integration
# ---------------------------------------------------------------------------
class TestKnowledgeGraphProvenanceIntegration:
    def test_provenance_none_by_default(self):
        from ipfs_datasets_py.knowledge_graphs.extraction import KnowledgeGraph
        kg = KnowledgeGraph("test")
        assert kg.provenance is None

    def test_enable_provenance_returns_chain(self):
        from ipfs_datasets_py.knowledge_graphs.extraction import KnowledgeGraph, ProvenanceChain
        kg = KnowledgeGraph("test")
        chain = kg.enable_provenance()
        assert isinstance(chain, ProvenanceChain)
        assert kg.provenance is chain

    def test_enable_provenance_idempotent(self):
        from ipfs_datasets_py.knowledge_graphs.extraction import KnowledgeGraph
        kg = KnowledgeGraph("test")
        chain1 = kg.enable_provenance()
        chain2 = kg.enable_provenance()
        assert chain1 is chain2

    def test_disable_provenance(self):
        from ipfs_datasets_py.knowledge_graphs.extraction import KnowledgeGraph
        kg = KnowledgeGraph("test")
        kg.enable_provenance()
        kg.disable_provenance()
        assert kg.provenance is None

    def test_add_entity_auto_records(self):
        from ipfs_datasets_py.knowledge_graphs.extraction import KnowledgeGraph
        kg = KnowledgeGraph("test")
        chain = kg.enable_provenance()
        kg.add_entity("person", "Alice")
        assert chain.depth == 1

    def test_add_relationship_auto_records(self):
        from ipfs_datasets_py.knowledge_graphs.extraction import KnowledgeGraph
        kg = KnowledgeGraph("test")
        chain = kg.enable_provenance()
        alice = kg.add_entity("person", "Alice")
        bob = kg.add_entity("person", "Bob")
        kg.add_relationship("knows", alice, bob)
        assert chain.depth == 3

    def test_no_auto_record_without_provenance(self):
        from ipfs_datasets_py.knowledge_graphs.extraction import KnowledgeGraph
        kg = KnowledgeGraph("test")
        kg.add_entity("person", "Alice")  # should not raise

    def test_provenance_chain_valid_after_kg_mutations(self):
        from ipfs_datasets_py.knowledge_graphs.extraction import KnowledgeGraph
        kg = KnowledgeGraph("test")
        chain = kg.enable_provenance()
        alice = kg.add_entity("person", "Alice")
        bob = kg.add_entity("person", "Bob")
        kg.add_relationship("knows", alice, bob)
        is_valid, errors = chain.verify_chain()
        assert is_valid, f"Chain invalid: {errors}"


# ---------------------------------------------------------------------------
# extraction/__init__.py exports
# ---------------------------------------------------------------------------
class TestExtractionExports:
    def test_provenance_chain_importable(self):
        from ipfs_datasets_py.knowledge_graphs.extraction import ProvenanceChain
        assert ProvenanceChain is not None

    def test_provenance_event_importable(self):
        from ipfs_datasets_py.knowledge_graphs.extraction import ProvenanceEvent
        assert ProvenanceEvent is not None

    def test_provenance_event_type_importable(self):
        from ipfs_datasets_py.knowledge_graphs.extraction import ProvenanceEventType
        assert ProvenanceEventType is not None

    def test_all_provenance_symbols_in_all(self):
        from ipfs_datasets_py.knowledge_graphs import extraction
        for sym in ("ProvenanceChain", "ProvenanceEvent", "ProvenanceEventType"):
            assert sym in extraction.__all__, f"{sym!r} not in __all__"


# ---------------------------------------------------------------------------
# Doc integrity
# ---------------------------------------------------------------------------
class TestDocIntegritySession75:
    def test_deferred_features_p10(self):
        content = _read("DEFERRED_FEATURES.md")
        assert "P10" in content

    def test_deferred_features_provenance_section(self):
        content = _read("DEFERRED_FEATURES.md")
        assert "Provenance" in content or "provenance" in content

    def test_deferred_features_implemented_v3_22_29(self):
        content = _read("DEFERRED_FEATURES.md")
        assert "3.22.29" in content

    def test_roadmap_blockchain_delivered(self):
        content = _read("ROADMAP.md")
        assert "3.22.29" in content

    def test_changelog_3_22_29(self):
        content = _read("CHANGELOG_KNOWLEDGE_GRAPHS.md")
        assert "3.22.29" in content

    def test_master_status_3_22_29(self):
        content = _read("MASTER_STATUS.md")
        assert "3.22.29" in content


# ---------------------------------------------------------------------------
# Version agreement
# ---------------------------------------------------------------------------
class TestVersionAgreement:
    def _extract_top_version(self, content: str) -> str:
        # Handle "**Version:** X.Y.Z" (MASTER_STATUS.md format)
        m = re.search(r'\*\*Version:\*\*\s+([0-9]+\.[0-9]+\.[0-9]+)', content)
        if m:
            return m.group(1)
        m = re.search(r'(?:Current Version|Module Version)[:\s]+([0-9]+\.[0-9]+\.[0-9]+)', content)
        if m:
            return m.group(1)
        m = re.search(r'\*\*Module Version:\*\*\s+([0-9]+\.[0-9]+\.[0-9]+)', content)
        return m.group(1) if m else ""

    def test_master_status_version(self):
        v = self._extract_top_version(_read("MASTER_STATUS.md"))
        assert v >= "3.22.29", f"MASTER_STATUS version is {v!r}"

    def test_changelog_has_version(self):
        assert "3.22.29" in _read("CHANGELOG_KNOWLEDGE_GRAPHS.md")

    def test_roadmap_has_version(self):
        assert "3.22.29" in _read("ROADMAP.md")
