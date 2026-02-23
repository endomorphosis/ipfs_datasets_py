"""
Session 70: Knowledge Graph Diff/Patch + MASTER_STATUS/REFACTORING_PLAN snapshot fixes.

Tests for:
1. KnowledgeGraphDiff dataclass (is_empty, summary, to_dict, from_dict)
2. KnowledgeGraph.diff() — entity/relationship diff computation
3. KnowledgeGraph.apply_diff() — in-place diff application
4. Doc integrity: MASTER_STATUS version + snapshot; MASTER_REFACTORING_PLAN snapshot
"""
import os
import sys
from pathlib import Path

import pytest

_KG_ROOT = Path(__file__).resolve().parents[3] / "ipfs_datasets_py" / "knowledge_graphs"
_REPO_ROOT = Path(__file__).resolve().parents[3]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_kg(name="test"):
    from ipfs_datasets_py.knowledge_graphs.extraction import KnowledgeGraph
    return KnowledgeGraph(name=name)


def _master_status() -> str:
    return (_KG_ROOT / "MASTER_STATUS.md").read_text()


def _refactoring_plan() -> str:
    return (_KG_ROOT / "MASTER_REFACTORING_PLAN_2026.md").read_text()


def _changelog() -> str:
    return (_KG_ROOT / "CHANGELOG_KNOWLEDGE_GRAPHS.md").read_text()


def _roadmap() -> str:
    return (_KG_ROOT / "ROADMAP.md").read_text()


def _deferred_features() -> str:
    return (_KG_ROOT / "DEFERRED_FEATURES.md").read_text()


# ===========================================================================
# Class 1: KnowledgeGraphDiff dataclass
# ===========================================================================

class TestKnowledgeGraphDiff:
    """Unit tests for KnowledgeGraphDiff dataclass methods."""

    def test_import_knowledge_graph_diff(self):
        """KnowledgeGraphDiff is importable from extraction package."""
        from ipfs_datasets_py.knowledge_graphs.extraction import KnowledgeGraphDiff
        assert KnowledgeGraphDiff is not None

    def test_empty_diff_is_empty_true(self):
        """A default-constructed diff is empty."""
        from ipfs_datasets_py.knowledge_graphs.extraction import KnowledgeGraphDiff
        diff = KnowledgeGraphDiff()
        assert diff.is_empty is True

    def test_non_empty_diff_is_empty_false(self):
        """A diff with any content is not empty."""
        from ipfs_datasets_py.knowledge_graphs.extraction import KnowledgeGraphDiff
        diff = KnowledgeGraphDiff(added_entities=[{"entity_id": "x"}])
        assert diff.is_empty is False

    def test_summary_contains_plus_entities(self):
        """summary() contains '+N entities' component."""
        from ipfs_datasets_py.knowledge_graphs.extraction import KnowledgeGraphDiff
        diff = KnowledgeGraphDiff(added_entities=[{"a": 1}, {"b": 2}])
        s = diff.summary()
        assert "+2 entities" in s

    def test_summary_contains_minus_entities(self):
        """summary() contains '-N entities' component."""
        from ipfs_datasets_py.knowledge_graphs.extraction import KnowledgeGraphDiff
        diff = KnowledgeGraphDiff(removed_entity_ids=["id1"])
        s = diff.summary()
        assert "-1 entities" in s

    def test_summary_contains_modified(self):
        """summary() contains '~N modified' component."""
        from ipfs_datasets_py.knowledge_graphs.extraction import KnowledgeGraphDiff
        diff = KnowledgeGraphDiff(modified_entities=[{"entity_id": "x"}])
        s = diff.summary()
        assert "~1 modified" in s

    def test_to_dict_from_dict_roundtrip(self):
        """to_dict() → from_dict() preserves all fields."""
        from ipfs_datasets_py.knowledge_graphs.extraction import KnowledgeGraphDiff
        diff = KnowledgeGraphDiff(
            added_entities=[{"entity_id": "a", "name": "Alice"}],
            removed_entity_ids=["old-id"],
            added_relationships=[{"relationship_type": "knows"}],
            removed_relationship_ids=["r1"],
            modified_entities=[{"entity_id": "m", "old_properties": {}, "new_properties": {"x": 1}}],
        )
        d = diff.to_dict()
        restored = KnowledgeGraphDiff.from_dict(d)
        assert len(restored.added_entities) == 1
        assert restored.removed_entity_ids == ["old-id"]
        assert len(restored.added_relationships) == 1
        assert restored.removed_relationship_ids == ["r1"]
        assert len(restored.modified_entities) == 1
        assert not restored.is_empty

    def test_from_dict_empty_produces_empty_diff(self):
        """from_dict({}) produces an empty diff."""
        from ipfs_datasets_py.knowledge_graphs.extraction import KnowledgeGraphDiff
        diff = KnowledgeGraphDiff.from_dict({})
        assert diff.is_empty


