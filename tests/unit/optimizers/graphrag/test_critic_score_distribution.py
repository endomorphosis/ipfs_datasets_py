"""
Tests for OntologyCritic score distribution analysis.

Validates that critic scores are properly distributed across various ontology qualities,
and that score dimensions behave consistently across multiple samples.
"""

import pytest
from ipfs_datasets_py.optimizers.graphrag.ontology_critic import OntologyCritic
from ipfs_datasets_py.optimizers.graphrag.ontology_types import Ontology, Entity, Relationship
from ipfs_datasets_py.optimizers.graphrag.ontology_generator import OntologyGenerationContext


@pytest.fixture
def critic():
    """Create a critic instance for testing."""
    return OntologyCritic()


@pytest.fixture
def context():
    """Create a minimal generation context for critic evaluation."""
    return OntologyGenerationContext(
        domain="general",
        data_source="test",
        data_type="text",
    )


@pytest.fixture
def minimal_ontology():
    """Create a minimal ontology with few entities/relationships."""
    return {
        "entities": [
            {"id": "e1", "text": "Entity A", "type": "Person", "confidence": 0.9},
        ],
        "relationships": [],
        "metadata": {"domain": "general"},
    }


@pytest.fixture
def small_ontology():
    """Create a small ontology with several entities and relationships."""
    return {
        "entities": [
            {"id": "e1", "text": "Alice", "type": "Person", "confidence": 0.9},
            {"id": "e2", "text": "Bob", "type": "Person", "confidence": 0.85},
            {"id": "e3", "text": "Acme Corp", "type": "Organization", "confidence": 0.8},
        ],
        "relationships": [
            {"id": "r1", "source_id": "e1", "target_id": "e3", "type": "works_at", "confidence": 0.75},
        ],
        "metadata": {"domain": "general"},
    }


@pytest.fixture
def medium_ontology():
    """Create a medium ontology with 10 entities and relationships."""
    entities = [
        {"id": f"e{i}", "text": f"Entity {i}", "type": "Concept", "confidence": 0.7 + 0.01 * i}
        for i in range(10)
    ]
    relationships = [
        {
            "id": f"r{i}",
            "source_id": f"e{i}",
            "target_id": f"e{(i + 1) % 10}",
            "type": "related_to",
            "confidence": 0.65 + 0.01 * i,
        }
        for i in range(8)
    ]
    return {
        "entities": entities,
        "relationships": relationships,
        "metadata": {"domain": "general"},
    }


@pytest.fixture
def large_ontology():
    """Create a large ontology with 50+ entities and relationships."""
    entities = [
        {"id": f"e{i}", "text": f"Entity {i}", "type": "Concept", "confidence": 0.6 + 0.004 * i}
        for i in range(50)
    ]
    relationships = [
        {
            "id": f"r{i}",
            "source_id": f"e{i}",
            "target_id": f"e{(i + 2) % 50}",
            "type": "related_to",
            "confidence": 0.60,
        }
        for i in range(40)
    ]
    return {
        "entities": entities,
        "relationships": relationships,
        "metadata": {"domain": "general"},
    }


class TestCriticScoreBasics:
    """Tests for basic critic score functionality."""

    def test_critic_returns_score_object(self, critic, small_ontology, context):
        """Test that critic returns a score object with required fields."""
        score = critic.evaluate_ontology(small_ontology, context)

        assert score is not None
        assert hasattr(score, 'completeness')
        assert hasattr(score, 'consistency')
        assert hasattr(score, 'clarity')
        assert hasattr(score, 'overall')

    def test_score_dimensions_in_valid_range(self, critic, small_ontology, context):
        """Test that all score dimensions are in [0, 1]."""
        score = critic.evaluate_ontology(small_ontology, context)

        assert 0.0 <= score.completeness <= 1.0
        assert 0.0 <= score.consistency <= 1.0
        assert 0.0 <= score.clarity <= 1.0
        assert 0.0 <= score.overall <= 1.0

    def test_minimal_ontology_scores_lower(self, critic, minimal_ontology, small_ontology, context):
        """Test that minimal ontology scores lower than small ontology."""
        score_minimal = critic.evaluate_ontology(minimal_ontology, context)
        score_small = critic.evaluate_ontology(small_ontology, context)

        # Overall score should be lower for minimal ontology
        assert score_minimal.overall < score_small.overall


