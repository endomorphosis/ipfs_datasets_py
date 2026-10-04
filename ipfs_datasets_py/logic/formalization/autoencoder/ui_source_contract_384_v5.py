"""Qualified bounded UI EC replacement, retaining the complete old failure."""
from copy import deepcopy
import importlib

from . import family_training as core
from . import ui_source_contract_384_v4 as previous
from . import native_ui_bounded_event_calculus as events

SCHEMA = events.REPORT_SCHEMA
UIBehaviorInterpretation = previous.UIBehaviorInterpretation
UIGuardInterpretation = previous.UIGuardInterpretation
UIBoundedECInterpretation = events.UIBoundedECInterpretation
require, digest = events.require, events.digest


def prepare_family_targets(source_text, target, requested_families=None, *,
                           behavior_interpretation=None, guard_interpretation=None, event_interpretation=None):
    base = previous.prepare_family_targets(source_text, target, requested_families,
        behavior_interpretation=behavior_interpretation, guard_interpretation=guard_interpretation)
    if event_interpretation is None: return base
    require("event_calculus" in base["report"]["requested_families"], "bounded EC declaration requires explicit requested EC family")
    payload = events.prepare_payload(source_text, target, behavior_interpretation, guard_interpretation, event_interpretation)
    report = deepcopy(base["report"])
    originals = [row for row in report["projections"] if row["projection_id"] == "ui_ux_ir:event_calculus"]
    require(len(originals) == 1 and originals[0]["logic_family"] == "event_calculus" and
        originals[0]["ready_for_training"] is False, "exact originally failed UI EC projection required")
    original = originals[0]
    archived = deepcopy(original)
    archived.update(active_for_training=False, replacement_projection_id=events.PROJECTION_ID,
        original_row_sha256=digest(original), superseded_reason="complete_explicit_signed_discrete_EC_interpretation")
    report.update(schema=SCHEMA, v4_report_sha256=base["report"]["report_sha256"],
        superseded_bounded_event_observations=[archived],
        bounded_event_source_binding={"source_text": source_text, "candidate": deepcopy(target),
            "behavior_interpretation": behavior_interpretation.to_dict(), "guard_interpretation": guard_interpretation.to_dict(),
            "event_interpretation": event_interpretation.to_dict()})
    original.update(projection_id=events.PROJECTION_ID, profile=events.PROFILE, producer_id=events.__name__,
        payload=payload, ready_for_training=True, qualification_gaps=list(payload["limitations"]),
        validation=[{"validator_id": "complete_signed_prefix_native_EC_operator_and_inertia_replay", "stage": "target",
            "status": "passed", "details": {"Lake_executed": False, "source_meaning_verified": False,
            "events_authenticated": False}}])
    report["producer_pins"].update(events.producer_pins())
    report["producer_pins"].update(core._pin(importlib.import_module(__name__)))
    report["source_digest"] = report["typed_input_digest"] = digest({"v4_source_digest": base["report"]["source_digest"],
        "event_interpretation": event_interpretation.to_dict()})
    for row in report["projections"]:
        row["source_digest"] = report["source_digest"]
        row["target_sha256"] = digest({k: v for k, v in row.items() if k != "target_sha256"})
    report["projections"].sort(key=lambda row: (row["logic_family"], row["projection_id"]))
    available = {row["logic_family"] for row in report["projections"] if row["ready_for_training"]}
    for row in report["family_inventory"]:
        projections = [p for p in report["projections"] if p["logic_family"] == row["family_id"]]
        ready = sum(p["ready_for_training"] for p in projections)
        row.update(target_count=len(projections), ready_target_count=ready, ready_for_training=bool(ready),
            status="not_requested" if not row["requested"] else "targets_available" if ready else "unsupported")
    report["all_requested_families_available"] = set(report["requested_families"]) <= available
    report["report_sha256"] = digest({k: v for k, v in report.items() if k != "report_sha256"})
    audit = deepcopy(base["audit"])
    audit.update(schema="source-ui-graph-qualification/v5", original_v4_audit_sha256=base["audit"]["audit_sha256"],
        status="projected_candidate", behavior_status="explicit_guard_and_bounded_EC_targets_require_native_build",
        original_failure_archived=True, available_families=sorted(available),
        missing_requested_families=sorted(set(report["requested_families"]) - available),
        family_report_sha256=report["report_sha256"], family_source_digest=report["source_digest"],
        bounded_event_interpretation=event_interpretation.to_dict(), event_authenticity_verified=False,
        bounded_clock_semantics_supplied=True, timeout_semantics_supported=False,
        bounded_EC_profile_available=True, supplied_occurrence_count=sum(e is not None for e in payload["occurrences"]))
    audit["producer_pins"].update(report["producer_pins"])
    audit["audit_sha256"] = digest({k: v for k, v in audit.items() if k != "audit_sha256"})
    inputs = {"source_text": source_text, "target": deepcopy(target), "requested_families": report["requested_families"],
        "behavior_interpretation": behavior_interpretation, "guard_interpretation": guard_interpretation,
        "event_interpretation": event_interpretation}
    validate_family_training_report(report)
    return {"report": report, "source_inputs": inputs, "audit": audit}


def validate_family_training_report(report, **source_inputs):
    events.producer_pins()
    require(type(report) is dict and report.get("schema") == SCHEMA and
        report.get("report_sha256") == digest({k: v for k, v in report.items() if k != "report_sha256"}),
        "bounded EC report schema/digest differs")
    compatible = deepcopy(report)
    compatible["schema"] = core.SCHEMA
    compatible["report_sha256"] = digest({k: v for k, v in compatible.items() if k != "report_sha256"})
    core.validate_family_training_report(compatible)
    if source_inputs:
        require(prepare_family_targets(**source_inputs)["report"] == report, "complete bounded EC source replay differs")
    return report


def validate_prepared(prepared, source_text, target, **options):
    require(prepare_family_targets(source_text, target, prepared["report"]["requested_families"], **options) == prepared,
            "bounded EC prepared envelope differs from exact replay")
    return True


def qualify_source_candidate(source_text, target, requested_families=None, **options):
    try: result = prepare_family_targets(source_text, target, requested_families, **options)
    except (ValueError, TypeError, KeyError, RecursionError) as error:
        return {"status": "invalid_or_missing_context", "reason": str(error)[:1024], "candidate": deepcopy(target),
            "candidate_rewritten": False, "continue_planning": True, "lake_executed": False, **previous.previous.FALSE}
    return {"status": result["audit"]["status"], "audit": result["audit"], "report": result["report"], **previous.previous.FALSE}


__all__ = ["UIBehaviorInterpretation", "UIGuardInterpretation", "UIBoundedECInterpretation", "prepare_family_targets",
           "validate_family_training_report", "validate_prepared", "qualify_source_candidate"]