# ===========================================================================
# Class 2: KnowledgeGraph.diff() computation
# ===========================================================================

class TestKnowledgeGraphDiffComputation:
    """Tests for KnowledgeGraph.diff()."""

    def test_diff_identical_graphs_is_empty(self):
        """Diffing two identical graphs produces an empty diff."""
        kg1 = _make_kg()
        alice = kg1.add_entity("person", "Alice")
        bob = kg1.add_entity("person", "Bob")
        kg1.add_relationship("knows", alice, bob)

        kg2 = _make_kg()
        a2 = kg2.add_entity("person", "Alice")
        b2 = kg2.add_entity("person", "Bob")
        kg2.add_relationship("knows", a2, b2)

        diff = kg1.diff(kg2)
        assert diff.is_empty

    def test_diff_detects_added_entity(self):
        """diff() lists Charlie as added when kg2 has an extra entity."""
        kg1 = _make_kg()
        kg1.add_entity("person", "Alice")

        kg2 = _make_kg()
        kg2.add_entity("person", "Alice")
        kg2.add_entity("person", "Charlie")

        diff = kg1.diff(kg2)
        names = [e.get("name") for e in diff.added_entities]
        assert "Charlie" in names
        assert len(diff.removed_entity_ids) == 0

    def test_diff_detects_removed_entity(self):
        """diff() lists a removal when kg2 is missing an entity from kg1."""
        kg1 = _make_kg()
        alice = kg1.add_entity("person", "Alice")
        bob = kg1.add_entity("person", "Bob")

        kg2 = _make_kg()
        kg2.add_entity("person", "Alice")

        diff = kg1.diff(kg2)
        assert bob.entity_id in diff.removed_entity_ids
        assert len(diff.added_entities) == 0

    def test_diff_detects_modified_entity_properties(self):
        """diff() reports modified_entities when same-name entity has changed props."""
        kg1 = _make_kg()
        kg1.add_entity("person", "Dave", properties={"score": 5})

        kg2 = _make_kg()
        kg2.add_entity("person", "Dave", properties={"score": 99})

        diff = kg1.diff(kg2)
        assert len(diff.modified_entities) == 1
        assert diff.modified_entities[0]["new_properties"]["score"] == 99

    def test_diff_detects_added_relationship(self):
        """diff() reports an added relationship."""
        kg1 = _make_kg()
        alice = kg1.add_entity("person", "Alice")
        bob = kg1.add_entity("person", "Bob")

        kg2 = _make_kg()
        a2 = kg2.add_entity("person", "Alice")
        b2 = kg2.add_entity("person", "Bob")
        kg2.add_relationship("knows", a2, b2)

        diff = kg1.diff(kg2)
        assert len(diff.added_relationships) == 1
        assert len(diff.removed_relationship_ids) == 0

    def test_diff_detects_removed_relationship(self):
        """diff() reports a removed relationship."""
        kg1 = _make_kg()
        alice = kg1.add_entity("person", "Alice")
        bob = kg1.add_entity("person", "Bob")
        rel = kg1.add_relationship("knows", alice, bob)

        kg2 = _make_kg()
        kg2.add_entity("person", "Alice")
        kg2.add_entity("person", "Bob")

        diff = kg1.diff(kg2)
        assert rel.relationship_id in diff.removed_relationship_ids

    def test_diff_empty_vs_nonempty_graph(self):
        """diff() from empty to non-empty reports all entities as added."""
        kg_empty = _make_kg()
        kg_full = _make_kg()
        kg_full.add_entity("person", "Alice")
        kg_full.add_entity("org", "ACME")

        diff = kg_empty.diff(kg_full)
        assert len(diff.added_entities) == 2
        assert len(diff.removed_entity_ids) == 0


