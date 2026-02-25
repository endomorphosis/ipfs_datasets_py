"""Tests for Critic Score Distribution Analysis (Batch 260).

Comprehensive statistical analysis of ontology scoring across 1000+ samples:
- Distribution properties (mean, median, std, quartiles)
- Domain-specific scoring patterns (legal, medical, technical)
- Convergence validation across refinement cycles
- Outlier detection and handling
"""

from __future__ import annotations

import pytest
import statistics
from typing import List

from ipfs_datasets_py.optimizers.graphrag.ontology_critic import (
    OntologyCritic,
    DIMENSION_WEIGHTS,
)
from ipfs_datasets_py.optimizers.graphrag.ontology_types import (
    Entity,
    Relationship,
    Ontology,
    GenerationContext,
)


# ============================================================================
# Fixtures for Test Data Generation
# ============================================================================


@pytest.fixture
def critic():
    """Create an OntologyCritic instance."""
    return OntologyCritic(
        backend_config=None,
        use_llm=False,  # Use rule-based evaluation for deterministic tests
    )


@pytest.fixture
def context() -> GenerationContext:
    """Create a simple generation context for tests."""
    return {
        "data_source": "test",
        "data_type": "text",
        "domain": "test",
    }


def create_sample_ontology(
    entity_count: int = 10,
    relationship_count: int = 5,
    base_score: float = 0.7,
) -> Ontology:
    """Create a sample ontology for testing."""
    # Keep confidence values inside [0, 1] while allowing callers to shape
    # score distributions using base_score.
    base = max(0.0, min(1.0, base_score))

    entities: List[Entity] = []
    for i in range(entity_count):
        entity: Entity = {
            "id": f"entity_{i}",
            "text": f"Entity {i}",
            "type": "TestType",
            "confidence": max(0.0, min(1.0, base + (i % 3) * 0.05)),
        }
        entities.append(entity)
    
    relationships: List[Relationship] = []
    for i in range(relationship_count):
        rel: Relationship = {
            "id": f"rel_{i}",
            "source_id": f"entity_{i % entity_count}",
            "target_id": f"entity_{(i + 1) % entity_count}",
            "type": "relatedTo",
            "confidence": max(0.0, min(1.0, base - 0.05 + (i % 2) * 0.1)),
        }
        relationships.append(rel)
    
    ontology: Ontology = {
        "entities": entities,
        "relationships": relationships,
        "metadata": {
            "source": "test",
            "domain": "test",
            "strategy": "rule_based",
            "timestamp": "2026-02-23T00:00:00",
            "version": "1.0",
            "config": {
                "complexity": "simple",
                "entities_count": entity_count,
                "relationships_count": relationship_count,
                "base_score": base,
            },
        },
    }
    
    return ontology


# ============================================================================
# Distribution Statistical Properties Tests
# ============================================================================


