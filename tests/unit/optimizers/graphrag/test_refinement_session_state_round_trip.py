"""Round-trip serialization tests for refinement session state snapshots.

Tests ensure MediatorState can be serialized to JSON and deserialized back
without data loss, supporting workflow persistence and recovery scenarios.
"""

from __future__ import annotations

import json
from typing import Any, Dict

import pytest

from ipfs_datasets_py.optimizers.graphrag.ontology_mediator import MediatorState
from ipfs_datasets_py.optimizers.graphrag.ontology_critic import CriticScore


@pytest.fixture
def sample_critic_score() -> CriticScore:
    """Create a sample CriticScore for testing."""
    return CriticScore(
        completeness=0.85,
        consistency=0.90,
        clarity=0.78,
        granularity=0.82,
        relationship_coherence=0.88,
        domain_alignment=0.92,
        strengths=["well_structured", "comprehensive"],
        weaknesses=["some_redundancy"],
        recommendations=["consolidate_entities"],
        metadata={"source": "test", "model": "gpt-4"},
    )


@pytest.fixture
def sample_ontology() -> Dict[str, Any]:
    """Create a sample ontology for testing."""
    return {
        "id": "test_ontology_v1",
        "entities": [
            {"id": "e1", "text": "Alice", "type": "Person", "confidence": 0.95},
            {"id": "e2", "text": "Bob", "type": "Person", "confidence": 0.92},
        ],
        "relationships": [
            {
                "id": "r1",
                "source_id": "e1",
                "target_id": "e2",
                "type": "knows",
                "confidence": 0.88,
            }
        ],
        "metadata": {"domain": "legal", "version": "1.0"},
    }


class TestMediatorStateBasicRoundTrip:
    """Test basic round-trip serialization of empty and minimal state."""

    def test_empty_state_serializes_to_json(self):
        """Empty MediatorState should serialize to valid JSON."""
        state = MediatorState()
        serialized = state.to_json_dict() if hasattr(state, "to_json_dict") else vars(state)
        serialized_str = json.dumps(serialized, default=str)
        assert serialized_str  # Non-empty
        
        # Should parse back
        parsed = json.loads(serialized_str)
        assert "session_id" in parsed or "current_ontology" in parsed

    def test_minimal_state_round_trip(self):
        """Minimal state with just ontology should round-trip."""
        original = MediatorState(current_ontology={"entities": [], "relationships": []})
        
        # Serialize
        data = vars(original).copy()
        serialized_str = json.dumps(data, default=str)
        
        # Deserialize
        parsed_data = json.loads(serialized_str)
        restored = MediatorState(**{k: v for k, v in parsed_data.items() if k in MediatorState.__annotations__})
        
        # Verify key fields
        assert restored.current_ontology == original.current_ontology
        assert restored.session_id == original.session_id


