"""UIR-012: semantic components composition and abstract layout."""

from __future__ import annotations

import pytest

from ipfs_datasets_py.logic.ui_ux_ir.model.components import (
    CompositionEdgeKind,
    CompositionRelationship,
    SemanticComponent,
    UIComponentGraph,
    validate_component_graph,
)
from ipfs_datasets_py.logic.ui_ux_ir.model.layout import (
    AbstractLayoutConstraint,
    AdaptationPolicy,
    LayoutOrder,
    OrderAxis,
    RequiredSemanticPolicy,
    UILayoutConstraints,
    reject_css_or_executable_layout,
    validate_layout_constraints,
)
from ipfs_datasets_py.logic.ui_ux_ir.schema import LayoutRegionKind, UILayoutRegion, UIIRValidationError


def _simple_graph() -> UIComponentGraph:
    form = SemanticComponent(
        component_id="form_main",
        role="form",
        child_ids=("btn_submit",),
    )
    button = SemanticComponent(
        component_id="btn_submit",
        role="button",
        parent_id="form_main",
    )
    edge = CompositionRelationship(
        edge_id="e_parent",
        kind=CompositionEdgeKind.PARENT,
        source_component_id="form_main",
        target_component_id="btn_submit",
    )
    return UIComponentGraph(
        components=(form, button),
        relationships=(edge,),
        entry_component_ids=("form_main",),
    )


def test_component_graph_validates_without_cycles() -> None:
    graph = validate_component_graph(_simple_graph())
    assert graph.entry_component_ids == ("form_main",)
    assert {c.component_id for c in graph.components} == {"form_main", "btn_submit"}


def test_component_graph_rejects_parent_cycles() -> None:
    a = SemanticComponent(component_id="a", role="group", child_ids=("b",), parent_id="b")
    b = SemanticComponent(component_id="b", role="group", child_ids=("a",), parent_id="a")
    edges = (
        CompositionRelationship(
            edge_id="e1",
            kind=CompositionEdgeKind.PARENT,
            source_component_id="a",
            target_component_id="b",
        ),
        CompositionRelationship(
            edge_id="e2",
            kind=CompositionEdgeKind.PARENT,
            source_component_id="b",
            target_component_id="a",
        ),
    )
    with pytest.raises(Exception) as exc:
        validate_component_graph(UIComponentGraph(components=(a, b), relationships=edges))
    assert "cycle" in str(exc.value).lower()


def test_component_graph_rejects_dangling_relationship() -> None:
    form = SemanticComponent(component_id="form_main", role="form")
    edge = CompositionRelationship(
        edge_id="e_bad",
        kind=CompositionEdgeKind.CHILD,
        source_component_id="form_main",
        target_component_id="missing",
    )
    with pytest.raises(Exception):
        validate_component_graph(
            UIComponentGraph(components=(form,), relationships=(edge,))
        )


def test_layout_orders_are_axis_distinct() -> None:
    region = UILayoutRegion(
        region_id="main",
        kind=LayoutRegionKind.FLOW,
        component_ids=("form_main", "btn_submit"),
    )
    orders = (
        LayoutOrder(axis=OrderAxis.READING, component_ids=("form_main", "btn_submit")),
        LayoutOrder(axis=OrderAxis.VISUAL, component_ids=("btn_submit", "form_main")),
        LayoutOrder(axis=OrderAxis.FOCUS, component_ids=("form_main", "btn_submit")),
    )
    req = RequiredSemanticPolicy(
        semantic_id="btn_submit",
        semantic_kind="action",
        adaptation_policy=AdaptationPolicy.PRESERVE,
    )
    model = UILayoutConstraints(
        regions=(region,),
        orders=orders,
        required_semantics=(req,),
        known_component_ids=("form_main", "btn_submit"),
    )
    validated = validate_layout_constraints(model)
    axes = {order.axis for order in validated.orders}
    assert axes == {OrderAxis.READING, OrderAxis.VISUAL, OrderAxis.FOCUS}
    # Reading/focus may share order but visual is intentionally different.
    reading = next(o for o in validated.orders if o.axis is OrderAxis.READING)
    visual = next(o for o in validated.orders if o.axis is OrderAxis.VISUAL)
    assert reading.component_ids != visual.component_ids


def test_layout_rejects_css_and_executable_expressions() -> None:
    with pytest.raises(UIIRValidationError):
        reject_css_or_executable_layout("display: flex; margin: 1rem;")
    with pytest.raises(UIIRValidationError):
        reject_css_or_executable_layout("onclick=submit()")
    region = UILayoutRegion(
        region_id="main",
        kind=LayoutRegionKind.FLOW,
        component_ids=("form_main",),
    )
    with pytest.raises(UIIRValidationError):
        validate_layout_constraints(
            UILayoutConstraints(
                regions=(region,),
                constraints=(
                    AbstractLayoutConstraint(
                        constraint_id="bad",
                        kind="alignment",
                        expression_ref="calc(100vw - 2rem)",
                    ),
                ),
                known_component_ids=("form_main",),
            )
        )


def test_required_actions_carry_preserve_or_fallback_policies() -> None:
    region = UILayoutRegion(
        region_id="main",
        kind=LayoutRegionKind.STACK,
        component_ids=("btn_submit",),
    )
    preserve = RequiredSemanticPolicy(
        semantic_id="btn_submit",
        semantic_kind="action",
        adaptation_policy=AdaptationPolicy.PRESERVE,
    )
    fallback = RequiredSemanticPolicy(
        semantic_id="btn_feedback",
        semantic_kind="feedback",
        adaptation_policy=AdaptationPolicy.FALLBACK,
        fallback_ref="msg:submit_unavailable",
    )
    model = UILayoutConstraints(
        regions=(region,),
        required_semantics=(preserve, fallback),
        known_component_ids=("btn_submit", "btn_feedback"),
    )
    validated = validate_layout_constraints(model)
    policies = {item.adaptation_policy for item in validated.required_semantics}
    assert AdaptationPolicy.PRESERVE in policies
    assert AdaptationPolicy.FALLBACK in policies
