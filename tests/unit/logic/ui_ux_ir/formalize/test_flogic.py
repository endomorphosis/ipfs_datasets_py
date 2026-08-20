"""UIR-021: structural FOL / F-logic compiler."""

from __future__ import annotations

from ipfs_datasets_py.logic.ui_ux_ir.formalize.contracts import FormalView
from ipfs_datasets_py.logic.ui_ux_ir.formalize.flogic import (
    compile_component_graph_to_flogic,
)
from ipfs_datasets_py.logic.ui_ux_ir.model.components import (
    CompositionEdgeKind,
    CompositionRelationship,
    SemanticComponent,
    UIComponentGraph,
)


def test_flogic_compilation_is_deterministic() -> None:
    form = SemanticComponent(component_id="form_main", role="form", child_ids=("btn_submit",))
    button = SemanticComponent(component_id="btn_submit", role="button", parent_id="form_main")
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
    a = compile_component_graph_to_flogic(graph)
    b = compile_component_graph_to_flogic(graph)
    assert a.facts == b.facts
    assert a.view is FormalView.FLOGIC
    predicates = {f.predicate for f in a.facts}
    assert "ui_component" in predicates
    assert "ui_contains" in predicates or "ui_parent" in predicates
    assert "pixel_layout" in a.unsupported
