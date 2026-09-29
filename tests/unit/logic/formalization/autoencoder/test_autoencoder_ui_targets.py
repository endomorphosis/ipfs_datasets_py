"""Actual UI views supervise features without replacing modality checks."""

from dataclasses import replace

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder.ui_targets import prepare_ui_targets
from ipfs_datasets_py.logic.ui_ux_ir.formalize.roundtrip import RoundTripDocument
from ipfs_datasets_py.logic.ui_ux_ir.model.behavior import BehaviorModel, BehaviorState, BehaviorTransition
from ipfs_datasets_py.logic.ui_ux_ir.model.bindings import (
    ConfirmationClass, ProgramBindingTargetKind, RiskClass, UIActionBinding, UIProgramRef,
)
from ipfs_datasets_py.logic.ui_ux_ir.model.components import SemanticComponent, UIComponentGraph
from ipfs_datasets_py.logic.ui_ux_ir.model.experience import (
    AccessibilityRole, AccessibleNameBinding, ExperienceModel, LocalizationMessage,
)
from ipfs_datasets_py.logic.ui_ux_ir.projection.capabilities import desktop_profile, headless_profile
from ipfs_datasets_py.logic.ui_ux_ir.projection.solver import ProjectionItem, ProjectionProblem
from ipfs_datasets_py.logic.ui_ux_ir.runtime.events import CanonicalInteractionEvent, EventKind, EventProvenance


def _document(*, complete=False):
    doc = RoundTripDocument(document_id="doc:confirm-delete", component_graph=UIComponentGraph(
        components=(SemanticComponent(component_id="delete", role="button"),),
        entry_component_ids=("delete",),
    ))
    if not complete:
        return doc
    return replace(doc,
        behavior_model=BehaviorModel(model_id="workflow", states=(
            BehaviorState(state_id="pending"), BehaviorState(state_id="cancelled", terminal=True),
        ), transitions=(BehaviorTransition(transition_id="timeout", source_state_ids=("pending",),
            target_state_id="cancelled", event_id="cancel", timeout_ms=5000),), initial_state_ids=("pending",)),
        action_bindings=(UIActionBinding(binding_id="binding:delete", action_id="delete",
            program_ref=UIProgramRef(target_kind=ProgramBindingTargetKind.MCP_IDL,
                mcp_idl_interface_cid="bafkreicotxqdc6qhz3h3miegt37q3iz2syjrhj7z4mhjd2sidi35bx3t5i",
                mcp_idl_method_name="delete"), risk_class=RiskClass.HIGH,
            confirmation_class=ConfirmationClass.CONFIRM),),
        events=(CanonicalInteractionEvent(event_id="click:delete", kind=EventKind.ACTIVATE,
            target_component_id="delete", timestamp_ms=1, provenance=EventProvenance.HUMAN,
            capability_id="pointer_mouse", consent_ok=True),),
        experience=ExperienceModel(model_id="accessible-delete", accessible_names=(
            AccessibleNameBinding(component_id="delete", name_message_id="delete.label",
                role=AccessibilityRole.BUTTON, modality_alternative_ids=("speech_output",)),
        ), messages=(LocalizationMessage(message_id="delete.label", default_text="Delete record"),)),
    )


def _observations(payload):
    return {row["validator_id"]: row for row in payload["validation"]}


def test_structural_targets_do_not_invent_other_families_or_qualification():
    target = prepare_ui_targets(_document())
    payload = target.to_dict()
    assert {row["logic_family"] for row in payload["projections"]} == {"frame_logic"}
    assert payload["projections"][0]["expression"]["facts"][0]["predicate"] == "ui_component"
    assert payload["ready_for_training"] is True
    assert payload["qualified"] is False
    assert payload["admitted"] is False
    assert payload["formalized"] is False
    observations = _observations(payload)
    assert observations["ui_ux.native_compile"]["status"] == "passed"
    assert observations["ui_ux.source_gate_adapter"]["details"]["code"] == "ui_ux.adapter_not_implemented"
    assert observations["ui_ux.roundtrip.trace_equivalence"]["status"] == "not_run"
    assert observations["ui_ux.device_projection"]["status"] == "not_run"
    assert prepare_ui_targets(_document()).digest == target.digest


