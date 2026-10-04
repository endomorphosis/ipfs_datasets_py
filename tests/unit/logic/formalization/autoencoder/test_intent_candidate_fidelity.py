"""The diagnostic exposes errors without replacing a learned Intent output."""
from copy import deepcopy

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder import intent_candidate_fidelity as api
from ipfs_datasets_py.logic.intent_ir.formalize import rich_grammar


def atom(**changes):
    return {"kind": "atom", "actor": "librarian", "action": "catalog",
            "object": "packet", "modality": "required", **changes}


def envelope(document=None):
    return {"kind": "intent_rich_ast", "document": atom() if document is None else document}


@pytest.mark.parametrize("source", [
    "The librarian must catalog the packet.",
    "the librarian shall catalog packet",
    "  librarian   is required to catalog packet.  ",
])
def test_complete_grammar_agreement_is_only_a_diagnostic(source):
    candidate = envelope()
    before = deepcopy(candidate)
    report = api.audit_intent_candidate(source, candidate)
    assert report["status"] == "source_agreement"
    assert report["native_valid"] and report["source_supported"] and report["exact"]
    assert report["source_agreement"] and report["differences"] == []
    assert report["source_text"] == source
    assert report["candidate"] == candidate == before
    assert report["candidate"] is not candidate
    assert report["candidate"]["document"] is not candidate["document"]
    assert not any(report[key] for key in api.FALSE)
    assert not report["model_inference_executed"] and not report["model_inputs_modified"]
    assert report["native_validation_scope"] == "complete_rich_grammar_AST_schema_only"
    assert report["producer_pins"] and report["resolved_logic_tree"]
    report["candidate"]["document"]["action"] = "changed"
    assert candidate == before


@pytest.mark.parametrize("field,value", [
    ("actor", "inspector"), ("action", "release"), ("object", "report"),
    ("modality", "permitted"), ("modality", "prohibited"),
    ("modality", "intended"), ("modality", "recommended"),
    ("actor", "Librarian"), ("object", "Packet"),
])
def test_wrong_slot_or_modality_is_retained_and_located(field, value):
    candidate = envelope(atom(**{field: value}))
    report = api.audit_intent_candidate("The librarian must catalog the packet.", candidate)
    assert report["status"] == "source_disagreement"
    assert report["native_valid"] and report["source_supported"]
    assert not report["exact"]
    assert report["candidate"] == candidate
    assert report["source_reference"] == envelope()
    assert len(report["differences"]) == 1
    difference = report["differences"][0]
    assert difference["path"] == "/document/" + field
    assert difference["reason"] == "value_mismatch"
    assert difference["candidate"] == value
    assert difference["expected"] == atom()[field]
    assert difference["expected_type"] == difference["candidate_type"] == "string"


def test_archived_three_field_failure_is_not_parser_failure():
    candidate = envelope(atom(actor="inspector", action="release", modality="permitted"))
    report = api.audit_intent_candidate("The librarian must catalog the packet.", candidate)
    assert report["status"] == "source_disagreement"
    assert {row["path"] for row in report["differences"]} == {
        "/document/actor", "/document/action", "/document/modality"}
    assert report["candidate"] == candidate


@pytest.mark.parametrize("mutation,path,reason", [
    ("delete", "/document/action", "missing_field"),
    ("extra", "/document/unsupported~1field~0", "unexpected_field"),
    ("type", "/document/action", "type_mismatch"),
    ("envelope", "/extra", "unexpected_field"),
])
def test_native_invalid_candidates_preserve_missing_extra_and_wrongly_typed_fields(mutation, path, reason):
    candidate = envelope()
    if mutation == "delete":
        del candidate["document"]["action"]
    elif mutation == "extra":
        candidate["document"]["unsupported/field~"] = [False, 1, None]
    elif mutation == "type":
        candidate["document"]["action"] = 1
    else:
        candidate["extra"] = True
    report = api.audit_intent_candidate("The librarian must catalog the packet.", candidate)
    assert report["status"] == "native_invalid"
    assert not report["native_valid"] and report["source_supported"]
    assert report["native_error"] and not report["exact"]
    assert report["candidate"] == candidate
    assert report["differences"][0]["path"] == path
    assert report["differences"][0]["reason"] == reason


