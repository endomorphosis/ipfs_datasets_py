"""UI native validity cannot stand in for complete source-field agreement."""
from copy import deepcopy
import hashlib
import json

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder import ui_candidate_fidelity as api
from ipfs_datasets_py.logic.ui_ux_ir.model.components import (
    PRESENTATION_CLASSIFICATION_VALUES, PRIVACY_SENSITIVITY_VALUES,
)


def envelope(**changes):
    return {"kind": "ui_component", "document": {
        "component_id": "approve_toggle", "role": "button",
        "privacy_sensitivity": "none", "presentation_classification": "interactive",
        **changes}}


def source(**changes):
    values = envelope(**changes)["document"]
    return (f"Component {values['component_id']} has role {values['role']}. "
            f"Its privacy sensitivity is {values['privacy_sensitivity']} and its "
            f"presentation classification is {values['presentation_classification']}.")


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, allow_nan=False).encode()).hexdigest()


@pytest.mark.parametrize("text", [source(), " \n" + source() + "\t ",
    source().replace(" ", "\t\r\n ")])
def test_complete_four_field_grammar_is_only_a_post_inference_diagnostic(text):
    candidate = envelope()
    before = deepcopy(candidate)
    report = api.audit_ui_candidate(text, candidate)
    assert report["status"] == "source_agreement"
    assert report["native_valid"] and report["source_supported"] and report["exact"]
    assert report["source_agreement"] and report["differences"] == []
    assert report["source_reference"] == candidate == before
    assert report["candidate"] == before and report["candidate"] is not candidate
    assert report["candidate"]["document"] is not candidate["document"]
    assert report["source_text"] == text
    assert report["source_sha256"] == hashlib.sha256(text.encode()).hexdigest()
    assert report["candidate_sha256"] == digest(candidate)
    assert report["producer_pins"] and report["resolved_logic_tree"]
    assert not any(report[key] for key in api.FALSE)
    assert not report["model_inference_executed"] and not report["model_inputs_modified"]
    assert report["report_sha256"] == digest({k: v for k, v in report.items() if k != "report_sha256"})
    report["candidate"]["document"]["role"] = "checkbox"
    assert candidate == before


@pytest.mark.parametrize("privacy", sorted(PRIVACY_SENSITIVITY_VALUES))
@pytest.mark.parametrize("presentation", sorted(PRESENTATION_CLASSIFICATION_VALUES))
def test_existing_semantic_owner_determines_classification_vocabulary(privacy, presentation):
    fields = dict(privacy_sensitivity=privacy, presentation_classification=presentation)
    assert api.audit_ui_candidate(source(**fields), envelope(**fields))["exact"]


@pytest.mark.parametrize("field,value", [
    ("component_id", "reject_toggle"), ("component_id", "Approve_toggle"),
    ("role", "checkbox"), ("role", "textbox"),
    ("privacy_sensitivity", "high"), ("presentation_classification", "status"),
])
def test_valid_but_wrong_candidate_slot_is_preserved_and_located(field, value):
    candidate = envelope(**{field: value})
    report = api.audit_ui_candidate(source(), candidate)
    assert report["status"] == "source_disagreement"
    assert report["native_valid"] and report["source_supported"] and not report["exact"]
    assert report["candidate"] == candidate
    assert report["source_reference"] == envelope()
    assert report["differences"] == [{
        "path": "/document/" + field, "path_segments": ["document", field],
        "reason": "value_mismatch", "expected_present": True, "candidate_present": True,
        "expected_type": "string", "candidate_type": "string",
        "expected": envelope()["document"][field], "candidate": value}]


@pytest.mark.parametrize("gold,candidate,paths", [
    ({}, {"role": "textbox", "privacy_sensitivity": "low", "presentation_classification": "status"},
     {"role", "privacy_sensitivity", "presentation_classification"}),
    ({"role": "checkbox", "privacy_sensitivity": "low", "presentation_classification": "status"},
     {"role": "textbox", "privacy_sensitivity": "low", "presentation_classification": "status"}, {"role"}),
    ({"privacy_sensitivity": "high", "presentation_classification": "status"},
     {"role": "textbox", "privacy_sensitivity": "low", "presentation_classification": "status"},
     {"role", "privacy_sensitivity"}),
    ({}, {"role": "checkbox"}, {"role"}),
    ({"role": "checkbox", "privacy_sensitivity": "low", "presentation_classification": "status"},
     {"role": "checkbox", "privacy_sensitivity": "high", "presentation_classification": "status"},
     {"privacy_sensitivity"}),
    ({"privacy_sensitivity": "high", "presentation_classification": "status"},
     {"role": "checkbox", "privacy_sensitivity": "high", "presentation_classification": "status"}, {"role"}),
])
def test_six_archived_baseline_failures_are_decoder_errors_not_source_ambiguity(gold, candidate, paths):
    predicted = envelope(**candidate)
    report = api.audit_ui_candidate(source(**gold), predicted)
    assert report["status"] == "source_disagreement"
    assert report["source_supported"] and report["native_valid"]
    assert report["candidate"] == predicted
    assert {d["path"] for d in report["differences"]} == {"/document/" + key for key in paths}


@pytest.mark.parametrize("field", ["privacy_sensitivity", "presentation_classification"])
def test_omitted_native_default_never_fills_a_predicted_field(field):
    candidate = envelope()
    del candidate["document"][field]
    report = api.audit_ui_candidate(source(), candidate)
    assert report["native_valid"] and report["status"] == "source_disagreement"
    assert field not in report["candidate"]["document"]
    assert report["differences"][0]["path"] == "/document/" + field
    assert report["differences"][0]["reason"] == "missing_field"


