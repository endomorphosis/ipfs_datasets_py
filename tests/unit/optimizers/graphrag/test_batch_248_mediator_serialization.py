"""Batch 248: MediatorState Serialization Round-Trip Tests.

Tests comprehensive serialization and deserialization of MediatorState objects,
ensuring complete state preservation across to_dict() / from_dict() cycles.

Test Categories:
- Basic round-trip serialization (to_dict → from_dict)
- Multiple rounds with full history
- CriticScore preservation in serialization
- Refinement history integrity
- Metadata and convergence state
- Timestamp preservation
- Edge cases (empty, single round, max rounds)
- JSON serialization compatibility
- Integration with actual refinement cycles
"""

import json
import pytest
from datetime import datetime
from typing import Dict, Any

from ipfs_datasets_py.optimizers.graphrag.ontology_mediator import (
    OntologyMediator,
    MediatorState,
)
from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
    OntologyGenerator,
    OntologyGenerationContext,
    DataType,
    ExtractionStrategy,
)
from ipfs_datasets_py.optimizers.graphrag.ontology_critic import (
    OntologyCritic,
    CriticScore,
)


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def simple_ontology():
    """Create a simple ontology for testing."""
    return {
        "entities": [
            {"id": "e1", "text": "Alice", "type": "Person", "confidence": 0.9},
            {"id": "e2", "text": "Bob", "type": "Person", "confidence": 0.8},
        ],
        "relationships": [
            {"id": "r1", "source_id": "e1", "target_id": "e2", "type": "knows", "confidence": 0.7}
        ],
        "metadata": {"source": "test"},
        "domain": "general",
    }


@pytest.fixture
def simple_critic_score():
    """Create a simple CriticScore for testing."""
    return CriticScore(
        completeness=0.8,
        connectivity=0.7,
        consistency=0.9,
        overall=0.8,
        feedback=["Good structure"],
        metadata={"test": True}
    )


@pytest.fixture
def empty_state():
    """Create an empty MediatorState."""
    return MediatorState(
        current_ontology={},
        max_rounds=5,
        target_score=0.85,
    )


@pytest.fixture
def populated_state(simple_ontology, simple_critic_score):
    """Create a MediatorState with multiple rounds."""
    state = MediatorState(
        current_ontology=simple_ontology,
        max_rounds=5,
        target_score=0.85,
    )
    
    # Add multiple rounds
    for i in range(3):
        modified_ontology = simple_ontology.copy()
        modified_ontology["metadata"] = {"round": i}
        
        score = CriticScore(
            completeness=0.7 + i * 0.05,
            connectivity=0.6 + i * 0.05,
            consistency=0.8 + i * 0.05,
            overall=0.7 + i * 0.05,
            feedback=[f"Round {i} feedback"],
        )
        
        state.add_round(modified_ontology, score, f"refinement_action_{i}")
    
    return state


# ============================================================================
# Basic Round-Trip Serialization
# ============================================================================

class TestBasicRoundTripSerialization:
    """Test basic to_dict() / from_dict() round-trip preservation."""
    
    def test_empty_state_round_trip(self, empty_state):
        """Empty state survives serialization round-trip."""
        serialized = empty_state.to_dict()
        deserialized = MediatorState.from_dict(serialized)
        
        assert deserialized.session_id == empty_state.session_id
        assert deserialized.max_rounds == empty_state.max_rounds
        assert deserialized.target_score == empty_state.target_score
        assert deserialized.current_ontology == empty_state.current_ontology
        assert len(deserialized.refinement_history) == 0
        assert len(deserialized.critic_scores) == 0
    
    def test_single_round_state_round_trip(self, simple_ontology, simple_critic_score):
        """State with single round preserves all data."""
        state = MediatorState(current_ontology=simple_ontology)
        state.add_round(simple_ontology, simple_critic_score, "initial_generation")
        
        serialized = state.to_dict()
        deserialized = MediatorState.from_dict(serialized)
        
        assert len(deserialized.refinement_history) == 1
        assert len(deserialized.critic_scores) == 1
        assert deserialized.refinement_history[0]["action"] == "initial_generation"
        assert deserialized.critic_scores[0].overall == simple_critic_score.overall
    
    def test_multiple_rounds_state_round_trip(self, populated_state):
        """State with multiple rounds preserves complete history."""
        serialized = populated_state.to_dict()
        deserialized = MediatorState.from_dict(serialized)
        
        assert len(deserialized.refinement_history) == len(populated_state.refinement_history)
        assert len(deserialized.critic_scores) == len(populated_state.critic_scores)
        
        for i in range(len(populated_state.refinement_history)):
            assert deserialized.refinement_history[i]["round"] == populated_state.refinement_history[i]["round"]
            assert deserialized.refinement_history[i]["action"] == populated_state.refinement_history[i]["action"]
    
    def test_to_dict_returns_dict(self, populated_state):
        """to_dict() returns a dictionary."""
        serialized = populated_state.to_dict()
        assert isinstance(serialized, dict)
    
    def test_from_dict_returns_mediator_state(self, populated_state):
        """from_dict() returns MediatorState instance."""
        serialized = populated_state.to_dict()
        deserialized = MediatorState.from_dict(serialized)
        assert isinstance(deserialized, MediatorState)
    
    def test_session_id_preserved(self, populated_state):
        """Session ID is preserved across serialization."""
        serialized = populated_state.to_dict()
        deserialized = MediatorState.from_dict(serialized)
        assert deserialized.session_id == populated_state.session_id


