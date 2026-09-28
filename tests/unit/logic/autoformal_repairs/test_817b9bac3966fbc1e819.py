"""Comparison qualifiers stay on the description; they are not if-conditions."""

from __future__ import annotations

from ipfs_datasets_py.logic.autoformal import AutoformalSession, compile_span
from ipfs_datasets_py.logic.deontic.formula_builder import build_deontic_formula_from_ir
from ipfs_datasets_py.logic.deontic.ir import LegalNormIR
from ipfs_datasets_py.logic.deontic.utils.deontic_parser import extract_normative_elements
from ipfs_datasets_py.logic.legal_ir.canonical_contracts import CanonicalRule
from ipfs_datasets_py.logic.legal_ir.canonical_decompiler import decompile_rule


_COMPARISON_CASES = (
    (
        "The report shall include a description of the manner in which such "
        "modification will maintain for the United States a range of strategic "
        "nuclear weapons delivery systems appropriate for the current and "
        "anticipated threats faced by the United States when compared with the "
        "current force structure of strategic nuclear weapons delivery systems.",
        "report",
        "include",
        "when compared with",
        "force structure",
    ),
    (
        "The assessment shall describe the manner in which the revision will "
        "preserve a range of delivery systems appropriate for the anticipated "
        "threats when compared to the current force structure.",
        "assessment",
        "describe",
        "when compared to",
        "force structure",
    ),
    (
        "The inventory shall state the range of systems appropriate for current "
        "threats when compared against the existing force structure.",
        "inventory",
        "state",
        "when compared against",
        "force structure",
    ),
)


def _first_norm(text: str) -> LegalNormIR:
    elements = extract_normative_elements(text)
    assert elements, f"parser returned no elements for {text!r}"
    return LegalNormIR.from_parser_element(elements[0])


def _condition_blob(norm: LegalNormIR) -> str:
    parts: list[str] = []
    for item in norm.conditions or []:
        if isinstance(item, dict):
            parts.append(
                str(
                    item.get("normalized_text")
                    or item.get("raw_text")
                    or item.get("value")
                    or ""
                )
            )
        else:
            parts.append(str(item))
    return " ".join(parts).lower()


def test_comparison_qualifier_stays_on_action_not_as_if_condition() -> None:
    for text, actor_head, verb, comparison, complement in _COMPARISON_CASES:
        elements = extract_normative_elements(text)
        assert elements, f"parser returned no elements for {text!r}"
        element = elements[0]
        parser_action = " ".join(
            str(part) for part in (element.get("action") or [])
        ).lower()
        parser_conditions = " ".join(
            str(item.get("normalized_text") or item.get("raw_text") or item)
            if isinstance(item, dict)
            else str(item)
            for item in (element.get("conditions") or [])
        ).lower()
        assert comparison in parser_action
        assert complement in parser_action
        assert "compared" not in parser_conditions

        norm = LegalNormIR.from_parser_element(element)
        actor = " ".join(str(norm.actor or "").split()).lower()
        action = " ".join(str(norm.action or "").split()).lower()
        conditions = _condition_blob(norm)

        assert actor_head in actor
        assert verb in action or str(norm.action_verb or "").lower() == verb
        assert comparison in action
        assert complement in action
        assert "if compared" not in conditions
        assert norm.modality in {"O", "shall"} or str(norm.norm_type).lower() in {
            "obligation",
            "duty",
        }
        formula = build_deontic_formula_from_ir(norm)
        assert formula
        assert "admitted" not in formula.lower()
        antecedent, _, _consequent = formula.partition("→")
        assert "Compared" not in antecedent


def test_governing_when_condition_is_still_extracted() -> None:
    text = "The secretary shall publish a notice when the inventory is complete."
    norm = _first_norm(text)
    action = " ".join(str(norm.action or "").split()).lower()
    conditions = _condition_blob(norm)
    assert "publish" in action
    assert "inventory is complete" in conditions
    assert "when compared" not in action


def test_comparison_roundtrip_renders_when_compared_not_if_compared() -> None:
    for text, actor_head, verb, comparison, complement in _COMPARISON_CASES:
        outcome = compile_span(AutoformalSession(), text, "comparison-qualifier")
        rendered = str(outcome.get("decompiled") or "").lower()
        assert outcome.get("compiler_status") == "compiled"
        assert rendered
        assert actor_head in rendered
        assert verb in rendered
        assert comparison in rendered
        assert complement in rendered
        assert "if compared" not in rendered
        assert outcome.get("admitted") is not True


def test_canonical_decompiler_renders_comparison_with_when() -> None:
    sentence = decompile_rule(
        CanonicalRule(
            modality="O",
            actor="report",
            action="include",
            object="a description of the manner in which the modification will maintain a range of systems",
            conditions=("compared with the current force structure",),
            exceptions=(),
            temporal=(),
        )
    ).lower()
    assert "report" in sentence
    assert "include" in sentence
    assert "when compared with the current force structure" in sentence
    assert "if compared" not in sentence


def test_canonical_decompiler_does_not_repeat_comparison_already_in_object() -> None:
    sentence = decompile_rule(
        CanonicalRule(
            modality="O",
            actor="report",
            action="include",
            object="a description when compared with the current force structure",
            conditions=("compared with the current force structure",),
            exceptions=(),
            temporal=(),
        )
    ).lower()
    assert "when compared with the current force structure" in sentence
    assert sentence.count("compared") == 1
    assert "if compared" not in sentence