@pytest.mark.parametrize("source", [
    "The librarian must catalog the packet unless a supervisor objects.",
    "The librarian must catalog the packet. The inspector must seal the report.",
    "The librarian must catalog the résumé.",
    "The librarian must catalog it.",
    "",
])
def test_unsupported_source_is_distinct_from_decoder_disagreement(source):
    report = api.audit_intent_candidate(source, envelope())
    assert report["status"] == "source_unsupported"
    assert report["native_valid"] and not report["source_supported"]
    assert report["source_error"] and report["native_error"] is None
    assert report["source_reference"] is None and report["differences"] is None
    assert report["candidate"] == envelope() and not report["exact"]


@pytest.mark.parametrize("candidate", [None, [], 3, False, {}, {"kind": "other", "document": {}}])
def test_json_native_invalid_envelopes_are_retained_even_when_source_is_unsupported(candidate):
    report = api.audit_intent_candidate("Inspect the résumé.", candidate)
    assert report["status"] == "native_invalid"
    assert report["native_error"] and report["source_error"]
    assert report["candidate"] == candidate
    assert not report["source_supported"] and not report["native_valid"]


def test_conditional_negation_cannot_be_dropped_or_coerced_to_integer():
    source = "If the cache is not empty, the librarian must not delete the packet."
    reference = rich_grammar.parse_instruction(source)
    report = api.audit_intent_candidate(source, envelope(reference))
    assert report["exact"]
    for value, status, reason, kind in [
        (False, "source_disagreement", "value_mismatch", "boolean"),
        (1, "native_invalid", "type_mismatch", "integer"),
    ]:
        changed = deepcopy(reference)
        changed["guard"]["negated"] = value
        report = api.audit_intent_candidate(source, envelope(changed))
        assert report["status"] == status
        assert report["differences"] == [{
            "path": "/document/guard/negated", "path_segments": ["document", "guard", "negated"],
            "reason": reason, "expected_present": True, "candidate_present": True,
            "expected_type": "boolean", "candidate_type": kind,
            "expected": True, "candidate": value}]


@pytest.mark.parametrize("connector", ["and", "or", "then"])
def test_complete_nonatomic_ast_preserves_branch_identity_and_sequence_order(connector):
    source = f"librarian must catalog packet {connector} inspector may seal report."
    reference = rich_grammar.parse_instruction(source)
    assert api.audit_intent_candidate(source, envelope(reference))["exact"]
    swapped = {**reference, "left": deepcopy(reference["right"]), "right": deepcopy(reference["left"])}
    report = api.audit_intent_candidate(source, envelope(swapped))
    assert report["status"] == "source_disagreement"
    assert {row["path"] for row in report["differences"]} >= {
        "/document/left/actor", "/document/left/action", "/document/left/modality",
        "/document/right/actor", "/document/right/action", "/document/right/modality"}
    assert report["candidate"] == envelope(swapped)


@pytest.mark.parametrize("candidate", [float("nan"), {1: "wrong key"}, {"bad": object()}, "x" * 65537])
def test_non_json_or_unbounded_transport_rejected(candidate):
    with pytest.raises(ValueError):
        api.audit_intent_candidate("librarian must catalog packet.", candidate)


def test_excessive_depth_rejected_before_copy_or_parser():
    value = {}
    for _ in range(api.MAX_DEPTH + 1):
        value = {"child": value}
    with pytest.raises(ValueError, match="depth"):
        api.audit_intent_candidate("librarian must catalog packet.", value)


def test_owner_loaded_code_substitution_is_rejected(monkeypatch):
    monkeypatch.setattr(rich_grammar, "parse_instruction", lambda source: atom())
    with pytest.raises(ValueError, match="producer"):
        api.audit_intent_candidate("librarian must catalog packet.", envelope())


def test_owner_from_different_tree_is_rejected(monkeypatch, tmp_path):
    monkeypatch.setattr(rich_grammar, "__file__", str(tmp_path / "rich_grammar.py"))
    with pytest.raises(ValueError, match="outside selected source tree"):
        api.audit_intent_candidate("librarian must catalog packet.", envelope())
