"""Web/desktop accessible projection (UIIRWebProjection@1).

Mirrors the SwissKnife ``projectUIIRToWeb`` contract at a semantic level:
deterministic accessible nodes, no script execution, mandatory surfaces stay
visible.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from .semantic_items import SemanticItem, document_to_semantic_items


UIIR_WEB_PROJECTION_INTERFACE = "UIIRWebProjection@1"
UIIR_WEB_PROJECTION_SCHEMA_VERSION = "ui-web-projection/v1"


@dataclass(frozen=True, slots=True)
class WebLoss:
    path: str
    reason: str
    category: str = "loss"

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "path": self.path,
            "reason": self.reason,
        }


def _role_for(kind: str) -> str:
    k = kind.lower()
    if k == "action":
        return "button"
    if k in {"error", "denial"}:
        return "alert"
    if k in {"confirmation", "consent"}:
        return "alertdialog"
    if k == "feedback":
        return "status"
    if k == "text_input":
        return "textbox"
    return "region"


def _surface_for(kind: str, role: str) -> str:
    if kind in {"error", "denial"}:
        return "error"
    if kind in {"confirmation", "consent"}:
        return "confirmation"
    if kind == "action" or role == "button":
        return "control"
    if kind == "feedback":
        return "status"
    if kind == "text_input":
        return "input"
    return "structure"


def project_to_web(
    document: Mapping[str, Any] | Any = None,
    *,
    items: Sequence[SemanticItem | Mapping[str, Any]] | None = None,
    render_mode: str = "accessible",
) -> dict[str, Any]:
    """Project document or semantic items into a web accessible model."""
    if items is None:
        if document is None:
            raise ValueError("document or items required")
        semantic = document_to_semantic_items(document)
    else:
        semantic = [
            item
            if isinstance(item, SemanticItem)
            else SemanticItem(
                item_id=str(item.get("item_id") or ""),
                semantic_kind=str(item.get("semantic_kind") or "structure"),
                label=str(item.get("label") or ""),
                component_id=str(item.get("component_id") or ""),
                order=int(item.get("order") or 100),
                mandatory=bool(item.get("mandatory")),
                disposition=str(item.get("disposition") or "preserved"),
                fallback_ref=str(item.get("fallback_ref") or ""),
                text=str(item.get("text") or item.get("label") or ""),
            )
            for item in items
        ]

    nodes: list[dict[str, Any]] = []
    losses: list[WebLoss] = []
    sorted_items = sorted(semantic, key=lambda i: (i.order, i.item_id))

    for index, item in enumerate(sorted_items):
        if not item.item_id:
            raise ValueError(f"items[{index}].item_id is required")
        kind = item.semantic_kind.lower()
        role = _role_for(kind)
        surface = _surface_for(kind, role)
        disposition = item.disposition or "preserved"
        label = (item.label or item.item_id).strip()
        text = label
        if surface == "confirmation":
            text = f"Confirm: {label}"
        elif surface == "error":
            text = f"Error: {label}"
        mandatory = bool(item.mandatory) or kind in {
            "error",
            "confirmation",
            "consent",
            "action",
            "feedback",
        }
        visible = disposition != "omitted" or mandatory
        if surface in {"error", "confirmation"} and not visible:
            raise ValueError(f"Mandatory {surface} for {item.item_id} must remain visible")

        focusable = role in {"button", "link", "textbox", "menuitem"} and disposition not in {
            "omitted",
            "unsatisfiable",
        }
        actions: list[str] = []
        if kind == "action" or surface == "control":
            actions = ["activate"]
        if surface == "confirmation":
            actions = ["confirm", "dismiss"]

        # No executable attributes ever
        aria = {
            "role": role,
            "name": label,
            "description": "",
            "live": "assertive" if surface in {"error", "confirmation"} else "off",
            "atomic": surface in {"error", "confirmation"},
        }
        nodes.append(
            {
                "node_id": f"web:{item.item_id}",
                "surface": surface,
                "semantic_kind": kind,
                "disposition": disposition,
                "order": index,
                "aria": aria,
                "tag_name": {
                    "button": "button",
                    "textbox": "input",
                    "alert": "div",
                    "alertdialog": "div",
                    "status": "div",
                    "region": "section",
                }.get(role, "div"),
                "text": text,
                "actions": actions,
                "component_id": item.component_id,
                "source_item_id": item.item_id,
                "focus_index": index if focusable else None,
                "tab_index": 0 if focusable else None,
                "visible": visible,
                "accessible": True,
                "mandatory": mandatory,
                "notes": [f"disposition:{disposition}"],
            }
        )
        if kind == "text_input" and render_mode == "read_only":
            losses.append(
                WebLoss(
                    path=item.item_id,
                    reason="text_input_read_only_mode",
                    category="degraded",
                )
            )

    return {
        "interface": UIIR_WEB_PROJECTION_INTERFACE,
        "schema_version": UIIR_WEB_PROJECTION_SCHEMA_VERSION,
        "render_mode": render_mode,
        "nodes": nodes,
        "losses": [loss.to_dict() for loss in losses],
        "node_count": len(nodes),
        "mandatory_visible": all(
            n["visible"] for n in nodes if n.get("mandatory")
        ),
        "grants_execution_authority": False,
        "executable_markup": False,
        "notes": [
            "Python web projection is semantic/accessible model only.",
            "SwissKnife ui-ux-ir-web-renderer remains the browser DOM peer.",
            "No script/style/iframe tags are emitted.",
        ],
    }


__all__ = [
    "UIIR_WEB_PROJECTION_INTERFACE",
    "UIIR_WEB_PROJECTION_SCHEMA_VERSION",
    "WebLoss",
    "project_to_web",
]
