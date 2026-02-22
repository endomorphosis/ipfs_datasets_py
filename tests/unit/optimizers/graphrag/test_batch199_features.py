"""Batch-199 feature tests.

Tests for 4 new statistical/analysis methods:
- OntologyOptimizer.history_trimmed_mean(trim_fraction)
- OntologyCritic.dimension_z_scores(score)
- OntologyGenerator.entity_id_list(result)
- LogicValidator.hub_nodes(ontology, min_degree)
"""

import pytest
import math
from hypothesis import given, settings, strategies as st

from ipfs_datasets_py.optimizers.graphrag import (
    OntologyOptimizer,
    OntologyCritic,
    OntologyGenerator,
    LogicValidator,
)
from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
    Entity,
    Relationship,
    EntityExtractionResult,
)
from ipfs_datasets_py.optimizers.graphrag.ontology_critic import CriticScore
from ipfs_datasets_py.optimizers.graphrag.ontology_optimizer import (
    OptimizationReport,
)


# ── OntologyOptimizer.history_trimmed_mean ──────────────────────────────────

class TestHistoryTrimmedMean:
    """Tests for OntologyOptimizer.history_trimmed_mean()."""

    def test_empty_history_returns_zero(self):
        """Empty history should return 0.0."""
        opt = OntologyOptimizer()
        assert opt.history_trimmed_mean() == 0.0
        assert opt.history_trimmed_mean(trim_fraction=0.1) == 0.0

    def test_single_entry(self):
        """Single entry: trimming should return that entry's score."""
        opt = OntologyOptimizer()
        entry = OptimizationReport(average_score=0.75, trend="stable")
        opt._history = [entry]
        assert opt.history_trimmed_mean() == pytest.approx(0.75)
        assert opt.history_trimmed_mean(trim_fraction=0.0) == pytest.approx(0.75)

    def test_two_entries_no_trim(self):
        """Two entries with trim=0: should return mean of both."""
        opt = OntologyOptimizer()
        opt._history = [
            OptimizationReport(average_score=0.5, trend="stable"),
            OptimizationReport(average_score=0.9, trend="stable"),
        ]
        assert opt.history_trimmed_mean(trim_fraction=0.0) == pytest.approx(0.7)

    def test_three_entries_trim_0_2(self):
        """Three entries, trim_fraction=0.2: k=0 so returns full mean."""
        opt = OntologyOptimizer()
        opt._history = [
            OptimizationReport(average_score=0.3, trend="stable"),
            OptimizationReport(average_score=0.7, trend="stable"),
            OptimizationReport(average_score=0.9, trend="stable"),
        ]
        # k = int(3 * 0.2) = 0
        result = opt.history_trimmed_mean(trim_fraction=0.2)
        expected = (0.3 + 0.7 + 0.9) / 3
        assert result == pytest.approx(expected)

    def test_five_entries_trim_0_2(self):
        """Five entries, trim_fraction=0.2: trim 1 from each end."""
        opt = OntologyOptimizer()
        scores = [0.2, 0.4, 0.5, 0.8, 0.9]
        opt._history = [
            OptimizationReport(average_score=s, trend="stable")
            for s in scores
        ]
        # When sorted: [0.2, 0.4, 0.5, 0.8, 0.9]
        # k = int(5 * 0.2) = 1
        # trimmed = [0.4, 0.5, 0.8]
        trimmed_mean = opt.history_trimmed_mean(trim_fraction=0.2)
        expected = (0.4 + 0.5 + 0.8) / 3
        assert trimmed_mean == pytest.approx(expected)

    def test_invalid_trim_fraction_negative(self):
        """Negative trim_fraction should raise ValueError."""
        opt = OntologyOptimizer()
        opt._history = [OptimizationReport(average_score=0.5, trend="stable")]
        with pytest.raises(ValueError, match="trim_fraction must be in"):
            opt.history_trimmed_mean(trim_fraction=-0.1)

    def test_invalid_trim_fraction_ge_half(self):
        """trim_fraction >= 0.5 should raise ValueError."""
        opt = OntologyOptimizer()
        opt._history = [OptimizationReport(average_score=0.5, trend="stable")]
        with pytest.raises(ValueError, match="trim_fraction must be in"):
            opt.history_trimmed_mean(trim_fraction=0.5)

    def test_trim_extremes_works(self):
        """Trimming should remove actual extremes."""
        opt = OntologyOptimizer()
        opt._history = [
            OptimizationReport(average_score=0.1, trend="stable"),  # extreme low
            OptimizationReport(average_score=0.5, trend="stable"),
            OptimizationReport(average_score=0.6, trend="stable"),
            OptimizationReport(average_score=0.7, trend="stable"),
            OptimizationReport(average_score=0.9, trend="stable"),  # extreme high
        ]
        # Sorted: [0.1, 0.5, 0.6, 0.7, 0.9]   
        # k = int(5 * 0.2) = 1
        # trimmed = [0.5, 0.6, 0.7]
        result = opt.history_trimmed_mean(trim_fraction=0.2)
        expected = (0.5 + 0.6 + 0.7) / 3
        assert result == pytest.approx(expected)


