"""Immutable feature targets produced by each domain's existing compiler.

These adapters preserve concrete native expressions and their provenance. They
do not share legal targets across domains, run provers, or turn structural
round trips into qualification. Feature readiness and qualification are separate.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import hashlib
import json
import re
from typing import Any


DOMAIN_TARGET_SCHEMA = "autoencoder-domain-targets/v1"
_MAX_BYTES = 32 * 1024 * 1024
_AUTHORITY = {"qualified": False, "admitted": False, "formalized": False}
_FIELDS = {
    "schema_version", "domain_id", "source_digest", "projections", "validation",
    "unsupported", "qualification_gaps", "ready_for_training", *_AUTHORITY,
}


def _wire(value: Any) -> bytes:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                     allow_nan=False).encode("utf-8")
    if len(raw) > _MAX_BYTES:
        raise ValueError("domain targets exceed the bounded envelope size")
    return raw


def _identifier(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"nonempty {name} required")
    return value


def _validate_payload(value: dict[str, Any]) -> None:
    from ipfs_datasets_py.logic.families.registry import DEFAULT_REGISTRY

    if set(value) != _FIELDS or value.get("schema_version") != DOMAIN_TARGET_SCHEMA:
        raise ValueError("closed versioned domain-target envelope required")
    _identifier(value["domain_id"], "domain_id")
    if not isinstance(value["source_digest"], str) or not re.fullmatch(r"[0-9a-f]{64}", value["source_digest"]):
        raise ValueError("source_digest must be a lowercase SHA-256 digest")
    if any(value[name] is not False for name in _AUTHORITY):
        raise ValueError("feature targets cannot establish qualification or admission")
    for name in ("projections", "validation", "unsupported", "qualification_gaps"):
        if not isinstance(value[name], list):
            raise ValueError(f"{name} must be a list")
    identities: set[str] = set()
    for row in value["projections"]:
        if not isinstance(row, dict):
            raise ValueError("structured projection rows required")
        for name in ("projection_id", "view_id", "representation_kind", "producer_id"):
            _identifier(row.get(name), name)
        if row["projection_id"] in identities:
            raise ValueError("projection IDs must be unique")
        identities.add(row["projection_id"])
        if not isinstance(row.get("expression"), (dict, list)) or not row["expression"]:
            raise ValueError("nonempty native structured expression required")
        family = row.get("logic_family")
        if family is not None and family not in DEFAULT_REGISTRY.families:
            raise ValueError("projection must name a canonical logic family")
        if family is None and not row.get("view_role"):
            raise ValueError("a family-free projection must retain its native view role")
        if row.get("profile") is not None:
            _identifier(row["profile"], "profile")
        if "properties" in row and (
            not isinstance(row["properties"], list)
            or any(not isinstance(item, str) or not item for item in row["properties"])
        ):
            raise ValueError("projection properties must be a list of identifiers")
    required_target_checks = []
    for row in value["validation"]:
        if not isinstance(row, dict):
            raise ValueError("structured validation observations required")
        _identifier(row.get("validator_id"), "validator_id")
        if row.get("stage", "target") not in {"target", "qualification"}:
            raise ValueError("validation stage must be target or qualification")
        if row.get("status") not in {"passed", "failed", "unsupported", "not_run"}:
            raise ValueError("explicit validation status required")
        if type(row.get("required", True)) is not bool or not isinstance(row.get("details"), dict):
            raise ValueError("validation requires a boolean requirement and structured details")
        if row.get("stage", "target") == "target" and row.get("required", True):
            required_target_checks.append(row)
    if not required_target_checks:
        raise ValueError("at least one required target validator is necessary")
    expected_ready = bool(value["projections"]) and not value["unsupported"] and all(
        row["status"] == "passed" for row in required_target_checks
    )
    if type(value["ready_for_training"]) is not bool or value["ready_for_training"] != expected_ready:
        raise ValueError("feature readiness differs from target validation evidence")


@dataclass(frozen=True, slots=True)
class DomainTargetEnvelope:
    """Canonical immutable bytes; returned dictionaries are detached copies."""

    canonical_bytes: bytes

    def __post_init__(self) -> None:
        if type(self.canonical_bytes) is not bytes or len(self.canonical_bytes) > _MAX_BYTES:
            raise ValueError("bounded immutable canonical bytes required")
        value = json.loads(self.canonical_bytes)
        if not isinstance(value, dict):
            raise ValueError("domain target mapping required")
        _validate_payload(value)
        if _wire(value) != self.canonical_bytes:
            raise ValueError("domain target bytes must be canonical")

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "DomainTargetEnvelope":
        return cls(_wire(dict(value)))

    def to_dict(self) -> dict[str, Any]:
        return json.loads(self.canonical_bytes)

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.canonical_bytes).hexdigest()

    @property
    def domain_id(self) -> str:
        return self.to_dict()["domain_id"]

    @property
    def source_digest(self) -> str:
        return self.to_dict()["source_digest"]

    @property
    def ready_for_training(self) -> bool:
        return self.to_dict()["ready_for_training"]


def build_target_envelope(
    *, domain_id: str, source_digest: str,
    projections: Sequence[Mapping[str, Any]], validation: Sequence[Mapping[str, Any]],
    unsupported: Sequence[Mapping[str, Any] | str] = (),
    qualification_gaps: Sequence[Mapping[str, Any] | str] = (),
) -> DomainTargetEnvelope:
    """Separate feature-input checks from unexecuted semantic qualification.

    Domain adapters, not this serialization helper, establish the observations.
    Loading an envelope checks its structure; consumers must still bind the
    trusted producer, source, target identity, and modality contract.
    """
    rows = [dict(row) for row in projections]
    checks = [dict(row) for row in validation]
    required = [row for row in checks if row.get("stage", "target") == "target"
                and row.get("required", True)]
    value = {
        "schema_version": DOMAIN_TARGET_SCHEMA, "domain_id": domain_id,
        "source_digest": source_digest, "projections": rows, "validation": checks,
        "unsupported": list(unsupported), "qualification_gaps": list(qualification_gaps),
        "ready_for_training": bool(rows) and not unsupported and bool(required)
        and all(row.get("status") == "passed" for row in required), **_AUTHORITY,
    }
    return DomainTargetEnvelope.from_dict(value)


def prepare_intent_targets(document: Any, *, required_view_ids: Sequence[str] = ()) -> DomainTargetEnvelope:
    """Compile a validated IntentIRDocument and review its protected fields.

    The shared intention/deontic view is split by the actual modal operator.
    Property kinds and verification roles retain their own namespaces.
    Structural fidelity to an Intent declaration does not prove the source's
    meaning or confer tool authorization.
    """
    from ipfs_datasets_py.logic.intent_ir.canonicalize import canonical_intent_ir_bytes
    from ipfs_datasets_py.logic.intent_ir.formalize import compiler as native
    from ipfs_datasets_py.logic.intent_ir.formalize.decompiler import IntentDecompiler
    from ipfs_datasets_py.logic.intent_ir.formalize.typed_compiler import resolve_intent_route
    from ipfs_datasets_py.logic.intent_ir.schema import validate_intent_ir

    document = validate_intent_ir(document)
    required = tuple(required_view_ids)
    if len(set(required)) != len(required) or set(required) - set(native.INTENT_FORMALIZATION_VIEW_REGISTRY.view_ids):
        raise ValueError("required Intent views must be unique registered view IDs")
    artifact = native.IntentFormalizationCompiler().compile_document(document)
    review = IntentDecompiler().compare(document, artifact)
    view_routes = {
        native.INTENT_FACT_VIEW_ID: "facts", native.INTENT_ACTION_VIEW_ID: "action_hoare",
        native.INTENT_WORKFLOW_VIEW_ID: "workflows", native.INTENT_INVARIANT_VIEW_ID: "safety",
        native.INTENT_FAILURE_VIEW_ID: "liveness", native.INTENT_VERIFICATION_VIEW_ID: "verification_condition",
    }
    grouped: dict[str, dict[str, Any]] = {}
    unsupported = []
    for formula in artifact.formulas:
        wire = formula.to_dict()
        expression = wire["expression"]
        if formula.opaque or not isinstance(expression, dict) or not expression:
            unsupported.append({"projection_id": formula.formula_id, "reason": "opaque_or_unstructured_formula"})
            continue
        if formula.view_id == native.INTENT_MODAL_VIEW_ID:
            operator = expression.get("operator")
            label = "intentions" if operator == "intended" else "norms"
            if operator not in {"intended", "required", "recommended", "permitted", "prohibited", "asserted"}:
                unsupported.append({"projection_id": formula.formula_id, "reason": "unknown_modal_operator"})
                continue
        else:
            label = view_routes.get(formula.view_id)
        if label is None:
            unsupported.append({"projection_id": formula.formula_id, "reason": "unmapped_native_view"})
            continue
        route = resolve_intent_route(label)
        projection = grouped.setdefault(route.route_id, {
            "projection_id": route.route_id, "view_id": formula.view_id,
            "logic_family": route.family_id or None, "profile": route.profile_id or None,
            "properties": [route.property_id] if route.property_id else [],
            "view_role": route.view_role_id or None, "expression": [],
            "representation_kind": "domain_structured_formula",
            "producer_id": native.INTENT_FORMALIZATION_PRODUCER_ID,
            "producer_version": native.INTENT_FORMALIZATION_COMPILER_VERSION,
            "source_ref_ids": [], "native_formulas": [],
            "route_id": route.route_id,
        })
        projection["expression"].append(expression)
        projection["native_formulas"].append(wire)
        projection["source_ref_ids"] = sorted(set(projection["source_ref_ids"]) | set(wire["source_ref_ids"]))
    projections = [grouped[key] for key in sorted(grouped)]
    observed = {row["view_id"] for row in projections}
    unsupported.extend({"view_id": view, "reason": "missing_requested_projection"}
                       for view in sorted(set(required) - observed))
    semantic_items = len(document.statements) + len(document.actions) + len(document.control_edges)
    checks = [
        {"validator_id": "intent_ir.schema", "status": "passed", "details": {"schema_version": document.schema_version}},
        {"validator_id": "intent_ir.nonempty_semantics", "status": "passed" if semantic_items else "failed",
         "details": {"semantic_item_count": semantic_items}},
        {"validator_id": "intent_ir.compiler", "status": "passed" if artifact.diagnostics.valid else "failed",
         "details": {"artifact_digest": artifact.digest, "formula_count": len(artifact.formulas),
                     "diagnostics": artifact.diagnostics.to_dict()}},
        {"validator_id": "intent_ir.decompiler_review", "status": "passed" if review.passed else "failed",
         "details": review.to_dict()},
    ]
    return build_target_envelope(
        domain_id="intent_ir", source_digest=hashlib.sha256(canonical_intent_ir_bytes(document)).hexdigest(),
        projections=projections, validation=checks, unsupported=unsupported,
        qualification_gaps=("source_meaning_not_verified", "backend_proofs_not_run", "tool_authority_not_granted"),
    )


def prepare_security_targets(
    *, code_unit: Any, source_bytes: bytes | None,
    typed_inputs: Sequence[Any] = (), requested_kinds: Sequence[str] | None = None,
) -> DomainTargetEnvelope:
    """Reuse source-bound Security IR native projections and exact replay.

    Typed inputs are CodeLogicEvidence objects. Security labels, classifier
    scores, and source text alone cannot supply missing program contracts,
    temporal properties, separation models, or information-flow policies.
    """
    from ipfs_datasets_py.logic.security_ir import code_logic_projection as native

    result = native.project_code_logic(code_unit=code_unit, source_bytes=source_bytes,
                                      typed_inputs=typed_inputs, requested_kinds=requested_kinds)
    native.validate_code_logic_projection(result, code_unit=code_unit, source_bytes=source_bytes)
    routes = {row["kind"]: row for row in native.describe_code_logic_projection_profile()["projections"]}
    source_digest = hashlib.sha256(_wire({"code_unit": code_unit.to_dict(),
        "source_sha256": hashlib.sha256(source_bytes).hexdigest() if source_bytes is not None else None})).hexdigest()
    projections = []
    for target in result["targets"]:
        kind, route = target["kind"], routes[target["kind"]]
        projections.append({
            "projection_id": route["payload_schema"],
            "view_id": route["payload_schema"], "logic_family": target["family_id"],
            "profile": target["profile_id"] or None, "properties": [],
            "view_role": route["view_role"] or None, "expression": target["native_document"],
            "representation_kind": "native_typed_document",
            "producer_id": "security-code-logic-projection", "producer_version": native.SCHEMA,
            "native_target": target, "source_binding": result["source"],
        })
    return build_target_envelope(
        domain_id="security_ir", source_digest=source_digest, projections=projections,
        validation=[
            {"validator_id": "security_ir.exact_source_binding", "status": "failed" if result["status"] == "quarantined" else "passed",
             "details": {"source": result["source"], "status": result["status"]}},
            {"validator_id": "security_ir.native_projection_replay", "status": "passed",
             "details": {"projection_cid": result["projection_cid"], "profile_cid": result["profile_cid"],
                         "target_count": len(projections), "requested_kinds": result["requested_kinds"],
                         "backend_calls": result["backend_calls"]}},
        ], unsupported=result["unsupported"],
        qualification_gaps=("source_semantics_not_verified", "backend_proofs_not_run", "model_checker_not_run"),
    )


__all__ = ["DOMAIN_TARGET_SCHEMA", "DomainTargetEnvelope", "build_target_envelope",
           "prepare_intent_targets", "prepare_security_targets"]
