"""
Tests for Batch Strategy Recommendation API - Batch 232 [api].

Comprehensive test coverage for batch strategy recommendation including:
- Basic batch processing
- Error handling
- Progress tracking
- Summary statistics
- Performance validation
- Edge cases
"""

import pytest
import time
from typing import List

from ipfs_datasets_py.optimizers.common.batch_strategy_recommender import (
    BatchStrategyRecommender,
    OntologyRef,
    StrategyRecommendation,
    BatchStrategySummary,
    create_batch_recommender,
)


# ============================================================================
# Test Data Fixtures
# ============================================================================


@pytest.fixture
def sample_ontologies() -> List[OntologyRef]:
    """Create sample ontologies for testing."""
    return [
        OntologyRef(
            ontology_id="ont_001",
            data={
                "entities": [
                    {"id": "e1", "name": "Company", "type": "Organization"},
                    {"id": "e2", "name": "Contract", "type": "Document"},
                ],
                "relationships": [
                    {"source": "e1", "target": "e2", "type": "signs"},
                ],
            },
            metadata={"domain": "legal"},
        ),
        OntologyRef(
            ontology_id="ont_002",
            data={
                "entities": [
                    {"id": "p1", "name": "Patient", "type": "Person"},
                    {"id": "d1", "name": "Diagnosis", "type": "Condition"},
                    {"id": "t1", "name": "Treatment", "type": "Procedure"},
                ],
                "relationships": [
                    {"source": "p1", "target": "d1", "type": "has"},
                    {"source": "d1", "target": "t1", "type": "requires"},
                ],
            },
            metadata={"domain": "medical"},
        ),
        OntologyRef(
            ontology_id="ont_003",
            data={
                "entities": [],  # Empty ontology
                "relationships": [],
            },
            metadata={"domain": "technical"},
        ),
    ]


@pytest.fixture
def empty_ontology() -> OntologyRef:
    """Create an empty ontology."""
    return OntologyRef(
        ontology_id="empty_001",
        data={"entities": [], "relationships": []},
    )


@pytest.fixture
def sparse_ontology() -> OntologyRef:
    """Create ontology with low relationship density."""
    return OntologyRef(
        ontology_id="sparse_001",
        data={
            "entities": [
                {"id": f"e{i}", "name": f"Entity{i}", "type": "Thing"}
                for i in range(10)
            ],
            "relationships": [
                {"source": "e1", "target": "e2", "type": "related"},
            ],  # Only 1 relationship for 10 entities
        },
    )


# ============================================================================
# Tests: Basic Batch Processing
# ============================================================================


class TestBasicBatchProcessing:
    """Test basic batch processing functionality."""

    def test_recommend_single_ontology(self, empty_ontology):
        """Test recommendation for single ontology."""
        recommender = create_batch_recommender()
        
        recommendations, summary = recommender.recommend_strategies_batch(
            [empty_ontology]
        )
        
        assert len(recommendations) == 1
        assert recommendations[0].ontology_id == "empty_001"
        assert summary.total_processed == 1
        assert summary.successful == 1

    def test_recommend_multiple_ontologies(self, sample_ontologies):
        """Test recommendation for multiple ontologies."""
        recommender = create_batch_recommender()
        
        recommendations, summary = recommender.recommend_strategies_batch(
            sample_ontologies
        )
        
        assert len(recommendations) >= 2  # At least some successful
        assert summary.total_processed == 3
        assert summary.successful > 0

    def test_recommendations_have_required_fields(self, sample_ontologies):
        """Test that recommendations include all required fields."""
        recommender = create_batch_recommender()
        recommendations, _ = recommender.recommend_strategies_batch(sample_ontologies)
        
        for rec in recommendations:
            assert rec.ontology_id is not None
            assert rec.strategy_type is not None
            assert rec.recommendation is not None
            assert 0 <= rec.confidence <= 1
            assert rec.computation_time_ms >= 0

    def test_strategy_types_are_valid(self, sample_ontologies):
        """Test that recommended strategy types are valid."""
        valid_types = {
            "add_missing_relationships",
            "prune_orphans",
            "merge_duplicates",
            "split_entity",
            "seed_entities",
            "add_missing_properties",
            "normalize_names",
            "validate_relationships",
        }
        
        recommender = create_batch_recommender()
        recommendations, _ = recommender.recommend_strategies_batch(sample_ontologies)
        
        for rec in recommendations:
            assert rec.strategy_type in valid_types