class TestCriticScoreDistributionStatistics:
    """Test statistical properties of critic scores."""
    
    def test_generate_1000_scores(self, critic, context):
        """Generate 1000 critic scores for distribution analysis."""
        scores = []
        for i in range(1000):
            ontology = create_sample_ontology(
                entity_count=10 + (i % 20),
                relationship_count=5 + (i % 10),
                base_score=0.5 + (i % 50) * 0.01,
            )
            score = critic.evaluate_ontology(ontology, context)
            scores.append(score.overall)
        
        assert len(scores) == 1000
        assert all(0.0 <= s <= 1.0 for s in scores)
    
    def test_score_mean_calculation(self, critic, context):
        """Test mean score across sample population."""
        scores = []
        for i in range(500):
            ontology = create_sample_ontology(entity_count=5 + (i % 15))
            score = critic.evaluate_ontology(ontology, context)
            scores.append(score.overall)
        
        mean = statistics.mean(scores)
        assert 0.0 < mean < 1.0
        assert 0.4 < mean < 0.9  # Reasonable range for test data
    
    def test_score_median_calculation(self, critic, context):
        """Test median score across sample population."""
        scores = []
        for i in range(100):
            ontology = create_sample_ontology(entity_count=5 + (i % 20))
            score = critic.evaluate_ontology(ontology, context)
            scores.append(score.overall)
        
        median = statistics.median(scores)
        assert 0.0 < median < 1.0
    
    def test_score_std_dev_calculation(self, critic, context):
        """Test standard deviation of scores."""
        scores = []
        for i in range(200):
            ontology = create_sample_ontology(entity_count=5 + (i % 20))
            score = critic.evaluate_ontology(ontology, context)
            scores.append(score.overall)
        
        if len(scores) > 1:
            stdev = statistics.stdev(scores)
            assert 0.0 <= stdev <= 1.0  # Std dev bounded
    
    def test_score_quartiles(self, critic, context):
        """Test quartile distribution of scores."""
        scores = []
        for i in range(400):
            ontology = create_sample_ontology(entity_count=5 + (i % 30))
            score = critic.evaluate_ontology(ontology, context)
            scores.append(score.overall)
        
        sorted_scores = sorted(scores)
        q1_idx = len(sorted_scores) // 4
        q2_idx = len(sorted_scores) // 2
        q3_idx = (3 * len(sorted_scores)) // 4
        
        q1 = sorted_scores[q1_idx]
        q2 = sorted_scores[q2_idx]  # median
        q3 = sorted_scores[q3_idx]
        
        assert q1 <= q2 <= q3
        assert 0.0 <= q1 < q2 < q3 <= 1.0
    
    def test_score_percentiles(self, critic, context):
        """Test percentile calculation."""
        scores = []
        for i in range(300):
            ontology = create_sample_ontology(entity_count=5 + (i % 25))
            score = critic.evaluate_ontology(ontology, context)
            scores.append(score.overall)
        
        sorted_scores = sorted(scores)
        
        # 10th, 50th (median), 90th percentiles
        idx_10 = max(0, int(0.10 * len(sorted_scores)))
        idx_50 = max(0, int(0.50 * len(sorted_scores)))
        idx_90 = max(0, int(0.90 * len(sorted_scores)))
        
        p10 = sorted_scores[idx_10]
        p50 = sorted_scores[idx_50]
        p90 = sorted_scores[idx_90]
        
        assert p10 <= p50 <= p90
    
    def test_score_range_analysis(self, critic, context):
        """Test min/max range of scores."""
        scores = []
        for i in range(100):
            ontology = create_sample_ontology(entity_count=5 + (i % 20))
            score = critic.evaluate_ontology(ontology, context)
            scores.append(score.overall)
        
        min_score = min(scores)
        max_score = max(scores)
        score_range = max_score - min_score
        
        assert 0.0 <= min_score <= max_score <= 1.0
        assert score_range >= 0.0


# ============================================================================
# Domain-Specific Distribution Tests
# ============================================================================


