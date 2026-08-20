"""UIR-043: Meta-glasses / spatial projection adapter (Python)."""

from __future__ import annotations

import pytest

from ipfs_datasets_py.logic.ui_ux_ir.projection.glasses import (
    GlassesCapabilityPath,
    is_supported_arrow_enter_token,
    normalize_arrow_enter_intent,
    project_to_glasses,
    reject_fabricated_capability_claims,
)
from ipfs_datasets_py.logic.ui_ux_ir.projection.loss import MandatorySemanticKind
from ipfs_datasets_py.logic.ui_ux_ir.projection.solver import ProjectionItem, ProjectionProblem
from ipfs_datasets_py.logic.ui_ux_ir.schema import UIIRValidationError


def _glasses_problem() -> ProjectionProblem:
    items = (
        ProjectionItem(
            item_id="action_ok",
            semantic_kind=MandatorySemanticKind.ACTION.value,
            mandatory=True,
            required_capability_ids=("dpad_captouch", "spatial_display"),
            component_id="btn_ok",
            label="OK",
            action_cost=1,
            text_chars=2,
            priority=10,
        ),
        ProjectionItem(
            item_id="confirm_delete",
            semantic_kind=MandatorySemanticKind.CONFIRMATION.value,
            mandatory=True,
            required_capability_ids=("dpad_captouch", "audio"),
            component_id="dlg_confirm",
            label="Confirm",
            action_cost=1,
            text_chars=12,
            priority=20,
        ),
        ProjectionItem(
            item_id="privacy_indicator",
            semantic_kind=MandatorySemanticKind.CONSENT.value
            if hasattr(MandatorySemanticKind, "CONSENT")
            else MandatorySemanticKind.FEEDBACK.value,
            mandatory=True,
            required_capability_ids=("spatial_display",),
            component_id="privacy_led",
            label="Mic active",
            text_chars=10,
            priority=30,
        ),
    )
    return ProjectionProblem(problem_id="pglasses", items=items, document_id="doc:g")


def test_arrow_enter_normalization_for_neural_band_style_input() -> None:
    assert is_supported_arrow_enter_token("ArrowUp")
    assert is_supported_arrow_enter_token("Enter")
    assert normalize_arrow_enter_intent("ArrowUp") == "navigate_up"
    assert normalize_arrow_enter_intent("Enter") == "activate"
    assert not is_supported_arrow_enter_token("raw_emg_burst")


def test_reject_fabricated_raw_sensor_claims() -> None:
    with pytest.raises(UIIRValidationError, match="Fabricated|forbidden|raw_emg"):
        reject_fabricated_capability_claims({"raw_emg": True})
    # Benign capability maps are allowed through.
    reject_fabricated_capability_claims({"dpad_captouch": True, "spatial_display": True})


def test_web_app_and_dat_paths_are_distinct() -> None:
    problem = _glasses_problem()
    web = project_to_glasses(problem, capability_path=GlassesCapabilityPath.WEB_APP)
    dat = project_to_glasses(problem, capability_path=GlassesCapabilityPath.DAT)
    assert web.capability_path != dat.capability_path
    assert web.profile_id != dat.profile_id or web.capability_path is GlassesCapabilityPath.WEB_APP
    assert web.nodes or web.loss_report is not None
    # Input bindings stay Arrow/Enter-style for web apps.
    assert web.input_bindings
