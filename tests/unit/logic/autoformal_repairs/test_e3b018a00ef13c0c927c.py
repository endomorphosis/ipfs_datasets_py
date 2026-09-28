"""Copular passives keep the participle, nested cite path, and coordination partner."""

from __future__ import annotations

from ipfs_datasets_py.logic.autoformal import AutoformalSession, compile_span
from ipfs_datasets_py.logic.deontic.formula_builder import (
    _canonical_section_citation,
    build_deontic_formula_from_ir,
)
from ipfs_datasets_py.logic.deontic.ir import LegalNormIR
from ipfs_datasets_py.logic.deontic.utils.deontic_parser import extract_normative_elements
from ipfs_datasets_py.logic.legal_ir.canonical_decompiler import decompile_rule
from ipfs_datasets_py.logic.legal_ir.canonical_contracts import CanonicalRule


_COORDINATED_PASSIVE_CASES = (
    (
        "Subsection (a)(9)(B)(iv) of the Resolution shall be fulfilled in coordination with the Secretary of State.",
        "subsection (a)(9)(b)(iv)",
        "resolution",
        "fulfilled",
        "coordination",
        "secretary",
        "(a)(9)(b)(iv)",
    ),
    (
        "Paragraph (2)(C)(i) of the Compact shall be implemented in coordination with the Attorney General.",
        "paragraph (2)(c)(i)",
        "compact",
        "implemented",
        "coordination",
        "attorney",
        "(2)(c)(i)",
    ),
    (
        "Subsection (c)(1)(A) of the Plan shall be carried out in consultation with the Secretary of Defense.",
        "subsection (c)(1)(a)",
        "plan",
        "carried",
        "consultation",
        "defense",
        "(c)(1)(a)",
    ),
    (
        "The requirement in subsection (b)(4)(D)(ii) of the Order shall be satisfied in coordination with the Secretary.",
        "subsection (b)(4)(d)(ii)",
        "order",
        "satisfied",
        "coordination",
        "secretary",
        "(b)(4)(d)(ii)",
    ),
)


def _first_norm(text: str) -> LegalNormIR:
    elements = extract_normative_elements(text)
    assert elements, f"parser returned no elements for {text!r}"
    return LegalNormIR.from_parser_element(elements[0])


def _surfaces(norm: LegalNormIR) -> tuple[str, str, str, str]:
    actor = " ".join(str(norm.actor or "").split()).lower()
    action = " ".join(str(norm.action or "").split()).lower()
    action_verb = " ".join(str(norm.action_verb or "").split()).lower()
    action_object = " ".join(str(norm.action_object or "").split()).lower()
    return actor, action, action_verb, action_object


def test_copular_passive_keeps_participle_nested_cite_and_coordination() -> None:
    for text, cite, instrument, participle, manner, partner, nested in _COORDINATED_PASSIVE_CASES:
        norm = _first_norm(text)
        actor, action, action_verb, action_object = _surfaces(norm)
        xrefs = " ".join(
            str(item.get("value") or item.get("raw_text") or "")
            for item in (norm.cross_references or [])
            if isinstance(item, dict)
        ).lower()

        assert cite in actor
        assert instrument in actor
        assert nested in actor
        assert participle in action or participle in action_verb
        assert action_verb != "be"
        assert participle in action_verb
        assert manner in action or manner in action_object
        assert partner in action or partner in action_object
        assert nested in xrefs or nested in actor
        assert norm.modality in {"O", "shall"} or str(norm.norm_type).lower() in {
            "obligation",
            "duty",
        }
        formula = build_deontic_formula_from_ir(norm)
        assert formula
        assert participle in formula.lower()
        assert "admitted" not in formula.lower()


def test_copular_passive_roundtrip_keeps_nested_numeric_and_coordination_surfaces() -> None:
    for text, cite, instrument, participle, manner, partner, nested in _COORDINATED_PASSIVE_CASES:
        outcome = compile_span(AutoformalSession(), text, "copular-passive-coordination")
        rendered = str(outcome.get("decompiled") or "").lower()
        rule = outcome.get("rule") or {}
        assert outcome.get("compiler_status") == "compiled"
        assert outcome.get("roundtrip") is True
        assert rendered
        assert cite.split()[0] in rendered
        assert instrument in rendered
        assert participle in rendered
        assert manner in rendered
        assert partner in rendered
        assert nested in rendered
        action = " ".join(str(rule.get("action") or "").split()).lower()
        assert action != "be"
        assert participle in action
        assert outcome.get("admitted") is not True


def test_copular_passive_object_is_coordination_complement_not_participle() -> None:
    text = (
        "Subsection (d)(2)(B) of the Resolution shall be fulfilled in "
        "coordination with the Secretary of State."
    )
    norm = _first_norm(text)
    action_verb = " ".join(str(norm.action_verb or "").split()).lower()
    action_object = " ".join(str(norm.action_object or "").split()).lower()
    assert action_verb == "be fulfilled"
    assert action_object.startswith("in coordination with")
    assert "secretary" in action_object
    formula = build_deontic_formula_from_ir(norm)
    assert "Fulfilled" in formula or "fulfilled" in formula.lower()
    assert "coordination" in formula.lower() or "secretary" in formula.lower()


def test_canonical_decompiler_renders_copular_passive_without_duplicating_object() -> None:
    sentence = decompile_rule(
        CanonicalRule(
            modality="O",
            actor="subsection_(a)(9)(B)(iv)_of_the_resolution",
            action="be fulfilled",
            object="in coordination with the Secretary of State",
            conditions=(),
            exceptions=(),
            temporal=(),
        )
    ).lower()
    assert "subsection" in sentence
    assert "(a)(9)(b)(iv)" in sentence
    assert "be fulfilled" in sentence
    assert "coordination" in sentence
    assert "secretary" in sentence
    assert sentence.count("fulfilled") == 1


def test_canonical_decompiler_does_not_repeat_object_already_in_copular_action() -> None:
    sentence = decompile_rule(
        CanonicalRule(
            modality="O",
            actor="duty",
            action="be fulfilled in coordination with the secretary",
            object="in coordination with the secretary",
            conditions=(),
            exceptions=(),
            temporal=(),
        )
    ).lower()
    assert "duty" in sentence
    assert "be fulfilled" in sentence
    assert sentence.count("coordination") == 1
    assert "in coordination with the secretary in coordination with the secretary" not in sentence


def test_nested_parenthetical_citation_is_kept_as_a_formula_surface() -> None:
    citation = _canonical_section_citation(
        "Subsection (a)(9)(B)(iv) of the Resolution"
    )
    assert "(a)(9)(b)(iv)" in citation
    assert citation.startswith("subsection")
