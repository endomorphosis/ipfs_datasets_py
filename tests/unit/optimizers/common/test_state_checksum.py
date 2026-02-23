"""Tests for BaseOptimizer.state_checksum() reproducibility method.

Validates that state_checksum() returns a stable, deterministic fingerprint
of the optimizer configuration and that it differentiates between distinct
configurations.
"""
from __future__ import annotations

import pytest

from ipfs_datasets_py.optimizers.common.base_optimizer import (
    BaseOptimizer,
    OptimizerConfig,
    OptimizationContext,
    OptimizationStrategy,
)


class SimpleOptimizer(BaseOptimizer):
    """Minimal concrete optimizer for testing."""

    def generate(self, input_data, context):
        return f"gen:{input_data}"

    def critique(self, artifact, context):
        return 0.8, ["ok"]

    def optimize(self, artifact, score, feedback, context):
        return f"{artifact}:opt"


class TestStateChecksum:
    """Tests for BaseOptimizer.state_checksum()."""

    def test_returns_string(self):
        """
        GIVEN: A configured optimizer
        WHEN: state_checksum() is called
        THEN: Returns a non-empty string
        """
        opt = SimpleOptimizer(config=OptimizerConfig())
        result = opt.state_checksum()
        assert isinstance(result, str)
        assert len(result) > 0

    def test_returns_hex_digest(self):
        """
        GIVEN: A configured optimizer
        WHEN: state_checksum() is called
        THEN: Returns a 32-character lowercase hex string (MD5)
        """
        opt = SimpleOptimizer(config=OptimizerConfig())
        checksum = opt.state_checksum()
        assert len(checksum) == 32
        assert all(c in "0123456789abcdef" for c in checksum)

    def test_deterministic_same_config(self):
        """
        GIVEN: Two optimizers with identical configurations
        WHEN: state_checksum() is called on each
        THEN: Both return the same checksum
        """
        config = OptimizerConfig(max_iterations=5, target_score=0.9)
        opt_a = SimpleOptimizer(config=config)
        opt_b = SimpleOptimizer(config=OptimizerConfig(max_iterations=5, target_score=0.9))
        assert opt_a.state_checksum() == opt_b.state_checksum()

    def test_different_max_iterations(self):
        """
        GIVEN: Two optimizers with different max_iterations
        WHEN: state_checksum() is called on each
        THEN: Checksums differ
        """
        opt_a = SimpleOptimizer(config=OptimizerConfig(max_iterations=5))
        opt_b = SimpleOptimizer(config=OptimizerConfig(max_iterations=10))
        assert opt_a.state_checksum() != opt_b.state_checksum()

    def test_different_target_score(self):
        """
        GIVEN: Two optimizers with different target_score
        WHEN: state_checksum() is called on each
        THEN: Checksums differ
        """
        opt_a = SimpleOptimizer(config=OptimizerConfig(target_score=0.8))
        opt_b = SimpleOptimizer(config=OptimizerConfig(target_score=0.95))
        assert opt_a.state_checksum() != opt_b.state_checksum()

    def test_different_strategy(self):
        """
        GIVEN: Two optimizers with different strategies
        WHEN: state_checksum() is called
        THEN: Checksums differ
        """
        opt_a = SimpleOptimizer(config=OptimizerConfig(strategy=OptimizationStrategy.SGD))
        opt_b = SimpleOptimizer(config=OptimizerConfig(strategy=OptimizationStrategy.HYBRID))
        assert opt_a.state_checksum() != opt_b.state_checksum()

    def test_stable_across_calls(self):
        """
        GIVEN: A configured optimizer
        WHEN: state_checksum() is called multiple times without config changes
        THEN: Each call returns the same value
        """
        opt = SimpleOptimizer(config=OptimizerConfig(max_iterations=7))
        checksums = [opt.state_checksum() for _ in range(5)]
        assert len(set(checksums)) == 1

    def test_different_learning_rate(self):
        """
        GIVEN: Two optimizers with different learning rates
        WHEN: state_checksum() is called
        THEN: Checksums differ
        """
        opt_a = SimpleOptimizer(config=OptimizerConfig(learning_rate=0.1))
        opt_b = SimpleOptimizer(config=OptimizerConfig(learning_rate=0.01))
        assert opt_a.state_checksum() != opt_b.state_checksum()

    def test_validation_enabled_flag(self):
        """
        GIVEN: Two optimizers differing only in validation_enabled
        WHEN: state_checksum() is called
        THEN: Checksums differ
        """
        opt_a = SimpleOptimizer(config=OptimizerConfig(validation_enabled=True))
        opt_b = SimpleOptimizer(config=OptimizerConfig(validation_enabled=False))
        assert opt_a.state_checksum() != opt_b.state_checksum()

    def test_checksum_does_not_depend_on_runtime_state(self):
        """
        GIVEN: An optimizer that has run a session
        WHEN: state_checksum() is called before and after running
        THEN: Checksums are identical (config unchanged)
        """
        config = OptimizerConfig(max_iterations=2, validation_enabled=False)
        opt = SimpleOptimizer(config=config)
        ctx = OptimizationContext(
            session_id="test",
            input_data="data",
            domain="test",
        )
        checksum_before = opt.state_checksum()
        opt.run_session("data", ctx)
        checksum_after = opt.state_checksum()
        assert checksum_before == checksum_after