# ============================================================================
# Tests: Empty and Edge Cases
# ============================================================================


class TestEdgeCases:
    """Test edge cases and special scenarios."""

    def test_empty_batch(self):
        """Test processing empty ontology list."""
        recommender = create_batch_recommender()
        
        recommendations, summary = recommender.recommend_strategies_batch([])
        
        assert len(recommendations) == 0
        assert summary.total_processed == 0
        assert summary.successful == 0

    def test_empty_ontology_recommendation(self, empty_ontology):
        """Test recommendation for empty ontology."""
        recommender = create_batch_recommender()
        
        recommendations, summary = recommender.recommend_strategies_batch(
            [empty_ontology]
        )
        
        # Empty ontology should recommend seeding
        assert len(recommendations) > 0
        rec = recommendations[0]
        assert rec.strategy_type == "seed_entities"

    def test_sparse_ontology_recommendation(self, sparse_ontology):
        """Test recommendation for sparse/disconnected ontology."""
        recommender = create_batch_recommender()
        
        recommendations, summary = recommender.recommend_strategies_batch(
            [sparse_ontology]
        )
        
        # Sparse ontology should recommend adding relationships
        assert len(recommendations) > 0
        rec = recommendations[0]
        assert rec.strategy_type in [
            "add_missing_relationships",
            "prune_orphans",
        ]

    def test_confidence_threshold_filtering(self, sample_ontologies):
        """Test confidence threshold filtering."""
        recommender = create_batch_recommender()
        
        # Get results with low confidence threshold
        recommendations_low, summary_low = recommender.recommend_strategies_batch(
            sample_ontologies,
            confidence_threshold=0.0,
        )
        
        # Get results with high confidence threshold
        recommendations_high, summary_high = recommender.recommend_strategies_batch(
            sample_ontologies,
            confidence_threshold=0.95,
        )
        
        # High threshold should have fewer or equal recommendations
        assert len(recommendations_high) <= len(recommendations_low)


# ============================================================================
# Tests: Strategy Type Filtering
# ============================================================================


class TestStrategyTypeFiltering:
    """Test filtering by strategy type."""

    @pytest.mark.xfail(reason="strategy_type filtering not fully implemented in batch recommender")
    def test_filter_by_strategy_type(self, sample_ontologies):
        """Test filtering recommendations by type."""
        recommender = create_batch_recommender()
        
        recommendations_filtered, _ = recommender.recommend_strategies_batch(
            sample_ontologies,
            strategy_type="add_missing_relationships",
        )
        
        # All filtered recommendations should match the requested strategy type
        for rec in recommendations_filtered:
            assert rec.strategy_type == "add_missing_relationships"

    def test_alternative_strategies_provided(self, sample_ontologies):
        """Test that alternative strategies are included."""
        recommender = create_batch_recommender()
        
        recommendations, _ = recommender.recommend_strategies_batch(
            sample_ontologies,
            max_per_ontology=3,
        )
        
        for rec in recommendations:
            # Should have alternatives
            if len(rec.alternatives) > 0:
                # All alternatives should have type and confidence
                for alt in rec.alternatives:
                    assert "type" in alt
                    assert "confidence" in alt


# ============================================================================
# Tests: Summary Statistics
# ============================================================================


