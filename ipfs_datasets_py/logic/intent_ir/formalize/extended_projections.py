"""Compose native Intent views with source-bound additional logic families.

This layer is separate from frozen autoencoder codecs. Existing checkpoint
weights still predict the same IntentIR; installed deterministic projectors
produce the additional views, retaining every declared modeling limitation.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .projection_contracts import (canonical_bytes, source_ir_sha256, validated_document,
                                   validate_projection, make_projection, AUTHORITY)

SCHEMA = "intent-extended-projections/v1"
DEFAULT_FAMILIES = ("dcec", "tdfol", "event_calculus", "frame_logic", "datalog",
                    "horn_chc", "transition_system", "higher_order")
ADDITIONAL_REQUIREMENTS = {
    "separation_logic": "explicit typed heap, ownership predicates, and frame conditions",
    "hyperproperty": "explicit multi-trace model, trace quantifiers, and information-flow policy",
    "epistemic": "explicit knowledge accessibility/evidence model; intent is not knowledge",
    "doxastic": "explicit belief statements and belief-state semantics; intent is not belief",
    "refinement": "typed source/target systems, simulation relation, and refinement obligations",
    "concurrency": "explicit shared-state interference, scheduler, and synchronization model",
    "session_process": "typed protocol participants, messages, and communication ordering",
    "cryptographic_protocol": "explicit protocol roles, adversary model, primitives, and security claims",
}


def _context(context):
    if context is None:
        return {}
    if type(context) is not dict or set(context) - {"modal", "state", "structural"}:
        raise ValueError("closed projection context namespaces required")
    if any(type(value) is not dict for value in context.values()):
        raise ValueError("structured projection context required")
    return json.loads(canonical_bytes(context))


def projection_producer_pins():
    from . import (projection_contracts, modal_projections, structural_projections,
                   state_projections, workflow_state, guarded_workflow, lean_projection)
    from ...backends.tla import compiler as tla_compiler
    from ...CEC.native import dcec_core, dcec_integration, dcec_parsing, dcec_namespace
    from ...TDFOL import tdfol_core, tdfol_parser
    from ...parsers import event_calculus, flogic, rules
    from ...software_verification import state, transitions, refinement, syntax_bridge
    modules = (projection_contracts, modal_projections, structural_projections, state_projections,
        workflow_state, guarded_workflow, lean_projection, tla_compiler, dcec_core, dcec_integration, dcec_parsing, dcec_namespace,
        tdfol_core, tdfol_parser, event_calculus, flogic, rules, state, transitions, refinement, syntax_bridge)
    pins = {m.__name__: hashlib.sha256(Path(m.__file__).read_bytes()).hexdigest() for m in modules}
    pins[__name__] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    return pins


def project_intent_families(document, *, context=None, requested_families=None):
    from ...formalization.autoencoder.domain_targets import prepare_intent_targets
    from .modal_projections import project_modal_families
    from .state_projections import project_state_families
    from .structural_projections import project_structural_families
    from .lean_projection import project_lean_family

    document = validated_document(document)
    context = _context(context)
    if "requested_families" in context.get("structural", {}):
        raise ValueError("select aggregate families through requested_families, not nested structural context")
    requested = list(DEFAULT_FAMILIES if requested_families is None else requested_families)
    if requested_families is None and "refinement_evidence" in context.get("structural", {}):
        requested.append("refinement")
    if (not requested or len(requested) > 24 or len(set(requested)) != len(requested)
            or any(type(v) is not str or v not in {*DEFAULT_FAMILIES, *ADDITIONAL_REQUIREMENTS} for v in requested)):
        raise ValueError("unique supported extension families required")
    namespace_families = {"modal": {"dcec", "tdfol", "event_calculus"}, "state": {"transition_system"},
                          "structural": {"frame_logic", "datalog", "horn_chc", "refinement"}}
    if any(not (set(requested) & namespace_families[name]) for name in context):
        raise ValueError("supplied context requires selecting its projection family")
    if "refinement_evidence" in context.get("structural", {}) and "refinement" not in requested:
        raise ValueError("supplied refinement evidence requires selecting refinement")
    reports = []
    if set(requested) & {"dcec", "tdfol", "event_calculus"}:
        reports += project_modal_families(document, context=context)
    if "transition_system" in requested:
        reports += project_state_families(document, context=context)
    structural = set(requested) & {"frame_logic", "datalog", "horn_chc", "refinement"}
    if structural:
        structural_context = {**context, "structural": {**context.get("structural", {}),
            "requested_families": sorted(structural)}}
        reports += project_structural_families(document, context=structural_context)
    if "higher_order" in requested:
        reports.append(project_lean_family(document))
    reports = [row for row in reports if row["family_id"] in requested]
    for family in requested:
        if any(row["family_id"] == family for row in reports):
            continue
        reason = ADDITIONAL_REQUIREMENTS.get(family, "missing native family projection")
        reports.append(make_projection(document, family_id=family, status="unsupported",
            representation={"format": "unavailable", "payload": None, "source": None},
            unsupported=[{"node_id": document.document_id, "reason": reason}],
            validation=[{"validator": "intent.explicit_model_requirements", "status": "not_run",
                         "details": {"requires": reason}}],
            assumptions=["Missing model evidence is not synthesized from instruction text."]))
    for report in reports:
        validate_projection(report, document)
    reports.sort(key=lambda row: row["projection_id"])
    if len({r["projection_id"] for r in reports}) != len(reports):
        raise ValueError("duplicate extension projection identity")
    native = prepare_intent_targets(document).to_dict()
    result = {"schema": SCHEMA, "source_ir_sha256": source_ir_sha256(document),
        "requested_families": requested, "context": context, "context_sha256": hashlib.sha256(canonical_bytes(context)).hexdigest(),
        "native_targets": native, "projections": reports,
        "additional_requirements": dict(ADDITIONAL_REQUIREMENTS),
        "producer_pins": projection_producer_pins(),
        "training_executed": False, "provider_calls": 0, "external_backend_calls": 0,
        "all_requested_families_projected": all(r["status"] == "projected" for r in reports), **AUTHORITY}
    result["report_sha256"] = hashlib.sha256(canonical_bytes(result)).hexdigest()
    return result


def validate_intent_family_report(report, document):
    if type(report) is not dict:
        raise ValueError("extended Intent family report required")
    expected = project_intent_families(document, context=report.get("context"),
                                     requested_families=report.get("requested_families"))
    if canonical_bytes(report) != canonical_bytes(expected):
        raise ValueError("Intent family projection differs from deterministic source replay")
    return report


__all__ = ["project_intent_families", "validate_intent_family_report", "DEFAULT_FAMILIES",
           "ADDITIONAL_REQUIREMENTS", "projection_producer_pins"]
