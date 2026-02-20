from __future__ import annotations

import csv


def test_identify_patterns_computes_common_types_and_averages() -> None:
    from ipfs_datasets_py.optimizers.graphrag.ontology_optimizer import OntologyOptimizer

    optimizer = OntologyOptimizer()

    ontologies = [
        {
            "entities": [
                {"id": "e1", "type": "Person", "properties": {"age": 30}},
                {"id": "e2", "type": "Person", "properties": {"age": 31}},
            ],
            "relationships": [
                {"id": "r1", "source_id": "e1", "target_id": "e2", "type": "knows"}
            ],
        },
        {
            "entities": [
                {"id": "e3", "type": "Company", "properties": {"name": "Acme"}},
            ],
            "relationships": [],
        },
    ]

    patterns = optimizer.identify_patterns(ontologies)

    assert isinstance(patterns, dict)
    assert patterns.get("sample_size") == 2

    assert patterns.get("avg_entity_count") == 1.5
    assert patterns.get("avg_relationship_count") == 0.5

    common_entity_types = patterns.get("common_entity_types")
    assert isinstance(common_entity_types, list)
    assert set(common_entity_types) >= {"Person", "Company"}

    common_relationship_types = patterns.get("common_relationship_types")
    assert isinstance(common_relationship_types, list)
    assert "knows" in common_relationship_types

    common_properties = patterns.get("common_properties")
    assert isinstance(common_properties, list)
    assert set(common_properties) >= {"age", "name"}


def test_ontology_optimizer_tracing_safe_when_dependency_missing(monkeypatch) -> None:
    from ipfs_datasets_py.optimizers.graphrag import ontology_optimizer as oo

    monkeypatch.setattr(oo, "HAVE_OPENTELEMETRY", False, raising=True)
    monkeypatch.setattr(oo, "trace", None, raising=True)

    optimizer = oo.OntologyOptimizer(enable_tracing=True)
    report = optimizer.analyze_batch([])

    assert report.trend == "insufficient_data"


def test_ontology_optimizer_emits_trace_attributes_with_fake_tracer(monkeypatch) -> None:
    from ipfs_datasets_py.optimizers.graphrag import ontology_optimizer as oo

    captured = []

    class _FakeSpan:
        def __init__(self):
            self.attrs = {}

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            captured.append(self.attrs)

        def set_attribute(self, key, value):
            self.attrs[key] = value

    class _FakeTracer:
        def start_as_current_span(self, _name):
            return _FakeSpan()

    class _FakeTraceModule:
        @staticmethod
        def get_tracer(_name):
            return _FakeTracer()

    monkeypatch.setattr(oo, "HAVE_OPENTELEMETRY", True, raising=True)
    monkeypatch.setattr(oo, "trace", _FakeTraceModule(), raising=True)

    optimizer = oo.OntologyOptimizer(enable_tracing=True)
    optimizer.analyze_batch([])

    assert captured
    assert any("duration_ms" in span for span in captured)
    assert any(span.get("status") == "insufficient_data" for span in captured)


def test_ontology_optimizer_export_learning_curve_csv_in_memory() -> None:
    from ipfs_datasets_py.optimizers.graphrag.ontology_optimizer import OntologyOptimizer, OptimizationReport

    optimizer = OntologyOptimizer()
    optimizer._history.append(
        OptimizationReport(
            average_score=0.65,
            trend="baseline",
            recommendations=["r1"],
            improvement_rate=0.0,
            metadata={"num_sessions": 2},
        )
    )
    optimizer._history.append(
        OptimizationReport(
            average_score=0.72,
            trend="improving",
            recommendations=["r1", "r2"],
            improvement_rate=0.07,
            metadata={"num_sessions": 3},
        )
    )

    csv_text = optimizer.export_learning_curve_csv()
    assert csv_text is not None

    rows = list(csv.DictReader(csv_text.splitlines()))
    assert len(rows) == 2
    assert rows[0]["batch_index"] == "1"
    assert rows[1]["trend"] == "improving"


def test_ontology_optimizer_export_learning_curve_csv_to_file(tmp_path) -> None:
    from ipfs_datasets_py.optimizers.graphrag.ontology_optimizer import OntologyOptimizer, OptimizationReport

    optimizer = OntologyOptimizer()
    optimizer._history.append(
        OptimizationReport(
            average_score=0.8,
            trend="stable",
            recommendations=[],
            metadata={"num_sessions": 1},
        )
    )

    out_path = tmp_path / "learning_curve.csv"
    result = optimizer.export_learning_curve_csv(str(out_path))

    assert result is None
    assert out_path.exists()
    content = out_path.read_text()
    assert "batch_index" in content
    assert "average_score" in content
