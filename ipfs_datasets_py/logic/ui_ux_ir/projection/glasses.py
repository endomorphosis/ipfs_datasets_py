"""Meta-glasses / spatial projection (UIIRGlassesProjection@1).

Respects capability budgets and never fabricates continuous cursor, free-form
touch, continuous text, or raw EMG. Mandatory overflow falls back to mobile.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from .semantic_items import SemanticItem, document_to_semantic_items


UIIR_GLASSES_PROJECTION_INTERFACE = "UIIRGlassesProjection@1"
UIIR_GLASSES_PROJECTION_SCHEMA_VERSION = "ui-glasses-projection/v1"

UNSUPPORTED_ASSUMPTIONS = (
    "continuous_cursor",
    "freeform_touch",
    "continuous_text_input",
    "raw_emg",
    "raw_neural_stream",
)

ARROW_ENTER_TOKENS = ("ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight", "Enter")

BUDGETS = {
    "web_app": {
        "action_count": 4,
        "text_chars": 240,
        "update_hz": 2,
        "field_of_view": 40,
        "attention": 20,
    },
    "dat": {
        "action_count": 6,
        "text_chars": 320,
        "update_hz": 5,
        "field_of_view": 50,
        "attention": 28,
    },
    "simulator": {
        "action_count": 12,
        "text_chars": 800,
        "update_hz": 10,
        "field_of_view": 100,
        "attention": 50,
    },
}


def project_to_glasses(
    document: Mapping[str, Any] | Any = None,
    *,
    items: Sequence[SemanticItem | Mapping[str, Any]] | None = None,
    capability_path: str = "web_app",
) -> dict[str, Any]:
    """Project semantic items onto a bounded glasses HUD presentation."""
    if capability_path not in BUDGETS:
        raise ValueError(f"unsupported capability_path: {capability_path}")
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
                label=str(item.get("label") or item.get("text") or ""),
                order=int(item.get("order") or 100),
                mandatory=bool(item.get("mandatory")),
                fallback_ref=str(item.get("fallback_ref") or ""),
                risk_class=str(item.get("risk_class") or "low"),
                confirmation_class=str(item.get("confirmation_class") or "none"),
            )
            for item in items
        ]
    if not semantic:
        raise ValueError("Glasses projection requires a non-empty items list")

    budgets = BUDGETS[capability_path]
    nodes: list[dict[str, Any]] = []
    losses: list[dict[str, Any]] = []
    action_used = text_used = fov_used = attention_used = 0
    has_fallback = has_degraded = has_unsat = False

    survival_kinds = {"confirmation", "consent", "error", "privacy", "feedback"}
    ordered = sorted(semantic, key=lambda i: (0 if (i.mandatory or i.semantic_kind in survival_kinds) else 1, i.order, i.item_id))

    for item in ordered:
        if not item.item_id or not item.semantic_kind:
            raise ValueError("Each glasses item requires item_id and semantic_kind")
        kind = item.semantic_kind.lower()
        label = item.label or item.item_id
        mandatory = bool(item.mandatory) or kind in survival_kinds
        action_cost = 1 if kind in {"action", "confirmation"} else 0
        text_chars = max(8, len(label))
        fov_share = 8 if mandatory else 4
        attention = 5 if mandatory else 1
        disposition = "preserved"
        surface = "hud_card"
        fallback_ref = item.fallback_ref

        if kind in {"text_input", "freeform_text"}:
            if mandatory:
                disposition = "fallback"
                fallback_ref = fallback_ref or f"fallback:mobile:{item.item_id}"
                has_fallback = True
                surface = "mobile_fallback"
                losses.append(
                    {
                        "loss_id": f"loss:fallback-text:{item.item_id}",
                        "semantic_id": item.item_id,
                        "category": "fallback",
                        "reason": "Continuous text input is not assumed on glasses",
                        "mandatory": True,
                        "fallback_ref": fallback_ref,
                    }
                )
            else:
                disposition = "omitted"
                surface = "unsatisfiable"
                losses.append(
                    {
                        "loss_id": f"loss:omit-text:{item.item_id}",
                        "semantic_id": item.item_id,
                        "category": "omitted",
                        "reason": "Optional free-form text omitted",
                        "mandatory": False,
                    }
                )
        else:
            would_exceed = (
                action_used + action_cost > budgets["action_count"]
                or text_used + text_chars > budgets["text_chars"]
                or fov_used + fov_share > budgets["field_of_view"]
                or attention_used + attention > budgets["attention"]
            )
            if would_exceed:
                if mandatory:
                    disposition = "fallback"
                    fallback_ref = fallback_ref or f"fallback:mobile:{item.item_id}"
                    has_fallback = True
                    surface = "mobile_fallback"
                    losses.append(
                        {
                            "loss_id": f"loss:fallback-budget:{item.item_id}",
                            "semantic_id": item.item_id,
                            "category": "fallback",
                            "reason": "Glasses budget exceeded; routing mandatory item to mobile",
                            "mandatory": True,
                            "fallback_ref": fallback_ref,
                        }
                    )
                else:
                    disposition = "omitted"
                    has_degraded = True
                    surface = "unsatisfiable"
                    losses.append(
                        {
                            "loss_id": f"loss:omit-budget:{item.item_id}",
                            "semantic_id": item.item_id,
                            "category": "omitted",
                            "reason": "Optional item omitted due to glasses budget",
                            "mandatory": False,
                        }
                    )
            else:
                if kind == "action":
                    surface = "action"
                elif kind in {"confirmation", "consent"}:
                    surface = "confirmation"
                elif kind in {"error", "denial"}:
                    surface = "status"
                elif kind == "feedback":
                    surface = "status"
                action_used += action_cost
                text_used += text_chars
                fov_used += fov_share
                attention_used += attention

        if disposition == "unsatisfiable":
            has_unsat = True

        nodes.append(
            {
                "node_id": f"glasses:{item.item_id}",
                "surface": surface,
                "semantic_kind": kind,
                "disposition": disposition,
                "label": label,
                "mandatory": mandatory,
                "fallback_ref": fallback_ref,
                "input_bindings": (
                    [{"token": "Enter", "intent": "activate"}]
                    if surface in {"action", "confirmation"}
                    else [{"token": t, "intent": "navigate"} for t in ARROW_ENTER_TOKENS[:4]]
                ),
                "source_item_id": item.item_id,
            }
        )

    status = "ok"
    if has_unsat and not nodes:
        status = "unsatisfiable"
    elif has_fallback:
        status = "fallback"
    elif has_degraded:
        status = "degraded"

    return {
        "interface": UIIR_GLASSES_PROJECTION_INTERFACE,
        "schema_version": UIIR_GLASSES_PROJECTION_SCHEMA_VERSION,
        "capability_path": capability_path,
        "status": status,
        "nodes": nodes,
        "losses": losses,
        "budgets": budgets,
        "budget_used": {
            "action_count": action_used,
            "text_chars": text_used,
            "field_of_view": fov_used,
            "attention": attention_used,
        },
        "unsupported_assumptions_rejected": list(UNSUPPORTED_ASSUMPTIONS),
        "grants_execution_authority": False,
        "notes": [
            "Never fabricates continuous cursor/touch/text/EMG capabilities.",
            "Mandatory overflow falls back to mobile companion.",
            "SwissKnife glasses adapter remains the device peer.",
        ],
    }


__all__ = [
    "ARROW_ENTER_TOKENS",
    "BUDGETS",
    "UIIR_GLASSES_PROJECTION_INTERFACE",
    "UIIR_GLASSES_PROJECTION_SCHEMA_VERSION",
    "UNSUPPORTED_ASSUMPTIONS",
    "project_to_glasses",
]
