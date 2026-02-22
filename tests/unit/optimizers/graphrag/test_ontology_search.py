"""Unit tests for ontology search and querying utilities.

Tests the find_entities_by_*, find_relationships_by_*, find_path_between,
and other search functions.
"""

import pytest
from ipfs_datasets_py.optimizers.graphrag.ontology_search import (
    find_entities_by_type,
    find_entities_by_text,
    find_entities_by_property,
    find_relationships_by_type,
    find_entity_neighbors,
    find_path_between,
    count_entities_by_type,
    count_relationships_by_type,
    get_related_entities,
    SearchResult,
    PathResult,
)


class TestFindEntitiesByType:
    """Test the find_entities_by_type function."""

    def test_no_entities(self):
        """Test searching with no entities."""
        ontology = {"entities": []}
        
        result = find_entities_by_type(ontology, "Person")
        
        assert result.count == 0
        assert len(result.matches) == 0

    def test_find_single_type(self):
        """Test finding entities of a single type."""
        ontology = {
            "entities": [
                {"id": "e1", "type": "Person", "text": "Alice"},
                {"id": "e2", "type": "Person", "text": "Bob"},
                {"id": "e3", "type": "Location", "text": "NYC"},
            ]
        }
        
        result = find_entities_by_type(ontology, "Person")
        
        assert result.count == 2
        assert all(e["type"] == "Person" for e in result.matches)

    def test_find_no_matches(self):
        """Test when no entities match type."""
        ontology = {
            "entities": [{"id": "e1", "type": "Person"}]
        }
        
        result = find_entities_by_type(ontology, "Organization")
        
        assert result.count == 0

    def test_case_insensitive(self):
        """Test case-insensitive type matching."""
        ontology = {
            "entities": [{"id": "e1", "type": "Person"}]
        }
        
        result = find_entities_by_type(ontology, "person", case_sensitive=False)
        
        assert result.count == 1

    def test_case_sensitive_no_match(self):
        """Test case-sensitive type matching."""
        ontology = {
            "entities": [{"id": "e1", "type": "Person"}]
        }
        
        result = find_entities_by_type(ontology, "person", case_sensitive=True)
        
        assert result.count == 0


class TestFindEntitiesByText:
    """Test the find_entities_by_text function."""

    def test_exact_match(self):
        """Test finding entities with exact text match."""
        ontology = {
            "entities": [
                {"id": "e1", "text": "Alice Smith"},
                {"id": "e2", "text": "Bob Jones"},
            ]
        }
        
        result = find_entities_by_text(ontology, "Alice", regex=False)
        
        assert result.count == 1
        assert result.matches[0]["id"] == "e1"

    def test_substring_match(self):
        """Test substring matching."""
        ontology = {
            "entities": [
                {"id": "e1", "text": "Alice Smith"},
                {"id": "e2", "text": "Alice Jones"},
            ]
        }
        
        result = find_entities_by_text(ontology, "Alice", regex=False)
        
        assert result.count == 2

    def test_case_insensitive(self):
        """Test case-insensitive text matching."""
        ontology = {
            "entities": [{"id": "e1", "text": "Alice Smith"}]
        }
        
        result = find_entities_by_text(ontology, "alice", regex=False, case_sensitive=False)
        
        assert result.count == 1

    def test_regex_match(self):
        """Test regex pattern matching."""
        ontology = {
            "entities": [
                {"id": "e1", "text": "Alice"},
                {"id": "e2", "text": "Bob"},
                {"id": "e3", "text": "Albert"},
            ]
        }
        
        # Find names starting with A
        result = find_entities_by_text(ontology, "^A.*", regex=True)
        
        assert result.count == 2

    def test_no_text_field(self):
        """Test entities without text field."""
        ontology = {
            "entities": [
                {"id": "e1", "type": "Person"},  # No text
                {"id": "e2", "text": "Alice"},
            ]
        }
        
        result = find_entities_by_text(ontology, "Alice")
        
        assert result.count == 1

    def test_invalid_regex(self):
        """Test behavior with invalid regex pattern."""
        ontology = {
            "entities": [{"id": "e1", "text": "Alice"}]
        }
        
        # Invalid regex should not crash, treats as literal search
        result = find_entities_by_text(ontology, "[invalid(regex", regex=True)
        
        assert result.count == 0