class TestSummaryStatistics:
    """Test summary statistics computation."""

    def test_summary_counts_accurate(self, sample_ontologies):
        """Test that summary counts are accurate."""
        recommender = create_batch_recommender()
        
        recommendations, summary = recommender.recommend_strategies_batch(
            sample_ontologies
        )
        
        assert summary.successful == len(recommendations)
        assert summary.total_processed == len(sample_ontologies)
        assert summary.successful + summary.failed + summary.skipped == summary.total_processed

    def test_confidence_statistics(self, sample_ontologies):
        """Test confidence score statistics."""
        recommender = create_batch_recommender()
        
        _, summary = recommender.recommend_strategies_batch(sample_ontologies)
        
        stats = summary.confidence_stats
        assert "average" in stats
        assert "min" in stats
        assert "max" in stats
        assert "median" in stats
        
        # All values should be between 0 and 1
        assert 0 <= stats["average"] <= 1
        assert 0 <= stats["min"] <= 1
        assert 0 <= stats["max"] <= 1
        assert 0 <= stats["median"] <= 1

    def test_strategy_distribution(self, sample_ontologies):
        """Test strategy type distribution."""
        recommender = create_batch_recommender()
        
        recommendations, summary = recommender.recommend_strategies_batch(
            sample_ontologies
        )
        
        # Distribution should match recommendations
        total_in_distribution = sum(summary.strategy_distribution.values())
        assert total_in_distribution == len(recommendations)

    def test_timing_statistics(self, sample_ontologies):
        """Test that timing statistics are computed."""
        recommender = create_batch_recommender()
        
        _, summary = recommender.recommend_strategies_batch(sample_ontologies)
        
        assert summary.total_time_ms > 0
        assert summary.average_time_per_ontology_ms >= 0
        
        # Average should be reasonable
        if summary.successful > 0:
            assert summary.average_time_per_ontology_ms < summary.total_time_ms


# ============================================================================
# Tests: Progress Tracking
# ============================================================================


class TestProgressTracking:
    """Test progress callback functionality."""

    def test_progress_callback_invoked(self, sample_ontologies):
        """Test that progress callback is called."""
        call_count = 0
        callback_args = []
        
        def progress_callback(processed: int, total: int):
            nonlocal call_count
            call_count += 1
            callback_args.append((processed, total))
        
        recommender = create_batch_recommender()
        
        recommendations, _ = recommender.recommend_strategies_batch(
            sample_ontologies,
            progress_callback=progress_callback,
        )
        
        # Callback should be called for each ontology
        assert call_count == len(sample_ontologies)
        
        # Progress should be monotonic
        processed_values = [args[0] for args in callback_args]
        assert processed_values == sorted(processed_values)

    def test_progress_callback_with_large_batch(self):
        """Test progress tracking with larger batch."""
        batch_size = 50
        ontologies = [
            OntologyRef(
                ontology_id=f"ont_{i:04d}",
                data={"entities": [], "relationships": []},
            )
            for i in range(batch_size)
        ]
        
        call_count = 0
        
        def progress_callback(processed: int, total: int):
            nonlocal call_count
            call_count += 1
        
        recommender = create_batch_recommender()
        
        _, _ = recommender.recommend_strategies_batch(
            ontologies,
            progress_callback=progress_callback,
        )
        
        assert call_count == batch_size


# ============================================================================
# Tests: Performance
# ============================================================================


class TestPerformance:
    """Test performance characteristics."""

    def test_batch_performance_target(self):
        """Test that batch processing meets performance targets."""
        # Create 100 ontologies
        batch_size = 100
        ontologies = [
            OntologyRef(
                ontology_id=f"ont_{i:04d}",
                data={
                    "entities": [{"id": f"e{j}", "name": f"Entity{j}"}
                               for j in range(5)],
                    "relationships": [{"source": "e1", "target": "e2"}],
                },
            )
            for i in range(batch_size)
        ]
        
        recommender = create_batch_recommender()
        
        start = time.perf_counter()
        recommendations, summary = recommender.recommend_strategies_batch(ontologies)
        elapsed_ms = (time.perf_counter() - start) * 1000
        
        # Performance target: 100 ontologies in <5 seconds
        assert elapsed_ms < 5000, f"Batch took {elapsed_ms:.1f}ms, target <5000ms"
        
        # Average per ontology should be reasonable (<50ms)
        average_ms = elapsed_ms / batch_size
        assert average_ms < 50, f"Average {average_ms:.1f}ms/ontology, target <50ms"

    def test_summary_computation_efficient(self, sample_ontologies):
        """Test that summary computation is efficient."""
        recommender = create_batch_recommender()
        
        recommendations, summary = recommender.recommend_strategies_batch(
            sample_ontologies
        )
        
        # Summary should exist and be populated
        assert summary is not None
        assert isinstance(summary, BatchStrategySummary)


