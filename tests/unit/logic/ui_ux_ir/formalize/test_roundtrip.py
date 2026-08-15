"""UIR-026: semantic decompilation and layered round-trip equivalence."""

from __future__ import annotations

from ipfs_datasets_py.logic.ui_ux_ir.formalize.compiler import (
    FormalizationInputs,
    compile_ui_formalization,
)
from ipfs_datasets_py.logic.ui_ux_ir.formalize.decompiler import (
    decompile_ui_formalization,
)
from ipfs_datasets_py.logic.ui_ux_ir.formalize.roundtrip import (
    EquivalenceLayer,
    RoundTripDocument,
    roundtrip_ui_ir,
)
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


def _sample_doc() -> RoundTripDocument:
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
    graph = UIComponentGraph(
        components=(form, button),
        relationships=(edge,),
        entry_component_ids=("form_main",),
    )
    behavior = BehaviorModel(
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
    binding = UIActionBinding(
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
    events = (
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
    return RoundTripDocument(
        document_id="d1",
        component_graph=graph,
        behavior_model=behavior,
        action_bindings=(binding,),
        events=events,
    )


def test_decompiler_never_invents_grants_or_claims_pixels() -> None:
    doc = _sample_doc()
    art = compile_ui_formalization(
        FormalizationInputs(
            component_graph=doc.component_graph,
            behavior_model=doc.behavior_model,
            action_bindings=doc.action_bindings,
            events=doc.events,
        )
    )
    recon = decompile_ui_formalization(art)
    assert recon.receipt.invented_grants == ()
    assert recon.receipt.claims_source_equality is False
    assert recon.receipt.claims_pixel_equality is False
    assert recon.receipt.deontic_non_weakening is True
    assert recon.components
    assert recon.norms
    assert "source_equality" in recon.excluded_equivalence_claims
    assert "pixel_equality" in recon.excluded_equivalence_claims


def test_roundtrip_passes_layered_semantic_equivalence() -> None:
    report = roundtrip_ui_ir(_sample_doc())
    assert report.overall_passed is True
    by_layer = {layer.layer: layer for layer in report.layers}
    assert by_layer[EquivalenceLayer.DEONTIC_NON_WEAKENING].passed is True
    assert by_layer[EquivalenceLayer.GRAPH_ISOMORPHISM].passed is True
    assert by_layer[EquivalenceLayer.CANONICAL_IDENTITY].passed is True
    assert report.excluded_claims == ("source_equality", "pixel_equality")
    assert report.reconstruction.receipt.faithful is True


def test_ambiguous_human_intent_produces_clarification() -> None:
    report = roundtrip_ui_ir(_sample_doc())
    assert report.reconstruction.clarifications or report.reconstruction.alternatives
