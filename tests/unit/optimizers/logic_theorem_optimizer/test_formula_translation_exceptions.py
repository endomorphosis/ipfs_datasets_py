"""Tests for typed exception handling in formula translation helpers."""

from __future__ import annotations

from types import SimpleNamespace

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.formula_translation import (
    CECFormulaTranslator,
    TDFOLFormulaTranslator,
)


def test_translate_to_tdfol_returns_failure_on_reasoner_error() -> None:
    translator = TDFOLFormulaTranslator()
    translator.reasoner_available = True
    translator.reasoner = SimpleNamespace(parse=lambda *_a, **_k: (_ for _ in ()).throw(ValueError("bad parse")))

    result = translator.translate_to_tdfol("All employees must complete training")

    assert result.success is False
    assert result.formula is None
    assert result.errors


def test_translate_from_tdfol_falls_back_to_string_on_nl_error() -> None:
    translator = TDFOLFormulaTranslator()
    translator.reasoner_available = True
    translator.reasoner = SimpleNamespace(
        nl_interface=SimpleNamespace(generate=lambda _f: (_ for _ in ()).throw(TypeError("no generator")))
    )

    rendered = translator.translate_from_tdfol({"f": "x"})

    assert rendered == "{'f': 'x'}"


def test_translate_to_cec_returns_failure_on_invalid_text_type() -> None:
    translator = CECFormulaTranslator()
    translator.cec_available = True

    result = translator.translate_to_cec(None)  # type: ignore[arg-type]

    assert result.success is False
    assert result.formula is None
    assert result.errors


def test_translate_to_tdfol_uses_common_resilience_wrapper(monkeypatch) -> None:
    translator = TDFOLFormulaTranslator()
    translator.reasoner_available = True
    translator.reasoner = SimpleNamespace(parse=lambda *_a, **_k: "F(x)")
    captured = {"service_name": None}

    def _fake_resilience(operation, policy, *, circuit_breaker, sleep_fn=None):
        captured["service_name"] = policy.service_name
        return operation()

    monkeypatch.setattr(
        "ipfs_datasets_py.optimizers.logic_theorem_optimizer.formula_translation.execute_with_resilience",
        _fake_resilience,
    )

    result = translator.translate_to_tdfol("All users must authenticate")

    assert result.success is True
    assert result.formula == "F(x)"
    assert captured["service_name"] == "tdfol_reasoner_parse"


def test_translate_from_tdfol_uses_common_resilience_wrapper(monkeypatch) -> None:
    translator = TDFOLFormulaTranslator()
    translator.reasoner_available = True
    translator.reasoner = SimpleNamespace(
        nl_interface=SimpleNamespace(generate=lambda _formula: "rendered")
    )
    captured = {"service_name": None}

    def _fake_resilience(operation, policy, *, circuit_breaker, sleep_fn=None):
        captured["service_name"] = policy.service_name
        return operation()

    monkeypatch.setattr(
        "ipfs_datasets_py.optimizers.logic_theorem_optimizer.formula_translation.execute_with_resilience",
        _fake_resilience,
    )

    rendered = translator.translate_from_tdfol({"f": "x"})

    assert rendered == "rendered"
    assert captured["service_name"] == "tdfol_reasoner_nl_generate"


def test_translate_to_tdfol_redacts_sensitive_error_text(caplog) -> None:
    translator = TDFOLFormulaTranslator()
    translator.reasoner_available = True
    translator.reasoner = SimpleNamespace(
        parse=lambda *_a, **_k: (_ for _ in ()).throw(
            ValueError("api_key=sk-1234567890abcdef password=hunter2")
        )
    )

    with caplog.at_level("ERROR"):
        result = translator.translate_to_tdfol("All employees must complete training")

    assert result.success is False
    assert result.errors
    assert "***REDACTED***" in result.errors[0]
    assert "sk-1234567890abcdef" not in result.errors[0]
    messages = " ".join(record.getMessage() for record in caplog.records)
    assert "***REDACTED***" in messages
    assert "hunter2" not in messages
