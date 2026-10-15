"""Fictional parser-slot regressions, not authoritative labels for a statute."""
from copy import deepcopy

import pytest

from ipfs_datasets_py.logic.deontic.ir import LegalNormIR, legal_norm_ir_slot_provenance


HEADING = "Assistance for adaptive sports programs"
ACTOR = "The Secretary"
MODAL = "is authorized and directed to"
ACTION = "make grants to eligible entities"
SUPPORT = f"{HEADING}. {ACTOR} {MODAL} {ACTION}."
POLLUTED = f"{HEADING} {ACTOR}"


def element(*, prefix="", suffix="", support=SUPPORT, action=ACTION):
    text = prefix + support + suffix
    start = len(prefix)
    action_start = text.index(action, start)
    return {"schema_version": "legal-norm-ir/v1", "source_id": "fictional-actor-grounding",
            "text": text, "support_text": support, "source_span": [0, len(text)],
            "support_span": [start, start + len(support)],
            "subject": [POLLUTED], "action": [action],
            "field_spans": {"action": [action_start, action_start + len(action)]}}


def test_exact_heading_actor_action_tuple_preserves_coherent_spans_and_entities():
    row = element(prefix="Résumé.\n", suffix=" Another clause may follow.")
    row["field_spans"]["actor"] = [len("Résumé.\n"), row["text"].index(MODAL) - 1]
    row["actor_entities"] = [POLLUTED, "The Treasurer", POLLUTED]
    before = deepcopy(row)
    norm = LegalNormIR.from_parser_element(row)
    assert norm.actor == ACTOR
    assert norm.actor_entities == [ACTOR, "The Treasurer", ACTOR]
    actor_start = row["text"].index(ACTOR)
    modal_start = row["text"].index(MODAL)
    assert norm.field_spans["actor"] == norm.field_spans["subject"] == [actor_start, actor_start + len(ACTOR)]
    assert norm.field_spans["modality"] == norm.field_spans["deontic_operator"] == [modal_start, modal_start + len(MODAL)]
    assert norm.modality == "O"
    assert norm.field_spans["action"] == row["field_spans"]["action"]
    assert row == before
    provenance = legal_norm_ir_slot_provenance(norm, slots=("actor", "modality", "action"))
    assert provenance["ungrounded_slots"] == provenance["missing_slots"] == []


def test_multiple_subjects_preserve_other_entities_in_original_order():
    row = element()
    row["subject"].append("The Treasurer")
    norm = LegalNormIR.from_parser_element(row)
    assert norm.actor == ACTOR
    assert norm.actor_entities == [ACTOR, "The Treasurer"]


def test_action_coordinates_select_first_modal_instead_of_last_section_modal():
    row = element(suffix=" The Treasurer may " + ACTION + ".")
    # Deliberately supply section-wide support; the exact action occurrence,
    # not the last modal in that support, selects the coherent recovery.
    row["support_text"] = row["text"]
    row["support_span"] = [0, len(row["text"])]
    norm = LegalNormIR.from_parser_element(row)
    assert norm.actor == ACTOR
    assert norm.modality == "O"
    modal_start = row["text"].index(MODAL)
    assert norm.field_spans["modality"] == [modal_start, modal_start + len(MODAL)]


def test_existing_explicit_modality_and_quality_are_not_reclassified():
    row = element()
    row["deontic_operator"] = "P"
    row["quality"] = {"schema_valid": False, "quality_label": "needs_review",
                      "parser_warnings": ["caller_review_required"], "promotable_to_theorem": False}
    norm = LegalNormIR.from_parser_element(row)
    assert norm.actor == ACTOR
    assert norm.modality == "P"
    assert norm.quality.schema_valid is False
    assert norm.quality.parser_warnings == ["caller_review_required"]
    assert norm.proof_ready is False


def test_support_only_view_retains_exact_caller_coordinates():
    row = element()
    row.pop("text")
    offset = 400
    row["source_span"] = [offset, offset + len(SUPPORT)]
    row["support_span"] = [offset, offset + len(SUPPORT)]
    row["field_spans"]["action"] = [value + offset for value in row["field_spans"]["action"]]
    norm = LegalNormIR.from_parser_element(row)
    start = offset + SUPPORT.index(ACTOR)
    assert norm.actor == ACTOR
    assert norm.field_spans["actor"] == [start, start + len(ACTOR)]


@pytest.mark.parametrize("actor", [
    "The Chief Administrative Officer of the House of Representatives",
    "The Judicial power of the United States",
])
def test_institutional_prepositional_actor_is_preserved(actor):
    text = actor + " shall appoint staff."
    row = {"text": text, "support_text": text, "source_span": [0, len(text)],
           "support_span": [0, len(text)], "subject": [actor], "action": ["appoint staff"],
           "field_spans": {"action": [text.index("appoint"), text.index("appoint") + len("appoint staff")]}}
    norm = LegalNormIR.from_parser_element(row)
    assert norm.actor == actor
    assert norm.actor_entities == [actor]


@pytest.mark.parametrize("opening,closing", [("(", ")"), ("[", "]"), ("{", "}")])
def test_bracket_enclosed_clause_does_not_authorize_heading_recovery(opening, closing):
    row = element(prefix=opening, suffix=closing)
    norm = LegalNormIR.from_parser_element(row)
    assert norm.actor == POLLUTED


def test_abbreviated_title_prefix_is_not_a_hard_sentence_boundary():
    heading = "Assistance for Dr"
    support = f"{heading}. {ACTOR} {MODAL} {ACTION}."
    row = element(support=support)
    row["subject"] = [heading + " " + ACTOR]
    norm = LegalNormIR.from_parser_element(row)
    assert norm.actor == row["subject"][0]
