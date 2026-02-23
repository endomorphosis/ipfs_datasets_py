"""Session 71 — Graph Event Subscriptions + KG Snapshots

Tests for two v4.0+ roadmap features implemented in v3.22.25:

  §17 Graph Event Subscriptions (real-time graph streaming):
      - GraphEventType / GraphEvent classes exist and are exported
      - KnowledgeGraph.subscribe(callback) → int
      - KnowledgeGraph.unsubscribe(handler_id) → bool
      - add_entity() emits ENTITY_ADDED events
      - add_relationship() emits RELATIONSHIP_ADDED events
      - apply_diff() emits ENTITY_REMOVED / RELATIONSHIP_REMOVED /
        ENTITY_ADDED / RELATIONSHIP_ADDED / ENTITY_MODIFIED events
      - Faulty subscribers don't crash graph operations
      - Multiple concurrent subscribers work independently

  §18 KG Snapshots (temporal graph versioning):
      - snapshot(name) saves a named copy
      - list_snapshots() returns sorted names
      - get_snapshot(name) returns copy of stored payload
      - restore_snapshot(name) rebuilds the graph from snapshot

  Doc-consistency checks:
      - DEFERRED_FEATURES.md has §17 + §18 entries
      - ROADMAP.md acknowledges v3.22.25 delivery
      - MASTER_STATUS.md version row matches CHANGELOG and ROADMAP
"""

import os
import time
from pathlib import Path

import pytest

# ── path helpers ─────────────────────────────────────────────────────────
# tests/unit/knowledge_graphs/ → 3 levels up → repo root
_REPO_ROOT = Path(__file__).resolve().parents[3]
_KG_ROOT = _REPO_ROOT / "ipfs_datasets_py" / "knowledge_graphs"


def _read(path) -> str:
    with open(path, encoding="utf-8") as fh:
        return fh.read()


# ═══════════════════════════════════════════════════════════════════════════
# Part 1 — GraphEventType and GraphEvent classes
# ═══════════════════════════════════════════════════════════════════════════


class TestGraphEventClasses:
    """GraphEventType enum and GraphEvent dataclass exist and are usable."""

    def test_graph_event_type_importable(self):
        from ipfs_datasets_py.knowledge_graphs.extraction import GraphEventType  # noqa: F401

    def test_graph_event_importable(self):
        from ipfs_datasets_py.knowledge_graphs.extraction import GraphEvent  # noqa: F401

    def test_event_type_values(self):
        from ipfs_datasets_py.knowledge_graphs.extraction import GraphEventType
        expected = {
            "entity_added",
            "entity_removed",
            "entity_modified",
            "relationship_added",
            "relationship_removed",
        }
        assert {e.value for e in GraphEventType} == expected

    def test_graph_event_fields(self):
        from ipfs_datasets_py.knowledge_graphs.extraction import GraphEvent, GraphEventType
        t = time.time()
        ev = GraphEvent(event_type=GraphEventType.ENTITY_ADDED, timestamp=t, entity_id="e1")
        assert ev.event_type == GraphEventType.ENTITY_ADDED
        assert ev.timestamp == t
        assert ev.entity_id == "e1"
        assert ev.relationship_id is None
        assert ev.data is None

    def test_graph_event_type_is_string_enum(self):
        from ipfs_datasets_py.knowledge_graphs.extraction import GraphEventType
        # str-subclassing enum: value == str comparison
        assert GraphEventType.ENTITY_ADDED == "entity_added"


# ═══════════════════════════════════════════════════════════════════════════
# Part 2 — subscribe / unsubscribe API
# ═══════════════════════════════════════════════════════════════════════════


class TestSubscribeUnsubscribe:
    """subscribe()/unsubscribe() on KnowledgeGraph."""

    def _kg(self):
        from ipfs_datasets_py.knowledge_graphs.extraction import KnowledgeGraph
        return KnowledgeGraph("sub_test")

    def test_subscribe_returns_int(self):
        kg = self._kg()
        hid = kg.subscribe(lambda e: None)
        assert isinstance(hid, int)

    def test_subscribe_ids_unique(self):
        kg = self._kg()
        ids = [kg.subscribe(lambda e: None) for _ in range(5)]
        assert len(set(ids)) == 5

    def test_unsubscribe_returns_true_when_found(self):
        kg = self._kg()
        hid = kg.subscribe(lambda e: None)
        assert kg.unsubscribe(hid) is True

    def test_unsubscribe_returns_false_when_not_found(self):
        kg = self._kg()
        assert kg.unsubscribe(9999) is False

    def test_unsubscribe_removes_subscriber(self):
        kg = self._kg()
        events = []
        hid = kg.subscribe(events.append)
        kg.unsubscribe(hid)
        kg.add_entity("person", "Alice")
        assert events == [], "No events after unsubscribe"

    def test_multiple_subscribers(self):
        kg = self._kg()
        log_a, log_b = [], []
        kg.subscribe(log_a.append)
        kg.subscribe(log_b.append)
        kg.add_entity("person", "Alice")
        assert len(log_a) == 1
        assert len(log_b) == 1