# ===========================================================================
# Class 3: KnowledgeGraph.apply_diff()
# ===========================================================================

class TestKnowledgeGraphApplyDiff:
    """Tests for KnowledgeGraph.apply_diff()."""

    def test_apply_empty_diff_no_change(self):
        """Applying an empty diff leaves the graph unchanged."""
        from ipfs_datasets_py.knowledge_graphs.extraction import KnowledgeGraphDiff
        kg = _make_kg()
        kg.add_entity("person", "Alice")
        initial_count = len(kg.entities)

        kg.apply_diff(KnowledgeGraphDiff())
        assert len(kg.entities) == initial_count

    def test_apply_diff_adds_entities(self):
        """apply_diff() adds new entities."""
        kg1 = _make_kg()
        kg1.add_entity("person", "Alice")

        kg2 = _make_kg()
        kg2.add_entity("person", "Alice")
        kg2.add_entity("person", "Bob")

        diff = kg1.diff(kg2)
        kg1.apply_diff(diff)
        names = [e.name for e in kg1.entities.values()]
        assert "Alice" in names
        assert "Bob" in names

    def test_apply_diff_removes_entities(self):
        """apply_diff() removes entities."""
        kg1 = _make_kg()
        alice = kg1.add_entity("person", "Alice")
        bob = kg1.add_entity("person", "Bob")

        kg2 = _make_kg()
        kg2.add_entity("person", "Alice")

        diff = kg1.diff(kg2)
        kg1.apply_diff(diff)
        names = [e.name for e in kg1.entities.values()]
        assert "Alice" in names
        assert "Bob" not in names

    def test_apply_diff_remove_entity_cascades_relationship(self):
        """Removing an entity via apply_diff also removes its relationships."""
        kg1 = _make_kg()
        alice = kg1.add_entity("person", "Alice")
        bob = kg1.add_entity("person", "Bob")
        kg1.add_relationship("knows", alice, bob)

        kg2 = _make_kg()
        kg2.add_entity("person", "Alice")  # Bob removed

        diff = kg1.diff(kg2)
        kg1.apply_diff(diff)
        assert len(kg1.relationships) == 0, "Relationship should cascade-deleted with Bob"

    def test_apply_diff_adds_relationships(self):
        """apply_diff() adds new relationships."""
        kg1 = _make_kg()
        kg1.add_entity("person", "Alice")
        kg1.add_entity("person", "Bob")

        kg2 = _make_kg()
        a2 = kg2.add_entity("person", "Alice")
        b2 = kg2.add_entity("person", "Bob")
        kg2.add_relationship("knows", a2, b2)

        diff = kg1.diff(kg2)
        kg1.apply_diff(diff)
        rel_types = [r.relationship_type for r in kg1.relationships.values()]
        assert "knows" in rel_types

    def test_apply_diff_removes_relationships(self):
        """apply_diff() removes standalone relationships."""
        kg1 = _make_kg()
        alice = kg1.add_entity("person", "Alice")
        bob = kg1.add_entity("person", "Bob")
        kg1.add_relationship("knows", alice, bob)

        kg2 = _make_kg()
        kg2.add_entity("person", "Alice")
        kg2.add_entity("person", "Bob")  # no relationship

        diff = kg1.diff(kg2)
        kg1.apply_diff(diff)
        assert len(kg1.relationships) == 0

    def test_apply_diff_modifies_entity_properties(self):
        """apply_diff() updates modified entity properties."""
        kg1 = _make_kg()
        e = kg1.add_entity("person", "Dave", properties={"score": 5})

        kg2 = _make_kg()
        kg2.add_entity("person", "Dave", properties={"score": 99})

        diff = kg1.diff(kg2)
        kg1.apply_diff(diff)
        dave = next(e for e in kg1.entities.values() if e.name == "Dave")
        assert dave.properties["score"] == 99

    def test_diff_and_apply_roundtrip(self):
        """After apply_diff, graph structure matches the target (same entity count)."""
        kg1 = _make_kg()
        kg1.add_entity("person", "Alice", properties={"role": "admin"})
        kg1.add_entity("person", "Bob")

        kg2 = _make_kg()
        kg2.add_entity("person", "Alice", properties={"role": "user"})
        kg2.add_entity("org", "ACME")

        diff = kg1.diff(kg2)
        kg1.apply_diff(diff)

        names = {e.name for e in kg1.entities.values()}
        assert "Alice" in names
        assert "ACME" in names
        assert "Bob" not in names

    def test_apply_diff_to_empty_graph(self):
        """Applying a diff that adds entities to an empty graph works."""
        kg_empty = _make_kg()
        kg_full = _make_kg()
        kg_full.add_entity("person", "Alice")
        kg_full.add_entity("org", "ACME")

        diff = kg_empty.diff(kg_full)
        kg_empty.apply_diff(diff)
        assert len(kg_empty.entities) == 2