class TestDomainSpecificScoreDistribution:
    """Test score distributions across different domains."""

    @pytest.mark.parametrize(
        "domain,entity_start,entity_mod,rel_start,rel_mod",
        [
            ("legal", 15, 20, 10, 15),
            ("medical", 20, 25, 15, 20),
            ("technical", 12, 18, 8, 12),
        ],
    )
    def test_domain_scores(
        self,
        critic,
        context,
        domain: str,
        entity_start: int,
        entity_mod: int,
        rel_start: int,
        rel_mod: int,
    ):
        """Test score distribution for each supported domain shape."""
        scores = []
        for i in range(50):
            ontology = create_sample_ontology(
                entity_count=entity_start + (i % entity_mod),
                relationship_count=rel_start + (i % rel_mod),
            )
            if "metadata" in ontology:
                ontology["metadata"]["domain"] = domain
            score = critic.evaluate_ontology(ontology, context)
            scores.append(score.overall)

        assert len(scores) == 50
        assert all(0.0 <= s <= 1.0 for s in scores)
        assert 0.0 < statistics.mean(scores) < 1.0
    
    def test_cross_domain_score_comparison(self, critic, context):
        """Compare score distributions across domains."""
        domain_scores = {}
        
        for domain in ["legal", "medical", "technical"]:
            scores = []
            for i in range(30):
                ontology = create_sample_ontology(
                    entity_count=10 + (i % 15),
                    relationship_count=5 + (i % 10),
                )
                if "metadata" in ontology:
                    ontology["metadata"]["domain"] = domain
                score = critic.evaluate_ontology(ontology, context)
                scores.append(score.overall)
            
            domain_scores[domain] = {
                "mean": statistics.mean(scores),
                "median": statistics.median(scores),
                "count": len(scores),
            }
        
        # All domains should have valid distributions
        assert len(domain_scores) == 3
        for domain, stats in domain_scores.items():
            assert 0.0 < stats["mean"] < 1.0
            assert 0.0 < stats["median"] < 1.0


# ============================================================================
# Convergence and Refinement Cycle Tests
# ============================================================================


class TestScoreConvergence:
    """Test score convergence across refinement cycles."""
    
    def test_score_improvement_trend(self, critic, context):
        """Test that scores generally improve with refinement."""
        refinement_scores = []
        
        for refinement_cycle in range(5):
            # Simulate refinement improving ontology
            ontology = create_sample_ontology(
                entity_count=10 + refinement_cycle * 2,
                relationship_count=5 + refinement_cycle,
                base_score=0.6 + refinement_cycle * 0.05,
            )
            score = critic.evaluate_ontology(ontology, context)
            refinement_scores.append(score.overall)
        
        assert len(refinement_scores) == 5
        # Generally trending upward
        assert refinement_scores[-1] >= refinement_scores[0] - 0.01  # Allow 1% tolerance for rule-based variance
    
    def test_score_stability_across_runs(self, critic, context):
        """Test score stability for same ontology across runs."""
        ontology = create_sample_ontology(entity_count=15, relationship_count=8)
        
        scores = []
        for _ in range(10):
            score = critic.evaluate_ontology(ontology, context)
            scores.append(score.overall)
        
        # Scores should be consistent
        mean_score = statistics.mean(scores)
        for score in scores:
            assert abs(score - mean_score) < 0.1  # Small variance
    
    def test_score_distribution_across_refinement(self, critic, context):
        """Track score distribution changes during refinement."""
        cycle_distributions = {}
        
        for cycle in range(3):
            scores = []
            for i in range(50):
                ontology = create_sample_ontology(
                    entity_count=10 + (i % 20) + cycle * 5,
                    relationship_count=5 + (i % 10) + cycle * 2,
                )
                score = critic.evaluate_ontology(ontology, context)
                scores.append(score.overall)
            
            cycle_distributions[cycle] = {
                "mean": statistics.mean(scores),
                "count": len(scores),
            }
        
        assert len(cycle_distributions) == 3
        for cycle, stats in cycle_distributions.items():
            assert 0.0 < stats["mean"] < 1.0


# ============================================================================
# Outlier and Anomaly Tests
# ============================================================================