class TestFindEntitiesByProperty:
    """Test the find_entities_by_property function."""

    def test_equal_match(self):
        """Test finding entities with property value."""
        ontology = {
            "entities": [
                {"id": "e1", "properties": {"age": 30}},
                {"id": "e2", "properties": {"age": 25}},
            ]
        }
        
        result = find_entities_by_property(ontology, "age", 30, operator="eq")
        
        assert result.count == 1

    def test_not_equal_match(self):
        """Test not equal operator."""
        ontology = {
            "entities": [
                {"id": "e1", "properties": {"status": "active"}},
                {"id": "e2", "properties": {"status": "inactive"}},
            ]
        }
        
        result = find_entities_by_property(ontology, "status", "inactive", operator="ne")
        
        assert result.count == 1

    def test_greater_than(self):
        """Test greater than operator."""
        ontology = {
            "entities": [
                {"id": "e1", "properties": {"score": 50}},
                {"id": "e2", "properties": {"score": 80}},
            ]
        }
        
        result = find_entities_by_property(ontology, "score", 60, operator="gt")
        
        assert result.count == 1

    def test_less_than(self):
        """Test less than operator."""
        ontology = {
            "entities": [
                {"id": "e1", "properties": {"score": 50}},
                {"id": "e2", "properties": {"score": 80}},
            ]
        }
        
        result = find_entities_by_property(ontology, "score", 60, operator="lt")
        
        assert result.count == 1

    def test_contains_operator(self):
        """Test contains operator for strings."""
        ontology = {
            "entities": [
                {"id": "e1", "properties": {"description": "A fast car"}},
                {"id": "e2", "properties": {"description": "A slow train"}},
            ]
        }
        
        result = find_entities_by_property(ontology, "description", "fast", operator="contains")
        
        assert result.count == 1

    def test_missing_property(self):
        """Test when entity lacks the property."""
        ontology = {
            "entities": [
                {"id": "e1", "properties": {"age": 30}},
                {"id": "e2", "properties": {"name": "Bob"}},  # Missing age
            ]
        }
        
        result = find_entities_by_property(ontology, "age", 30)
        
        assert result.count == 1


class TestFindRelationshipsByType:
    """Test the find_relationships_by_type function."""

    def test_find_single_type(self):
        """Test finding relationships of a type."""
        ontology = {
            "relationships": [
                {"id": "r1", "type": "knows"},
                {"id": "r2", "type": "knows"},
                {"id": "r3", "type": "works_at"},
            ]
        }
        
        result = find_relationships_by_type(ontology, "knows")
        
        assert result.count == 2

    def test_no_matches(self):
        """Test when no relationships match."""
        ontology = {
            "relationships": [{"id": "r1", "type": "knows"}]
        }
        
        result = find_relationships_by_type(ontology, "loves")
        
        assert result.count == 0

    def test_case_insensitive(self):
        """Test case-insensitive type matching."""
        ontology = {
            "relationships": [{"id": "r1", "type": "Knows"}]
        }
        
        result = find_relationships_by_type(ontology, "knows", case_sensitive=False)
        
        assert result.count == 1


class TestFindEntityNeighbors:
    """Test the find_entity_neighbors function."""

    def test_outgoing_only(self):
        """Test finding outgoing relationships."""
        ontology = {
            "relationships": [
                {"id": "r1", "source_id": "e1", "target_id": "e2"},
                {"id": "r2", "source_id": "e2", "target_id": "e1"},
            ]
        }
        
        neighbors = find_entity_neighbors(ontology, "e1", direction="out")
        
        assert len(neighbors) == 1
        assert neighbors[0]["id"] == "r1"

    def test_incoming_only(self):
        """Test finding incoming relationships."""
        ontology = {
            "relationships": [
                {"id": "r1", "source_id": "e1", "target_id": "e2"},
                {"id": "r2", "source_id": "e2", "target_id": "e1"},
            ]
        }
        
        neighbors = find_entity_neighbors(ontology, "e1", direction="in")
        
        assert len(neighbors) == 1
        assert neighbors[0]["id"] == "r2"

    def test_both_directions(self):
        """Test finding all relationships (both directions)."""
        ontology = {
            "relationships": [
                {"id": "r1", "source_id": "e1", "target_id": "e2"},
                {"id": "r2", "source_id": "e2", "target_id": "e1"},
                {"id": "r3", "source_id": "e1", "target_id": "e3"},
            ]
        }
        
        neighbors = find_entity_neighbors(ontology, "e1", direction="both")
        
        assert len(neighbors) == 3

    def test_no_neighbors(self):
        """Test entity with no relationships."""
        ontology = {
            "relationships": [
                {"id": "r1", "source_id": "e2", "target_id": "e3"}
            ]
        }
        
        neighbors = find_entity_neighbors(ontology, "e1", direction="both")
        
        assert len(neighbors) == 0


