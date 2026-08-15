"""UIR-013: behavior and experience semantics."""

from __future__ import annotations

import pytest

from ipfs_datasets_py.logic.ui_ux_ir.model.behavior import (
    BehaviorModel,
    BehaviorState,
    BehaviorTransition,
    TransitionJoinKind,
    validate_behavior_model,
)
from ipfs_datasets_py.logic.ui_ux_ir.model.experience import (
    AccessibilityRole,
    AccessibleNameBinding,
    ExperienceModel,
    LocalizationMessage,
    validate_experience_model,
)
from ipfs_datasets_py.logic.ui_ux_ir.schema import UIIRValidationError


def test_behavior_transitions_are_priority_deterministic() -> None:
    model = BehaviorModel(
        model_id="bm1",
        states=(
            BehaviorState(state_id="idle"),
            BehaviorState(state_id="busy"),
            BehaviorState(state_id="done", terminal=True),
        ),
        transitions=(
            BehaviorTransition(
                transition_id="t1",
                source_state_ids=("idle",),
                target_state_id="busy",
                event_id="submit",
                priority=10,
                retryable=True,
                timeout_ms=5000,
                rollback_target_state_id="idle",
            ),
            BehaviorTransition(
                transition_id="t2",
                source_state_ids=("busy",),
                target_state_id="done",
                event_id="complete",
                priority=1,
                undoable=True,
                join_kind=TransitionJoinKind.ALL,
            ),
        ),
        initial_state_ids=("idle",),
    )
    assert validate_behavior_model(model).model_id == "bm1"
    colliding = BehaviorModel(
        model_id="bm2",
        states=model.states,
        transitions=(
            model.transitions[0],
            BehaviorTransition(
                transition_id="t_collision",
                source_state_ids=("idle",),
                target_state_id="done",
                event_id="submit",
                priority=10,
            ),
        ),
        initial_state_ids=("idle",),
    )
    with pytest.raises(UIIRValidationError, match="priority"):
        validate_behavior_model(colliding)


def test_behavior_rejects_executable_effect_expressions() -> None:
    model = BehaviorModel(
        model_id="bm3",
        states=(BehaviorState(state_id="idle"), BehaviorState(state_id="done", terminal=True)),
        transitions=(
            BehaviorTransition(
                transition_id="t_bad",
                source_state_ids=("idle",),
                target_state_id="done",
                effect_ids=("handler(() => alert(1))",),
            ),
        ),
        initial_state_ids=("idle",),
    )
    with pytest.raises(UIIRValidationError, match="executable"):
        validate_behavior_model(model)


def test_experience_resolves_names_roles_and_locale_fallbacks() -> None:
    model = ExperienceModel(
        model_id="ex1",
        messages=(
            LocalizationMessage(
                message_id="loc:submit",
                default_text="Submit",
                locale_fallbacks=("en", "en-US"),
            ),
            LocalizationMessage(
                message_id="loc:submit-help",
                default_text="Submit the form",
            ),
        ),
        accessible_names=(
            AccessibleNameBinding(
                component_id="component:submit",
                name_message_id="loc:submit",
                role=AccessibilityRole.BUTTON,
                description_message_id="loc:submit-help",
                modality_alternative_ids=("screen_reader", "speech_output"),
            ),
        ),
        feedback_ids=("feedback:error",),
        recovery_path_ids=("recovery:retry",),
    )
    assert validate_experience_model(model).model_id == "ex1"
    with pytest.raises(UIIRValidationError):
        validate_experience_model(
            ExperienceModel(
                model_id="ex2",
                messages=(
                    LocalizationMessage(message_id="loc:x", default_text="${evil()}"),
                ),
                accessible_names=(
                    AccessibleNameBinding(
                        component_id="c",
                        name_message_id="loc:x",
                        role=AccessibilityRole.BUTTON,
                        modality_alternative_ids=("screen_reader",),
                    ),
                ),
            )
        )
