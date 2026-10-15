"""Adversarial source-boundary checks for the narrow actor-heading override.

Every polluted label includes ``for``, so the older institution-preserving
heuristic vetoes it. Negative cases therefore test only the new override.
"""
from __future__ import annotations

from copy import deepcopy

import pytest

from ipfs_datasets_py.logic.deontic.ir import LegalNormIR, legal_norm_ir_slot_provenance


HEADING = "Assistance for adaptive sports programs"
ACTOR = "The Secretary"
MODAL = "is authorized and directed to"
ACTION = "make grants to eligible entities"


def element(*, actor=ACTOR, modal=MODAL, action=ACTION, prefix="", suffix="", quoted=None):
    clause = f"{actor} {modal} {action}."
    if quoted is not None:
        opening, closing = quoted
        clause = opening + clause + closing
    support = f"{HEADING}. {clause}"
    document = prefix + support + suffix
    start = document.index(action)
    polluted = f"{HEADING} {actor}"
    return {
        "schema_version": "legal-norm-ir/v1", "source_id": "heading-boundary-test",
        "text": document, "support_text": support,
        "source_span": [0, len(document)],
        "support_span": [len(prefix), len(prefix) + len(support)],
        "subject": [polluted], "action": [action],
        "field_spans": {"action": [start, start + len(action)]},
    }


def assert_not_recovered(row):
    original_actor = row["subject"][0]
    before = deepcopy(row)
    norm = LegalNormIR.from_parser_element(row)
    assert norm.actor == original_actor
    assert row == before
    return norm


@pytest.mark.parametrize("prefix", ["", "Préambule 🏛.\n\n"])
def test_exact_unicode_document_offsets_update_actor_and_subject_aliases(prefix):
    row = element(prefix=prefix, suffix=" Further context.")
    polluted = row["subject"][0]
    row["actor_entities"] = [polluted]
    # Both stale aliases must be replaced; provenance checks actor first.
    row["field_spans"]["actor"] = [len(prefix), row["text"].index(MODAL) - 1]
    row["field_spans"]["subject"] = list(row["field_spans"]["actor"])
    before = deepcopy(row)
    norm = LegalNormIR.from_parser_element(row)
    actor_start = row["text"].index(ACTOR)
    modal_start = row["text"].index(MODAL)
    assert norm.actor == ACTOR
    assert norm.actor_entities == [ACTOR]
    assert norm.field_spans["actor"] == norm.field_spans["subject"] == [actor_start, actor_start + len(ACTOR)]
    assert norm.field_spans["modality"] == norm.field_spans["deontic_operator"] == [modal_start, modal_start + len(MODAL)]
    assert norm.modality == "O"
    assert norm.action == ACTION
    for field, expected in (("actor", ACTOR), ("subject", ACTOR), ("modality", MODAL), ("action", ACTION)):
        start, end = norm.field_spans[field]
        assert row["text"][start:end] == expected
    assert row == before
    provenance = legal_norm_ir_slot_provenance(norm, slots=("actor", "modality", "action"))
    assert provenance["missing_slots"] == provenance["ungrounded_slots"] == []


@pytest.mark.parametrize("actor", [
    "The Chief Administrative Officer of the House of Representatives",
    "The Secretary and the Treasurer",
    "The Board for the Department",
])
def test_separated_heading_preserves_entire_compound_institution_or_actor(actor):
    row = element(actor=actor, modal="shall")
    norm = LegalNormIR.from_parser_element(row)
    assert norm.actor == actor
    assert norm.actor_entities == [actor]
    start, end = norm.field_spans["actor"]
    assert row["text"][start:end] == actor


@pytest.mark.parametrize("explicit_entities", [False, True])
def test_recovery_replaces_only_polluted_entity_and_preserves_other_actors(explicit_entities):
    row = element()
    polluted = row["subject"][0]
    row["subject"].extend(["The Treasurer", "The Board"])
    if explicit_entities:
        row["actor_entities"] = ["The Board", polluted, "The Treasurer"]
        expected = ["The Board", ACTOR, "The Treasurer"]
    else:
        expected = [ACTOR, "The Treasurer", "The Board"]
    before = deepcopy(row)
    norm = LegalNormIR.from_parser_element(row)
    assert norm.actor == ACTOR
    assert norm.actor_entities == expected
    assert row == before


@pytest.mark.parametrize("actor", [
    "Chief Administrative Officer of the House of Representatives",
    "The Secretary and the Treasurer",
    "The Board for the Department",
])
def test_unseparated_institutional_titles_keep_legacy_suffix_veto(actor):
    text = f"{actor} shall {ACTION}."
    row = {"text": text, "support_text": text, "source_span": [0, len(text)],
           "support_span": [0, len(text)], "subject": [actor], "action": [ACTION],
           "field_spans": {"action": [text.index(ACTION), text.index(ACTION) + len(ACTION)]}}
    norm = LegalNormIR.from_parser_element(row)
    assert norm.actor == actor
    assert norm.actor_entities == [actor]


@pytest.mark.parametrize("quotes", [('"', '"'), ("“", "”"), ("'", "'"), ('"', '')])
def test_quoted_or_unclosed_quoted_modal_clause_does_not_recover_actor(quotes):
    assert_not_recovered(element(quoted=quotes))


def test_quote_opened_before_support_window_still_blocks_heading_recovery():
    row = element(prefix='Préface: "', suffix='"')
    assert '"' not in row["support_text"]
    assert_not_recovered(row)


