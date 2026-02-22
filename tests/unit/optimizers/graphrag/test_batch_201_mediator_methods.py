"""
Unit tests for Batch 201 OntologyMediator analysis methods.

Tests new methods for refinement tracking and analysis:
- total_refinements: Count all refinement operations
- rounds_completed: Count refinement roundshas_converged: Convergence detection
- refinement_efficiency: Improvement per action
- score_change_per_round: Average delta per round
- action_impact: Impact of specific actions
- most_productive_round: Find best improvement round
- refinement_stagnation_rounds: Track stagnation periods
- score_volatility: Measure score volatility
- refinement_trajectory: Overall improvement direction
"""

import pytest
from unittest.mock import Mock
from ipfs_datasets_py.optimizers.graphrag import OntologyMediator


@pytest.fixture
def mediator():
    """Create a test OntologyMediator instance with mocked dependencies."""
    mock_generator = Mock()
    mock_critic = Mock()
    return OntologyMediator(generator=mock_generator, critic=mock_critic)


class TestTotalRefinements:
    """Test total_refinements() method."""

    def test_total_refinements_positive(self, mediator):
        """Test with multiple refinements."""
        mediator._action_counts = {
            "add_entity": 3,
            "merge_entities": 2,
            "refine_properties": 4,
        }
        assert mediator.total_refinements() == 9

    def test_total_refinements_single(self, mediator):
        """Test with single refinement."""
        mediator._action_counts = {"add_entity": 1}
        assert mediator.total_refinements() == 1

    def test_total_refinements_empty(self, mediator):
        """Test with no refinements."""
        mediator._action_counts = {}
        assert mediator.total_refinements() == 0


class TestRoundsCompleted:
    """Test rounds_completed() method."""

    def test_rounds_completed_positive(self, mediator):
        """Test rounds count with history."""
        
        mediator._history = [
            {"score": 0.5},
            {"score": 0.6},
            {"score": 0.7},
        ]
        assert mediator.rounds_completed() == 3

    def test_rounds_completed_single(self, mediator):
        """Test with single round."""
        
        mediator._history = [{"score": 0.5}]
        assert mediator.rounds_completed() == 1

    def test_rounds_completed_empty(self, mediator):
        """Test with no history."""
        
        mediator._history = []
        assert mediator.rounds_completed() == 0


class TestHasConverged:
    """Test has_converged() method."""

    def test_has_converged_true(self, mediator):
        """Test convergence detection when converged."""
        
        mediator._history = [
            {"score": 0.5},
            {"score": 0.501},  # Delta < 0.01
            {"score": 0.502},  # Delta < 0.01
            {"score": 0.503},  # Delta < 0.01
        ]
        assert mediator.has_converged(threshold=0.01, window=3)

    def test_has_converged_false(self, mediator):
        """Test convergence detection when not converged."""
        
        mediator._history = [
            {"score": 0.5},
            {"score": 0.6},  # Delta > 0.01
            {"score": 0.7},
        ]
        assert not mediator.has_converged(threshold=0.01, window=2)

    def test_has_converged_insufficient_history(self, mediator):
        """Test with insufficient history."""
        
        mediator._history = [{"score": 0.5}]
        assert not mediator.has_converged()

    def test_has_converged_empty(self, mediator):
        """Test with empty history."""
        
        mediator._history = []
        assert not mediator.has_converged()


class TestRefinementEfficiency:
    """Test refinement_efficiency() method."""

    def test_refinement_efficiency_positive(self, mediator):
        """Test efficiency calculation with improvement."""
        
        mediator._history = [
            {"score": 0.5},  # Start
            {"score": 0.6},
        ]
        mediator._action_counts = {"add_entity": 5}  # 5 actions for 0.1 improvement
        efficiency = mediator.refinement_efficiency()
        expected = (0.6 - 0.5) / 5  # 0.02
        assert abs(efficiency - expected) < 1e-6

    def test_refinement_efficiency_no_actions(self, mediator):
        """Test efficiency with no actions."""
        
        mediator._history = [{"score": 0.5}]
        mediator._action_counts = {}
        assert mediator.refinement_efficiency() == 0.0

    def test_refinement_efficiency_no_improvement(self, mediator):
        """Test efficiency with no score change."""
        
        mediator._history = [
            {"score": 0.5},
            {"score": 0.5},
        ]
        mediator._action_counts = {"add_entity": 3}
        assert mediator.refinement_efficiency() == 0.0


