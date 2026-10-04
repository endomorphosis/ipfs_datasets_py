"""Batch 309: OpenTelemetry span hooks for OntologyMediator cycles."""

from __future__ import annotations

from types import SimpleNamespace

from ipfs_datasets_py.optimizers.graphrag import ontology_mediator as mediator_module
from ipfs_datasets_py.optimizers.graphrag.ontology_critic import CriticScore


class _Span:
    def __init__(self, name: str) -> None:
        self.name = name
        self.attributes: dict[str, object] = {}

    def set_attribute(self, key: str, value: object) -> None:
        self.attributes[key] = value


class _SpanContext:
    def __init__(self, tracer: "_Tracer", name: str) -> None:
        self._tracer = tracer
        self._name = name
        self._span = _Span(name)

    def __enter__(self):
        self._tracer.spans.append(self._span)
        return self._span

    def __exit__(self, exc_type, exc, tb):
        return False


class _Tracer:
    def __init__(self) -> None:
        self.spans: list[_Span] = []

    def start_as_current_span(self, name: str):
        return _SpanContext(self, name)


class _TraceModule:
    def __init__(self, tracer: _Tracer) -> None:
        self._tracer = tracer

    def get_tracer(self, name: str):
        return self._tracer


class _NoopPrometheus:
    enabled = False


class _Generator:
    def generate_ontology(self, data, context):
        return {
            "entities": [{"id": "e1", "type": "Person", "text": "Alice"}],
            "relationships": [],
            "metadata": {},
        }


class _Critic:
    def __init__(self):
        self._scores = [
            self._score(0.35),
            self._score(0.48),
            self._score(0.61),
        ]
        self._idx = 0

    @staticmethod
    def _score(v: float) -> CriticScore:
        return CriticScore(
            completeness=v,
            consistency=v,
            clarity=v,
            granularity=v,
            relationship_coherence=v,
            domain_alignment=v,
            recommendations=["Add missing properties"],
        )

    def evaluate_ontology(self, ontology, context, source_data=None):
        score = self._scores[min(self._idx, len(self._scores) - 1)]
        self._idx += 1
        return score


def test_refinement_cycle_emits_otel_spans_when_enabled(monkeypatch):
    tracer = _Tracer()
    monkeypatch.setenv("OTEL_ENABLED", "true")
    monkeypatch.setattr(mediator_module, "HAVE_OPENTELEMETRY", True)
    monkeypatch.setattr(mediator_module, "trace", _TraceModule(tracer))
    monkeypatch.setattr(mediator_module, "get_global_prometheus_metrics", lambda: _NoopPrometheus())

    mediator = mediator_module.OntologyMediator(
        generator=_Generator(),
        critic=_Critic(),
        max_rounds=3,
        convergence_threshold=0.95,
    )

    context = SimpleNamespace(domain="general", extraction_strategy="rule_based", data_type="text")
    state = mediator.run_refinement_cycle(data="Alice met Bob.", context=context)

    names = [span.name for span in tracer.spans]
    assert "ontology_mediator.initial_generation" in names
    assert "ontology_mediator.round" in names
    assert "ontology_mediator.summary" in names

    summary_span = next(span for span in tracer.spans if span.name == "ontology_mediator.summary")
    assert summary_span.attributes.get("optimizer.type") == "ontology_mediator"
    assert summary_span.attributes.get("refinement.mode") == "standard"
    assert summary_span.attributes.get("domain") == "general"
    assert summary_span.attributes.get("rounds") == state.current_round


def test_agentic_cycle_emits_agentic_mode_summary_span(monkeypatch):
    tracer = _Tracer()
    monkeypatch.setenv("OTEL_ENABLED", "true")
    monkeypatch.setattr(mediator_module, "HAVE_OPENTELEMETRY", True)
    monkeypatch.setattr(mediator_module, "trace", _TraceModule(tracer))
    monkeypatch.setattr(mediator_module, "get_global_prometheus_metrics", lambda: _NoopPrometheus())

    mediator = mediator_module.OntologyMediator(
        generator=_Generator(),
        critic=_Critic(),
        max_rounds=3,
        convergence_threshold=0.95,
    )

    context = SimpleNamespace(domain="general", extraction_strategy="rule_based", data_type="text")
    mediator.run_agentic_refinement_cycle(data="Alice met Bob.", context=context)

    summary_span = next(span for span in tracer.spans if span.name == "ontology_mediator.summary")
    assert summary_span.attributes.get("refinement.mode") == "agentic"