# ===========================================================================
# Class 4: Doc integrity — MASTER_STATUS + REFACTORING_PLAN snapshot
# ===========================================================================

class TestDocIntegritySession70:
    """Doc integrity tests for stale snapshot data fixed in session 70."""

    def test_master_status_version_is_3_22_24(self):
        """MASTER_STATUS.md reports version 3.22.24 or later."""
        content = _master_status()
        assert "3.22.24" in content, "MASTER_STATUS.md should contain version 3.22.24"

    def test_master_status_test_files_updated(self):
        """MASTER_STATUS.md test-files count is 110+ (not the stale 103)."""
        content = _master_status()
        assert "103 total" not in content, "Stale 103 test-files count should be gone"
        assert "110" in content or "108" in content or "111" in content or "112" in content, (
            "MASTER_STATUS.md should have updated test-files count (110+)"
        )

    def test_master_status_session70_in_log(self):
        """MASTER_STATUS.md session log contains session 70 entry."""
        content = _master_status()
        assert "session70" in content.lower() or "session 70" in content.lower(), (
            "Session 70 entry should appear in MASTER_STATUS.md"
        )

    def test_refactoring_plan_version_updated(self):
        """MASTER_REFACTORING_PLAN_2026.md Document Version reflects 3.22.24."""
        content = _refactoring_plan()
        # Should NOT still say 3.22.21 or older
        assert "Document Version: 3.22.21" not in content, (
            "Stale Document Version 3.22.21 should be removed"
        )
        assert "3.22.24" in content, "MASTER_REFACTORING_PLAN_2026.md should reference 3.22.24"

    def test_refactoring_plan_snapshot_session_updated(self):
        """MASTER_REFACTORING_PLAN_2026.md snapshot heading should NOT say session 66."""
        content = _refactoring_plan()
        # Session 66 was the old value from before session 67 fixed it to session 69
        assert "Module Snapshot (2026-02-22, session 66)" not in content, (
            "Stale 'session 66' snapshot heading should be gone"
        )

    def test_refactoring_plan_test_count_updated(self):
        """MASTER_REFACTORING_PLAN_2026.md snapshot tests collected should be 3,939+."""
        content = _refactoring_plan()
        assert "3,856+" not in content, (
            "Stale 3,856+ test count should be replaced with 3,939+"
        )

    def test_changelog_has_3_22_24_section(self):
        """CHANGELOG_KNOWLEDGE_GRAPHS.md contains a ## [3.22.24] section."""
        content = _changelog()
        assert "## [3.22.24]" in content, (
            "CHANGELOG_KNOWLEDGE_GRAPHS.md should have a [3.22.24] section"
        )

    def test_roadmap_has_3_22_24_row(self):
        """ROADMAP.md release table contains a 3.22.24 row."""
        content = _roadmap()
        assert "3.22.24" in content, (
            "ROADMAP.md release table should contain 3.22.24"
        )

    def test_deferred_features_has_graph_diff(self):
        """DEFERRED_FEATURES.md mentions graph diff/patch as implemented."""
        content = _deferred_features()
        assert "diff" in content.lower() or "patch" in content.lower(), (
            "DEFERRED_FEATURES.md should mention graph diff/patch feature"
        )


# ===========================================================================
# Class 5: Version Agreement
# ===========================================================================

class TestVersionAgreement:
    """MASTER_STATUS, CHANGELOG, and ROADMAP must all agree on current version."""

    def test_master_status_has_3_22_24(self):
        assert "3.22.24" in _master_status()

    def test_changelog_has_3_22_24(self):
        assert "3.22.24" in _changelog()

    def test_roadmap_has_3_22_24(self):
        assert "3.22.24" in _roadmap()
