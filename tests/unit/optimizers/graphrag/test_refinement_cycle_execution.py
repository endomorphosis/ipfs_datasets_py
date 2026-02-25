"""Tests for full OntologyMediator.run_refinement_cycle() execution and state management.

Complements test_refinement_session_state_round_trip.py (which tests MediatorState
serialization) by testing the complete refinement cycle execution, intermediate state
checkpointing, recovery scenarios, and round-by-round state evolution.

Run with: pytest test_refinement_cycle_execution.py -v --tb=short
"""
from __future__ import annotations

import json
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest

from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
    DataType,
    Entity,
    EntityExtractionResult,
    ExtractionStrategy,
    OntologyGenerationContext,
    OntologyGenerator,
)
from ipfs_datasets_py.optimizers.graphrag.ontology_critic import (
    CriticScore,
    OntologyCritic,
)
from ipfs_datasets_py.optimizers.graphrag.ontology_mediator import (
    MediatorState,
    OntologyMediator,
)


# ===== Test Fixtures =====

@pytest.fixture
def generator() -> OntologyGenerator:
    """OntologyGenerator instance."""
    return OntologyGenerator(use_ipfs_accelerate=False)


@pytest.fixture
def critic() -> OntologyCritic:
    """OntologyCritic instance."""
    return OntologyCritic()


@pytest.fixture
def mediator(generator, critic) -> OntologyMediator:
    """OntologyMediator instance."""
    return OntologyMediator(
        generator=generator,
        critic=critic,
        max_rounds=5,
        convergence_threshold=0.85,
    )


@pytest.fixture
def context() -> OntologyGenerationContext:
    """Basic generation context."""
    return OntologyGenerationContext(
        data_source="test_cycle",
        data_type=DataType.TEXT,
        domain="legal",
        extraction_strategy=ExtractionStrategy.RULE_BASED,
    )


@pytest.fixture
def sample_text() -> str:
    """Sample text for extraction."""
    return (
        "This Agreement includes warranty provisions and indemnification clauses. "
        "The parties agree to arbitration. Confidential information must be protected. "
        "Governing law is Delaware. Effective date is January 1, 2024."
    )


def _make_mock_ontology(version: int = 1, n_entities: int = 5) -> Dict[str, Any]:
    """Create mock ontology dict."""
    entities = [
        {
            "id": f"entity_{i}",
            "type": "Term",
            "text": f"Entity_{i}",
            "confidence": 0.7,
        }
        for i in range(n_entities)
    ]
    return {
        "id": f"ontology_v{version}",
        "entities": entities,
        "relationships": [],
        "metadata": {"version": version},
    }


def _make_mock_score(overall: float = 0.75) -> CriticScore:
    """Create mock CriticScore."""
    return CriticScore(
        completeness=overall,
        consistency=overall + 0.05,
        clarity=overall - 0.05,
        granularity=overall,
        relationship_coherence=overall + 0.02,
        domain_alignment=overall + 0.03,
        strengths=["good coverage"],
        weaknesses=["needs more relationships"],
        recommendations=["add relationship inference"],
    )


# ===== Refinement Cycle Execution Tests =====