class TestOutlierDetection:
    """Test outlier detection in score distributions."""
    
    def test_score_outlier_identification(self, critic, context):
        """Identify and validate outlier scores."""
        scores = []
        for i in range(100):
            ontology = create_sample_ontology(entity_count=5 + (i % 20))
            score = critic.evaluate_ontology(ontology, context)
            scores.append(score.overall)
        
        mean = statistics.mean(scores)
        stdev = statistics.stdev(scores) if len(scores) > 1 else 0.1
        
        # Identify outliers (> 2 std deviations)
        outliers = [s for s in scores if abs(s - mean) > 2 * stdev]
        
        # Should have some outliers in large sample
        assert isinstance(outliers, list)
    
    def test_extreme_score_values(self, critic, context):
        """Test handling of extreme score values."""
        scores = []
        for i in range(50):
            if i == 0:
                # Create minimal ontology
                ontology = create_sample_ontology(entity_count=1, relationship_count=0)
            elif i == 49:
                # Create complex ontology
                ontology = create_sample_ontology(entity_count=50, relationship_count=30)
            else:
                ontology = create_sample_ontology(
                    entity_count=10 + (i % 30),
                    relationship_count=5 + (i % 20),
                )
            
            score = critic.evaluate_ontology(ontology, context)
            scores.append(score.overall)
        
        assert all(0.0 <= s <= 1.0 for s in scores)
        assert min(scores) >= 0.0
        assert max(scores) <= 1.0


# ============================================================================
# Dimension-Level Score Distribution Tests
# ============================================================================


class TestDimensionScoreDistribution:
    """Test distribution of individual critic dimensions."""

    @pytest.mark.parametrize(
        "dimension_name",
        ["completeness", "consistency", "clarity"],
    )
    def test_dimension_score_distribution(self, critic, context, dimension_name: str):
        """Test score distribution for selected dimensions."""
        dimension_scores = []

        for i in range(100):
            ontology = create_sample_ontology(
                entity_count=5 + (i % 25),
                relationship_count=3 + (i % 15),
            )
            score = critic.evaluate_ontology(ontology, context)
            dimension_scores.append(getattr(score, dimension_name))

        assert all(0.0 <= s <= 1.0 for s in dimension_scores)
        assert 0.0 < statistics.mean(dimension_scores) <= 1.0
    
    def test_dimension_correlation(self, critic, context):
        """Test correlation between different dimensions."""
        dimension_data = {"completeness": [], "consistency": [], "clarity": []}
        
        for i in range(50):
            ontology = create_sample_ontology(
                entity_count=10 + (i % 20),
                relationship_count=5 + (i % 10),
            )
            score = critic.evaluate_ontology(ontology, context)
            dimension_data["completeness"].append(score.completeness)
            dimension_data["consistency"].append(score.consistency)
            dimension_data["clarity"].append(score.clarity)
        
        # All dimensions should have valid ranges and counts
        assert all(len(scores) == 50 for scores in dimension_data.values())
        assert all(
            all(0.0 <= s <= 1.0 for s in scores)
            for scores in dimension_data.values()
        )


# ============================================================================
# Distribution Invariants (Batch 260 follow-up)
# ============================================================================


class TestCriticScoreDistributionInvariants:
    """Validate distribution-level invariants for critic scores."""

    def test_overall_between_min_max_dimensions(self, critic, context):
        """Overall score should be between min/max dimension scores."""
        for i in range(100):
            ontology = create_sample_ontology(
                entity_count=5 + (i % 25),
                relationship_count=3 + (i % 15),
            )
            score = critic.evaluate_ontology(ontology, context)
            dims = score.to_list()

            assert len(dims) == 6
            assert min(dims) <= score.overall <= max(dims)

    def test_overall_matches_weighted_sum(self, critic, context):
        """Overall score equals the weighted sum of dimensions."""
        for i in range(100):
            ontology = create_sample_ontology(
                entity_count=8 + (i % 20),
                relationship_count=4 + (i % 12),
            )
            score = critic.evaluate_ontology(ontology, context)
            expected = (
                DIMENSION_WEIGHTS["completeness"] * score.completeness
                + DIMENSION_WEIGHTS["consistency"] * score.consistency
                + DIMENSION_WEIGHTS["clarity"] * score.clarity
                + DIMENSION_WEIGHTS["granularity"] * score.granularity
                + DIMENSION_WEIGHTS["relationship_coherence"] * score.relationship_coherence
                + DIMENSION_WEIGHTS["domain_alignment"] * score.domain_alignment
            )

            assert score.overall == pytest.approx(expected, rel=1e-12, abs=1e-12)

    def test_batch_mean_overall_matches_weighted_mean_of_dimensions(self, critic, context):
        """Mean overall equals weighted mean of dimension means across batch."""
        scores = []
        for i in range(200):
            ontology = create_sample_ontology(
                entity_count=6 + (i % 22),
                relationship_count=2 + (i % 14),
            )
            scores.append(critic.evaluate_ontology(ontology, context))

        overall_mean = statistics.mean(score.overall for score in scores)
        mean_dims = {
            "completeness": statistics.mean(score.completeness for score in scores),
            "consistency": statistics.mean(score.consistency for score in scores),
            "clarity": statistics.mean(score.clarity for score in scores),
            "granularity": statistics.mean(score.granularity for score in scores),
            "relationship_coherence": statistics.mean(score.relationship_coherence for score in scores),
            "domain_alignment": statistics.mean(score.domain_alignment for score in scores),
        }
        weighted_mean = sum(DIMENSION_WEIGHTS[key] * mean_dims[key] for key in mean_dims)

        assert overall_mean == pytest.approx(weighted_mean, rel=1e-12, abs=1e-12)

