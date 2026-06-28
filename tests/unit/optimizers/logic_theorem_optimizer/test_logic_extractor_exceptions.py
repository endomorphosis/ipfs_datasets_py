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


def test_logic_extractor_defaults_to_codex_53_model() -> None:
    extractor = _build_extractor()

    assert extractor.model == "gpt-5.5"


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
    assert extractor.llm_call_count == 1


def test_query_llm_raises_when_mock_fallback_is_disabled() -> None:
    extractor = le.LogicExtractor(
        use_ipfs_accelerate=False,
        enable_formula_translation=False,
        enable_kg_integration=False,
        enable_rag_integration=False,
        allow_mock_fallback=False,
    )
    context = _build_context()

    class BrokenBackend:
        def generate(self, request):
            raise RuntimeError("backend down")

    extractor.backend = BrokenBackend()

    with pytest.raises(RuntimeError, match="mock fallback is disabled"):
        extractor._query_llm("prompt", context)


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
    context = le.LogicExtractionContext(
        data="The agency must make records promptly available to any person.",
        domain="legal",
    )

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
    assert context.extraction_mode == le.ExtractionMode.MODAL
    assert result.metrics["llm_call_count"] == 0


def test_legal_modal_extraction_can_use_spacy_profile_without_llm() -> None:
    extractor = _build_extractor()
    context = le.LogicExtractionContext(
        data="The agency must make records promptly available to any person.",
        domain="legal",
        config={"extraction_mode": "modal", "modal_profile": "spacy"},
        hints=["5 U.S.C. 552"],
    )

    result = extractor.extract(context)

    assert result.success is True
    assert result.statements
    assert result.metrics["llm_call_count"] == 0
    assert result.metrics["embedding_cosine_similarity"] == result.metrics["cosine_similarity"]
    assert result.metrics["deterministic_parser"] == "spacy_modal_codec_v1"
    assert result.metrics["spacy_token_count"] > 0
    assert result.statements[0].metadata["modal_family"] == "deontic"


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


def test_query_llm_redacts_sensitive_error_text_in_logs(caplog: pytest.LogCaptureFixture) -> None:
    extractor = _build_extractor()
    context = _build_context()

    class BrokenBackend:
        def generate(self, request):
            raise RuntimeError("api_key=sk-1234567890abcdef password=hunter2")

    extractor.backend = BrokenBackend()

    with caplog.at_level("WARNING"):
        response = extractor._query_llm("prompt", context)

    assert "Formula:" in response
    messages = " ".join(
        record.getMessage()
        for record in caplog.records
        if record.name == "ipfs_datasets_py.optimizers.logic_theorem_optimizer.logic_extractor"
    )
    assert "***REDACTED***" in messages
    assert "sk-1234567890abcdef" not in messages
    assert "hunter2" not in messages
