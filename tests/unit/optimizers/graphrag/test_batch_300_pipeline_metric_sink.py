"""Tests for OntologyPipeline metric sink integration."""

from __future__ import annotations

from typing import Any, Dict, List

from ipfs_datasets_py.optimizers.graphrag.ontology_pipeline import OntologyPipeline


class _RecordingMetricSink:
    def __init__(self) -> None:
        self.calls: List[Dict[str, Any]] = []

    def emit_run_metrics(self, metrics: Dict[str, Any]) -> None:
        self.calls.append(metrics)


def test_pipeline_emits_metrics_to_sink_after_run() -> None:
    sink = _RecordingMetricSink()
    pipeline = OntologyPipeline(domain="general", metric_sink=sink)

    pipeline.run("Alice works at Acme Corp.", data_source="unit-test", refine=False)

    assert len(sink.calls) == 1
    payload = sink.calls[0]
    assert payload["domain"] == "general"
    assert payload["data_source"] == "unit-test"
    assert isinstance(payload["score"], float)
    assert isinstance(payload["entity_count"], int)
    assert isinstance(payload["relationship_count"], int)
    assert isinstance(payload["actions_count"], int)
    assert isinstance(payload["stage_durations_s"], dict)
    assert "extracting" in payload["stage_durations_s"]
