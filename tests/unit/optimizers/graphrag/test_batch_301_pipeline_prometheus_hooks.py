"""Prometheus hook tests for OntologyPipeline."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ipfs_datasets_py.optimizers.graphrag.ontology_pipeline import OntologyPipeline


class _FakePrometheusMetrics:
    def __init__(self) -> None:
        self.enabled = True
        self.score_calls: List[tuple[float, Optional[Dict[str, str]]]] = []
        self.round_calls: List[Optional[str]] = []
        self.score_delta_calls: List[tuple[float, Optional[Dict[str, str]]]] = []
        self.stage_calls: List[tuple[str, float, Optional[Dict[str, str]]]] = []

    def record_score(self, score: float, labels: Optional[Dict[str, str]] = None) -> None:
        self.score_calls.append((score, labels))

    def record_round_completion(self, domain: Optional[str] = None) -> None:
        self.round_calls.append(domain)

    def record_score_delta(self, delta: float, labels: Optional[Dict[str, str]] = None) -> None:
        self.score_delta_calls.append((delta, labels))

    def record_stage_duration(
        self,
        stage: str,
        duration_seconds: float,
        labels: Optional[Dict[str, str]] = None,
    ) -> None:
        self.stage_calls.append((stage, duration_seconds, labels))


def test_pipeline_records_prometheus_score_round_and_stage_metrics(
    monkeypatch: Any,
) -> None:
    fake_metrics = _FakePrometheusMetrics()
    monkeypatch.setattr(
        "ipfs_datasets_py.optimizers.common.metrics_prometheus.get_global_prometheus_metrics",
        lambda enabled=None: fake_metrics,
    )

    pipeline = OntologyPipeline(domain="general")
    pipeline.run("Alice works at Acme Corp.", data_source="prometheus-test", refine=False)

    assert len(fake_metrics.score_calls) == 1
    assert len(fake_metrics.round_calls) == 1
    assert len(fake_metrics.stage_calls) >= 1
    score_value, score_labels = fake_metrics.score_calls[0]
    assert isinstance(score_value, float)
    assert score_labels is not None
    assert score_labels["domain"] == "general"
    assert score_labels["pipeline"] == "graphrag"
    assert fake_metrics.round_calls[0] == "general"


def test_pipeline_records_score_delta_from_second_run(monkeypatch: Any) -> None:
    fake_metrics = _FakePrometheusMetrics()
    monkeypatch.setattr(
        "ipfs_datasets_py.optimizers.common.metrics_prometheus.get_global_prometheus_metrics",
        lambda enabled=None: fake_metrics,
    )

    pipeline = OntologyPipeline(domain="general")
    pipeline.run("Alice works at Acme Corp.", refine=False)
    pipeline.run("Bob manages Acme Corp.", refine=False)

    assert len(fake_metrics.score_delta_calls) == 1
    delta_value, delta_labels = fake_metrics.score_delta_calls[0]
    assert isinstance(delta_value, float)
    assert delta_labels is not None
    assert delta_labels["domain"] == "general"
    assert delta_labels["pipeline"] == "graphrag"

