"""Tests for OntologyGenerator result helper methods (batch 225).

Tests for describe_result, relationship_confidence_bounds, is_result_empty, result_summary_dict.
"""
import pytest
from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
    OntologyGenerator,
    Entity,
    EntityExtractionResult,
    Relationship,
    OntologyGenerationContext,
    DataType,
    ExtractionStrategy,
)


@pytest.fixture
def generator():
    """Create a basic OntologyGenerator for testing."""
    return OntologyGenerator(use_ipfs_accelerate=False)


@pytest.fixture
def context():
    """Create a basic OntologyGenerationContext."""
    return OntologyGenerationContext(
        data_source="test",
        data_type=DataType.TEXT,
        domain="general",
        extraction_strategy=ExtractionStrategy.RULE_BASED,
    )


@pytest.fixture
def sample_result():
    """Create a sample EntityExtractionResult for testing."""
    entities = [
        Entity(id="e1", text="Alice", type="Person", confidence=0.9, properties={}),
        Entity(id="e2", text="Bob", type="Person", confidence=0.85, properties={}),
        Entity(id="e3", text="Acme Corp", type="Organization", confidence=0.95, properties={}),
    ]
    relationships = [
        Relationship(id="r1", source_id="e1", target_id="e3", type="works_for", confidence=0.8),
        Relationship(id="r2", source_id="e2", target_id="e3", type="works_for", confidence=0.75),
    ]
    return EntityExtractionResult(
        entities=entities,
        relationships=relationships,
        confidence=0.87,
        metadata={},
        errors=[],
    )


@pytest.fixture
def empty_result():
    """Create an empty EntityExtractionResult."""
    return EntityExtractionResult(
        entities=[],
        relationships=[],
        confidence=0.0,
        metadata={},
        errors=[],
    )


class TestDescribeResult:
    """Tests for OntologyGenerator.describe_result() method."""

    def test_describe_sample_result(self, generator, sample_result):
        """Should produce human-readable summary of sample result."""
        description = generator.describe_result(sample_result)
        assert "3 entities" in description
        assert "2 types" in description  # Person, Organization
        assert "2 relationships" in description
        assert "0.87" in description  # confidence

    def test_describe_empty_result(self, generator, empty_result):
        """Should handle empty result gracefully."""
        description = generator.describe_result(empty_result)
        assert "0 entities" in description
        assert "0 relationships" in description

    def test_describe_result_returns_string(self, generator, sample_result):
        """Should return a string."""
        description = generator.describe_result(sample_result)
        assert isinstance(description, str)
        assert len(description) > 0

    def test_describe_single_entity(self, generator):
        """Should describe result with single entity."""
        result = EntityExtractionResult(
            entities=[Entity(id="e1", text="Test", type="Thing", confidence=0.9, properties={})],
            relationships=[],
            confidence=0.9,
            metadata={},
            errors=[],
        )
        description = generator.describe_result(result)
        assert "1entity" in description.replace(" ", "") or "1 entities" in description

    def test_describe_with_errors(self, generator):
        """Should handle result with errors."""
        result = EntityExtractionResult(
            entities=[Entity(id="e1", text="Test", type="Thing", confidence=0.9, properties={})],
            relationships=[],
            confidence=0.5,
            metadata={},
            errors=["Error 1", "Error 2"],
        )
        description = generator.describe_result(result)
        # Method doesn't include error count in description (by design), just check it runs
        assert isinstance(description, str)


class TestRelationshipConfidenceBounds:
    """Tests for OntologyGenerator.relationship_confidence_bounds() method."""

    def test_range_sample_result(self, generator, sample_result):
        """Should return correct min/max confidence range."""
        min_conf, max_conf = generator.relationship_confidence_bounds(sample_result)
        assert min_conf == 0.75
        assert max_conf == 0.8

    def test_range_empty_result(self, generator, empty_result):
        """Should return (0.0, 0.0) for empty result."""
        min_conf, max_conf = generator.relationship_confidence_bounds(empty_result)
        assert min_conf == 0.0
        assert max_conf == 0.0

    def test_range_no_relationships(self, generator):
        """Should return (0.0, 0.0) when no relationships."""
        result = EntityExtractionResult(
            entities=[Entity(id="e1", text="Test", type="Thing", confidence=0.9, properties={})],
            relationships=[],
            confidence=0.9,
            metadata={},
            errors=[],
        )
        min_conf, max_conf = generator.relationship_confidence_bounds(result)
        assert min_conf == 0.0
        assert max_conf == 0.0

    def test_range_single_relationship(self, generator):
        """Should handle single relationship (min == max)."""
        result = EntityExtractionResult(
            entities=[
                Entity(id="e1", text="A", type="Thing", confidence=0.9, properties={}),
                Entity(id="e2", text="B", type="Thing", confidence=0.9, properties={}),
            ],
            relationships=[Relationship(id="r1", source_id="e1", target_id="e2", type="rel", confidence=0.7)],
            confidence=0.8,
            metadata={},
            errors=[],
        )
        min_conf, max_conf = generator.relationship_confidence_bounds(result)
        assert min_conf == 0.7
        assert max_conf == 0.7

    def test_range_returns_tuple(self, generator, sample_result):
        """Should return a tuple of two floats."""
        result = generator.relationship_confidence_bounds(sample_result)
        assert isinstance(result, tuple)
        assert len(result) == 2
        assert isinstance(result[0], float)
        assert isinstance(result[1], float)

    def test_range_order(self, generator, sample_result):
        """Should have min <= max."""
        min_conf, max_conf = generator.relationship_confidence_bounds(sample_result)
        assert min_conf <= max_conf