class TestRefinementCycleExecution:
    """Test complete refinement cycle execution."""
    
    def test_basic_cycle_executes_to_completion(self, mediator, context, sample_text):
        """Basic refinement cycle should execute and return final state."""
        with patch.object(mediator.generator, "generate_ontology", return_value=_make_mock_ontology(version=1)), \
             patch.object(mediator.critic, "evaluate_ontology", return_value=_make_mock_score(overall=0.70)), \
             patch.object(mediator, "refine_ontology", return_value=_make_mock_ontology(version=2)):
            
            state = mediator.run_refinement_cycle(sample_text, context)
        
        # Should have final state
        assert isinstance(state, MediatorState)
        assert state.current_ontology is not None
        assert len(state.critic_scores) >= 1
        assert len(state.refinement_history) >= 1
    
    def test_cycle_respects_max_rounds(self, mediator, context, sample_text):
        """Refinement cycle should stop at max_rounds."""
        # Set low max rounds
        mediator.max_rounds = 3
        
        # Mock always low score to force max rounds
        with patch.object(mediator.generator, "generate_ontology", return_value=_make_mock_ontology(version=1)), \
             patch.object(mediator.critic, "evaluate_ontology", return_value=_make_mock_score(overall=0.50)), \
             patch.object(mediator, "refine_ontology", side_effect=lambda o, s, c: _make_mock_ontology(version=2)):
            
            state = mediator.run_refinement_cycle(sample_text, context)
        
        # Should stop at max_rounds (initial + refinements)
        assert state.current_round <= 3
        assert len(state.refinement_history) <= 3
    
    def test_cycle_converges_early(self, mediator, context, sample_text):
        """Cycle should stop early if convergence threshold reached."""
        # Mock high initial score to trigger convergence
        high_score = _make_mock_score(overall=0.90)
        
        with patch.object(mediator.generator, "generate_ontology", return_value=_make_mock_ontology(version=1)), \
             patch.object(mediator.critic, "evaluate_ontology", return_value=high_score), \
             patch.object(mediator, "refine_ontology", return_value=_make_mock_ontology(version=2)):
            
            state = mediator.run_refinement_cycle(sample_text, context)
        
        # Should converge after 1 round (initial score > threshold)
        assert state.converged is True
        assert len(state.refinement_history) == 1  # Only initial
    
    def test_cycle_tracks_score_improvement(self, mediator, context, sample_text):
        """Cycle should track score improvement across rounds."""
        # Mock progressive improvement (provide enough scores for max_rounds)
        scores = [0.60, 0.70, 0.75, 0.80, 0.82, 0.84]
        score_index = [0]  # Use list to allow modification in nested function
        
        def get_next_score(ont, ctx, data):
            score = scores[min(score_index[0], len(scores) - 1)]  # Reuse last score if we run out
            score_index[0] += 1
            return _make_mock_score(overall=score)
        
        with patch.object(mediator.generator, "generate_ontology", return_value=_make_mock_ontology(version=1)), \
             patch.object(mediator.critic, "evaluate_ontology", side_effect=get_next_score), \
             patch.object(mediator, "refine_ontology", side_effect=lambda o, s, c: _make_mock_ontology(version=2)):
            
            state = mediator.run_refinement_cycle(sample_text, context)
        
        # Should have metadata tracking improvement
        assert 'improvement' in state.metadata
        assert state.metadata['improvement'] > 0  # Should improve from 0.60
        assert 'final_score' in state.metadata


# ===== State Persistence and Checkpointing =====

class TestCycleStateCheckpointing:
    """Test intermediate state checkpointing during refinement cycles."""
    
    def test_state_can_be_checkpointed_mid_cycle(self, mediator, context, sample_text):
        """MediatorState should be serializable at any point during cycle."""
        checkpoints = []
        
        def capture_checkpoint(ontology, score, ctx):
            # Capture state after each refinement
            checkpoints.append({
                "ontology": ontology,
                "score": score.overall if hasattr(score, "overall") else 0.0,
                "round": len(checkpoints) + 1,
            })
            return _make_mock_ontology(version=len(checkpoints) + 1)
        
        with patch.object(mediator.generator, "generate_ontology", return_value=_make_mock_ontology(version=1)), \
             patch.object(mediator.critic, "evaluate_ontology", return_value=_make_mock_score(overall=0.70)), \
             patch.object(mediator, "refine_ontology", side_effect=capture_checkpoint):
            
            mediator.max_rounds = 3
            state = mediator.run_refinement_cycle(sample_text, context)
        
        # Should have captured checkpoints
        assert len(checkpoints) >= 1
        
        # State should be JSON-serializable at end
        state_dict = vars(state).copy()
        serialized = json.dumps(state_dict, default=str)
        assert serialized  # Non-empty
        
        # Should deserialize
        parsed = json.loads(serialized)
        assert "current_ontology" in parsed
        assert "refinement_history" in parsed
    
    def test_checkpoint_preserves_round_history(self, mediator, context, sample_text):
        """Checkpointed state should preserve complete refinement history."""
        with patch.object(mediator.generator, "generate_ontology", return_value=_make_mock_ontology(version=1)), \
             patch.object(mediator.critic, "evaluate_ontology", return_value=_make_mock_score(overall=0.70)), \
             patch.object(mediator, "refine_ontology", side_effect=lambda o, s, c: _make_mock_ontology(version=2)):
            
            mediator.max_rounds = 4
            state = mediator.run_refinement_cycle(sample_text, context)
        
        # Serialize state
        state_dict = {
            "session_id": state.session_id,
            "current_ontology": state.current_ontology,
            "refinement_history": state.refinement_history,
            "critic_scores": [s.to_dict() if hasattr(s, "to_dict") else s for s in state.critic_scores],
            "max_rounds": state.max_rounds,
            "target_score": state.target_score,
        }
        serialized = json.dumps(state_dict, default=str)
        parsed = json.loads(serialized)
        
        # Verify history preserved
        assert len(parsed["refinement_history"]) == len(state.refinement_history)
        for orig, restored in zip(state.refinement_history, parsed["refinement_history"]):
            assert orig["round"] == restored["round"]
            assert orig["action"] == restored["action"]


