"""Tests for typed exception handling in logic extractor paths."""

from __future__ import annotations

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import logic_extractor as le


def _build_extractor() -> le.LogicExtractor:
    return le.LogicExtractor(
        use_ipfs_accelerate=False,
        enable_formula_translation=False,
        enable_kg_integration=False,
        enable_rag_integration=False,
    )


def _build_context() -> le.LogicExtractionContext:
    return le.LogicExtractionContext(
        data="All users must authenticate",
        domain="security",
        config={"extraction_mode": "fol"},
    )


def test_extract_handles_typed_value_error(monkeypatch: pytest.MonkeyPatch) -> None:
    extractor = _build_extractor()
    context = _build_context()
    monkeypatch.setattr(extractor, "_build_extraction_prompt", lambda ctx: (_ for _ in ()).throw(ValueError("bad prompt")))

    result = extractor.extract(context)

    assert result.success is False
    assert result.errors == ["bad prompt"]


def test_extract_does_not_swallow_keyboard_interrupt(monkeypatch: pytest.MonkeyPatch) -> None:
    extractor = _build_extractor()
    context = _build_context()
    monkeypatch.setattr(
        extractor,
        "_build_extraction_prompt",
        lambda ctx: (_ for _ in ()).throw(KeyboardInterrupt()),
    )

    with pytest.raises(KeyboardInterrupt):
        extractor.extract(context)


def test_query_llm_handles_typed_runtime_error_with_fallback() -> None:
    extractor = _build_extractor()
    context = _build_context()

    class BrokenBackend:
        def generate(self, request):
            raise RuntimeError("backend down")

    extractor.backend = BrokenBackend()
    response = extractor._query_llm("prompt", context)

    assert "Formula:" in response


def test_query_llm_does_not_swallow_keyboard_interrupt() -> None:
    extractor = _build_extractor()
    context = _build_context()

    class BrokenBackend:
        def generate(self, request):
            raise KeyboardInterrupt()

    extractor.backend = BrokenBackend()

    with pytest.raises(KeyboardInterrupt):
        extractor._query_llm("prompt", context)


def test_extract_auto_mode_updates_config_instead_of_property_assignment() -> None:
    extractor = _build_extractor()
    context = le.LogicExtractionContext(data="Contract parties must pay", domain="legal")

    class SimpleBackend:
        def generate(self, request):
            return type(
                "Resp",
                (),
                {"backend": "test", "text": "Formula: P(a)\nExplanation: test\nConfidence: 0.9"},
            )()

    extractor.backend = SimpleBackend()
    result = extractor.extract(context)

    assert result.success is True
    assert context.extraction_mode == le.ExtractionMode.TDFOL


def test_query_llm_uses_common_backend_resilience_wrapper(monkeypatch: pytest.MonkeyPatch) -> None:
    extractor = _build_extractor()
    context = _build_context()
    captured = {"service_name": None, "breaker_name": None}

    class SimpleBackend:
        def generate(self, request):
            return type("Resp", (), {"backend": "test", "text": "Formula: P(a)\nConfidence: 0.9"})()

    def _fake_execute_with_resilience(operation, policy, *, circuit_breaker, sleep_fn=None):
        captured["service_name"] = policy.service_name
        captured["breaker_name"] = getattr(circuit_breaker, "name", None)
        return operation()

    monkeypatch.setattr(
        "ipfs_datasets_py.optimizers.logic_theorem_optimizer.logic_extractor.execute_with_resilience",
        _fake_execute_with_resilience,
    )
    extractor.backend = SimpleBackend()

    response = extractor._query_llm("prompt", context)

    assert "Formula:" in response
    assert captured["service_name"] == "logic_extractor_llm"
    assert captured["breaker_name"] == "logic_extractor_llm"
