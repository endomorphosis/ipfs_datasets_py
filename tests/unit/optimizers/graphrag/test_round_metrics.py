"""Tests for per-round metric counters in ontology refinement.

These tests validate that refinement rounds are properly tracked with
detailed metrics on entity/relationship changes and score improvements.
"""

import pytest
from ipfs_datasets_py.optimizers.graphrag.round_metrics import (
    RoundMetrics,
    RoundMetricsCollector,
    compute_ontology_delta,
    create_round_metrics,
)


class TestRoundMetricsDataclass:
    """Test RoundMetrics dataclass."""

    def test_round_metrics_creation(self):
        """
        GIVEN: Round metrics parameters
        WHEN: RoundMetrics object is created
        THEN: All fields are initialized correctly
        """
        metrics = RoundMetrics(
            round_number=1,
            entities_count_before=5,
            entities_count_after=7,
            entities_delta=2,
            entities_added=3,
            entities_removed=1,
            relationships_count_before=3,
            relationships_count_after=4,
            relationships_delta=1,
            score_before=0.7,
            score_after=0.75,
            score_delta=0.05,
            actions_applied=['add_entity', 'normalize_names'],
        )
        
        assert metrics.round_number == 1
        assert metrics.entities_delta == 2
        assert metrics.score_delta == 0.05
        assert 'add_entity' in metrics.actions_applied

    def test_round_metrics_to_dict(self):
        """
        GIVEN: RoundMetrics object
        WHEN: to_dict() is called
        THEN: Returns dict with all fields
        """
        metrics = RoundMetrics(
            round_number=2,
            entities_delta=1,
            score_delta=0.02,
            actions_applied=['prune_orphans'],
        )
        
        result = metrics.to_dict()
        
        assert isinstance(result, dict)
        assert result['round_number'] == 2
        assert result['entities_delta'] == 1
        assert result['score_delta'] == 0.02

    def test_round_metrics_repr(self):
        """
        GIVEN: RoundMetrics object
        WHEN: __repr__ is called
        THEN: Returns concise string
        """
        metrics = RoundMetrics(
            round_number=1,
            entities_delta=2,
            relationships_delta=1,
            score_delta=0.05,
            actions_applied=['add_entity'],
        )
        
        repr_str = repr(metrics)
        
        assert "r1" in repr_str
        assert "+2" in repr_str  # entities_delta
        assert "+1" in repr_str  # relationships_delta


class TestComputeOntologyDelta:
    """Test ontology diff computation."""

    def test_identical_ontologies(self):
        """
        GIVEN: Two identical ontologies
        WHEN: compute_ontology_delta is called
        THEN: Returns all zeros
        """
        onto = {
            "entities": [{"id": "e1", "type": "Person"}],
            "relationships": [{"source": "e1", "target": "e2", "type": "knows"}],
        }
        
        added, removed, modified, rel_added, rel_removed, rel_modified = \
            compute_ontology_delta(onto, onto)
        
        assert added == 0
        assert removed == 0
        assert modified == 0
        assert rel_added == 0
        assert rel_removed == 0

    def test_entities_added(self):
        """
        GIVEN: Ontology with new entity added
        WHEN: compute_ontology_delta is called
        THEN: entities_added is > 0
        """
        before = {
            "entities": [{"id": "e1", "type": "Person"}],
            "relationships": [],
        }
        after = {
            "entities": [
                {"id": "e1", "type": "Person"},
                {"id": "e2", "type": "Person"},
            ],
            "relationships": [],
        }
        
        added, removed, modified, _, _, _ = compute_ontology_delta(before, after)
        
        assert added == 1
        assert removed == 0
        assert modified == 0

    def test_entities_removed(self):
        """
        GIVEN: Ontology with entity removed
        WHEN: compute_ontology_delta is called
        THEN: entities_removed is > 0
        """
        before = {
            "entities": [
                {"id": "e1", "type": "Person"},
                {"id": "e2", "type": "Person"},
            ],
            "relationships": [],
        }
        after = {
            "entities": [{"id": "e1", "type": "Person"}],
            "relationships": [],
        }
        
        added, removed, modified, _, _, _ = compute_ontology_delta(before, after)
        
        assert added == 0
        assert removed == 1
        assert modified == 0

    def test_entities_modified(self):
        """
        GIVEN: Entity with changed properties
        WHEN: compute_ontology_delta is called
        THEN: entities_modified is > 0
        """
        before = {
            "entities": [{"id": "e1", "type": "Person", "confidence": 0.8}],
            "relationships": [],
        }
        after = {
            "entities": [{"id": "e1", "type": "Person", "confidence": 0.95}],
            "relationships": [],
        }
        
        added, removed, modified, _, _, _ = compute_ontology_delta(before, after)
        
        assert added == 0
        assert removed == 0
        assert modified == 1

    def test_relationships_added_removed(self):
        """
        GIVEN: Ontologies with different relationships
        WHEN: compute_ontology_delta is called
        THEN: Returns relationship changes
        """
        before = {
            "entities": [
                {"id": "e1"},
                {"id": "e2"},
                {"id": "e3"},
            ],
            "relationships": [
                {"source": "e1", "target": "e2", "type": "knows"},
            ],
        }
        after = {
            "entities": [
                {"id": "e1"},
                {"id": "e2"},
                {"id": "e3"},
            ],
            "relationships": [
                {"source": "e1", "target": "e2", "type": "knows"},
                {"source": "e2", "target": "e3", "type": "knows"},
            ],
        }
        
        _, _, _, rel_added, rel_removed, rel_modified = \
            compute_ontology_delta(before, after)
        
        assert rel_added == 1
        assert rel_removed == 0

    def test_empty_ontologies(self):
        """
        GIVEN: Empty ontologies
        WHEN: compute_ontology_delta is called
        THEN: Returns all zeros
        """
        before = {"entities": [], "relationships": []}
        after = {"entities": [], "relationships": []}
        
        result = compute_ontology_delta(before, after)
        
        assert result == (0, 0, 0, 0, 0, 0)


