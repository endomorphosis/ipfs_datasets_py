"""Focused target-projection tests for UI/UX IR."""

from __future__ import annotations

from ipfs_datasets_py.logic.ui_ux_ir import project_to_mobile, project_ui_document
from ipfs_datasets_py.logic.ui_ux_ir.projection.semantic_items import SemanticItem


def _items() -> list[SemanticItem]:
    return [
        SemanticItem(
            item_id="item:query",
            semantic_kind="text_input",
            label="Search query",
            mandatory=True,
        ),
        SemanticItem(
            item_id="item:delete",
            semantic_kind="action",
            label="Delete account",
            mandatory=True,
            risk_class="critical",
            confirmation_class="explicit",
        ),
    ]


def test_mobile_projection_preserves_text_and_requires_safe_confirmation() -> None:
    result = project_to_mobile(items=_items(), platform="android")

    by_source = {
        node.get("source_item_id"): node for node in result.get("nodes") or []
    }
    assert by_source["item:query"]["surface"] == "text_field"
    assert by_source["item:query"]["touch_target_min_pt"] == 44
    assert by_source["item:delete"]["surface"] == "confirmation_sheet"
    assert by_source["item:delete"]["actions"] == ["confirm", "cancel"]
    assert result["grants_execution_authority"] is False


def test_multi_target_solver_routes_glasses_text_fallback_to_mobile() -> None:
    result = project_ui_document(
        items=_items(), targets=("web", "mobile", "glasses")
    )

    assert result["passed"] is True
    assert result["targets"] == ["glasses", "mobile", "web"]
    glasses = result["projections"]["glasses"]
    mobile = result["projections"]["mobile"]
    assert any(
        loss.get("semantic_id") == "item:query"
        and loss.get("fallback_ref") == "fallback:mobile:item:query"
        for loss in glasses["losses"]
    )
    assert any(
        item.get("fallback_ref") == "fallback:mobile:item:query"
        for item in mobile["inbox"]
    )
    assert result["cross_target_losses"] == []
    assert result["grants_execution_authority"] is False


def test_multi_target_solver_rejects_unknown_target() -> None:
    result = project_ui_document(items=_items(), targets=("web", "watch"))

    assert result["passed"] is False
    assert result["errors"] == {"watch": "unsupported target: watch"}