# ============================================================================
# CriticScore Serialization
# ============================================================================

class TestCriticScoreSerialization:
    """Test CriticScore preservation in MediatorState serialization."""
    
    def test_critic_score_fields_preserved(self, simple_ontology):
        """All CriticScore fields are preserved."""
        state = MediatorState(current_ontology=simple_ontology)
        score = CriticScore(
            completeness=0.85,
            connectivity=0.75,
            consistency=0.95,
            overall=0.85,
            feedback=["test feedback 1", "test feedback 2"],
            metadata={"key": "value"}
        )
        state.add_round(simple_ontology, score, "test_action")
        
        serialized = state.to_dict()
        deserialized = MediatorState.from_dict(serialized)
        
        restored_score = deserialized.critic_scores[0]
        assert restored_score.completeness == 0.85
        assert restored_score.connectivity == 0.75
        assert restored_score.consistency == 0.95
        assert restored_score.overall == 0.85
        assert len(restored_score.feedback) == 2
        assert restored_score.metadata["key"] == "value"
    
    def test_critic_score_feedback_list_preserved(self, simple_ontology):
        """CriticScore feedback list is preserved."""
        state = MediatorState(current_ontology=simple_ontology)
        score = CriticScore(
            completeness=0.8, connectivity=0.7, consistency=0.9, overall=0.8,
            feedback=["feedback1", "feedback2", "feedback3"]
        )
        state.add_round(simple_ontology, score, "action")
        
        serialized = state.to_dict()
        deserialized = MediatorState.from_dict(serialized)
        
        assert deserialized.critic_scores[0].feedback == ["feedback1", "feedback2", "feedback3"]
    
    def test_multiple_critic_scores_preserved(self, populated_state):
        """Multiple CriticScore objects are preserved in order."""
        serialized = populated_state.to_dict()
        deserialized = MediatorState.from_dict(serialized)
        
        assert len(deserialized.critic_scores) == len(populated_state.critic_scores)
        
        for i in range(len(populated_state.critic_scores)):
            original_score = populated_state.critic_scores[i]
            restored_score = deserialized.critic_scores[i]
            assert restored_score.overall == original_score.overall
            assert restored_score.completeness == original_score.completeness


# ============================================================================
# Refinement History Preservation
# ============================================================================

class TestRefinementHistoryPreservation:
    """Test refinement history integrity across serialization."""
    
    def test_refinement_history_structure(self, populated_state):
        """Refinement history maintains structure."""
        serialized = populated_state.to_dict()
        deserialized = MediatorState.from_dict(serialized)
        
        for history_item in deserialized.refinement_history:
            assert "round" in history_item
            assert "ontology" in history_item
            assert "score" in history_item
            assert "action" in history_item
    
    def test_refinement_actions_preserved(self, populated_state):
        """Refinement action descriptions are preserved."""
        serialized = populated_state.to_dict()
        deserialized = MediatorState.from_dict(serialized)
        
        for i, history_item in enumerate(deserialized.refinement_history):
            expected_action = f"refinement_action_{i}"
            assert history_item["action"] == expected_action
    
    def test_ontology_snapshots_in_history(self, populated_state):
        """Ontology snapshots are preserved in refinement history."""
        serialized = populated_state.to_dict()
        deserialized = MediatorState.from_dict(serialized)
        
        for history_item in deserialized.refinement_history:
            ontology = history_item["ontology"]
            assert isinstance(ontology, dict)
            assert "entities" in ontology or "metadata" in ontology
    
    def test_score_snapshots_in_history(self, populated_state):
        """Score snapshots are preserved in refinement history."""
        serialized = populated_state.to_dict()
        deserialized = MediatorState.from_dict(serialized)
        
        for history_item in deserialized.refinement_history:
            score = history_item["score"]
            assert isinstance(score, dict)
            assert "overall" in score