def test_conflicting_full_source_alias_cannot_supply_alternate_recovery():
    row = element()
    row["source_text"] = row["text"].replace("adaptive", "modified")
    assert_not_recovered(row)


@pytest.mark.parametrize("span_field,index,value_type", [
    ("source_span", 0, "bool"), ("source_span", 1, "float"),
    ("source_span", 0, "string"), ("support_span", 0, "bool"),
    ("support_span", 1, "float"), ("support_span", 0, "string"),
    ("action", 0, "bool"), ("action", 1, "float"), ("action", 0, "string"),
])
def test_new_override_rejects_coercible_noninteger_bounds(span_field, index, value_type):
    row = element()
    span = row[span_field] if span_field != "action" else row["field_spans"]["action"]
    value = span[index]
    span[index] = False if value_type == "bool" else float(value) if value_type == "float" else str(value)
    assert_not_recovered(row)


@pytest.mark.parametrize("mutation", [
    "support_shift", "support_truncated", "support_edited", "source_out_of_range",
    "action_shift", "action_text_differs", "missing_action_span", "ambiguous_action_spans",
    "heading_words_differ", "no_heading_boundary", "missing_support_span",
])
def test_unaligned_or_ambiguous_evidence_cannot_override_institution_veto(mutation):
    row = element(prefix="Préface. ", suffix=" More context.")
    if mutation == "support_shift":
        row["support_span"] = [value + 1 for value in row["support_span"]]
    elif mutation == "support_truncated":
        row["support_span"][1] -= 1
    elif mutation == "support_edited":
        row["support_text"] = row["support_text"].replace("adaptive", "modified")
    elif mutation == "source_out_of_range":
        row["source_span"][1] += 1
    elif mutation == "action_shift":
        row["field_spans"]["action"] = [value + 1 for value in row["field_spans"]["action"]]
    elif mutation == "action_text_differs":
        row["action"] = ["make loans to eligible entities"]
    elif mutation == "missing_action_span":
        del row["field_spans"]["action"]
    elif mutation == "ambiguous_action_spans":
        span = row["field_spans"]["action"]
        row["field_spans"]["action"] = [span, list(span)]
    elif mutation == "heading_words_differ":
        row["subject"] = ["Assistance for unrelated programs The Secretary"]
    elif mutation == "no_heading_boundary":
        text = row["support_text"].replace(HEADING + ".", HEADING)
        row = {**row, "text": text, "support_text": text,
               "source_span": [0, len(text)], "support_span": [0, len(text)]}
        row["field_spans"]["action"] = [text.index(ACTION), text.index(ACTION) + len(ACTION)]
    elif mutation == "missing_support_span":
        del row["support_span"]
    assert_not_recovered(row)


@pytest.mark.parametrize("later_action", [ACTION, "retain all supporting records"])
def test_exact_action_span_selects_first_modal_and_not_later_modal(later_action):
    row = element(modal="may")
    later = f" The Treasurer shall {later_action}."
    row["text"] += later
    row["support_text"] += later
    row["source_span"][1] += len(later)
    row["support_span"][1] += len(later)
    norm = LegalNormIR.from_parser_element(row)
    assert norm.actor == ACTOR
    assert norm.actor_entities == [ACTOR]
    assert norm.modality == "P"
    start = row["text"].index("may")
    assert norm.field_spans["modality"] == [start, start + 3]
    assert norm.field_spans["deontic_operator"] == norm.field_spans["modality"]


def test_action_span_pointing_to_other_actor_cannot_trim_supplied_subject():
    row = element(modal="may")
    later = f" The Treasurer shall {ACTION}."
    row["text"] += later
    row["support_text"] += later
    row["source_span"][1] += len(later)
    row["support_span"][1] += len(later)
    start = row["text"].rindex(ACTION)
    row["field_spans"]["action"] = [start, start + len(ACTION)]
    assert_not_recovered(row)


@pytest.mark.parametrize("slot", ["modality", "deontic_operator"])
def test_conflicting_declared_modal_span_blocks_new_override(slot):
    row = element()
    start = row["text"].index(MODAL)
    row["field_spans"][slot] = [start + 1, start + len(MODAL)]
    assert_not_recovered(row)


def test_heading_recovery_preserves_input_quality_warnings_and_explicit_operator():
    row = element()
    row["deontic_operator"] = "P"
    row["quality"] = {
        "schema_valid": False, "slot_coverage": 0.25, "scaffold_quality": 0.5,
        "quality_label": "needs_review", "parser_warnings": ["ambiguous_actor", "manual_review_required"],
        "promotable_to_theorem": False,
        "export_readiness": {"proof_ready": False, "blockers": ["manual_review_required"]},
    }
    before = deepcopy(row)
    norm = LegalNormIR.from_parser_element(row)
    assert norm.actor == ACTOR
    assert norm.modality == "P"
    assert norm.quality.parser_warnings == row["quality"]["parser_warnings"]
    assert norm.quality.schema_valid is False
    assert norm.quality.slot_coverage == 0.25
    assert norm.quality.scaffold_quality == 0.5
    assert norm.quality.quality_label == "needs_review"
    assert norm.proof_ready is False
    assert norm.quality.export_readiness == row["quality"]["export_readiness"]
    assert row == before


def test_unsourced_polluted_actor_stays_unchanged():
    row = {"subject": [f"{HEADING} {ACTOR}"], "action": [ACTION]}
    assert_not_recovered(row)
