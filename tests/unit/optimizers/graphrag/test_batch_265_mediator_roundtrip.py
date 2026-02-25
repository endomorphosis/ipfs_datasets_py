"""Batch 265: OntologyMediator.run_refinement_cycle() Round-Trip Tests

Tests round-trip serialization for complete refinement cycle state,
ensuring full state preservation across to_dict() / from_dict() cycles
after running actual refinement cycles.

Test Categories:
- Single round refinement cycle round-trip
- Multiple rounds refinement cycle round-trip  
- Convergence detection state preservation
- Critic feedback preservation across serialization
- Refinement action history integrity
- Integration with real generator/critic/mediator workflow
"""

import json
import pytest
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
)


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def mediator_with_components():
    """Create a mediator with real generator and critic."""
    generator = OntologyGenerator(use_ipfs_accelerate=False)
    critic = OntologyCritic()
    mediator = OntologyMediator(
        generator=generator,
        critic=critic,
        max_rounds=5,
        convergence_threshold=0.85,
    )
    return mediator


@pytest.fixture
def sample_text():
    """Sample text for testing refinement cycles."""
    return """
    John Smith works at Acme Corporation as a software engineer.
    He manages the engineering team and reports to the CTO, Jane Doe.
    The company is located in San Francisco, California.
    They develop cloud-based software solutions for enterprise clients.
    """


@pytest.fixture
def generation_context():
    """Create a generation context for testing."""
    return OntologyGenerationContext(
        data_source="test_roundtrip",
        data_type=DataType.TEXT,
        domain="business",
        extraction_strategy=ExtractionStrategy.RULE_BASED,
    )


# ============================================================================
# Test Classes
# ============================================================================

class TestSingleRoundRefinementRoundTrip:
    """Test round-trip serialization after single refinement round."""

    def test_single_round_state_serializable(
        self, mediator_with_components, sample_text, generation_context
    ):
        """Single round refinement produces serializable state."""
        mediator = mediator_with_components
        
        # Run one refinement cycle
        state = mediator.run_refinement_cycle(sample_text, generation_context)
        
        # Should be serializable
        state_dict = state.to_dict()
        assert isinstance(state_dict, dict)
        assert "current_ontology" in state_dict
        assert "critic_scores" in state_dict

    def test_single_round_deserialization_restores_state(
        self, mediator_with_components, sample_text, generation_context
    ):
        """Deserialized state matches original after single round."""
        mediator = mediator_with_components
        
        state = mediator.run_refinement_cycle(sample_text, generation_context)
        original_ontology = state.current_ontology.copy()
        original_scores = len(state.critic_scores)
        
        # Serialize and deserialize
        state_dict = state.to_dict()
        restored = MediatorState.from_dict(state_dict)
        
        # Verify restoration
        assert restored.current_ontology == original_ontology
        assert len(restored.critic_scores) == original_scores
        assert restored.current_round == state.current_round

    def test_single_round_json_round_trip(
        self, mediator_with_components, sample_text, generation_context
    ):
        """State survives JSON serialization round-trip."""
        mediator = mediator_with_components
        
        state = mediator.run_refinement_cycle(sample_text, generation_context)
        original_entities = len(state.current_ontology.get("entities", []))
        
        # JSON round-trip
        state_dict = state.to_dict()
        json_str = json.dumps(state_dict)
        restored_dict = json.loads(json_str)
        restored = MediatorState.from_dict(restored_dict)
        
        assert len(restored.current_ontology.get("entities", [])) == original_entities


class TestMultipleRoundsRefinementRoundTrip:
    """Test round-trip after multiple refinement rounds."""

    def test_multiple_rounds_state_preserved(
        self, mediator_with_components, sample_text, generation_context
    ):
        """Multi-round refinement state is preserved through serialization."""
        mediator = mediator_with_components
        
        # Run multiple refinement cycles
        state = mediator.run_refinement_cycle(sample_text, generation_context)
        # Force additional rounds by continuing refinement
        for _ in range(2):
            if not state.converged and state.current_round < mediator.max_rounds:
                state = mediator.run_refinement_cycle(sample_text, generation_context, initial_state=state)
        
        # Verify we have multiple rounds
        assert state.current_round >= 1
        
        # Serialize and restore
        state_dict = state.to_dict()
        restored = MediatorState.from_dict(state_dict)
        
        # Verify all rounds preserved
        assert restored.current_round == state.current_round
        assert len(restored.critic_scores) == len(state.critic_scores)
        assert len(restored.refinement_history) == len(state.refinement_history)

    def test_refinement_history_complete_after_roundtrip(
        self, mediator_with_components, sample_text, generation_context
    ):
        """Complete refinement history preserved through round-trip."""
        mediator = mediator_with_components
        
        state = mediator.run_refinement_cycle(sample_text, generation_context)
        original_history_len = len(state.refinement_history)
        
        # Round-trip
        restored = MediatorState.from_dict(state.to_dict())
        
        # History length preserved
        assert len(restored.refinement_history) == original_history_len
        
        # Each history entry has required fields
        for entry in restored.refinement_history:
            assert "round" in entry or "action" in entry