class TestFindPathBetween:
    """Test the find_path_between function."""

    def test_direct_connection(self):
        """Test finding direct connection."""
        ontology = {
            "relationships": [
                {"id": "r1", "source_id": "e1", "target_id": "e2"}
            ]
        }
        
        path = find_path_between(ontology, "e1", "e2")
        
        assert path.exists
        assert path.distance == 1
        assert path.path == ["e1", "e2"]

    def test_two_hops(self):
        """Test finding path with two hops."""
        ontology = {
            "relationships": [
                {"id": "r1", "source_id": "e1", "target_id": "e2"},
                {"id": "r2", "source_id": "e2", "target_id": "e3"},
            ]
        }
        
        path = find_path_between(ontology, "e1", "e3")
        
        assert path.exists
        assert path.distance == 2
        assert path.path == ["e1", "e2", "e3"]

    def test_no_path(self):
        """Test when no path exists."""
        ontology = {
            "relationships": [
                {"id": "r1", "source_id": "e1", "target_id": "e2"},
                {"id": "r2", "source_id": "e3", "target_id": "e4"},
            ]
        }
        
        path = find_path_between(ontology, "e1", "e4")
        
        assert not path.exists
        assert path.distance == 0

    def test_same_entity(self):
        """Test path from entity to itself."""
        path = find_path_between({"relationships": []}, "e1", "e1")
        
        # Single node isn't a path (exists requires path length > 1)
        assert not path.exists
        assert path.distance == 0
        assert path.path == ["e1"]

    def test_bidirectional_relationship(self):
        """Test path working both directions."""
        ontology = {
            "relationships": [
                {"id": "r1", "source_id": "e1", "target_id": "e2"}
            ]
        }
        
        # Forward direction
        path_forward = find_path_between(ontology, "e1", "e2")
        assert path_forward.exists
        
        # Reverse direction (should work with bidirectional search)
        path_reverse = find_path_between(ontology, "e2", "e1")
        assert path_reverse.exists


class TestCountEntitiesByType:
    """Test the count_entities_by_type function."""

    def test_empty(self):
        """Test with no entities."""
        ontology = {"entities": []}
        
        counts = count_entities_by_type(ontology)
        
        assert len(counts) == 0

    def test_single_type(self):
        """Test counting single entity type."""
        ontology = {
            "entities": [
                {"type": "Person"},
                {"type": "Person"},
                {"type": "Person"},
            ]
        }
        
        counts = count_entities_by_type(ontology)
        
        assert counts["Person"] == 3

    def test_multiple_types(self):
        """Test counting multiple entity types."""
        ontology = {
            "entities": [
                {"type": "Person"},
                {"type": "Person"},
                {"type": "Location"},
                {"type": "Organization"},
            ]
        }
        
        counts = count_entities_by_type(ontology)
        
        assert counts["Person"] == 2
        assert counts["Location"] == 1
        assert counts["Organization"] == 1


class TestCountRelationshipsByType:
    """Test the count_relationships_by_type function."""

    def test_empty(self):
        """Test with no relationships."""
        ontology = {"relationships": []}
        
        counts = count_relationships_by_type(ontology)
        
        assert len(counts) == 0

    def test_relationship_types(self):
        """Test counting relationship types."""
        ontology = {
            "relationships": [
                {"type": "knows"},
                {"type": "knows"},
                {"type": "works_at"},
            ]
        }
        
        counts = count_relationships_by_type(ontology)
        
        assert counts["knows"] == 2
        assert counts["works_at"] == 1