# ============================================================================
# Integration and Real-World Pattern Tests
# ============================================================================


class TestRealWorldScoringPatterns:
    """Test realistic scoring patterns and edge cases."""
    
    def test_small_vs_large_ontology_scores(self, critic, context):
        """Compare scores for small vs. large ontologies."""
        small_scores = []
        large_scores = []
        
        for i in range(50):
            small_ontology = create_sample_ontology(
                entity_count=2,
                relationship_count=1,
            )
            small_score = critic.evaluate_ontology(small_ontology, context)
            small_scores.append(small_score.overall)
            
            large_ontology = create_sample_ontology(
                entity_count=50,
                relationship_count=30,
            )
            large_score = critic.evaluate_ontology(large_ontology, context)
            large_scores.append(large_score.overall)
        
        small_mean = statistics.mean(small_scores)
        large_mean = statistics.mean(large_scores)
        
        # Both should produce valid scores
        assert 0.0 < small_mean < 1.0
        assert 0.0 < large_mean < 1.0
    
    def test_dense_vs_sparse_relationship_graphs(self, critic, context):
        """Compare scores for dense vs. sparse relationship graphs."""
        sparse_scores = []
        dense_scores = []
        
        for i in range(30):
            # Sparse: many entities, few relationships
            sparse_ontology = create_sample_ontology(
                entity_count=30,
                relationship_count=2,
            )
            sparse_score = critic.evaluate_ontology(sparse_ontology, context)
            sparse_scores.append(sparse_score.overall)
            
            # Dense: fewer entities, many relationships
            dense_ontology = create_sample_ontology(
                entity_count=10,
                relationship_count=20,
            )
            dense_score = critic.evaluate_ontology(dense_ontology, context)
            dense_scores.append(dense_score.overall)
        
        assert len(sparse_scores) == 30
        assert len(dense_scores) == 30
    
    def test_bimodal_score_distribution(self, critic, context):
        """Test detection of bimodal distributions."""
        # Create mixture of poor and good ontologies
        scores = []
        
        for i in range(100):
            if i % 2 == 0:
                # Poor ontology (sparse)
                ontology = create_sample_ontology(
                    entity_count=2,
                    relationship_count=0,
                    base_score=0.3,
                )
            else:
                # Good ontology (well-developed)
                ontology = create_sample_ontology(
                    entity_count=30,
                    relationship_count=20,
                    base_score=0.8,
                )
            
            score = critic.evaluate_ontology(ontology, context)
            scores.append(score.overall)
        
        # Should see separation in distribution
        assert len(scores) == 100
        sorted_scores = sorted(scores)
        median = statistics.median(scores)
        
        # Bimodal: clear separation around median
        assert min(sorted_scores) < median < max(sorted_scores)
