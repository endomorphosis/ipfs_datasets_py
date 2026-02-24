"""Batch 268: analyze_batch parallel routing tests."""

from types import SimpleNamespace

import pytest

from ipfs_datasets_py.optimizers.graphrag.ontology_optimizer import (
    OntologyOptimizer,
    OptimizationReport,
)


def _make_score(overall: float) -> SimpleNamespace:
    """Create a score-like object with required attributes."""
    return SimpleNamespace(
        overall=overall,
        completeness=overall * 0.98,
        consistency=overall * 0.95,
        clarity=overall * 0.96,
        granularity=overall * 0.94,
        domain_alignment=overall * 0.93,
    )


def _make_session(overall: float) -> SimpleNamespace:
    """Create a minimal session result with critic_scores and ontology."""
    return SimpleNamespace(
        critic_scores=[_make_score(overall)],
        current_ontology={"entities": [], "relationships": []},
        current_round=1,
    )


def test_analyze_batch_parallel_equivalence():
    """Parallel routing should preserve report outputs."""
    sessions = [_make_session(score) for score in (0.62, 0.71, 0.68, 0.74, 0.66)]

    optimizer_seq = OntologyOptimizer()
    report_seq = optimizer_seq.analyze_batch(
        sessions,
        use_parallel=False,
    )

    optimizer_par = OntologyOptimizer()
    report_par = optimizer_par.analyze_batch(
        sessions,
        use_parallel=True,
        max_workers=3,
    )

    assert report_seq.average_score == pytest.approx(report_par.average_score, rel=1e-6)
    assert report_seq.trend == report_par.trend
    assert report_seq.recommendations == report_par.recommendations
    assert report_seq.score_distribution == report_par.score_distribution


def test_analyze_batch_auto_parallel_threshold(monkeypatch):
    """Auto parallel routing should trigger for large batches."""
    sessions = [_make_session(0.7) for _ in range(6)]
    optimizer = OntologyOptimizer()

    called = {"value": False}

    def _fake_parallel(session_results, max_workers=4, json_log_path=None):
        called["value"] = True
        return OptimizationReport(
            average_score=0.7,
            trend="stable",
            recommendations=[],
            score_distribution={},
        )

    monkeypatch.setattr(optimizer, "analyze_batch_parallel", _fake_parallel)

    report = optimizer.analyze_batch(
        sessions,
        use_parallel=None,
        parallel_threshold=5,
    )

    assert called["value"] is True
    assert report.average_score == pytest.approx(0.7)