class TestMediatorStateWithHistory:
    """Test round-trip with refinement history."""

    def test_state_with_single_round(self, sample_ontology, sample_critic_score):
        """State with one refinement round should preserve all data."""
        state = MediatorState(current_ontology=sample_ontology)
        state.add_round(sample_ontology, sample_critic_score, "initial_extraction")
        
        # Serialize to JSON-compatible format
        data = {
            "session_id": state.session_id,
            "domain": state.domain,
            "max_rounds": state.max_rounds,
            "target_score": state.target_score,
            "convergence_threshold": state.convergence_threshold,
            "current_ontology": state.current_ontology,
            "refinement_history": state.refinement_history,
            "total_time_ms": state.total_time_ms,
        }
        serialized_str = json.dumps(data, default=str)
        
        # Parse back
        parsed = json.loads(serialized_str)
        
        # Verify fields
        assert len(parsed["refinement_history"]) == 1
        assert parsed["current_ontology"]["id"] == "test_ontology_v1"
        assert parsed["refinement_history"][0]["action"] == "initial_extraction"
        assert parsed["target_score"] == 0.85

    def test_state_with_multiple_rounds(self, sample_ontology, sample_critic_score):
        """State with multiple refinement rounds preserves full history."""
        state = MediatorState(current_ontology=sample_ontology)
        
        # Add multiple rounds
        for i in range(3):
            modified_ontology = sample_ontology.copy()
            modified_ontology["version"] = i + 1
            score = CriticScore(
                completeness=0.80 + (i * 0.02),
                consistency=0.85 + (i * 0.02),
                clarity=0.75 + (i * 0.02),
                granularity=0.80 + (i * 0.01),
                relationship_coherence=0.85 + (i * 0.02),
                domain_alignment=0.90 + (i * 0.01),
                strengths=[f"strength_{i}"],
                weaknesses=[f"weakness_{i}"],
                recommendations=[f"recommendation_{i}"],
                metadata={"round": i},
            )
            state.add_round(modified_ontology, score, f"refinement_{i}")
        
        # Serialize
        data = vars(state).copy()
        serialized_str = json.dumps(data, default=str)
        parsed = json.loads(serialized_str)
        
        # Verify history
        assert len(parsed["refinement_history"]) == 3
        for i, entry in enumerate(parsed["refinement_history"]):
            assert entry["action"] == f"refinement_{i}"
            assert entry["round"] == i + 1

    def test_complex_ontology_preserves_structure(self):
        """Complex ontology structure should be preserved in round-trip."""
        complex_ont = {
            "id": "complex_test",
            "entities": [
                {
                    "id": f"e{i}",
                    "text": f"Entity{i}",
                    "type": "Type" + str(i % 3),
                    "confidence": 0.5 + (i * 0.05),
                    "metadata": {
                        "source": f"doc_{i}",
                        "section": f"section_{i}",
                        "custom": {"nested": True, "value": i},
                    },
                }
                for i in range(10)
            ],
            "relationships": [
                {
                    "id": f"r{i}",
                    "source_id": f"e{i}",
                    "target_id": f"e{(i+1)%10}",
                    "type": ["type_a", "type_b"][i % 2],
                    "confidence": 0.7 + (i * 0.02),
                    "strength": i % 3,
                    "properties": {"key": f"value_{i}", "count": i},
                }
                for i in range(15)
            ],
            "metadata": {
                "domain": "complex_legal",
                "version": "2.5.1",
                "stats": {
                    "entity_count": 10,
                    "relationship_count": 15,
                    "extraction_time_ms": 1234.5,
                },
            },
        }
        
        state = MediatorState(current_ontology=complex_ont)
        
        # Serialize
        data = vars(state).copy()
        serialized_str = json.dumps(data, default=str)
        parsed = json.loads(serialized_str)
        
        # Verify complex structure
        restored_ont = parsed["current_ontology"]
        assert len(restored_ont["entities"]) == 10
        assert len(restored_ont["relationships"]) == 15
        assert restored_ont["metadata"]["stats"]["entity_count"] == 10
        assert restored_ont["entities"][5]["metadata"]["custom"]["value"] == 5


class TestMediatorStateCriticScoreRoundTrip:
    """Test round-trip with CriticScore serialization."""

    def test_critic_scores_serialize_to_dict(self, sample_critic_score):
        """CriticScore should serialize to dict for JSON compatibility."""
        score_dict = sample_critic_score.to_dict()
        
        # Should be JSON-serializable
        serialized_str = json.dumps(score_dict)
        parsed = json.loads(serialized_str)
        
        # Verify all dimensions preserved
        assert parsed["dimensions"]["completeness"] == 0.85
        assert parsed["dimensions"]["consistency"] == 0.90
        assert parsed["dimensions"]["clarity"] == 0.78
        assert parsed["dimensions"]["granularity"] == 0.82
        assert parsed["dimensions"]["relationship_coherence"] == 0.88
        assert parsed["dimensions"]["domain_alignment"] == 0.92

    def test_score_reconstruction_from_dict(self, sample_critic_score):
        """CriticScore should be reconstructable from serialized dict."""
        # Serialize
        score_dict = sample_critic_score.to_dict()
        serialized_str = json.dumps(score_dict)
        parsed = json.loads(serialized_str)
        
        # Reconstruct
        reconstructed = CriticScore.from_dict(parsed)
        
        # Verify all fields
        assert reconstructed.completeness == sample_critic_score.completeness
        assert reconstructed.consistency == sample_critic_score.consistency
        assert reconstructed.clarity == sample_critic_score.clarity
        assert reconstructed.granularity == sample_critic_score.granularity
        assert reconstructed.relationship_coherence == sample_critic_score.relationship_coherence
        assert reconstructed.domain_alignment == sample_critic_score.domain_alignment
        assert reconstructed.strengths == sample_critic_score.strengths
        assert reconstructed.weaknesses == sample_critic_score.weaknesses
        assert reconstructed.recommendations == sample_critic_score.recommendations