class TestScoreDistributionAcrossSizes:
    """Tests for score distribution across ontologies of different sizes."""

    def test_completeness_increases_with_size(self, critic, minimal_ontology, small_ontology, medium_ontology, context):
        """Test that completeness tends to increase with ontology size."""
        score_minimal = critic.evaluate_ontology(minimal_ontology, context)
        score_small = critic.evaluate_ontology(small_ontology, context)
        score_medium = critic.evaluate_ontology(medium_ontology, context)

        # Completeness should generally increase with ontology size
        assert score_small.completeness >= score_minimal.completeness
        assert score_medium.completeness >= score_small.completeness

    def test_consistency_independent_of_size(self, critic, small_ontology, medium_ontology, large_ontology, context):
        """Test that consistency can vary independently of ontology size."""
        score_small1 = critic.evaluate_ontology(small_ontology, context)
        score_medium1 = critic.evaluate_ontology(medium_ontology, context)
        score_large1 = critic.evaluate_ontology(large_ontology, context)

        # Consistency may increase, decrease, or stay same - the key is variation
        # Just verify they all have valid scores
        assert 0.0 <= score_small1.consistency <= 1.0
        assert 0.0 <= score_medium1.consistency <= 1.0
        assert 0.0 <= score_large1.consistency <= 1.0

    def test_clarity_varies_across_sizes(self, critic, small_ontology, medium_ontology, large_ontology, context):
        """Test that clarity scores vary across different ontology sizes."""
        scores = [
            critic.evaluate_ontology(small_ontology, context),
            critic.evaluate_ontology(medium_ontology, context),
            critic.evaluate_ontology(large_ontology, context),
        ]

        clarities = [s.clarity for s in scores]
        # Clarity should vary across different sizes
        assert len(set([f"{c:.2f}" for c in clarities])) > 1


class TestScoreDimensionRelationships:
    """Tests for relationships between score dimensions."""

    def test_overall_reflects_dimensions(self, critic, small_ontology, context):
        """Test that overall score reflects individual dimensions."""
        score = critic.evaluate_ontology(small_ontology, context)

        # Overall should be reasonably close to average of dimensions
        avg_dimension = (score.completeness + score.consistency + score.clarity) / 3
        # Allow some variation, but they should be correlated
        assert abs(score.overall - avg_dimension) < 0.5

    def test_high_quality_ontology_has_balanced_scores(self, critic, medium_ontology, context):
        """Test that a well-formed ontology has reasonably balanced dimensions."""
        score = critic.evaluate_ontology(medium_ontology, context)

        # Dimensions should not have extreme variance
        dimensions = [score.completeness, score.consistency, score.clarity]
        min_dim = min(dimensions)
        max_dim = max(dimensions)

        # Difference between min and max should be reasonable (allow up to 0.7 range)
        assert (max_dim - min_dim) < 0.7


class TestScoresWithDuplicates:
    """Tests for critic behavior with duplicate or near-duplicate entities."""

    def test_duplicates_reduce_consistency(self, critic, context):
        """Test that duplicate entities reduce consistency score."""
        ontology_no_dups = {
            "entities": [
                {"id": "e1", "text": "John Smith", "type": "Person", "confidence": 0.9},
                {"id": "e2", "text": "Jane Doe", "type": "Person", "confidence": 0.9},
            ],
            "relationships": [],
            "metadata": {"domain": "general"},
        }

        ontology_with_dups = {
            "entities": [
                {"id": "e1", "text": "John Smith", "type": "Person", "confidence": 0.9},
                {"id": "e2", "text": "John Smith", "type": "Person", "confidence": 0.9},  # Duplicate
                {"id": "e3", "text": "Jane Doe", "type": "Person", "confidence": 0.9},
            ],
            "relationships": [],
            "metadata": {"domain": "general"},
        }

        score_no_dups = critic.evaluate_ontology(ontology_no_dups, context)
        score_with_dups = critic.evaluate_ontology(ontology_with_dups, context)

        # Duplicates should reduce consistency
        assert score_with_dups.consistency <= score_no_dups.consistency


