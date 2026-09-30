"""Pure, locally trusted UI mediation → MCP-IDL request/result projections.

This boundary verifies descriptor preimages, inline JSON schemas and correlation;
it neither transports a request nor authenticates a caller/backend. A Python
``UIMediationDecision`` supplied by a caller is not an authentication credential.
Callers must obtain it from their trusted mediator with current policy/consent
and independently authenticate any executor and response. These data-only
projections never grant execution authority or mutate DOM/runtime state.

Only locally available JSON Schema drafts and inline schemas are supported.
All reference keywords are rejected (including local references), so schema
validation cannot fetch a resource. Format annotations are not semantic proof.
Streaming responses, error envelopes and CID-only schemas need separate typed
protocols; this module handles one successful result matching an output schema.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, replace
from typing import Any, Mapping

from ..schema import ProgramBindingTargetKind, UIIRValidationError
from ..source_adapters.mcp_idl_identity import MCPIDLIdentityError, verify_interface_preimage
from .mediator import MediationOutcome, UIMediationDecision, UIInvocationRequest

SCHEMA_VERSION = "ui-ux-ir/idl-runtime-projection@1"


def _json_text(value: Any) -> str:
    """Freeze strict JSON without coercing mapping keys or non-JSON objects."""
    def check(item: Any) -> None:
        if item is None or type(item) in (str, bool, int):
            return
        if type(item) is float and math.isfinite(item):
            return
        if isinstance(item, Mapping):
            if not all(type(key) is str for key in item):
                raise UIIRValidationError("JSON object keys must be strings")
            for child in item.values():
                check(child)
            return
        if type(item) in (list, tuple):
            for child in item:
                check(child)
            return
        raise UIIRValidationError("Projection values must be finite JSON data")

    try:
        check(value)
        return json.dumps(value, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=True, allow_nan=False)
    except (TypeError, ValueError, RecursionError) as exc:
        raise UIIRValidationError("Projection values must be finite JSON data") from exc


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _schema_validator(schema: Any):
    # Import only the installed local implementation. Never resolve an external
    # $schema URI or a $ref, even if a permissive jsonschema registry is installed.
    from jsonschema import Draft4Validator, Draft6Validator, Draft7Validator
    from jsonschema import Draft201909Validator, Draft202012Validator
    from jsonschema.exceptions import SchemaError

    def reject_refs(node: Any) -> None:
        if isinstance(node, dict):
            if {"$ref", "$dynamicRef", "$recursiveRef"}.intersection(node):
                raise UIIRValidationError("Referenced schemas are unsupported; supply inline schemas")
            for value in node.values():
                reject_refs(value)
        elif isinstance(node, list):
            for value in node:
                reject_refs(value)

    if type(schema) not in (dict, bool):
        raise UIIRValidationError("Method input/output schemas must be inline JSON schemas")
    reject_refs(schema)
    validators = (Draft4Validator, Draft6Validator, Draft7Validator,
                  Draft201909Validator, Draft202012Validator)
    known = {str(cls.META_SCHEMA.get("$id", cls.META_SCHEMA.get("id"))).rstrip("#"): cls
             for cls in validators}
    draft = schema.get("$schema") if isinstance(schema, dict) else None
    if draft is not None and (not isinstance(draft, str) or draft.rstrip("#") not in known):
        raise UIIRValidationError("Unknown JSON Schema draft; external schema retrieval is forbidden")
    cls = known[draft.rstrip("#")] if draft is not None else Draft202012Validator
    try:
        cls.check_schema(schema)
    except SchemaError as exc:
        raise UIIRValidationError("Malformed inline JSON schema") from exc
    return cls(schema)


def _validate_instance(schema: Any, value: Any, label: str) -> None:
    error = next(_schema_validator(schema).iter_errors(value), None)
    if error is not None:
        # Do not embed arguments/results (possibly sensitive) in error messages.
        raise UIIRValidationError(f"{label} does not satisfy its verified method schema")


def _method_schemas(descriptor: Mapping[str, Any], interface_cid: str,
                    method_name: str) -> tuple[str, Any, Any]:
    snapshot = json.loads(_json_text(descriptor))
    try:
        identity = verify_interface_preimage(interface_cid, snapshot)
    except MCPIDLIdentityError as exc:
        raise UIIRValidationError(f"MCP-IDL descriptor identity failed: {exc.reason_code}") from exc
    # Schemas are read from the exact identity-bound snapshot, never an unbound
    # mutable descriptor or an unrelated UI target envelope.
    methods = identity.snapshot.get("methods", ())
    seen: set[str] = set()
    selected = None
    for method in methods:
        if not isinstance(method, Mapping):
            raise UIIRValidationError("Descriptor methods must be objects")
        name = method.get("name")
        if not isinstance(name, str) or not name.strip() or name in seen:
            raise UIIRValidationError("Descriptor method names must be nonempty and unique")
        seen.add(name)
        if name == method_name:
            selected = method
    if selected is None:
        raise UIIRValidationError("Invocation method is absent from the verified descriptor")
    if selected.get("streaming"):
        raise UIIRValidationError("Streaming methods require a separate result protocol")
    if "input_schema" not in selected or "output_schema" not in selected:
        raise UIIRValidationError("Both inline input_schema and output_schema are required")
    # Frozen identity maps/tuples become ordinary JSON for the schema validator.
    schemas = json.loads(identity.canonical_bytes)["methods"]
    method = next(item for item in schemas if item["name"] == method_name)
    input_schema, output_schema = method["input_schema"], method["output_schema"]
    raw_method = next(item for item in snapshot["methods"] if item["name"] == method_name)
    # The shared identity profile recursively normalizes known wire aliases.
    # Never silently turn a JSON Schema property name into another property.
    for key, alias, schema in (("input_schema", "inputSchema", input_schema),
                               ("output_schema", "outputSchema", output_schema)):
        if key in raw_method and alias in raw_method and raw_method[key] != raw_method[alias]:
            raise UIIRValidationError("Conflicting method schema aliases")
        original = raw_method.get(key, raw_method.get(alias))
        if _json_text(original) != _json_text(schema):
            raise UIIRValidationError("Identity normalization changed inline schema semantics")
    _schema_validator(input_schema)
    _schema_validator(output_schema)
    return identity.sha256_hex, input_schema, output_schema


@dataclass(frozen=True, slots=True)
class IDLRequestProjection:
    """Immutable declaration; its digest also binds arguments absent from UI IDs."""

    invocation_request: UIInvocationRequest
    decision_id: str
    descriptor_sha256: str
    input_schema_sha256: str
    output_schema_sha256: str
    arguments_json: str

    @property
    def arguments_sha256(self) -> str:
        return _digest(self.arguments_json)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "kind": "request_declaration",
            "invocation_request": self.invocation_request.to_dict(),
            "decision_id": self.decision_id,
            "descriptor_sha256": self.descriptor_sha256,
            "input_schema_sha256": self.input_schema_sha256,
            "output_schema_sha256": self.output_schema_sha256,
            "arguments": json.loads(self.arguments_json),
            "arguments_sha256": self.arguments_sha256,
            "execution_grant": None,
            "transport_executed": False,
        }

    @property
    def sha256(self) -> str:
        return _digest(_json_text(self.to_dict()))


@dataclass(frozen=True, slots=True)
class IDLResultProjection:
    """Correlated, schema-checked data; backend authenticity is not established."""

    request_id: str
    request_sha256: str
    interface_cid: str
    method_name: str
    arguments_sha256: str
    output_schema_sha256: str
    result_json: str

    @property
    def result_sha256(self) -> str:
        return _digest(self.result_json)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "kind": "result_schema_evidence",
            "request_id": self.request_id,
            "request_sha256": self.request_sha256,
            "interface_cid": self.interface_cid,
            "method_name": self.method_name,
            "arguments_sha256": self.arguments_sha256,
            "output_schema_sha256": self.output_schema_sha256,
            "result": json.loads(self.result_json),
            "result_sha256": self.result_sha256,
            "schema_validated": True,
            "backend_authenticated": False,
            "execution_grant": None,
            "state_mutation_applied": False,
        }


def project_idl_request(
    decision: UIMediationDecision,
    descriptor: Mapping[str, Any],
    arguments: Any,
    *,
    expected_request_id: str,
    expected_event_id: str,
    expected_declaration_digest: str,
    expected_projection_id: str,
    expected_state_version: int,
) -> IDLRequestProjection:
    """Project a trusted local ALLOW decision after checking current context.

    Expected values must come from the caller's current runtime/request ledger,
    not be copied from untrusted request metadata. An ALLOW class instance is
    not a credential, and this function does not re-evaluate policy or consent.
    """
    if not isinstance(decision, UIMediationDecision):
        raise UIIRValidationError("A trusted local UIMediationDecision is required")
    if decision.outcome is not MediationOutcome.ALLOW or not decision.can_execute:
        raise UIIRValidationError("Only ALLOW decisions can produce request projections")
    request = decision.invocation_request
    if not isinstance(request, UIInvocationRequest) or decision.ui_state_authority_used:
        raise UIIRValidationError("A governed invocation request is required")
    for key, value in request.to_dict().items():
        if key not in ("state_version", "expected_effect_ids") and not isinstance(value, str):
            raise UIIRValidationError(f"Invocation {key} must be a string")
    if not isinstance(request.expected_effect_ids, (tuple, list)) or not all(
            isinstance(value, str) for value in request.expected_effect_ids):
        raise UIIRValidationError("Invocation expected effect IDs must be strings")
    request = replace(request, expected_effect_ids=tuple(request.expected_effect_ids))
    expected = {
        "request_id": expected_request_id, "event_id": expected_event_id,
        "declaration_digest": expected_declaration_digest,
        "projection_id": expected_projection_id, "state_version": expected_state_version,
    }
    if type(expected_state_version) is not int or expected_state_version < 0:
        raise UIIRValidationError("Expected state version must be a nonnegative integer")
    for key, value in expected.items():
        if key != "state_version" and (not isinstance(value, str) or not value.strip()):
            raise UIIRValidationError(f"Expected {key} must be nonempty")
        if type(getattr(request, key)) is not type(value) or getattr(request, key) != value:
            raise UIIRValidationError(f"Invocation {key} does not match current context")
    for key in ("binding_id", "action_id", "event_id"):
        if getattr(decision, key) != getattr(request, key):
            raise UIIRValidationError(f"Decision and invocation {key} differ")
    if not decision.decision_id or not request.actor_id or not request.policy_norm_id:
        raise UIIRValidationError("Decision, actor and policy lineage must be present")
    if decision.selected_policy_norm_id != request.policy_norm_id:
        raise UIIRValidationError("Decision and invocation policy lineage differ")
    if request.program_target_kind != ProgramBindingTargetKind.MCP_IDL.value:
        raise UIIRValidationError("Only MCP-IDL invocation targets are supported")
    cid, method = request.mcp_idl_interface_cid, request.mcp_idl_method_name
    if request.program_target_ref != f"mcp:{cid}#{method}":
        raise UIIRValidationError("Invocation target reference differs from CID/method")
    if request.intent_document_id or request.intent_action_id or request.invocation_template_cid:
        raise UIIRValidationError("Invocation has mixed program target families")
    descriptor_sha256, input_schema, output_schema = _method_schemas(descriptor, cid, method)
    arguments_json = _json_text(arguments)
    _validate_instance(input_schema, json.loads(arguments_json), "Arguments")
    return IDLRequestProjection(
        request, decision.decision_id, descriptor_sha256,
        _digest(_json_text(input_schema)), _digest(_json_text(output_schema)), arguments_json,
    )


def project_idl_result(
    request: IDLRequestProjection,
    descriptor: Mapping[str, Any],
    *,
    request_id: str,
    request_sha256: str,
    interface_cid: str,
    method_name: str,
    result: Any,
) -> IDLResultProjection:
    """Validate one correlated success result without executing or rendering.

    The adapter around an independently authenticated executor must carry the
    request digest as well as request ID; UI request IDs alone omit arguments.
    A caller can forge all correlation fields, so matching is not authentication.
    """
    if not isinstance(request, IDLRequestProjection):
        raise UIIRValidationError("A locally retained IDLRequestProjection is required")
    invocation = request.invocation_request
    if (request_id != invocation.request_id or request_sha256 != request.sha256
            or interface_cid != invocation.mcp_idl_interface_cid
            or method_name != invocation.mcp_idl_method_name):
        raise UIIRValidationError("Result does not match the retained request correlation")
    descriptor_digest, input_schema, output_schema = _method_schemas(descriptor, interface_cid, method_name)
    if (descriptor_digest != request.descriptor_sha256
            or _digest(_json_text(input_schema)) != request.input_schema_sha256
            or _digest(_json_text(output_schema)) != request.output_schema_sha256):
        raise UIIRValidationError("Retained request schemas differ from the verified descriptor")
    _validate_instance(input_schema, json.loads(request.arguments_json), "Arguments")
    result_json = _json_text(result)
    _validate_instance(output_schema, json.loads(result_json), "Result")
    return IDLResultProjection(request_id, request_sha256, interface_cid, method_name,
                               request.arguments_sha256, request.output_schema_sha256, result_json)


__all__ = ["IDLRequestProjection", "IDLResultProjection", "project_idl_request", "project_idl_result"]