class TestIsResultEmpty:
    """Tests for OntologyGenerator.is_result_empty() method."""

    def test_empty_result_is_empty(self, generator, empty_result):
        """Should return True for empty result."""
        assert generator.is_result_empty(empty_result) is True

    def test_sample_result_not_empty(self, generator, sample_result):
        """Should return False for result with data."""
        assert generator.is_result_empty(sample_result) is False

    def test_entities_only_not_empty(self, generator):
        """Should return False when entities exist but no relationships."""
        result = EntityExtractionResult(
            entities=[Entity(id="e1", text="Test", type="Thing", confidence=0.9, properties={})],
            relationships=[],
            confidence=0.9,
            metadata={},
            errors=[],
        )
        assert generator.is_result_empty(result) is False

    def test_relationships_only_not_empty(self, generator):
        """Should return False when relationships exist but no entities."""
        result = EntityExtractionResult(
            entities=[],
            relationships=[Relationship(id="r1", source_id="e1", target_id="e2", type="rel", confidence=0.7)],
            confidence=0.7,
            metadata={},
            errors=[],
        )
        assert generator.is_result_empty(result) is False

    def test_returns_boolean(self, generator, sample_result):
        """Should return a boolean value."""
        result = generator.is_result_empty(sample_result)
        assert isinstance(result, bool)


class TestResultSummaryDict:
    """Tests for OntologyGenerator.result_summary_dict() method."""

    def test_summary_sample_result(self, generator, sample_result):
        """Should return correct summary for sample result."""
        summary = generator.result_summary_dict(sample_result)
        assert summary["entity_count"] == 3
        assert summary["relationship_count"] == 2
        assert summary["unique_types"] == 2  # Person, Organization
        assert 0.85 <= summary["mean_confidence"] <= 0.95  # Average of 0.9, 0.85, 0.95
        assert summary["min_confidence"] == 0.85
        assert summary["max_confidence"] == 0.95
        assert summary["has_errors"] is False
        assert summary["error_count"] == 0

    def test_summary_empty_result(self, generator, empty_result):
        """Should handle empty result."""
        summary = generator.result_summary_dict(empty_result)
        assert summary["entity_count"] == 0
        assert summary["relationship_count"] == 0
        assert summary["unique_types"] == 0
        assert summary["mean_confidence"] == 0.0
        assert summary["min_confidence"] == 0.0
        assert summary["max_confidence"] == 0.0
        assert summary["has_errors"] is False
        assert summary["error_count"] == 0

    def test_summary_with_errors(self, generator):
        """Should detect errors in result."""
        result = EntityExtractionResult(
            entities=[Entity(id="e1", text="Test", type="Thing", confidence=0.9, properties={})],
            relationships=[],
            confidence=0.9,
            metadata={},
            errors=["Error 1", "Error 2"],
        )
        summary = generator.result_summary_dict(result)
        assert summary["has_errors"] is True
        assert summary["error_count"] == 2

    def test_summary_returns_dict(self, generator, sample_result):
        """Should return a dictionary."""
        summary = generator.result_summary_dict(sample_result)
        assert isinstance(summary, dict)

    def test_summary_has_required_keys(self, generator, sample_result):
        """Should include all required keys."""
        summary = generator.result_summary_dict(sample_result)
        required_keys = {
            "entity_count",
            "relationship_count",
            "unique_types",
            "mean_confidence",
            "min_confidence",
            "max_confidence",
            "has_errors",
            "error_count",
        }
        assert required_keys.issubset(summary.keys())

    def test_summary_single_entity(self, generator):
        """Should handle single entity correctly."""
        result = EntityExtractionResult(
            entities=[Entity(id="e1", text="Test", type="Thing", confidence=0.9, properties={})],
            relationships=[],
            confidence=0.9,
            metadata={},
            errors=[],
        )
        summary = generator.result_summary_dict(result)
        assert summary["entity_count"] == 1
        assert summary["unique_types"] == 1
        assert summary["mean_confidence"] == 0.9
        assert summary["min_confidence"] == 0.9
        assert summary["max_confidence"] == 0.9

    def test_summary_mean_confidence_calculation(self, generator):
        """Should calculate mean confidence correctly."""
        result = EntityExtractionResult(
            entities=[
                Entity(id="e1", text="A", type="Thing", confidence=0.8, properties={}),
                Entity(id="e2", text="B", type="Thing", confidence=0.6, properties={}),
                Entity(id="e3", text="C", type="Thing", confidence=1.0, properties={}),
            ],
            relationships=[],
            confidence=0.8,
            metadata={},
            errors=[],
        )
        summary = generator.result_summary_dict(result)
        expected_mean = (0.8 + 0.6 + 1.0) / 3
        assert abs(summary["mean_confidence"] - expected_mean) < 0.01