class TestGetRelatedEntities:
    """Test the get_related_entities function."""

    def test_find_related(self):
        """Test finding related entities."""
        ontology = {
            "entities": [
                {"id": "e1", "type": "Person"},
                {"id": "e2", "type": "Person"},
                {"id": "e3", "type": "Location"},
            ],
            "relationships": [
                {"id": "r1", "source_id": "e1", "target_id": "e2", "type": "knows"},
                {"id": "r2", "source_id": "e1", "target_id": "e3", "type": "lives_in"},
            ]
        }
        
        related = get_related_entities(ontology, "e1")
        
        assert len(related) == 2
        assert all(e["id"] in ("e2", "e3") for e in related)

    def test_filter_by_relationship_type(self):
        """Test filtering related entities by relationship type."""
        ontology = {
            "entities": [
                {"id": "e1", "type": "Person"},
                {"id": "e2", "type": "Person"},
                {"id": "e3", "type": "Location"},
            ],
            "relationships": [
                {"id": "r1", "source_id": "e1", "target_id": "e2", "type": "knows"},
                {"id": "r2", "source_id": "e1", "target_id": "e3", "type": "lives_in"},
            ]
        }
        
        related = get_related_entities(ontology, "e1", relationship_type="knows")
        
        assert len(related) == 1
        assert related[0]["id"] == "e2"

    def test_no_related(self):
        """Test entity with no related entities."""
        ontology = {
            "entities": [{"id": "e1"}],
            "relationships": [],
        }
        
        related = get_related_entities(ontology, "e1")
        
        assert len(related) == 0


class TestSearchResult:
    """Test the SearchResult dataclass."""

    def test_count_property(self):
        """Test count property."""
        result = SearchResult(
            matches=[{"id": "e1"}, {"id": "e2"}],
            query="test"
        )
        
        assert result.count == 2

    def test_repr(self):
        """Test __repr__ method."""
        result = SearchResult(matches=[{"id": "e1"}], query="test")
        repr_str = repr(result)
        
        assert "SearchResult" in repr_str
        assert "count=1" in repr_str


class TestPathResult:
    """Test the PathResult dataclass."""

    def test_distance_property(self):
        """Test distance property."""
        result = PathResult(
            path=["e1", "e2", "e3"],
            relationships=["r1", "r2"]
        )
        
        assert result.distance == 2

    def test_exists_property(self):
        """Test exists property."""
        result_exists = PathResult(path=["e1", "e2"])
        assert result_exists.exists
        
        result_empty = PathResult()
        assert not result_empty.exists

    def test_repr(self):
        """Test __repr__ method."""
        result = PathResult(path=["e1", "e2"], relationships=["r1"])
        repr_str = repr(result)
        
        assert "PathResult" in repr_str
        assert "distance=1" in repr_str


class TestEdgeCases:
    """Test edge cases."""

    def test_malformed_entities(self):
        """Test with non-dict entities."""
        ontology = {
            "entities": ["not a dict", {"id": "e1", "type": "Person"}]
        }
        
        result = find_entities_by_type(ontology, "Person")
        
        assert result.count == 1

    def test_malformed_relationships(self):
        """Test with non-dict relationships."""
        ontology = {
            "relationships": ["not a dict", {"id": "r1", "type": "knows"}]
        }
        
        result = find_relationships_by_type(ontology, "knows")
        
        assert result.count == 1

    def test_large_graph_path_search(self):
        """Test path search on a larger graph."""
        # Create a chain: e1 -> e2 -> e3 -> ... -> e10
        rels = [
            {"id": f"r{i}", "source_id": f"e{i}", "target_id": f"e{i+1}"}
            for i in range(1, 10)
        ]
        ontology = {"relationships": rels}
        
        # Path from e1 to e10 requires 9 hops
        path = find_path_between(ontology, "e1", "e10", max_depth=20)
        
        assert path.exists
        assert path.distance == 9