# ============================================================================
# Tests: Factory Function
# ============================================================================


class TestFactoryFunction:
    """Test the factory function."""

    def test_create_batch_recommender(self):
        """Test creating recommender via factory."""
        recommender = create_batch_recommender()
        
        assert isinstance(recommender, BatchStrategyRecommender)
        assert recommender.max_batch_size == 100

    def test_create_with_custom_batch_size(self):
        """Test creating recommender with custom batch size."""
        recommender = create_batch_recommender(max_batch_size=500)
        
        assert recommender.max_batch_size == 500


# ============================================================================
# Integration Tests
# ============================================================================


class TestIntegration:
    """Integration tests combining multiple features."""

    def test_full_workflow(self, sample_ontologies):
        """Test complete batch recommendation workflow."""
        recommender = create_batch_recommender()
        
        progress_calls = []
        
        def track_progress(processed, total):
            progress_calls.append((processed, total))
        
        # Run full batch with all features
        recommendations, summary = recommender.recommend_strategies_batch(
            sample_ontologies,
            strategy_type=None,
            max_per_ontology=3,
            confidence_threshold=0.5,
            progress_callback=track_progress,
        )
        
        # Verify all aspects
        assert len(progress_calls) == len(sample_ontologies)
        assert summary.total_processed == len(sample_ontologies)
        assert len(recommendations) > 0
        assert len(summary.strategy_distribution) > 0

    def test_batch_with_diverse_ontologies(self):
        """Test batch processing with diverse ontology characteristics."""
        ontologies = [
            # Empty
            OntologyRef(
                ontology_id="empty",
                data={"entities": [], "relationships": []},
            ),
            # Dense
            OntologyRef(
                ontology_id="dense",
                data={
                    "entities": [
                        {"id": f"e{i}", "name": f"Ent{i}", "properties": {"type": "thing"}}
                        for i in range(5)
                    ],
                    "relationships": [
                        {"source": f"e{i}", "target": f"e{j}", "type": "links"}
                        for i in range(5)
                        for j in range(i + 1, min(i + 3, 5))
                    ],
                },
            ),
            # Sparse
            OntologyRef(
                ontology_id="sparse",
                data={
                    "entities": [
                        {"id": f"e{i}", "name": f"Entity{i}"}
                        for i in range(10)
                    ],
                    "relationships": [{"source": "e0", "target": "e1"}],
                },
            ),
        ]
        
        recommender = create_batch_recommender()
        recommendations, summary = recommender.recommend_strategies_batch(ontologies)
        
        # All different ontology types should be processed
        assert summary.total_processed == 3
        assert len(summary.strategy_distribution) > 1
        
        # Should have recommendations for different strategy types
        strategy_types = set(rec.strategy_type for rec in recommendations)
        assert len(strategy_types) > 1


class TestExceptionHandling:
    """Test typed exception handling during batch recommendation."""

    def test_typed_runtime_error_is_recorded_as_failure(self, sample_ontologies, monkeypatch):
        recommender = create_batch_recommender()

        def _broken_single(*args, **kwargs):
            raise RuntimeError("recommendation failed")

        monkeypatch.setattr(
            BatchStrategyRecommender,
            "_recommend_for_single",
            staticmethod(_broken_single),
        )

        recommendations, summary = recommender.recommend_strategies_batch(sample_ontologies)

        assert recommendations == []
        assert summary.failed == len(sample_ontologies)
        assert summary.successful == 0

    def test_keyboard_interrupt_propagates(self, sample_ontologies, monkeypatch):
        recommender = create_batch_recommender()

        def _interrupt_single(*args, **kwargs):
            raise KeyboardInterrupt()

        monkeypatch.setattr(
            BatchStrategyRecommender,
            "_recommend_for_single",
            staticmethod(_interrupt_single),
        )

        with pytest.raises(KeyboardInterrupt):
            recommender.recommend_strategies_batch(sample_ontologies)