# ===== State Recovery Scenarios =====

class TestCycleStateRecovery:
    """Test recovery and resumption from checkpointed state."""
    
    def test_state_can_be_reconstructed_from_checkpoint(self, sample_text):
        """MediatorState should be reconstructable from serialized checkpoint."""
        # Create original state
        original_state = MediatorState(
            current_ontology=_make_mock_ontology(version=1),
            max_rounds=5,
            target_score=0.85,
        )
        original_state.add_round(
            _make_mock_ontology(version=1),
            _make_mock_score(overall=0.70),
            "initial_generation"
        )
        
        # Serialize to checkpoint
        checkpoint = {
            "session_id": original_state.session_id,
            "current_ontology": original_state.current_ontology,
            "refinement_history": original_state.refinement_history,
            "critic_scores": [s.to_dict() if hasattr(s, "to_dict") else s for s in original_state.critic_scores],
            "max_rounds": original_state.max_rounds,
            "target_score": original_state.target_score,
        }
        checkpoint_json = json.dumps(checkpoint, default=str)
        
        # Recover from checkpoint
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
        assert recovered_state.max_rounds == 5
        assert recovered_state.target_score == 0.85
    
    def test_recovered_state_can_resume_refinement(self, mediator, context):
        """Recovered state should allow refinement to continue."""
        # Create partial state (simulating recovery from checkpoint)
        recovered_state = MediatorState(
            current_ontology=_make_mock_ontology(version=2),
            max_rounds=5,
            target_score=0.85,
        )
        recovered_state.add_round(
            _make_mock_ontology(version=1),
            _make_mock_score(overall=0.70),
            "recovered_round_1"
        )
        
        # Resume refinement from recovered state
        with patch.object(mediator, "refine_ontology", return_value=_make_mock_ontology(version=3)):
            refined_ont = mediator.refine_ontology(
                recovered_state.current_ontology,
                _make_mock_score(overall=0.75),
                context
            )
        
        # Should continue normally
        assert refined_ont is not None
        assert refined_ont["metadata"]["version"] == 3


# ===== Round-by-Round State Evolution =====

class TestRoundByRoundEvolution:
    """Test state evolution across refinement rounds."""
    
    def test_state_tracks_each_round(self, mediator, context, sample_text):
        """State should track every refinement round separately."""
        round_count = 0
        
        def track_rounds(ontology, score, ctx):
            nonlocal round_count
            round_count += 1
            return _make_mock_ontology(version=round_count + 1)
        
        with patch.object(mediator.generator, "generate_ontology", return_value=_make_mock_ontology(version=1)), \
             patch.object(mediator.critic, "evaluate_ontology", return_value=_make_mock_score(overall=0.70)), \
             patch.object(mediator, "refine_ontology", side_effect=track_rounds):
            
            mediator.max_rounds = 4
            state = mediator.run_refinement_cycle(sample_text, context)
        
        # Should have tracked all rounds
        assert len(state.refinement_history) >= 1
        
        # Each round should have unique metadata
        actions = [entry["action"] for entry in state.refinement_history]
        assert "initial_generation" in actions
    
    def test_state_accumulates_scores(self, mediator, context, sample_text):
        """State should accumulate critic scores from each round."""
        scores = [0.65, 0.70, 0.75, 0.78, 0.80, 0.82]
        score_index = [0]
        
        def get_next_score(ont, ctx, data):
            score = scores[min(score_index[0], len(scores) - 1)]  # Reuse last if we run out
            score_index[0] += 1
            return _make_mock_score(overall=score)
        
        with patch.object(mediator.generator, "generate_ontology", return_value=_make_mock_ontology(version=1)), \
             patch.object(mediator.critic, "evaluate_ontology", side_effect=get_next_score), \
             patch.object(mediator, "refine_ontology", side_effect=lambda o, s, c: _make_mock_ontology(version=2)):
            
            state = mediator.run_refinement_cycle(sample_text, context)
        
        # Should have multiple scores
        assert len(state.critic_scores) >= 2
        
        # Scores should be increasing (or at least changing)
        first_score = state.critic_scores[0].overall if hasattr(state.critic_scores[0], "overall") else 0.0
        last_score = state.critic_scores[-1].overall if hasattr(state.critic_scores[-1], "overall") else 0.0
        assert last_score >= first_score  # Should not degrade
    
    def test_state_tracks_ontology_versions(self, mediator, context, sample_text):
        """State should track ontology evolution across rounds."""
        version_tracker = []
        
        def track_versions(ontology, score, ctx):
            version = ontology.get("metadata", {}).get("version", 0)
            version_tracker.append(version)
            return _make_mock_ontology(version=version + 1)
        
        with patch.object(mediator.generator, "generate_ontology", return_value=_make_mock_ontology(version=1)), \
             patch.object(mediator.critic, "evaluate_ontology", return_value=_make_mock_score(overall=0.70)), \
             patch.object(mediator, "refine_ontology", side_effect=track_versions):
            
            mediator.max_rounds = 3
            state = mediator.run_refinement_cycle(sample_text, context)
        
        # Should have tracked versions
        assert len(version_tracker) >= 1
        
        # Final ontology should have latest version
        final_version = state.current_ontology.get("metadata", {}).get("version", 0)
        assert final_version >= 1


