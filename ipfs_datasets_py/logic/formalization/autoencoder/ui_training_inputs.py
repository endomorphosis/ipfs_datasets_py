"""Closed JSON inputs for source-bound native UI structural feature training.

Interface identity and explicit component/method joins are checked here. A
descriptor is not a grant, DOM affordances are not observed events, and a
supplied state machine is not an observed execution trace. No source, schema,
image, or interface is fetched or executed by this adapter.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
import hashlib
import json
import math
import re
from types import MappingProxyType
from typing import Any

from .domain_targets import DomainTargetEnvelope, build_target_envelope
from .ui_targets import prepare_ui_targets

SCHEMA = "ui-bound-training-row/v1"
INTERFACE_PROJECTION = "ui_ux_ir:interface_bindings"
MAX_ROW_BYTES = 1_048_576
MAX_NODES = 256
MAX_METHODS = 128
MAX_BINDINGS = 256
MAX_EVENTS = 256
MAX_STATES = 128
MAX_TRANSITIONS = 256
MAX_DEPTH = 24
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,255}\Z")


class UITrainingInputError(ValueError):
    """A malformed or insufficiently joined training source was rejected."""


def _require(condition: Any, message: str) -> None:
    if not condition:
        raise UITrainingInputError(message)


def _object(value: Any, allowed: set[str], required: set[str], label: str) -> dict:
    _require(type(value) is dict, f"{label} must be a JSON object")
    _require(not set(value) - allowed, f"{label} has unknown fields: {sorted(set(value) - allowed)}")
    _require(required <= set(value), f"{label} is missing required fields: {sorted(required - set(value))}")
    return value


def _text(value: Any, label: str, *, identifier: bool = False) -> str:
    _require(type(value) is str and 0 < len(value) <= 4096 and value.strip() == value,
             f"{label} must be nonempty trimmed text")
    if identifier:
        _require(_ID.fullmatch(value), f"{label} must be a bounded identifier")
    return value


def _array(value: Any, maximum: int, label: str, *, nonempty: bool = False) -> list:
    _require(type(value) is list and len(value) <= maximum and (value or not nonempty),
             f"{label} must be a bounded {'nonempty ' if nonempty else ''}array")
    return value


def _integer(value: Any, label: str, *, minimum: int = 0) -> int:
    _require(type(value) is int and minimum <= value <= 2**53 - 1, f"{label} must be a bounded integer")
    return value


def _boolean(value: Any, label: str) -> bool:
    _require(type(value) is bool, f"{label} must be boolean")
    return value


def _wire(value: Any) -> bytes:
    def check(item: Any, depth: int) -> None:
        _require(depth <= MAX_DEPTH, "training row exceeds nesting bound")
        if type(item) is dict:
            _require(all(type(key) is str for key in item), "JSON object keys must be strings")
            for child in item.values():
                check(child, depth + 1)
        elif type(item) is list:
            for child in item:
                check(child, depth + 1)
        else:
            _require(item is None or type(item) in {str, int, float, bool}, "training input must contain JSON values only")
            if type(item) is float:
                _require(math.isfinite(item), "training input contains nonfinite numbers")
    check(value, 0)
    body = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()
    _require(len(body) <= MAX_ROW_BYTES, "training row exceeds byte bound")
    return body


def _ids(value: Any, maximum: int, label: str, *, nonempty: bool = False) -> tuple[str, ...]:
    result = tuple(_text(item, label, identifier=True) for item in _array(value, maximum, label, nonempty=nonempty))
    _require(len(result) == len(set(result)), f"{label} contains duplicate IDs")
    return result


@dataclass(frozen=True, slots=True)
class PreparedUITrainingRow:
    target: DomainTargetEnvelope
    group_id: str
    source_id: str
    input_sha256: str
    provenance: Mapping[str, str]
    document: Any

    def __post_init__(self) -> None:
        object.__setattr__(self, "provenance", MappingProxyType(dict(self.provenance)))


def _dom(value: dict):
    from ipfs_datasets_py.logic.ui_ux_ir.source_adapters.dom_aria import adapt_dom_aria_to_uiir
    allowed = {"document_id", "title", "root", "source_uri", "source_id", "source_revision", "locale", "review_status"}
    _object(value, allowed, {"document_id", "title", "root"}, "dom_aria")
    _text(value["document_id"], "dom_aria.document_id", identifier=True)
    _text(value["title"], "dom_aria.title")
    for field in set(value) - {"root", "document_id", "title"}:
        _text(value[field], f"dom_aria.{field}")
    count = 0
    seen: set[str] = set()
    def node(item: Any) -> None:
        nonlocal count
        count += 1
        _require(count <= MAX_NODES, "DOM node count exceeds bound")
        fields = {"node_id", "role", "name", "description", "value", "states", "relationships", "actions",
                  "children", "focus_order", "validation", "live", "tag_name", "text_content"}
        _object(item, fields, {"node_id", "role"}, "DOM node")
        identifier = _text(item["node_id"], "DOM node_id", identifier=True)
        _require(identifier not in seen, "duplicate DOM node_id")
        seen.add(identifier)
        for field in {"role", "name", "description", "value", "tag_name", "text_content"} & set(item):
            _require(type(item[field]) is str, f"DOM {field} must be a string")
        _text(item["role"], "DOM role")
        for field in ("states", "relationships"):
            if field in item:
                _require(type(item[field]) is dict, f"DOM {field} must be an object")
                for key, val in item[field].items():
                    _text(key, f"DOM {field} key")
                    if field == "states":
                        _require(type(val) is str, "DOM state values must be explicit strings")
                    else:
                        _ids(val, MAX_NODES, "DOM relationship targets")
        if "actions" in item:
            _ids(item["actions"], 16, "DOM actions")
        if "focus_order" in item:
            _integer(item["focus_order"], "DOM focus_order")
        if "validation" in item:
            v = _object(item["validation"], {"valid", "message", "required", "invalid_state"}, set(), "DOM validation")
            for key in {"valid", "required"} & set(v):
                _boolean(v[key], f"DOM validation.{key}")
            for key in {"message", "invalid_state"} & set(v):
                _require(type(v[key]) is str, f"DOM validation.{key} must be text")
        if "live" in item:
            v = _object(item["live"], {"politeness", "atomic", "relevant"}, set(), "DOM live")
            if "atomic" in v:
                _boolean(v["atomic"], "DOM live.atomic")
            for key in {"politeness", "relevant"} & set(v):
                _require(type(v[key]) is str, f"DOM live.{key} must be text")
        for child in _array(item.get("children", []), MAX_NODES, "DOM children"):
            node(child)
    node(value["root"])
    # Bind the actual supplied snapshot, not a caller-claimed hash or the
    # native adapter's partial fallback digest. This is not original HTML.
    snapshot_sha = hashlib.sha256(_wire(value)).hexdigest()
    result = adapt_dom_aria_to_uiir({**value, "content_sha256": snapshot_sha})
    _require(bool(result.components), "DOM produced no components")
    _require(not result.losses, "DOM has unsupported or sanitized semantics; retain them outside this strict training profile")
    _require({component.component_id for component in result.components} == seen,
             "DOM node IDs must already be canonical component: identifiers; implicit ID normalization is unsupported")
    return result, snapshot_sha


def _interface(value: dict):
    from ipfs_datasets_py.logic.ui_ux_ir.runtime.idl_projection import _schema_validator
    from ipfs_datasets_py.logic.ui_ux_ir.source_adapters.mcp_idl import adapt_mcp_idl_to_uiir
    from ipfs_datasets_py.logic.ui_ux_ir.source_adapters.mcp_idl_identity import (
        IDENTITY_AFFECTING_FIELDS, METHOD_IDENTITY_AFFECTING_FIELDS, verify_interface_preimage,
    )
    _object(value, {"descriptor", "claimed_interface_cid"}, {"descriptor", "claimed_interface_cid"}, "interface")
    descriptor = _object(value["descriptor"], set(IDENTITY_AFFECTING_FIELDS) | {"profile"},
                         {"name", "namespace", "version", "methods"}, "interface descriptor")
    for key in ("name", "namespace", "version"):
        _text(descriptor[key], f"interface descriptor.{key}")
    cid = _text(value["claimed_interface_cid"], "claimed_interface_cid")
    methods: dict[str, dict] = {}
    for method in _array(descriptor["methods"], MAX_METHODS, "interface methods", nonempty=True):
        _object(method, set(METHOD_IDENTITY_AFFECTING_FIELDS), {"name", "input_schema", "output_schema"}, "interface method")
        name = _text(method["name"], "method.name", identifier=True)
        _require(name not in methods, "duplicate interface method name")
        methods[name] = method
        if "streaming" in method:
            _boolean(method["streaming"], "method.streaming")
            _require(not method["streaming"], "streaming methods require a separate typed training profile")
        for field in ("input_schema", "output_schema"):
            schema = method[field]
            _require(type(schema) is dict and type(schema.get("type")) is str and schema["type"] in {"object", "array", "string", "number", "integer", "boolean", "null"},
                     f"method.{field} requires an explicit JSON Schema type")
            try:
                _schema_validator(schema)
            except ValueError as exc:
                raise UITrainingInputError(f"invalid method.{field}: {exc}") from exc
        _require(method["input_schema"]["type"] == "object", "method input_schema must describe an object")
    adapted = adapt_mcp_idl_to_uiir(descriptor, claimed_interface_cid=cid)
    verified = verify_interface_preimage(cid, descriptor)
    canonical_methods = {method["name"]: method for method in json.loads(verified.canonical_bytes)["methods"]}
    for name, method in methods.items():
        for field in ("input_schema", "output_schema"):
            _require(_wire(method[field]) == _wire(canonical_methods[name][field]),
                     "identity normalization changed inline schema semantics")
    return adapted, methods


def _events(items: Any, components: set[str]):
    from ipfs_datasets_py.logic.ui_ux_ir.runtime.events import CanonicalInteractionEvent, EventKind, EventProvenance, validate_event
    from ipfs_datasets_py.logic.ui_ux_ir.model.modality import CANONICAL_INPUT_CAPABILITIES
    required = {"event_id", "kind", "target_component_id", "timestamp_ms", "provenance", "capability_id", "consent_ok", "source_adapter"}
    events = []
    seen = set()
    for item in _array(items, MAX_EVENTS, "events"):
        _object(item, required | {"sequence", "confidence"}, required, "event")
        event_id = _text(item["event_id"], "event_id", identifier=True)
        _require(event_id not in seen, "duplicate event_id")
        seen.add(event_id)
        component_id = _text(item["target_component_id"], "event target_component_id", identifier=True)
        capability_id = _text(item["capability_id"], "event capability_id", identifier=True)
        _require(component_id in components, "event targets unknown component")
        _require(capability_id in CANONICAL_INPUT_CAPABILITIES, "event names unsupported input capability")
        _integer(item["timestamp_ms"], "event timestamp_ms")
        _integer(item.get("sequence", 0), "event sequence")
        _boolean(item["consent_ok"], "event consent_ok")
        _text(item["source_adapter"], "event source_adapter")
        confidence = item.get("confidence")
        _require(confidence is None or type(confidence) in {int, float} and 0 <= confidence <= 1,
                 "event confidence must be numeric in [0, 1]")
        events.append(validate_event(CanonicalInteractionEvent(
            **{**item, "kind": EventKind(item["kind"]), "provenance": EventProvenance(item["provenance"])})))
    return tuple(events)


def _behavior(value: Any):
    from ipfs_datasets_py.logic.ui_ux_ir.model.behavior import BehaviorModel, BehaviorState, BehaviorTransition, validate_behavior_model
    if value is None:
        return None
    required = {"model_id", "states", "transitions", "initial_state_ids"}
    _object(value, required, required, "behavior")
    _text(value["model_id"], "behavior.model_id", identifier=True)
    states, transitions, seen = [], [], set()
    for state in _array(value["states"], MAX_STATES, "behavior states", nonempty=True):
        _object(state, {"state_id", "label", "terminal"}, {"state_id"}, "behavior state")
        _text(state["state_id"], "state_id", identifier=True)
        _boolean(state.get("terminal", False), "state terminal")
        _require(type(state.get("label", "")) is str, "state label must be text")
        states.append(BehaviorState(**state))
    fields = {"transition_id", "source_state_ids", "target_state_id", "event_id"}
    for item in _array(value["transitions"], MAX_TRANSITIONS, "behavior transitions", nonempty=True):
        _object(item, fields | {"timeout_ms"}, fields, "behavior transition")
        for key in ("transition_id", "target_state_id", "event_id"):
            _text(item[key], f"transition.{key}", identifier=True)
        _require(item["transition_id"] not in seen, "duplicate transition_id")
        seen.add(item["transition_id"])
        if "timeout_ms" in item:
            _integer(item["timeout_ms"], "transition.timeout_ms")
        sources = _ids(item["source_state_ids"], MAX_STATES, "transition sources", nonempty=True)
        transitions.append(BehaviorTransition(**{**item, "source_state_ids": sources}))
    return validate_behavior_model(BehaviorModel(model_id=value["model_id"], states=tuple(states),
        transitions=tuple(transitions), initial_state_ids=_ids(value["initial_state_ids"], MAX_STATES,
            "initial_state_ids", nonempty=True)))


def prepare_ui_training_row(row: Mapping[str, Any]) -> PreparedUITrainingRow:
    """Validate a closed JSON row and prepare actual native feature targets.

    Events and state-machine declarations are consumed only when supplied.
    Their real-world authenticity and mutual behavior consistency are not
    established here. Provenance split/group declarations remain explicit for
    the caller's corpus-level leakage policy.
    """
    from ipfs_datasets_py.logic.ui_ux_ir.model.components import SemanticComponent, CompositionRelationship, UIComponentGraph, validate_component_graph
    from ipfs_datasets_py.logic.ui_ux_ir.model.bindings import UIActionBinding, RiskClass, ConfirmationClass, IdempotencyClass, validate_action_binding
    from ipfs_datasets_py.logic.ui_ux_ir.formalize.roundtrip import RoundTripDocument
    required = {"schema_version", "provenance", "dom_aria", "interface", "bindings", "behavior", "events"}
    _object(row, required, required, "training row")
    raw = _wire(row)
    row = json.loads(raw)  # Freeze the caller's input before the native adapters run.
    _require(row["schema_version"] == SCHEMA, "unsupported training row schema")
    pfields = {"dataset", "revision", "split", "row_id", "group_id"}
    provenance = _object(row["provenance"], pfields, pfields, "provenance")
    for key, value in provenance.items():
        _text(value, f"provenance.{key}", identifier=True)
    _require(provenance["revision"].lower() not in {"main", "master", "latest"}, "immutable provenance revision required")
    _require(provenance["split"] in {"train", "validation", "valid", "tuning", "test", "canary"}, "unknown provenance split")
    dom, snapshot_sha = _dom(row["dom_aria"])
    interface, methods = _interface(row["interface"])
    ids = {component.component_id for component in dom.components}
    bindings, joins, bound_ids, action_ids, component_actions = [], [], set(), set(), set()
    method_bindings = {binding.program_ref.mcp_idl_method_name: binding for binding in interface.action_bindings}
    binding_fields = {"binding_id", "action_id", "component_id", "dom_action", "method_name", "risk_class", "confirmation_class", "idempotency"}
    for item in _array(row["bindings"], MAX_BINDINGS, "bindings", nonempty=True):
        _object(item, binding_fields, binding_fields, "binding")
        for key in ("binding_id", "action_id", "component_id", "dom_action", "method_name"):
            _text(item[key], f"binding.{key}", identifier=True)
        _require(item["component_id"] in ids, "binding references unknown component")
        _require(item["dom_action"] in dom.actions_by_node.get(item["component_id"], ()), "binding DOM action is absent from component affordances")
        _require(item["method_name"] in methods, "binding references unknown interface method")
        _require(item["binding_id"] not in bound_ids and item["action_id"] not in action_ids, "duplicate binding/action ID")
        join = (item["component_id"], item["dom_action"])
        _require(join not in component_actions, "ambiguous component/action method join")
        component_actions.add(join); bound_ids.add(item["binding_id"]); action_ids.add(item["action_id"])
        source_binding = method_bindings[item["method_name"]]
        binding = validate_action_binding(UIActionBinding(
            binding_id=item["binding_id"], action_id=item["action_id"], program_ref=source_binding.program_ref,
            risk_class=RiskClass(item["risk_class"]), confirmation_class=ConfirmationClass(item["confirmation_class"]),
            idempotency=IdempotencyClass(item["idempotency"]), source_ref_ids=tuple(source.ref_id for source in dom.sources)))
        bindings.append(binding)
        joins.append({**item, "interface_cid": interface.interface_cid,
                      "method_contract": methods[item["method_name"]]})
    component_models = tuple(replace(SemanticComponent.from_envelope(component),
        program_binding_ids=tuple(item["binding_id"] for item in joins if item["component_id"] == component.component_id))
        for component in dom.components)
    graph = validate_component_graph(UIComponentGraph(components=component_models,
        relationships=tuple(CompositionRelationship.from_envelope(edge) for edge in dom.composition_edges),
        entry_component_ids=dom.entry_components))
    document = RoundTripDocument(document_id=row["dom_aria"]["document_id"], component_graph=graph,
        action_bindings=tuple(bindings), behavior_model=_behavior(row["behavior"]), events=_events(row["events"], ids))
    native = prepare_ui_targets(document).to_dict()
    input_sha = hashlib.sha256(raw).hexdigest()
    projections = native["projections"] + [{
        "projection_id": INTERFACE_PROJECTION, "view_id": "verified_interface_bindings",
        "logic_family": "frame_logic", "profile": "ui-verified-interface-bindings/v1", "properties": [],
        "view_role": "interface_method_contracts", "representation_kind": "native_verified_binding_records",
        "producer_id": "ui-bound-training-inputs/v1",
        "expression": {"identity_profile": interface.profile, "interface_cid": interface.interface_cid,
                       "bindings": sorted(joins, key=lambda item: item["binding_id"])},
    }]
    validation = native["validation"] + [{
        "validator_id": "ui_ux.verified_interface_join", "stage": "target", "status": "passed", "required": True,
        "details": {"input_sha256": input_sha, "native_document_sha256": native["source_digest"],
                    "dom_snapshot_sha256": snapshot_sha, "interface_cid": interface.interface_cid,
                    "method_count": len(methods), "binding_count": len(joins), "provenance": provenance,
                    "method_schema_validation": "inline_locally_supported_draft_shape_only", "execution_grant": None},
    }]
    gaps = native["qualification_gaps"] + [{
        "code": "ui_ux.source_binding_is_not_semantic_verification",
        "details": "DOM snapshot and MCP preimage identity do not verify application behavior or authorize invocation",
    }, {"code": "ui_ux.supplied_events_not_independently_attested"},
       {"code": "ui_ux.interface_binding_family_syntax_not_checked"},
       {"code": "ui_ux.dom_accessibility_and_state_fields_not_fully_projected",
        "details": "native frame view covers component roles and relationships; names, values, state, and feedback remain in source identity"},
       {"code": "ui_ux.idl_ui_semantics_not_derived", "losses": [vars(loss) if hasattr(loss, "__dict__") else
         {"loss_id": loss.loss_id, "path": loss.path, "reason": loss.reason, "disposition": loss.disposition}
         for loss in interface.losses]}]
    target = build_target_envelope(domain_id="ui_ux_ir", source_digest=input_sha, projections=projections,
        validation=validation, unsupported=native["unsupported"], qualification_gaps=gaps)
    return PreparedUITrainingRow(target=target, group_id=provenance["group_id"], source_id=provenance["row_id"],
        input_sha256=input_sha, provenance=provenance, document=document)


__all__ = ["SCHEMA", "INTERFACE_PROJECTION", "PreparedUITrainingRow", "UITrainingInputError", "prepare_ui_training_row"]
