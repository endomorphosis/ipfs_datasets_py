"""UIR-041: bounded DOM/ARIA import and web/desktop rendering (Python)."""

from __future__ import annotations

from ipfs_datasets_py.logic.ui_ux_ir.projection.web import (
    UIIR_WEB_PROJECTION_INTERFACE,
    UIIR_WEB_RENDERER_INTERFACE,
    UIIRWebRenderer,
    WebInteractionState,
    WebSurfaceKind,
    project_to_web,
    render_web,
    web_pilot_problem,
)
from ipfs_datasets_py.logic.ui_ux_ir.source_adapters.dom_aria import (
    DOMARIA_UIIR_ADAPTER,
    DomAriaAdapterError,
    adapt_dom_aria_to_uiir,
)


def _dom_aria_snapshot() -> dict:
    return {
        "document_id": "doc:web-form",
        "title": "Web form snapshot",
        "root": {
            "node_id": "root",
            "role": "form",
            "name": "Profile form",
            "tag_name": "form",
            "css_classes": ["form-root", "react-form"],
            "framework_hints": {"framework": "react", "component": "Form"},
            "children": [
                {
                    "node_id": "email",
                    "role": "textbox",
                    "name": "Email",
                    "tag_name": "input",
                    "value": "user@example.com",
                    "states": {"required": "true", "invalid": "true"},
                    "validation": {
                        "valid": False,
                        "message": "Enter a valid email",
                        "required": True,
                        "invalid_state": "true",
                    },
                    "actions": ["edit"],
                    "focus_order": 1,
                    "relationships": {"labelledby": ["email-label"]},
                    "css_classes": ["input", "is-invalid"],
                    "css_inline": "color: red",
                    "attributes": {
                        "type": "email",
                        "onclick": "alert(1)",
                        "aria-required": "true",
                    },
                },
                {
                    "node_id": "email-label",
                    "role": "presentation",
                    "name": "Email label",
                    "tag_name": "label",
                    "text_content": "Email",
                },
                {
                    "node_id": "submit",
                    "role": "button",
                    "name": "Submit",
                    "tag_name": "button",
                    "actions": ["click"],
                    "focus_order": 2,
                    "attributes": {"type": "submit"},
                },
                {
                    "node_id": "confirm",
                    "role": "alertdialog",
                    "name": "Confirm delete",
                    "tag_name": "div",
                    "focus_order": 0,
                },
                {
                    "node_id": "error",
                    "role": "alert",
                    "name": "Save failed",
                    "tag_name": "div",
                    "live": {"politeness": "assertive", "atomic": True},
                },
                {
                    "node_id": "denied",
                    "role": "alert",
                    "name": "Access denied",
                    "tag_name": "div",
                },
                {
                    "node_id": "status",
                    "role": "status",
                    "name": "Working",
                    "tag_name": "div",
                    "states": {"busy": "true"},
                    "live": "polite",
                },
                {
                    "node_id": "evil-script",
                    "tag_name": "script",
                    "name": "should-reject",
                    "text_content": "alert('xss')",
                },
            ],
        },
    }


def test_dom_aria_import_preserves_semantic_subset() -> None:
    result = adapt_dom_aria_to_uiir(_dom_aria_snapshot())
    assert result.adapter == DOMARIA_UIIR_ADAPTER
    assert result.execution_performed is False
    roles = {c.role for c in result.components}
    assert "aria:form" in roles
    assert "aria:textbox" in roles
    assert "aria:button" in roles
    assert "aria:alertdialog" in roles
    assert "aria:alert" in roles
    # Script tag never imported as a component.
    assert all("script" not in c.component_id for c in result.components)
    assert any(loss.category.value == "rejected" for loss in result.losses)
    # Focus order explicit.
    assert result.focus_order
    assert "component:confirm" in result.focus_order or any(
        "confirm" in fid for fid in result.focus_order
    )
    # Validation + live feedback retained.
    assert result.node_validations
    assert result.live_regions
    # CSS/framework retained as metadata or loss.
    assert result.source_metadata
    assert any(
        loss.category.value == "source_metadata" for loss in result.losses
    )
    # Event handlers sanitized, never executed.
    assert any(loss.category.value == "sanitized" for loss in result.losses)
    blob = str(result.to_dict()).lower()
    assert "onclick" not in blob or "sanitized" in blob


