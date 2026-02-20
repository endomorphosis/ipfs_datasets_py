"""Tests for LLM fallback extraction in OntologyGenerator (batch 33).

Covers: fallback triggered when low confidence + llm_backend set,
fallback skipped when threshold=0, fallback skipped when no llm_backend,
fallback uses rule-based result when LLM confidence is worse,
and LLM exception swallowing.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

import pytest

from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
    DataType,
    Entity,
    EntityExtractionResult,
    ExtractionConfig,
    ExtractionStrategy,
    OntologyGenerationContext,
    OntologyGenerator,
)


def _make_extraction_result(confidence: float, n_entities: int = 2) -> EntityExtractionResult:
    entities = [
        Entity(id=f"e{i}", type="Person", text=f"Person{i}", confidence=confidence)
        for i in range(n_entities)
    ]
    return EntityExtractionResult(
        entities=entities, relationships=[], confidence=confidence, metadata={}
    )


def _make_context(threshold: float = 0.5) -> OntologyGenerationContext:
    return OntologyGenerationContext(
        data_source="test",
        data_type=DataType.TEXT,
        domain="general",
        extraction_strategy=ExtractionStrategy.RULE_BASED,
        config=ExtractionConfig(llm_fallback_threshold=threshold),
    )


class TestLLMFallbackTriggered:
    """Fallback fires when rule confidence < threshold AND llm_backend set."""

    def test_fallback_called_on_low_confidence(self):
        llm_backend = MagicMock()
        gen = OntologyGenerator(use_ipfs_accelerate=False, llm_backend=llm_backend)
        rule_result = _make_extraction_result(confidence=0.3)
        llm_result = _make_extraction_result(confidence=0.8)
        ctx = _make_context(threshold=0.5)

        with patch.object(gen, "_extract_rule_based", return_value=rule_result), \
             patch.object(gen, "_extract_llm_based", return_value=llm_result) as mock_llm:
            result = gen.extract_entities("some text", ctx)

        mock_llm.assert_called_once()
        assert result.confidence == 0.8

    def test_fallback_returns_rule_result_if_llm_worse(self):
        """If LLM result has lower confidence, keep rule-based result."""
        llm_backend = MagicMock()
        gen = OntologyGenerator(use_ipfs_accelerate=False, llm_backend=llm_backend)
        rule_result = _make_extraction_result(confidence=0.3)
        llm_result = _make_extraction_result(confidence=0.1)  # worse
        ctx = _make_context(threshold=0.5)

        with patch.object(gen, "_extract_rule_based", return_value=rule_result), \
             patch.object(gen, "_extract_llm_based", return_value=llm_result):
            result = gen.extract_entities("some text", ctx)

        assert result.confidence == 0.3

    def test_fallback_exception_swallowed(self):
        """LLM fallback exceptions must not propagate; return rule result instead."""
        llm_backend = MagicMock()
        gen = OntologyGenerator(use_ipfs_accelerate=False, llm_backend=llm_backend)
        rule_result = _make_extraction_result(confidence=0.2)
        ctx = _make_context(threshold=0.5)

        with patch.object(gen, "_extract_rule_based", return_value=rule_result), \
             patch.object(gen, "_extract_llm_based", side_effect=RuntimeError("LLM unavailable")):
            result = gen.extract_entities("some text", ctx)

        assert result.confidence == 0.2


class TestLLMFallbackSkipped:
    """Fallback should NOT fire in certain conditions."""

    def test_no_fallback_when_threshold_zero(self):
        """Default llm_fallback_threshold=0.0 must disable fallback entirely."""
        llm_backend = MagicMock()
        gen = OntologyGenerator(use_ipfs_accelerate=False, llm_backend=llm_backend)
        rule_result = _make_extraction_result(confidence=0.1)  # very low
        ctx = _make_context(threshold=0.0)

        with patch.object(gen, "_extract_rule_based", return_value=rule_result), \
             patch.object(gen, "_extract_llm_based") as mock_llm:
            result = gen.extract_entities("some text", ctx)

        mock_llm.assert_not_called()
        assert result is rule_result

    def test_no_fallback_without_llm_backend(self):
        """No llm_backend → fallback must never fire."""
        gen = OntologyGenerator(use_ipfs_accelerate=False, llm_backend=None)
        rule_result = _make_extraction_result(confidence=0.1)
        ctx = _make_context(threshold=0.5)

        with patch.object(gen, "_extract_rule_based", return_value=rule_result), \
             patch.object(gen, "_extract_llm_based") as mock_llm:
            result = gen.extract_entities("some text", ctx)

        mock_llm.assert_not_called()
        assert result is rule_result

    def test_no_fallback_when_confidence_above_threshold(self):
        """High rule-based confidence → skip fallback even if llm_backend set."""
        llm_backend = MagicMock()
        gen = OntologyGenerator(use_ipfs_accelerate=False, llm_backend=llm_backend)
        rule_result = _make_extraction_result(confidence=0.9)
        ctx = _make_context(threshold=0.5)

        with patch.object(gen, "_extract_rule_based", return_value=rule_result), \
             patch.object(gen, "_extract_llm_based") as mock_llm:
            result = gen.extract_entities("some text", ctx)

        mock_llm.assert_not_called()
        assert result is rule_result


class TestExtractionConfigLLMFallbackField:
    def test_default_fallback_threshold_is_zero(self):
        cfg = ExtractionConfig()
        assert cfg.llm_fallback_threshold == 0.0

    def test_custom_fallback_threshold_stored(self):
        cfg = ExtractionConfig(llm_fallback_threshold=0.4)
        assert cfg.llm_fallback_threshold == 0.4

    def test_to_dict_includes_threshold(self):
        cfg = ExtractionConfig(llm_fallback_threshold=0.6)
        d = cfg.to_dict()
        assert d["llm_fallback_threshold"] == 0.6

    def test_from_dict_reads_threshold(self):
        cfg = ExtractionConfig.from_dict({"llm_fallback_threshold": 0.7})
        assert cfg.llm_fallback_threshold == 0.7

    def test_from_dict_default_is_zero(self):
        cfg = ExtractionConfig.from_dict({})
        assert cfg.llm_fallback_threshold == 0.0
