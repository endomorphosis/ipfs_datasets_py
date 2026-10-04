"""Inert source-bound linking plans for subsequent tactician/hammer work.

Proposed values and retrieved links remain hypotheses. No retrieved sentence is
registered as a theorem, no supervisor task is submitted, and no prover runs.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .context_resolution import context_digest, validate_context_bundle, AUTHORITY
from ...processors.legal_data.proof_tactician import ProofSearchPlan, ProofSearchSource

SCHEMA = "provisional-context-link-obligation/v1"
RELATIONS = frozenset({"governing_scope", "defines", "deadline_trigger", "clock_convention", "application_policy", "referent"})
_PRODUCER = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def prepare_context_link_obligation(bundle, *, index, slot_id, candidate_span_id, proposed_binding, relation):
    """Prepare a native ProofSearchPlan and a blocked hammer handoff.

    Source review and typed lowering are deliberately prerequisites to a hammer
    request. A plan is usable for orchestration/design without fabricating the
    typed theorem inputs that the existing hammer requires.
    """
    if hashlib.sha256(Path(__file__).read_bytes()).hexdigest() != _PRODUCER:
        raise ValueError("context_link_producer_changed_since_import")
    validate_context_bundle(bundle, index=index)
    if relation not in RELATIONS:
        raise ValueError("unsupported_context_link_relation")
    slots = [s for s in bundle["slots"] if s["slot_id"] == slot_id]
    if len(slots) != 1:
        raise ValueError("selected_context_slot_required")
    slot = slots[0]
    hits = [h for h in slot["candidates"] if h["span_id"] == candidate_span_id]
    if len(hits) != 1:
        raise ValueError("retrieved_candidate_for_slot_required")
    raw = json.dumps(proposed_binding, sort_keys=True, allow_nan=False)
    if proposed_binding is None or len(raw.encode()) > 4096:
        raise ValueError("bounded_proposed_binding_required")
    binding = json.loads(raw)
    candidate = bundle["artifacts"][hits[0]["artifact_sha256"]]
    request = {"bundle_sha256": bundle["bundle_sha256"], "slot_id": slot_id,
        "candidate_span_id": candidate_span_id, "proposed_binding": binding, "relation": relation}
    identity = "context-link:" + context_digest(request)
    assumptions = []
    for selected in bundle["slots"]:
        if selected["assumption"] is not None:
            assumptions.append({"assumption_id": "fixture:" + context_digest(selected["assumption"]),
                "slot_id": selected["slot_id"], "value": selected["assumption"], "discharged": False})
    assumptions.append({"assumption_id": "proposed-link:" + context_digest(request), "slot_id": slot_id,
        "value": binding, "discharged": False, "scope": "candidate_interpretation_not_source_fact"})
    stages = [
        {"stage": "review_source_scope", "status": "pending", "required": [
            "exact_revision_and_source_relation", "governing_scope_not_merely_adjacency", "competing_interpretations"]},
        {"stage": "lower_reviewed_context_relation", "status": "pending", "required": [
            "typed_source_to_IR_binding", "complete_assumption_dependencies", "supported_logic_family"]},
        {"stage": "hammer_conditional_obligation", "status": "pending", "required": [
            "reviewed_typed_goal", "existing_verified_library_premises_or_explicit_hypotheses", "no_circular_slot_self_justification"]},
        {"stage": "native_validation", "status": "pending", "required": [
            "all_emitted_family_syntax_checks", "actual_lake_build_for_modality", "independent_source_semantics_review"]},
    ]
    plan = ProofSearchPlan(plan_id=identity, work_item_id=identity, party="context_review",
        objective="Assess the proposed source relationship and slot binding; preserve unsupported alternatives.",
        recommended_route=[s["stage"] for s in stages], selected_starting_source_id=candidate_span_id,
        selected_starting_source_type="source_span_context_candidate", search_stages=stages,
        proof_gap_focus=[slot["question"]], candidate_sources=[ProofSearchSource(
            source_id=candidate_span_id, source_type="source_span_context_candidate", label=candidate_span_id,
            priority=1, rationale="Retrieved candidate awaiting source-scope review; selection is a proposal.",
            query_hints=[slot["question"]], metadata={"artifact_sha256": hits[0]["artifact_sha256"],
                "source_ref": candidate["source_ref"], "span": candidate["span"], "authority": "context_only"})],
        escalation_policy={"unresolved": "retain_original_and_provisional_companion",
            "conflicting": "retain_alternatives_and_request_scope_review", "automatic_source_repair": False})
    report = {"schema": SCHEMA, "request": request, "plan_id": identity,
        "selected_source": bundle["selected_source"], "candidate_source": candidate,
        "retrieval": hits[0]["retrieval"], "projection_ids": slot["projection_ids"],
        "new_assumption_ids": [item["assumption_id"] for item in assumptions], "assumptions": assumptions,
        "tactician_plan": plan.to_dict(), "tactician_plan_type": "ProofSearchPlan",
        "hammer_handoff": {"status": "awaiting_reviewed_typed_goal_and_premises", "execution_ready": False,
            "premises_registered": 0, "goal_registered": False,
            "conditional_proof_would_not_verify_source_premises": True},
        "producer_sha256": _PRODUCER,
        "proof_executed": False, "enqueued": False, "source_resolved": False, **AUTHORITY}
    report["obligation_sha256"] = context_digest(report)
    if hashlib.sha256(Path(__file__).read_bytes()).hexdigest() != _PRODUCER:
        raise ValueError("context_link_producer_changed_since_import")
    return report


def validate_context_link_obligation(report, *, bundle, index):
    if type(report) is not dict or report.get("schema") != SCHEMA:
        raise ValueError("context_link_obligation_required")
    request = report["request"]
    expected = prepare_context_link_obligation(bundle, index=index, slot_id=request["slot_id"],
        candidate_span_id=request["candidate_span_id"], proposed_binding=request["proposed_binding"], relation=request["relation"])
    if report != expected:
        raise ValueError("context_link_obligation_differs_from_replay")
    return True