# ═══════════════════════════════════════════════════════════════════════════
# Part 3 — Events fired during mutations
# ═══════════════════════════════════════════════════════════════════════════


class TestEventFiring:
    """Events are emitted for every structural mutation."""

    def _setup(self):
        from ipfs_datasets_py.knowledge_graphs.extraction import KnowledgeGraph
        kg = KnowledgeGraph("event_test")
        events = []
        kg.subscribe(events.append)
        return kg, events

    def test_add_entity_fires_entity_added(self):
        from ipfs_datasets_py.knowledge_graphs.extraction import GraphEventType
        kg, events = self._setup()
        e = kg.add_entity("person", "Alice")
        assert len(events) == 1
        assert events[0].event_type == GraphEventType.ENTITY_ADDED
        assert events[0].entity_id == e.entity_id

    def test_add_entity_event_has_data(self):
        kg, events = self._setup()
        kg.add_entity("person", "Alice")
        assert events[0].data["entity_type"] == "person"
        assert events[0].data["name"] == "Alice"

    def test_add_entity_event_timestamp_recent(self):
        kg, events = self._setup()
        before = time.time()
        kg.add_entity("person", "Alice")
        after = time.time()
        assert before <= events[0].timestamp <= after

    def test_add_relationship_fires_relationship_added(self):
        from ipfs_datasets_py.knowledge_graphs.extraction import GraphEventType
        kg, events = self._setup()
        e1 = kg.add_entity("person", "Alice")
        e2 = kg.add_entity("person", "Bob")
        events.clear()
        r = kg.add_relationship("knows", e1, e2)
        assert len(events) == 1
        assert events[0].event_type == GraphEventType.RELATIONSHIP_ADDED
        assert events[0].relationship_id == r.relationship_id

    def test_apply_diff_fires_entity_removed(self):
        from ipfs_datasets_py.knowledge_graphs.extraction import (
            GraphEventType, KnowledgeGraph,
        )
        kg1 = KnowledgeGraph("orig")
        kg1.add_entity("person", "Alice")
        kg2 = KnowledgeGraph("updated")  # empty — Alice was removed

        diff = kg1.diff(kg2)
        events = []
        kg1.subscribe(events.append)
        kg1.apply_diff(diff)

        removed_types = [ev.event_type for ev in events]
        assert GraphEventType.ENTITY_REMOVED in removed_types

    def test_apply_diff_fires_entity_added(self):
        from ipfs_datasets_py.knowledge_graphs.extraction import (
            GraphEventType, KnowledgeGraph,
        )
        kg1 = KnowledgeGraph("orig")
        kg2 = KnowledgeGraph("updated")
        kg2.add_entity("person", "Charlie")

        diff = kg1.diff(kg2)
        events = []
        kg1.subscribe(events.append)
        kg1.apply_diff(diff)

        assert any(ev.event_type == GraphEventType.ENTITY_ADDED for ev in events)

    def test_apply_diff_fires_entity_modified(self):
        """Entities with the same fingerprint but changed properties fire ENTITY_MODIFIED."""
        from ipfs_datasets_py.knowledge_graphs.extraction import (
            GraphEventType, KnowledgeGraph,
        )
        # Build two independent graphs with same entity fingerprint but different props
        kg1 = KnowledgeGraph("orig")
        kg1.add_entity("person", "Alice", properties={"age": 30})
        kg2 = KnowledgeGraph("updated")
        kg2.add_entity("person", "Alice", properties={"age": 31})

        diff = kg1.diff(kg2)
        assert diff.modified_entities, "diff should detect property change"

        events = []
        kg1.subscribe(events.append)
        kg1.apply_diff(diff)

        assert any(ev.event_type == GraphEventType.ENTITY_MODIFIED for ev in events)

    def test_faulty_subscriber_does_not_crash(self):
        kg, _ = self._setup()
        kg.subscribe(lambda e: 1 / 0)  # always raises ZeroDivisionError
        # Should not raise
        kg.add_entity("person", "Alice")


# ═══════════════════════════════════════════════════════════════════════════
# Part 4 — Snapshot API
# ═══════════════════════════════════════════════════════════════════════════