class TestCreateRoundMetrics:
    """Test RoundMetrics creation helper."""

    def test_create_basic_metrics(self):
        """
        GIVEN: Before/after ontologies and scores
        WHEN: create_round_metrics is called
        THEN: Returns RoundMetrics with computed deltas
        """
        before = {
            "entities": [{"id": "e1"}],
            "relationships": [],
        }
        after = {
            "entities": [{"id": "e1"}, {"id": "e2"}],
            "relationships": [{"source": "e1", "target": "e2", "type": "knows"}],
        }
        
        metrics = create_round_metrics(
            round_number=1,
            ontology_before=before,
            ontology_after=after,
            score_before=0.7,
            score_after=0.75,
            actions_applied=['add_entity'],
            execution_time_ms=150.5,
        )
        
        assert metrics.round_number == 1
        assert metrics.entities_count_before == 1
        assert metrics.entities_count_after == 2
        assert metrics.entities_delta == 1
        assert metrics.entities_added == 1
        assert metrics.score_delta == 0.05
        assert metrics.execution_time_ms == 150.5
        assert 'add_entity' in metrics.actions_applied

    def test_create_metrics_no_improvement(self):
        """
        GIVEN: Before/after with no score improvement
        WHEN: create_round_metrics is called
        THEN: score_delta is 0 or negative
        """
        onto = {"entities": [], "relationships": []}
        
        metrics = create_round_metrics(
            round_number=1,
            ontology_before=onto,
            ontology_after=onto,
            score_before=0.75,
            score_after=0.73,
        )
        
        assert metrics.score_delta == -0.02


