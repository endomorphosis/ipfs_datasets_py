"""UI/UX native feature targets with separate reconstruction evidence.

The UI compiler emits domain records, not parser-checked logic-family ASTs.
These records can supervise feature training without acquiring proof, policy,
syntax qualification, or inference authority. Device projection observations
are scoped to the supplied problem; they never prove the whole UI declaration.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from enum import Enum
from typing import Any

from .domain_targets import DomainTargetEnvelope, build_target_envelope


def _json_value(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value) and not isinstance(value, type):
        return {field.name: _json_value(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, Mapping):
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted((_json_value(item) for item in value), key=lambda item: json.dumps(item, sort_keys=True))
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"unsupported UI target input: {type(value).__name__}")


def _digest(value: Any) -> str:
    body = json.dumps(_json_value(value), sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def prepare_ui_targets(
    document: Any,
    *,
    roundtrip_policy: Any = None,
    projection_problem: Any = None,
    device_profile: Any = None,
    projection_policy: Any = None,
) -> DomainTargetEnvelope:
    """Compile actual UI view records and retain bounded validation evidence.

    ``document`` must be a native ``RoundTripDocument`` or
    ``FormalizationInputs``. An optional projection problem must carry the same
    document ID and a device profile. Missing device inputs remain an explicit
    qualification gap; they do not turn a structural feature target into a
    failed compile. Invalid source models do fail target readiness.
    """
    from ipfs_datasets_py.logic.conformance.ui_ux_logic_gate_v2 import (
        UIUXFormalizationAdapter,
        UIUXLogicGateV2Error,
    )
    from ipfs_datasets_py.logic.ui_ux_ir.formalize.compiler import FormalizationInputs
    from ipfs_datasets_py.logic.ui_ux_ir.formalize.roundtrip import (
        RoundTripDocument,
        SemanticRoundTripPolicy,
        roundtrip_ui_ir,
    )
    from ipfs_datasets_py.logic.ui_ux_ir.model.experience import validate_experience_model
    from ipfs_datasets_py.logic.ui_ux_ir.model.modality import validate_modality_contract
    from ipfs_datasets_py.logic.ui_ux_ir.schema import UIIRValidationError

    if isinstance(document, FormalizationInputs):
        document = RoundTripDocument(
            document_id=document.artifact_id,
            component_graph=document.component_graph,
            behavior_model=document.behavior_model,
            action_bindings=document.action_bindings,
            events=document.events,
            actor_id=document.actor_id,
        )
    if not isinstance(document, RoundTripDocument):
        raise TypeError("UI targets require RoundTripDocument or FormalizationInputs")
    if (projection_problem is None) != (device_profile is None):
        raise ValueError("projection_problem and device_profile must be provided together")
    if projection_policy is not None and projection_problem is None:
        raise ValueError("projection_policy requires a projection problem")

    source_digest = _digest(document)
    policy = roundtrip_policy or SemanticRoundTripPolicy()
    projections: list[dict[str, Any]] = []
    validation: list[dict[str, Any]] = []
    unsupported: list[dict[str, Any]] = []
    qualification_gaps: list[dict[str, Any]] = []

    def observe(validator: str, status: str, details: Any, *, stage: str = "qualification", required: bool = True) -> None:
        validation.append({"validator_id": validator, "status": status, "details": details, "stage": stage, "required": required})

    # This compatibility gate is intentionally distinct from the working
    # native UI compiler; source presence is not adapter implementation.
    try:
        UIUXFormalizationAdapter().formalize(document)
    except UIUXLogicGateV2Error as exc:
        qualification_gaps.append({"code": exc.code, "message": str(exc)})
        observe("ui_ux.source_gate_adapter", "unsupported", {"code": exc.code})
        if exc.code == "ui_ux.source_missing":
            observe("ui_ux.native_compile", "not_run", {"reason": exc.code}, stage="target")
            unsupported.append({"code": exc.code})
            return build_target_envelope(domain_id="ui_ux_ir", source_digest=source_digest,
                projections=projections, validation=validation, unsupported=unsupported,
                qualification_gaps=qualification_gaps)
    else:
        observe("ui_ux.source_gate_adapter", "passed", {"scope": "adapter invocation only"})

    try:
        if document.experience is not None:
            validate_experience_model(document.experience)
        if document.modality is not None:
            validate_modality_contract(document.modality)
        report = roundtrip_ui_ir(document, policy)
    except (UIIRValidationError, TypeError, ValueError) as exc:
        observe("ui_ux.native_compile", "failed", {"error": str(exc)}, stage="target")
        unsupported.append({"code": "ui_ux.invalid_native_source", "message": str(exc)})
        return build_target_envelope(domain_id="ui_ux_ir", source_digest=source_digest,
            projections=projections, validation=validation, unsupported=unsupported,
            qualification_gaps=qualification_gaps)

    artifact = report.formalization
    if artifact is None:
        raise RuntimeError("UI roundtrip did not return its compiler artifact")
    views = (
        ("flogic", "frame_logic", "structural_components", "facts"),
        ("event_calculus", "event_calculus", "behavior_transitions", "formulas"),
        ("tdfol", "tdfol", "action_norms", "formulas"),
        ("dcec", "dcec", "interaction_cognition", "formulas"),
    )
    for view_id, family, role, field_name in views:
        view = getattr(artifact, view_id)
        if view is None:
            continue
        expressions = getattr(view, field_name)
        if expressions:
            projections.append({
                "projection_id": f"ui_ux_ir:{view_id}",
                "view_id": view_id,
                "logic_family": family,
                "expression": {field_name: _json_value(expressions)},
                "representation_kind": "domain_structured_formula",
                "producer_id": view.compiler,
                "profile": view.schema_version,
                "properties": [],
                "view_role": role,
            })
        qualification_gaps.append({"code": "ui_ux.family_syntax_not_checked", "view_id": view_id, "logic_family": family})
    observe("ui_ux.native_compile", "passed" if projections else "failed", {
        "compiler_id": artifact.compiler_id,
        "projection_count": len(projections),
        "syntax_checked": False,
    }, stage="target")
    for semantic in artifact.unsupported_semantics:
        qualification_gaps.append({"code": "ui_ux.compiler_scope_exclusion", "semantic": semantic})
    observe("ui_ux.compiler_coverage", "not_run", {
        "coverage": _json_value(artifact.coverage),
        "proof_obligations": list(artifact.proof_obligations),
        "backend_requests": _json_value(artifact.backend_requests),
    }, required=False)

    for layer in report.layers:
        observe(f"ui_ux.roundtrip.{layer.layer.value}",
            ("passed" if layer.passed and not layer.counterexamples else "failed") if layer.evaluated else "not_run",
            {"evaluated": layer.evaluated, "details": layer.details,
             "counterexamples": list(layer.counterexamples), "policy": _json_value(policy),
             "scope": "native bounded reconstruction; not entailment or proof"})
        if not layer.evaluated:
            qualification_gaps.append({"code": "ui_ux.roundtrip_layer_not_evaluated", "layer": layer.layer.value})
    observe("ui_ux.native_roundtrip", "passed" if report.overall_passed else "failed", {
        "counterexamples": list(report.counterexamples),
        "excluded_claims": list(report.excluded_claims),
        "scope": "evaluated native layers only",
    })

    if projection_problem is None:
        qualification_gaps.append({"code": "ui_ux.device_projection_not_requested"})
        observe("ui_ux.device_projection", "not_run", {"reason": "no device profile and projection problem"})
    else:
        from ipfs_datasets_py.logic.ui_ux_ir.projection.solver import solve_projection
        if projection_problem.document_id != document.document_id:
            raise ValueError("projection problem document_id does not match UI source")
        try:
            projected = solve_projection(projection_problem, device_profile, projection_policy)
            payload = projected.to_dict()
            # Wall-clock timing is not part of target identity; retain bounds
            # and outcomes, which still distinguish a timeout from success.
            payload["bounds"].pop("elapsed_ms", None)
            observe("ui_ux.device_projection", "passed" if projected.status.value == "satisfied" else "failed", {
                "scope": "supplied projection problem only",
                "input_digest": _digest({"problem": projection_problem, "profile": device_profile, "policy": projection_policy}),
                "result": payload,
            })
        except (UIIRValidationError, TypeError, ValueError) as exc:
            observe("ui_ux.device_projection", "failed", {"error": str(exc)})

    return build_target_envelope(domain_id="ui_ux_ir", source_digest=source_digest,
        projections=projections, validation=validation, unsupported=unsupported,
        qualification_gaps=qualification_gaps)


__all__ = ["prepare_ui_targets"]