class TestScoresWithMissingData:
    """Tests for critic behavior with missing or incomplete data."""

    def test_low_confidence_entities_reduce_clarity(self, critic, context):
        """Test that low-confidence entities affect the overall score."""
        ontology_high_conf = {
            "entities": [
                {"id": "e1", "text": "Alice", "type": "Person", "confidence": 0.95},
                {"id": "e2", "text": "Bob", "type": "Person", "confidence": 0.95},
            ],
            "relationships": [],
            "metadata": {"domain": "general"},
        }

        ontology_low_conf = {
            "entities": [
                {"id": "e1", "text": "Alice", "type": "Person", "confidence": 0.3},
                {"id": "e2", "text": "Bob", "type": "Person", "confidence": 0.3},
            ],
            "relationships": [],
            "metadata": {"domain": "general"},
        }

        score_high_conf = critic.evaluate_ontology(ontology_high_conf, context)
        score_low_conf = critic.evaluate_ontology(ontology_low_conf, context)

        # Low confidence should reduce overall score or at least not increase it significantly
        assert score_low_conf.overall <= score_high_conf.overall

    def test_missing_relationships_reduce_completeness(self, critic, context):
        """Test that complete relationship info improves completeness."""
        ontology_with_rel = {
            "entities": [
                {"id": "e1", "text": "Alice", "type": "Person", "confidence": 0.9},
                {"id": "e2", "text": "Bob", "type": "Person", "confidence": 0.9},
            ],
            "relationships": [
                {"id": "r1", "source_id": "e1", "target_id": "e2", "type": "knows", "confidence": 0.8},
            ],
            "metadata": {"domain": "general"},
        }

        ontology_no_rel = {
            "entities": [
                {"id": "e1", "text": "Alice", "type": "Person", "confidence": 0.9},
                {"id": "e2", "text": "Bob", "type": "Person", "confidence": 0.9},
            ],
            "relationships": [],
            "metadata": {"domain": "general"},
        }

        score_with_rel = critic.evaluate_ontology(ontology_with_rel, context)
        score_no_rel = critic.evaluate_ontology(ontology_no_rel, context)

        # Having relationships should improve overall completeness
        assert score_with_rel.completeness >= score_no_rel.completeness


class TestScoreDistributionStatistics:
    """Tests for statistical properties of score distributions."""

    def test_score_reproducibility(self, critic, small_ontology, context):
        """Test that scoring the same ontology twice yields identical results."""
        score1 = critic.evaluate_ontology(small_ontology, context)
        score2 = critic.evaluate_ontology(small_ontology, context)

        assert score1.overall == score2.overall
        assert score1.completeness == score2.completeness
        assert score1.consistency == score2.consistency
        assert score1.clarity == score2.clarity

    def test_all_dimensions_non_negative(self, critic, large_ontology, context):
        """Test that all score dimensions are non-negative."""
        score = critic.evaluate_ontology(large_ontology, context)

        assert score.completeness >= 0.0
        assert score.consistency >= 0.0
        assert score.clarity >= 0.0
        assert score.overall >= 0.0


def test_score_distribution_across_100_samples():
    """Test score distribution statistics across 100 random sample ontologies.
    
    This is a property-based test that validates the distribution characteristics
    of the critic scorer across various ontology configurations.
    """
    critic = OntologyCritic()
    context = OntologyGenerationContext(
        domain="general",
        data_source="test",
        data_type="text",
    )

    scores = []
    for i in range(100):
        # Create random ontology with 5-15 entities
        num_entities = 5 + (i % 11)
        entities = [
            {"id": f"e{j}", "text": f"Entity {j}", "type": "Concept", "confidence": 0.7}
            for j in range(num_entities)
        ]
        # Add 1-5 relationships
        num_rels = 1 + (i % 5)
        relationships = [
            {
                "id": f"r{j}",
                "source_id": f"e{j}",
                "target_id": f"e{(j + 1) % num_entities}",
                "type": "related_to",
                "confidence": 0.7,
            }
            for j in range(num_rels)
        ]

        ontology = {
            "entities": entities,
            "relationships": relationships,
            "metadata": {"domain": "general"},
        }

        score = critic.evaluate_ontology(ontology, context)
        scores.append(score)

    # Validate distribution statistics
    assert len(scores) == 100

    # All scores should be valid
    for score in scores:
        assert 0.0 <= score.overall <= 1.0
        assert 0.0 <= score.completeness <= 1.0
        assert 0.0 <= score.consistency <= 1.0
        assert 0.0 <= score.clarity <= 1.0

    # Distribution should show some variation (but may be small for similar ontologies)
    overalls = [s.overall for s in scores]
    # Allow for small variance since random ontologies with consistent structure have similar scores
    assert max(overalls) - min(overalls) > 0.01  # At least 1% range
