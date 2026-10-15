"""Repeated wording is merged only for the same source-grounded occurrence."""

from copy import deepcopy
from dataclasses import replace

import pytest

from ipfs_datasets_py.logic.deontic.decoder import decode_legal_norm_ir, decoded_phrase_slot_text_map
from ipfs_datasets_py.logic.deontic.exports import build_decoder_record_from_ir
from ipfs_datasets_py.logic.deontic.formula_builder import build_deontic_formula_record_from_ir
from ipfs_datasets_py.logic.deontic.ir import LegalNormIR
from ipfs_datasets_py.logic.deontic.utils.deontic_parser import extract_normative_elements


TEXT = "The Director shall issue a permit within 10 days after application."


def parsed_norm():
    return LegalNormIR.from_parser_element(extract_normative_elements(TEXT)[0])


def source_norm(*, second=""):
    """Use explicit source spans to isolate rendering from parser inventory."""
    norm = parsed_norm()
    source = TEXT[:-1] + (" and " + second if second else "")
    temporal_text = "within 10 days after application"
    temporal_start = source.index(temporal_text)
    relation_texts = ["after application"] + ([second] if second else [])
    relations = []
    search_start = 0
    for text in relation_texts:
        start = source.index(text, search_start)
        search_start = start + len(text)
        relation, anchor = text.split(" ", 1)
        relations.append({"event": "issuance", "relation": relation, "anchor_event": anchor,
                          "raw_text": text, "span": [start, start + len(text)]})
    temporal = {"type": "deadline", "raw_text": temporal_text, "value": temporal_text,
                "anchor": "application", "anchor_event": "application",
                "span": [temporal_start, temporal_start + len(temporal_text)]}
    return replace(norm, source_text=source, temporal_constraints=[temporal],
                   procedure={"event_relations": relations})


def test_parser_deadline_anchor_is_rendered_once_with_procedure_provenance():
    norm = parsed_norm()
    before = deepcopy(norm)
    formula_before = build_deontic_formula_record_from_ir(norm)
    decoded = decode_legal_norm_ir(norm)
    assert decoded.text == "Director shall issue a permit within 10 days after application."
    procedure, = [phrase for phrase in decoded.phrases if phrase.slot == "procedure"]
    assert procedure.provenance_only is True
    assert procedure.text == "after application"
    assert procedure.spans == [norm.procedure["event_relations"][0]["span"]]
    assert decoded_phrase_slot_text_map(decoded)["procedure"] == ["after application"]
    assert "procedure" not in decoded_phrase_slot_text_map(decoded, include_provenance_only=False)
    exported = build_decoder_record_from_ir(norm)
    assert any(row["slot"] == "procedure" and row["spans"]
               and row["provenance_only"] for row in exported["phrase_provenance"])
    assert build_deontic_formula_record_from_ir(norm) == formula_before
    assert norm == before


def test_missing_temporal_slot_still_renders_independent_procedure_anchor():
    norm = replace(parsed_norm(), temporal_constraints=[])
    decoded = decode_legal_norm_ir(norm)
    assert decoded.text == "Director shall issue a permit after application."
    assert "10 days" not in decoded.text
    assert all(phrase.slot != "temporal_constraints" for phrase in decoded.phrases)
    assert any(phrase.slot == "procedure" and not phrase.provenance_only for phrase in decoded.phrases)


@pytest.mark.parametrize("second", ["after approval", "before application", "after application"])
def test_separate_relation_or_repeated_occurrence_remains_visible(second):
    norm = source_norm(second=second)
    decoded = decode_legal_norm_ir(norm)
    assert decoded.text == f"Director shall issue a permit within 10 days after application and {second}."
    procedure = [phrase for phrase in decoded.phrases if phrase.slot == "procedure"]
    assert [phrase.provenance_only for phrase in procedure] == [True, False]
    assert [phrase.spans for phrase in procedure] == [
        [record["span"]] for record in norm.procedure["event_relations"]
    ]
    assert procedure[0].spans != procedure[1].spans


@pytest.mark.parametrize("slot", ["temporal", "procedure"])
@pytest.mark.parametrize("span", [None, [True, 66], [49.0, 66], ["49", 66], [-1, 66], [49, 10000]])
def test_unverified_spans_cannot_suppress_a_procedure_phrase(slot, span):
    norm = source_norm()
    record = norm.temporal_constraints[0] if slot == "temporal" else norm.procedure["event_relations"][0]
    record["span"] = span
    decoded = decode_legal_norm_ir(norm)
    assert any(phrase.slot == "procedure" and not phrase.provenance_only for phrase in decoded.phrases)


@pytest.mark.parametrize("slot", ["temporal", "procedure"])
@pytest.mark.parametrize("alias", ["source_span", "support_span", "source_id"])
def test_conflicting_source_aliases_do_not_authorize_overlap_suppression(slot, alias):
    norm = source_norm()
    record = norm.temporal_constraints[0] if slot == "temporal" else norm.procedure["event_relations"][0]
    record[alias] = "other-source" if alias == "source_id" else [False, 66]
    decoded = decode_legal_norm_ir(norm)
    assert any(phrase.slot == "procedure" and not phrase.provenance_only for phrase in decoded.phrases)


def test_same_words_at_other_source_occurrence_are_not_merged():
    norm = source_norm(second="after application")
    norm.procedure["event_relations"] = norm.procedure["event_relations"][1:]
    decoded = decode_legal_norm_ir(norm)
    assert decoded.text.count("after application") == 2
    procedure, = [phrase for phrase in decoded.phrases if phrase.slot == "procedure"]
    assert procedure.provenance_only is False


def test_containment_without_matching_anchor_does_not_merge_semantic_records():
    norm = source_norm()
    norm.temporal_constraints[0]["anchor_event"] = "approval"
    decoded = decode_legal_norm_ir(norm)
    assert any(phrase.slot == "procedure" and not phrase.provenance_only for phrase in decoded.phrases)


@pytest.mark.parametrize("slot", ["temporal", "procedure"])
def test_source_text_mismatch_cannot_authorize_suppression(slot):
    norm = source_norm()
    record = norm.temporal_constraints[0] if slot == "temporal" else norm.procedure["event_relations"][0]
    record["raw_text"] = record["raw_text"].replace("application", "approval")
    decoded = decode_legal_norm_ir(norm)
    assert any(phrase.slot == "procedure" and not phrase.provenance_only for phrase in decoded.phrases)


def test_rendered_procedure_text_must_match_its_source_occurrence():
    norm = source_norm()
    norm.procedure["event_relations"][0]["value"] = "before application"
    decoded = decode_legal_norm_ir(norm)
    assert decoded.text.endswith("and before application.")
    assert any(phrase.slot == "procedure" and not phrase.provenance_only for phrase in decoded.phrases)


@pytest.mark.parametrize("slot", ["temporal", "procedure"])
def test_conflicting_direction_is_not_hidden_by_shared_wording(slot):
    norm = source_norm()
    if slot == "temporal":
        norm.temporal_constraints[0]["direction"] = "before"
    else:
        norm.procedure["event_relations"][0]["relation"] = "before"
    decoded = decode_legal_norm_ir(norm)
    assert any(phrase.slot == "procedure" and not phrase.provenance_only for phrase in decoded.phrases)