class TestMediatorStateEdgeCases:
    """Test edge cases in round-trip serialization."""

    def test_state_with_unicode_characters(self, sample_ontology):
        """State should preserve Unicode characters in text fields."""
        unicode_ont = sample_ontology.copy()
        unicode_ont["entities"] = [
            {"id": "e1", "text": "Alice 爱丽丝", "type": "Person", "confidence": 0.95},
            {"id": "e2", "text": "Bob (Բոբ)", "type": "Person", "confidence": 0.92},
            {"id": "e3", "text": "Смоук", "type": "Organization", "confidence": 0.88},
        ]
        
        state = MediatorState(current_ontology=unicode_ont)
        
        # Serialize with UTF-8 and handle datetime fields
        data = vars(state).copy()
        serialized_str = json.dumps(data, ensure_ascii=False, default=str)
        parsed = json.loads(serialized_str)
        
        # Verify Unicode preserved
        assert parsed["current_ontology"]["entities"][0]["text"] == "Alice 爱丽丝"
        assert parsed["current_ontology"]["entities"][1]["text"] == "Bob (Բոբ)"
        assert parsed["current_ontology"]["entities"][2]["text"] == "Смоук"

    def test_state_with_large_ontology(self):
        """Large ontology should serialize without truncation."""
        large_ont = {
            "id": "large",
            "entities": [
                {
                    "id": f"e{i}",
                    "text": f"Entity{i}",
                    "type": "Type",
                    "confidence": 0.9,
                    "description": "x" * 500,  # 500 char description
                }
                for i in range(100)
            ],
            "relationships": [
                {
                    "id": f"r{i}",
                    "source_id": f"e{i%100}",
                    "target_id": f"e{(i+1)%100}",
                    "type": "related",
                    "confidence": 0.8,
                }
                for i in range(250)
            ],
            "metadata": {"size": "large"},
        }
        
        state = MediatorState(current_ontology=large_ont)
        
        # Serialize
        data = vars(state).copy()
        serialized_str = json.dumps(data, default=str)
        parsed = json.loads(serialized_str)
        
        # Verify size preserved correctly
        assert len(parsed["current_ontology"]["entities"]) == 100
        assert len(parsed["current_ontology"]["relationships"]) == 250
        # Check description wasn't truncated
        assert len(parsed["current_ontology"]["entities"][0]["description"]) == 500

    def test_state_with_special_json_values(self):
        """State should handle special JSON values (null, empty, etc)."""
        special_ont = {
            "id": "special",
            "entities": [],
            "relationships": [],
            "metadata": {
                "nullable_field": None,
                "empty_string": "",
                "zero": 0,
                "false": False,
                "nested_empty": {"inner": None, "list": []},
            },
        }
        
        state = MediatorState(current_ontology=special_ont)
        
        # Serialize with datetime handling
        data = vars(state).copy()
        serialized_str = json.dumps(data, default=str)
        parsed = json.loads(serialized_str)
        
        # Verify special values preserved
        assert parsed["current_ontology"]["metadata"]["nullable_field"] is None
        assert parsed["current_ontology"]["metadata"]["empty_string"] == ""
        assert parsed["current_ontology"]["metadata"]["zero"] == 0
        assert parsed["current_ontology"]["metadata"]["false"] is False


