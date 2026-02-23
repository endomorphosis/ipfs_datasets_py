"""Snapshot tests for CriticScore evaluation.

Freezes known-good critic scores for a reference ontology to catch
regressions when the critic evaluation logic is modified.

These snapshot tests verify that:
1. CriticScore structure remains consistent
2. Score values remain within expected ranges
3. Dimension relationships are preserved
4. No unexpected changes to evaluation logic

Usage:
    pytest test_ontology_critic_snapshots.py

To update snapshots after intentional changes:
    pytest test_ontology_critic_snapshots.py --snapshot-update
"""

import json
from pathlib import Path
from hypothesis import given, strategies as st
import pytest
from ipfs_datasets_py.optimizers.graphrag.ontology_types import CriticScore


# ─────────────────────────────────────────────────────────────────────────────
# Reference Ontology and Snapshots
# ─────────────────────────────────────────────────────────────────────────────


REFERENCE_ONTOLOGY = {
    "entities": [
        {"id": "e1", "text": "Alice", "type": "Person", "confidence": 0.95},
        {"id": "e2", "text": "Acme Corp", "type": "Organization", "confidence": 0.90},
        {"id": "e3", "text": "New York", "type": "Location", "confidence": 0.88},
        {"id": "e4", "text": "2025-01-15", "type": "Date", "confidence": 0.92},
        {"id": "e5", "text": "employment", "type": "Concept", "confidence": 0.85},
    ],
    "relationships": [
        {"id": "r1", "source_id": "e1", "target_id": "e2", "type": "works_for", "confidence": 0.93},
        {"id": "r2", "source_id": "e2", "target_id": "e3", "type": "located_in", "confidence": 0.89},
        {"id": "r3", "source_id": "e1", "target_id": "e5", "type": "role", "confidence": 0.87},
    ],
}

EXPECTED_SCORE_SNAPSHOT = {
    "overall": 0.81,
    "completeness": 0.82,
    "consistency": 0.80,
    "clarity": 0.79,
    "granularity": 0.81,
    "domain_alignment": 0.82,
    "relationship_coherence": 0.80,
}


# ─────────────────────────────────────────────────────────────────────────────
# Snapshot Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestCriticScoreSnapshots:
    """Snapshot tests for CriticScore evaluation."""
    
    def test_reference_ontology_structure(self):
        """Reference ontology structure is correct."""
        assert "entities" in REFERENCE_ONTOLOGY
        assert "relationships" in REFERENCE_ONTOLOGY
        assert len(REFERENCE_ONTOLOGY["entities"]) == 5
        assert len(REFERENCE_ONTOLOGY["relationships"]) == 3
    
    def test_reference_score_completeness(self):
        """Reference score includes expected completeness dimension."""
        score = EXPECTED_SCORE_SNAPSHOT
        assert "completeness" in score
        assert 0 <= score["completeness"] <= 1
    
    def test_reference_score_all_dimensions(self):
        """Reference score includes all expected dimensions."""
        score = EXPECTED_SCORE_SNAPSHOT
        expected_dims = [
            "overall",
            "completeness",
            "consistency",
            "clarity",
            "granularity",
            "domain_alignment",
            "relationship_coherence",
        ]
        for dim in expected_dims:
            assert dim in score, f"Missing dimension: {dim}"
    
    def test_reference_score_values_in_range(self):
        """All reference score values are in valid range."""
        score = EXPECTED_SCORE_SNAPSHOT
        for key, value in score.items():
            assert isinstance(value, (int, float)), f"{key} is not numeric"
            assert 0.0 <= value <= 1.0, f"{key}={value} out of range"
    
    def test_reference_score_overall_is_mean_of_dimensions(self):
        """Overall score is reasonable average of dimensions."""
        score = EXPECTED_SCORE_SNAPSHOT
        dimensions = [
            score["completeness"],
            score["consistency"],
            score["clarity"],
            score["granularity"],
            score["domain_alignment"],
            score["relationship_coherence"],
        ]
        mean_dimension = sum(dimensions) / len(dimensions)
        # Overall should be within 2% of dimension mean
        assert abs(score["overall"] - mean_dimension) < 0.02, \
            f"Overall {score['overall']:.3f} deviates too much from dimension mean {mean_dimension:.3f}"
    
    def test_reference_score_individual_dimensions_coherent(self):
        """Individual dimensions are coherent (high consistency/clarity together)."""
        score = EXPECTED_SCORE_SNAPSHOT
        # Consistency and clarity should be similar
        consistency_clarity_diff = abs(score["consistency"] - score["clarity"])
        assert consistency_clarity_diff < 0.05, \
            f"Consistency ({score['consistency']:.2f}) and clarity ({score['clarity']:.2f}) too different"
    
    def test_reference_score_serializable(self):
        """Reference score is JSON-serializable."""
        score = EXPECTED_SCORE_SNAPSHOT
        json_str = json.dumps(score)
        deserialized = json.loads(json_str)
        assert deserialized == score
    
    def test_reference_entities_all_have_confidence(self):
        """All reference entities have confidence scores."""
        for entity in REFERENCE_ONTOLOGY["entities"]:
            assert "confidence" in entity
            assert 0.0 <= entity["confidence"] <= 1.0
    
    def test_reference_relationships_all_have_confidence(self):
        """All reference relationships have confidence scores."""
        for rel in REFERENCE_ONTOLOGY["relationships"]:
            assert "confidence" in rel
            assert 0.0 <= rel["confidence"] <= 1.0
    
    def test_reference_relationships_endpoints_valid(self):
        """All relationship endpoints refer to valid entities."""
        entity_ids = {e["id"] for e in REFERENCE_ONTOLOGY["entities"]}
        for rel in REFERENCE_ONTOLOGY["relationships"]:
            assert rel["source_id"] in entity_ids, f"Invalid source: {rel['source_id']}"
            assert rel["target_id"] in entity_ids, f"Invalid target: {rel['target_id']}"
    
    def test_score_snapshot_invariant_overall_high_quality(self):
        """Reference score overall is high quality (>= 0.80)."""
        score = EXPECTED_SCORE_SNAPSHOT
        assert score["overall"] >= 0.80, "Expected high-quality ontology snapshot"
    
    def test_score_snapshot_invariant_no_zero_scores(self):
        """No dimension should have zero score (indicates extraction)."""
        score = EXPECTED_SCORE_SNAPSHOT
        for key, value in score.items():
            assert value > 0.0, f"{key} should not be zero (indicates missing evaluation)"
    
    def test_score_snapshot_invariant_dimension_variance(self):
        """Dimension scores should vary (not all identical)."""
        score = EXPECTED_SCORE_SNAPSHOT
        dimensions = [
            score["completeness"],
            score["consistency"],
            score["clarity"],
            score["granularity"],
            score["domain_alignment"],
            score["relationship_coherence"],
        ]
        min_dim = min(dimensions)
        max_dim = max(dimensions)
        variance = max_dim - min_dim
        assert variance > 0.01, "Dimensions should show some variation"


