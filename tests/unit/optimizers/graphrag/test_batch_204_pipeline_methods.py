"""
Unit tests for Batch 204 OntologyPipeline analysis methods.

Tests new methods for pipeline run history analysis:
- run_total_entity_count: Sum entities across runs
- run_total_relationship_count: Sum relationships across runs
- run_average_entity_count: Average entities per run
- run_average_relationship_count: Average relationships per run
- run_action_frequency: Count action occurrences
- run_most_common_action: Identify most frequent action
- run_score_variance: Calculate score variance
- run_score_std_dev: Calculate score standard deviation
- run_score_coefficient_of_variation: Calculate CV
- run_has_improving_trend: Detect improving score trend
"""

import pytest
from unittest.mock import Mock
from ipfs_datasets_py.optimizers.graphrag.ontology_pipeline import (
    OntologyPipeline,
    PipelineResult,
)


@pytest.fixture
def pipeline():
    """Create a test OntologyPipeline instance."""
    return OntologyPipeline(domain="test", use_llm=False)


@pytest.fixture
def mock_score():
    """Create a mock CriticScore."""
    score = Mock()
    score.overall = 0.75
    return score


def create_result(entity_count=5, rel_count=10, score_val=0.75, actions=None):
    """Helper to create PipelineResult with test data."""
    score = Mock()
    score.overall = score_val
    
    entities = [{"id": f"e{i}", "text": f"Entity {i}"} for i in range(entity_count)]
    relationships = [{"id": f"r{i}", "source_id": f"e{i}", "target_id": f"e{i+1}"} for i in range(rel_count)]
    
    return PipelineResult(
        ontology={"entities": entities, "relationships": relationships},
        score=score,
        entities=entities,
        relationships=relationships,
        actions_applied=actions or [],
    )


class TestRunTotalEntityCount:
    """Test run_total_entity_count() method."""

    def test_total_entity_count_empty(self, pipeline):
        """Test with no runs."""
        assert pipeline.run_total_entity_count() == 0

    def test_total_entity_count_single_run(self, pipeline):
        """Test with single run."""
        pipeline._run_history = [create_result(entity_count=10)]
        assert pipeline.run_total_entity_count() == 10

    def test_total_entity_count_multiple_runs(self, pipeline):
        """Test with multiple runs."""
        pipeline._run_history = [
            create_result(entity_count=5),
            create_result(entity_count=8),
            create_result(entity_count=12),
        ]
        # 5 + 8 + 12 = 25
        assert pipeline.run_total_entity_count() == 25


class TestRunTotalRelationshipCount:
    """Test run_total_relationship_count() method."""

    def test_total_rel_count_empty(self, pipeline):
        """Test with no runs."""
        assert pipeline.run_total_relationship_count() == 0

    def test_total_rel_count_single_run(self, pipeline):
        """Test with single run."""
        pipeline._run_history = [create_result(rel_count=15)]
        assert pipeline.run_total_relationship_count() == 15

    def test_total_rel_count_multiple_runs(self, pipeline):
        """Test with multiple runs."""
        pipeline._run_history = [
            create_result(rel_count=10),
            create_result(rel_count=20),
            create_result(rel_count=30),
        ]
        # 10 + 20 + 30 = 60
        assert pipeline.run_total_relationship_count() == 60


class TestRunAverageEntityCount:
    """Test run_average_entity_count() method."""

    def test_average_entity_count_empty(self, pipeline):
        """Test with no runs."""
        assert pipeline.run_average_entity_count() == 0.0

    def test_average_entity_count_single_run(self, pipeline):
        """Test with single run."""
        pipeline._run_history = [create_result(entity_count=10)]
        assert abs(pipeline.run_average_entity_count() - 10.0) < 0.01

    def test_average_entity_count_multiple_runs(self, pipeline):
        """Test with multiple runs."""
        pipeline._run_history = [
            create_result(entity_count=5),
            create_result(entity_count=10),
            create_result(entity_count=15),
        ]
        # (5 + 10 + 15) / 3 = 10.0
        assert abs(pipeline.run_average_entity_count() - 10.0) < 0.01