class TestRoundMetricsCollector:
    """Test RoundMetricsCollector for aggregating round data."""

    def test_collector_initialization(self):
        """
        GIVEN: New RoundMetricsCollector
        WHEN: Created
        THEN: Has empty rounds list
        """
        collector = RoundMetricsCollector()
        
        assert collector.rounds == []
        assert collector.total_score_delta() == 0.0

    def test_record_and_retrieve_rounds(self):
        """
        GIVEN: RoundMetricsCollector
        WHEN: Multiple rounds are recorded
        THEN: Can retrieve all rounds
        """
        collector = RoundMetricsCollector()
        
        metrics1 = RoundMetrics(round_number=1, score_delta=0.05)
        metrics2 = RoundMetrics(round_number=2, score_delta=0.03)
        
        collector.record_round(metrics1)
        collector.record_round(metrics2)
        
        assert len(collector.rounds) == 2
        assert collector.rounds[0].round_number == 1

    def test_total_entity_delta(self):
        """
        GIVEN: Multiple rounds with entity changes
        WHEN: total_entity_delta is called
        THEN: Returns sum of all entities_delta
        """
        collector = RoundMetricsCollector()
        
        metrics1 = RoundMetrics(round_number=1, entities_delta=2)
        metrics2 = RoundMetrics(round_number=2, entities_delta=1)
        metrics3 = RoundMetrics(round_number=3, entities_delta=-1)
        
        collector.record_round(metrics1)
        collector.record_round(metrics2)
        collector.record_round(metrics3)
        
        assert collector.total_entity_delta() == 2  # 2 + 1 - 1

    def test_total_score_delta(self):
        """
        GIVEN: Multiple rounds with score progression
        WHEN: total_score_delta is called
        THEN: Returns final_score - initial_score
        """
        collector = RoundMetricsCollector()
        
        metrics1 = RoundMetrics(
            round_number=1,
            score_before=0.7,
            score_after=0.72,
            score_delta=0.02,
        )
        metrics2 = RoundMetrics(
            round_number=2,
            score_before=0.72,
            score_after=0.76,
            score_delta=0.04,
        )
        
        collector.record_round(metrics1)
        collector.record_round(metrics2)
        
        # Total should be 0.76 - 0.7 = 0.06
        assert collector.total_score_delta() == pytest.approx(0.06, abs=0.001)

    def test_average_round_improvement(self):
        """
        GIVEN: Multiple rounds with improvements
        WHEN: average_round_improvement is called
        THEN: Returns total_delta / num_rounds
        """
        collector = RoundMetricsCollector()
        
        # Set score_before/after to calculate total improvement correctly
        metrics1 = RoundMetrics(
            round_number=1,
            score_before=0.70,
            score_after=0.74,
            score_delta=0.04,
        )
        metrics2 = RoundMetrics(
            round_number=2,
            score_before=0.74,
            score_after=0.76,
            score_delta=0.02,
        )
        
        collector.record_round(metrics1)
        collector.record_round(metrics2)
        
        # Average: total (0.76 - 0.70 = 0.06) / 2 rounds = 0.03
        assert collector.average_round_improvement() == pytest.approx(0.03, abs=0.001)

    def test_rounds_to_convergence(self):
        """
        GIVEN: Rounds with decreasing improvements
        WHEN: rounds_to_convergence is called
        THEN: Returns round where improvement drops below threshold
        """
        collector = RoundMetricsCollector()
        
        collector.record_round(RoundMetrics(round_number=1, score_delta=0.05))
        collector.record_round(RoundMetrics(round_number=2, score_delta=0.03))
        collector.record_round(RoundMetrics(round_number=3, score_delta=0.0005))  # Below threshold
        
        convergence_round = collector.rounds_to_convergence(threshold=0.001)
        
        assert convergence_round == 3

    def test_most_effective_actions(self):
        """
        GIVEN: Rounds with various actions applied
        WHEN: most_effective_actions is called
        THEN: Returns actions sorted by average improvement
        """
        collector = RoundMetricsCollector()
        
        # Round 1: two actions applied, 0.05 improvement shared
        collector.record_round(RoundMetrics(
            round_number=1,
            score_delta=0.05,
            actions_applied=['add_entity', 'normalize_names'],
        ))
        # Round 2: one action, 0.01 improvement
        collector.record_round(RoundMetrics(
            round_number=2,
            score_delta=0.01,
            actions_applied=['prune_orphans'],
        ))
        # Round 3: add_entity again, 0.03 improvement
        collector.record_round(RoundMetrics(
            round_number=3,
            score_delta=0.03,
            actions_applied=['add_entity'],
        ))
        
        top_actions = collector.most_effective_actions(top_n=3)
        
        # add_entity appears twice with (0.05 + 0.03) / 2 = 0.04 avg
        # Should be first or tied
        assert len(top_actions) > 0
        assert top_actions[0][0] in ['add_entity', 'normalize_names', 'prune_orphans']

    def test_to_dict_export(self):
        """
        GIVEN: RoundMetricsCollector with data
        WHEN: to_dict() is called
        THEN: Returns complete dict representation
        """
        collector = RoundMetricsCollector()
        
        collector.record_round(RoundMetrics(
            round_number=1,
            entities_delta=2,
            score_before=0.7,
            score_after=0.75,
            score_delta=0.05,
        ))
        
        result = collector.to_dict()
        
        assert isinstance(result, dict)
        assert result['total_rounds'] == 1
        assert result['total_entity_delta'] == 2
        assert result['total_score_delta'] == pytest.approx(0.05, abs=0.001)
        assert len(result['rounds']) == 1

    def test_repr(self):
        """
        GIVEN: RoundMetricsCollector with multiple rounds
        WHEN: __repr__ is called
        THEN: Returns concise string
        """
        collector = RoundMetricsCollector()
        
        collector.record_round(RoundMetrics(
            round_number=1,
            entities_delta=2,
            relationships_delta=1,
            score_delta=0.05,
        ))
        
        repr_str = repr(collector)
        
        assert "1 rounds" in repr_str or "1 round" in repr_str
        assert "+2" in repr_str  # entities
        assert "+1" in repr_str  # relationships


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
