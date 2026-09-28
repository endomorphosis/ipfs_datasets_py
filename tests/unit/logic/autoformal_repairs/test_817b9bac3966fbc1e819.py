"""Comparative ``when compared with`` stays on the duty. It is not ``if compared``."""

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
        "manner in which",
        "when compared with",
        "force structure",
    ),
    (
        "The inventory shall list the vehicles appropriate for the mission when "
        "compared with the current fleet.",
        "inventory",
        "list",
        "vehicles",
        "when compared with",
        "current fleet",
    ),
    (
        "The plan shall describe the capability appropriate for the threat when "
        "compared to the prior posture.",
        "plan",
        "describe",
        "capability",
        "when compared to",
        "prior posture",
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
            parts.append(str(item.get("normalized_text") or item.get("value") or item.get("raw_text") or ""))
        else:
            parts.append(str(item))
    return " ".join(parts).casefold()


def test_when_compared_stays_on_action_and_keeps_obligation() -> None:
    for text, actor_head, verb, object_head, compared, compared_object in _COMPARISON_CASES:
        elements = extract_normative_elements(text)
        assert len(elements) == 1
        norm = _first_norm(text)
        actor = " ".join(str(norm.actor or "").split()).lower()
        action = " ".join(str(norm.action or "").split()).lower()
        action_object = " ".join(str(norm.action_object or "").split()).lower()
        blob = f"{action} {action_object}"
        conditions = _condition_blob(norm)

        assert actor_head in actor
        assert verb in action or str(norm.action_verb or "").lower() == verb
        assert object_head in blob
        assert compared in blob
        assert compared_object in blob
        assert "if compared" not in blob
        assert "if compared" not in conditions
        assert compared not in conditions
        assert compared_object not in conditions
        assert norm.modality in {"O", "shall"} or str(norm.norm_type).lower() in {
            "obligation",
            "duty",
        }
        formula = build_deontic_formula_from_ir(norm)
        assert formula.startswith("O(") or "O(∀" in formula
        assert "Compared" in formula or "compared" in formula.lower()
        assert "admitted" not in formula.lower()


def test_when_compared_roundtrip_does_not_rewrite_to_if() -> None:
    for text, actor_head, verb, object_head, compared, compared_object in _COMPARISON_CASES:
        outcome = compile_span(AutoformalSession(), text, "when-compared")
        rendered = str(outcome.get("decompiled") or "").lower()
        assert outcome.get("compiler_status") == "compiled"
        assert rendered
        assert actor_head in rendered
        assert verb in rendered
        assert object_head.split()[0] in rendered
        assert "when compared" in rendered
        assert compared_object.split()[0] in rendered
        assert "if compared" not in rendered
        assert outcome.get("admitted") is not True
        assert outcome.get("formalized") is not True


def test_canonical_decompiler_renders_comparison_without_if_connector() -> None:
    sentence = decompile_rule(
        CanonicalRule(
            modality="O",
            actor="report",
            action="include",
            object="a description of the manner in which such modification will maintain a range",
            conditions=("compared with the current force structure",),
            exceptions=(),
            temporal=(),
        )
    ).lower()
    assert "report" in sentence
    assert "include" in sentence
    assert "when compared with the current force structure" in sentence
    assert "if compared" not in sentence
    assert "if when compared" not in sentence


def test_canonical_decompiler_does_not_repeat_comparison_already_in_object() -> None:
    sentence = decompile_rule(
        CanonicalRule(
            modality="O",
            actor="inventory",
            action="list",
            object="vehicles appropriate for the mission when compared with the current fleet",
            conditions=("compared with the current fleet",),
            exceptions=(),
            temporal=(),
        )
    ).lower()
    assert "inventory" in sentence
    assert "when compared with the current fleet" in sentence
    assert sentence.count("compared") == 1
    assert "if compared" not in sentence


def test_if_compared_atom_surface_is_when_compared() -> None:
    sentence = decompile_rule(
        CanonicalRule(
            modality="O",
            actor="agency",
            action="publish",
            object="the assessment",
            conditions=("if_compared",),
            exceptions=(),
            temporal=(),
        )
    ).lower()
    assert "when compared" in sentence
    assert "if compared" not in sentence
    assert "if when compared" not in sentence


def test_ordinary_when_condition_still_extracts() -> None:
    text = "The officer shall file a report when the board requests it."
    norm = _first_norm(text)
    action = " ".join(str(norm.action or "").split()).lower()
    conditions = _condition_blob(norm)
    assert "file" in action or str(norm.action_verb or "").lower() == "file"
    assert "board requests" in conditions
    assert "when compared" not in conditions
    formula = build_deontic_formula_from_ir(norm)
    assert formula
    assert "Board" in formula or "board" in formula.lower()


def test_if_condition_is_kept_when_comparison_qualifies_the_action() -> None:
    text = (
        "If funding is available, the agency shall publish the inventory "
        "when compared with the prior year."
    )
    norm = _first_norm(text)
    action = " ".join(str(norm.action or "").split()).lower()
    action_object = " ".join(str(norm.action_object or "").split()).lower()
    blob = f"{action} {action_object}"
    conditions = _condition_blob(norm)
    assert "publish" in action or str(norm.action_verb or "").lower() == "publish"
    assert "when compared with" in blob
    assert "prior year" in blob
    assert "funding is available" in conditions
    assert "if compared" not in conditions
    formula = build_deontic_formula_from_ir(norm)
    assert "Funding" in formula or "funding" in formula.lower()
    outcome = compile_span(AutoformalSession(), text, "if-and-when-compared")
    rendered = str(outcome.get("decompiled") or "").lower()
    assert "when compared" in rendered
    assert "if compared" not in rendered
    assert "funding" in rendered
    assert outcome.get("admitted") is not True