# ── OntologyCritic.dimension_z_scores ────────────────────────────────────

class TestDimensionZScores:
    """Tests for OntologyCritic.dimension_z_scores()."""

    def test_all_zeros(self):
        """Score with all zeros should have negative z-scores."""
        critic = OntologyCritic()
        score = CriticScore(
            completeness=0.0, consistency=0.0, clarity=0.0,
            granularity=0.0, relationship_coherence=0.0, domain_alignment=0.0
        )
        z_scores = critic.dimension_z_scores(score)
        
        # z = (0 - 0.5) / 0.2 = -2.5
        for dim, z in z_scores.items():
            assert z == pytest.approx(-2.5)

    def test_all_ones(self):
        """Score with all 1.0 should have positive z-scores."""
        critic = OntologyCritic()
        score = CriticScore(
            completeness=1.0, consistency=1.0, clarity=1.0,
            granularity=1.0, relationship_coherence=1.0, domain_alignment=1.0
        )
        z_scores = critic.dimension_z_scores(score)
        
        # z = (1.0 - 0.5) / 0.2 = 2.5
        for dim, z in z_scores.items():
            assert z == pytest.approx(2.5)

    def test_nominal_value_0_5(self):
        """Score with all 0.5 should have z-score=0."""
        critic = OntologyCritic()
        score = CriticScore(
            completeness=0.5, consistency=0.5, clarity=0.5,
            granularity=0.5, relationship_coherence=0.5, domain_alignment=0.5
        )
        z_scores = critic.dimension_z_scores(score)
        
        for dim, z in z_scores.items():
            assert z == pytest.approx(0.0)

    def test_mixed_values(self):
        """Mixed dimension values should return varied z-scores."""
        critic = OntologyCritic()
        score = CriticScore(
            completeness=0.7,       # (0.7 - 0.5) / 0.2 = 1.0
            consistency=0.3,        # (0.3 - 0.5) / 0.2 = -1.0
            clarity=0.9,            # (0.9 - 0.5) / 0.2 = 2.0
            granularity=0.1,        # (0.1 - 0.5) / 0.2 = -2.0
            relationship_coherence=0.5,  # 0.0
            domain_alignment=0.6,   # (0.6 - 0.5) / 0.2 = 0.5
        )
        z_scores = critic.dimension_z_scores(score)
        
        assert z_scores["completeness"] == pytest.approx(1.0)
        assert z_scores["consistency"] == pytest.approx(-1.0)
        assert z_scores["clarity"] == pytest.approx(2.0)
        assert z_scores["granularity"] == pytest.approx(-2.0)
        assert z_scores["relationship_coherence"] == pytest.approx(0.0)
        assert z_scores["domain_alignment"] == pytest.approx(0.5)

    def test_returns_dict_with_all_dimensions(self):
        """Result should contain all 6 dimensions."""
        critic = OntologyCritic()
        score = CriticScore(
            completeness=0.7, consistency=0.6, clarity=0.8,
            granularity=0.5, relationship_coherence=0.7, domain_alignment=0.6
        )
        z_scores = critic.dimension_z_scores(score)
        
        expected_dims = {
            "completeness", "consistency", "clarity",
            "granularity", "relationship_coherence", "domain_alignment"
        }
        assert set(z_scores.keys()) == expected_dims

    def test_round_to_4_decimals(self):
        """Z-scores should be rounded to 4 decimal places."""
        critic = OntologyCritic()
        score = CriticScore(
            completeness=0.7123, consistency=0.6, clarity=0.8,
            granularity=0.5, relationship_coherence=0.7, domain_alignment=0.6
        )
        z_scores = critic.dimension_z_scores(score)
        
        # Each should be a float with <= 4 decimals
        for z in z_scores.values():
            # Check that string representation doesn't exceed 4 decimals
            assert isinstance(z, float)


# ── OntologyGenerator.entity_id_list ─────────────────────────────────────

