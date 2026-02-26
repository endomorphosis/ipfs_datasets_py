"""Tests for OntologyPipeline OpenTelemetry run span integration."""

from __future__ import annotations

from unittest.mock import Mock

from ipfs_datasets_py.optimizers.graphrag.ontology_pipeline import OntologyPipeline
from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
    Entity,
    EntityExtractionResult,
    Relationship,
)


class _SpanRecorder:
    def __init__(self, name: str, sink: list[tuple[str, dict[str, object]]]) -> None:
        self._name = name
        self._sink = sink
        self._attrs: dict[str, object] = {}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self._sink.append((self._name, dict(self._attrs)))
        return False

    def set_attribute(self, key: str, value: object) -> None:
        self._attrs[key] = value


class _TracerRecorder:
    def __init__(self) -> None:
        self.spans: list[tuple[str, dict[str, object]]] = []

    def start_as_current_span(self, name: str) -> _SpanRecorder:
        return _SpanRecorder(name, self.spans)


def _make_pipeline_with_mocks() -> OntologyPipeline:
    pipeline = OntologyPipeline(domain="legal", use_llm=False, max_rounds=1)

    extraction = EntityExtractionResult(
        entities=[Entity(id="e1", text="Alice", type="person", confidence=0.99)],
        relationships=[
            Relationship(
                id="r1",
                source_id="e1",
                target_id="e1",
                type="self",
                confidence=0.8,
            )
        ],
        confidence=0.9,
    )
    refined = {
        "entities": [{"id": "e1", "name": "Alice"}],
        "relationships": [{"source": "e1", "target": "e1", "type": "self"}],
        "metadata": {"refinement_actions": ["noop"]},
    }

    pipeline._generator = Mock()
    pipeline._generator.extract_entities.return_value = extraction

    pipeline._critic = Mock()
    pipeline._critic.evaluate_ontology.return_value = Mock(overall=0.8)

    pipeline._mediator = Mock()
    pipeline._mediator.refine_ontology.return_value = refined
    pipeline._mediator.max_rounds = 1

    pipeline._adapter = Mock()
    pipeline._adapter.get_extraction_hint.return_value = 0.5
    return pipeline


def test_pipeline_run_records_otel_span_when_enabled(monkeypatch) -> None:
    monkeypatch.setenv("OTEL_ENABLED", "1")
    pipeline = _make_pipeline_with_mocks()
    tracer = _TracerRecorder()
    pipeline._otel_tracer = tracer
    pipeline._otel_enabled = True

    result = pipeline.run("Alice signed contract", data_source="unit-test", data_type="text", refine=True)

    assert result.score.overall == 0.8
    assert len(tracer.spans) == 1
    span_name, attrs = tracer.spans[0]
    assert span_name == "graphrag.pipeline.run"
    assert attrs["pipeline.domain"] == "legal"
    assert attrs["pipeline.data_source"] == "unit-test"
    assert attrs["pipeline.refine"] is True
    assert attrs["pipeline.entity_count"] == 1


def test_pipeline_run_skips_otel_span_when_disabled(monkeypatch) -> None:
    monkeypatch.delenv("OTEL_ENABLED", raising=False)
    pipeline = _make_pipeline_with_mocks()
    tracer = _TracerRecorder()
    pipeline._otel_tracer = tracer
    pipeline._otel_enabled = False

    pipeline.run("Alice signed contract", data_source="unit-test", data_type="text", refine=False)

    assert tracer.spans == []


def test_pipeline_run_batch_records_otel_span_when_enabled(monkeypatch) -> None:
    monkeypatch.setenv("OTEL_ENABLED", "1")
    pipeline = _make_pipeline_with_mocks()
    tracer = _TracerRecorder()
    pipeline._otel_tracer = tracer
    pipeline._otel_enabled = True

    result = pipeline.run_batch(
        ["Alice signed contract", "Bob signed agreement"],
        data_source="unit-test-batch",
        data_type="text",
        refine=False,
        parallel=False,
    )

    assert len(result) == 2
    assert len(tracer.spans) >= 1
    matching = [entry for entry in tracer.spans if entry[0] == "graphrag.pipeline.run_batch"]
    assert len(matching) == 1
    span_name, attrs = matching[0]
    assert span_name == "graphrag.pipeline.run_batch"
    assert attrs["pipeline.domain"] == "legal"
    assert attrs["pipeline.data_source"] == "unit-test-batch"
    assert attrs["pipeline.refine"] is False
    assert attrs["pipeline.doc_count"] == 2
    assert attrs["pipeline.result_count"] == 2


def test_pipeline_run_batch_skips_otel_span_when_disabled(monkeypatch) -> None:
    monkeypatch.delenv("OTEL_ENABLED", raising=False)
    pipeline = _make_pipeline_with_mocks()
    tracer = _TracerRecorder()
    pipeline._otel_tracer = tracer
    pipeline._otel_enabled = False

    pipeline.run_batch(["Alice signed contract"], data_source="unit-test", refine=True)

    assert tracer.spans == []