class TestConvergenceStatePreservation:
    """Test convergence detection state preservation."""

    def test_convergence_flag_preserved(
        self, mediator_with_components, sample_text, generation_context
    ):
        """Convergence flag survives serialization."""
        mediator = mediator_with_components
        
        state = mediator.run_refinement_cycle(sample_text, generation_context)
        original_converged = state.converged
        
        # Round-trip
        restored = MediatorState.from_dict(state.to_dict())
        
        assert restored.converged == original_converged

    def test_convergence_threshold_preserved(
        self, mediator_with_components, sample_text, generation_context
    ):
        """Convergence threshold preserved through round-trip."""
        mediator = mediator_with_components
        
        state = mediator.run_refinement_cycle(sample_text, generation_context)
        original_threshold = state.convergence_threshold
        
        # Round-trip
        restored = MediatorState.from_dict(state.to_dict())
        
        assert restored.convergence_threshold == original_threshold


class TestCriticFeedbackPreservation:
    """Test critic feedback preservation across serialization."""

    def test_critic_scores_preserved(
        self, mediator_with_components, sample_text, generation_context
    ):
        """Critic scores preserved through round-trip."""
        mediator = mediator_with_components
        
        state = mediator.run_refinement_cycle(sample_text, generation_context)
        if state.critic_scores:
            original_overall = state.critic_scores[-1].overall
            
            # Round-trip
            restored = MediatorState.from_dict(state.to_dict())
            
            if restored.critic_scores:
                assert restored.critic_scores[-1].overall == original_overall

    def test_score_recommendations_preserved(
        self, mediator_with_components, sample_text, generation_context
    ):
        """Score recommendations preserved through round-trip."""
        mediator = mediator_with_components
        
        state = mediator.run_refinement_cycle(sample_text, generation_context)
        
        # Round-trip
        restored = MediatorState.from_dict(state.to_dict())
        
        # Verify scores exist and have structure
        for score in restored.critic_scores:
            assert hasattr(score, 'overall')
            assert 0.0 <= score.overall <= 1.0


class TestMediatorConfigurationPreservation:
    """Test mediator configuration preservation."""

    def test_max_rounds_preserved(
        self, mediator_with_components, sample_text, generation_context
    ):
        """Max rounds setting preserved through round-trip."""
        mediator = mediator_with_components
        
        state = mediator.run_refinement_cycle(sample_text, generation_context)
        original_max_rounds = state.max_rounds
        
        # Round-trip
        restored = MediatorState.from_dict(state.to_dict())
        
        assert restored.max_rounds == original_max_rounds

    def test_target_score_preserved(
        self, mediator_with_components, sample_text, generation_context
    ):
        """Target score preserved through round-trip."""
        mediator = mediator_with_components
        
        state = mediator.run_refinement_cycle(sample_text, generation_context)
        original_target = state.target_score
        
        # Round-trip
        restored = MediatorState.from_dict(state.to_dict())
        
        assert restored.target_score == original_target


class TestEdgeCases:
    """Test edge cases for round-trip serialization."""

    def test_empty_ontology_round_trip(
        self, mediator_with_components, generation_context
    ):
        """Empty/minimal text produces valid round-trip state."""
        mediator = mediator_with_components
        
        # Minimal text
        minimal_text = "Test."
        
        state = mediator.run_refinement_cycle(minimal_text, generation_context)
        
        # Should still serialize
        state_dict = state.to_dict()
        restored = MediatorState.from_dict(state_dict)
        
        assert restored is not None
        assert isinstance(restored.current_ontology, dict)

    def test_complex_text_round_trip(
        self, mediator_with_components, generation_context
    ):
        """Complex multi-entity text produces valid round-trip state."""
        mediator = mediator_with_components
        
        complex_text = """
        Alice Johnson, CEO of TechCorp Inc., announced a partnership with
        Global Systems Ltd. The deal involves Dr. Robert Chen, Chief Technology
        Officer, and will be finalized in New York on January 15, 2024.
        The companies will collaborate on cloud infrastructure projects
        worth $50 million over three years.
        """
        
        state = mediator.run_refinement_cycle(complex_text, generation_context)
        
        # Round-trip
        restored = MediatorState.from_dict(state.to_dict())
        
        # Verify entities were extracted and preserved
        original_entities = len(state.current_ontology.get("entities", []))
        restored_entities = len(restored.current_ontology.get("entities", []))
        assert restored_entities == original_entities


class TestIntegrationWithFullWorkflow:
    """Integration tests with full mediator workflow."""

    def test_full_workflow_serializable(
        self, mediator_with_components, sample_text, generation_context
    ):
        """Complete workflow produces serializable state."""
        mediator = mediator_with_components
        
        # Full workflow
        state = mediator.run_refinement_cycle(sample_text, generation_context)
        
        # Verify workflow completed
        assert state.current_round >= 1
        assert state.current_ontology is not None
        
        # Verify serializable
        state_dict = state.to_dict()
        assert isinstance(state_dict, dict)
        
        # Verify restorable
        restored = MediatorState.from_dict(state_dict)
        assert restored.current_round == state.current_round

    def test_continuation_after_deserialization(
        self, mediator_with_components, sample_text, generation_context
    ):
        """Refinement can continue after state deserialization."""
        mediator = mediator_with_components
        
        # Initial refinement
        state = mediator.run_refinement_cycle(sample_text, generation_context)
        initial_round = state.current_round
        
        # Serialize and restore
        state_dict = state.to_dict()
        restored_state = MediatorState.from_dict(state_dict)
        
        # Can continue from restored state if not converged
        if not restored_state.converged and restored_state.current_round < mediator.max_rounds:
            continued_state = mediator.run_refinement_cycle(
                sample_text, generation_context, initial_state=restored_state
            )
            # Should advance
            assert continued_state.current_round > initial_round
