"""Abstract modality capabilities, device profiles, and fallback contracts.

UIModalityContract@1 declares input/output capabilities without device SDK
types. Raw EMG, camera frames, biometric streams, and vendor SDK objects are
never part of the canonical model. Neural Band and captouch appear only as
normalized intent tokens (Arrow/Enter-style navigation and activation).

Essential requirements must declare alternatives; unsupported capabilities and
missing alternatives fail closed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Final, Iterable, Mapping, Sequence

from ..schema import (
    AdaptationPolicy,
    UIIRValidationError,
    UIModalityAlternative,
    UIModalityRequirement,
)

UI_MODALITY_CONTRACT_INTERFACE: Final = "UIModalityContract@1"
UI_MODALITY_CONTRACT_SCHEMA_VERSION: Final = "ui-modality-contract/v1"

_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")

# Keys that would pull raw sensor streams or vendor SDK state into the IR.
_FORBIDDEN_RAW_SENSOR_KEYS: Final = frozenset(
    {
        "camera_frame",
        "emg",
        "emg_raw",
        "gaze_stream",
        "microphone_pcm",
        "neural_band_raw",
        "raw_emg",
        "raw_sensor",
        "sdk_handle",
        "sdk_object",
        "vendor_sdk",
    }
)


class InputCapabilityKind(str, Enum):
    """Canonical abstract input capabilities (no device SDK types)."""

    POINTER_MOUSE = "pointer_mouse"
    KEYBOARD = "keyboard"
    SWITCH = "switch"
    TOUCHSCREEN = "touchscreen"
    PEN = "pen"
    SPEECH = "speech"
    HAND_GESTURE = "hand_gesture"
    GAZE = "gaze"
    HEAD_POSE = "head_pose"
    MOTION_ORIENTATION = "motion_orientation"
    DPAD_CAPTOUCH = "dpad_captouch"
    NEURAL_BAND_NORMALIZED = "neural_band_normalized"
    AGENT_PROPOSAL = "agent_proposal"
    AGENT_DELEGATED = "agent_delegated"
    COMPOSITE_MULTIMODAL = "composite_multimodal"


class OutputCapabilityKind(str, Enum):
    """Canonical abstract output capabilities (no device SDK types)."""

    DISPLAY = "display"
    SPATIAL_DISPLAY = "spatial_display"
    AUDIO = "audio"
    SPEECH_OUTPUT = "speech_output"
    HAPTIC = "haptic"
    NOTIFICATION = "notification"
    MOBILE_COMPANION = "mobile_companion"
    AGENT_STRUCTURED = "agent_structured"
    FALLBACK = "fallback"


class ModalityDirection(str, Enum):
    """Requirement direction for input versus output modality."""

    INPUT = "input"
    OUTPUT = "output"


class ConsentRequirement(str, Enum):
    """Whether a capability requires explicit consent before use."""

    NONE = "none"
    PURPOSE_BOUND = "purpose_bound"
    EXPLICIT = "explicit"


class ConfidenceRequirement(str, Enum):
    """Whether recognized intent must carry a confidence bound."""

    NONE = "none"
    CALIBRATED = "calibrated"
    THRESHOLD = "threshold"


# Closed catalogues used for fail-closed admission of capability identifiers.
CANONICAL_INPUT_CAPABILITIES: Final[frozenset[str]] = frozenset(
    kind.value for kind in InputCapabilityKind
)
CANONICAL_OUTPUT_CAPABILITIES: Final[frozenset[str]] = frozenset(
    kind.value for kind in OutputCapabilityKind
)
CANONICAL_CAPABILITIES: Final[frozenset[str]] = (
    CANONICAL_INPUT_CAPABILITIES | CANONICAL_OUTPUT_CAPABILITIES
)

# Capabilities that never claim continuous raw streams in the IR.
NORMALIZED_ONLY_INPUTS: Final[frozenset[str]] = frozenset(
    {
        InputCapabilityKind.NEURAL_BAND_NORMALIZED.value,
        InputCapabilityKind.DPAD_CAPTOUCH.value,
        InputCapabilityKind.GAZE.value,
        InputCapabilityKind.HEAD_POSE.value,
        InputCapabilityKind.HAND_GESTURE.value,
        InputCapabilityKind.MOTION_ORIENTATION.value,
    }
)


def _validate_identifier(name: str, value: str) -> None:
    if not isinstance(value, str) or not _IDENTIFIER_RE.fullmatch(value):
        raise UIIRValidationError(f"{name} is not a stable identifier")


def _validate_non_empty_string(name: str, value: Any) -> None:
    if not isinstance(value, str) or not value.strip():
        raise UIIRValidationError(f"{name} must be a non-empty string")


def _require_tuple(name: str, value: Any) -> None:
    if not isinstance(value, tuple):
        raise UIIRValidationError(f"{name} must be an immutable tuple")


def _require_unique(values: Iterable[str], label: str) -> None:
    seen: set[str] = set()
    for value in values:
        if value in seen:
            raise UIIRValidationError(f"Duplicate {label} id: {value}")
        seen.add(value)


def _validate_identifier_items(name: str, values: Iterable[Any]) -> None:
    for index, value in enumerate(values):
        _validate_identifier(f"{name}[{index}]", value)


def _reject_raw_sensor_payload(value: Any, label: str, *, _path: str = "") -> None:
    """Reject raw sensor / SDK payloads that must stay in trusted adapters."""

    if callable(value) or isinstance(value, type):
        raise UIIRValidationError(f"{label}{_path} contains an executable callback")
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise UIIRValidationError(f"{label}{_path} map keys must be strings")
            lowered = key.lower()
            if lowered in _FORBIDDEN_RAW_SENSOR_KEYS:
                raise UIIRValidationError(
                    f"{label}{_path}/{key} is a raw sensor or SDK field"
                )
            _reject_raw_sensor_payload(item, label, _path=f"{_path}/{key}")
        return
    if isinstance(value, (str, bytes, bytearray)) or value is None:
        return
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for index, item in enumerate(value):
            _reject_raw_sensor_payload(item, label, _path=f"{_path}[{index}]")


def require_supported_capability(
    capability_id: str,
    *,
    direction: ModalityDirection | None = None,
    label: str = "capability",
) -> str:
    """Admit a capability id against the closed catalogue or fail closed."""

    _validate_non_empty_string(label, capability_id)
    if capability_id not in CANONICAL_CAPABILITIES:
        raise UIIRValidationError(
            f"Unsupported {label}: {capability_id!r} is not a canonical "
            "ui-ux-ir modality capability"
        )
    if direction is ModalityDirection.INPUT and capability_id not in CANONICAL_INPUT_CAPABILITIES:
        raise UIIRValidationError(
            f"Unsupported input {label}: {capability_id!r} is not an input capability"
        )
    if direction is ModalityDirection.OUTPUT and capability_id not in CANONICAL_OUTPUT_CAPABILITIES:
        raise UIIRValidationError(
            f"Unsupported output {label}: {capability_id!r} is not an output capability"
        )
    return capability_id


@dataclass(frozen=True, slots=True)
class InputCapability:
    """One abstract input capability declaration (SDK-free)."""

    capability_id: str
    kind: InputCapabilityKind
    consent: ConsentRequirement = ConsentRequirement.NONE
    confidence: ConfidenceRequirement = ConfidenceRequirement.NONE
    normalized_intent_only: bool = False
    description: str = ""

    def validate(self) -> None:
        _validate_identifier("InputCapability.capability_id", self.capability_id)
        if not isinstance(self.kind, InputCapabilityKind):
            raise UIIRValidationError(
                "InputCapability.kind must be an InputCapabilityKind value"
            )
        if not isinstance(self.consent, ConsentRequirement):
            raise UIIRValidationError(
                "InputCapability.consent must be a ConsentRequirement value"
            )
        if not isinstance(self.confidence, ConfidenceRequirement):
            raise UIIRValidationError(
                "InputCapability.confidence must be a ConfidenceRequirement value"
            )
        if not isinstance(self.normalized_intent_only, bool):
            raise UIIRValidationError(
                "InputCapability.normalized_intent_only must be a boolean"
            )
        if not isinstance(self.description, str):
            raise UIIRValidationError("InputCapability.description must be a string")
        if self.kind.value in NORMALIZED_ONLY_INPUTS and not self.normalized_intent_only:
            raise UIIRValidationError(
                f"InputCapability {self.capability_id!r} kind {self.kind.value!r} "
                "requires normalized_intent_only=True (no raw sensor streams)"
            )
        if self.kind is InputCapabilityKind.NEURAL_BAND_NORMALIZED:
            if self.consent is ConsentRequirement.NONE:
                raise UIIRValidationError(
                    f"InputCapability {self.capability_id!r} neural_band_normalized "
                    "requires purpose-bound or explicit consent"
                )
        _reject_raw_sensor_payload(self.to_dict(), f"InputCapability {self.capability_id}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "capability_id": self.capability_id,
            "confidence": self.confidence.value,
            "consent": self.consent.value,
            "description": self.description,
            "kind": self.kind.value,
            "normalized_intent_only": self.normalized_intent_only,
        }


@dataclass(frozen=True, slots=True)
class OutputCapability:
    """One abstract output capability declaration (SDK-free)."""

    capability_id: str
    kind: OutputCapabilityKind
    is_fallback: bool = False
    description: str = ""

    def validate(self) -> None:
        _validate_identifier("OutputCapability.capability_id", self.capability_id)
        if not isinstance(self.kind, OutputCapabilityKind):
            raise UIIRValidationError(
                "OutputCapability.kind must be an OutputCapabilityKind value"
            )
        if not isinstance(self.is_fallback, bool):
            raise UIIRValidationError("OutputCapability.is_fallback must be a boolean")
        if not isinstance(self.description, str):
            raise UIIRValidationError("OutputCapability.description must be a string")
        if self.kind is OutputCapabilityKind.FALLBACK and not self.is_fallback:
            raise UIIRValidationError(
                f"OutputCapability {self.capability_id!r} kind fallback "
                "requires is_fallback=True"
            )
        _reject_raw_sensor_payload(self.to_dict(), f"OutputCapability {self.capability_id}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "capability_id": self.capability_id,
            "description": self.description,
            "is_fallback": self.is_fallback,
            "kind": self.kind.value,
        }


@dataclass(frozen=True, slots=True)
class DeviceProfile:
    """Device capability profile used for adaptive projection predicates."""

    profile_id: str
    input_capability_ids: tuple[str, ...]
    output_capability_ids: tuple[str, ...]
    adaptation_policy: AdaptationPolicy = AdaptationPolicy.ADAPT
    description: str = ""

    def validate(self) -> None:
        _validate_identifier("DeviceProfile.profile_id", self.profile_id)
        _require_tuple("DeviceProfile.input_capability_ids", self.input_capability_ids)
        _require_tuple("DeviceProfile.output_capability_ids", self.output_capability_ids)
        if not self.input_capability_ids and not self.output_capability_ids:
            raise UIIRValidationError(
                f"DeviceProfile {self.profile_id!r} must declare at least one capability"
            )
        for capability_id in self.input_capability_ids:
            require_supported_capability(
                capability_id,
                direction=ModalityDirection.INPUT,
                label="DeviceProfile.input_capability_ids member",
            )
        for capability_id in self.output_capability_ids:
            require_supported_capability(
                capability_id,
                direction=ModalityDirection.OUTPUT,
                label="DeviceProfile.output_capability_ids member",
            )
        _require_unique(
            self.input_capability_ids, "DeviceProfile.input_capability_ids member"
        )
        _require_unique(
            self.output_capability_ids, "DeviceProfile.output_capability_ids member"
        )
        if not isinstance(self.adaptation_policy, AdaptationPolicy):
            raise UIIRValidationError(
                "DeviceProfile.adaptation_policy must be an AdaptationPolicy value"
            )
        if not isinstance(self.description, str):
            raise UIIRValidationError("DeviceProfile.description must be a string")

    def to_dict(self) -> dict[str, Any]:
        return {
            "adaptation_policy": self.adaptation_policy.value,
            "description": self.description,
            "input_capability_ids": sorted(set(self.input_capability_ids)),
            "output_capability_ids": sorted(set(self.output_capability_ids)),
            "profile_id": self.profile_id,
        }


@dataclass(frozen=True, slots=True)
class ModalityRequirementSpec:
    """Closed modality requirement with explicit essential/fallback semantics."""

    requirement_id: str
    direction: ModalityDirection
    capability_ids: tuple[str, ...]
    essential: bool = True
    min_confidence: float | None = None
    consent: ConsentRequirement = ConsentRequirement.NONE
    source_ref_ids: tuple[str, ...] = ()

    def validate(self) -> None:
        _validate_identifier(
            "ModalityRequirementSpec.requirement_id", self.requirement_id
        )
        if not isinstance(self.direction, ModalityDirection):
            raise UIIRValidationError(
                "ModalityRequirementSpec.direction must be a ModalityDirection value"
            )
        if not self.capability_ids:
            raise UIIRValidationError(
                f"ModalityRequirementSpec {self.requirement_id!r}.capability_ids "
                "must not be empty"
            )
        _require_tuple(
            "ModalityRequirementSpec.capability_ids", self.capability_ids
        )
        for capability_id in self.capability_ids:
            require_supported_capability(
                capability_id,
                direction=self.direction,
                label=f"ModalityRequirementSpec {self.requirement_id!r}.capability_ids member",
            )
        _require_unique(
            self.capability_ids,
            "ModalityRequirementSpec.capability_ids member",
        )
        if not isinstance(self.essential, bool):
            raise UIIRValidationError(
                "ModalityRequirementSpec.essential must be a boolean"
            )
        if self.min_confidence is not None:
            if isinstance(self.min_confidence, bool) or not isinstance(
                self.min_confidence, (int, float)
            ):
                raise UIIRValidationError(
                    "ModalityRequirementSpec.min_confidence must be a number or None"
                )
            if not 0.0 <= float(self.min_confidence) <= 1.0:
                raise UIIRValidationError(
                    "ModalityRequirementSpec.min_confidence must be in [0.0, 1.0]"
                )
        if not isinstance(self.consent, ConsentRequirement):
            raise UIIRValidationError(
                "ModalityRequirementSpec.consent must be a ConsentRequirement value"
            )
        _require_tuple(
            "ModalityRequirementSpec.source_ref_ids", self.source_ref_ids
        )
        _validate_identifier_items(
            "ModalityRequirementSpec.source_ref_ids", self.source_ref_ids
        )
        _reject_raw_sensor_payload(
            self.to_dict(), f"ModalityRequirementSpec {self.requirement_id}"
        )

    def to_envelope_requirement(self) -> UIModalityRequirement:
        """Project into the envelope :class:`UIModalityRequirement` leaf."""

        return UIModalityRequirement(
            requirement_id=self.requirement_id,
            direction=self.direction.value,
            capability_ids=self.capability_ids,
            essential=self.essential,
            source_ref_ids=self.source_ref_ids,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "capability_ids": sorted(set(self.capability_ids)),
            "consent": self.consent.value,
            "direction": self.direction.value,
            "essential": self.essential,
            "min_confidence": self.min_confidence,
            "requirement_id": self.requirement_id,
            "source_ref_ids": sorted(set(self.source_ref_ids)),
        }


@dataclass(frozen=True, slots=True)
class UIModalityContract:
    """Closed modality contract: capabilities, profiles, requirements, alternatives.

    Interface identity: ``UIModalityContract@1``.
    """

    contract_id: str
    input_capabilities: tuple[InputCapability, ...]
    output_capabilities: tuple[OutputCapability, ...]
    requirements: tuple[ModalityRequirementSpec, ...]
    alternatives: tuple[UIModalityAlternative, ...] = ()
    device_profiles: tuple[DeviceProfile, ...] = ()
    schema_version: str = UI_MODALITY_CONTRACT_SCHEMA_VERSION

    def validate(self) -> None:
        if self.schema_version != UI_MODALITY_CONTRACT_SCHEMA_VERSION:
            raise UIIRValidationError(
                f"Unsupported modality contract schema_version: {self.schema_version!r}"
            )
        _validate_identifier("UIModalityContract.contract_id", self.contract_id)
        _require_tuple("UIModalityContract.input_capabilities", self.input_capabilities)
        _require_tuple(
            "UIModalityContract.output_capabilities", self.output_capabilities
        )
        _require_tuple("UIModalityContract.requirements", self.requirements)
        _require_tuple("UIModalityContract.alternatives", self.alternatives)
        _require_tuple("UIModalityContract.device_profiles", self.device_profiles)

        if not self.input_capabilities and not self.output_capabilities:
            raise UIIRValidationError(
                f"UIModalityContract {self.contract_id!r} must declare at least "
                "one input or output capability"
            )

        input_ids: list[str] = []
        for capability in self.input_capabilities:
            if not isinstance(capability, InputCapability):
                raise UIIRValidationError(
                    "UIModalityContract.input_capabilities members must be InputCapability"
                )
            capability.validate()
            input_ids.append(capability.capability_id)
        _require_unique(input_ids, "UIModalityContract.input_capabilities member")

        output_ids: list[str] = []
        for capability in self.output_capabilities:
            if not isinstance(capability, OutputCapability):
                raise UIIRValidationError(
                    "UIModalityContract.output_capabilities members must be OutputCapability"
                )
            capability.validate()
            output_ids.append(capability.capability_id)
        _require_unique(output_ids, "UIModalityContract.output_capabilities member")

        declared_capability_kinds = {
            capability.kind.value for capability in self.input_capabilities
        } | {capability.kind.value for capability in self.output_capabilities}

        requirement_ids: list[str] = []
        essential_requirement_ids: set[str] = set()
        for requirement in self.requirements:
            if not isinstance(requirement, ModalityRequirementSpec):
                raise UIIRValidationError(
                    "UIModalityContract.requirements members must be ModalityRequirementSpec"
                )
            requirement.validate()
            requirement_ids.append(requirement.requirement_id)
            for capability_id in requirement.capability_ids:
                if capability_id not in declared_capability_kinds:
                    raise UIIRValidationError(
                        f"UIModalityContract {self.contract_id!r} requirement "
                        f"{requirement.requirement_id!r} references capability "
                        f"{capability_id!r} not declared on the contract"
                    )
            if requirement.essential:
                essential_requirement_ids.add(requirement.requirement_id)
        _require_unique(
            requirement_ids, "UIModalityContract.requirements member"
        )
        requirement_id_set = set(requirement_ids)

        alternative_ids: list[str] = []
        covered_primaries: set[str] = set()
        for alternative in self.alternatives:
            if not isinstance(alternative, UIModalityAlternative):
                raise UIIRValidationError(
                    "UIModalityContract.alternatives members must be UIModalityAlternative"
                )
            alternative.validate()
            alternative_ids.append(alternative.alternative_id)
            if alternative.primary_requirement_id not in requirement_id_set:
                raise UIIRValidationError(
                    f"UIModalityAlternative {alternative.alternative_id!r} "
                    f"primary_requirement_id {alternative.primary_requirement_id!r} "
                    "is unknown"
                )
            if alternative.alternative_requirement_id not in requirement_id_set:
                raise UIIRValidationError(
                    f"UIModalityAlternative {alternative.alternative_id!r} "
                    f"alternative_requirement_id "
                    f"{alternative.alternative_requirement_id!r} is unknown"
                )
            covered_primaries.add(alternative.primary_requirement_id)
        _require_unique(
            alternative_ids, "UIModalityContract.alternatives member"
        )

        missing_alternatives = sorted(essential_requirement_ids - covered_primaries)
        if missing_alternatives:
            raise UIIRValidationError(
                f"UIModalityContract {self.contract_id!r} essential requirements "
                f"missing alternatives: {', '.join(missing_alternatives)}"
            )

        profile_ids: list[str] = []
        for profile in self.device_profiles:
            if not isinstance(profile, DeviceProfile):
                raise UIIRValidationError(
                    "UIModalityContract.device_profiles members must be DeviceProfile"
                )
            profile.validate()
            profile_ids.append(profile.profile_id)
            for capability_id in (
                profile.input_capability_ids + profile.output_capability_ids
            ):
                if capability_id not in declared_capability_kinds:
                    raise UIIRValidationError(
                        f"DeviceProfile {profile.profile_id!r} references capability "
                        f"{capability_id!r} not declared on the contract"
                    )
        _require_unique(profile_ids, "UIModalityContract.device_profiles member")
        _reject_raw_sensor_payload(
            self.to_dict(), f"UIModalityContract {self.contract_id}"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "alternatives": [
                item.to_dict()
                for item in sorted(
                    self.alternatives, key=lambda item: item.alternative_id
                )
            ],
            "contract_id": self.contract_id,
            "device_profiles": [
                item.to_dict()
                for item in sorted(
                    self.device_profiles, key=lambda item: item.profile_id
                )
            ],
            "input_capabilities": [
                item.to_dict()
                for item in sorted(
                    self.input_capabilities, key=lambda item: item.capability_id
                )
            ],
            "interface": UI_MODALITY_CONTRACT_INTERFACE,
            "output_capabilities": [
                item.to_dict()
                for item in sorted(
                    self.output_capabilities, key=lambda item: item.capability_id
                )
            ],
            "requirements": [
                item.to_dict()
                for item in sorted(
                    self.requirements, key=lambda item: item.requirement_id
                )
            ],
            "schema_version": self.schema_version,
        }


def default_input_capability_catalogue() -> tuple[InputCapability, ...]:
    """Return one validated catalogue entry per canonical input capability."""

    consent_for = {
        InputCapabilityKind.SPEECH: ConsentRequirement.PURPOSE_BOUND,
        InputCapabilityKind.GAZE: ConsentRequirement.EXPLICIT,
        InputCapabilityKind.HEAD_POSE: ConsentRequirement.PURPOSE_BOUND,
        InputCapabilityKind.HAND_GESTURE: ConsentRequirement.PURPOSE_BOUND,
        InputCapabilityKind.MOTION_ORIENTATION: ConsentRequirement.PURPOSE_BOUND,
        InputCapabilityKind.NEURAL_BAND_NORMALIZED: ConsentRequirement.PURPOSE_BOUND,
        InputCapabilityKind.DPAD_CAPTOUCH: ConsentRequirement.NONE,
        InputCapabilityKind.AGENT_PROPOSAL: ConsentRequirement.PURPOSE_BOUND,
        InputCapabilityKind.AGENT_DELEGATED: ConsentRequirement.EXPLICIT,
    }
    confidence_for = {
        InputCapabilityKind.SPEECH: ConfidenceRequirement.CALIBRATED,
        InputCapabilityKind.HAND_GESTURE: ConfidenceRequirement.THRESHOLD,
        InputCapabilityKind.GAZE: ConfidenceRequirement.CALIBRATED,
        InputCapabilityKind.HEAD_POSE: ConfidenceRequirement.THRESHOLD,
        InputCapabilityKind.NEURAL_BAND_NORMALIZED: ConfidenceRequirement.THRESHOLD,
        InputCapabilityKind.DPAD_CAPTOUCH: ConfidenceRequirement.NONE,
        InputCapabilityKind.AGENT_PROPOSAL: ConfidenceRequirement.NONE,
        InputCapabilityKind.AGENT_DELEGATED: ConfidenceRequirement.NONE,
    }
    items: list[InputCapability] = []
    for kind in InputCapabilityKind:
        normalized = kind.value in NORMALIZED_ONLY_INPUTS
        items.append(
            InputCapability(
                capability_id=kind.value,
                kind=kind,
                consent=consent_for.get(kind, ConsentRequirement.NONE),
                confidence=confidence_for.get(kind, ConfidenceRequirement.NONE),
                normalized_intent_only=normalized,
                description=f"Canonical abstract input capability {kind.value}",
            )
        )
    return tuple(items)


def default_output_capability_catalogue() -> tuple[OutputCapability, ...]:
    """Return one validated catalogue entry per canonical output capability."""

    items: list[OutputCapability] = []
    for kind in OutputCapabilityKind:
        items.append(
            OutputCapability(
                capability_id=kind.value,
                kind=kind,
                is_fallback=kind is OutputCapabilityKind.FALLBACK,
                description=f"Canonical abstract output capability {kind.value}",
            )
        )
    return tuple(items)


def validate_modality_contract(contract: UIModalityContract) -> UIModalityContract:
    """Validate and return a modality contract (fail closed)."""

    if not isinstance(contract, UIModalityContract):
        raise UIIRValidationError(
            "validate_modality_contract requires a UIModalityContract instance"
        )
    contract.validate()
    return contract


__all__ = [
    "CANONICAL_CAPABILITIES",
    "CANONICAL_INPUT_CAPABILITIES",
    "CANONICAL_OUTPUT_CAPABILITIES",
    "ConsentRequirement",
    "ConfidenceRequirement",
    "DeviceProfile",
    "InputCapability",
    "InputCapabilityKind",
    "ModalityDirection",
    "ModalityRequirementSpec",
    "NORMALIZED_ONLY_INPUTS",
    "OutputCapability",
    "OutputCapabilityKind",
    "UI_MODALITY_CONTRACT_INTERFACE",
    "UI_MODALITY_CONTRACT_SCHEMA_VERSION",
    "UIModalityContract",
    "default_input_capability_catalogue",
    "default_output_capability_catalogue",
    "require_supported_capability",
    "validate_modality_contract",
]
