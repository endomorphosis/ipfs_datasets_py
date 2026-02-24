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
