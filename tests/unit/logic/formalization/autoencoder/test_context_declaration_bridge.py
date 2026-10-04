"""Actual context declarations feed native targets without promoting source truth."""
from copy import deepcopy
from dataclasses import replace
import hashlib
import json

import pytest

from ipfs_datasets_py.logic.formalization import context_resolution as context
from ipfs_datasets_py.logic.formalization.context_slot_bindings import prepare_context_binding
from ipfs_datasets_py.logic.formalization.autoencoder import context_declaration_bridge as bridge
from ipfs_datasets_py.logic.formalization.autoencoder import native_family_lake_v5 as native
from ipfs_datasets_py.logic.formalization.autoencoder import family_training_v2 as source_owner
from ipfs_datasets_py.logic.formalization.autoencoder.native_formula_evidence import NativeFormulaEvidence
from ipfs_datasets_py.logic.formalization.autoencoder.projection_context_audit import FORMULAS
from ipfs_datasets_py.logic.ir_core.provenance import SourceRef, SourceSpan
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import domain_reconstruction_panel as fixtures


def values_for(domain, inputs):
    if domain == "legal_ir":
        return {
            "legal.temporal_anchor": {"origin": "caller_supplied_evaluation_time",
                "binding_kind": "evaluation_origin_declared_as_trigger", "trigger_ref": "authored:receipt"},
            "legal.temporal_model": {"temporal_kind": "within_duration", "quantity": 10, "unit": "day",
                "time_domain": "discrete_nat", "lower_inclusive": True, "upper_inclusive": True},
            "legal.scope": {"norm_projection_id": bridge.LEGAL_PROJECTIONS[0], "body_projection_id": bridge.LEGAL_PROJECTIONS[1],
                "body_relation": "temporal_view_is_auxiliary_body_not_fact", "enclosing_modal_symbol": "O",
                "activation_scope": "all_conditions_at_evaluation_origin", "exception_scope": "activation_time_waiver",
                "independent_event_fact": False}}
    return {"ui.confirmation_policy": {"action_ids": [r["action_id"] for r in inputs["ui_training_row"]["bindings"]],
        "event_order": "strict_sequence_position", "clock_order": "nondecreasing", "time_domain": "discrete_nat_ticks",
        "max_age_ticks": 10, "freshness_upper_inclusive": True, "correlation": "action_request_token",
        "cancellation": "since_latest_confirmation", "consumption": "every_prior_invocation_consumes_token"},
        "ui.trace_scope": {"trace_scope": "finite_observed_prefix", "unobserved_future": "unknown",
            "origin": "caller_supplied_sequence_position", "event_occurrences_attested": False, "whole_workflow_verified": False}}


def make_case(domain, *, mode="fixture_assumption", edit_values=None, edit_inputs=None,
              source_ref_change=None, partial_span=False, revision="context-index-r1", unresolved=False):
    inputs = fixtures.source_inputs(fixtures.rows(domain, "train")[0])
    if edit_inputs:
        edit_inputs(inputs)
    ref = source_owner.supplemental_source_ref(domain, **inputs)
    inputs["formula_inputs"] = [NativeFormulaEvidence(name, formula, ref) for name, formula in FORMULAS.items()]
    raw, _, _ = source_owner._source_bytes(domain, inputs)
    selected_ref = source_ref_change(ref) if source_ref_change else ref
    selected = context.ContextSpan.from_source(source_ref=selected_ref,
        span=SourceSpan("selected", selected_ref.ref_id, 0, 8 if partial_span else len(raw)),
        source_text=raw.decode(), partition="train")
    values = values_for(domain, inputs)
    if edit_values:
        edit_values(values)
    text = "Explicit authored interpretation declaration. " + json.dumps(values, sort_keys=True)
    policy_ref = SourceRef(ref_id="context:policy", source_uri="fixture://context-policy", source_id="context-policy",
        source_revision="authored-v1", content_sha256=hashlib.sha256(text.encode()).hexdigest())
    policy_span = context.ContextSpan.from_source(source_ref=policy_ref, span=SourceSpan("policy", policy_ref.ref_id, 0, len(text.encode())),
        source_text=text, partition="train")
    index = context.BoundedContextIndex([selected, policy_span], revision=revision,
        edges=[{"source_span_id": "selected", "target_span_id": "policy", "relation": "policy"}])
    projections = bridge.LEGAL_PROJECTIONS if domain == "legal_ir" else bridge.UI_PROJECTIONS
    slots = [{"slot_id": name, "sort": kind, "question": "Explicit authored interpretation declaration " + name,
        "projection_ids": list(projections)} for name, kind in bridge.SLOTS[domain].items()]
    assumed = [] if mode == "source_cited_declaration" or unresolved else [
        {"slot_id": name, "value": value, "rationale": "Explicit provisional diagnostic premise."} for name, value in values.items()]
    bundle = context.prepare_context_bundle(index, source_span_id="selected", slots=slots, fixtures=assumed)
    declarations = []
    if not unresolved:
        for name, value in values.items():
            evidence = {} if mode == "fixture_assumption" else {
                "citations": [{"span_id": "policy", "start_byte": 0, "end_byte": len(text.encode()), "quote": text}],
                "scope_review": {"relation": "governing_scope", "governing_scope": "This authored diagnostic source only.",
                    "alternatives_disposition": "This test explicitly selects the declared interpretation, not source truth."},
                "reviewer_record": {"reviewer_id": "test-caller", "review_method": "caller_declaration", "rationale": "Authored integration premises."}}
            declarations.append(prepare_context_binding(bundle, index=index, slot_id=name, mode=mode, value=value, **evidence))
    return {"domain_id": domain, "source_inputs": inputs, "context_index": index, "context_bundle": bundle, "bindings": declarations}


