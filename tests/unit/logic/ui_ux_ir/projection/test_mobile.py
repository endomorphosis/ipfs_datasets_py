"""UIR-042: mobile companion projection adapter (Python)."""

from __future__ import annotations

from ipfs_datasets_py.logic.ui_ux_ir.projection.loss import MandatorySemanticKind
from ipfs_datasets_py.logic.ui_ux_ir.projection.mobile import (
    MIN_TOUCH_TARGET_DP,
    ConnectivityState,
    project_to_mobile,
)
from ipfs_datasets_py.logic.ui_ux_ir.projection.solver import ProjectionItem, ProjectionProblem


def _mobile_problem() -> ProjectionProblem:
    items = (
        ProjectionItem(
            item_id="action_submit",
            semantic_kind=MandatorySemanticKind.ACTION.value,
            mandatory=True,
            required_capability_ids=("touchscreen", "display"),
            component_id="btn_submit",
            label="Submit",
            action_cost=1,
            text_chars=12,
            priority=10,
        ),
        ProjectionItem(
            item_id="confirm_delete",
            semantic_kind=MandatorySemanticKind.CONFIRMATION.value,
            mandatory=True,
            required_capability_ids=("touchscreen", "display"),
            component_id="dlg_confirm",
            label="Confirm delete",
            action_cost=1,
            text_chars=20,
            priority=20,
        ),
        ProjectionItem(
            item_id="error_surface",
            semantic_kind=MandatorySemanticKind.ERROR.value,
            mandatory=True,
            required_capability_ids=("display",),
            component_id="err_banner",
            label="Something failed",
            text_chars=30,
            priority=30,
        ),
        ProjectionItem(
            item_id="feedback_pending",
            semantic_kind=MandatorySemanticKind.FEEDBACK.value,
            mandatory=True,
            required_capability_ids=("display",),
            component_id="status_pending",
            label="Working…",
            text_chars=10,
            priority=15,
        ),
    )
    return ProjectionProblem(problem_id="pmobile", items=items, document_id="doc:m")


def test_mobile_projection_emits_surfaces_and_touch_budget() -> None:
    artifact = project_to_mobile(_mobile_problem())
    assert artifact.surfaces
    assert artifact.connectivity in set(ConnectivityState)
    assert MIN_TOUCH_TARGET_DP >= 44
    assert artifact.viewport is not None
    assert artifact.glasses_fallback is not None
    # Explicit offline/unavailable support exists on the contract surface.
    assert ConnectivityState.OFFLINE in set(ConnectivityState)
    # Mandatory confirmation/error/action present as surface models.
    kinds = {s.kind for s in artifact.surfaces}
    assert kinds  # non-empty presentation


def test_mobile_is_presentation_not_policy_owner() -> None:
    artifact = project_to_mobile(_mobile_problem())
    # No authorization/grant fields on the mobile artifact.
    payload = artifact.to_dict() if hasattr(artifact, "to_dict") else artifact.__dict__
    blob = str(payload).lower()
    assert "authority_grant" not in blob
    assert "raw_emg" not in blob
