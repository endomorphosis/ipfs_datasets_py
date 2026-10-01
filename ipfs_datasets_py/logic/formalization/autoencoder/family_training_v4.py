"""Versioned native targets with explicit bounded TLA/Lean state projections.

All v3 non-TLA targets and shortcomings remain visible. Superseded artifacts
are retained with their reason; unsupported replacements stay active and block.
"""
from copy import deepcopy
import importlib

from . import family_training as core
from . import family_training_v3 as previous
from . import native_tla_projection as tla
from . import native_intent_lean as intent
from ...software_verification.transitions import StateTransitionIR

SCHEMA = "domain-family-training-targets/v4"
TypedFamilyEvidence = previous.TypedFamilyEvidence
supplemental_source_ref = previous.supplemental_source_ref
_PINS = {name: digest for module in (core, previous, tla, intent, importlib.import_module(__name__))
         for name, digest in core._pin(module).items()}


def _guard():
    from ....optimizers.logic_theorem_optimizer.autoencoder_schema_lake import _pin_imported_module
    for name, digest in _PINS.items():
        if _pin_imported_module(importlib.import_module(name)) != digest:
            raise ValueError("v4 native projection producer changed")


def _state(payload):
    if type(payload) is not dict:
        return None
    if payload.get("schema_version") == "state-transition-ir/v1":
        return payload
    if payload.get("format") == "StateTransitionIR@1":
        return payload.get("payload")
    return payload.get("native_document")


def prepare_family_training_targets_v4(domain_id, **source_inputs):
    _guard()
    base = previous.prepare_family_training_targets_v3(domain_id, **source_inputs)
    report = deepcopy(base)
    report.update(schema=SCHEMA, v3_report_sha256=base["report_sha256"], v3_source_digest=base["source_digest"])
    report["producer_pins"].update(_PINS)
    report["producer_pins"].update(core._pin(importlib.import_module(StateTransitionIR.__module__)))
    report["producer_pins"].update(core._pin(tla.lean))
    states = [_state(p["payload"]) for p in base["projections"]
              if p["logic_family"] == "transition_system" and p.get("profile") != "tla_plus"]
    states = [s for s in states if s]
    report["superseded_tla_observations"] = []
    for row in report["projections"]:
        if row.get("profile") != "tla_plus":
            continue
        old = deepcopy(row)
        candidates = [_state(row["payload"])] if _state(row["payload"]) else states
        try:
            if len(candidates) != 1:
                raise ValueError("exact_single_native_state_for_TLA_required")
            native = StateTransitionIR.from_dict(candidates[0])
            payload = row["payload"]
            prior = payload.get("artifact", payload)
            max_steps = prior.get("bounds", {}).get("max_steps", payload.get("context", {}).get("max_steps", 64))
            artifact = tla.compile_bounded_state(native, max_steps=max_steps)
        except (ValueError, KeyError, TypeError) as error:
            row["ready_for_training"] = False
            row["validation"].append({"validator_id": "bounded_native_TLA", "stage": "target", "status": "failed",
                "details": {"reason": str(error)}})
            report["frontier"].append({"family_id": "transition_system", "projection_id": row["projection_id"], "reason": str(error)})
            continue
        old.update(active_for_training=False, superseded_reason="versioned_exact_aliases_frames_labels_bounds_without_invented_liveness")
        report["superseded_tla_observations"].append(old)
        row.update(projection_id=domain_id + "/bounded_state/tla_plus/v4", payload=artifact,
            producer_id=tla.__name__, ready_for_training=True,
            validation=[{"validator_id": "compile_bounded_state_native_replay", "stage": "target", "status": "passed",
                "details": {"structural_generation_only": True, "SANY_executed": False, "Lake_executed": False}}],
            qualification_gaps=["SANY_and_Lake_must_execute", "finite_step_bound", "source_model_fidelity_not_verified", "external_model_check_not_run"])
    ids = [p["projection_id"] for p in report["projections"]]
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate bounded TLA target identity")
    digest = core._sha({"v3_source_digest": base["source_digest"], "bounded_TLA": [p["payload"] for p in report["projections"] if p.get("profile") == "tla_plus"]})
    report["source_digest"] = report["typed_input_digest"] = digest
    for row in report["projections"]:
        row["source_digest"] = digest
        row["target_sha256"] = core._sha({k: v for k, v in row.items() if k != "target_sha256"})
    report["projections"].sort(key=lambda p: (p["logic_family"], p["projection_id"]))
    ready = {p["logic_family"] for p in report["projections"] if p["ready_for_training"]}
    for row in report["family_inventory"]:
        targets = [p for p in report["projections"] if p["logic_family"] == row["family_id"]]
        row.update(target_count=len(targets), ready_target_count=sum(p["ready_for_training"] for p in targets),
                   ready_for_training=row["family_id"] in ready)
        row["status"] = "not_requested" if not row["requested"] else "targets_available" if row["ready_for_training"] else "unsupported"
    report["ready_for_training"] = bool(ready)
    report["all_requested_families_available"] = set(report["requested_families"]) <= ready
    report["report_sha256"] = core._sha({k: v for k, v in report.items() if k != "report_sha256"})
    validate_family_training_report_v4(report)
    return report


def validate_family_training_report_v4(report, **source_inputs):
    _guard()
    if type(report) is not dict or report.get("schema") != SCHEMA:
        raise ValueError("native v4 report required")
    if report.get("report_sha256") != core._sha({k: v for k, v in report.items() if k != "report_sha256"}):
        raise ValueError("v4 report digest differs")
    if any(report.get("producer_pins", {}).get(name) != digest for name, digest in _PINS.items()):
        raise ValueError("v4 source producer pin differs")
    compatible = deepcopy(report)
    compatible["schema"] = core.SCHEMA
    compatible["report_sha256"] = core._sha({k: v for k, v in compatible.items() if k != "report_sha256"})
    core.validate_family_training_report(compatible)
    if report.get("source_text_to_native_formula_inference") is not False or report.get("structural_readiness_is_qualification") is not False:
        raise ValueError("structural generation cannot claim semantic qualification")
    if source_inputs:
        expected = prepare_family_training_targets_v4(report["domain_id"], requested_families=report["requested_families"], **source_inputs)
        if core._wire(expected) != core._wire(report):
            raise ValueError("v4 report differs from exact source replay")
    return report