# ============================================================================
# Metadata and Convergence State
# ============================================================================

class TestMetadataAndConvergence:
    """Test metadata and convergence state preservation."""
    
    def test_convergence_flag_preserved(self, simple_ontology, simple_critic_score):
        """Convergence flag is preserved."""
        state = MediatorState(current_ontology=simple_ontology)
        state.add_round(simple_ontology, simple_critic_score, "action")
        state.converged = True
        
        serialized = state.to_dict()
        deserialized = MediatorState.from_dict(serialized)
        
        assert deserialized.converged is True
    
    def test_convergence_threshold_preserved(self, empty_state):
        """Convergence threshold is preserved."""
        empty_state.convergence_threshold = 0.92
        
        serialized = empty_state.to_dict()
        deserialized = MediatorState.from_dict(serialized)
        
        assert deserialized.convergence_threshold == 0.92
    
    def test_metadata_dict_preserved(self, simple_ontology, simple_critic_score):
        """Metadata dictionary is preserved."""
        state = MediatorState(current_ontology=simple_ontology)
        state.add_round(simple_ontology, simple_critic_score, "action")
        state.metadata["custom_key"] = "custom_value"
        state.metadata["nested"] = {"inner": "data"}
        
        serialized = state.to_dict()
        deserialized = MediatorState.from_dict(serialized)
        
        assert deserialized.metadata["custom_key"] == "custom_value"
        assert deserialized.metadata["nested"]["inner"] == "data"
    
    def test_total_time_ms_preserved(self, populated_state):
        """Total time metric is preserved."""
        populated_state.total_time_ms = 1234.5
        
        serialized = populated_state.to_dict()
        deserialized = MediatorState.from_dict(serialized)
        
        assert deserialized.total_time_ms == 1234.5
    
    def test_max_rounds_and_target_score_preserved(self, empty_state):
        """Max rounds and target score are preserved."""
        empty_state.max_rounds = 15
        empty_state.target_score = 0.95
        
        serialized = empty_state.to_dict()
        deserialized = MediatorState.from_dict(serialized)
        
        assert deserialized.max_rounds == 15
        assert deserialized.target_score == 0.95


# ============================================================================
# Timestamp Preservation
# ============================================================================

class TestTimestampPreservation:
    """Test timestamp field preservation."""
    
    def test_started_at_timestamp_preserved(self, empty_state):
        """started_at timestamp is preserved."""
        test_time = datetime(2026, 2, 23, 12, 30, 45)
        empty_state.started_at = test_time
        
        serialized = empty_state.to_dict()
        deserialized = MediatorState.from_dict(serialized)
        
        # Timestamps may be serialized as ISO strings
        assert deserialized.started_at is not None
        if isinstance(deserialized.started_at, datetime):
            assert deserialized.started_at.year == 2026
            assert deserialized.started_at.month == 2
            assert deserialized.started_at.day == 23
    
    def test_finished_at_timestamp_preserved(self, populated_state):
        """finished_at timestamp is preserved."""
        test_time = datetime(2026, 2, 23, 12, 35, 50)
        populated_state.finished_at = test_time
        
        serialized = populated_state.to_dict()
        deserialized = MediatorState.from_dict(serialized)
        
        assert deserialized.finished_at is not None
        if isinstance(deserialized.finished_at, datetime):
            assert deserialized.finished_at.year == 2026


# ============================================================================
# JSON Serialization Compatibility
# ============================================================================

