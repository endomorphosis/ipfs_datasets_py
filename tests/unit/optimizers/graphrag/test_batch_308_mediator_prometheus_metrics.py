"""Batch 308: Prometheus metrics emission for OntologyMediator refinement cycles."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from ipfs_datasets_py.optimizers.graphrag import ontology_mediator as mediator_module
from ipfs_datasets_py.optimizers.graphrag.ontology_critic import CriticScore


class _FakePrometheusMetrics:
    def __init__(self) -> None:
        self.enabled = True
        self.score_calls: list[tuple[float, dict[str, str]]] = []
        self.round_calls: list[str | None] = []
        self.duration_calls: list[float] = []
        self.delta_calls: list[tuple[float, dict[str, str]]] = []

    def record_score(self, score: float, labels=None) -> None:
        self.score_calls.append((float(score), dict(labels or {})))

    def record_round_completion(self, domain: str | None = None) -> None:
        self.round_calls.append(domain)

    def record_session_duration(self, duration_seconds: float) -> None:
        self.duration_calls.append(float(duration_seconds))

    def record_score_delta(self, delta: float, labels=None) -> None:
        self.delta_calls.append((float(delta), dict(labels or {})))


class _StaticGenerator:
    def generate_ontology(self, data, context):
        return {
            "entities": [{"id": "e1", "type": "Person", "text": "Alice"}],
            "relationships": [],
            "metadata": {"source": "test"},
        }


class _SequencedCritic:
    def __init__(self, scores: list[CriticScore]):
        self._scores = scores
        self._idx = 0

    def evaluate_ontology(self, ontology, context, source_data=None):
        score = self._scores[min(self._idx, len(self._scores) - 1)]
        self._idx += 1
        return score


def _score(overall: float, recommendations: list[str] | None = None) -> CriticScore:
    return CriticScore(
        completeness=overall,
        consistency=overall,
        clarity=overall,
        granularity=overall,
        relationship_coherence=overall,
        domain_alignment=overall,
        recommendations=recommendations or [],
    )


@pytest.fixture
def context() -> SimpleNamespace:
    return SimpleNamespace(domain="general", extraction_strategy="rule_based", data_type="text")


def test_run_refinement_cycle_emits_prometheus_score_and_round_metrics(monkeypatch, context):
    metrics = _FakePrometheusMetrics()
    monkeypatch.setattr(mediator_module, "get_global_prometheus_metrics", lambda: metrics)

    mediator = mediator_module.OntologyMediator(
        generator=_StaticGenerator(),
        critic=_SequencedCritic([_score(0.35), _score(0.45), _score(0.55)]),
        max_rounds=3,
        convergence_threshold=0.95,
    )

    state = mediator.run_refinement_cycle(data="Alice met Bob.", context=context)

    assert len(state.refinement_history) >= 2
    assert len(metrics.score_calls) == len(state.refinement_history)
    assert len(metrics.round_calls) == len(state.refinement_history)
    assert metrics.duration_calls and metrics.duration_calls[-1] >= 0.0
    assert metrics.delta_calls and metrics.delta_calls[-1][0] >= 0.0
    assert all(labels.get("optimizer_type") == "ontology_mediator" for _, labels in metrics.score_calls)
    assert all(domain == "general" for domain in metrics.round_calls)


def test_run_agentic_refinement_cycle_emits_prometheus_iteration_metrics(monkeypatch, context):
    metrics = _FakePrometheusMetrics()
    monkeypatch.setattr(mediator_module, "get_global_prometheus_metrics", lambda: metrics)

    mediator = mediator_module.OntologyMediator(
        generator=_StaticGenerator(),
        critic=_SequencedCritic(
            [
                _score(0.40, recommendations=["Add missing properties for entities"]),
                _score(0.52, recommendations=["Normalize names"]),
                _score(0.63),
            ]
        ),
        max_rounds=3,
        convergence_threshold=0.95,
    )

    state = mediator.run_agentic_refinement_cycle(data="Alice met Bob.", context=context)

    assert len(state.refinement_history) >= 2
    assert len(metrics.score_calls) == len(state.refinement_history)
    assert len(metrics.round_calls) == len(state.refinement_history)
    assert metrics.duration_calls and metrics.duration_calls[-1] >= 0.0
    assert metrics.delta_calls