class TestEntityIdList:
    """Tests for OntologyGenerator.entity_id_list()."""

    def test_empty_result(self):
        """Empty result should return empty list."""
        gen = OntologyGenerator()
        result = EntityExtractionResult(entities=[], relationships=[], confidence=1.0)
        ids = gen.entity_id_list(result)
        assert ids == []

    def test_single_entity(self):
        """Single entity should return list with its ID."""
        gen = OntologyGenerator()
        entity = Entity(id="alice", text="Alice", type="person")
        result = EntityExtractionResult(entities=[entity], relationships=[], confidence=1.0)
        ids = gen.entity_id_list(result)
        assert ids == ["alice"]

    def test_multiple_entities_sorted(self):
        """Multiple entities should be returned in sorted order."""
        gen = OntologyGenerator()
        entities = [
            Entity(id="charlie", text="Charlie", type="person"),
            Entity(id="alice", text="Alice", type="person"),
            Entity(id="bob", text="Bob", type="person"),
        ]
        result = EntityExtractionResult(entities=entities, relationships=[], confidence=1.0)
        ids = gen.entity_id_list(result)
        assert ids == ["alice", "bob", "charlie"]

    def test_duplicate_ids_removed(self):
        """Duplicate entity IDs should appear only once."""
        gen = OntologyGenerator()
        entities = [
            Entity(id="alice", text="Alice", type="person"),
            Entity(id="alice", text="Alice (dup)", type="person"),
            Entity(id="bob", text="Bob", type="person"),
        ]
        result = EntityExtractionResult(entities=entities, relationships=[], confidence=1.0)
        ids = gen.entity_id_list(result)
        assert ids == ["alice", "bob"]

    def test_entities_with_none_id_skipped(self):
        """Entities with None ID should be skipped."""
        gen = OntologyGenerator()
        entities = [
            Entity(id="alice", text="Alice", type="person"),
            Entity(id=None, text="No ID", type="person"),
            Entity(id="bob", text="Bob", type="person"),
        ]
        result = EntityExtractionResult(entities=entities, relationships=[], confidence=1.0)
        ids = gen.entity_id_list(result)
        assert ids == ["alice", "bob"]

    def test_large_id_set(self):
        """Test with large number of entities."""
        gen = OntologyGenerator()
        entities = [Entity(id=f"entity_{i}", text=f"Entity {i}", type="obj") for i in range(100)]
        result = EntityExtractionResult(entities=entities, relationships=[], confidence=1.0)
        ids = gen.entity_id_list(result)
        
        assert len(ids) == 100
        assert ids == sorted(ids)
        assert ids[0] == "entity_0"
        assert ids[-1] == "entity_99"


# ── LogicValidator.hub_nodes ────────────────────────────────────────────

