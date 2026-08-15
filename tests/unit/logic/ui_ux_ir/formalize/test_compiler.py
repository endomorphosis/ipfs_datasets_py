"""UIR-025: integrated multi-view formalization compiler."""

from __future__ import annotations

from ipfs_datasets_py.logic.ui_ux_ir.formalize.compiler import (
    CoverageKind,
    FormalizationInputs,
    UI_FORMALIZATION_COMPILER_ID,
    compile_ui_formalization,
)
from ipfs_datasets_py.logic.ui_ux_ir.formalize.contracts import FormalView, ResultAuthority
from ipfs_datasets_py.logic.ui_ux_ir.model.behavior import (
    BehaviorModel,
    BehaviorState,
    BehaviorTransition,
)
from ipfs_datasets_py.logic.ui_ux_ir.model.bindings import (
    ConfirmationClass,
    ProgramBindingTargetKind,
    RiskClass,
    UIActionBinding,
    UIProgramRef,
)
from ipfs_datasets_py.logic.ui_ux_ir.model.components import (
    CompositionEdgeKind,
    CompositionRelationship,
    SemanticComponent,
    UIComponentGraph,
)
from ipfs_datasets_py.logic.ui_ux_ir.runtime.events import (
    CanonicalInteractionEvent,
    EventKind,
    EventProvenance,
)
from ipfs_datasets_py.logic.ui_ux_ir.schema import UIIRValidationError
import pytest


def _sample_graph() -> UIComponentGraph:
    form = SemanticComponent(
        component_id="form_main",
        role="form",
        child_ids=("btn_submit",),
        source_ref_ids=("src:form",),
    )
    button = SemanticComponent(
        component_id="btn_submit",
        role="button",
        parent_id="form_main",
        source_ref_ids=("src:btn",),
    )
    edge = CompositionRelationship(
        edge_id="e1",
        kind=CompositionEdgeKind.PARENT,
        source_component_id="form_main",
        target_component_id="btn_submit",
    )
    return UIComponentGraph(
        components=(form, button),
        relationships=(edge,),
        entry_component_ids=("form_main",),
    )


def _sample_behavior() -> BehaviorModel:
    return BehaviorModel(
        model_id="bm",
        states=(
            BehaviorState(state_id="idle"),
            BehaviorState(state_id="done", terminal=True),
        ),
        transitions=(
            BehaviorTransition(
                transition_id="t1",
                source_state_ids=("idle",),
                target_state_id="done",
                event_id="submit",
            ),
        ),
        initial_state_ids=("idle",),
    )


def _sample_binding() -> UIActionBinding:
    return UIActionBinding(
        binding_id="b1",
        action_id="delete",
        program_ref=UIProgramRef(
            target_kind=ProgramBindingTargetKind.MCP_IDL,
            mcp_idl_interface_cid=(
                "bafkreicotxqdc6qhz3h3miegt37q3iz2syjrhj7z4mhjd2sidi35bx3t5i"
            ),
            mcp_idl_method_name="delete",
        ),
        risk_class=RiskClass.HIGH,
        confirmation_class=ConfirmationClass.CONFIRM,
    )


def _sample_events() -> tuple[CanonicalInteractionEvent, ...]:
    return (
        CanonicalInteractionEvent(
            event_id="e1",
            kind=EventKind.ACTIVATE,
            target_component_id="btn_submit",
            timestamp_ms=1,
            provenance=EventProvenance.HUMAN,
            capability_id="pointer_mouse",
            consent_ok=True,
        ),
    )


def test_integrated_compiler_emits_separate_views_not_mixed_blob() -> None:
    artifact = compile_ui_formalization(
        FormalizationInputs(
            component_graph=_sample_graph(),
            behavior_model=_sample_behavior(),
            action_bindings=(_sample_binding(),),
            events=_sample_events(),
            artifact_id="art:1",
        )
    )
    assert artifact.compiler_id == UI_FORMALIZATION_COMPILER_ID
    assert artifact.artifact_id == "art:1"
    assert artifact.flogic is not None
    assert artifact.event_calculus is not None
    assert artifact.tdfol is not None
    assert artifact.dcec is not None
    # Views remain typed modules — not a concatenated mixed-logic blob.
    assert artifact.flogic.view is FormalView.FLOGIC
    assert artifact.event_calculus.view is FormalView.EVENT_CALCULUS
    assert artifact.tdfol.view is FormalView.TDFOL
    assert artifact.dcec.view is FormalView.DCEC
    assert "mixed_logic_concatenation" in artifact.unsupported_semantics
    assert artifact.result_authority is ResultAuthority.ADVISORY


def test_coverage_receipt_covers_required_semantics() -> None:
    artifact = compile_ui_formalization(
        FormalizationInputs(component_graph=_sample_graph())
    )
    by_id = {c.source_semantic_id: c for c in artifact.coverage}
    assert "source.semantic.raw_emg" in by_id
    raw = by_id["source.semantic.raw_emg"]
    assert raw.kind == CoverageKind.INTENTIONALLY_NON_FORMAL
    # Every coverage kind is one of the four accepted dispositions.
    allowed = {
        CoverageKind.REPRESENTED,
        CoverageKind.APPROXIMATED,
        CoverageKind.UNSUPPORTED,
        CoverageKind.INTENTIONALLY_NON_FORMAL,
    }
    for receipt in artifact.coverage:
        assert receipt.kind in allowed
        for kind in receipt.views.values():
            assert kind in allowed


def test_backend_unavailability_is_not_reported_as_proof() -> None:
    artifact = compile_ui_formalization(
        FormalizationInputs(action_bindings=(_sample_binding(),))
    )
    assert artifact.backend_requests
    for req in artifact.backend_requests:
        if req.status == "unavailable":
            assert req.result_authority in {
                ResultAuthority.NONE,
                ResultAuthority.ADVISORY,
                ResultAuthority.DECLARATION,
                ResultAuthority.OBSERVATION,
            }
            assert req.result_authority is not ResultAuthority.PROOF
    messages = " ".join(d.message for d in artifact.diagnostics)
    assert "not reported as proof" in messages or any(
        d.code == "backend.unavailable" for d in artifact.diagnostics
    )


def test_cross_view_links_and_proof_obligations() -> None:
    artifact = compile_ui_formalization(
        FormalizationInputs(
            component_graph=_sample_graph(),
            action_bindings=(_sample_binding(),),
            events=_sample_events(),
        )
    )
    assert artifact.cross_view_links
    assert artifact.proof_obligations
    assert any("confirm" in o or "invoke" in o for o in artifact.proof_obligations)
    # Determinism
    again = compile_ui_formalization(
        FormalizationInputs(
            component_graph=_sample_graph(),
            action_bindings=(_sample_binding(),),
            events=_sample_events(),
        )
    )
    assert artifact.cross_view_links == again.cross_view_links
    assert artifact.proof_obligations == again.proof_obligations


def test_empty_inputs_fail_closed() -> None:
    with pytest.raises(UIIRValidationError, match="at least one"):
        compile_ui_formalization(FormalizationInputs())
