"""Local mediation and schema checks never become transport/authentication."""

from copy import deepcopy
from dataclasses import replace

import pytest

from ipfs_datasets_py.logic.ui_ux_ir.runtime.events import (
    CanonicalInteractionEvent, EventKind, EventProvenance,
)
from ipfs_datasets_py.logic.ui_ux_ir.runtime.idl_projection import (
    project_idl_request, project_idl_result,
)
from ipfs_datasets_py.logic.ui_ux_ir.runtime.mediator import (
    ActorContext, ActorKind, MediationOutcome, PolicyNorm, PolicyVerdict,
    RuntimeMediationContext, UIMediator,
)
from ipfs_datasets_py.logic.ui_ux_ir.schema import UIIRValidationError
from ipfs_datasets_py.logic.ui_ux_ir.source_adapters.mcp_idl import adapt_mcp_idl_to_uiir


def _descriptor():
    return {
        "name": "catalog", "namespace": "test", "version": "1",
        "methods": [{
            "name": "list_items",
            "input_schema": {
                "type": "object", "properties": {"limit": {"type": "integer", "minimum": 1}},
                "required": ["limit"], "additionalProperties": False,
            },
            "output_schema": {
                "type": "object", "properties": {"items": {"type": "array", "items": {"type": "string"}}},
                "required": ["items"], "additionalProperties": False,
            },
        }],
    }


def _decision(descriptor=None, verdict=PolicyVerdict.ALLOW):
    binding = adapt_mcp_idl_to_uiir(descriptor or _descriptor()).action_bindings[0]
    event = CanonicalInteractionEvent(
        event_id="event:1", kind=EventKind.ACTIVATE, target_component_id="component:list",
        timestamp_ms=1000, provenance=EventProvenance.HUMAN, capability_id="cap:pointer", consent_ok=True,
    )
    context = RuntimeMediationContext(
        declaration_digest="decl:abc", projection_id="projection:web", state_version=3,
        actor=ActorContext("actor:human", ActorKind.HUMAN),
        policy_norms=(PolicyNorm("policy:list", verdict, binding_id=binding.binding_id),),
    )
    return UIMediator().mediate(binding, event, context)


def _project(decision=None, descriptor=None, arguments=None, **overrides):
    descriptor = descriptor or _descriptor()
    decision = decision or _decision(descriptor)
    expected = dict(
        expected_request_id=(decision.invocation_request.request_id
                             if getattr(decision, "invocation_request", None) else "inv:denied"),
        expected_event_id="event:1", expected_declaration_digest="decl:abc",
        expected_projection_id="projection:web", expected_state_version=3,
    )
    expected.update(overrides)
    return project_idl_request(decision, descriptor, {"limit": 2} if arguments is None else arguments, **expected)


def _result(request, **overrides):
    fields = dict(
        request_id=request.invocation_request.request_id, request_sha256=request.sha256,
        interface_cid=request.invocation_request.mcp_idl_interface_cid,
        method_name="list_items", result={"items": ["one"]},
    )
    fields.update(overrides)
    return project_idl_result(request, _descriptor(), **fields)


def test_real_mediator_request_and_result_are_correlated_data_only():
    arguments = {"limit": 2}
    request = _project(arguments=arguments)
    arguments["limit"] = 9
    assert request.to_dict()["arguments"] == {"limit": 2}
    assert request.to_dict()["execution_grant"] is None
    assert request.to_dict()["transport_executed"] is False
    output = {"items": ["one"]}
    evidence = _result(request, result=output)
    output["items"].append("mutated")
    assert evidence.to_dict()["result"] == {"items": ["one"]}
    assert evidence.to_dict()["schema_validated"] is True
    assert evidence.to_dict()["backend_authenticated"] is False
    assert evidence.to_dict()["state_mutation_applied"] is False
    assert evidence.to_dict()["execution_grant"] is None
    assert evidence.arguments_sha256 == request.arguments_sha256


@pytest.mark.parametrize("outcome", [item for item in MediationOutcome if item is not MediationOutcome.ALLOW])
def test_every_nonallow_outcome_fails_closed(outcome):
    decision = replace(_decision(), outcome=outcome, can_execute=False, invocation_request=None)
    with pytest.raises(UIIRValidationError, match="Only ALLOW"):
        _project(decision)


@pytest.mark.parametrize("field,value", [
    ("expected_request_id", "different"), ("expected_event_id", "event:old"),
    ("expected_declaration_digest", "decl:old"), ("expected_projection_id", "projection:old"),
    ("expected_state_version", 2), ("expected_state_version", True),
])
def test_stale_or_mismatched_runtime_correlation_rejected(field, value):
    with pytest.raises(UIIRValidationError):
        _project(**{field: value})


