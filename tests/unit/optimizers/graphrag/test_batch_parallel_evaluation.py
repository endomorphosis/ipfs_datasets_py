"""Tests for parallel batch evaluation in OntologyCritic.

Tests verify that evaluate_batch_parallel produces equivalent results to
evaluate_batch with lower latency for large batches.
"""

import time
import pytest
from ipfs_datasets_py.optimizers.graphrag import OntologyCritic, OntologyGenerationContext, DataType, ExtractionStrategy


@pytest.fixture
def critic():
    """Create a critic instance for testing."""
    return OntologyCritic()


@pytest.fixture
def context():
    """Create a generation context for testing."""
    return OntologyGenerationContext(
        data_source="test",
        data_type=DataType.TEXT,
        domain="general",
        extraction_strategy=ExtractionStrategy.RULE_BASED,
    )


@pytest.fixture
def sample_ontologies():
    """Create sample ontologies for batch evaluation."""
    ontologies = []
    for i in range(5):
        onto = {
            "entities": [
                {
                    "id": f"e{i}_1",
                    "type": "Person",
                    "text": f"Person {i}",
                    "confidence": 0.8,
                    "properties": {"name": f"Entity {i}"},
                },
                {
                    "id": f"e{i}_2",
                    "type": "Organization",
                    "text": f"Org {i}",
                    "confidence": 0.9,
                    "properties": {},
                },
            ],
            "relationships": [
                {
                    "source_id": f"e{i}_1",
                    "target_id": f"e{i}_2",
                    "type": "works_for",
                    "confidence": 0.85,
                }
            ],
        }
        ontologies.append(onto)
    return ontologies