class TestScoreChangePerRound:
    """Test score_change_per_round() method."""

    def test_score_change_per_round_positive(self, mediator):
        """Test average score change calculation."""
        
        mediator._history = [
            {"score": 0.5},
            {"score": 0.6},  # Delta 0.1
            {"score": 0.65},  # Delta 0.05
            {"score": 0.7},  # Delta 0.05
        ]
        avg_change = mediator.score_change_per_round()
        expected = (0.1 + 0.05 + 0.05) / 3  # 0.0667
        assert abs(avg_change - expected) < 1e-4

    def test_score_change_per_round_single_change(self, mediator):
        """Test with single round transition."""
        
        mediator._history = [
            {"score": 0.5},
            {"score": 0.7},
        ]
        assert abs(mediator.score_change_per_round() - 0.2) < 1e-6

    def test_score_change_per_round_insufficient(self, mediator):
        """Test with insufficient history."""
        
        mediator._history = [{"score": 0.5}]
        assert mediator.score_change_per_round() == 0.0


class TestActionImpact:
    """Test action_impact() method."""

    def test_action_impact_positive(self, mediator):
        """Test impact calculation for an action."""
        
        mediator._action_counts = {
            "add_entity": 5,
            "merge_entities": 3,
        }
        impact = mediator.action_impact("add_entity")
        expected = 5 / 8  # 0.625
        assert abs(impact - expected) < 1e-6

    def test_action_impact_absent_action(self, mediator):
        """Test impact for non-existent action."""
        
        mediator._action_counts = {"add_entity": 3}
        assert mediator.action_impact("unknown_action") == 0.0

    def test_action_impact_no_actions(self, mediator):
        """Test impact with no recorded actions."""
        
        mediator._action_counts = {}
        assert mediator.action_impact("any_action") == 0.0


class TestMostProductiveRound:
    """Test most_productive_round() method."""

    def test_most_productive_round_found(self, mediator):
        """Test finding most productive round."""
        
        mediator._history = [
            {"score": 0.5},
            {"score": 0.6},  # Improvement 0.1
            {"score": 0.65},  # Improvement 0.05
            {"score": 0.8},  # Improvement 0.15 <- Best
            {"score": 0.78},  # Degradation
        ]
        assert mediator.most_productive_round() == 3

    def test_most_productive_round_first(self, mediator):
        """Test when most productive is first round."""
        
        mediator._history = [
            {"score": 0.5},
            {"score": 0.8},  # First big jump
            {"score": 0.81},  # Small improvement
        ]
        assert mediator.most_productive_round() == 1

    def test_most_productive_round_no_improvement(self, mediator):
        """Test when no improvement occurs."""
        
        mediator._history = [
            {"score": 0.5},
            {"score": 0.4},
            {"score": 0.3},
        ]
        assert mediator.most_productive_round() == -1

    def test_most_productive_round_insufficient(self, mediator):
        """Test with insufficient history."""
        
        mediator._history = [{"score": 0.5}]
        assert mediator.most_productive_round() == -1


class TestRefinementStagnationRounds:
    """Test refinement_stagnation_rounds() method."""

    def test_stagnation_rounds_found(self, mediator):
        """Test detecting stagnation at end."""
        
        mediator._history = [
            {"score": 0.5},
            {"score": 0.7},  # Improvement
            {"score": 0.7001},  # Stagnation starts
            {"score": 0.7002},  # Stagnation
            {"score": 0.7001},  # Stagnation
        ]
        stagnation = mediator.refinement_stagnation_rounds(threshold=0.001)
        assert stagnation == 3

    def test_stagnation_rounds_none(self, mediator):
        """Test when no end stagnation."""
        
        mediator._history = [
            {"score": 0.5},
            {"score": 0.6},
            {"score": 0.7},
        ]
        assert mediator.refinement_stagnation_rounds() == 0

    def test_stagnation_rounds_all(self, mediator):
        """Test when all rounds stagnant."""
        
        mediator._history = [
            {"score": 0.5},
            {"score": 0.5},
            {"score": 0.5},
        ]
        stagnation = mediator.refinement_stagnation_rounds(threshold=0.01)
        assert stagnation == 2  # Last 2 rounds after first

    def test_stagnation_rounds_insufficient(self, mediator):
        """Test with insufficient history."""
        
        mediator._history = [{"score": 0.5}]
        assert mediator.refinement_stagnation_rounds() == 0


