"""Unit tests for LogicTheoremOptimizer metrics wiring.

Tests that the metrics_collector param is correctly wired into
BaseOptimizer.run_session() when used with LogicTheoremOptimizer.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest


def _make_optimizer(collector=None):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.unified_optimizer import (
        LogicTheoremOptimizer,
    )
    from ipfs_datasets_py.optimizers.common import OptimizerConfig

    opt = LogicTheoremOptimizer(
        config=OptimizerConfig(max_iterations=1, validation_enabled=False),
        use_provers=[],
        metrics_collector=collector,
    )
    return opt


def _make_context():
    from ipfs_datasets_py.optimizers.common import OptimizationContext
    return OptimizationContext(session_id="lto-test-1", input_data="dummy", domain="logic")


def _monkeypatch_optimizer(opt, monkeypatch):
    """Patch generate/critique/optimize/validate to avoid real ML calls."""
    monkeypatch.setattr(opt, "generate", lambda data, ctx: {"statements": [data]})
    monkeypatch.setattr(opt, "critique", lambda art, ctx: (0.9, []))
    monkeypatch.setattr(opt, "optimize", lambda art, score, fb, ctx: art)
    monkeypatch.setattr(opt, "validate", lambda art, ctx: True)


class TestLogicTheoremOptimizerMetrics:
    """Metrics collector wiring tests for LogicTheoremOptimizer."""

    def test_run_session_without_collector(self, monkeypatch):
        opt = _make_optimizer()
        _monkeypatch_optimizer(opt, monkeypatch)
        ctx = _make_context()
        result = opt.run_session("dummy", ctx)
        assert "artifact" in result
        assert result["score"] == pytest.approx(0.9, abs=1e-6)

    def test_run_session_with_collector_start_called(self, monkeypatch):
        collector = MagicMock()
        opt = _make_optimizer(collector=collector)
        _monkeypatch_optimizer(opt, monkeypatch)
        ctx = _make_context()
        opt.run_session("dummy", ctx)
        collector.start_cycle.assert_called_once()
        assert collector.start_cycle.call_args[0][0] == "lto-test-1"

    def test_run_session_with_collector_end_called(self, monkeypatch):
        collector = MagicMock()
        opt = _make_optimizer(collector=collector)
        _monkeypatch_optimizer(opt, monkeypatch)
        ctx = _make_context()
        opt.run_session("dummy", ctx)
        collector.end_cycle.assert_called_once()

    def test_run_session_broken_collector_does_not_crash(self, monkeypatch):
        collector = MagicMock()
        collector.start_cycle.side_effect = RuntimeError("db down")
        opt = _make_optimizer(collector=collector)
        _monkeypatch_optimizer(opt, monkeypatch)
        ctx = _make_context()
        result = opt.run_session("dummy", ctx)
        assert "score" in result  # session completed despite broken collector

    def test_metrics_collector_stored_on_optimizer(self):
        collector = MagicMock()
        opt = _make_optimizer(collector=collector)
        assert opt.metrics_collector is collector

    def test_metrics_dict_in_result(self, monkeypatch):
        opt = _make_optimizer()
        _monkeypatch_optimizer(opt, monkeypatch)
        ctx = _make_context()
        result = opt.run_session("dummy", ctx)
        assert "metrics" in result
        m = result["metrics"]
        assert "score_delta" in m
        assert "initial_score" in m


# ---------------------------------------------------------------------------
# Tests for learning_metrics_collector wiring (OptimizerLearningMetricsCollector)
# ---------------------------------------------------------------------------

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.unified_optimizer import LogicTheoremOptimizer
from ipfs_datasets_py.optimizers.common.base_optimizer import OptimizerConfig, OptimizationContext

class TestLogicTheoremOptimizerLearningMetrics:
    """LogicTheoremOptimizer wires learning_metrics_collector into run_session."""

    def _make_optimizer(self, lm_collector=None):
        config = OptimizerConfig(
            max_iterations=1,
            target_score=0.9,
            early_stopping=False,
            validation_enabled=False,
            metrics_enabled=False,
        )
        return LogicTheoremOptimizer(
            config=config,
            llm_backend=object(),
            learning_metrics_collector=lm_collector,
        )

    def _patch_and_run(self, optimizer, monkeypatch):
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer import logic_extractor as _le
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer.logic_extractor import (
            ExtractionResult,
            LogicExtractionContext,
            DataType,
            ExtractionMode,
            LogicalStatement,
        )
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer.logic_critic import (
            CriticScore, CriticDimensions, DimensionScore,
        )
        from ipfs_datasets_py.optimizers.common.base_optimizer import OptimizationContext

        extraction_ctx = LogicExtractionContext(
            data="Test theorem.", data_type=DataType.TEXT,
            extraction_mode=ExtractionMode.FOL, domain="general",
        )
        fake_result = ExtractionResult(
            statements=[LogicalStatement(
                formula="P(x)", natural_language="P holds.", confidence=0.7, formalism="fol",
            )],
            context=extraction_ctx, success=True,
        )
        fake_score = CriticScore(
            overall=0.65,
            dimension_scores=[DimensionScore(
                dimension=CriticDimensions.SOUNDNESS, score=0.65, feedback="OK",
            )],
            strengths=[], weaknesses=[], recommendations=[],
        )
        monkeypatch.setattr(optimizer.extractor, "extract", lambda ctx: fake_result)
        monkeypatch.setattr(optimizer.critic, "evaluate", lambda a: fake_score)
        ctx = OptimizationContext(session_id="lm-test-1", input_data="x", domain="general")
        return optimizer.run_session("x", ctx)

    def test_learning_metrics_not_created_when_module_missing(self, monkeypatch):
        import ipfs_datasets_py.optimizers.logic_theorem_optimizer.unified_optimizer as mod
        monkeypatch.setattr(mod, "_HAVE_LEARNING_METRICS", False)
        monkeypatch.setattr(mod, "OptimizerLearningMetricsCollector", None)
        opt = self._make_optimizer()
        assert opt._learning_metrics is None

    def test_learning_metrics_injected_collector_used(self, monkeypatch):
        collector = MagicMock()
        opt = self._make_optimizer(lm_collector=collector)
        self._patch_and_run(opt, monkeypatch)
        collector.record_learning_cycle.assert_called_once()

    def test_learning_metrics_cycle_id_contains_session_id(self, monkeypatch):
        collector = MagicMock()
        opt = self._make_optimizer(lm_collector=collector)
        self._patch_and_run(opt, monkeypatch)
        call_args = collector.record_learning_cycle.call_args
        cycle_id = call_args.args[0] if call_args.args else call_args.kwargs.get("cycle_id", "")
        assert "lm-test-1" in cycle_id

    def test_learning_metrics_exception_doesnt_propagate(self, monkeypatch):
        collector = MagicMock()
        collector.record_learning_cycle.side_effect = RuntimeError("oops")
        opt = self._make_optimizer(lm_collector=collector)
        result = self._patch_and_run(opt, monkeypatch)
        assert "score" in result

    def test_learning_metrics_auto_created_when_available(self, monkeypatch):
        import ipfs_datasets_py.optimizers.logic_theorem_optimizer.unified_optimizer as mod
        fake_cls = MagicMock(return_value=MagicMock())
        monkeypatch.setattr(mod, "_HAVE_LEARNING_METRICS", True)
        monkeypatch.setattr(mod, "OptimizerLearningMetricsCollector", fake_cls)
        opt = self._make_optimizer()
        assert opt._learning_metrics is not None
        fake_cls.assert_called_once_with()