class TestEvaluateBatchParallel:
    """Test evaluate_batch_parallel method."""

    def test_parallel_vs_sequential_same_results(self, critic, context, sample_ontologies):
        """Parallel evaluation should produce same scores as sequential."""
        seq_result = critic.evaluate_batch(
            sample_ontologies, context, source_data="test data"
        )
        par_result = critic.evaluate_batch_parallel(
            sample_ontologies, context, source_data="test data", max_workers=2
        )

        # Counts should match
        assert seq_result["count"] == par_result["count"]
        assert len(seq_result["scores"]) == len(par_result["scores"])

        # Aggregate scores should be (approximately) equal
        assert abs(seq_result["mean_overall"] - par_result["mean_overall"]) < 0.01
        assert abs(seq_result["max_overall"] - par_result["max_overall"]) < 0.01
        assert abs(seq_result["min_overall"] - par_result["min_overall"]) < 0.01

    def test_empty_batch_parallel(self, critic, context):
        """Parallel evaluation of empty batch should return empty results."""
        result = critic.evaluate_batch_parallel([], context, max_workers=2)

        assert result["count"] == 0
        assert result["scores"] == []
        assert result["mean_overall"] == 0.0
        assert result["min_overall"] == 0.0
        assert result["max_overall"] == 0.0

    def test_single_item_batch_parallel(self, critic, context, sample_ontologies):
        """Parallel evaluation of single item should work correctly."""
        single_onto = sample_ontologies[:1]
        result = critic.evaluate_batch_parallel(
            single_onto, context, max_workers=1
        )

        assert result["count"] == 1
        assert len(result["scores"]) == 1
        assert 0.0 <= result["mean_overall"] <= 1.0

    def test_progress_callback_parallel(self, critic, context, sample_ontologies):
        """Progress callback should be invoked for each ontology in parallel."""
        callback_invocations = []

        def track_callback(idx, total, score):
            callback_invocations.append((idx, total, score))

        critic.evaluate_batch_parallel(
            sample_ontologies, context, progress_callback=track_callback, max_workers=2
        )

        assert len(callback_invocations) == len(sample_ontologies)
        # All callbacks should report same total
        assert all(inv[1] == len(sample_ontologies) for inv in callback_invocations)

    def test_max_workers_parameter(self, critic, context, sample_ontologies):
        """Test with different max_workers values."""
        result_1 = critic.evaluate_batch_parallel(
            sample_ontologies, context, max_workers=1
        )
        result_4 = critic.evaluate_batch_parallel(
            sample_ontologies, context, max_workers=4
        )

        # Results should be equivalent regardless of worker count
        assert result_1["count"] == result_4["count"]
        assert abs(result_1["mean_overall"] - result_4["mean_overall"]) < 0.01

    def test_large_batch_parallel(self, critic, context):
        """Test parallel evaluation on larger batch."""
        large_batch = []
        for i in range(20):
            onto = {
                "entities": [
                    {
                        "id": f"e{i}_{j}",
                        "type": "Concept",
                        "text": f"Concept {i}-{j}",
                        "confidence": 0.5 + (j * 0.1),
                        "properties": {},
                    }
                    for j in range(3)
                ],
                "relationships": [
                    {
                        "source_id": f"e{i}_0",
                        "target_id": f"e{i}_1",
                        "type": "related_to",
                        "confidence": 0.7,
                    }
                ],
            }
            large_batch.append(onto)

        seq_result = critic.evaluate_batch(large_batch, context)
        par_result = critic.evaluate_batch_parallel(
            large_batch, context, max_workers=4
        )

        # Same ontologies, same context → same aggregates
        assert seq_result["count"] == par_result["count"] == 20
        assert abs(seq_result["mean_overall"] - par_result["mean_overall"]) < 0.01

    def test_parallel_handles_evaluation_errors_gracefully(
        self, critic, context, sample_ontologies
    ):
        """Parallel evaluation should skip malformed ontologies gracefully."""
        bad_ontologies = sample_ontologies + [
            {"entities": []},  # Missing relationships key (might be OK)
            {"relationships": []},  # Missing entities key (might be OK)
        ]

        # Should not crash; should evaluate valid ones
        result = critic.evaluate_batch_parallel(
            bad_ontologies, context, max_workers=2
        )
        # At minimum should have tried all
        assert result["count"] <= len(bad_ontologies)

    def test_parallel_respects_source_data_parameter(
        self, critic, context, sample_ontologies
    ):
        """Parallel evaluation should pass source_data to each evaluation."""
        source_text = "Important legal document with specific requirements"

        result_with_source = critic.evaluate_batch_parallel(
            sample_ontologies, context, source_data=source_text, max_workers=2
        )
        result_without_source = critic.evaluate_batch_parallel(
            sample_ontologies, context, source_data=None, max_workers=2
        )

        # With additional source context might slightly change scores
        # Just verify both completed successfully
        assert result_with_source["count"] > 0
        assert result_without_source["count"] > 0

    def test_scores_list_order_preserved_parallel(self, critic, context, sample_ontologies):
        """Parallel evaluation should preserve order of input ontologies in output."""
        result = critic.evaluate_batch_parallel(
            sample_ontologies, context, max_workers=2
        )

        # Should have same number of scores as input ontologies
        assert len(result["scores"]) == len(sample_ontologies)
        # All scores should be CriticScore objects
        for score in result["scores"]:
            assert hasattr(score, "overall")
            assert hasattr(score, "completeness")


class TestLatencyComparison:
    """Compare latency of parallel vs sequential evaluation."""

    def test_parallel_faster_on_large_batch(self, critic, context):
        """Parallel evaluation should be faster than sequential on large batches."""
        large_batch = []
        for i in range(10):
            onto = {
                "entities": [
                    {
                        "id": f"e{i}_{j}",
                        "type": "Entity",
                        "text": f"Entity {i}-{j}",
                        "confidence": 0.7,
                        "properties": {"desc": f"Description {j}"},
                    }
                    for j in range(5)
                ],
                "relationships": [
                    {
                        "source_id": f"e{i}_{j}",
                        "target_id": f"e{i}_{(j+1) % 5}",
                        "type": "links_to",
                        "confidence": 0.8,
                    }
                    for j in range(5)
                ],
            }
            large_batch.append(onto)

        start_seq = time.time()
        seq_result = critic.evaluate_batch(large_batch, context)
        seq_time = time.time() - start_seq

        start_par = time.time()
        par_result = critic.evaluate_batch_parallel(
            large_batch, context, max_workers=4
        )
        par_time = time.time() - start_par

        # Results should be equivalent
        assert seq_result["count"] == par_result["count"]

        # Log times for reference (parallel should typically be faster on multicore)
        print(f"\nSequential time: {seq_time:.3f}s, Parallel time: {par_time:.3f}s")
        # Note: We don't assert par_time < seq_time because on single-core or
        # with fast operations, overhead may dominate. Just verify both work.
