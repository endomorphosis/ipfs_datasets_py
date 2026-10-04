"""Complete schema decoding preserves source fields before learned384 validation."""
from copy import deepcopy
from dataclasses import replace
import importlib.util
import json
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.ui_ux_ir import decoder, schema

spec = importlib.util.spec_from_file_location("_complete_ui_codec_fixtures", Path(__file__).with_name("test_schema.py"))
fixtures = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixtures)


@pytest.mark.parametrize("fixture", [fixtures._minimal_document, fixtures._rich_document])
@pytest.mark.parametrize("representation", ["mapping", "text", "bytes"])
def test_complete_document_roundtrip_retains_every_declared_field(fixture, representation):
    expected = fixture().to_dict()
    payload = expected if representation == "mapping" else json.dumps(expected)
    if representation == "bytes":
        payload = payload.encode()
    actual = decoder.decode_ui_ir(payload).to_dict()
    assert actual == expected
    assert set(actual) == schema.UIIR_DOCUMENT_FIELDS
    assert actual["program_bindings"] and actual["feedback_contracts"]
    assert actual["producer"] and actual["configuration"] and actual["review"]


def test_ui384_accepts_full_rich_target_without_dropping_any_supplied_fields():
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.domain_384_autoencoder import validate_target
    from ipfs_datasets_py.logic.formalization.autoencoder.ui_source_contract_384 import qualify_source_candidate
    target = fixtures._rich_document().to_dict()
    validation = validate_target("ui_ux_ir", target)
    assert validation["native_ir"] == target
    report = qualify_source_candidate("Authored form fixture with bindings and guarded transition.", target)
    assert report["status"] == "projected_candidate", report
    assert report["source_semantics_verified"] is False
    assert report["source_fidelity_check_required"] is True
    assert "temporal_interaction" in report["unprojected_facets"]


def test_ordered_effects_children_and_locale_fallbacks_keep_their_order():
    original = fixtures._rich_document()
    extra = replace(original.effects[0], effect_id="effect:additional")
    transition = replace(original.transitions[0], effect_ids=(extra.effect_id, original.effects[0].effect_id))
    original = replace(original, effects=(*original.effects, extra), transitions=(transition,),
        locale_defaults=replace(original.locale_defaults, fallback_locales=("fr", "en-US", "en")))
    schema.validate_ui_ir(original)
    decoded = decoder.decode_ui_ir(original.to_dict())
    assert decoded.transitions[0].effect_ids == transition.effect_ids
    assert decoded.locale_defaults.fallback_locales == ("fr", "en-US", "en")
    assert decoded.components[0].child_ids == original.components[0].child_ids
    assert decoded.to_dict() == original.to_dict()


@pytest.mark.parametrize("field", ["sources", "components", "states", "transitions", "effects", "program_bindings"])
def test_unknown_nested_fields_are_not_silently_dropped(field):
    payload = fixtures._rich_document().to_dict()
    payload[field][0]["invented_field"] = "not_in_schema"
    with pytest.raises(decoder.UIIRDecodeError, match="unknown fields"):
        decoder.decode_ui_ir(payload)


@pytest.mark.parametrize("mutation", ["boolean_span", "string_span", "number_title", "number_identifier",
    "number_derived", "null_array", "false_array", "null_locale", "false_review", "wrong_enum_type"])
def test_scalar_and_container_types_are_not_coerced(mutation):
    payload = fixtures._rich_document().to_dict()
    if mutation == "boolean_span": payload["sources"][0]["span"]["start_char"] = True
    elif mutation == "string_span": payload["sources"][0]["span"]["start_char"] = "0"
    elif mutation == "number_title": payload["title"] = 17
    elif mutation == "number_identifier": payload["document_id"] = 123
    elif mutation == "number_derived": payload["state_variables"][0]["derived"] = 1
    elif mutation == "null_array": payload["states"] = None
    elif mutation == "false_array": payload["effects"] = False
    elif mutation == "null_locale": payload["locale_defaults"] = None
    elif mutation == "false_review": payload["review"] = False
    else: payload["events"][0]["kind"] = True
    with pytest.raises(decoder.UIIRDecodeError):
        decoder.decode_ui_ir(payload)


def test_missing_nested_required_fields_do_not_receive_invented_defaults():
    payload = fixtures._rich_document().to_dict()
    del payload["sources"][0]["span"]["end_char"]
    with pytest.raises(decoder.UIIRDecodeError, match="missing required"):
        decoder.decode_ui_ir(payload)


def test_duplicate_json_keys_nonfinite_and_executable_extension_fail_closed():
    with pytest.raises(decoder.UIIRDecodeError, match="duplicate"):
        decoder.decode_ui_ir('{"schema_version":"ui-ux-ir/v1","schema_version":"ui-ux-ir/v1"}')
    payload = fixtures._rich_document().to_dict()
    payload["configuration"]["settings"]["ratio"] = float("nan")
    with pytest.raises(decoder.UIIRDecodeError, match="nonfinite"):
        decoder.decode_ui_ir(payload)
    payload = fixtures._rich_document().to_dict()
    payload["extensions"][0]["payload"]["code"] = "untrusted"
    with pytest.raises(decoder.UIIRDecodeError):
        decoder.decode_ui_ir(payload)


def test_full_reference_validation_still_rejects_missing_guard_effect_and_binding():
    for field in ("guards", "effects", "program_bindings"):
        payload = fixtures._rich_document().to_dict()
        payload[field] = []
        with pytest.raises(decoder.UIIRDecodeError, match="unknown"):
            decoder.decode_ui_ir(payload)


def test_complete_decoding_detaches_input_without_mutating_declared_payload():
    payload = fixtures._rich_document().to_dict()
    expected = deepcopy(payload)
    result = decoder.decode_ui_ir(payload)
    assert payload == expected
    payload["configuration"]["settings"]["theme_intent"] = "changed"
    payload["transitions"][0]["effect_ids"].clear()
    assert result.to_dict() == expected


def test_wire_resource_bounds(monkeypatch):
    monkeypatch.setattr(decoder, "MAX_WIRE_NODES", 3)
    with pytest.raises(decoder.UIIRDecodeError, match="resource bound"):
        decoder.decode_ui_ir(fixtures._rich_document().to_dict())