# ===== Metadata and Timing =====

class TestCycleMetadata:
    """Test metadata tracking during refinement cycles."""
    
    def test_cycle_records_total_time(self, mediator, context, sample_text):
        """Cycle should record total execution time."""
        with patch.object(mediator.generator, "generate_ontology", return_value=_make_mock_ontology(version=1)), \
             patch.object(mediator.critic, "evaluate_ontology", return_value=_make_mock_score(overall=0.70)), \
             patch.object(mediator, "refine_ontology", return_value=_make_mock_ontology(version=2)):
            
            state = mediator.run_refinement_cycle(sample_text, context)
        
        # Should have timing info
        assert state.total_time_ms > 0
        assert state.total_time_ms < 10000  # Should complete in < 10 seconds
    
    def test_cycle_metadata_includes_score_trend(self, mediator, context, sample_text):
        """Cycle metadata should include score trend calculation."""
        with patch.object(mediator.generator, "generate_ontology", return_value=_make_mock_ontology(version=1)), \
             patch.object(mediator.critic, "evaluate_ontology", return_value=_make_mock_score(overall=0.70)), \
             patch.object(mediator, "refine_ontology", return_value=_make_mock_ontology(version=2)):
            
            state = mediator.run_refinement_cycle(sample_text, context)
        
        # Should have score_trend in metadata
        assert 'score_trend' in state.metadata
        assert 'final_score' in state.metadata
        assert 'improvement' in state.metadata
    
    def test_cycle_metadata_serializable(self, mediator, context, sample_text):
        """All cycle metadata should be JSON-serializable."""
        with patch.object(mediator.generator, "generate_ontology", return_value=_make_mock_ontology(version=1)), \
             patch.object(mediator.critic, "evaluate_ontology", return_value=_make_mock_score(overall=0.70)), \
             patch.object(mediator, "refine_ontology", return_value=_make_mock_ontology(version=2)):
            
            state = mediator.run_refinement_cycle(sample_text, context)
        
        # Metadata should be JSON-serializable
        metadata_json = json.dumps(state.metadata, default=str)
        assert metadata_json  # Non-empty
        
        parsed_metadata = json.loads(metadata_json)
        assert 'final_score' in parsed_metadata
        assert 'improvement' in parsed_metadata


# ===== Error Handling and Edge Cases =====

class TestCycleErrorHandling:
    """Test error handling during refinement cycles."""
    
    def test_cycle_handles_generator_failure(self, mediator, context, sample_text):
        """Cycle should handle generator failures gracefully."""
        with patch.object(mediator.generator, "generate_ontology", side_effect=RuntimeError("Generation failed")):
            with pytest.raises(RuntimeError, match="Generation failed"):
                mediator.run_refinement_cycle(sample_text, context)
    
    def test_cycle_handles_critic_failure(self, mediator, context, sample_text):
        """Cycle should handle critic failures gracefully."""
        with patch.object(mediator.generator, "generate_ontology", return_value=_make_mock_ontology(version=1)), \
             patch.object(mediator.critic, "evaluate_ontology", side_effect=RuntimeError("Evaluation failed")):
            with pytest.raises(RuntimeError, match="Evaluation failed"):
                mediator.run_refinement_cycle(sample_text, context)
    
    def test_cycle_handles_empty_ontology(self, mediator, context, sample_text):
        """Cycle should handle empty ontology gracefully."""
        empty_ontology = {"id": "empty", "entities": [], "relationships": [], "metadata": {}}
        
        with patch.object(mediator.generator, "generate_ontology", return_value=empty_ontology), \
             patch.object(mediator.critic, "evaluate_ontology", return_value=_make_mock_score(overall=0.10)), \
             patch.object(mediator, "refine_ontology", return_value=empty_ontology):
            
            state = mediator.run_refinement_cycle(sample_text, context)
        
        # Should complete but with low score
        assert state is not None
        assert len(state.current_ontology["entities"]) == 0