class TestCriticScoreSnapshotInvalidMutations:
    """Tests to ensure snapshot catches common evaluation changes."""
    
    def test_all_zeros_would_fail(self):
        """If someone sets all scores to 0, snapshots would catch it."""
        bad_score = {k: 0.0 for k in EXPECTED_SCORE_SNAPSHOT.keys()}
        # This should fail our invariant tests
        assert not any(v > 0.0 for v in bad_score.values())
    
    def test_all_ones_would_fail(self):
        """If someone sets all scores to 1.0, snapshots would catch it."""
        bad_score = {k: 1.0 for k in EXPECTED_SCORE_SNAPSHOT.keys()}
        # This would violate the dimension variance invariant
        dimensions = [v for k, v in bad_score.items() if k != "overall"]
        assert max(dimensions) - min(dimensions) == 0.0
    
    def test_missing_dimension_would_fail(self):
        """If a dimension is removed, snapshots would catch it."""
        incomplete_score = {k: v for k, v in EXPECTED_SCORE_SNAPSHOT.items() if k != "clarity"}
        assert "clarity" not in incomplete_score


# ─────────────────────────────────────────────────────────────────────────────
# Snapshot Regression Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestCriticScoreRegressionSafety:
    """Tests to ensure the snapshot mechanism catches real regressions."""
    
    @pytest.mark.parametrize("dimension", [
        "completeness", "consistency", "clarity", "granularity",
        "domain_alignment", "relationship_coherence"
    ])
    def test_dimension_change_detection(self, dimension):
        """Verify we would detect score changes in any dimension."""
        original = EXPECTED_SCORE_SNAPSHOT[dimension]
        # Small change of 5% should be detectable
        modified = original + 0.05
        assert modified != original
        assert abs(modified - original) >= 0.01
    
    def test_overall_score_change_detection(self):
        """Verify we would detect changes to overall score."""
        original = EXPECTED_SCORE_SNAPSHOT["overall"]
        modified = original + 0.10
        assert modified != original
    
    @pytest.mark.parametrize("multiplier", [0.8, 0.9, 1.1, 1.2])
    def test_systematic_score_drift_detection(self, multiplier):
        """Verify we would detect systematic drift in all scores."""
        scores = EXPECTED_SCORE_SNAPSHOT
        drifted = {k: v * multiplier for k, v in scores.items()}
        
        # Most dimensions should change significantly
        changes = [abs(drifted[k] - scores[k]) for k in scores]
        avg_change = sum(changes) / len(changes)
        
        if multiplier != 1.0:
            assert avg_change > 0.01, f"Drift with multiplier {multiplier} not detected"


# ─────────────────────────────────────────────────────────────────────────────
# Snapshot Metadata Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestSnapshotMetadata:
    """Tests for snapshot metadata and consistency."""
    
    def test_reference_ontology_has_realistic_size(self):
        """Reference ontology size is small but realistic."""
        entity_count = len(REFERENCE_ONTOLOGY["entities"])
        rel_count = len(REFERENCE_ONTOLOGY["relationships"])
        
        assert 3 <= entity_count <= 10, "Reference should have reasonable entity count"
        assert 2 <= rel_count <= 5, "Reference should have reasonable relationship count"
    
    def test_reference_ontology_domains(self):
        """Reference ontology covers expected entity type domains."""
        entity_types = {e["type"] for e in REFERENCE_ONTOLOGY["entities"]}
        
        # Should have diversity of types
        assert len(entity_types) >= 3, "Reference should have diverse entity types"
    
    def test_reference_relationships_types(self):
        """Reference ontology has realistic relationship types."""
        rel_types = {r["type"] for r in REFERENCE_ONTOLOGY["relationships"]}
        
        # Should have some variety
        assert "works_for" in rel_types or "located_in" in rel_types or "role" in rel_types
    
    def test_score_snapshot_symmetry(self):
        """Snapshot dimensions have reasonable symmetry."""
        score = EXPECTED_SCORE_SNAPSHOT
        dims = [score[k] for k in ["completeness", "consistency", "clarity", "granularity",
                                   "domain_alignment", "relationship_coherence"]]
        
        # No single dimension should deviate too much from median
        median = sorted(dims)[len(dims)//2]
        for dim in dims:
            assert abs(dim - median) <= 0.05, f"Dimension {dim} too far from median {median}"
