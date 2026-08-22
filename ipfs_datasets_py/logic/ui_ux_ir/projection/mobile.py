"""Mobile companion projection (UIIRMobileProjection@1).

Primary home for overflow from glasses (text input, high-risk confirmations,
budget fallbacks) and a first-class touch-friendly projection of UIIR.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from .semantic_items import SemanticItem, document_to_semantic_items


UIIR_MOBILE_PROJECTION_INTERFACE = "UIIRMobileProjection@1"
UIIR_MOBILE_PROJECTION_SCHEMA_VERSION = "ui-mobile-projection/v1"

# Closed mobile surface vocabulary
MOBILE_SURFACES = (
    "screen",
    "sheet",
    "list_row",
    "primary_button",
    "secondary_button",
    "text_field",
    "banner",
    "toast",
    "confirmation_sheet",
    "privacy_badge",
    "nav_bar",
)


def _surface_for(kind: str, *, confirmation: bool = False) -> str:
    k = kind.lower()
    if confirmation or k in {"confirmation", "consent"}:
        return "confirmation_sheet"
    if k == "action":
        return "primary_button"
    if k == "text_input":
        return "text_field"
    if k in {"error", "denial"}:
        return "banner"
    if k == "feedback":
        return "toast"
    if k == "privacy":
        return "privacy_badge"
    return "list_row"


def project_to_mobile(
    document: Mapping[str, Any] | Any = None,
    *,
    items: Sequence[SemanticItem | Mapping[str, Any]] | None = None,
    include_fallback_inbox: bool = True,
    fallback_refs: Sequence[str] | None = None,
    platform: str = "generic",  # generic | ios | android
) -> dict[str, Any]:
    """Project UIIR semantic items into a mobile companion surface model.

    Parameters
    ----------
    include_fallback_inbox:
        When true, materialize explicit fallback refs (from glasses/web) as
        inbox rows so mandatory overflow remains actionable on-device.
    platform:
        Soft hint for layout density only; never selects native SDKs.
    """
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
                component_id=str(item.get("component_id") or ""),
                order=int(item.get("order") or 100),
                mandatory=bool(item.get("mandatory")),
                disposition=str(item.get("disposition") or "preserved"),
                fallback_ref=str(item.get("fallback_ref") or ""),
                risk_class=str(item.get("risk_class") or "low"),
                confirmation_class=str(item.get("confirmation_class") or "none"),
                target_ref=str(item.get("target_ref") or ""),
            )
            for item in items
        ]

    nodes: list[dict[str, Any]] = []
    losses: list[dict[str, Any]] = []
    inbox: list[dict[str, Any]] = []

    # Nav chrome
    nodes.append(
        {
            "node_id": "mobile:nav:root",
            "surface": "nav_bar",
            "semantic_kind": "structure",
            "label": "Companion",
            "order": -10,
            "mandatory": True,
            "actions": ["back"],
            "platform_hint": platform,
        }
    )

    sorted_items = sorted(semantic, key=lambda i: (i.order, i.item_id))
    for index, item in enumerate(sorted_items):
        if not item.item_id:
            raise ValueError(f"items[{index}].item_id is required")
        kind = item.semantic_kind.lower()
        conf = (item.confirmation_class or "none") != "none" or kind in {
            "confirmation",
            "consent",
        }
        surface = _surface_for(kind, confirmation=conf)
        # High-risk always gets confirmation sheet on mobile
        if (item.risk_class or "low") in {"high", "critical"}:
            surface = "confirmation_sheet"
            conf = True

        actions: list[str] = []
        if surface == "primary_button":
            actions = ["tap", "long_press"]
        elif surface == "confirmation_sheet":
            actions = ["confirm", "cancel"]
        elif surface == "text_field":
            actions = ["focus", "input", "submit"]
        elif surface == "list_row":
            actions = ["tap"]

        # Mobile fully supports text input (unlike glasses)
        disposition = item.disposition or "preserved"
        if disposition in {"fallback", "omitted"} and kind == "text_input":
            disposition = "preserved"  # recover on mobile
            losses.append(
                {
                    "path": item.item_id,
                    "reason": "recovered_text_input_from_upstream_fallback",
                    "category": "recovery",
                }
            )

        nodes.append(
            {
                "node_id": f"mobile:{item.item_id}",
                "surface": surface,
                "semantic_kind": kind,
                "label": item.label or item.item_id,
                "text": item.text or item.label,
                "order": index,
                "mandatory": bool(item.mandatory) or conf,
                "disposition": disposition,
                "actions": actions,
                "component_id": item.component_id,
                "target_ref": item.target_ref,
                "risk_class": item.risk_class,
                "confirmation_class": item.confirmation_class,
                "haptic": "impact_medium" if conf else "selection",
                "safe_area": True,
                "touch_target_min_pt": 44,
                "platform_hint": platform,
                "source_item_id": item.item_id,
            }
        )

    # Materialize fallback inbox from external refs (glasses overflow)
    refs = list(fallback_refs or [])
    if include_fallback_inbox:
        for item in sorted_items:
            if item.fallback_ref and item.fallback_ref.startswith("fallback:mobile:"):
                refs.append(item.fallback_ref)
        for ref in sorted(set(refs)):
            leaf = ref.rsplit(":", 1)[-1]
            inbox.append(
                {
                    "inbox_id": f"inbox:{leaf}",
                    "fallback_ref": ref,
                    "surface": "sheet",
                    "label": f"Continue on phone: {leaf}",
                    "actions": ["open", "dismiss"],
                    "mandatory": True,
                }
            )
            # Ensure an actionable row exists even if source item omitted upstream
            if not any(n.get("source_item_id", "").endswith(leaf) for n in nodes):
                nodes.append(
                    {
                        "node_id": f"mobile:fallback:{leaf}",
                        "surface": "list_row",
                        "semantic_kind": "action",
                        "label": f"Resume {leaf}",
                        "order": 10_000,
                        "mandatory": True,
                        "disposition": "preserved",
                        "actions": ["tap"],
                        "fallback_ref": ref,
                        "source_item_id": leaf,
                        "from_fallback_inbox": True,
                    }
                )

    return {
        "interface": UIIR_MOBILE_PROJECTION_INTERFACE,
        "schema_version": UIIR_MOBILE_PROJECTION_SCHEMA_VERSION,
        "platform": platform,
        "nodes": nodes,
        "inbox": inbox,
        "losses": losses,
        "surfaces_used": sorted({n["surface"] for n in nodes}),
        "closed_surface_vocabulary": list(MOBILE_SURFACES),
        "supports_text_input": True,
        "supports_touch": True,
        "supports_haptics": True,
        "min_touch_target_pt": 44,
        "grants_execution_authority": False,
        "notes": [
            "Mobile is the overflow home for glasses text/budget fallbacks.",
            "High-risk actions always use confirmation sheets.",
            "No native SDK types are embedded; model is target-neutral.",
            "Invocation still requires control-surface / ORB mediation.",
        ],
    }


__all__ = [
    "MOBILE_SURFACES",
    "UIIR_MOBILE_PROJECTION_INTERFACE",
    "UIIR_MOBILE_PROJECTION_SCHEMA_VERSION",
    "project_to_mobile",
]