def prepare(case):
    return bridge.prepare_contextual_targets(**case)


def original_arguments(case):
    return {key: value for key, value in case.items() if key != "domain_id"}


@pytest.mark.parametrize("domain", ("legal_ir", "ui_ux_ir"))
@pytest.mark.parametrize("mode", ("fixture_assumption", "source_cited_declaration"))
def test_context_bindings_actually_prepare_all_native_projections(domain, mode):
    case = make_case(domain, mode=mode)
    prepared = prepare(case)
    assert bridge.validate_contextual_targets(prepared, **original_arguments(case))
    report = prepared.report
    observation = native.prepare_native_family_lean(report, source_inputs=prepared.source_inputs)
    assert len(report["family_inventory"]) == len(report["requested_families"]) == 40
    assert len(observation["per_projection"]) == (11 if domain == "legal_ir" else 16)
    assert all(row["semantic_lowering_supported"] for row in observation["per_projection"])
    assert all(row["lake_status"] == "not_run" for row in observation["per_projection"])
    receipt = prepared.to_dict()
    assert all(receipt[field] is False for field in bridge.FALSE)
    assert receipt["Lake_executed"] is receipt["SANY_executed"] is False
    assert {r["mode"] for r in receipt["context_bindings"]} == {mode}
    assert receipt["contextual_target_sha256"] == bridge._digest({k: v for k, v in receipt.items() if k != "contextual_target_sha256"})
    assert all(record["interpretation_assumption"]["discharged"] is False for record in receipt["context_bindings"])
    for row in observation["per_projection"]:
        if "interpretation" in (row["profile"] or "") or "confirmation" in (row["profile"] or ""):
            assert row["lowering"]["capability_floor_eligible"] is False
    if domain == "legal_ir":
        relation = receipt["legal_auxiliary_view_relation"]
        assert relation["independent_event_fact"] is relation["native_AST_containment_verified"] is False
        assert relation["trigger_origin_correspondence_verified"] is relation["trigger_occurrence_attested"] is False


@pytest.mark.parametrize("domain", ("legal_ir", "ui_ux_ir"))
def test_retrieval_candidates_cannot_choose_missing_interpretations(domain):
    case = make_case(domain, unresolved=True)
    assert case["context_bundle"]["slots"][0]["candidates"]
    with pytest.raises(ValueError, match="complete_closed_context_binding_set"):
        prepare(case)


@pytest.mark.parametrize("change", ("missing", "duplicate", "foreign_bundle"))
def test_binding_coverage_or_join_cannot_be_narrowed(change):
    case = make_case("legal_ir")
    if change == "missing":
        case["bindings"].pop()
    elif change == "duplicate":
        case["bindings"][-1] = case["bindings"][0]
    else:
        case["bindings"] = make_case("legal_ir", revision="foreign-index")["bindings"]
    with pytest.raises(ValueError):
        prepare(case)


@pytest.mark.parametrize("domain", ("legal_ir", "ui_ux_ir"))
@pytest.mark.parametrize("change", ("ref_id", "metadata", "review_status", "partial"))
def test_whole_native_source_identity_required_even_with_same_excerpt(domain, change):
    def alter(ref):
        if change == "ref_id":
            return replace(ref, ref_id="source:foreign")
        if change == "metadata":
            return replace(ref, metadata={"declared": "foreign"})
        from ipfs_datasets_py.logic.ir_core.provenance import SourceReviewStatus
        return replace(ref, review_status=SourceReviewStatus.HUMAN_REVIEWED)
    case = make_case(domain, partial_span=change == "partial", source_ref_change=None if change == "partial" else alter)
    with pytest.raises(ValueError, match="context_selected_source_ref_differs|whole_native_source_context_span_required"):
        prepare(case)


