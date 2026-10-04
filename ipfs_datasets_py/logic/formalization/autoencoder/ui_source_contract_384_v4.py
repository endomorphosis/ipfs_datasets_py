"""Additive explicitly interpreted UI Boolean guards; v3 remains unchanged."""
from copy import deepcopy
import importlib

from . import family_training as core
from . import ui_source_contract_384_v3 as previous
from . import native_ui_guarded_lean as guarded

SCHEMA = "ui-guarded-family-training-targets/v1"
AUDIT_SCHEMA = "source-ui-graph-qualification/v4"
UIBehaviorInterpretation = previous.UIBehaviorInterpretation
UIGuardInterpretation = guarded.UIGuardInterpretation


def prepare_family_targets(source_text, target, requested_families=None, *,
                           behavior_interpretation=None, guard_interpretation=None):
    base = previous.prepare_family_targets(source_text, target, requested_families,
        behavior_interpretation=behavior_interpretation)
    if guard_interpretation is None:
        return base
    payload = guarded.prepare_guarded_payload(source_text, target, behavior_interpretation, guard_interpretation)
    report = deepcopy(base["report"])
    report.update(schema=SCHEMA, v3_report_sha256=base["report"]["report_sha256"],
        guard_interpretation=guard_interpretation.to_dict(), original_failures_preserved=True)
    report["producer_pins"].update(guarded.producer_pins())
    report["producer_pins"].update(core._pin(importlib.import_module(__name__)))
    if "transition_system" in report["requested_families"]:
        for kind, (family, profile) in guarded.ROUTES.items():
            report["projections"].append({"projection_id": guarded.PREFIX + kind + "/v1",
                "logic_family": family, "profile": profile, "representation_kind": "native_typed_projection",
                "producer_id": guarded.__name__, "payload": deepcopy(payload), "ready_for_training": True,
                "validation": [{"validator_id": "exhaustive_frozen_boolean_UI_guard_interpretation",
                    "stage": "target", "status": "passed", "details": {"source_meaning_verified": False,
                        "Lake_executed": False, "disabled_rows_retained": True}}],
                "qualification_gaps": list(payload["limitations"]), **core.AUTHORITY})
    binding = core._sha({"v3_source_digest": base["report"]["source_digest"],
                        "guard_interpretation": guard_interpretation.to_dict()})
    report["source_digest"] = report["typed_input_digest"] = binding
    for row in report["projections"]:
        row["source_digest"] = binding
        row["target_sha256"] = core._sha({key: value for key, value in row.items() if key != "target_sha256"})
    report["projections"].sort(key=lambda row: (row["logic_family"], row["projection_id"]))
    available = {row["logic_family"] for row in report["projections"] if row["ready_for_training"]}
    for row in report["family_inventory"]:
        projections = [p for p in report["projections"] if p["logic_family"] == row["family_id"]]
        ready = sum(p["ready_for_training"] for p in projections)
        row.update(target_count=len(projections), ready_target_count=ready, ready_for_training=bool(ready),
            status="not_requested" if not row["requested"] else "targets_available" if ready else "unsupported")
    report["ready_for_training"] = bool(available)
    report["all_requested_families_available"] = set(report["requested_families"]) <= available
    report["report_sha256"] = core._sha({key: value for key, value in report.items() if key != "report_sha256"})
    audit = deepcopy(base["audit"])
    audit.update(schema=AUDIT_SCHEMA, guard_interpretation=guard_interpretation.to_dict(),
        guard_scope=guarded.SCOPE, original_v3_audit_sha256=base["audit"]["audit_sha256"],
        original_v3_behavior_status=base["audit"]["behavior_status"],
        behavior_status="explicit_guarded_state_available_legacy_event_calculus_still_blocked"
            if "transition_system" in available else "explicit_guard_interpretation_retained_state_route_not_requested",
        original_failures_preserved=True, family_report_sha256=report["report_sha256"],
        family_source_digest=binding, available_families=sorted(available),
        missing_requested_families=sorted(set(report["requested_families"]) - available),
        guarded_state_route_available="transition_system" in available,
        guarded_truth_table_rows=len(payload["truth_table"]), guarded_enabled_edges=len(payload["enabled_edges"]),
        reachable_nonterminal_deadlocks=payload["reachable_nonterminal_deadlocks"],
        source_text_to_guard_inference=False, runtime_parameter_updates_modeled=False, timing_supported=False)
    audit["producer_pins"].update(report["producer_pins"])
    audit["audit_sha256"] = core._sha({key: value for key, value in audit.items() if key != "audit_sha256"})
    inputs = {"source_text": source_text, "target": deepcopy(target),
        "behavior_interpretation": behavior_interpretation, "guard_interpretation": guard_interpretation,
        "requested_families": report["requested_families"]}
    validate_family_training_report(report)
    return {"report": report, "source_inputs": inputs, "audit": audit}


def validate_family_training_report(report, **source_inputs):
    guarded.producer_pins()
    previous._require(type(report) is dict and report.get("schema") == SCHEMA, "UI guarded report schema required")
    previous._require(report.get("report_sha256") == core._sha({key: value for key, value in report.items()
        if key != "report_sha256"}), "UI guarded report digest differs")
    compatible = deepcopy(report)
    compatible["schema"] = core.SCHEMA
    compatible["report_sha256"] = core._sha({key: value for key, value in compatible.items() if key != "report_sha256"})
    core.validate_family_training_report(compatible)
    if source_inputs:
        replay = prepare_family_targets(**source_inputs)
        previous._require(replay["report"] == report, "exact UI guarded source replay differs")
    return report


def validate_prepared(prepared, source_text, target, *, behavior_interpretation=None, guard_interpretation=None):
    if guard_interpretation is None:
        return previous.validate_prepared(prepared, source_text, target, behavior_interpretation=behavior_interpretation)
    replay = prepare_family_targets(source_text, target, prepared["report"]["requested_families"],
        behavior_interpretation=behavior_interpretation, guard_interpretation=guard_interpretation)
    previous._require(replay == prepared, "UI v4 complete source/guard preparation replay differs")
    return True


def qualify_source_candidate(source_text, target, requested_families=None, *,
                             behavior_interpretation=None, guard_interpretation=None):
    try:
        result = prepare_family_targets(source_text, target, requested_families,
            behavior_interpretation=behavior_interpretation, guard_interpretation=guard_interpretation)
    except (ValueError, TypeError, KeyError, RecursionError) as error:
        return {"schema": AUDIT_SCHEMA, "status": "invalid_or_missing_context", "reason": str(error)[:1024],
            "candidate": deepcopy(target), "candidate_rewritten": False, "continue_planning": True,
            "lake_executed": False, **previous.FALSE}
    return {"status": result["audit"]["status"], "audit": result["audit"], "report": result["report"], **previous.FALSE}


__all__ = ["UIBehaviorInterpretation", "UIGuardInterpretation", "prepare_family_targets",
           "validate_family_training_report", "validate_prepared", "qualify_source_candidate"]