class TestScoreVolatility:
    """Test score_volatility() method."""

    def test_score_volatility_positive(self, mediator):
        """Test volatility calculation."""
        
        mediator._history = [
            {"score": 0.5},  # Mean = 0.6, variance = 0.04
            {"score": 0.7},
        ]
        volatility = mediator.score_volatility()
        expected_variance = 0.01 + 0.01  # Variance per point
        expected_std = (expected_variance / 2) ** 0.5  # 0.1
        assert abs(volatility - expected_std) < 1e-6

    def test_score_volatility_no_variation(self, mediator):
        """Test volatility when scores identical."""
        
        mediator._history = [
            {"score": 0.5},
            {"score": 0.5},
            {"score": 0.5},
        ]
        assert mediator.score_volatility() == 0.0

    def test_score_volatility_insufficient(self, mediator):
        """Test with insufficient data."""
        
        mediator._history = [{"score": 0.5}]
        assert mediator.score_volatility() == 0.0


class TestRefinementTrajectory:
    """Test refinement_trajectory() method."""

    def test_trajectory_improving(self, mediator):
        """Test improving trajectory."""
        
        mediator._history = [
            {"score": 0.5},
            {"score": 0.6},
            {"score": 0.7},  # Final > Initial + 0.05
        ]
        assert mediator.refinement_trajectory() == "improving"

    def test_trajectory_degrading(self, mediator):
        """Test degrading trajectory."""
        
        mediator._history = [
            {"score": 0.8},
            {"score": 0.7},
            {"score": 0.6},  # Final < Initial - 0.05
        ]
        assert mediator.refinement_trajectory() == "degrading"

    def test_trajectory_stable(self, mediator):
        """Test stable trajectory."""
        
        mediator._history = [
            {"score": 0.6},
            {"score": 0.61},
            {"score": 0.602},
        ]
        assert mediator.refinement_trajectory() == "stable"

    def test_trajectory_volatile(self, mediator):
        """Test volatile trajectory."""
        
        mediator._history = [
            {"score": 0.5},
            {"score": 0.9},
            {"score": 0.2},
            {"score": 0.8},
        ]
        trajectory = mediator.refinement_trajectory()
        assert trajectory == "volatile"

    def test_trajectory_unknown(self, mediator):
        """Test unknown trajectory."""
        
        mediator._history = [{"score": 0.5}]
        assert mediator.refinement_trajectory() == "unknown"


# Integration tests
class TestBatch201Integration:
    """Integration tests for refinement analysis."""

    def test_complete_refinement_analysis(self, mediator):
        """Test analyzing a complete refinement session."""
        
        mediator._history = [
            {"score": 0.5},
            {"score": 0.6},
            {"score": 0.65},
            {"score": 0.68},
            {"score": 0.85},
        ]
        mediator._action_counts = {
            "add_entity": 10,
            "merge_entities": 5,
            "refine_properties": 8,
        }
        
        # All analysis methods should work together
        assert mediator.total_refinements() == 23
        assert mediator.rounds_completed() == 5
        assert not mediator.has_converged()
        efficiency = mediator.refinement_efficiency()
        assert efficiency > 0
        assert mediator.most_productive_round() >= 0
        assert mediator.refinement_trajectory() == "improving"

    def test_stagnant_session_analysis(self, mediator):
        """Test analyzing stagnant refinement session."""
        
        mediator._history = [
            {"score": 0.7},
            {"score": 0.8},  # Initial improvement
            {"score": 0.8001},  # Stagnation starts
            {"score": 0.8002},
            {"score": 0.8001},
        ]
        mediator._action_counts = {"update": 50}
        
        # Should detect stagnation and low efficiency
        stagnation = mediator.refinement_stagnation_rounds(threshold=0.001)
        assert stagnation == 3  # Last 3 rounds are stagnant
        efficiency = mediator.refinement_efficiency()
        assert efficiency < 0.01  # Very low efficiency


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
