"""Unit tests for ontology diff utilities.

Tests the diff_ontologies, format_diff, and compute_diff_stats functions.
"""

import pytest
from ipfs_datasets_py.optimizers.graphrag.ontology_diff import (
    diff_ontologies,
    format_diff,
    compute_diff_stats,
    DiffResult,
)


class TestDiffOntologies:
    """Test the diff_ontologies function."""

    def test_empty_ontologies(self):
        """Test diffing two empty ontologies."""
        before = {"entities": [], "relationships": []}
        after = {"entities": [], "relationships": []}
        
        diff = diff_ontologies(before, after)
        
        assert not diff.has_changes
        assert diff.total_changes == 0
        assert len(diff.entities_added) == 0
        assert len(diff.entities_removed) == 0

    def test_entity_added(self):
        """Test detecting added entities."""
        before = {"entities": [], "relationships": []}
        after = {
            "entities": [{"id": "e1", "type": "Person", "text": "Alice"}],
            "relationships": [],
        }
        
        diff = diff_ontologies(before, after)
        
        assert diff.has_changes
        assert len(diff.entities_added) == 1
        assert diff.entities_added[0]["id"] == "e1"

    def test_entity_removed(self):
        """Test detecting removed entities."""
        before = {
            "entities": [{"id": "e1", "type": "Person", "text": "Alice"}],
            "relationships": [],
        }
        after = {"entities": [], "relationships": []}
        
        diff = diff_ontologies(before, after)
        
        assert diff.has_changes
        assert len(diff.entities_removed) == 1
        assert diff.entities_removed[0]["id"] == "e1"

    def test_entity_modified_text(self):
        """Test detecting entity text changes."""
        before = {
            "entities": [{"id": "e1", "type": "Person", "text": "Alice"}],
            "relationships": [],
        }
        after = {
            "entities": [{"id": "e1", "type": "Person", "text": "Alice Smith"}],
            "relationships": [],
        }
        
        diff = diff_ontologies(before, after)
        
        assert diff.has_changes
        assert len(diff.entities_modified) == 1
        assert diff.entities_modified[0]["id"] == "e1"
        assert diff.entities_modified[0]["before"]["text"] == "Alice"
        assert diff.entities_modified[0]["after"]["text"] == "Alice Smith"

    def test_entity_modified_type(self):
        """Test detecting entity type changes."""
        before = {
            "entities": [{"id": "e1", "type": "Person", "text": "Alice"}],
            "relationships": [],
        }
        after = {
            "entities": [{"id": "e1", "type": "Organization", "text": "Alice"}],
            "relationships": [],
        }
        
        diff = diff_ontologies(before, after)
        
        assert len(diff.entities_modified) == 1

    def test_entity_modified_confidence(self):
        """Test detecting confidence changes."""
        before = {
            "entities": [{"id": "e1", "type": "Person", "text": "Alice", "confidence": 0.8}],
            "relationships": [],
        }
        after = {
            "entities": [{"id": "e1", "type": "Person", "text": "Alice", "confidence": 0.95}],
            "relationships": [],
        }
        
        diff = diff_ontologies(before, after, compare_confidence=True, confidence_threshold=0.01)
        
        assert len(diff.entities_modified) == 1

    def test_entity_confidence_below_threshold(self):
        """Test that small confidence changes are ignored with threshold."""
        before = {
            "entities": [{"id": "e1", "type": "Person", "text": "Alice", "confidence": 0.8}],
            "relationships": [],
        }
        after = {
            "entities": [{"id": "e1", "type": "Person", "text": "Alice", "confidence": 0.805}],
            "relationships": [],
        }
        
        diff = diff_ontologies(before, after, compare_confidence=True, confidence_threshold=0.01)
        
        # 0.005 change is below 0.01 threshold
        assert len(diff.entities_modified) == 0

    def test_entity_confidence_ignored(self):
        """Test that confidence changes are ignored when compare_confidence=False."""
        before = {
            "entities": [{"id": "e1", "type": "Person", "text": "Alice", "confidence": 0.5}],
            "relationships": [],
        }
        after = {
            "entities": [{"id": "e1", "type": "Person", "text": "Alice", "confidence": 0.99}],
            "relationships": [],
        }
        
        diff = diff_ontologies(before, after, compare_confidence=False)
        
        assert len(diff.entities_modified) == 0

    def test_entity_properties_modified(self):
        """Test detecting property changes."""
        before = {
            "entities": [
                {"id": "e1", "type": "Person", "text": "Alice", "properties": {"age": 30}}
            ],
            "relationships": [],
        }
        after = {
            "entities": [
                {"id": "e1", "type": "Person", "text": "Alice", "properties": {"age": 31}}
            ],
            "relationships": [],
        }
        
        diff = diff_ontologies(before, after)
        
        assert len(diff.entities_modified) == 1

    def test_relationship_added(self):
        """Test detecting added relationships."""
        before = {"entities": [], "relationships": []}
        after = {
            "entities": [],
            "relationships": [
                {"id": "r1", "source_id": "e1", "target_id": "e2", "type": "knows"}
            ],
        }
        
        diff = diff_ontologies(before, after)
        
        assert len(diff.relationships_added) == 1
        assert diff.relationships_added[0]["id"] == "r1"

    def test_relationship_removed(self):
        """Test detecting removed relationships."""
        before = {
            "entities": [],
            "relationships": [
                {"id": "r1", "source_id": "e1", "target_id": "e2", "type": "knows"}
            ],
        }
        after = {"entities": [], "relationships": []}
        
        diff = diff_ontologies(before, after)
        
        assert len(diff.relationships_removed) == 1

    def test_relationship_modified(self):
        """Test detecting relationship modifications."""
        before = {
            "entities": [],
            "relationships": [
                {"id": "r1", "source_id": "e1", "target_id": "e2", "type": "knows"}
            ],
        }
        after = {
            "entities": [],
            "relationships": [
                {"id": "r1", "source_id": "e1", "target_id": "e2", "type": "works_with"}
            ],
        }
        
        diff = diff_ontologies(before, after)
        
        assert len(diff.relationships_modified) == 1

    def test_complex_diff(self):
        """Test a complex diff with multiple changes."""
        before = {
            "entities": [
                {"id": "e1", "type": "Person", "text": "Alice"},
                {"id": "e2", "type": "Organization", "text": "ACME"},
            ],
            "relationships": [
                {"id": "r1", "source_id": "e1", "target_id": "e2", "type": "works_for"}
            ],
        }
        after = {
            "entities": [
                {"id": "e1", "type": "Person", "text": "Alice Smith"},  # modified
                {"id": "e3", "type": "Location", "text": "NYC"},  # added
            ],
            "relationships": [
                {"id": "r2", "source_id": "e1", "target_id": "e3", "type": "lives_in"}  # added
                # r1 removed
            ],
        }
        
        diff = diff_ontologies(before, after)
        
        assert diff.has_changes
        assert len(diff.entities_added) == 1  # e3
        assert len(diff.entities_removed) == 1  # e2
        assert len(diff.entities_modified) == 1  # e1
        assert len(diff.relationships_added) == 1  # r2
        assert len(diff.relationships_removed) == 1  # r1
        assert diff.total_changes == 5