class TestJSONSerializationCompatibility:
    """Test JSON serialization compatibility."""
    
    def test_to_dict_json_serializable(self, populated_state):
        """to_dict() output is JSON-serializable."""
        serialized = populated_state.to_dict()
        
        # Should not raise exception
        json_str = json.dumps(serialized)
        assert isinstance(json_str, str)
        assert len(json_str) > 0
    
    def test_json_round_trip(self, populated_state):
        """State survives JSON serialization round-trip."""
        serialized = populated_state.to_dict()
        json_str = json.dumps(serialized)
        json_loaded = json.loads(json_str)
        deserialized = MediatorState.from_dict(json_loaded)
        
        assert len(deserialized.refinement_history) == len(populated_state.refinement_history)
        assert len(deserialized.critic_scores) == len(populated_state.critic_scores)
    
    def test_json_no_numpy_types(self, simple_ontology, simple_critic_score):
        """JSON output contains no numpy types."""
        state = MediatorState(current_ontology=simple_ontology)
        state.add_round(simple_ontology, simple_critic_score, "action")
        
        serialized = state.to_dict()
        json_str = json.dumps(serialized)
        
        # Should not contain numpy type indicators
        assert "numpy" not in json_str.lower()
        assert "np.float" not in json_str


# ============================================================================
# Edge Cases
# ============================================================================

class TestEdgeCases:
    """Test edge cases and boundary conditions."""
    
    def test_empty_refinement_history(self, empty_state):
        """State with empty refinement history serializes correctly."""
        serialized = empty_state.to_dict()
        deserialized = MediatorState.from_dict(serialized)
        
        assert len(deserialized.refinement_history) == 0
        assert len(deserialized.critic_scores) == 0
    
    def test_state_at_max_rounds(self, simple_ontology, simple_critic_score):
        """State at maximum rounds serializes correctly."""
        state = MediatorState(current_ontology=simple_ontology, max_rounds=3)
        
        for i in range(3):
            state.add_round(simple_ontology, simple_critic_score, f"round_{i}")
        
        serialized = state.to_dict()
        deserialized = MediatorState.from_dict(serialized)
        
        assert len(deserialized.refinement_history) == 3
        assert deserialized.max_rounds == 3
    
    def test_empty_current_ontology(self):
        """State with empty current_ontology serializes correctly."""
        state = MediatorState(current_ontology={})
        
        serialized = state.to_dict()
        deserialized = MediatorState.from_dict(serialized)
        
        assert deserialized.current_ontology == {}
    
    def test_missing_optional_fields_in_dict(self):
        """from_dict() handles missing optional fields gracefully."""
        minimal_dict = {
            "session_id": "test_session",
            "domain": "graphrag",
            "max_rounds": 5,
        }
        
        # Should not raise exception
        state = MediatorState.from_dict(minimal_dict)
        assert state.session_id == "test_session"
        assert state.max_rounds == 5


# ============================================================================
# Integration Tests
# ============================================================================

class TestIntegrationWithRefinementCycle:
    """Test serialization in actual refinement cycle context."""
    
    @pytest.fixture
    def mediator(self):
        """Create mediator for integration tests."""
        generator = OntologyGenerator(use_ipfs_accelerate=False)
        critic = OntologyCritic(use_llm=False)
        return OntologyMediator(generator=generator, critic=critic, max_rounds=2)
    
    @pytest.fixture
    def context(self):
        """Create generation context."""
        return OntologyGenerationContext(
            data_source="test",
            data_type=DataType.TEXT,
            domain="general",
            extraction_strategy=ExtractionStrategy.RULE_BASED,
        )
    
    def test_refinement_cycle_state_serialization(self, mediator, context):
        """State from run_refinement_cycle() can be serialized."""
        text = "Alice manages Bob. Bob works with Charlie."
        
        state = mediator.run_refinement_cycle(text, context)
        
        serialized = state.to_dict()
        deserialized = MediatorState.from_dict(serialized)
        
        assert len(deserialized.refinement_history) > 0
        assert len(deserialized.critic_scores) > 0
        assert deserialized.total_time_ms > 0
    
    def test_agentic_refinement_cycle_serialization(self, mediator, context):
        """State from run_agentic_refinement_cycle() can be serialized."""
        text = "Contract between Party A and Party B."
        
        state = mediator.run_agentic_refinement_cycle(text, context, max_rounds=1)
        
        serialized = state.to_dict()
        deserialized = MediatorState.from_dict(serialized)
        
        assert isinstance(deserialized, MediatorState)
        assert len(deserialized.refinement_history) > 0
    
    def test_score_trend_after_deserialization(self, populated_state):
        """get_score_trend() works after deserialization."""
        populated_state.converged = False
        
        serialized = populated_state.to_dict()
        deserialized = MediatorState.from_dict(serialized)
        
        trend = deserialized.get_score_trend()
        assert trend in ["improving", "stable", "degrading", "insufficient_data"]