@pytest.mark.parametrize("field,value", [
    ("mcp_idl_interface_cid", "sha256:" + "1" * 64),
    ("mcp_idl_method_name", "absent"), ("binding_id", "bind:other"),
    ("policy_norm_id", "policy:other"), ("intent_document_id", "other-family"),
])
def test_forged_invocation_fields_rejected(field, value):
    decision = _decision()
    invocation = replace(decision.invocation_request, **{field: value})
    with pytest.raises(UIIRValidationError):
        _project(replace(decision, invocation_request=invocation))


def test_descriptor_drift_duplicate_names_and_absent_method_rejected():
    descriptor = _descriptor()
    decision = _decision(descriptor)
    descriptor["methods"][0]["input_schema"]["required"] = []
    with pytest.raises(UIIRValidationError):
        _project(decision, descriptor)
    descriptor = _descriptor()
    descriptor["methods"].append(deepcopy(descriptor["methods"][0]))
    with pytest.raises(UIIRValidationError, match="unique"):
        _project(descriptor=descriptor)
    decision = _decision()
    invocation = replace(decision.invocation_request, mcp_idl_method_name="absent",
                         program_target_ref=f"mcp:{decision.invocation_request.mcp_idl_interface_cid}#absent")
    with pytest.raises(UIIRValidationError, match="absent"):
        _project(replace(decision, invocation_request=invocation))


@pytest.mark.parametrize("arguments", [{"limit": "2"}, {"limit": True}, {"limit": 0}, {}, {"limit": float("nan")}, {1: 2}])
def test_bad_argument_types_and_non_json_rejected(arguments):
    with pytest.raises(UIIRValidationError):
        _project(arguments=arguments)


@pytest.mark.parametrize("schema", [
    {"$ref": "https://invalid.example/schema.json"}, {"$ref": "#/$defs/value"},
    {"$dynamicRef": "https://invalid.example/schema.json"},
    {"properties": {"limit": {"$recursiveRef": "#"}}},
    {"$schema": "https://invalid.example/meta-schema"}, {"type": "invalid-type"},
    "ipfs://cid-only-schema",
])
def test_reference_and_unsupported_schemas_fail_without_fetch(schema, monkeypatch):
    import socket
    def forbidden(*args, **kwargs):
        pytest.fail("schema validation attempted network access")
    monkeypatch.setattr(socket, "create_connection", forbidden)
    descriptor = _descriptor()
    descriptor["methods"][0]["input_schema"] = schema
    with pytest.raises(UIIRValidationError):
        _project(descriptor=descriptor)


@pytest.mark.parametrize("key", ["input_schema", "output_schema"])
def test_both_inline_method_schemas_required(key):
    descriptor = _descriptor()
    del descriptor["methods"][0][key]
    with pytest.raises(UIIRValidationError, match="Both inline"):
        _project(descriptor=descriptor)


@pytest.mark.parametrize("field,value", [
    ("request_id", "different"), ("request_sha256", "0" * 64),
    ("interface_cid", "different"), ("method_name", "different"),
    ("result", {"items": [1]}), ("result", {"missing": []}),
])
def test_result_correlation_and_schema_rejections(field, value):
    with pytest.raises(UIIRValidationError):
        _result(_project(), **{field: value})


def test_request_digest_binds_arguments_beyond_mediator_request_id():
    one, two = _project(arguments={"limit": 1}), _project(arguments={"limit": 2})
    assert one.invocation_request.request_id == two.invocation_request.request_id
    assert one.sha256 != two.sha256
    with pytest.raises(UIIRValidationError, match="correlation"):
        _result(two, request_sha256=one.sha256)


def test_target_envelope_or_loss_is_not_a_decision():
    with pytest.raises(UIIRValidationError, match="UIMediationDecision"):
        _project({"loss": 0, "outcome": "allow"}, expected_request_id="inv:1")


def test_streaming_method_needs_its_own_protocol():
    descriptor = _descriptor()
    descriptor["methods"][0]["streaming"] = True
    with pytest.raises(UIIRValidationError, match="Streaming"):
        _project(descriptor=descriptor)


def test_wire_schema_aliases_work_but_conflicts_and_semantic_renames_fail():
    descriptor = _descriptor()
    method = descriptor["methods"][0]
    method["inputSchema"] = method.pop("input_schema")
    method["outputSchema"] = method.pop("output_schema")
    assert _project(descriptor=descriptor).to_dict()["arguments"] == {"limit": 2}
    method["input_schema"] = {"type": "null"}
    with pytest.raises(UIIRValidationError, match="Conflicting"):
        _project(descriptor=descriptor)
    descriptor = _descriptor()
    descriptor["methods"][0]["input_schema"]["properties"]["inputSchema"] = {"type": "string"}
    with pytest.raises(UIIRValidationError, match="normalization changed"):
        _project(descriptor=descriptor)


def test_request_snapshots_expected_effect_ids():
    decision = _decision()
    effects = ["effect:load"]
    decision = replace(decision, invocation_request=replace(decision.invocation_request, expected_effect_ids=effects))
    request = _project(decision)
    digest = request.sha256
    effects.append("effect:injected")
    assert request.sha256 == digest
    assert request.invocation_request.expected_effect_ids == ("effect:load",)