class TestFormatDiff:
    """Test the format_diff function."""

    def test_format_empty_diff(self):
        """Test formatting an empty diff."""
        diff = DiffResult()
        formatted = format_diff(diff)
        
        assert "Ontology Diff" in formatted
        assert "+0 added" in formatted
        assert "-0 removed" in formatted

    def test_format_simple_diff(self):
        """Test formatting a simple diff."""
        diff = DiffResult(
            entities_added=[{"id": "e1", "type": "Person", "text": "Alice"}],
            entities_removed=[],
        )
        formatted = format_diff(diff)
        
        assert "+1 added" in formatted
        assert "Total changes: 1" in formatted

    def test_format_verbose(self):
        """Test verbose formatting with details."""
        diff = DiffResult(
            entities_added=[{"id": "e1", "type": "Person", "text": "Alice"}],
            relationships_removed=[{"id": "r1", "source_id": "e1", "target_id": "e2", "type": "knows"}],
        )
        formatted = format_diff(diff, verbose=True)
        
        assert "Entities Added:" in formatted
        assert "e1: Alice (Person)" in formatted
        assert "Relationships Removed:" in formatted
        assert "r1:" in formatted

    def test_format_modified_entities(self):
        """Test formatting entity modifications."""
        diff = DiffResult(
            entities_modified=[
                {
                    "id": "e1",
                    "before": {"id": "e1", "text": "Alice", "confidence": 0.8},
                    "after": {"id": "e1", "text": "Alice Smith", "confidence": 0.95},
                }
            ]
        )
        formatted = format_diff(diff, verbose=True)
        
        assert "Entities Modified:" in formatted
        assert "e1:" in formatted
        assert "text: Alice → Alice Smith" in formatted
        assert "confidence: 0.8 → 0.95" in formatted


