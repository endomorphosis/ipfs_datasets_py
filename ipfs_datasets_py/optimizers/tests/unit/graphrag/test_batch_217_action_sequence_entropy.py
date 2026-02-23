"""Tests for OntologyMediator.action_sequence_entropy() method.

Validates Shannon entropy calculation for action sequences, covering various
distribution patterns from uniform (high entropy) to highly skewed (low entropy).
"""

import pytest
from ipfs_datasets_py.optimizers.graphrag.ontology_mediator import OntologyMediator
from ipfs_datasets_py.optimizers.graphrag.ontology_generator import OntologyGenerator
from ipfs_datasets_py.optimizers.graphrag.ontology_critic import OntologyCritic
import math


@pytest.fixture
def mediator():
    """Create a basic mediator instance for testing."""
    generator = OntologyGenerator()
    critic = OntologyCritic(use_llm=False)
    return OntologyMediator(
        generator=generator,
        critic=critic,
        max_rounds=5,
        convergence_threshold=0.8,
    )


class TestActionSequenceEntropy:
    """Tests for action_sequence_entropy() method."""

    def test_empty_sequence_returns_zero(self, mediator):
        """Should return 0.0 when no actions recorded."""
        assert mediator.action_sequence_entropy() == 0.0

    def test_single_action_type_returns_zero(self, mediator):
        """Should return 0.0 when all actions are of the same type (no uncertainty)."""
        # Simulate recording same action multiple times
        mediator._action_entries = [
            ("add_missing_properties", 0),
            ("add_missing_properties", 1),
            ("add_missing_properties", 2),
        ]
        
        entropy = mediator.action_sequence_entropy()
        assert entropy == 0.0, "Single action type should have zero entropy"

    def test_two_actions_uniform_distribution(self, mediator):
        """Should return log2(2)=1.0 for two equally frequent action types."""
        mediator._action_entries = [
            ("add_missing_properties", 0),
            ("normalize_names", 1),
            ("add_missing_properties", 2),
            ("normalize_names", 3),
        ]
        
        entropy = mediator.action_sequence_entropy()
        expected = 1.0  # log2(2) for uniform distribution over 2 actions
        assert abs(entropy - expected) < 0.001, f"Expected {expected}, got {entropy}"

    def test_three_actions_uniform_distribution(self, mediator):
        """Should return log2(3)≈1.585 for three equally frequent action types."""
        mediator._action_entries = [
            ("add_missing_properties", 0),
            ("normalize_names", 1),
            ("prune_orphans", 2),
            ("add_missing_properties", 3),
            ("normalize_names", 4),
            ("prune_orphans", 5),
        ]
        
        entropy = mediator.action_sequence_entropy()
        expected = math.log2(3)  # ≈1.585
        assert abs(entropy - expected) < 0.001, f"Expected {expected:.3f}, got {entropy:.3f}"

    def test_skewed_distribution_lower_entropy(self, mediator):
        """Should return lower entropy for skewed distribution (one dominant action)."""
        # 80% one action, 20% another
        mediator._action_entries = [
            ("add_missing_properties", 0),
            ("add_missing_properties", 1),
            ("add_missing_properties", 2),
            ("add_missing_properties", 3),
            ("normalize_names", 4),
        ]
        
        entropy = mediator.action_sequence_entropy()
        
        # H = -0.8*log2(0.8) - 0.2*log2(0.2) ≈ 0.722
        p1, p2 = 0.8, 0.2
        expected = -(p1 * math.log2(p1) + p2 * math.log2(p2))
        
        assert abs(entropy - expected) < 0.001, f"Expected {expected:.3f}, got {entropy:.3f}"
        assert entropy < 1.0, "Skewed distribution should have entropy < 1.0"

    def test_maximum_entropy_uniform_distribution(self, mediator):
        """Should return log2(n) for uniform distribution over n action types."""
        n = 5
        actions = ["action_" + str(i) for i in range(n)]
        
        # Create uniform distribution: each action appears once
        mediator._action_entries = [(action, i) for i, action in enumerate(actions)]
        
        entropy = mediator.action_sequence_entropy()
        expected = math.log2(n)  # Maximum entropy for n symbols
        
        assert abs(entropy - expected) < 0.001, f"Expected {expected:.3f}, got {entropy:.3f}"

    def test_entropy_increases_with_diversity(self, mediator):
        """Should show increasing entropy as action distribution becomes more uniform."""
        # Scenario 1: 90% one action, 10% another
        mediator._action_entries = [("a", i) for i in range(9)] + [("b", 9)]
        entropy1 = mediator.action_sequence_entropy()
        
        # Scenario 2: 70% one action, 30% another
        mediator._action_entries = [("a", i) for i in range(7)] + [("b", i) for i in range(3)]
        entropy2 = mediator.action_sequence_entropy()
        
        # Scenario 3: 50% each (uniform)
        mediator._action_entries = [("a", i) for i in range(5)] + [("b", i) for i in range(5)]
        entropy3 = mediator.action_sequence_entropy()
        
        assert entropy1 < entropy2 < entropy3, "Entropy should increase with uniformity"

    def test_entropy_with_multiple_rounds(self, mediator):
        """Should correctly handle actions from multiple refinement rounds."""
        mediator._action_entries = [
            ("add_missing_properties", 0),
            ("normalize_names", 0),
            ("prune_orphans", 1),
            ("merge_duplicates", 1),
            ("add_missing_relationships", 2),
        ]
        
        entropy = mediator.action_sequence_entropy()
        
        # 5 actions, each appears once → log2(5) ≈ 2.322
        expected = math.log2(5)
        assert abs(entropy - expected) < 0.001

    def test_entropy_return_type(self, mediator):
        """Should always return a float."""
        mediator._action_entries = [("action", 0)]
        entropy = mediator.action_sequence_entropy()
        assert isinstance(entropy, float)

    def test_entropy_non_negative(self, mediator):
        """Should always return non-negative entropy."""
        test_cases = [
            [],  # empty
            [("a", 0)],  # single entry
            [("a", 0), ("a", 1)],  # same action
            [("a", 0), ("b", 1)],  # different actions
        ]
        
        for entries in test_cases:
            mediator._action_entries = entries
            entropy = mediator.action_sequence_entropy()
            assert entropy >= 0.0, f"Entropy should be non-negative, got {entropy}"

    def test_entropy_with_real_action_types(self, mediator):
        """Should work with actual refinement action type names."""
        mediator._action_entries = [
            ("add_missing_properties", 0),
            ("normalize_names", 0),
            ("prune_orphans", 1),
            ("merge_duplicates", 1),
            ("add_missing_relationships", 2),
            ("split_entity", 2),
            ("rename_entity", 3),
        ]
        
        entropy = mediator.action_sequence_entropy()
        
        # 7 unique actions, each once → log2(7) ≈ 2.807
        assert abs(entropy - math.log2(7)) < 0.001

    def test_entropy_calculation_formula(self, mediator):
        """Should correctly implement Shannon entropy formula."""
        # Test case with known entropy
        mediator._action_entries = [
            ("a", 0),
            ("a", 1),
            ("b", 2),
        ]
        
        # Manual calculation: p(a)=2/3, p(b)=1/3
        # H = -(2/3)*log2(2/3) - (1/3)*log2(1/3)
        p_a = 2/3
        p_b = 1/3
        expected = -(p_a * math.log2(p_a) + p_b * math.log2(p_b))
        
        entropy = mediator.action_sequence_entropy()
        assert abs(entropy - expected) < 0.001

    def test_entropy_with_long_sequence(self, mediator):
        """Should handle long action sequences efficiently."""
        # Create sequence with 100 actions, 10 types
        action_types = [f"action_{i % 10}" for i in range(100)]
        mediator._action_entries = [(action, i) for i, action in enumerate(action_types)]
        
        entropy = mediator.action_sequence_entropy()
        
        # Uniform distribution over 10 types → log2(10) ≈ 3.322
        expected = math.log2(10)
        assert abs(entropy - expected) < 0.001

    def test_entropy_comparison_ordered_vs_unordered(self, mediator):
        """Entropy should depend only on frequencies, not sequence order."""
        # Sequence 1: [a, a, b, b, c, c]
        mediator._action_entries = [
            ("a", 0), ("a", 1), ("b", 2), ("b", 3), ("c", 4), ("c", 5)
        ]
        entropy1 = mediator.action_sequence_entropy()
        
        # Sequence 2: [a, b, c, a, b, c] (same frequencies, different order)
        mediator._action_entries = [
            ("a", 0), ("b", 1), ("c", 2), ("a", 3), ("b", 4), ("c", 5)
        ]
        entropy2 = mediator.action_sequence_entropy()
        
        assert abs(entropy1 - entropy2) < 0.001, "Entropy should be order-independent"

    def test_entropy_with_malformed_entries(self, mediator):
        """Should handle malformed entries gracefully."""
        # Mix of valid and potentially malformed entries
        mediator._action_entries = [
            ("add_missing_properties", 0),
            ("normalize_names", 1),
            None,  # Malformed: None entry
            ("prune_orphans", 2),
        ]
        
        # Should skip None and compute on valid entries
        # 3 unique actions → log2(3)
        entropy = mediator.action_sequence_entropy()
        assert entropy > 0.0, "Should handle None entries by skipping"
