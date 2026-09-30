"""Source-bound native fixtures exercise identity and exact interface joins."""
from copy import deepcopy
import hashlib
import json

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder.ui_training_inputs import (
    INTERFACE_PROJECTION, MAX_ROW_BYTES, SCHEMA, UITrainingInputError, prepare_ui_training_row,
)
from ipfs_datasets_py.logic.ui_ux_ir.source_adapters.mcp_idl_identity import compute_verified_interface_cid


def native_row(index=0, group_id=None, split="train"):
    """Authored structural example, never represented as an observed human trace."""
    descriptor = {"name": "record-ui", "namespace": "fixture", "version": "1.0.0", "methods": [{
        "name": "delete_record", "input_schema": {"type": "object", "properties": {
            "record_id": {"type": "string"}}, "required": ["record_id"], "additionalProperties": False},
        "output_schema": {"type": "object", "properties": {"deleted": {"type": "boolean"}},
                          "required": ["deleted"], "additionalProperties": False},
    }]}
    return {"schema_version": SCHEMA,
        "provenance": {"dataset": "authored-ui-fixtures", "revision": "fixture-v1", "split": split,
                       "row_id": f"row:{index}", "group_id": group_id or f"group:{index}"},
        "dom_aria": {"document_id": f"document:{index}", "title": "Delete record",
                     "source_id": f"dom:{index}", "source_revision": "fixture-v1",
                     "root": {"node_id": "component:delete", "role": "button", "name": "Delete record",
                              "actions": ["activate"]}},
        "interface": {"descriptor": descriptor, "claimed_interface_cid": compute_verified_interface_cid(descriptor)},
        "bindings": [{"binding_id": "binding:delete", "action_id": "delete_record", "component_id": "component:delete",
                      "dom_action": "activate", "method_name": "delete_record", "risk_class": "high",
                      "confirmation_class": "confirm", "idempotency": "non_idempotent"}],
        "behavior": {"model_id": "delete-workflow", "states": [{"state_id": "pending"},
                      {"state_id": "finished", "terminal": True}], "initial_state_ids": ["pending"],
                     "transitions": [{"transition_id": "delete-complete", "source_state_ids": ["pending"],
                         "target_state_id": "finished", "event_id": "click:delete", "timeout_ms": 1000 + index}]},
        "events": [{"event_id": "click:delete", "kind": "activate", "target_component_id": "component:delete",
                    "timestamp_ms": index + 1, "provenance": "synthetic", "capability_id": "pointer_mouse",
                    "consent_ok": True, "source_adapter": "authored-structural-fixture"}],
    }


def _rehash(row):
    row["interface"]["claimed_interface_cid"] = compute_verified_interface_cid(row["interface"]["descriptor"])


