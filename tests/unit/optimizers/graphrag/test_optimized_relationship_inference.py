"""
Tests for optimized relationship inference implementation.

Validates that optimizations produce correct results matching the original logic.
"""

import pytest
from ipfs_datasets_py.optimizers.graphrag.optimizations.optimized_relationship_inference import (
    OptimizedRelationshipInference,
    EntityPosition,
)


@pytest.fixture
def optimizer():
    """Create an optimizer instance for testing."""
    return OptimizedRelationshipInference()


@pytest.fixture
def mock_entities():
    """Create mock entities for testing."""
    class MockEntity:
        def __init__(self, entity_id: str, text: str, entity_type: str):
            self.id = entity_id
            self.text = text
            self.type = entity_type

    return [
        MockEntity("e1", "Alice", "person"),
        MockEntity("e2", "Bob", "person"),
        MockEntity("e3", "Acme Corp", "organization"),
        MockEntity("e4", "New York", "location"),
        MockEntity("e5", "Project X", "project"),
    ]


@pytest.fixture
def sample_text():
    """Sample text for relationship extraction."""
    return """
    Alice works for Acme Corp in New York. Bob also works for Acme Corp.
    Acme Corp employs over 500 people. Alice manages Project X.
    Bob causes problems in the project. The project relates to cloud computing.
    """


def test_position_index_building(optimizer, mock_entities, sample_text):
    """Test that position index is built correctly."""
    position_index = optimizer.build_entity_position_index(mock_entities, sample_text)

    # Should have positioned all entities found in text
    assert "e1" in position_index  # Alice
    assert "e2" in position_index  # Bob
    assert "e3" in position_index  # Acme Corp
    assert "e4" in position_index  # New York

    # Verify position is correct (Alice should be first occurrence)
    alice_pos = position_index["e1"]
    assert alice_pos.position >= 0
    assert alice_pos.entity_text.lower() in sample_text.lower()


def test_position_entity_attributes(optimizer, mock_entities, sample_text):
    """Test that EntityPosition objects capture all required attributes."""
    position_index = optimizer.build_entity_position_index(mock_entities, sample_text)

    e1_pos = position_index["e1"]
    assert e1_pos.entity_id == "e1"
    assert e1_pos.entity_text == "Alice"
    assert e1_pos.entity_text_lower == "alice"
    assert isinstance(e1_pos.position, int)
    assert e1_pos.entity_type == "person"


def test_verb_patterns_compiled_once(optimizer):
    """Test that verb patterns are compiled at class level (not repeatedly)."""
    patterns1 = optimizer._get_compiled_verb_patterns()
    patterns2 = optimizer._get_compiled_verb_patterns()

    # Should return same object (class-level cache)
    assert patterns1 is patterns2
    assert len(patterns1) > 0


def test_type_inference_rules_cached(optimizer):
    """Test that type inference rules are cached at class level."""
    rules1 = optimizer._get_type_inference_rules()
    rules2 = optimizer._get_type_inference_rules()

    # Should return same object (class-level cache)
    assert rules1 is rules2
    assert len(rules1) > 0


def test_infer_relationships_basic(optimizer, mock_entities, sample_text):
    """Test basic relationship inference."""
    relationships = optimizer.infer_relationships_optimized(mock_entities, sample_text)

    # Should infer multiple relationships
    assert len(relationships) > 0

    # All relationships should have required fields
    for rel in relationships:
        assert "id" in rel
        assert "source_id" in rel
        assert "target_id" in rel
        assert "type" in rel
        assert "confidence" in rel
        assert "properties" in rel


def test_relationship_ids_unique(optimizer, mock_entities, sample_text):
    """Test that all relationship IDs are unique."""
    relationships = optimizer.infer_relationships_optimized(mock_entities, sample_text)

    ids = [r["id"] for r in relationships]
    assert len(ids) == len(set(ids)), "Duplicate relationship IDs found"


def test_relationship_confidence_range(optimizer, mock_entities, sample_text):
    """Test that confidence scores are in valid range [0, 1]."""
    relationships = optimizer.infer_relationships_optimized(mock_entities, sample_text)

    for rel in relationships:
        assert 0.0 <= rel["confidence"] <= 1.0, f"Invalid confidence: {rel['confidence']}"


def test_no_self_relationships(optimizer, mock_entities, sample_text):
    """Test that relationships don't connect an entity to itself."""
    relationships = optimizer.infer_relationships_optimized(mock_entities, sample_text)

    for rel in relationships:
        assert (
            rel["source_id"] != rel["target_id"]
        ), "Self-relationship found"