def test_web_projection_from_solver_renders_critical_surfaces() -> None:
    artifact = project_to_web(web_pilot_problem())
    assert artifact.interface == UIIR_WEB_PROJECTION_INTERFACE
    assert artifact.renderer == UIIR_WEB_RENDERER_INTERFACE
    assert artifact.execution_performed is False
    assert artifact.policy_owner == "UIProjectionSolver@1"
    kinds = {n.kind for n in artifact.nodes}
    assert WebSurfaceKind.ACTION in kinds
    assert WebSurfaceKind.CONFIRMATION in kinds
    assert WebSurfaceKind.ALERT in kinds
    assert WebSurfaceKind.DENIAL in kinds
    for node in artifact.nodes:
        if node.kind in {
            WebSurfaceKind.DENIAL,
            WebSurfaceKind.ALERT,
            WebSurfaceKind.CONFIRMATION,
        }:
            assert node.visible is True
            assert node.accessible is True
            assert node.body
    assert artifact.focus.order
    model = render_web(artifact)
    assert model["execution_performed"] is False
    assert model["elements"]
    critical_text = " ".join(el["text"] for el in model["elements"]).lower()
    assert "denied" in critical_text or "error" in critical_text
    assert "confirm" in critical_text


def test_web_projection_from_dom_aria_roundtrip_semantics() -> None:
    adapted = adapt_dom_aria_to_uiir(_dom_aria_snapshot())
    web = project_to_web(adapted)
    assert web.nodes
    # Role/name/value/state preserved for email control.
    email = next(n for n in web.nodes if "email" in n.node_id and n.role.endswith("textbox"))
    assert email.name
    assert email.value == "user@example.com"
    assert email.states.get("required") == "true" or email.validation.required
    assert email.validation.message
    assert email.actions
    # Relationships preserved.
    assert any(n.relationships for n in web.nodes)
    # Focus order present and keyboard plan set.
    assert web.focus.order
    assert web.focus.keyboard_mode.value in {
        "tab_order",
        "roving_tabindex",
        "dialog_trap",
    }
    # Live feedback.
    assert any(
        n.live.politeness in {"polite", "assertive"} for n in web.nodes
    )
    # Source metadata / losses for CSS and framework.
    assert web.source_metadata
    assert any(loss.category == "source_metadata" for loss in web.losses)
    # Never executes.
    assert web.execution_performed is False
    html = web.to_accessible_html_model()
    assert html["execution_performed"] is False
    assert "<script" not in str(html).lower()


def test_invalid_source_receipt_for_unsupported_role() -> None:
    payload = {
        "document_id": "doc:bad",
        "title": "Bad",
        "root": {
            "node_id": "root",
            "role": "document",
            "name": "Root",
            "children": [
                {
                    "node_id": "custom",
                    "role": "not-a-real-role-xyz",
                    "name": "Custom",
                },
                {
                    "node_id": "ok",
                    "role": "button",
                    "name": "OK",
                },
            ],
        },
    }
    result = adapt_dom_aria_to_uiir(payload)
    assert any(
        loss.category.value == "unsupported" and "role" in loss.reason.lower()
        for loss in result.losses
    )
    # Supported sibling still imported.
    assert any(c.role.endswith("button") for c in result.components)


def test_executable_markup_never_executed() -> None:
    payload = {
        "document_id": "doc:xss",
        "title": "XSS",
        "root": {
            "node_id": "root",
            "role": "region",
            "name": "Root",
            "children": [
                {
                    "node_id": "btn",
                    "role": "button",
                    "name": "Click <script>alert(1)</script>",
                    "attributes": {
                        "href": "javascript:alert(1)",
                        "onclick": "doEvil()",
                    },
                    "text_content": "javascript:void(0)",
                }
            ],
        },
    }
    result = adapt_dom_aria_to_uiir(payload)
    assert result.execution_performed is False
    rendered = render_web(result)
    assert rendered["execution_performed"] is False
    blob = str(rendered).lower()
    assert "<script" not in blob
    assert "javascript:" not in blob
    # Name sanitized.
    btn = next(c for c in result.components if "btn" in c.component_id)
    name_locs = {
        loc.localization_id: loc.default_text for loc in result.localization
    }
    name = name_locs.get(btn.accessible_name_ref, "")
    assert "<script" not in name.lower()


def test_uiir_web_renderer_class_and_interaction_states() -> None:
    renderer = UIIRWebRenderer()
    assert renderer.interface == UIIR_WEB_RENDERER_INTERFACE
    artifact = renderer.project(web_pilot_problem())
    assert artifact.nodes
    states = {n.interaction_state for n in artifact.nodes}
    assert WebInteractionState.CONFIRMATION in states or any(
        n.kind is WebSurfaceKind.CONFIRMATION for n in artifact.nodes
    )
    model = renderer.render(artifact)
    assert model["renderer"] == UIIR_WEB_RENDERER_INTERFACE
    assert model["focus_order"]


def test_empty_root_rejection() -> None:
    payload = {
        "document_id": "doc:empty",
        "title": "Empty",
        "root": {
            "node_id": "root",
            "tag_name": "script",
            "name": "evil",
        },
    }
    try:
        adapt_dom_aria_to_uiir(payload)
        raised = False
    except DomAriaAdapterError:
        raised = True
    assert raised
