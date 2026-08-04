"""Device capability profiles and negotiation for UI projection (UIDeviceProfile@1).

Profiles describe abstract capabilities and resource budgets, never brand or
vendor SDK objects. Negotiation is fail-closed: unsupported required
capabilities produce an explicit result rather than silent coercion.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Final, Iterable, Mapping, Sequence

from ..model.modality import (
    CANONICAL_CAPABILITIES,
    CANONICAL_INPUT_CAPABILITIES,
    CANONICAL_OUTPUT_CAPABILITIES,
    require_supported_capability,
)
from ..schema import AdaptationPolicy, UIIRValidationError

UI_DEVICE_PROFILE_INTERFACE: Final = "UIDeviceProfile@1"
UI_DEVICE_PROFILE_SCHEMA_VERSION: Final = "ui-device-profile/v1"
UI_CAPABILITY_NEGOTIATION_INTERFACE: Final = "UICapabilityNegotiation@1"

_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")

# Default absolute solver bounds (time/step/memory). Callers may tighten.
DEFAULT_MAX_SOLVE_MS: Final = 100
DEFAULT_MAX_SOLVE_STEPS: Final = 10_000
DEFAULT_MAX_MEMORY_NODES: Final = 1_000


class ProfileFamily(str, Enum):
    """Capability-based profile families (not device brands)."""

    DESKTOP = "desktop"
    MOBILE = "mobile"
    GLASSES = "glasses"
    VOICE = "voice"
    HEADLESS = "headless"
    CUSTOM = "custom"


class BudgetKind(str, Enum):
    """Closed set of projection resource/attention budgets."""

    ACTION_COUNT = "action_count"
    TEXT_DENSITY = "text_density"
    UPDATE_RATE = "update_rate"
    LATENCY = "latency"
    ATTENTION = "attention"
    FIELD_OF_VIEW = "field_of_view"
    SAFE_AREA = "safe_area"
    MEMORY = "memory"
    BANDWIDTH = "bandwidth"


# Budget kinds the acceptance criteria call out explicitly.
REQUIRED_BUDGET_KINDS: Final[frozenset[str]] = frozenset(
    {
        BudgetKind.ACTION_COUNT.value,
        BudgetKind.TEXT_DENSITY.value,
        BudgetKind.UPDATE_RATE.value,
        BudgetKind.LATENCY.value,
        BudgetKind.ATTENTION.value,
        BudgetKind.FIELD_OF_VIEW.value,
        BudgetKind.SAFE_AREA.value,
    }
)


class NegotiationStatus(str, Enum):
    """Outcome of capability negotiation."""

    SATISFIED = "satisfied"
    DEGRADED = "degraded"
    FALLBACK = "fallback"
    UNSATISFIABLE = "unsatisfiable"


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
            raise UIIRValidationError(f"Duplicate {label}: {value}")
        seen.add(value)


@dataclass(frozen=True, slots=True)
class ProfileBudget:
    """One bounded resource/attention budget on a device profile."""

    kind: BudgetKind
    limit: int
    unit: str = "count"
    soft_limit: int | None = None

    def validate(self) -> None:
        if not isinstance(self.kind, BudgetKind):
            raise UIIRValidationError("ProfileBudget.kind must be a BudgetKind")
        if not isinstance(self.limit, int) or isinstance(self.limit, bool) or self.limit < 0:
            raise UIIRValidationError(
                "ProfileBudget.limit must be a non-negative integer"
            )
        _validate_non_empty_string("ProfileBudget.unit", self.unit)
        if self.soft_limit is not None:
            if (
                not isinstance(self.soft_limit, int)
                or isinstance(self.soft_limit, bool)
                or self.soft_limit < 0
            ):
                raise UIIRValidationError(
                    "ProfileBudget.soft_limit must be a non-negative integer or None"
                )
            if self.soft_limit > self.limit:
                raise UIIRValidationError(
                    "ProfileBudget.soft_limit must not exceed hard limit"
                )

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "limit": self.limit,
            "soft_limit": self.soft_limit,
            "unit": self.unit,
        }


@dataclass(frozen=True, slots=True)
class UIDeviceProfile:
    """Capability-based device profile used for projection negotiation.

    Interface identity: ``UIDeviceProfile@1``.
    Profiles describe capabilities and budgets rather than brands.
    """

    profile_id: str
    family: ProfileFamily
    input_capability_ids: tuple[str, ...]
    output_capability_ids: tuple[str, ...]
    budgets: tuple[ProfileBudget, ...] = ()
    adaptation_policy: AdaptationPolicy = AdaptationPolicy.ADAPT
    max_solve_ms: int = DEFAULT_MAX_SOLVE_MS
    max_solve_steps: int = DEFAULT_MAX_SOLVE_STEPS
    max_memory_nodes: int = DEFAULT_MAX_MEMORY_NODES
    description: str = ""
    schema_version: str = UI_DEVICE_PROFILE_SCHEMA_VERSION

    def validate(self) -> "UIDeviceProfile":
        if self.schema_version != UI_DEVICE_PROFILE_SCHEMA_VERSION:
            raise UIIRValidationError(
                f"Unsupported UIDeviceProfile schema_version: {self.schema_version!r}"
            )
        _validate_identifier("UIDeviceProfile.profile_id", self.profile_id)
        if not isinstance(self.family, ProfileFamily):
            raise UIIRValidationError(
                "UIDeviceProfile.family must be a ProfileFamily value"
            )
        _require_tuple(
            "UIDeviceProfile.input_capability_ids", self.input_capability_ids
        )
        _require_tuple(
            "UIDeviceProfile.output_capability_ids", self.output_capability_ids
        )
        if not self.input_capability_ids and not self.output_capability_ids:
            raise UIIRValidationError(
                f"UIDeviceProfile {self.profile_id!r} must declare at least one capability"
            )
        for capability_id in self.input_capability_ids:
            require_supported_capability(capability_id)
            if capability_id not in CANONICAL_INPUT_CAPABILITIES:
                raise UIIRValidationError(
                    f"UIDeviceProfile {self.profile_id!r} input capability "
                    f"{capability_id!r} is not an input capability"
                )
        for capability_id in self.output_capability_ids:
            require_supported_capability(capability_id)
            if capability_id not in CANONICAL_OUTPUT_CAPABILITIES:
                raise UIIRValidationError(
                    f"UIDeviceProfile {self.profile_id!r} output capability "
                    f"{capability_id!r} is not an output capability"
                )
        _require_unique(
            self.input_capability_ids, "UIDeviceProfile.input_capability_ids member"
        )
        _require_unique(
            self.output_capability_ids, "UIDeviceProfile.output_capability_ids member"
        )
        _require_tuple("UIDeviceProfile.budgets", self.budgets)
        seen_kinds: set[str] = set()
        for budget in self.budgets:
            if not isinstance(budget, ProfileBudget):
                raise UIIRValidationError(
                    "UIDeviceProfile.budgets members must be ProfileBudget"
                )
            budget.validate()
            if budget.kind.value in seen_kinds:
                raise UIIRValidationError(
                    f"Duplicate budget kind on profile {self.profile_id!r}: "
                    f"{budget.kind.value}"
                )
            seen_kinds.add(budget.kind.value)
        if not isinstance(self.adaptation_policy, AdaptationPolicy):
            raise UIIRValidationError(
                "UIDeviceProfile.adaptation_policy must be an AdaptationPolicy"
            )
        for name, value in (
            ("max_solve_ms", self.max_solve_ms),
            ("max_solve_steps", self.max_solve_steps),
            ("max_memory_nodes", self.max_memory_nodes),
        ):
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise UIIRValidationError(
                    f"UIDeviceProfile.{name} must be a positive integer"
                )
        if not isinstance(self.description, str):
            raise UIIRValidationError("UIDeviceProfile.description must be a string")
        return self

    @property
    def available_capability_ids(self) -> frozenset[str]:
        return frozenset(self.input_capability_ids) | frozenset(
            self.output_capability_ids
        )

    def budget_for(self, kind: BudgetKind | str) -> ProfileBudget | None:
        key = kind.value if isinstance(kind, BudgetKind) else str(kind)
        for budget in self.budgets:
            if budget.kind.value == key:
                return budget
        return None

    def budget_limit(self, kind: BudgetKind | str, default: int | None = None) -> int | None:
        budget = self.budget_for(kind)
        if budget is None:
            return default
        return budget.limit

    def to_dict(self) -> dict[str, Any]:
        return {
            "adaptation_policy": self.adaptation_policy.value,
            "budgets": [
                item.to_dict()
                for item in sorted(self.budgets, key=lambda b: b.kind.value)
            ],
            "description": self.description,
            "family": self.family.value,
            "input_capability_ids": sorted(set(self.input_capability_ids)),
            "interface": UI_DEVICE_PROFILE_INTERFACE,
            "max_memory_nodes": self.max_memory_nodes,
            "max_solve_ms": self.max_solve_ms,
            "max_solve_steps": self.max_solve_steps,
            "output_capability_ids": sorted(set(self.output_capability_ids)),
            "profile_id": self.profile_id,
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True, slots=True)
class CapabilityRequirement:
    """One capability requirement presented to the negotiator."""

    requirement_id: str
    capability_ids: tuple[str, ...]
    essential: bool = True
    direction: str = "output"
    alternative_capability_ids: tuple[str, ...] = ()
    fallback_capability_ids: tuple[str, ...] = ()

    def validate(self) -> None:
        _validate_identifier(
            "CapabilityRequirement.requirement_id", self.requirement_id
        )
        _require_tuple(
            "CapabilityRequirement.capability_ids", self.capability_ids
        )
        if not self.capability_ids:
            raise UIIRValidationError(
                f"CapabilityRequirement {self.requirement_id!r}.capability_ids "
                "must not be empty"
            )
        for capability_id in self.capability_ids:
            if capability_id not in CANONICAL_CAPABILITIES:
                raise UIIRValidationError(
                    f"CapabilityRequirement {self.requirement_id!r} references "
                    f"unknown capability {capability_id!r}"
                )
        if self.direction not in {"input", "output", "either"}:
            raise UIIRValidationError(
                "CapabilityRequirement.direction must be input, output, or either"
            )
        if not isinstance(self.essential, bool):
            raise UIIRValidationError(
                "CapabilityRequirement.essential must be a boolean"
            )
        for field_name in ("alternative_capability_ids", "fallback_capability_ids"):
            values = getattr(self, field_name)
            _require_tuple(f"CapabilityRequirement.{field_name}", values)
            for capability_id in values:
                if capability_id not in CANONICAL_CAPABILITIES:
                    raise UIIRValidationError(
                        f"CapabilityRequirement {self.requirement_id!r} "
                        f"{field_name} references unknown capability "
                        f"{capability_id!r}"
                    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "alternative_capability_ids": sorted(set(self.alternative_capability_ids)),
            "capability_ids": sorted(set(self.capability_ids)),
            "direction": self.direction,
            "essential": self.essential,
            "fallback_capability_ids": sorted(set(self.fallback_capability_ids)),
            "requirement_id": self.requirement_id,
        }


@dataclass(frozen=True, slots=True)
class CapabilityNegotiationResult:
    """Explicit result of negotiating requirements against a device profile."""

    profile_id: str
    status: NegotiationStatus
    satisfied_requirement_ids: tuple[str, ...]
    degraded_requirement_ids: tuple[str, ...]
    fallback_requirement_ids: tuple[str, ...]
    unsatisfiable_requirement_ids: tuple[str, ...]
    available_capability_ids: tuple[str, ...]
    used_capability_ids: tuple[str, ...]
    notes: tuple[str, ...] = ()
    interface: str = UI_CAPABILITY_NEGOTIATION_INTERFACE

    def to_dict(self) -> dict[str, Any]:
        return {
            "available_capability_ids": list(self.available_capability_ids),
            "degraded_requirement_ids": list(self.degraded_requirement_ids),
            "fallback_requirement_ids": list(self.fallback_requirement_ids),
            "interface": self.interface,
            "notes": list(self.notes),
            "profile_id": self.profile_id,
            "satisfied_requirement_ids": list(self.satisfied_requirement_ids),
            "status": self.status.value,
            "unsatisfiable_requirement_ids": list(self.unsatisfiable_requirement_ids),
            "used_capability_ids": list(self.used_capability_ids),
        }


def validate_device_profile(profile: UIDeviceProfile) -> UIDeviceProfile:
    """Validate and return a device profile (fail closed)."""

    if not isinstance(profile, UIDeviceProfile):
        raise UIIRValidationError("expected UIDeviceProfile")
    return profile.validate()


def negotiate_capabilities(
    profile: UIDeviceProfile,
    requirements: Sequence[CapabilityRequirement],
) -> CapabilityNegotiationResult:
    """Negotiate declared requirements against a validated device profile.

    Essential requirements without a primary, alternative, or fallback match
    are reported as unsatisfiable. Non-essential missing requirements degrade.
    Never silently drops an essential requirement.
    """

    profile = validate_device_profile(profile)
    if not isinstance(requirements, (list, tuple)):
        raise UIIRValidationError("requirements must be a sequence")

    available = set(profile.available_capability_ids)
    satisfied: list[str] = []
    degraded: list[str] = []
    fallback: list[str] = []
    unsatisfiable: list[str] = []
    used: set[str] = set()
    notes: list[str] = []
    seen_ids: set[str] = set()

    ordered = sorted(requirements, key=lambda item: item.requirement_id)
    for requirement in ordered:
        if not isinstance(requirement, CapabilityRequirement):
            raise UIIRValidationError(
                "requirements members must be CapabilityRequirement"
            )
        requirement.validate()
        if requirement.requirement_id in seen_ids:
            raise UIIRValidationError(
                f"Duplicate capability requirement id: {requirement.requirement_id}"
            )
        seen_ids.add(requirement.requirement_id)

        primary_hits = [c for c in requirement.capability_ids if c in available]
        if primary_hits:
            satisfied.append(requirement.requirement_id)
            used.update(primary_hits)
            continue

        alt_hits = [
            c for c in requirement.alternative_capability_ids if c in available
        ]
        if alt_hits:
            degraded.append(requirement.requirement_id)
            used.update(alt_hits)
            notes.append(
                f"{requirement.requirement_id}: primary unavailable; "
                f"using alternative {','.join(sorted(alt_hits))}"
            )
            continue

        fallback_hits = [
            c for c in requirement.fallback_capability_ids if c in available
        ]
        if fallback_hits:
            fallback.append(requirement.requirement_id)
            used.update(fallback_hits)
            notes.append(
                f"{requirement.requirement_id}: primary unavailable; "
                f"using fallback {','.join(sorted(fallback_hits))}"
            )
            continue

        if requirement.essential:
            unsatisfiable.append(requirement.requirement_id)
            notes.append(
                f"{requirement.requirement_id}: essential capabilities "
                f"{','.join(requirement.capability_ids)} unavailable with no "
                "alternative or fallback"
            )
        else:
            degraded.append(requirement.requirement_id)
            notes.append(
                f"{requirement.requirement_id}: non-essential capabilities "
                "unavailable; degraded"
            )

    if unsatisfiable:
        status = NegotiationStatus.UNSATISFIABLE
    elif fallback:
        status = NegotiationStatus.FALLBACK
    elif degraded:
        status = NegotiationStatus.DEGRADED
    else:
        status = NegotiationStatus.SATISFIED

    return CapabilityNegotiationResult(
        profile_id=profile.profile_id,
        status=status,
        satisfied_requirement_ids=tuple(sorted(satisfied)),
        degraded_requirement_ids=tuple(sorted(degraded)),
        fallback_requirement_ids=tuple(sorted(fallback)),
        unsatisfiable_requirement_ids=tuple(sorted(unsatisfiable)),
        available_capability_ids=tuple(sorted(available)),
        used_capability_ids=tuple(sorted(used)),
        notes=tuple(notes),
    )


def _budget(
    kind: BudgetKind,
    limit: int,
    *,
    unit: str = "count",
    soft_limit: int | None = None,
) -> ProfileBudget:
    return ProfileBudget(kind=kind, limit=limit, unit=unit, soft_limit=soft_limit)


def desktop_profile(
    profile_id: str = "profile:desktop:default",
) -> UIDeviceProfile:
    """Reference desktop capability profile with generous budgets."""

    return validate_device_profile(
        UIDeviceProfile(
            profile_id=profile_id,
            family=ProfileFamily.DESKTOP,
            input_capability_ids=(
                "pointer_mouse",
                "keyboard",
                "touchscreen",
            ),
            output_capability_ids=(
                "display",
                "audio",
                "notification",
                "agent_structured",
                "fallback",
            ),
            budgets=(
                _budget(BudgetKind.ACTION_COUNT, 32),
                _budget(BudgetKind.TEXT_DENSITY, 4000, unit="chars"),
                _budget(BudgetKind.UPDATE_RATE, 60, unit="hz"),
                _budget(BudgetKind.LATENCY, 100, unit="ms"),
                _budget(BudgetKind.ATTENTION, 100, unit="points"),
                _budget(BudgetKind.FIELD_OF_VIEW, 100, unit="percent"),
                _budget(BudgetKind.SAFE_AREA, 100, unit="percent"),
                _budget(BudgetKind.MEMORY, 1000, unit="nodes"),
            ),
            adaptation_policy=AdaptationPolicy.ADAPT,
            description="Capability-based desktop/web profile",
        )
    )


def mobile_profile(
    profile_id: str = "profile:mobile:default",
) -> UIDeviceProfile:
    """Reference mobile companion capability profile."""

    return validate_device_profile(
        UIDeviceProfile(
            profile_id=profile_id,
            family=ProfileFamily.MOBILE,
            input_capability_ids=(
                "touchscreen",
                "keyboard",
                "speech",
                "motion_orientation",
            ),
            output_capability_ids=(
                "display",
                "audio",
                "haptic",
                "notification",
                "mobile_companion",
                "fallback",
            ),
            budgets=(
                _budget(BudgetKind.ACTION_COUNT, 12),
                _budget(BudgetKind.TEXT_DENSITY, 1200, unit="chars"),
                _budget(BudgetKind.UPDATE_RATE, 30, unit="hz"),
                _budget(BudgetKind.LATENCY, 150, unit="ms"),
                _budget(BudgetKind.ATTENTION, 60, unit="points"),
                _budget(BudgetKind.FIELD_OF_VIEW, 80, unit="percent"),
                _budget(BudgetKind.SAFE_AREA, 90, unit="percent"),
                _budget(BudgetKind.MEMORY, 400, unit="nodes"),
            ),
            adaptation_policy=AdaptationPolicy.ADAPT,
            description="Capability-based mobile companion profile",
        )
    )


def glasses_profile(
    profile_id: str = "profile:glasses:default",
) -> UIDeviceProfile:
    """Reference spatial/glasses profile with tight FOV and action budgets."""

    return validate_device_profile(
        UIDeviceProfile(
            profile_id=profile_id,
            family=ProfileFamily.GLASSES,
            input_capability_ids=(
                "dpad_captouch",
                "neural_band_normalized",
                "gaze",
                "head_pose",
                "speech",
                "hand_gesture",
            ),
            output_capability_ids=(
                "spatial_display",
                "audio",
                "speech_output",
                "haptic",
                "mobile_companion",
                "fallback",
            ),
            budgets=(
                _budget(BudgetKind.ACTION_COUNT, 4, soft_limit=3),
                _budget(BudgetKind.TEXT_DENSITY, 180, unit="chars"),
                _budget(BudgetKind.UPDATE_RATE, 10, unit="hz"),
                _budget(BudgetKind.LATENCY, 80, unit="ms"),
                _budget(BudgetKind.ATTENTION, 25, unit="points"),
                _budget(BudgetKind.FIELD_OF_VIEW, 30, unit="percent"),
                _budget(BudgetKind.SAFE_AREA, 70, unit="percent"),
                _budget(BudgetKind.MEMORY, 80, unit="nodes"),
            ),
            adaptation_policy=AdaptationPolicy.FALLBACK,
            max_solve_ms=80,
            max_solve_steps=5_000,
            max_memory_nodes=80,
            description=(
                "Capability-based glasses/spatial profile with tight action, "
                "text, FOV, latency, and attention budgets"
            ),
        )
    )


def voice_profile(
    profile_id: str = "profile:voice:default",
) -> UIDeviceProfile:
    """Reference voice/audio profile without visual display."""

    return validate_device_profile(
        UIDeviceProfile(
            profile_id=profile_id,
            family=ProfileFamily.VOICE,
            input_capability_ids=("speech", "keyboard"),
            output_capability_ids=(
                "audio",
                "speech_output",
                "notification",
                "agent_structured",
                "fallback",
            ),
            budgets=(
                _budget(BudgetKind.ACTION_COUNT, 6),
                _budget(BudgetKind.TEXT_DENSITY, 600, unit="chars"),
                _budget(BudgetKind.UPDATE_RATE, 5, unit="hz"),
                _budget(BudgetKind.LATENCY, 200, unit="ms"),
                _budget(BudgetKind.ATTENTION, 40, unit="points"),
                _budget(BudgetKind.FIELD_OF_VIEW, 0, unit="percent"),
                _budget(BudgetKind.SAFE_AREA, 100, unit="percent"),
                _budget(BudgetKind.MEMORY, 200, unit="nodes"),
            ),
            adaptation_policy=AdaptationPolicy.FALLBACK,
            description="Capability-based voice/audio profile",
        )
    )


def headless_profile(
    profile_id: str = "profile:headless:default",
) -> UIDeviceProfile:
    """Reference agent-readable structured output profile."""

    return validate_device_profile(
        UIDeviceProfile(
            profile_id=profile_id,
            family=ProfileFamily.HEADLESS,
            input_capability_ids=("agent_proposal", "agent_delegated", "keyboard"),
            output_capability_ids=(
                "agent_structured",
                "notification",
                "fallback",
            ),
            budgets=(
                _budget(BudgetKind.ACTION_COUNT, 20),
                _budget(BudgetKind.TEXT_DENSITY, 8000, unit="chars"),
                _budget(BudgetKind.UPDATE_RATE, 100, unit="hz"),
                _budget(BudgetKind.LATENCY, 50, unit="ms"),
                _budget(BudgetKind.ATTENTION, 100, unit="points"),
                _budget(BudgetKind.FIELD_OF_VIEW, 0, unit="percent"),
                _budget(BudgetKind.SAFE_AREA, 100, unit="percent"),
                _budget(BudgetKind.MEMORY, 1000, unit="nodes"),
            ),
            adaptation_policy=AdaptationPolicy.ADAPT,
            description="Capability-based headless/agent-structured profile",
        )
    )


def default_profile_catalogue() -> tuple[UIDeviceProfile, ...]:
    """Return the closed reference catalogue of capability profiles."""

    return (
        desktop_profile(),
        mobile_profile(),
        glasses_profile(),
        voice_profile(),
        headless_profile(),
    )


def profile_from_mapping(payload: Mapping[str, Any]) -> UIDeviceProfile:
    """Decode a mapping into a validated UIDeviceProfile."""

    if not isinstance(payload, Mapping):
        raise UIIRValidationError("device profile payload must be a mapping")
    try:
        family = ProfileFamily(str(payload.get("family") or "custom"))
    except ValueError as exc:
        raise UIIRValidationError(
            f"Unknown profile family: {payload.get('family')!r}"
        ) from exc
    budgets_raw = payload.get("budgets") or ()
    if not isinstance(budgets_raw, (list, tuple)):
        raise UIIRValidationError("budgets must be a sequence")
    budgets: list[ProfileBudget] = []
    for index, item in enumerate(budgets_raw):
        if not isinstance(item, Mapping):
            raise UIIRValidationError(f"budgets[{index}] must be a mapping")
        try:
            kind = BudgetKind(str(item.get("kind")))
        except ValueError as exc:
            raise UIIRValidationError(
                f"budgets[{index}].kind is not a supported BudgetKind"
            ) from exc
        soft = item.get("soft_limit")
        budgets.append(
            ProfileBudget(
                kind=kind,
                limit=int(item.get("limit", 0)),
                unit=str(item.get("unit") or "count"),
                soft_limit=None if soft is None else int(soft),
            )
        )
    policy_raw = str(payload.get("adaptation_policy") or AdaptationPolicy.ADAPT.value)
    try:
        policy = AdaptationPolicy(policy_raw)
    except ValueError as exc:
        raise UIIRValidationError(
            f"Unknown adaptation_policy: {policy_raw!r}"
        ) from exc

    inputs = payload.get("input_capability_ids") or ()
    outputs = payload.get("output_capability_ids") or ()
    if not isinstance(inputs, (list, tuple)) or not isinstance(outputs, (list, tuple)):
        raise UIIRValidationError("capability id collections must be sequences")

    return validate_device_profile(
        UIDeviceProfile(
            profile_id=str(payload.get("profile_id") or ""),
            family=family,
            input_capability_ids=tuple(str(x) for x in inputs),
            output_capability_ids=tuple(str(x) for x in outputs),
            budgets=tuple(budgets),
            adaptation_policy=policy,
            max_solve_ms=int(payload.get("max_solve_ms", DEFAULT_MAX_SOLVE_MS)),
            max_solve_steps=int(
                payload.get("max_solve_steps", DEFAULT_MAX_SOLVE_STEPS)
            ),
            max_memory_nodes=int(
                payload.get("max_memory_nodes", DEFAULT_MAX_MEMORY_NODES)
            ),
            description=str(payload.get("description") or ""),
            schema_version=str(
                payload.get("schema_version") or UI_DEVICE_PROFILE_SCHEMA_VERSION
            ),
        )
    )


__all__ = [
    "BudgetKind",
    "DEFAULT_MAX_MEMORY_NODES",
    "DEFAULT_MAX_SOLVE_MS",
    "DEFAULT_MAX_SOLVE_STEPS",
    "CapabilityNegotiationResult",
    "CapabilityRequirement",
    "NegotiationStatus",
    "ProfileBudget",
    "ProfileFamily",
    "REQUIRED_BUDGET_KINDS",
    "UI_CAPABILITY_NEGOTIATION_INTERFACE",
    "UI_DEVICE_PROFILE_INTERFACE",
    "UI_DEVICE_PROFILE_SCHEMA_VERSION",
    "UIDeviceProfile",
    "default_profile_catalogue",
    "desktop_profile",
    "glasses_profile",
    "headless_profile",
    "mobile_profile",
    "negotiate_capabilities",
    "profile_from_mapping",
    "validate_device_profile",
    "voice_profile",
]