class TestRunAverageRelationshipCount:
    """Test run_average_relationship_count() method."""

    def test_average_rel_count_empty(self, pipeline):
        """Test with no runs."""
        assert pipeline.run_average_relationship_count() == 0.0

    def test_average_rel_count_single_run(self, pipeline):
        """Test with single run."""
        pipeline._run_history = [create_result(rel_count=20)]
        assert abs(pipeline.run_average_relationship_count() - 20.0) < 0.01

    def test_average_rel_count_multiple_runs(self, pipeline):
        """Test with multiple runs."""
        pipeline._run_history = [
            create_result(rel_count=10),
            create_result(rel_count=20),
            create_result(rel_count=30),
        ]
        # (10 + 20 + 30) / 3 = 20.0
        assert abs(pipeline.run_average_relationship_count() - 20.0) < 0.01


class TestRunActionFrequency:
    """Test run_action_frequency() method."""

    def test_action_frequency_empty(self, pipeline):
        """Test with no runs."""
        assert pipeline.run_action_frequency() == {}

    def test_action_frequency_single_run(self, pipeline):
        """Test with single run."""
        pipeline._run_history = [create_result(actions=["merge_entities", "add_relationship"])]
        freq = pipeline.run_action_frequency()
        assert freq == {"merge_entities": 1, "add_relationship": 1}

    def test_action_frequency_multiple_runs(self, pipeline):
        """Test with multiple runs."""
        pipeline._run_history = [
            create_result(actions=["merge_entities", "add_relationship"]),
            create_result(actions=["merge_entities", "refine_properties"]),
            create_result(actions=["add_relationship", "merge_entities"]),
        ]
        freq = pipeline.run_action_frequency()
        assert freq == {
            "merge_entities": 3,
            "add_relationship": 2,
            "refine_properties": 1,
        }


class TestRunMostCommonAction:
    """Test run_most_common_action() method."""

    def test_most_common_action_empty(self, pipeline):
        """Test with no runs."""
        assert pipeline.run_most_common_action() == "none"

    def test_most_common_action_single_action(self, pipeline):
        """Test with single action type."""
        pipeline._run_history = [
            create_result(actions=["merge_entities"]),
            create_result(actions=["merge_entities"]),
        ]
        assert pipeline.run_most_common_action() == "merge_entities"

    def test_most_common_action_multiple_types(self, pipeline):
        """Test with multiple action types."""
        pipeline._run_history = [
            create_result(actions=["merge_entities", "add_relationship"]),
            create_result(actions=["merge_entities", "refine_properties"]),
            create_result(actions=["merge_entities"]),
        ]
        # merge_entities appears 3 times
        assert pipeline.run_most_common_action() == "merge_entities"


class TestRunScoreVariance:
    """Test run_score_variance() method."""

    def test_variance_empty(self, pipeline):
        """Test with no runs."""
        assert pipeline.run_score_variance() == 0.0

    def test_variance_single_run(self, pipeline):
        """Test with single run."""
        pipeline._run_history = [create_result(score_val=0.75)]
        assert pipeline.run_score_variance() == 0.0

    def test_variance_identical_scores(self, pipeline):
        """Test with identical scores."""
        pipeline._run_history = [
            create_result(score_val=0.75),
            create_result(score_val=0.75),
            create_result(score_val=0.75),
        ]
        assert pipeline.run_score_variance() == 0.0

    def test_variance_varied_scores(self, pipeline):
        """Test with varied scores."""
        pipeline._run_history = [
            create_result(score_val=0.5),
            create_result(score_val=0.7),
            create_result(score_val=0.9),
        ]
        # Mean = 0.7, variance = [(0.5-0.7)^2 + (0.7-0.7)^2 + (0.9-0.7)^2] / 3
        # = [0.04 + 0.0 + 0.04] / 3 = 0.0267
        variance = pipeline.run_score_variance()
        assert abs(variance - 0.0267) < 0.001


class TestRunScoreStdDev:
    """Test run_score_std_dev() method."""

    def test_std_dev_empty(self, pipeline):
        """Test with no runs."""
        assert pipeline.run_score_std_dev() == 0.0

    def test_std_dev_single_run(self, pipeline):
        """Test with single run."""
        pipeline._run_history = [create_result(score_val=0.75)]
        assert pipeline.run_score_std_dev() == 0.0

    def test_std_dev_varied_scores(self, pipeline):
        """Test with varied scores."""
        pipeline._run_history = [
            create_result(score_val=0.5),
            create_result(score_val=0.7),
            create_result(score_val=0.9),
        ]
        # Variance = 0.0267, std_dev = sqrt(0.0267) ≈ 0.163
        std_dev = pipeline.run_score_std_dev()
        assert abs(std_dev - 0.163) < 0.01