class TestMediatorStateConsistency:
    """Test consistency invariants during round-trip."""

    def test_round_count_preserved(self, sample_ontology, sample_critic_score):
        """Round count should match refinement history length."""
        state = MediatorState(current_ontology=sample_ontology)
        for i in range(5):
            state.add_round(sample_ontology, sample_critic_score, f"action_{i}")
        
        # Serialize
        data = vars(state).copy()
        serialized_str = json.dumps(data, default=str)
        parsed = json.loads(serialized_str)
        
        # Verify consistency
        assert len(parsed["refinement_history"]) == 5

    def test_session_id_preserved(self, sample_ontology):
        """Session ID should be preserved unchanged through round-trip."""
        state = MediatorState(current_ontology=sample_ontology)
        original_id = state.session_id
        
        # Serialize
        data = vars(state).copy()
        serialized_str = json.dumps(data, default=str)
        parsed = json.loads(serialized_str)
        
        # Verify ID preserved
        assert parsed["session_id"] == original_id

    def test_metadata_invariants(self, sample_ontology):
        """Configuration metadata should remain consistent."""
        state = MediatorState(
            current_ontology=sample_ontology,
            max_rounds=15,
            target_score=0.90,
            convergence_threshold=0.005,
        )
        
        # Serialize with datetime handling
        data = vars(state).copy()
        serialized_str = json.dumps(data, default=str)
        parsed = json.loads(serialized_str)
        
        # Verify all config preserved
        assert parsed["max_rounds"] == 15
        assert parsed["target_score"] == 0.90
        assert parsed["convergence_threshold"] == 0.005
        assert parsed["domain"] == "graphrag"


class TestMediatorStateRecoveryScenarios:
    """Test recovery scenarios using serialized state."""

    def test_state_persistence_and_recovery(self, sample_ontology, sample_critic_score):
        """Simulate persist-and-recover workflow."""
        # Create initial state
        original_state = MediatorState(current_ontology=sample_ontology)
        original_state.add_round(sample_ontology, sample_critic_score, "initial")
        
        # Simulate persistence
        checkpoint = {
            "session_id": original_state.session_id,
            "current_ontology": original_state.current_ontology,
            "refinement_history": original_state.refinement_history,
            "critic_scores": [s.to_dict() if hasattr(s, "to_dict") else s for s in original_state.critic_scores],
            "max_rounds": original_state.max_rounds,
            "target_score": original_state.target_score,
        }
        checkpoint_json = json.dumps(checkpoint, default=str)
        
        # Simulate recovery from persistence
        recovered_data = json.loads(checkpoint_json)
        recovered_state = MediatorState(
            session_id=recovered_data["session_id"],
            current_ontology=recovered_data["current_ontology"],
            refinement_history=recovered_data["refinement_history"],
            max_rounds=recovered_data["max_rounds"],
            target_score=recovered_data["target_score"],
        )
        
        # Verify recovery
        assert recovered_state.session_id == original_state.session_id
        assert len(recovered_state.refinement_history) == 1
        assert recovered_state.current_ontology["entities"] == sample_ontology["entities"]

    def test_partial_state_recovery(self, sample_ontology):
        """Recover state even if some fields are missing."""
        data = {
            "session_id": "test_session_123",
            "current_ontology": sample_ontology,
        }
        serialized_str = json.dumps(data)
        parsed = json.loads(serialized_str)
        
        # Should be able to create state with minimal fields
        state = MediatorState(
            session_id=parsed["session_id"],
            current_ontology=parsed["current_ontology"],
        )
        
        assert state.session_id == "test_session_123"
        assert state.current_ontology == sample_ontology
        # Defaults should be applied
        assert state.max_rounds == 10
        assert state.target_score == 0.85
