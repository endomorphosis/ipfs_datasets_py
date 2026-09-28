"""Instrument-fulfillment duties keep nested citations and coordination partners."""

from __future__ import annotations

from ipfs_datasets_py.logic.autoformal import AutoformalSession, compile_span
from ipfs_datasets_py.logic.deontic.formula_builder import build_deontic_formula_from_ir
from ipfs_datasets_py.logic.deontic.ir import LegalNormIR
from ipfs_datasets_py.logic.deontic.utils.deontic_parser import extract_normative_elements
from ipfs_datasets_py.logic.legal_ir.canonical_decompiler import decompile_rule
from ipfs_datasets_py.logic.legal_ir.canonical_contracts import CanonicalRule


_COORDINATED_FULFILLMENT_CASES = (
    (
        "Subsection (a)(9)(B)(iv) of the Resolution shall be fulfilled in coordination with the Secretary of State.",
        "subsection",
        "(a)(9)(B)(iv)",
        "9",
        "resolution",
        "fulfill",
        "coordination",
        "secretary",
    ),
    (
        "Paragraph (2)(C)(i) of the compact shall be carried out in consultation with the Attorney General.",
        "paragraph",
        "(2)(C)(i)",
        "2",
        "compact",
        "carried",
        "consultation",
        "attorney",
    ),
    (
        "Clause (iii) of the ordinance shall be implemented in conjunction with the Commission.",
        "clause",
        "(iii)",
        "",
        "ordinance",
        "implement",
        "conjunction",
        "commission",
    ),
    (
        "Subparagraph (B)(iv) of the statute shall be completed in concert with the Director.",
        "subparagraph",
        "(B)(iv)",
        "",
        "statute",
        "complete",
        "concert",
        "director",
    ),
)


def _first_norm(text: str) -> LegalNormIR:
    elements = extract_normative_elements(text)
    assert elements, f"parser returned no elements for {text!r}"
    return LegalNormIR.from_parser_element(elements[0])


def _cross_reference_blob(norm: LegalNormIR) -> str:
    parts: list[str] = []
    for item in list(norm.cross_references or []):
        if isinstance(item, dict):
            parts.extend(str(item.get(key) or "") for key in ("type", "value", "raw_text", "normalized_text"))
        else:
            parts.append(str(item))
    return " ".join(parts).lower()


def test_nested_instrument_citation_stays_on_the_duty_bearer() -> None:
    for text, unit, path, numeral, instrument, verb, manner, partner in _COORDINATED_FULFILLMENT_CASES:
        norm = _first_norm(text)
        actor = " ".join(str(norm.actor or "").split()).lower()
        action = " ".join(str(norm.action or "").split()).lower()
        action_verb = " ".join(str(norm.action_verb or "").split()).lower()
        action_object = " ".join(str(norm.action_object or "").split()).lower()
        refs = _cross_reference_blob(norm)

        assert unit in actor
        assert path.lower() in actor
        assert instrument in actor
        assert verb in action or verb in action_verb
        assert manner in action or manner in action_object
        assert partner in action or partner in action_object
        assert unit in refs
        assert path.lower() in actor or path.lower() in refs
        if numeral:
            assert numeral in actor
            assert numeral in refs or numeral in actor
        assert "be" in action_verb
        assert action_verb != "be"
        assert norm.modality in {"O", "shall"} or str(norm.norm_type).lower() in {
            "obligation",
            "duty",
        }
        formula = build_deontic_formula_from_ir(norm)
        assert formula
        assert "admitted" not in formula.lower()
        assert verb[:5] in formula.lower() or verb in formula.lower()
        assert manner in formula.lower()
        assert partner in formula.lower()
        if numeral:
            assert numeral in formula


def test_coordinated_fulfillment_roundtrip_keeps_citation_and_partner() -> None:
    for text, unit, path, numeral, instrument, verb, manner, partner in _COORDINATED_FULFILLMENT_CASES:
        outcome = compile_span(AutoformalSession(), text, "instrument-fulfillment")
        rendered = str(outcome.get("decompiled") or "").lower()
        assert outcome.get("compiler_status") == "compiled"
        assert rendered
        assert unit in rendered
        assert path.lower() in rendered
        assert instrument in rendered
        assert verb in rendered or "fulfill" in rendered or "carried" in rendered
        assert manner in rendered
        assert partner in rendered
        if numeral:
            assert numeral in rendered
        assert outcome.get("admitted") is not True
        assert outcome.get("roundtrip") is True


def test_copular_passive_action_atom_keeps_participle_and_manner() -> None:
    text = (
        "Subsection (c)(1)(A) of the Resolution shall be fulfilled "
        "in coordination with the Secretary of Defense."
    )
    norm = _first_norm(text)
    action = " ".join(str(norm.action or "").split()).lower()
    action_verb = " ".join(str(norm.action_verb or "").split()).lower()
    action_object = " ".join(str(norm.action_object or "").split()).lower()
    assert "be fulfilled" in action_verb
    assert "coordination" in action or "coordination" in action_object
    assert "secretary" in action or "secretary" in action_object
    assert "fulfilled" not in action_object.split()[:1]
    formula = build_deontic_formula_from_ir(norm)
    assert "be fulfilled" not in formula.lower()
    assert "fulfill" in formula.lower()
    assert "coordination" in formula.lower()
    assert "secretary" in formula.lower()


def test_canonical_decompiler_renders_copular_passive_and_coordination() -> None:
    sentence = decompile_rule(
        CanonicalRule(
            modality="O",
            actor="subsection (a)(9)(B)(iv) of the resolution",
            action="be fulfilled",
            object="in coordination with the secretary of state",
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


def test_canonical_decompiler_does_not_repeat_manner_already_in_action() -> None:
    sentence = decompile_rule(
        CanonicalRule(
            modality="O",
            actor="paragraph (2)(c)(i) of the compact",
            action="be carried out in consultation with the attorney general",
            object="in consultation with the attorney general",
            conditions=(),
            exceptions=(),
            temporal=(),
        )
    ).lower()
    assert "paragraph" in sentence
    assert "carried out" in sentence
    assert "consultation" in sentence
    assert "attorney" in sentence
    assert "in consultation with the attorney general in consultation with the attorney general" not in sentence
