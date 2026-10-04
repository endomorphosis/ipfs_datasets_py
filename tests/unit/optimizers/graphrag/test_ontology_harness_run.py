"""Tests for OntologyHarness.run_sessions with real generator + critic."""

import pytest

from ipfs_datasets_py.optimizers.graphrag import (
    OntologyHarness,
    OntologyGenerationContext,
    DataType,
    ExtractionStrategy,
)


def _make_context(domain: str) -> OntologyGenerationContext:
    return OntologyGenerationContext(
        data_source="test",
        data_type=DataType.TEXT,
        domain=domain,
        extraction_strategy=ExtractionStrategy.RULE_BASED,
    )


def test_harness_run_sessions_real_components():
    """Harness should run real sessions and return aggregated BatchResult."""
    harness = OntologyHarness(parallelism=1, max_retries=0)

    docs = [
        "Alice works for Acme Corp.",
        "Bob manages the New York office for Acme.",
    ]
    contexts = [_make_context("legal"), _make_context("legal")]

    result = harness.run_sessions(docs, contexts, num_sessions_per_source=1)

    assert result.total_sessions == 2
    assert result.success_rate == 1.0
    assert len(result.sessions) == 2
    assert result.average_score >= 0.0
    assert result.best_session is not None


def test_harness_run_single_session_returns_error_tuple_on_runtime_failure(monkeypatch):
    """run_single_session should return (id, None, exc) when session creation/execution fails."""
    harness = OntologyHarness(parallelism=1, max_retries=0)

    def _raise_runtime_error():
        raise RuntimeError("session init failed")

    monkeypatch.setattr(harness, "create_session", _raise_runtime_error)

    sid, result, err = harness.run_single_session("doc", _make_context("legal"), session_id=42)

    assert sid == 42
    assert result is None
    assert isinstance(err, RuntimeError)
    assert "session init failed" in str(err)


def test_harness_run_sessions_collects_failed_sessions(monkeypatch):
    """run_sessions should report failed session metadata when individual runs fail."""
    harness = OntologyHarness(parallelism=1, max_retries=0)

    def _raise_runtime_error():
        raise RuntimeError("boom")

    monkeypatch.setattr(harness, "create_session", _raise_runtime_error)

    result = harness.run_sessions(
        ["Alice works for Acme"],
        [_make_context("legal")],
        num_sessions_per_source=1,
    )

    assert result.total_sessions == 1
    assert result.success_rate == 0.0
    assert result.sessions == []
    assert len(result.failed_sessions) == 1
    assert result.failed_sessions[0]["session_id"] == 0
    assert "boom" in result.failed_sessions[0]["error"]


def test_harness_run_sessions_optimizer_analysis_failure_is_non_fatal(monkeypatch):
    """Optimizer analysis errors should not fail the batch result."""
    harness = OntologyHarness(parallelism=1, max_retries=0)

    class _BrokenOptimizer:
        def analyze_batch(self, _states):
            raise RuntimeError("analysis boom")

    monkeypatch.setattr(harness, "OntologyOptimizer", _BrokenOptimizer)

    result = harness.run_sessions(
        ["Alice works for Acme"],
        [_make_context("legal")],
        num_sessions_per_source=1,
    )

    assert result.total_sessions == 1
    assert result.success_rate == 1.0
    assert len(result.sessions) == 1
    assert result.optimization_report is None
