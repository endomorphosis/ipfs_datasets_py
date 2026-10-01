"""Read-only diagnosis of two exact authored Legal/UI coverage fixtures.

This is deliberately not a corpus ambiguity classifier, policy interpreter,
supervisor task importer, or Lake execution issuer. Native preparation is
replayed, including its unsupported rows; no source meaning is filled in.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import importlib
import json
from pathlib import Path

SCHEMA = "authored-projection-context-audit/v1"
WORK_SCHEMA = "projection-context-review-work/v1"
FIXTURE_BASE_COMMIT = "6bd6eaabd2d3dde46e664b7386efb134253eb928"
FIXTURE_SHA256 = "f39096f181a0eae43241e3d1fe02cad9e2f67792e35770a5ca015e7559856817"
DOMAINS = ("legal_ir", "ui_ux_ir")
FORMULAS = {
    "FOL": "forall x. Person(x) -> Reports(x)",
    "DFOL": "forall x. O(Reports(x))",
    "TFOL": "forall x. □(Reports(x))",
    "TDFOL": "forall x. O(□(Reports(x)))",
    "CEC": "K(Officer,Happens(Submit,Time))",
    "DCEC": "O(K(Officer,Happens(Submit,Time)))",
    "frame_logic": "alice[role -> officer].",
    "propositional": "p and q",
}
BLOCKERS = {
    "legal_ir": {
        "legal-ir/modal-family/deontic/v3": "native_projection_not_ready",
        "legal-ir/modal-family/temporal/v3": "native_projection_not_ready",
    },
    "ui_ux_ir": {
        "ui_ux_ir:tdfol": "UI_before_requires_explicit_occurrence_and_precedence_semantics",
    },
}
FALSE = {"qualified": False, "admitted": False, "formalized": False,
         "source_semantics_verified": False, "training_executed": False,
         "backend_executed": False, "supervisor_importable": False,
         "enqueued": False, "uploaded": False, "constitution_formalized": False}
MAX_REPORT_BYTES = 16 * 1024 * 1024
_SOURCE_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def _raw(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _digest(value):
    return hashlib.sha256(_raw(value)).hexdigest()


def _require(condition, reason):
    if not condition:
        raise ValueError(reason)


def _guard_source():
    _require(hashlib.sha256(Path(__file__).read_bytes()).hexdigest() == _SOURCE_SHA256,
             "context audit implementation changed since import")


@dataclass(frozen=True)
class ProjectionContextAudit:
    """Detached diagnostic bytes, never a process-local validation handle."""
    _bytes: bytes

    def to_dict(self):
        return json.loads(self._bytes)


def _source_record(domain, row, inputs):
    if domain == "legal_ir":
        payload = {"source_text": inputs["source_text"], "document": inputs["document"].to_dict()}
        _require(payload["source_text"] == "custodian must publish record within 10 days.",
                 "audited Legal fixture text changed")
        _require(len(payload["document"]["formulas"]) == 2 and all(
            f["conditions"] == ["within 10 days"] and f["exceptions"] == []
            for f in payload["document"]["formulas"]), "audited Legal qualifier inputs changed")
        spans = [{"text": "within 10 days", "start_char": 30, "end_char": 44,
                  "start_byte": 30, "end_byte": 44}]
        # Both offsets are checked rather than silently searching another span.
        for span in spans:
            _require(payload["source_text"][span["start_char"]:span["end_char"]] == span["text"],
                     "audited Legal source span changed")
        mode = "authored_ModalIRDocument_NLP_parser_not_run"
    else:
        payload = {"ui_training_row": inputs["ui_training_row"]}
        ui = payload["ui_training_row"]
        _require(_digest(ui) == "5f34201d88a0ca82514f4d1f50817bd974bdc8ea5be42d5da8a583694039a2d7",
                 "audited UI fixture content changed")
        spans = [{"json_pointer": "/ui_training_row/bindings/0",
                  "meaning": "exact high-risk single-confirm action declaration"},
                 {"json_pointer": "/ui_training_row/events/0",
                  "meaning": "synthetic activation observation; no confirmation observation supplied"}]
        mode = "authored_structured_UI_adapter_not_natural_language_encoding"
    _require(row["source_id"] == domain + ":pair:0:2:0", "default first training fixture changed")
    return {"source_id": row["source_id"], "fixture_row": row,
            "input_payload": payload, "input_payload_sha256": _digest(payload),
            "evidence_locations": spans, "construction": mode,
            "parent_corpus": "absent_authored_fixture_has_no_retrievable_parent_document",
            "source_truncation": "not_observed_fixture_is_complete_as_authored",
            "NLP_parser_defect": "not_tested_no_NLP_parser_execution",
            "source_extraction_defect": "not_tested_no_corpus_extraction_execution"}


def _diagnosis(domain):
    if domain == "legal_ir":
        return {
            "classification": ["uninterpreted_retained_qualifier", "underspecified_authored_time_contract"],
            "stage": "authored_typed_IR_to_native_temporal_deontic_interpretation",
            "finding": "The duration literal survives in both formula partitions; its anchor and clock contract are not declared.",
            "loss_observation": "qualifier_text_retained_not_dropped; bounded_operator_not_constructed",
            "missing_semantic_slots": ["deadline_origin_or_trigger", "clock_domain_and_day_convention",
                "interval_boundary_convention", "deontic_and_temporal_scope_join"],
            "resolution_owner": "fixture_author_and_legal_temporal_semantics_owner",
            "needed_context": "For corpus rows retrieve exact parent/trigger/definition sources; this fixture has none.",
            "resolution_requirements": [
                "Retain the original unresolved fixture as a negative regression.",
                "Author a separately identified complete trigger/clock/scope declaration without treating it as inferred source meaning.",
                "Bind both partitions to one coherent source-bound qualifier interpretation; retain every original formula.",
                "Replay all projections and run actual Lake with unchanged policy/floor requirements before strict training."],
            "distinguishing_tests": ["origin_0_vs_origin_5_can_change_a_deadline_for_the_same_event",
                "event_at_exact_deadline_vs_one_tick_late", "obligation_of_eventually_vs_eventually_of_obligation"],
            "automatic_resolution": "none_no_time_policy_inferred",
        }
    return {
        "classification": ["flattened_occurrence_relation", "missing_authored_confirmation_policy"],
        "stage": "structured_UI_binding_to_TDFOL_precedence_interpretation",
        "finding": "The binding supplies high-risk confirmation intent; flattened before strings do not specify occurrence correlation or policy scope. The synthetic activate event and pending-to-finished edge establish neither invocation nor completion.",
        "loss_observation": "original_binding_retained_in_source; before_formula_does_not_encode_a_complete_occurrence_policy",
        "missing_semantic_slots": ["action_request_occurrence_correlation", "confirmation_lifetime",
            "event_order_and_clock", "cancellation_and_reuse_policy", "trace_origin_and_observation_scope"],
        "resolution_owner": "UI_binding_and_runtime_policy_owner",
        "needed_context": "Recover an existing source-bound policy/trace if supplied; do not fabricate confirmation events from activate.",
        "trace_join_status": "no_request_token_confirmation_trace_supplied; observed_compliance_not_evaluated",
        "policy_status": "occurrence_scope_and_lifecycle_not_declared",
        "resolution_requirements": [
            "Retain the original underspecified binding as a negative regression.",
            "Supply separately versioned request/token policy inputs or implement another explicitly declared occurrence profile.",
            "Keep policy interpretation, observed trace conformance, event authenticity and backend authorization separate.",
            "A finite observed prefix is not a whole-workflow guarantee; an empty prefix is not successful execution.",
            "Preserve all native binding fields and TDFOL formulas; replay every family then run actual Lake/SANY as required."],
        "distinguishing_tests": ["same_action_different_request", "stale_confirmation", "cancellation",
            "reused_token", "same_tick_different_sequence_order", "activation_is_not_confirmation"],
        "automatic_resolution": "none_no_token_policy_or_runtime_events_invented",
    }


def _code_pins(reports, fixtures, targets, lake, policy):
    # Declared producers and preparation implementations, not an ambient sys.modules census.
    pins = {}
    modules = {__name__, fixtures.__name__, targets.__name__, lake.__name__, policy.__name__}
    for report in reports:
        modules.update(report["producer_pins"])
        for name, expected in report["producer_pins"].items():
            path = Path(importlib.import_module(name).__file__).resolve()
            _require(hashlib.sha256(path.read_bytes()).hexdigest() == expected,
                     "declared target producer changed during context audit")
    for name in sorted(modules):
        module = importlib.import_module(name)
        path = Path(module.__file__).resolve()
        relative = path.relative_to(Path(__file__).resolve().parents[4])
        pins[relative.as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    for path, sha in lake._static_pins().items():
        relative = Path(path).relative_to(Path(__file__).resolve().parents[4])
        pins[relative.as_posix()] = sha
    return dict(sorted(pins.items()))


def audit_default_projection_context():
    """Recreate the exact default Legal/UI targets; prepare, never execute, Lean.

    The fixed fixture digest and precise expected blocker set make this an
    audited fixture diagnosis, not a heuristic that silently follows changed
    samples. Every one of the 27 targets and preparation observations is kept.
    """
    from ...autoformal.tree_pin import require_workspace_logic_tree
    from . import family_training_v7 as targets
    from . import native_family_lake_v5 as lake
    from . import projection_validation_contract_v5 as policy
    from .native_formula_evidence import NativeFormulaEvidence
    from ....optimizers.logic_theorem_optimizer import domain_reconstruction_panel as fixtures

    _guard_source()
    require_workspace_logic_tree()
    from ....optimizers.logic_theorem_optimizer.autoencoder_schema_lake import _pin_imported_module
    _require(_pin_imported_module(fixtures) == FIXTURE_SHA256,
             "audited fixture producer changed; review the diagnosis before updating its pin")
    reports, sources, originals = [], [], []
    for domain in DOMAINS:
        row = fixtures.rows(domain, "train")[0]
        inputs = fixtures.source_inputs(row)
        source = _source_record(domain, row, inputs)
        reference = targets.supplemental_source_ref(domain, **inputs)
        inputs["formula_inputs"] = [NativeFormulaEvidence(name, formula, reference)
                                    for name, formula in FORMULAS.items()]
        report = targets.prepare_family_training_targets_v7(domain, **inputs)
        _require(len(report["requested_families"]) == len(report["family_inventory"]) == 40,
                 "complete forty-family request required")
        reports.append(report)
        sources.append(source)
        originals.append(inputs)

    work_items = []
    for domain, source, inputs, report in zip(DOMAINS, sources, originals, reports):
        prepared = lake.prepare_native_family_lean(report, source_inputs=inputs)
        rows = prepared["per_projection"]
        blocked = {r["projection_id"]: r["reason"] for r in rows if not r["semantic_lowering_supported"]}
        _require(blocked == BLOCKERS[domain], "default semantic blockers changed; diagnosis must be reviewed")
        _require(len(rows) == (11 if domain == "legal_ir" else 16), "default projection count changed")
        _require({r["projection_id"] for r in rows} == {r["projection_id"] for r in report["projections"]},
                 "native preparation omitted a target")
        _require(prepared["backend_executed"] is False and all(r["lake_status"] != "passed" for r in rows),
                 "preparation must not claim a Lake execution")
        # This deliberately retains missing-live-evidence and missing-review
        # results, separately from the three historical semantic blockers.
        observation = policy.validate_projection_report(report).to_dict()
        source.update(domain_id=domain, source_digest=report["source_digest"],
            source_ref=targets.supplemental_source_ref(domain, **inputs).to_dict(),
            target_report=report,
            native_preparation={key: prepared[key] for key in (
                "schema", "library", "report_sha256", "source_digest", "source_sha256",
                "requested_families", "missing_requested_families", "per_projection",
                "lean_source", "lean_source_sha256", "source_replay_passed", "backend_executed", "status")},
            semantic_blockers=blocked, diagnosis=_diagnosis(domain),
            policy_without_execution=observation, fixed_policy=policy.domain_projection_policy(domain),
            live_evidence_status="not_run_this_audit_does_not_reuse_historical_receipts",
            training_gate_status="blocked_no_live_Lake_no_applicability_reviews_and_unresolved_semantic_rows")
        identity = {"schema": WORK_SCHEMA, "source_id": source["source_id"],
            "input_payload_sha256": source["input_payload_sha256"],
            "source_digest": source["source_digest"], "projection_ids": sorted(blocked),
            "missing_semantic_slots": source["diagnosis"]["missing_semantic_slots"]}
        work_items.append({**identity, "work_id": "context-review:" + _digest(identity),
            "status": "deferred_diagnostic_only", "owner": source["diagnosis"]["resolution_owner"],
            "requirements": source["diagnosis"]["resolution_requirements"],
            "not_a_supervisor_task": True, **FALSE})
    result = {"schema": SCHEMA, "fixture_base_commit": FIXTURE_BASE_COMMIT,
        "fixture_scope": "two_authored_integration_sources_not_three_corpus_spans",
        "sources": sources, "work_items": work_items,
        "producer_pins": _code_pins(reports, fixtures, targets, lake, policy),
        "producer_pin_scope": "declared_target_producers_preparation_static_implementations_and_audit",
        "counts": {"sources": 2, "projections": 27, "supported_preparations": 24,
            "semantic_blockers": 3, "source_grouped_review_items": 2,
            "supplied_formula_cases": 16, "Lake_executions": 0, "SANY_executions": 0},
        "strict_training_gate_changed": False, "policies_inferred": False,
        "context_window_changed": False, "network_calls": 0, "download_calls": 0,
        "qualification_scope": "diagnostic_only_neither_syntax_preparation_nor_policy_declaration_is_admission",
        **FALSE}
    result["report_sha256"] = _digest(result)
    raw = _raw(result)
    _require(len(raw) <= MAX_REPORT_BYTES, "projection context audit exceeds byte bound")
    _guard_source()
    return ProjectionContextAudit(raw)


def validate_projection_context_audit(report):
    """Replay exact fixture/code bindings; returned JSON still grants no authority."""
    _require(type(report) is dict and len(_raw(report)) <= MAX_REPORT_BYTES, "bounded audit mapping required")
    _require(report.get("schema") == SCHEMA, "known diagnostic audit schema required")
    _require(report.get("report_sha256") == _digest({k: v for k, v in report.items() if k != "report_sha256"}),
             "context audit digest differs")
    fresh = audit_default_projection_context().to_dict()
    _require(_raw(report) == _raw(fresh), "context audit differs from fresh source/code replay")
    return ProjectionContextAudit(_raw(fresh))


__all__ = ["SCHEMA", "WORK_SCHEMA", "ProjectionContextAudit", "audit_default_projection_context",
           "validate_projection_context_audit"]
