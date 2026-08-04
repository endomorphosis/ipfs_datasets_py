"""UX accessibility, localization, and feedback experience (UIR-013)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Final

from ..schema import UIIRValidationError

UI_EXPERIENCE_MODEL_INTERFACE: Final = "UIExperienceModel@1"


class AccessibilityRole(str, Enum):
    BUTTON = "button"
    LINK = "link"
    TEXTBOX = "textbox"
    HEADING = "heading"
    DIALOG = "dialog"
    ALERT = "alert"
    NAVIGATION = "navigation"
    MAIN = "main"
    STATUS = "status"


@dataclass(frozen=True, slots=True)
class AccessibleNameBinding:
    component_id: str
    name_message_id: str
    role: AccessibilityRole
    description_message_id: str = ""
    modality_alternative_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class LocalizationMessage:
    message_id: str
    default_text: str
    locale_fallbacks: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ExperienceModel:
    model_id: str
    accessible_names: tuple[AccessibleNameBinding, ...]
    messages: tuple[LocalizationMessage, ...]
    feedback_ids: tuple[str, ...] = ()
    recovery_path_ids: tuple[str, ...] = ()
    schema_version: str = "ui-experience-model/v1"


def validate_experience_model(model: ExperienceModel) -> ExperienceModel:
    """Validate accessibility and localization bindings fail-closed."""

    if not model.model_id.strip():
        raise UIIRValidationError("ExperienceModel.model_id must not be empty")
    message_ids = {message.message_id for message in model.messages}
    for message in model.messages:
        if not message.message_id.strip():
            raise UIIRValidationError("LocalizationMessage.message_id must not be empty")
        if not message.default_text.strip():
            raise UIIRValidationError(
                f"LocalizationMessage {message.message_id!r} default_text must not be empty"
            )
        # Reject executable expressions in localization text.
        if any(token in message.default_text for token in ("${", "{{", "javascript:", "=>")):
            raise UIIRValidationError(
                f"LocalizationMessage {message.message_id!r} rejects executable expressions"
            )
    for binding in model.accessible_names:
        if binding.name_message_id not in message_ids:
            raise UIIRValidationError(
                f"AccessibleNameBinding for {binding.component_id!r} references unknown "
                f"message {binding.name_message_id!r}"
            )
        if (
            binding.description_message_id
            and binding.description_message_id not in message_ids
        ):
            raise UIIRValidationError(
                f"AccessibleNameBinding for {binding.component_id!r} references unknown "
                f"description message {binding.description_message_id!r}"
            )
        if not binding.modality_alternative_ids:
            # Essential accessible names require at least one modality alternative id
            # (screen reader, speech, haptic, etc.) for equivalence.
            raise UIIRValidationError(
                f"AccessibleNameBinding for {binding.component_id!r} requires modality alternatives"
            )
    return model


__all__ = [
    "AccessibilityRole",
    "AccessibleNameBinding",
    "ExperienceModel",
    "LocalizationMessage",
    "UI_EXPERIENCE_MODEL_INTERFACE",
    "validate_experience_model",
]
