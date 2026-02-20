"""Tests for OntologyOptimizer metrics collector wiring."""
from __future__ import annotations

import json
import time
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from ipfs_datasets_py.optimizers.graphrag.ontology_optimizer import (
    OntologyOptimizer,
    OptimizationReport,
)


def _make_result(score: float):
    """Build a minimal session-result stub with a critic score."""
    cr = SimpleNamespace(overall=score)
    return SimpleNamespace(critic_score=cr)


class TestMetricsCollectorWiring:
    """OntologyOptimizer wires OptimizerLearningMetricsCollector after analyze_batch."""

    def test_default_no_metrics_when_module_missing(self, monkeypatch):
        """If HAVE_LEARNING_METRICS is False, _metrics is None."""
        import ipfs_datasets_py.optimizers.graphrag.ontology_optimizer as mod
        monkeypatch.setattr(mod, "HAVE_LEARNING_METRICS", False)
        monkeypatch.setattr(mod, "OptimizerLearningMetricsCollector", None)
        opt = OntologyOptimizer()
        assert opt._metrics is None

    def test_injected_collector_is_used(self):
        """Injected metrics_collector gets record_learning_cycle called."""
        collector = MagicMock()
        opt = OntologyOptimizer(metrics_collector=collector)
        assert opt._metrics is collector

        results = [_make_result(0.8), _make_result(0.6)]
        opt.analyze_batch(results)

        collector.record_learning_cycle.assert_called_once()
        call_kwargs = collector.record_learning_cycle.call_args
        kw = call_kwargs.kwargs if call_kwargs.kwargs else {}
        args = call_kwargs.args if call_kwargs.args else ()
        # cycle_id is first positional arg
        assert "ontology_batch_" in (args[0] if args else kw.get("cycle_id", ""))

    def test_parallel_injected_collector_is_used(self):
        """analyze_batch_parallel also records a learning cycle."""
        collector = MagicMock()
        opt = OntologyOptimizer(metrics_collector=collector)

        results = [_make_result(0.7), _make_result(0.9)]
        opt.analyze_batch_parallel(results, max_workers=2)

        collector.record_learning_cycle.assert_called_once()
        call_args = collector.record_learning_cycle.call_args
        # cycle_id may be positional or keyword
        cycle_id = (
            call_args.args[0]
            if call_args.args
            else call_args.kwargs.get("cycle_id", "")
        )
        assert "ontology_parallel_batch_" in cycle_id

    def test_collector_exception_doesnt_propagate(self):
        """Metrics errors must never surface from analyze_batch."""
        collector = MagicMock()
        collector.record_learning_cycle.side_effect = RuntimeError("boom")
        opt = OntologyOptimizer(metrics_collector=collector)
        # Should not raise
        report = opt.analyze_batch([_make_result(0.5)])
        assert report.average_score == pytest.approx(0.5)

    def test_auto_collector_created_when_module_available(self, monkeypatch):
        """When HAVE_LEARNING_METRICS is True, a default collector is created."""
        import ipfs_datasets_py.optimizers.graphrag.ontology_optimizer as mod
        fake_cls = MagicMock(return_value=MagicMock())
        monkeypatch.setattr(mod, "HAVE_LEARNING_METRICS", True)
        monkeypatch.setattr(mod, "OptimizerLearningMetricsCollector", fake_cls)
        opt = OntologyOptimizer()
        assert opt._metrics is not None
        fake_cls.assert_called_once_with()

    def test_analyze_batch_empty_does_not_call_metrics(self):
        """Empty batch returns early before metrics recording."""
        collector = MagicMock()
        opt = OntologyOptimizer(metrics_collector=collector)
        report = opt.analyze_batch([])
        collector.record_learning_cycle.assert_not_called()
        assert report.trend == "insufficient_data"

    def test_metrics_analyzed_queries_equals_session_count(self):
        """record_learning_cycle analyzed_queries == len(session_results)."""
        collector = MagicMock()
        opt = OntologyOptimizer(metrics_collector=collector)
        n = 5
        opt.analyze_batch([_make_result(0.6)] * n)
        call_kwargs = collector.record_learning_cycle.call_args.kwargs
        # analyzed_queries is a positional arg at index 1
        args = collector.record_learning_cycle.call_args.args
        analyzed = args[1] if len(args) > 1 else call_kwargs.get("analyzed_queries")
        assert analyzed == n

    def test_analyze_batch_emits_structured_json_summary_log(self, caplog):
        """Successful analyze_batch emits one parseable JSON summary at INFO."""
        opt = OntologyOptimizer()

        with caplog.at_level("INFO"):
            opt.analyze_batch([_make_result(0.8), _make_result(0.6)])

        payloads = []
        for rec in caplog.records:
            try:
                msg = json.loads(rec.message)
            except Exception:
                continue
            if msg.get("event") == "ontology_optimizer.analyze_batch.summary":
                payloads.append(msg)

        assert payloads, "Expected structured analyze_batch summary JSON log"
        summary = payloads[-1]
        assert summary["status"] == "ok"
        assert summary["session_count"] == 2
        assert summary["trend"] in {"baseline", "improving", "stable", "degrading"}
        assert summary["average_score"] == pytest.approx(0.7)

    def test_analyze_batch_empty_emits_structured_json_summary_log(self, caplog):
        """Empty analyze_batch also emits a structured JSON summary log."""
        opt = OntologyOptimizer()

        with caplog.at_level("INFO"):
            report = opt.analyze_batch([])

        assert report.trend == "insufficient_data"

        payloads = []
        for rec in caplog.records:
            try:
                msg = json.loads(rec.message)
            except Exception:
                continue
            if msg.get("event") == "ontology_optimizer.analyze_batch.summary":
                payloads.append(msg)

        assert payloads, "Expected structured analyze_batch summary JSON log"
        summary = payloads[-1]
        assert summary["status"] == "insufficient_data"
        assert summary["session_count"] == 0
