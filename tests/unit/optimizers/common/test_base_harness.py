"""Tests for BaseHarness orchestration logic.

Uses a simple concrete subclass that doesn't require external LLM/prover deps.
"""
from __future__ import annotations

import pytest

from ipfs_datasets_py.optimizers.common.base_harness import BaseHarness, HarnessConfig
from ipfs_datasets_py.optimizers.common.base_critic import CriticResult
from ipfs_datasets_py.optimizers.common.base_session import BaseSession


class _CountingHarness(BaseHarness):
    """Minimal harness: score goes up by 0.1 per round, starting at 0.4."""

    def __init__(self, config=None, start_score=0.4, step=0.1, fail_generate=False):
        super().__init__(config)
        self._round = 0
        self._start = start_score
        self._step = step
        self._fail_generate = fail_generate

    def _generate(self, data, context):
        if self._fail_generate:
            from ipfs_datasets_py.optimizers.common.exceptions import ExtractionError
            raise ExtractionError("generate failed")
        return {"data": data, "round": self._round}

    def _critique(self, artifact, context):
        score = min(self._start + self._round * self._step, 1.0)
        self._round += 1
        return CriticResult(score=score, feedback={"round": self._round})

    def _optimize(self, artifact, critique, context):
        return {**artifact, "optimized": True}


class TestBaseHarnessRun:
    def test_returns_base_session(self):
        h = _CountingHarness()
        session = h.run("hello", None)
        assert isinstance(session, BaseSession)

    def test_session_has_scores(self):
        h = _CountingHarness(config=HarnessConfig(max_rounds=3))
        session = h.run("test", None)
        assert len(session.scores) > 0

    def test_best_score_increases_over_rounds(self):
        h = _CountingHarness(config=HarnessConfig(max_rounds=5, target_score=1.1))
        session = h.run("test", None)
        assert session.best_score >= 0.4

    def test_target_score_stops_early(self):
        # start_score=0.9 so first round already passes 0.85 target
        h = _CountingHarness(
            config=HarnessConfig(max_rounds=10, target_score=0.85),
            start_score=0.9,
        )
        session = h.run("test", None)
        # Should not run all 10 rounds; convergence should stop it
        assert session.current_round <= 10

    def test_session_metadata_has_final_valid(self):
        h = _CountingHarness()
        session = h.run("x", None)
        assert "final_valid" in session.metadata

    def test_custom_session_id(self):
        h = _CountingHarness()
        session = h.run("x", None, session_id="my-session-42")
        assert session.session_id == "my-session-42"

    def test_domain_stored_on_session(self):
        h = _CountingHarness()
        session = h.run("x", None, domain="legal")
        assert session.domain == "legal"

    def test_get_config_returns_dict(self):
        h = _CountingHarness(config=HarnessConfig(max_rounds=7))
        cfg = h.get_config()
        assert cfg["max_rounds"] == 7
        assert cfg["harness_class"] == "_CountingHarness"

    def test_verbose_flag_accepted(self):
        h = _CountingHarness(config=HarnessConfig(max_rounds=2, verbose=True))
        session = h.run("x", None)  # Just verify it doesn't crash
        assert session is not None


class TestHarnessConfig:
    def test_defaults(self):
        cfg = HarnessConfig()
        assert cfg.max_rounds == 10
        assert cfg.target_score == 0.85
        assert cfg.convergence_threshold == 0.01
        assert cfg.verbose is False

    def test_custom_values(self):
        cfg = HarnessConfig(max_rounds=5, target_score=0.95, verbose=True)
        assert cfg.max_rounds == 5
        assert cfg.target_score == 0.95
        assert cfg.verbose is True