class TestSnapshotAPI:
    """snapshot() / get_snapshot() / list_snapshots() / restore_snapshot()."""

    def _kg(self):
        from ipfs_datasets_py.knowledge_graphs.extraction import KnowledgeGraph
        kg = KnowledgeGraph("snap_test")
        kg.add_entity("person", "Alice")
        kg.add_entity("person", "Bob")
        return kg

    def test_snapshot_returns_name(self):
        kg = self._kg()
        name = kg.snapshot("v1")
        assert name == "v1"

    def test_snapshot_auto_name(self):
        kg = self._kg()
        name = kg.snapshot()
        assert name.startswith("snap_")
        assert len(name) == len("snap_") + 8

    def test_list_snapshots_empty(self):
        from ipfs_datasets_py.knowledge_graphs.extraction import KnowledgeGraph
        kg = KnowledgeGraph("empty")
        assert kg.list_snapshots() == []

    def test_list_snapshots_sorted(self):
        kg = self._kg()
        kg.snapshot("b")
        kg.snapshot("a")
        kg.snapshot("c")
        assert kg.list_snapshots() == ["a", "b", "c"]

    def test_get_snapshot_returns_copy(self):
        kg = self._kg()
        kg.snapshot("v1")
        snap = kg.get_snapshot("v1")
        assert snap is not None
        assert "entities" in snap
        assert "relationships" in snap
        assert len(snap["entities"]) == 2

    def test_get_snapshot_missing_returns_none(self):
        kg = self._kg()
        assert kg.get_snapshot("nonexistent") is None

    def test_restore_snapshot_returns_true(self):
        kg = self._kg()
        kg.snapshot("v1")
        assert kg.restore_snapshot("v1") is True

    def test_restore_snapshot_missing_returns_false(self):
        kg = self._kg()
        assert kg.restore_snapshot("missing") is False

    def test_restore_reverts_additions(self):
        kg = self._kg()
        kg.snapshot("before")
        kg.add_entity("org", "Acme")
        assert len(kg.entities) == 3
        kg.restore_snapshot("before")
        assert len(kg.entities) == 2

    def test_restore_reverts_removals_via_diff(self):
        from ipfs_datasets_py.knowledge_graphs.extraction import KnowledgeGraph
        kg = KnowledgeGraph("rev_test")
        kg.add_entity("person", "Alice")
        kg.add_entity("person", "Bob")
        kg.snapshot("full")

        kg2 = KnowledgeGraph("empty")
        diff = kg.diff(kg2)
        kg.apply_diff(diff)
        assert len(kg.entities) == 0

        kg.restore_snapshot("full")
        assert len(kg.entities) == 2

    def test_snapshot_relationships_preserved(self):
        from ipfs_datasets_py.knowledge_graphs.extraction import KnowledgeGraph
        kg = KnowledgeGraph("rel_snap")
        e1 = kg.add_entity("person", "Alice")
        e2 = kg.add_entity("person", "Bob")
        kg.add_relationship("knows", e1, e2)
        kg.snapshot("with_rel")
        kg.restore_snapshot("with_rel")
        assert len(kg.relationships) == 1

    def test_restore_rebuilds_indexes(self):
        kg = self._kg()
        kg.snapshot("v1")
        kg.add_entity("org", "Acme")
        kg.restore_snapshot("v1")
        persons = kg.get_entities_by_type("person")
        assert len(persons) == 2


# ═══════════════════════════════════════════════════════════════════════════
# Part 5 — Documentation integrity
# ═══════════════════════════════════════════════════════════════════════════


class TestDeferredFeaturesDoc:
    """DEFERRED_FEATURES.md acknowledges §17 and §18."""

    def _text(self):
        return _read(_KG_ROOT / "DEFERRED_FEATURES.md")

    def test_graph_event_subscriptions_entry(self):
        text = self._text()
        assert "Graph Event Subscription" in text or "GraphEvent" in text

    def test_kg_snapshots_entry(self):
        text = self._text()
        assert "snapshot" in text.lower()


class TestRoadmapDoc:
    """ROADMAP.md acknowledges v3.22.25 delivery."""

    def _text(self):
        return _read(_KG_ROOT / "ROADMAP.md")

    def test_v3_22_25_row_present(self):
        assert "3.22.25" in self._text()

    def test_real_time_streaming_delivered(self):
        text = self._text()
        # Either "real-time" or "streaming" or "event" mentioned as delivered
        assert "streaming" in text.lower() or "event" in text.lower()


class TestVersionAgreement:
    """MASTER_STATUS.md, CHANGELOG, and ROADMAP agree on the current version."""

    def test_master_status_version(self):
        text = _read(_KG_ROOT / "MASTER_STATUS.md")
        assert "3.22.25" in text

    def test_changelog_version(self):
        text = _read(_KG_ROOT / "CHANGELOG_KNOWLEDGE_GRAPHS.md")
        assert "3.22.25" in text

    def test_roadmap_current_version(self):
        text = _read(_KG_ROOT / "ROADMAP.md")
        assert "3.22.25" in text


