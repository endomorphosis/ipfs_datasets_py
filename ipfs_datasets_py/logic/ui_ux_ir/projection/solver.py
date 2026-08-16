"""Multi-target projection solver (UIProjectionSolver@1)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from .glasses import project_to_glasses
from .mobile import project_to_mobile
from .semantic_items import SemanticItem, document_to_semantic_items
from .web import project_to_web

UI_PROJECTION_SOLVER_INTERFACE = "UIProjectionSolver@1"


def project_ui_document(
    document: Mapping[str, Any] | Any = None,
    *,
    items: Sequence[SemanticItem | Mapping[str, Any]] | None = None,
    targets: Sequence[str] = ("web", "mobile", "glasses"),
    glasses_capability_path: str = "web_app",
    mobile_platform: str = "generic",
) -> dict[str, Any]:
    """Project one UIIR document to one or more targets with loss correlation."""
    if items is None:
        if document is None:
            raise ValueError("document or items required")
        semantic = document_to_semantic_items(document)
    else:
        semantic = list(items)
    results: dict[str, Any] = {}
    errors: dict[str, str] = {}

    want = {t.lower() for t in targets}
    unknown = sorted(want - {"web", "mobile", "glasses"})
    for target in unknown:
        errors[target] = f"unsupported target: {target}"
    if "web" in want:
        try:
            results["web"] = project_to_web(items=semantic)
        except Exception as exc:  # noqa: BLE001
            errors["web"] = f"{type(exc).__name__}: {exc}"
    if "glasses" in want:
        try:
            results["glasses"] = project_to_glasses(
                items=semantic, capability_path=glasses_capability_path
            )
        except Exception as exc:  # noqa: BLE001
            errors["glasses"] = f"{type(exc).__name__}: {exc}"
    if "mobile" in want:
        fallback_refs: list[str] = []
        glasses = results.get("glasses") or {}
        for loss in glasses.get("losses") or []:
            ref = loss.get("fallback_ref") or ""
            if ref:
                fallback_refs.append(ref)
        for node in glasses.get("nodes") or []:
            ref = node.get("fallback_ref") or ""
            if ref:
                fallback_refs.append(ref)
        try:
            results["mobile"] = project_to_mobile(
                items=semantic,
                fallback_refs=fallback_refs,
                platform=mobile_platform,
            )
        except Exception as exc:  # noqa: BLE001
            errors["mobile"] = f"{type(exc).__name__}: {exc}"

    # Cross-target: mandatory glasses fallbacks must appear on mobile
    cross_losses: list[str] = []
    glasses = results.get("glasses") or {}
    mobile = results.get("mobile") or {}
    if glasses and mobile:
        mobile_ids = {
            n.get("source_item_id") or n.get("node_id")
            for n in mobile.get("nodes") or []
        }
        for loss in glasses.get("losses") or []:
            if loss.get("mandatory") and loss.get("category") == "fallback":
                leaf = str(loss.get("fallback_ref") or "").rsplit(":", 1)[-1]
                semantic_id = str(loss.get("semantic_id") or "")
                if leaf not in mobile_ids and semantic_id not in {
                    str(x) for x in mobile_ids
                }:
                    # inbox materialization uses leaf / semantic id
                    inbox_ok = any(
                        leaf in str(i.get("fallback_ref") or "")
                        for i in mobile.get("inbox") or []
                    )
                    if not inbox_ok:
                        cross_losses.append(
                            f"mandatory_fallback_missing_on_mobile:{semantic_id}"
                        )

    return {
        "interface": UI_PROJECTION_SOLVER_INTERFACE,
        "semantic_item_count": len(semantic),
        "targets": sorted(want),
        "projections": results,
        "errors": errors,
        "cross_target_losses": cross_losses,
        "passed": not errors and not cross_losses,
        "grants_execution_authority": False,
        "notes": [
            "Solver coordinates web/mobile/glasses with explicit loss routing.",
            "Mobile absorbs glasses mandatory fallbacks.",
            "No target grants execution authority.",
        ],
    }


__all__ = ["UI_PROJECTION_SOLVER_INTERFACE", "project_ui_document"]