@pytest.mark.parametrize("edit", (
    lambda v: v["legal.temporal_model"].update(quantity=True),
    lambda v: v["legal.temporal_model"].update(quantity=11),
    lambda v: v["legal.temporal_model"].update(unit="hour"),
    lambda v: v["legal.temporal_model"].update(upper_inclusive=False),
    lambda v: v["legal.scope"].update(independent_event_fact=True),
    lambda v: v["legal.scope"].update(enclosing_modal_symbol="P"),
    lambda v: v["legal.temporal_anchor"].update(origin="invented_day_zero"),
))
def test_unsupported_or_conflicting_legal_values_rejected(edit):
    with pytest.raises(ValueError):
        prepare(make_case("legal_ir", edit_values=edit))


@pytest.mark.parametrize("edit", (
    lambda v: v["ui.confirmation_policy"].update(max_age_ticks=True),
    lambda v: v["ui.confirmation_policy"].update(action_ids=["another_action"]),
    lambda v: v["ui.confirmation_policy"].update(correlation="action_only"),
    lambda v: v["ui.trace_scope"].update(whole_workflow_verified=True),
))
def test_unsupported_ui_values_rejected(edit):
    with pytest.raises(ValueError):
        prepare(make_case("ui_ux_ir", edit_values=edit))


@pytest.mark.parametrize("field,value", (("confirmation_class", "double_confirm"), ("confirmation_class", "consent"),
    ("risk_class", "destructive"), ("risk_class", "low")))
def test_richer_or_weaker_ui_source_policy_is_not_overridden(field, value):
    with pytest.raises(ValueError, match="high_risk_single_confirm"):
        prepare(make_case("ui_ux_ir", edit_inputs=lambda inputs: inputs["ui_training_row"]["bindings"][0].update({field: value})))


def test_ui_source_text_override_cannot_bypass_canonical_row_join():
    case = make_case("ui_ux_ir")
    case["source_inputs"]["source_text"] = "unrelated textual source"
    with pytest.raises(ValueError, match="closed_bridge_source_inputs"):
        prepare(case)


def test_context_revision_changes_cache_identity_without_changing_interpretation():
    left = prepare(make_case("legal_ir", revision="r1"))
    right = prepare(make_case("legal_ir", revision="r2"))
    assert left.report == right.report
    assert left.to_dict()["contextual_target_sha256"] != right.to_dict()["contextual_target_sha256"]


def test_chosen_ui_value_reaches_actual_v7_interpretation():
    left = prepare(make_case("ui_ux_ir"))
    right = prepare(make_case("ui_ux_ir", mode="source_cited_declaration",
        edit_values=lambda v: v["ui.confirmation_policy"].update(max_age_ticks=12)))
    assert left.report["report_sha256"] != right.report["report_sha256"]
    assert [f["max_age_ticks"] for f in right.to_dict()["explicit_interpretations"][0]["formulas"][:2]] == [12, 12]


def test_unissued_or_detached_receipts_do_not_become_live_handles():
    case = make_case("legal_ir")
    with pytest.raises(ValueError, match="issued_contextual"):
        bridge.PreparedContextualTargets().to_dict()
    prepared = prepare(case)
    with pytest.raises(ValueError, match="issued_contextual"):
        bridge.validate_contextual_targets(prepared.to_dict(), **original_arguments(case))
    changed = prepared.report
    changed["source_digest"] = "0" * 64
    assert prepared.report["source_digest"] != changed["source_digest"]


def test_build_rejects_changed_original_context_before_any_lake_call(monkeypatch, tmp_path):
    original = make_case("legal_ir")
    prepared = prepare(original)
    changed = make_case("legal_ir", revision="new-context")
    calls = []
    monkeypatch.setattr(native, "build_native_family_lake", lambda *a, **kw: calls.append(kw))
    with pytest.raises(ValueError, match="differs_from_live_replay"):
        bridge.build_contextual_family_lake(prepared, **original_arguments(changed),
            lake_executable="unused", output_directory=tmp_path / "must-not-run")
    assert calls == []


def test_build_replays_after_tool_work_before_issuing_validation(monkeypatch, tmp_path):
    case = make_case("ui_ux_ir")
    prepared = prepare(case)
    def change_context(*args, **kwargs):
        case["context_bundle"]["selected_source"]["text"] = "changed during tool work"
        return object()
    monkeypatch.setattr(native, "build_native_family_lake", change_context)
    with pytest.raises(ValueError, match="context_bundle_differs"):
        bridge.build_contextual_family_lake(prepared, **original_arguments(case),
            lake_executable="unused", output_directory=tmp_path / "process-double-only")
