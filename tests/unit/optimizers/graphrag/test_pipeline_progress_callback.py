"""Tests for OntologyPipeline.run() progress_callback parameter.

Validates that the progress callback is invoked correctly at each pipeline
stage, that it receives the expected keys, and that callback exceptions are
silently suppressed.
"""
from __future__ import annotations

from ipfs_datasets_py.optimizers.graphrag.ontology_pipeline import OntologyPipeline


def test_progress_callback_called_on_run():
    """
    GIVEN: A pipeline with a progress callback
    WHEN: run() is called
    THEN: The callback is invoked at least once
    """
    events = []

    def _cb(info):
        events.append(info)

    pipeline = OntologyPipeline(domain="general", use_llm=False, max_rounds=1)
    pipeline.run(
        "Alice works at Acme Corp. Bob manages the team.",
        data_source="test",
        refine=False,
        progress_callback=_cb,
    )

    assert len(events) > 0


def test_progress_callback_has_required_keys():
    """
    GIVEN: A pipeline with a progress callback
    WHEN: run() is called
    THEN: Each callback invocation includes 'stage', 'step', and 'total_steps'
    """
    events = []

    def _cb(info):
        events.append(info)

    pipeline = OntologyPipeline(domain="general", use_llm=False, max_rounds=1)
    pipeline.run(
        "Alice works at Acme Corp.",
        data_source="test",
        refine=False,
        progress_callback=_cb,
    )

    for event in events:
        assert "stage" in event, f"Missing 'stage' key in {event}"
        assert "step" in event, f"Missing 'step' key in {event}"
        assert "total_steps" in event, f"Missing 'total_steps' key in {event}"
        assert isinstance(event["step"], int)
        assert isinstance(event["total_steps"], int)
        assert 1 <= event["step"] <= event["total_steps"]


def test_progress_callback_stages_without_refine():
    """
    GIVEN: A pipeline with refine=False
    WHEN: run() is called with a progress callback
    THEN: 'extracting' and 'extracted' stages are present
    """
    stages = []

    def _cb(info):
        stages.append(info["stage"])

    pipeline = OntologyPipeline(domain="general", use_llm=False, max_rounds=1)
    pipeline.run(
        "Alice works at Acme Corp.",
        data_source="test",
        refine=False,
        progress_callback=_cb,
    )

    assert "extracting" in stages
    assert "extracted" in stages


def test_progress_callback_total_steps_no_refine():
    """
    GIVEN: A pipeline with refine=False
    WHEN: run() is called
    THEN: total_steps is 3
    """
    events = []

    def _cb(info):
        events.append(info)

    pipeline = OntologyPipeline(domain="general", use_llm=False, max_rounds=1)
    pipeline.run(
        "Test data.",
        data_source="test",
        refine=False,
        progress_callback=_cb,
    )

    assert all(e["total_steps"] == 3 for e in events)


def test_progress_callback_total_steps_with_refine():
    """
    GIVEN: A pipeline with refine=True
    WHEN: run() is called
    THEN: total_steps is 4
    """
    events = []

    def _cb(info):
        events.append(info)

    pipeline = OntologyPipeline(domain="general", use_llm=False, max_rounds=1)
    pipeline.run(
        "Test data.",
        data_source="test",
        refine=True,
        progress_callback=_cb,
    )

    assert all(e["total_steps"] == 4 for e in events)


def test_progress_callback_none_does_not_raise():
    """
    GIVEN: A pipeline with no callback (None)
    WHEN: run() is called
    THEN: Pipeline runs without errors
    """
    pipeline = OntologyPipeline(domain="general", use_llm=False, max_rounds=1)
    result = pipeline.run(
        "Test data.",
        data_source="test",
        refine=False,
        progress_callback=None,
    )
    assert result is not None


def test_progress_callback_exception_does_not_interrupt():
    """
    GIVEN: A progress callback that raises an exception
    WHEN: run() is called
    THEN: The pipeline completes successfully despite the callback error
    """
    call_count = [0]

    def _bad_cb(info):
        call_count[0] += 1
        raise RuntimeError("Callback failure!")

    pipeline = OntologyPipeline(domain="general", use_llm=False, max_rounds=1)
    result = pipeline.run(
        "Alice works at Acme Corp.",
        data_source="test",
        refine=False,
        progress_callback=_bad_cb,
    )

    # Pipeline should complete even though callback raised
    assert result is not None
    # Callback should have been attempted
    assert call_count[0] > 0