def test_actual_native_views_and_verified_contracts_without_qualification():
    row = native_row(1, "application:one", "validation")
    prepared = prepare_ui_training_row(row)
    payload = prepared.target.to_dict()
    assert prepared.group_id == "application:one"
    assert prepared.source_id == "row:1"
    assert prepared.provenance["split"] == "validation"
    assert prepared.document.document_id == "document:1"
    assert prepared.input_sha256 == hashlib.sha256(json.dumps(row, sort_keys=True,
        separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
    assert payload["source_digest"] == prepared.input_sha256
    projections = {item["projection_id"]: item for item in payload["projections"]}
    assert set(projections) == {"ui_ux_ir:flogic", "ui_ux_ir:event_calculus",
        "ui_ux_ir:tdfol", "ui_ux_ir:dcec", INTERFACE_PROJECTION}
    contracts = projections[INTERFACE_PROJECTION]
    assert contracts["logic_family"] == "frame_logic"
    assert contracts["profile"] == "ui-verified-interface-bindings/v1"
    assert contracts["expression"]["interface_cid"] == row["interface"]["claimed_interface_cid"]
    assert contracts["expression"]["bindings"][0]["method_contract"] == row["interface"]["descriptor"]["methods"][0]
    assert prepared.document.action_bindings[0].risk_class.value == "high"
    assert prepared.document.component_graph.components[0].program_binding_ids == ("binding:delete",)
    assert payload["ready_for_training"] is True
    assert all(payload[flag] is False for flag in ("qualified", "admitted", "formalized"))
    observations = {item["validator_id"]: item for item in payload["validation"]}
    assert observations["ui_ux.native_compile"]["status"] == "passed"
    assert observations["ui_ux.source_gate_adapter"]["status"] != "passed"
    assert observations["ui_ux.verified_interface_join"]["details"]["execution_grant"] is None
    assert any(item["code"] == "ui_ux.supplied_events_not_independently_attested" for item in payload["qualification_gaps"])


def test_preparation_owns_input_and_immutable_provenance():
    row = native_row()
    prepared = prepare_ui_training_row(row)
    digest = prepared.target.digest
    row["interface"]["descriptor"]["methods"][0]["input_schema"]["type"] = "string"
    row["provenance"]["row_id"] = "changed"
    assert prepared.target.digest == digest
    assert prepared.provenance["row_id"] == "row:0"
    with pytest.raises(TypeError):
        prepared.provenance["split"] = "validation"


def test_input_identity_includes_unprojected_dom_provenance_and_method_schema():
    row = native_row()
    original = prepare_ui_training_row(row)
    for variant in ("dom", "provenance", "method"):
        changed = deepcopy(row)
        if variant == "dom":
            changed["dom_aria"]["root"]["description"] = "Caller supplied detail"
        elif variant == "provenance":
            changed["provenance"]["revision"] = "fixture-v2"
        else:
            changed["interface"]["descriptor"]["methods"][0]["output_schema"]["description"] = "Result contract"
            _rehash(changed)
        candidate = prepare_ui_training_row(changed)
        assert candidate.input_sha256 != original.input_sha256
        assert candidate.target.digest != original.target.digest


@pytest.mark.parametrize("mutation,match", [
    (lambda r: r.update(extra=True), "unknown fields"),
    (lambda r: r["provenance"].update(revision="main"), "immutable"),
    (lambda r: r["bindings"][0].update(component_id="missing"), "unknown component"),
    (lambda r: r["bindings"][0].update(method_name="missing"), "unknown interface method"),
    (lambda r: r["bindings"][0].update(dom_action="cancel"), "affordances"),
    (lambda r: r["bindings"][0].pop("risk_class"), "missing required"),
    (lambda r: r["bindings"].append(deepcopy(r["bindings"][0])), "duplicate binding"),
    (lambda r: r["bindings"][0].update(confirmation_class="none"), "confirmation"),
    (lambda r: r["events"][0].update(target_component_id="missing"), "unknown component"),
    (lambda r: r["events"][0].update(target_component_id=[]), "event target_component_id"),
    (lambda r: r["events"][0].update(timestamp_ms=True), "timestamp_ms"),
    (lambda r: r["events"][0].update(consent_ok=False), "consent"),
    (lambda r: r["behavior"]["transitions"][0].update(guards=[]), "unknown fields"),
    (lambda r: r["behavior"]["transitions"][0].update(target_state_id="missing"), "state"),
    (lambda r: r["dom_aria"]["root"].update(children=[None]), "DOM node"),
    (lambda r: r["dom_aria"].update(content_sha256="0" * 64), "unknown fields"),
    (lambda r: r["dom_aria"]["root"].update(role="unsupported_role"), "no components|unsupported|Root node was rejected"),
    (lambda r: r["dom_aria"]["root"].update(actions=["teleport"]), "unsupported"),
])
def test_invalid_or_silently_dropped_input_is_rejected(mutation, match):
    row = native_row()
    mutation(row)
    with pytest.raises(ValueError, match=match):
        prepare_ui_training_row(row)


def test_bad_cid_and_changed_preimage_cannot_be_claimed_verified():
    for alteration in ("cid", "preimage"):
        row = native_row()
        if alteration == "cid":
            row["interface"]["claimed_interface_cid"] = "bafkreifake"
        else:
            row["interface"]["descriptor"]["version"] = "2.0.0"
        with pytest.raises(ValueError):
            prepare_ui_training_row(row)


@pytest.mark.parametrize("change", [
    lambda d: d["methods"].append(deepcopy(d["methods"][0])),
    lambda d: d["methods"][0].pop("input_schema"),
    lambda d: d["methods"][0].update(output_schema={"type": ["object", "null"]}),
    lambda d: d["methods"][0].update(input_schema={"type": "string"}),
    lambda d: d["methods"][0].update(output_schema={"type": "object", "required": "bad"}),
    lambda d: d["methods"][0].update(output_schema={"type": "object", "$ref": "https://example.invalid/schema"}),
    lambda d: d["methods"][0].update(output_schema={"type": "object", "$schema": "https://example.invalid/draft"}),
    lambda d: d["methods"][0].update(streaming=True),
    lambda d: d["methods"][0].update(unknown_extension=True),
])
def test_interface_requires_unique_named_methods_and_inline_typed_schemas(change):
    row = native_row()
    change(row["interface"]["descriptor"])
    with pytest.raises(UITrainingInputError):
        prepare_ui_training_row(row)


def test_absent_events_and_behavior_do_not_invent_event_targets():
    row = native_row()
    row["events"] = []
    row["behavior"] = None
    payload = prepare_ui_training_row(row).target.to_dict()
    assert {p["projection_id"] for p in payload["projections"]} == {
        "ui_ux_ir:flogic", "ui_ux_ir:tdfol", INTERFACE_PROJECTION}
    assert payload["ready_for_training"] is True
    assert payload["qualified"] is False


def test_schema_draft_dispatch_and_recursive_identity_alias_drift():
    row = native_row()
    schema = row["interface"]["descriptor"]["methods"][0]["input_schema"]
    schema["$schema"] = "http://json-schema.org/draft-04/schema#"
    schema["properties"]["amount"] = {"type": "number", "minimum": 0, "exclusiveMinimum": True}
    _rehash(row)
    # A real Draft 4 exclusiveMinimum is boolean; newer drafts require a number.
    assert prepare_ui_training_row(row).target.to_dict()["ready_for_training"] is True
    schema["properties"]["inputSchema"] = {"type": "string"}
    _rehash(row)
    with pytest.raises(UITrainingInputError, match="normalization changed inline schema semantics"):
        prepare_ui_training_row(row)


def test_json_and_row_bounds_are_enforced():
    row = native_row()
    row["dom_aria"]["root"]["description"] = "x" * MAX_ROW_BYTES
    with pytest.raises(UITrainingInputError, match="byte bound"):
        prepare_ui_training_row(row)
    row = native_row()
    row["events"][0]["confidence"] = float("nan")
    with pytest.raises(UITrainingInputError, match="nonfinite"):
        prepare_ui_training_row(row)
    row = native_row()
    node = row["dom_aria"]["root"]
    for index in range(30):
        child = {"node_id": f"nested:{index}", "role": "group"}
        node["children"] = [child]
        node = child
    with pytest.raises(UITrainingInputError, match="nesting"):
        prepare_ui_training_row(row)
