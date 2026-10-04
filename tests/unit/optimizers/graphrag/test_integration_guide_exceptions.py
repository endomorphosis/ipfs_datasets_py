"""Exception-path regression tests for graphrag.integration_guide."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

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


def test_extract_with_retry_redacts_sensitive_error_log(monkeypatch):
    workflow = BasicOntologyExtraction()
    workflow.logger = Mock()

    def _raise_value_error(_text):
        raise ValueError("invalid extraction input password=hunter2")

    monkeypatch.setattr(workflow, "extract_and_validate", _raise_value_error)
    result = workflow.extract_with_retry("text", max_attempts=1)

    assert result == {}
    workflow.logger.error.assert_called_once()
    assert "password=***REDACTED***" in workflow.logger.error.call_args.args[2]
    assert "hunter2" not in workflow.logger.error.call_args.args[2]


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


def test_complete_multilingual_pipeline_redacts_sensitive_typed_error(monkeypatch):
    workflow = AdvancedScenarios()

    def _raise_value_error(_config):
        raise ValueError("invalid configuration api_key=sk-secret123")

    monkeypatch.setattr(workflow.config_validator, "validate", _raise_value_error)
    result = workflow.complete_multilingual_pipeline("hello", config={})
    assert "api_key=***REDACTED***" in result["errors"][0]
    assert "sk-secret123" not in result["errors"][0]


def test_complete_multilingual_pipeline_propagates_base_exception(monkeypatch):
    workflow = AdvancedScenarios()

    def _raise_interrupt(_config):
        raise KeyboardInterrupt("stop")

    monkeypatch.setattr(workflow.config_validator, "validate", _raise_interrupt)
    with pytest.raises(KeyboardInterrupt):
        workflow.complete_multilingual_pipeline("hello", config={})