def test_real_temporal_accessibility_and_device_checks_preserve_scope():
    doc = _document(complete=True)
    problem = ProjectionProblem(problem_id="device:delete", document_id=doc.document_id, items=(
        ProjectionItem(item_id="delete", semantic_kind="action", mandatory=True,
            required_capability_ids=("display",), label="Delete record", action_cost=1),
        ProjectionItem(item_id="delete-name", semantic_kind="accessibility", mandatory=True,
            required_capability_ids=("display",), label="Delete record"),
    ))
    payload = prepare_ui_targets(doc, projection_problem=problem, device_profile=desktop_profile()).to_dict()
    assert {row["logic_family"] for row in payload["projections"]} == {
        "frame_logic", "event_calculus", "tdfol", "dcec",
    }
    ec = [expression for row in payload["projections"] if row["logic_family"] == "event_calculus" for expression in row["expression"]["formulas"]]
    assert any("5000" in expression["args"] for expression in ec)
    norms = [expression for row in payload["projections"] if row["logic_family"] == "tdfol" for expression in row["expression"]["formulas"]]
    assert any(row["operator"] == "obligation" and "confirm(delete)" in row["proposition"] for row in norms)
    observations = _observations(payload)
    assert observations["ui_ux.roundtrip.accessibility"]["status"] == "passed"
    assert observations["ui_ux.roundtrip.trace_equivalence"]["details"]["evaluated"] is True
    assert observations["ui_ux.device_projection"]["status"] == "passed"
    assert observations["ui_ux.device_projection"]["details"]["scope"] == "supplied projection problem only"
    assert payload["qualified"] is False
    assert any(gap["code"] == "ui_ux.family_syntax_not_checked" for gap in payload["qualification_gaps"])


def test_unavailable_device_capability_is_not_a_projection_pass():
    doc = _document()
    problem = ProjectionProblem(problem_id="device:delete", document_id=doc.document_id, items=(
        ProjectionItem(item_id="delete", semantic_kind="action", mandatory=True,
            required_capability_ids=("display",)),
    ))
    payload = prepare_ui_targets(doc, projection_problem=problem, device_profile=headless_profile()).to_dict()
    assert _observations(payload)["ui_ux.device_projection"]["status"] == "failed"
    assert payload["ready_for_training"] is True  # Structural records are still actual targets.
    assert payload["qualified"] is False


def test_empty_and_invalid_accessibility_inputs_fail_target_readiness():
    empty = prepare_ui_targets(RoundTripDocument(document_id="empty")).to_dict()
    assert empty["projections"] == []
    assert empty["ready_for_training"] is False
    assert _observations(empty)["ui_ux.native_compile"]["status"] == "failed"
    doc = _document(complete=True)
    bad = replace(doc, experience=replace(doc.experience, accessible_names=(
        replace(doc.experience.accessible_names[0], modality_alternative_ids=()),
    )))
    payload = prepare_ui_targets(bad).to_dict()
    assert payload["ready_for_training"] is False
    assert payload["source_digest"] != prepare_ui_targets(doc).to_dict()["source_digest"]
    assert "modality alternatives" in _observations(payload)["ui_ux.native_compile"]["details"]["error"]


def test_projection_binding_and_input_types_fail_closed():
    with pytest.raises(TypeError, match="RoundTripDocument"):
        prepare_ui_targets("button")
    with pytest.raises(ValueError, match="together"):
        prepare_ui_targets(_document(), device_profile=desktop_profile())
    problem = ProjectionProblem(problem_id="device:other", document_id="other", items=(
        ProjectionItem(item_id="delete", semantic_kind="action"),
    ))
    with pytest.raises(ValueError, match="does not match"):
        prepare_ui_targets(_document(), projection_problem=problem, device_profile=desktop_profile())


def test_changed_timeout_updates_bound_targets_without_changing_projection_ids():
    doc = _document(complete=True)
    changed = replace(doc, behavior_model=replace(doc.behavior_model, transitions=(
        replace(doc.behavior_model.transitions[0], timeout_ms=6000),
    )))
    before = prepare_ui_targets(doc).to_dict()
    after = prepare_ui_targets(changed).to_dict()
    assert before["source_digest"] != after["source_digest"]
    old = {row["projection_id"]: row for row in before["projections"]}
    new = {row["projection_id"]: row for row in after["projections"]}
    assert old.keys() == new.keys()
    assert old["ui_ux_ir:event_calculus"] != new["ui_ux_ir:event_calculus"]
    assert old["ui_ux_ir:tdfol"] == new["ui_ux_ir:tdfol"]


def test_source_missing_stops_target_preparation(monkeypatch):
    from ipfs_datasets_py.logic.conformance.ui_ux_logic_gate_v2 import UIUXFormalizationAdapter, UIUXSourceMissingError

    def missing_source(self, document):
        raise UIUXSourceMissingError()

    monkeypatch.setattr(UIUXFormalizationAdapter, "formalize", missing_source)
    payload = prepare_ui_targets(_document()).to_dict()
    assert payload["projections"] == []
    assert payload["ready_for_training"] is False
    assert _observations(payload)["ui_ux.native_compile"]["status"] == "not_run"