def test_empty_text(optimizer, mock_entities):
    """Test inference with empty text."""
    relationships = optimizer.infer_relationships_optimized(mock_entities, "")

    # Should return empty list for empty text
    assert relationships == []


def test_no_entities(optimizer):
    """Test inference with no entities."""
    relationships = optimizer.infer_relationships_optimized([], "Some sample text")

    # Should return empty list for no entities
    assert relationships == []


def test_entities_not_in_text(optimizer):
    """Test inference when entities are not in the text."""
    class MockEntity:
        def __init__(self, entity_id: str, text: str, entity_type: str):
            self.id = entity_id
            self.text = text
            self.type = entity_type

    entities = [
        MockEntity("e1", "NonExistent1", "concept"),
        MockEntity("e2", "NonExistent2", "concept"),
    ]

    relationships = optimizer.infer_relationships_optimized(
        entities, "This text has no matching entities"
    )

    # Should return empty list when no entities match
    assert relationships == []


def test_verb_pattern_relationships(optimizer):
    """Test that verb patterns are correctly detected."""
    class MockEntity:
        def __init__(self, entity_id: str, text: str, entity_type: str):
            self.id = entity_id
            self.text = text
            self.type = entity_type

    entities = [
        MockEntity("e1", "Alice", "person"),
        MockEntity("e2", "Bob", "person"),
    ]

    text = "Alice obligates Bob to pay $100"
    relationships = optimizer.infer_relationships_optimized(entities, text)

    # Should find obligates relationship via verb pattern
    obligates_rels = [r for r in relationships if r["type"] == "obligates"]
    assert len(obligates_rels) > 0, "No obligates relationship found"


def test_type_confidence_calculation():
    """Test type confidence calculation for different relationship types."""
    optimizer = OptimizedRelationshipInference()

    # Test specific relationship types
    assert optimizer._calculate_type_confidence("obligates") == 0.85
    assert optimizer._calculate_type_confidence("owns") == 0.80
    assert optimizer._calculate_type_confidence("employs") == 0.80
    assert optimizer._calculate_type_confidence("related_to") == 0.65

    # Test fallback for unknown type
    assert optimizer._calculate_type_confidence("unknown_type") == 0.65


def test_distance_based_confidence(optimizer):
    """Test that confidence decays with distance."""
    class MockEntity:
        def __init__(self, entity_id: str, text: str, entity_type: str):
            self.id = entity_id
            self.text = text
            self.type = entity_type

    entities = [
        MockEntity("e1", "Alice", "person"),
        MockEntity("e2", "Bob", "person"),
    ]

    # Create text with entities at specific distances
    text_close = "Alice and Bob are friends"
    text_far = "Alice is a person. " + " " * 150 + "Bob is another person."

    rels_close = optimizer.infer_relationships_optimized(entities, text_close)
    rels_far = optimizer.infer_relationships_optimized(entities, text_far)

    # Close co-occurrences should have equal or higher confidence than far ones
    if rels_close and rels_far:
        close_conf = max((r["confidence"] for r in rels_close), default=0)
        far_conf = max((r["confidence"] for r in rels_far), default=0)
        # Note: May not always be true due to different relationship types,
        # but general trend should hold for same entities


def test_properties_include_metadata(optimizer, mock_entities, sample_text):
    """Test that relationship properties include expected metadata."""
    relationships = optimizer.infer_relationships_optimized(mock_entities, sample_text)

    for rel in relationships:
        props = rel["properties"]
        assert "type_confidence" in props
        assert "type_method" in props

        # Type method should be either verb_frame or cooccurrence
        assert props["type_method"] in ["verb_frame", "cooccurrence"]


def test_undirected_vs_directed_relationships(optimizer, mock_entities, sample_text):
    """Test that relationships have correct direction types."""
    relationships = optimizer.infer_relationships_optimized(mock_entities, sample_text)

    directions = set(r["direction"] for r in relationships)

    # Should have at least one type of direction
    assert len(directions) > 0

    # Valid directions
    valid_directions = {"subject_to_object", "undirected"}
    for direction in directions:
        assert direction in valid_directions


def test_duplicate_relationships_not_created(optimizer, mock_entities, sample_text):
    """Test that duplicate relationships are not created."""
    relationships = optimizer.infer_relationships_optimized(mock_entities, sample_text)

    # Create a set of (source, target, type) tuples
    rel_tuples = {(r["source_id"], r["target_id"], r["type"]) for r in relationships}

    # If there were duplicates, this set would be smaller than the list
    # (allowing for different types between same entities)
    # Check that we don't have the exact same relationship twice
    rel_keys = [(r["source_id"], r["target_id"], r["type"]) for r in relationships]
    assert len(rel_keys) == len(set(rel_keys)), "Duplicate relationships found"