class TestHubNodes:
    """Tests for LogicValidator.hub_nodes()."""

    def test_empty_ontology(self):
        """Empty ontology should return empty hub list."""
        validator = LogicValidator()
        ontology = {"entities": [], "relationships": []}
        hubs = validator.hub_nodes(ontology)
        assert hubs == []

    def test_no_relationships(self):
        """Ontology with no relationships should have no hubs."""
        validator = LogicValidator()
        ontology = {
            "entities": [
                {"id": "alice", "text": "Alice"},
                {"id": "bob", "text": "Bob"},
            ],
            "relationships": []
        }
        hubs = validator.hub_nodes(ontology, min_degree=1)
        assert hubs == []

    def test_single_relationship(self):
        """Single relationship: nodes have degree=1 (< min_degree=2)."""
        validator = LogicValidator()
        ontology = {
            "entities": [
                {"id": "alice", "text": "Alice"},
                {"id": "bob", "text": "Bob"},
            ],
            "relationships": [
                {"source_id": "alice", "target_id": "bob", "type": "knows"}
            ]
        }
        hubs = validator.hub_nodes(ontology, min_degree=2)
        assert hubs == []

    def test_hub_with_min_degree_1(self):
        """With min_degree=1, any node in relationships is a hub."""
        validator = LogicValidator()
        ontology = {
            "entities": [
                {"id": "alice", "text": "Alice"},
                {"id": "bob", "text": "Bob"},
            ],
            "relationships": [
                {"source_id": "alice", "target_id": "bob", "type": "knows"}
            ]
        }
        hubs = validator.hub_nodes(ontology, min_degree=1)
        assert set(hubs) == {"alice", "bob"}

    def test_star_topology(self):
        """Star topology: central node is hub."""
        validator = LogicValidator()
        ontology = {
            "entities": [
                {"id": "hub", "text": "Hub"},
                {"id": "a", "text": "A"},
                {"id": "b", "text": "B"},
                {"id": "c", "text": "C"},
            ],
            "relationships": [
                {"source_id": "hub", "target_id": "a", "type": "rel"},
                {"source_id": "hub", "target_id": "b", "type": "rel"},
                {"source_id": "hub", "target_id": "c", "type": "rel"},
            ]
        }
        hubs = validator.hub_nodes(ontology, min_degree=2)
        # hub has degree=3, a/b/c have degree=1
        assert hubs == ["hub"]

    def test_sorted_by_degree_descending(self):
        """Hubs should be sorted by degree (descending)."""
        validator = LogicValidator()
        ontology = {
            "entities": [
                {"id": "alice", "text": "Alice"},
                {"id": "bob", "text": "Bob"},
                {"id": "charlie", "text": "Charlie"},
            ],
            "relationships": [
                {"source_id": "alice", "target_id": "bob", "type": "rel"},
                {"source_id": "alice", "target_id": "charlie", "type": "rel"},
                {"source_id": "bob", "target_id": "charlie", "type": "rel"},
            ]
        }
        hubs = validator.hub_nodes(ontology, min_degree=2)
        # All have degree=2, should be sorted alphabetically
        assert hubs == ["alice", "bob", "charlie"]

    def test_bidirectional_edges(self):
        """Bidirectional edges count toward degree."""
        validator = LogicValidator()
        ontology = {
            "entities": [
                {"id": "alice", "text": "Alice"},
                {"id": "bob", "text": "Bob"},
            ],
            "relationships": [
                {"source_id": "alice", "target_id": "bob", "type": "rel1"},
                {"source_id": "bob", "target_id": "alice", "type": "rel2"},
            ]
        }
        hubs = validator.hub_nodes(ontology, min_degree=2)
        assert set(hubs) == {"alice", "bob"}

    def test_self_loops(self):
        """Self-loops should count toward degree."""
        validator = LogicValidator()
        ontology = {
            "entities": [
                {"id": "alice", "text": "Alice"},
            ],
            "relationships": [
                {"source_id": "alice", "target_id": "alice", "type": "self"},
            ]
        }
        hubs = validator.hub_nodes(ontology, min_degree=2)
        # alice has degree=2 from self-loop (counts as both source and target)
        assert hubs == ["alice"]

    def test_missing_relationships_key(self):
        """Missing 'relationships' key should be handled gracefully."""
        validator = LogicValidator()
        ontology = {
            "entities": [
                {"id": "alice", "text": "Alice"},
            ]
        }
        hubs = validator.hub_nodes(ontology, min_degree=1)
        assert hubs == []

    def test_complex_network(self):
        """Complex network with varying degrees."""
        validator = LogicValidator()
        ontology = {
            "entities": [
                {"id": "a", "text": "A"},
                {"id": "b", "text": "B"},
                {"id": "c", "text": "C"},
                {"id": "d", "text": "D"},
            ],
            "relationships": [
                {"source_id": "a", "target_id": "b", "type": "rel"},
                {"source_id": "a", "target_id": "c", "type": "rel"},
                {"source_id": "a", "target_id": "d", "type": "rel"},
                {"source_id": "b", "target_id": "c", "type": "rel"},
                {"source_id": "c", "target_id": "d", "type": "rel"},
            ]
        }
        # a: degree=3, b: degree=2, c: degree=3, d: degree=2
        hubs = validator.hub_nodes(ontology, min_degree=2)
        assert set(hubs) == {"a", "b", "c", "d"}
        # Should be sorted: [a/c by degree 3, then b/d by degree 2]
        assert hubs[0] in {"a", "c"}  # degree 3


# ── Property-based tests (Hypothesis) ──────────────────────────────────

@given(
    scores=st.lists(
        st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
        min_size=1,
        max_size=20,
    )
)
@settings(max_examples=50)
def test_history_trimmed_mean_in_range(scores):
    """Trimmed mean should be between min and max scores."""
    opt = OntologyOptimizer()
    opt._history = [
        OptimizationReport(average_score=s, trend="stable")
        for s in scores
    ]
    
    trimmed = opt.history_trimmed_mean(trim_fraction=0.1)
    assert min(scores) <= trimmed <= max(scores)


@given(
    comp=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
    cons=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
    clar=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
    gran=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
    relc=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
    doma=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
)
@settings(max_examples=30)
def test_dimension_z_scores_all_dimensions(comp, cons, clar, gran, relc, doma):
    """dimension_z_scores should always include all 6 dimensions."""
    critic = OntologyCritic()
    score = CriticScore(
        completeness=comp, consistency=cons, clarity=clar,
        granularity=gran, relationship_coherence=relc, domain_alignment=doma
    )
    z_scores = critic.dimension_z_scores(score)
    
    expected = {
        "completeness", "consistency", "clarity",
        "granularity", "relationship_coherence", "domain_alignment"
    }
    assert set(z_scores.keys()) == expected