@pytest.mark.parametrize("field,value", [("purpose", ""), ("child_ids", []), ("purpose", "execute")])
def test_additional_native_valid_fields_are_unjustified_even_if_default(field, value):
    candidate = envelope(**{field: value})
    report = api.audit_ui_candidate(source(), candidate)
    assert report["native_valid"] and report["status"] == "source_disagreement"
    assert report["candidate"] == candidate
    assert report["differences"][0]["path"] == "/document/" + field
    assert report["differences"][0]["reason"] == "unexpected_field"


@pytest.mark.parametrize("field,value", [("component_id", 1), ("role", True),
    ("privacy_sensitivity", None), ("presentation_classification", [])])
def test_wrongly_typed_fields_are_never_coerced(field, value):
    candidate = envelope(**{field: value})
    report = api.audit_ui_candidate(source(), candidate)
    assert report["status"] == "native_invalid" and report["source_supported"]
    assert report["candidate"] == candidate
    assert report["differences"][0]["path"] == "/document/" + field
    assert report["differences"][0]["reason"] == "type_mismatch"


def test_unknown_extra_field_escapes_json_pointer_without_disappearing():
    candidate = envelope(**{"unknown/field~": [False, 1, None]})
    report = api.audit_ui_candidate(source(), candidate)
    assert report["status"] == "native_invalid" and report["source_supported"]
    assert report["differences"][0]["path"] == "/document/unknown~1field~0"
    assert report["differences"][0]["reason"] == "unexpected_field"
    assert report["candidate"] == candidate


@pytest.mark.parametrize("text", [
    "Component approve_toggle has role button.",
    source() + " Unless authorization fails.",
    source() + " " + source(component_id="other"),
    source().replace("Component", "Set component", 1),
    source().replace("Its privacy", "The privacy", 1),
    source().replace("approve_toggle", "appróve_toggle"),
    source().replace("approve_toggle", "it" ).replace("Component it", "It"),
    source().replace("is none", "is sensitive"),
    source().replace("is interactive", "is informational"),
    source().replace("Component", "component", 1),
    source()[:-1], "", "\x00" + source(),
])
def test_partial_paraphrased_or_extended_source_remains_unsupported(text):
    report = api.audit_ui_candidate(text, envelope())
    assert report["status"] == "source_unsupported" and report["native_valid"]
    assert not report["source_supported"] and not report["exact"]
    assert report["source_error"] and report["native_error"] is None
    assert report["source_reference"] is None and report["differences"] is None
    assert report["candidate"] == envelope()


@pytest.mark.parametrize("candidate", [None, [], 3, False, {},
    {"kind": "document", "document": {}}, {"kind": "ui_component", "document": {}},
    {"kind": "ui_component", "document": {}, "extra": True}])
def test_malformed_json_is_retained_even_if_source_is_unsupported(candidate):
    report = api.audit_ui_candidate("Create a toolbar.", candidate)
    assert report["status"] == "native_invalid"
    assert report["native_error"] and report["source_error"]
    assert report["candidate"] == candidate
    assert not report["native_valid"] and not report["source_supported"]


def test_native_owner_custom_role_token_is_preserved_without_guessing():
    # Unlike privacy/presentation classifications, native roles allow custom
    # stable tokens. Source auditing must not invent a smaller closed role set.
    candidate = envelope(role="nonsense")
    report = api.audit_ui_candidate(source(role="nonsense"), candidate)
    assert report["exact"] and report["candidate"] == candidate
    different = api.audit_ui_candidate(source(role="nonsense"), envelope())
    assert different["status"] == "source_disagreement"
    assert different["differences"][0]["expected"] == "nonsense"


@pytest.mark.parametrize("candidate", [float("nan"), float("inf"), {1: "key"},
    {"bad": object()}, "x" * 65537, [None] * 4097])
def test_non_json_or_unbounded_candidate_rejected(candidate):
    with pytest.raises(ValueError):
        api.audit_ui_candidate(source(), candidate)


@pytest.mark.parametrize("text", [None, 1, "x" * 65537])
def test_source_must_be_a_bounded_original_string(text):
    with pytest.raises(ValueError, match="bounded original source"):
        api.audit_ui_candidate(text, envelope())


def test_depth_bound_precedes_copy_or_source_parse():
    candidate = {}
    for _ in range(api.MAX_DEPTH + 1):
        candidate = {"child": candidate}
    with pytest.raises(ValueError, match="depth"):
        api.audit_ui_candidate(source(), candidate)


def test_loaded_native_owner_substitution_is_rejected(monkeypatch):
    monkeypatch.setattr(api.native_owner, "validate_training_target", lambda value: {"valid": True})
    with pytest.raises(ValueError, match="producer"):
        api.audit_ui_candidate(source(), envelope())


def test_loaded_source_parser_substitution_is_rejected(monkeypatch):
    monkeypatch.setattr(api, "_parse_source", lambda text: envelope())
    with pytest.raises(ValueError, match="producer"):
        api.audit_ui_candidate(source(), envelope())


def test_owner_from_different_tree_is_rejected(monkeypatch, tmp_path):
    monkeypatch.setattr(api.native_owner, "__file__", str(tmp_path / "ui_source_contract_384.py"))
    with pytest.raises(ValueError, match="outside selected source tree"):
        api.audit_ui_candidate(source(), envelope())
