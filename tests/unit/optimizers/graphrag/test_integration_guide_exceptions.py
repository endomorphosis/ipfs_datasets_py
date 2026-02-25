"""Exception-path regression tests for graphrag.integration_guide."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from ipfs_datasets_py.optimizers.graphrag.integration_guide import (
    AdvancedScenarios,
    BasicOntologyExtraction,
)


def test_extract_with_retry_returns_empty_on_typed_error(monkeypatch):
    workflow = BasicOntologyExtraction()
    workflow.logger = SimpleNamespace(error=lambda *_args, **_kwargs: None)

    def _raise_value_error(_text):
        raise ValueError("invalid extraction input")

    monkeypatch.setattr(workflow, "extract_and_validate", _raise_value_error)
    result = workflow.extract_with_retry("text", max_attempts=1)
    assert result == {}


def test_extract_with_retry_propagates_base_exception(monkeypatch):
    workflow = BasicOntologyExtraction()

    def _raise_interrupt(_text):
        raise KeyboardInterrupt("stop")

    monkeypatch.setattr(workflow, "extract_and_validate", _raise_interrupt)
    with pytest.raises(KeyboardInterrupt):
        workflow.extract_with_retry("text", max_attempts=1)


def test_complete_multilingual_pipeline_records_typed_error(monkeypatch):
    workflow = AdvancedScenarios()

    def _raise_value_error(_config):
        raise ValueError("invalid configuration")

    monkeypatch.setattr(workflow.config_validator, "validate", _raise_value_error)
    result = workflow.complete_multilingual_pipeline("hello", config={})
    assert "invalid configuration" in result["errors"]


def test_complete_multilingual_pipeline_propagates_base_exception(monkeypatch):
    workflow = AdvancedScenarios()

    def _raise_interrupt(_config):
        raise KeyboardInterrupt("stop")

    monkeypatch.setattr(workflow.config_validator, "validate", _raise_interrupt)
    with pytest.raises(KeyboardInterrupt):
        workflow.complete_multilingual_pipeline("hello", config={})
