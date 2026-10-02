"""Sunset clauses keep the duty-bearing instrument, action, and calendar date."""

from __future__ import annotations

from ipfs_datasets_py.logic.autoformal import AutoformalSession, compile_span
from ipfs_datasets_py.logic.deontic.formula_builder import build_deontic_formula_from_ir
from ipfs_datasets_py.logic.deontic.ir import LegalNormIR
from ipfs_datasets_py.logic.deontic.utils.deontic_parser import extract_normative_elements
from ipfs_datasets_py.logic.legal_ir.canonical_decompiler import decompile_rule
from ipfs_datasets_py.logic.legal_ir.canonical_contracts import CanonicalRule


_SUNSET_CASES = (
    (
        "The duty to file a report under subsection (c) shall terminate on March 15, 2031.",
        "duty",
        "file a report",
        "subsection (c)",
        "terminate",
        "2031",
        "15",
    ),
    (
        "Expiration .—The authority to collect a fee under paragraph (2) shall terminate on June 30, 2029.",
        "authority",
        "collect a fee",
        "paragraph (2)",
        "terminate",
        "2029",
        "30",
    ),
    (
        "The requirement to submit an inventory under subsection (b) shall expire on December 31, 2030.",
        "requirement",
        "submit an inventory",
        "subsection (b)",
        "expire",
        "2030",
        "31",
    ),
    (
        "(b) Sunset .—The requirement to provide a statement under subsection (c) shall terminate on January 12, 2033.",
        "requirement",
        "provide a statement",
        "subsection (c)",
        "terminate",
        "2033",
        "12",
    ),
)


def _first_norm(text: str) -> LegalNormIR:
    elements = extract_normative_elements(text)
    assert elements, f"parser returned no elements for {text!r}"
    return LegalNormIR.from_parser_element(elements[0])


def test_parenthetical_instrument_sunset_keeps_actor_action_and_date() -> None:
    for text, actor_head, complement, citation, verb, year, day in _SUNSET_CASES:
        norm = _first_norm(text)
        actor = " ".join(str(norm.actor or "").split()).lower()
        action = " ".join(str(norm.action or "").split()).lower()
        action_verb = " ".join(str(norm.action_verb or "").split()).lower()
        temporal = " ".join(
            str(item.get("normalized_text") or item.get("value") or "")
            for item in (norm.temporal_constraints or [])
            if isinstance(item, dict)
        ).lower()

        assert actor_head in actor
        assert complement in actor
        assert citation in actor
        assert verb in action or verb in action_verb
        assert year in temporal
        assert day in temporal
        assert "on " in temporal
        assert norm.modality in {"O", "shall"} or str(norm.norm_type).lower() in {
            "obligation",
            "duty",
        }
        formula = build_deontic_formula_from_ir(norm)
        assert formula
        assert "admitted" not in formula.lower()


def test_parenthetical_sunset_roundtrip_keeps_numeric_and_citation_surfaces() -> None:
    for text, actor_head, complement, citation, verb, year, day in _SUNSET_CASES:
        outcome = compile_span(AutoformalSession(), text, "sunset-parenthetical")
        rendered = str(outcome.get("decompiled") or "").lower()
        assert outcome.get("compiler_status") == "compiled"
        assert rendered
        assert actor_head in rendered
        assert complement.split()[0] in rendered
        assert citation.split()[0] in rendered
        assert verb in rendered
        assert year in rendered
        assert day in rendered
        assert outcome.get("admitted") is not True


def test_calendar_date_temporal_is_not_swallowed_by_action_atom() -> None:
    text = (
        "The requirement to publish a notice under subsection (d) shall terminate "
        "on April 1, 2032."
    )
    norm = _first_norm(text)
    action = " ".join(str(norm.action or "").split()).lower()
    temporal = " ".join(
        str(item.get("normalized_text") or item.get("value") or "")
        for item in (norm.temporal_constraints or [])
        if isinstance(item, dict)
    ).lower()
    assert "terminate" in action or str(norm.action_verb or "").lower() == "terminate"
    assert "2032" not in action
    assert "on april 1, 2032" in temporal
    formula = build_deontic_formula_from_ir(norm)
    assert "Terminate" in formula or "terminate" in formula.lower()
    assert "2032" in formula or "April" in formula or "april" in formula.lower()


def test_canonical_decompiler_renders_on_date_temporal_atom() -> None:
    sentence = decompile_rule(
        CanonicalRule(
            modality="O",
            actor="requirement_to_file_report",
            action="terminate",
            object="",
            conditions=(),
            exceptions=(),
            temporal=("on_april_1_2032",),
        )
    ).lower()
    assert "requirement" in sentence
    assert "terminate" in sentence
    assert "2032" in sentence
    assert "april" in sentence