class TestComputeDiffStats:
    """Test the compute_diff_stats function."""

    def test_stats_no_changes(self):
        """Test stats for no changes."""
        diff = DiffResult()
        stats = compute_diff_stats(diff)
        
        assert stats["entities_net_change"] == 0
        assert stats["relationships_net_change"] == 0
        assert stats["has_changes"] is False
        assert stats["total_changes"] == 0

    def test_stats_entities_net_positive(self):
        """Test net positive entity change."""
        diff = DiffResult(
            entities_added=[{"id": "e1"}, {"id": "e2"}, {"id": "e3"}],
            entities_removed=[{"id": "e4"}],
        )
        stats = compute_diff_stats(diff)
        
        assert stats["entities_net_change"] == 2  # 3 added - 1 removed

    def test_stats_entities_net_negative(self):
        """Test net negative entity change."""
        diff = DiffResult(
            entities_added=[{"id": "e1"}],
            entities_removed=[{"id": "e2"}, {"id": "e3"}],
        )
        stats = compute_diff_stats(diff)
        
        assert stats["entities_net_change"] == -1  # 1 added - 2 removed

    def test_stats_modification_rate(self):
        """Test modification rate calculation."""
        diff = DiffResult(
            entities_added=[{"id": "e1"}],
            entities_modified=[{"id": "e2"}, {"id": "e3"}],
            relationships_added=[{"id": "r1"}],
        )
        stats = compute_diff_stats(diff)
        
        # 2 modified out of (1+2+1) = 4 items -> 0.5
        assert stats["modification_rate"] == pytest.approx(0.5)

    def test_stats_all_fields(self):
        """Test that all stat fields are present."""
        diff = DiffResult(
            entities_added=[{"id": "e1"}],
            relationships_removed=[{"id": "r1"}],
        )
        stats = compute_diff_stats(diff)
        
        assert "entities_net_change" in stats
        assert "relationships_net_change" in stats
        assert "modification_rate" in stats
        assert "has_changes" in stats
        assert "total_changes" in stats


class TestDiffResultProperties:
    """Test DiffResult dataclass properties."""

    def test_has_changes_true(self):
        """Test has_changes property returns True when changes exist."""
        diff = DiffResult(entities_added=[{"id": "e1"}])
        assert diff.has_changes is True

    def test_has_changes_false(self):
        """Test has_changes property returns False when no changes."""
        diff = DiffResult()
        assert diff.has_changes is False

    def test_total_changes(self):
        """Test total_changes property."""
        diff = DiffResult(
            entities_added=[{"id": "e1"}, {"id": "e2"}],
            entities_removed=[{"id": "e3"}],
            relationships_added=[{"id": "r1"}],
            relationships_modified=[{"id": "r2"}],
        )
        assert diff.total_changes == 5

    def test_total_changes_zero(self):
        """Test total_changes is zero for empty diff."""
        diff = DiffResult()
        assert diff.total_changes == 0


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_diff_missing_keys(self):
        """Test diffing ontologies with missing keys."""
        before = {}  # Missing entities and relationships
        after = {"entities": [{"id": "e1", "text": "Alice"}]}
        
        diff = diff_ontologies(before, after)
        
        assert len(diff.entities_added) == 1

    def test_diff_duplicate_ids(self):
        """Test behavior with duplicate IDs (last one wins)."""
        before = {
            "entities": [
                {"id": "e1", "text": "Alice"},
                {"id": "e1", "text": "Alice v2"},  # Duplicate
            ],
            "relationships": [],
        }
        after = {
            "entities": [{"id": "e1", "text": "Alice v3"}],
            "relationships": [],
        }
        
        diff = diff_ontologies(before, after)
        
        # Should compare against last version (Alice v2)
        assert len(diff.entities_modified) == 1

    def test_diff_none_values(self):
        """Test diffing with None values in properties."""
        before = {
            "entities": [{"id": "e1", "text": "Alice", "properties": None}],
            "relationships": [],
        }
        after = {
            "entities": [{"id": "e1", "text": "Alice", "properties": {}}],
            "relationships": [],
        }
        
        diff = diff_ontologies(before, after)
        
        # None vs {} should be considered different
        assert len(diff.entities_modified) == 1

    def test_format_diff_with_special_characters(self):
        """Test formatting with special characters in text."""
        diff = DiffResult(
            entities_added=[
                {"id": "e1", "type": "Person", "text": "Alice \"Ace\" Smith"}
            ]
        )
        formatted = format_diff(diff, verbose=True)
        
        assert 'Alice "Ace" Smith' in formatted

    def test_diff_relationship_direction_change(self):
        """Test detecting relationship direction changes."""
        before = {
            "entities": [],
            "relationships": [
                {
                    "id": "r1",
                    "source_id": "e1",
                    "target_id": "e2",
                    "type": "knows",
                    "direction": "subject_to_object",
                }
            ],
        }
        after = {
            "entities": [],
            "relationships": [
                {
                    "id": "r1",
                    "source_id": "e1",
                    "target_id": "e2",
                    "type": "knows",
                    "direction": "undirected",
                }
            ],
        }
        
        diff = diff_ontologies(before, after)
        
        assert len(diff.relationships_modified) == 1