class TestRunScoreCoefficientOfVariation:
    """Test run_score_coefficient_of_variation() method."""

    def test_cv_empty(self, pipeline):
        """Test with no runs."""
        assert pipeline.run_score_coefficient_of_variation() == 0.0

    def test_cv_single_run(self, pipeline):
        """Test with single run."""
        pipeline._run_history = [create_result(score_val=0.75)]
        assert pipeline.run_score_coefficient_of_variation() == 0.0

    def test_cv_identical_scores(self, pipeline):
        """Test with identical scores (std_dev = 0)."""
        pipeline._run_history = [
            create_result(score_val=0.75),
            create_result(score_val=0.75),
        ]
        assert pipeline.run_score_coefficient_of_variation() == 0.0

    def test_cv_varied_scores(self, pipeline):
        """Test with varied scores."""
        pipeline._run_history = [
            create_result(score_val=0.5),
            create_result(score_val=0.7),
            create_result(score_val=0.9),
        ]
        # Mean = 0.7, std_dev ≈ 0.163, CV = 0.163 / 0.7 ≈ 0.233
        cv = pipeline.run_score_coefficient_of_variation()
        assert abs(cv - 0.233) < 0.01

    def test_cv_zero_mean(self, pipeline):
        """Test CV when mean is zero."""
        pipeline._run_history = [
            create_result(score_val=0.0),
            create_result(score_val=0.0),
        ]
        assert pipeline.run_score_coefficient_of_variation() == 0.0


class TestRunHasImprovingTrend:
    """Test run_has_improving_trend() method."""

    def test_improving_trend_empty(self, pipeline):
        """Test with no runs."""
        assert pipeline.run_has_improving_trend() is False

    def test_improving_trend_single_run(self, pipeline):
        """Test with single run."""
        pipeline._run_history = [create_result(score_val=0.75)]
        assert pipeline.run_has_improving_trend() is False

    def test_improving_trend_true(self, pipeline):
        """Test with improving scores."""
        pipeline._run_history = [
            create_result(score_val=0.5),
            create_result(score_val=0.6),
            create_result(score_val=0.7),
            create_result(score_val=0.8),
        ]
        # Window of 3: last 3 runs are [0.6, 0.7, 0.8], 0.8 > 0.6
        assert pipeline.run_has_improving_trend(window=3) is True

    def test_improving_trend_false(self, pipeline):
        """Test with degrading scores."""
        pipeline._run_history = [
            create_result(score_val=0.8),
            create_result(score_val=0.7),
            create_result(score_val=0.6),
        ]
        # 0.6 < 0.8
        assert pipeline.run_has_improving_trend(window=3) is False

    def test_improving_trend_stable(self, pipeline):
        """Test with stable scores."""
        pipeline._run_history = [
            create_result(score_val=0.75),
            create_result(score_val=0.75),
            create_result(score_val=0.75),
        ]
        assert pipeline.run_has_improving_trend(window=3) is False


class TestBatch204Integration:
    """Integration tests combining multiple Batch 204 methods."""

    def test_comprehensive_run_analysis(self, pipeline):
        """Test complete analysis workflow."""
        pipeline._run_history = [
            create_result(entity_count=10, rel_count=20, score_val=0.6, actions=["merge_entities"]),
            create_result(entity_count=15, rel_count=25, score_val=0.7, actions=["merge_entities", "add_relationship"]),
            create_result(entity_count=12, rel_count=22, score_val=0.8, actions=["merge_entities"]),
        ]

        # Entity/relationship aggregates
        assert pipeline.run_total_entity_count() == 37  # 10 + 15 + 12
        assert pipeline.run_total_relationship_count() == 67  # 20 + 25 + 22
        assert abs(pipeline.run_average_entity_count() - 12.333) < 0.01
        assert abs(pipeline.run_average_relationship_count() - 22.333) < 0.01

        # Action analysis
        assert pipeline.run_most_common_action() == "merge_entities"
        freq = pipeline.run_action_frequency()
        assert freq["merge_entities"] == 3
        assert freq["add_relationship"] == 1

        # Score analysis
        assert pipeline.run_score_variance() > 0.0
        assert pipeline.run_score_std_dev() > 0.0
        assert pipeline.run_has_improving_trend() is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
