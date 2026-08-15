"""Bounded UI invariant engine (VGO-021).

Wire interfaces:

* ``UiInvariantEngine@1`` — finite, source-traceable catalog of bounded UI
  obligations with explicit pass / fail / unknown outcomes.
* ``UiInvariantViolation@1`` — minimal counterexample evidence for a failed
  rule, bound to rule identifiers and source spans.
* ``UiConstraintReceipt@1`` — closed aggregate receipt already owned by the
  VGO-001 models (this engine *emits* it; it does not redefine the schema).

Conflict policy
---------------
Rules are finite, explicit, and independent of aesthetic scoring or backend
authorization.  The engine never authorizes a host action.  Uncertainty
(``unknown`` / inconclusive / unsupported / unresolved / non-exact analysis)
cannot auto-accept a change.

These checks do **not** establish complete accessibility, complete security,
or aesthetic optimality.  A ``satisfied`` status is a bounded structural
conclusion under declared premises, not a WCAG certification or a security
proof.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import deque
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, ClassVar, Final

from .formal_adapter import (
    FORBIDDEN_CLAIM_KINDS as ADAPTER_FORBIDDEN_CLAIM_KINDS,
    GuiFormalAdapter,
    UiAsyncEffectPremise,
    UiConstraintPropertyKind,
    UiConstraintResult,
    UiConstraintResultKind,
    UiConstraintSourceBinding,
    create_gui_formal_adapter,
)
from .models import (
    UiActionBinding,
    UiConstraintReceipt,
    UiEventDefinition,
    UiStateDefinition,
    UiTransitionDefinition,
)
from .schema import (
    CANONICAL_JSON_PROFILE,
    UI_CONSTRAINT_RECEIPT_INTERFACE,
    UI_CONSTRAINT_RECEIPT_SCHEMA,
    AnalysisClassification,
    ConstraintCheckStatus,
    EvidenceLevel,
    VerificationStatus,
    parse_enum,
)

# ---------------------------------------------------------------------------
# Interface / schema identities
# ---------------------------------------------------------------------------

UI_INVARIANT_ENGINE_INTERFACE: Final = "UiInvariantEngine@1"
UI_INVARIANT_ENGINE_SCHEMA: Final = "ui-invariant-engine/v1"
UI_INVARIANT_ENGINE_VERSION: Final = "ui-invariant-engine@1.0.0"

UI_INVARIANT_VIOLATION_INTERFACE: Final = "UiInvariantViolation@1"
UI_INVARIANT_VIOLATION_SCHEMA: Final = "ui-invariant-violation/v1"

UI_INVARIANT_REPORT_INTERFACE: Final = "UiInvariantReport@1"
UI_INVARIANT_REPORT_SCHEMA: Final = "ui-invariant-report/v1"

UI_INVARIANT_WORLD_INTERFACE: Final = "UiInvariantWorld@1"
UI_INVARIANT_WORLD_SCHEMA: Final = "ui-invariant-world/v1"

ENGINE_SOLVER_ID: Final = "solver:ui-invariant-engine"

# Bounded-claim disclaimer.  Satisfied results never upgrade these to proofs.
FULL_ACCESSIBILITY_PROOF: Final = False
FULL_SECURITY_PROOF: Final = False
FULL_AESTHETIC_PROOF: Final = False
ENGINE_AUTHORIZES_ACTIONS: Final = False

INVARIANT_DISCLAIMER: Final = (
    "Bounded UI invariant checks do not establish complete accessibility, "
    "complete security, or aesthetic optimality. Satisfied statuses are "
    "structural conclusions under explicit finite premises. Uncertainty "
    "never authorizes a host action and never auto-accepts a change."
)

FORBIDDEN_CLAIM_KINDS: Final[frozenset[str]] = frozenset(
    ADAPTER_FORBIDDEN_CLAIM_KINDS
) | frozenset({"aesthetic_optimality"})

_IDENTIFIER_RE: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/#@-]{0,255}$")
_DIGEST_RE: Final = re.compile(r"^sha256:[0-9a-f]{64}$")
_MAX_STATES: Final = 256
_MAX_EVENTS: Final = 256
_MAX_TRANSITIONS: Final = 1_024
_MAX_SEQUENCE: Final = 512

_PASS_STATUSES: Final[frozenset[ConstraintCheckStatus]] = frozenset(
    {ConstraintCheckStatus.SATISFIED}
)
_FAIL_STATUSES: Final[frozenset[ConstraintCheckStatus]] = frozenset(
    {ConstraintCheckStatus.VIOLATED}
)
_UNKNOWN_STATUSES: Final[frozenset[ConstraintCheckStatus]] = frozenset(
    {
        ConstraintCheckStatus.INCONCLUSIVE,
        ConstraintCheckStatus.UNSUPPORTED,
        ConstraintCheckStatus.SKIPPED,
        ConstraintCheckStatus.ERROR,
    }
)


class GuiInvariantEngineError(ValueError):
    """Raised when an invariant world or report cannot be constructed safely."""


class UiInvariantVerdict(str, Enum):
    """Closed pass / fail / unknown vocabulary for one bounded rule."""

    PASS = "pass"
    FAIL = "fail"
    UNKNOWN = "unknown"


class UiInvariantFamily(str, Enum):
    """Closed families matching the plan's bounded-obligation groups."""

    STATE_COMPLETENESS = "state_completeness"
    DESTRUCTIVE_POLICY = "destructive_policy"
    FORM_INTEGRITY = "form_integrity"
    STRUCTURE_ACCESSIBILITY = "structure_accessibility"


class UiInvariantAcceptanceOutcome(str, Enum):
    """Automatic-acceptance gate.  There is no authorize outcome."""

    ALLOW_AUTOMATIC = "allow_automatic"
    BLOCK_AUTOMATIC = "block_automatic"


class UiPresentationVisibility(str, Enum):
    ENABLED = "enabled"
    DISABLED = "disabled"
    HIDDEN = "hidden"


class UiDeonticStatus(str, Enum):
    PERMITTED = "permitted"
    OBLIGATED = "obligated"
    PROHIBITED = "prohibited"
    UNAVAILABLE = "unavailable"


class UiBindingResolution(str, Enum):
    EXACT = "exact"
    AMBIGUOUS = "ambiguous"
    DYNAMIC = "dynamic"
    UNRESOLVED = "unresolved"


class UiImageKind(str, Enum):
    NONE = "none"
    MEANINGFUL = "meaningful"
    DECORATIVE = "decorative"


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _reject_unknown(value: Mapping[str, Any], allowed: frozenset[str], label: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise GuiInvariantEngineError(f"unknown {label} field(s): {', '.join(unknown)}")


def _text(value: object, label: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise GuiInvariantEngineError(f"{label} must be a string")
    if "\x00" in value:
        raise GuiInvariantEngineError(f"{label} must not contain NUL bytes")
    if value.strip() != value:
        raise GuiInvariantEngineError(f"{label} must be trimmed")
    if not allow_empty and not value:
        raise GuiInvariantEngineError(f"{label} must be a non-empty string")
    return value


def _identifier(value: object, label: str) -> str:
    text = _text(value, label)
    if not _IDENTIFIER_RE.fullmatch(text):
        raise GuiInvariantEngineError(f"{label} is not a valid identifier")
    return text


def _optional_identifier(value: object, label: str) -> str:
    if value is None or value == "":
        return ""
    return _identifier(value, label)


def _enum(value: object, enum_type: type[Enum], label: str) -> Any:
    try:
        return value if isinstance(value, enum_type) else enum_type(value)
    except (TypeError, ValueError) as error:
        choices = ", ".join(repr(item.value) for item in enum_type)
        raise GuiInvariantEngineError(f"{label} must be one of {choices}") from error


def _schema_enum(value: object, enum_type: type[Enum], label: str) -> Any:
    if isinstance(value, enum_type):
        return value
    if isinstance(value, Enum):
        value = value.value
    try:
        return parse_enum(value, enum_type, label)
    except Exception as error:  # noqa: BLE001 - normalize to engine error
        raise GuiInvariantEngineError(str(error)) from error


def _bool(value: object, label: str) -> bool:
    if not isinstance(value, bool):
        raise GuiInvariantEngineError(f"{label} must be a boolean")
    return value


def _optional_bool(value: object, label: str) -> bool | None:
    if value is None:
        return None
    return _bool(value, label)


def _int(value: object, label: str, *, minimum: int, maximum: int) -> int:
    if type(value) is not int or isinstance(value, bool):
        raise GuiInvariantEngineError(f"{label} must be an int")
    if value < minimum or value > maximum:
        raise GuiInvariantEngineError(f"{label} must be in [{minimum}, {maximum}]")
    return value


def _optional_int(
    value: object, label: str, *, minimum: int, maximum: int
) -> int | None:
    if value is None:
        return None
    return _int(value, label, minimum=minimum, maximum=maximum)


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise GuiInvariantEngineError(f"{label} must be a mapping")
    return value


def _sequence(value: object, label: str) -> Sequence[Any]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise GuiInvariantEngineError(f"{label} must be a sequence")
    if len(value) > _MAX_SEQUENCE:
        raise GuiInvariantEngineError(f"{label} exceeds bound {_MAX_SEQUENCE}")
    return value


def _optional_digest(value: object, label: str) -> str:
    if value is None or value == "":
        return ""
    text = _text(value, label)
    if not _DIGEST_RE.fullmatch(text):
        raise GuiInvariantEngineError(f"{label} must be a sha256:<64-hex> digest")
    return text


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _sha256_hex(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _digest_id(prefix: str, payload: Mapping[str, Any] | bytes) -> str:
    if isinstance(payload, bytes):
        digest = _sha256_hex(payload)
    else:
        digest = _sha256_hex(_canonical_bytes(payload))
    return f"{prefix}:{digest[:32]}"


def _status_to_verdict(status: ConstraintCheckStatus) -> UiInvariantVerdict:
    if status in _PASS_STATUSES:
        return UiInvariantVerdict.PASS
    if status in _FAIL_STATUSES:
        return UiInvariantVerdict.FAIL
    return UiInvariantVerdict.UNKNOWN


def _decode_state(value: object) -> UiStateDefinition:
    if isinstance(value, UiStateDefinition):
        return value
    return UiStateDefinition.from_dict(value)


def _decode_event(value: object) -> UiEventDefinition:
    if isinstance(value, UiEventDefinition):
        return value
    return UiEventDefinition.from_dict(value)


def _decode_transition(value: object) -> UiTransitionDefinition:
    if isinstance(value, UiTransitionDefinition):
        return value
    return UiTransitionDefinition.from_dict(value)


# ---------------------------------------------------------------------------
# Observation records
# ---------------------------------------------------------------------------


_CONFIRMATION_FIELDS: Final = frozenset(
    {
        "action_id",
        "argument_digest",
        "confirmation_id",
        "granted",
        "notes",
        "policy_decision_id",
    }
)


@dataclass(frozen=True, slots=True)
class UiConfirmationObservation:
    """Exact action + argument-digest confirmation binding."""

    confirmation_id: str
    action_id: str
    argument_digest: str
    granted: bool = False
    policy_decision_id: str = ""
    notes: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "confirmation_id", _identifier(self.confirmation_id, "confirmation_id")
        )
        object.__setattr__(self, "action_id", _identifier(self.action_id, "action_id"))
        object.__setattr__(
            self, "argument_digest", _optional_digest(self.argument_digest, "argument_digest")
        )
        object.__setattr__(self, "granted", _bool(self.granted, "granted"))
        object.__setattr__(
            self,
            "policy_decision_id",
            _optional_identifier(self.policy_decision_id, "policy_decision_id"),
        )
        object.__setattr__(self, "notes", _text(self.notes, "notes", allow_empty=True))

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_id": self.action_id,
            "argument_digest": self.argument_digest,
            "confirmation_id": self.confirmation_id,
            "granted": self.granted,
            "notes": self.notes,
            "policy_decision_id": self.policy_decision_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any] | Any) -> UiConfirmationObservation:
        payload = _mapping(value, "UiConfirmationObservation")
        _reject_unknown(payload, _CONFIRMATION_FIELDS, "UiConfirmationObservation")
        return cls(
            confirmation_id=payload.get("confirmation_id", ""),
            action_id=payload.get("action_id", ""),
            argument_digest=payload.get("argument_digest", ""),
            granted=payload.get("granted", False),
            policy_decision_id=payload.get("policy_decision_id", ""),
            notes=payload.get("notes", ""),
        )


_RUNTIME_FIELDS: Final = frozenset(
    {
        "action_id",
        "browser_policy_authoritative_claim",
        "current_argument_digest",
        "current_method",
        "current_schema_id",
        "deontic_status",
        "has_hidden_dispatch_path",
        "is_dispatchable",
        "policy_fresh",
        "presentation_visibility",
        "resolution",
        "runtime_reevaluated",
        "target_count",
    }
)


@dataclass(frozen=True, slots=True)
class UiActionRuntimeObservation:
    """Runtime re-evaluation facts for one displayed action."""

    action_id: str
    current_method: str
    current_schema_id: str
    current_argument_digest: str = ""
    presentation_visibility: UiPresentationVisibility | str = UiPresentationVisibility.ENABLED
    deontic_status: UiDeonticStatus | str = UiDeonticStatus.PERMITTED
    resolution: UiBindingResolution | str = UiBindingResolution.EXACT
    target_count: int = 1
    is_dispatchable: bool = True
    has_hidden_dispatch_path: bool = False
    runtime_reevaluated: bool = True
    policy_fresh: bool = True
    browser_policy_authoritative_claim: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "action_id", _identifier(self.action_id, "action_id"))
        object.__setattr__(
            self, "current_method", _identifier(self.current_method, "current_method")
        )
        object.__setattr__(
            self,
            "current_schema_id",
            _identifier(self.current_schema_id, "current_schema_id"),
        )
        object.__setattr__(
            self,
            "current_argument_digest",
            _optional_digest(self.current_argument_digest, "current_argument_digest"),
        )
        object.__setattr__(
            self,
            "presentation_visibility",
            _enum(
                self.presentation_visibility,
                UiPresentationVisibility,
                "presentation_visibility",
            ),
        )
        object.__setattr__(
            self,
            "deontic_status",
            _enum(self.deontic_status, UiDeonticStatus, "deontic_status"),
        )
        object.__setattr__(
            self,
            "resolution",
            _enum(self.resolution, UiBindingResolution, "resolution"),
        )
        object.__setattr__(
            self,
            "target_count",
            _int(self.target_count, "target_count", minimum=0, maximum=64),
        )
        object.__setattr__(
            self, "is_dispatchable", _bool(self.is_dispatchable, "is_dispatchable")
        )
        object.__setattr__(
            self,
            "has_hidden_dispatch_path",
            _bool(self.has_hidden_dispatch_path, "has_hidden_dispatch_path"),
        )
        object.__setattr__(
            self,
            "runtime_reevaluated",
            _bool(self.runtime_reevaluated, "runtime_reevaluated"),
        )
        object.__setattr__(self, "policy_fresh", _bool(self.policy_fresh, "policy_fresh"))
        object.__setattr__(
            self,
            "browser_policy_authoritative_claim",
            _bool(
                self.browser_policy_authoritative_claim,
                "browser_policy_authoritative_claim",
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_id": self.action_id,
            "browser_policy_authoritative_claim": self.browser_policy_authoritative_claim,
            "current_argument_digest": self.current_argument_digest,
            "current_method": self.current_method,
            "current_schema_id": self.current_schema_id,
            "deontic_status": self.deontic_status.value,
            "has_hidden_dispatch_path": self.has_hidden_dispatch_path,
            "is_dispatchable": self.is_dispatchable,
            "policy_fresh": self.policy_fresh,
            "presentation_visibility": self.presentation_visibility.value,
            "resolution": self.resolution.value,
            "runtime_reevaluated": self.runtime_reevaluated,
            "target_count": self.target_count,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any] | Any) -> UiActionRuntimeObservation:
        payload = _mapping(value, "UiActionRuntimeObservation")
        _reject_unknown(payload, _RUNTIME_FIELDS, "UiActionRuntimeObservation")
        return cls(
            action_id=payload.get("action_id", ""),
            current_method=payload.get("current_method", ""),
            current_schema_id=payload.get("current_schema_id", ""),
            current_argument_digest=payload.get("current_argument_digest", ""),
            presentation_visibility=payload.get(
                "presentation_visibility", UiPresentationVisibility.ENABLED.value
            ),
            deontic_status=payload.get("deontic_status", UiDeonticStatus.PERMITTED.value),
            resolution=payload.get("resolution", UiBindingResolution.EXACT.value),
            target_count=payload.get("target_count", 1),
            is_dispatchable=payload.get("is_dispatchable", True),
            has_hidden_dispatch_path=payload.get("has_hidden_dispatch_path", False),
            runtime_reevaluated=payload.get("runtime_reevaluated", True),
            policy_fresh=payload.get("policy_fresh", True),
            browser_policy_authoritative_claim=payload.get(
                "browser_policy_authoritative_claim", False
            ),
        )


_FORM_INPUT_FIELDS: Final = frozenset(
    {
        "accessible_name",
        "associated_error_ids",
        "exposes_required_state",
        "input_id",
        "required",
    }
)


@dataclass(frozen=True, slots=True)
class UiFormInputObservation:
    """Declared form-control facts used by form-integrity rules."""

    input_id: str
    accessible_name: str
    required: bool = False
    exposes_required_state: bool | None = None
    associated_error_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "input_id", _identifier(self.input_id, "input_id"))
        object.__setattr__(
            self,
            "accessible_name",
            _text(self.accessible_name, "accessible_name", allow_empty=True),
        )
        object.__setattr__(self, "required", _bool(self.required, "required"))
        object.__setattr__(
            self,
            "exposes_required_state",
            _optional_bool(self.exposes_required_state, "exposes_required_state"),
        )
        ids = tuple(
            _identifier(item, "associated_error_ids item")
            for item in self.associated_error_ids
        )
        if len(ids) != len(set(ids)):
            raise GuiInvariantEngineError("associated_error_ids must be unique")
        object.__setattr__(self, "associated_error_ids", ids)

    def to_dict(self) -> dict[str, Any]:
        return {
            "accessible_name": self.accessible_name,
            "associated_error_ids": list(self.associated_error_ids),
            "exposes_required_state": self.exposes_required_state,
            "input_id": self.input_id,
            "required": self.required,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any] | Any) -> UiFormInputObservation:
        payload = _mapping(value, "UiFormInputObservation")
        _reject_unknown(payload, _FORM_INPUT_FIELDS, "UiFormInputObservation")
        return cls(
            input_id=payload.get("input_id", ""),
            accessible_name=payload.get("accessible_name", ""),
            required=payload.get("required", False),
            exposes_required_state=payload.get("exposes_required_state"),
            associated_error_ids=tuple(payload.get("associated_error_ids", ())),
        )


_VALIDATION_ERROR_FIELDS: Final = frozenset({"error_id", "field_id", "message"})


@dataclass(frozen=True, slots=True)
class UiValidationErrorObservation:
    """A validation error that must associate with a specific field."""

    error_id: str
    field_id: str
    message: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "error_id", _identifier(self.error_id, "error_id"))
        object.__setattr__(self, "field_id", _identifier(self.field_id, "field_id"))
        object.__setattr__(self, "message", _text(self.message, "message", allow_empty=True))

    def to_dict(self) -> dict[str, Any]:
        return {
            "error_id": self.error_id,
            "field_id": self.field_id,
            "message": self.message,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any] | Any) -> UiValidationErrorObservation:
        payload = _mapping(value, "UiValidationErrorObservation")
        _reject_unknown(payload, _VALIDATION_ERROR_FIELDS, "UiValidationErrorObservation")
        return cls(
            error_id=payload.get("error_id", ""),
            field_id=payload.get("field_id", ""),
            message=payload.get("message", ""),
        )


_FORM_SUBMISSION_FIELDS: Final = frozenset(
    {"discards_validation_failure", "success_follows_confirmed_effect"}
)


@dataclass(frozen=True, slots=True)
class UiFormSubmissionObservation:
    """Submission / success integrity flags for one form surface."""

    discards_validation_failure: bool
    success_follows_confirmed_effect: bool

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "discards_validation_failure",
            _bool(self.discards_validation_failure, "discards_validation_failure"),
        )
        object.__setattr__(
            self,
            "success_follows_confirmed_effect",
            _bool(
                self.success_follows_confirmed_effect,
                "success_follows_confirmed_effect",
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "discards_validation_failure": self.discards_validation_failure,
            "success_follows_confirmed_effect": self.success_follows_confirmed_effect,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any] | Any) -> UiFormSubmissionObservation:
        payload = _mapping(value, "UiFormSubmissionObservation")
        _reject_unknown(payload, _FORM_SUBMISSION_FIELDS, "UiFormSubmissionObservation")
        return cls(
            discards_validation_failure=payload.get("discards_validation_failure", True),
            success_follows_confirmed_effect=payload.get(
                "success_follows_confirmed_effect", False
            ),
        )


_MODAL_FIELDS: Final = frozenset(
    {
        "close_restores_focus",
        "escape_or_cancel_defined",
        "hidden_not_focusable",
        "modal_id",
        "opens_moves_focus_inside",
        "tab_contained",
    }
)


@dataclass(frozen=True, slots=True)
class UiModalFocusObservation:
    """Bounded modal focus-lifecycle observations (not a complete a11y proof)."""

    modal_id: str
    opens_moves_focus_inside: bool | None = None
    tab_contained: bool | None = None
    escape_or_cancel_defined: bool | None = None
    close_restores_focus: bool | None = None
    hidden_not_focusable: bool | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "modal_id", _identifier(self.modal_id, "modal_id"))
        object.__setattr__(
            self,
            "opens_moves_focus_inside",
            _optional_bool(self.opens_moves_focus_inside, "opens_moves_focus_inside"),
        )
        object.__setattr__(
            self, "tab_contained", _optional_bool(self.tab_contained, "tab_contained")
        )
        object.__setattr__(
            self,
            "escape_or_cancel_defined",
            _optional_bool(self.escape_or_cancel_defined, "escape_or_cancel_defined"),
        )
        object.__setattr__(
            self,
            "close_restores_focus",
            _optional_bool(self.close_restores_focus, "close_restores_focus"),
        )
        object.__setattr__(
            self,
            "hidden_not_focusable",
            _optional_bool(self.hidden_not_focusable, "hidden_not_focusable"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "close_restores_focus": self.close_restores_focus,
            "escape_or_cancel_defined": self.escape_or_cancel_defined,
            "hidden_not_focusable": self.hidden_not_focusable,
            "modal_id": self.modal_id,
            "opens_moves_focus_inside": self.opens_moves_focus_inside,
            "tab_contained": self.tab_contained,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any] | Any) -> UiModalFocusObservation:
        payload = _mapping(value, "UiModalFocusObservation")
        _reject_unknown(payload, _MODAL_FIELDS, "UiModalFocusObservation")
        return cls(
            modal_id=payload.get("modal_id", ""),
            opens_moves_focus_inside=payload.get("opens_moves_focus_inside"),
            tab_contained=payload.get("tab_contained"),
            escape_or_cancel_defined=payload.get("escape_or_cancel_defined"),
            close_restores_focus=payload.get("close_restores_focus"),
            hidden_not_focusable=payload.get("hidden_not_focusable"),
        )


_DOM_FIELDS: Final = frozenset(
    {
        "accessible_name",
        "decorative_hidden",
        "dom_id",
        "has_keyboard_activation",
        "has_text_alternative",
        "heading_level",
        "image_kind",
        "interactive",
        "native_control",
        "node_id",
        "role",
    }
)


@dataclass(frozen=True, slots=True)
class UiDomNodeObservation:
    """Bounded DOM identity / keyboard / heading / image observation."""

    node_id: str
    dom_id: str = ""
    role: str = ""
    interactive: bool = False
    accessible_name: str = ""
    native_control: bool = False
    has_keyboard_activation: bool | None = None
    heading_level: int | None = None
    image_kind: UiImageKind | str = UiImageKind.NONE
    has_text_alternative: bool | None = None
    decorative_hidden: bool | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "node_id", _identifier(self.node_id, "node_id"))
        object.__setattr__(
            self, "dom_id", _text(self.dom_id, "dom_id", allow_empty=True)
        )
        object.__setattr__(self, "role", _text(self.role, "role", allow_empty=True))
        object.__setattr__(self, "interactive", _bool(self.interactive, "interactive"))
        object.__setattr__(
            self,
            "accessible_name",
            _text(self.accessible_name, "accessible_name", allow_empty=True),
        )
        object.__setattr__(
            self, "native_control", _bool(self.native_control, "native_control")
        )
        object.__setattr__(
            self,
            "has_keyboard_activation",
            _optional_bool(self.has_keyboard_activation, "has_keyboard_activation"),
        )
        object.__setattr__(
            self,
            "heading_level",
            _optional_int(self.heading_level, "heading_level", minimum=1, maximum=6),
        )
        object.__setattr__(
            self, "image_kind", _enum(self.image_kind, UiImageKind, "image_kind")
        )
        object.__setattr__(
            self,
            "has_text_alternative",
            _optional_bool(self.has_text_alternative, "has_text_alternative"),
        )
        object.__setattr__(
            self,
            "decorative_hidden",
            _optional_bool(self.decorative_hidden, "decorative_hidden"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "accessible_name": self.accessible_name,
            "decorative_hidden": self.decorative_hidden,
            "dom_id": self.dom_id,
            "has_keyboard_activation": self.has_keyboard_activation,
            "has_text_alternative": self.has_text_alternative,
            "heading_level": self.heading_level,
            "image_kind": self.image_kind.value,
            "interactive": self.interactive,
            "native_control": self.native_control,
            "node_id": self.node_id,
            "role": self.role,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any] | Any) -> UiDomNodeObservation:
        payload = _mapping(value, "UiDomNodeObservation")
        _reject_unknown(payload, _DOM_FIELDS, "UiDomNodeObservation")
        return cls(
            node_id=payload.get("node_id", ""),
            dom_id=payload.get("dom_id", ""),
            role=payload.get("role", ""),
            interactive=payload.get("interactive", False),
            accessible_name=payload.get("accessible_name", ""),
            native_control=payload.get("native_control", False),
            has_keyboard_activation=payload.get("has_keyboard_activation"),
            heading_level=payload.get("heading_level"),
            image_kind=payload.get("image_kind", UiImageKind.NONE.value),
            has_text_alternative=payload.get("has_text_alternative"),
            decorative_hidden=payload.get("decorative_hidden"),
        )


_PRESENTATION_FIELDS: Final = frozenset(
    {"accesses_credentials", "component_id", "is_presentation"}
)


@dataclass(frozen=True, slots=True)
class UiPresentationObservation:
    """Presentation-component credential-access observation."""

    component_id: str
    is_presentation: bool
    accesses_credentials: bool

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "component_id", _identifier(self.component_id, "component_id")
        )
        object.__setattr__(
            self, "is_presentation", _bool(self.is_presentation, "is_presentation")
        )
        object.__setattr__(
            self,
            "accesses_credentials",
            _bool(self.accesses_credentials, "accesses_credentials"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "accesses_credentials": self.accesses_credentials,
            "component_id": self.component_id,
            "is_presentation": self.is_presentation,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any] | Any) -> UiPresentationObservation:
        payload = _mapping(value, "UiPresentationObservation")
        _reject_unknown(payload, _PRESENTATION_FIELDS, "UiPresentationObservation")
        return cls(
            component_id=payload.get("component_id", ""),
            is_presentation=payload.get("is_presentation", True),
            accesses_credentials=payload.get("accesses_credentials", False),
        )


_POLICY_FIELDS: Final = frozenset(
    {"browser_policy_authoritative", "host_authorization_authoritative"}
)


@dataclass(frozen=True, slots=True)
class UiPolicyObservation:
    """Policy-authority observation.  Browser output is never authoritative."""

    browser_policy_authoritative: bool
    host_authorization_authoritative: bool

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "browser_policy_authoritative",
            _bool(self.browser_policy_authoritative, "browser_policy_authoritative"),
        )
        object.__setattr__(
            self,
            "host_authorization_authoritative",
            _bool(
                self.host_authorization_authoritative,
                "host_authorization_authoritative",
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "browser_policy_authoritative": self.browser_policy_authoritative,
            "host_authorization_authoritative": self.host_authorization_authoritative,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any] | Any) -> UiPolicyObservation:
        payload = _mapping(value, "UiPolicyObservation")
        _reject_unknown(payload, _POLICY_FIELDS, "UiPolicyObservation")
        return cls(
            browser_policy_authoritative=payload.get(
                "browser_policy_authoritative", False
            ),
            host_authorization_authoritative=payload.get(
                "host_authorization_authoritative", True
            ),
        )


# ---------------------------------------------------------------------------
# World (closed input)
# ---------------------------------------------------------------------------


_WORLD_FIELDS: Final = frozenset(
    {
        "action_bindings",
        "action_state_ids",
        "analysis_classification",
        "application_id",
        "async_effects",
        "confirmations",
        "dom_nodes",
        "events",
        "form_inputs",
        "form_submission",
        "initial_state_id",
        "interface",
        "machine_id",
        "modal_focus",
        "policy",
        "presentation_components",
        "repository_revision",
        "required_action_ids",
        "runtime_observations",
        "schema_version",
        "screen_id",
        "source_bindings",
        "state_event_ids",
        "states",
        "transitions",
        "unresolved",
        "validation_errors",
    }
)


@dataclass(frozen=True, slots=True)
class UiInvariantWorld:
    """Closed observation world consumed by ``UiInvariantEngine@1``."""

    INTERFACE: ClassVar[str] = UI_INVARIANT_WORLD_INTERFACE
    SCHEMA_VERSION: ClassVar[str] = UI_INVARIANT_WORLD_SCHEMA

    application_id: str
    screen_id: str
    machine_id: str
    repository_revision: str
    initial_state_id: str
    states: tuple[UiStateDefinition, ...]
    events: tuple[UiEventDefinition, ...]
    transitions: tuple[UiTransitionDefinition, ...]
    analysis_classification: AnalysisClassification | str = AnalysisClassification.EXACT
    async_effects: tuple[UiAsyncEffectPremise, ...] = ()
    required_action_ids: tuple[str, ...] = ()
    action_state_ids: Mapping[str, str] = field(default_factory=dict)
    state_event_ids: Mapping[str, tuple[str, ...]] | None = None
    action_bindings: tuple[UiActionBinding, ...] = ()
    confirmations: tuple[UiConfirmationObservation, ...] = ()
    runtime_observations: tuple[UiActionRuntimeObservation, ...] = ()
    form_inputs: tuple[UiFormInputObservation, ...] = ()
    validation_errors: tuple[UiValidationErrorObservation, ...] = ()
    form_submission: UiFormSubmissionObservation | None = None
    modal_focus: tuple[UiModalFocusObservation, ...] = ()
    dom_nodes: tuple[UiDomNodeObservation, ...] = ()
    presentation_components: tuple[UiPresentationObservation, ...] = ()
    policy: UiPolicyObservation | None = None
    source_bindings: tuple[UiConstraintSourceBinding, ...] = ()
    unresolved: tuple[str, ...] = ()
    interface: str = UI_INVARIANT_WORLD_INTERFACE
    schema_version: str = UI_INVARIANT_WORLD_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "application_id", _identifier(self.application_id, "application_id")
        )
        object.__setattr__(self, "screen_id", _identifier(self.screen_id, "screen_id"))
        object.__setattr__(self, "machine_id", _identifier(self.machine_id, "machine_id"))
        object.__setattr__(
            self,
            "repository_revision",
            _text(self.repository_revision, "repository_revision"),
        )
        object.__setattr__(
            self,
            "initial_state_id",
            _identifier(self.initial_state_id, "initial_state_id")
            if self.initial_state_id
            else "",
        )
        states = tuple(self.states)
        events = tuple(self.events)
        transitions = tuple(self.transitions)
        if len(states) > _MAX_STATES:
            raise GuiInvariantEngineError(f"states exceeds bound {_MAX_STATES}")
        if len(events) > _MAX_EVENTS:
            raise GuiInvariantEngineError(f"events exceeds bound {_MAX_EVENTS}")
        if len(transitions) > _MAX_TRANSITIONS:
            raise GuiInvariantEngineError(
                f"transitions exceeds bound {_MAX_TRANSITIONS}"
            )
        for index, state in enumerate(states):
            if not isinstance(state, UiStateDefinition):
                raise GuiInvariantEngineError(
                    f"states[{index}] must be a UiStateDefinition"
                )
        for index, event in enumerate(events):
            if not isinstance(event, UiEventDefinition):
                raise GuiInvariantEngineError(
                    f"events[{index}] must be a UiEventDefinition"
                )
        for index, transition in enumerate(transitions):
            if not isinstance(transition, UiTransitionDefinition):
                raise GuiInvariantEngineError(
                    f"transitions[{index}] must be a UiTransitionDefinition"
                )
        object.__setattr__(self, "states", states)
        object.__setattr__(self, "events", events)
        object.__setattr__(self, "transitions", transitions)
        object.__setattr__(
            self,
            "analysis_classification",
            _schema_enum(
                self.analysis_classification,
                AnalysisClassification,
                "analysis_classification",
            ),
        )
        effects = tuple(
            item
            if isinstance(item, UiAsyncEffectPremise)
            else UiAsyncEffectPremise.from_dict(item)
            for item in self.async_effects
        )
        object.__setattr__(self, "async_effects", effects)
        required = tuple(
            _identifier(item, "required_action_ids item")
            for item in self.required_action_ids
        )
        if len(required) != len(set(required)):
            raise GuiInvariantEngineError("required_action_ids must be unique")
        object.__setattr__(self, "required_action_ids", required)
        action_states = {
            _identifier(key, "action_state_ids key"): _identifier(
                value, "action_state_ids value"
            )
            for key, value in dict(self.action_state_ids or {}).items()
        }
        object.__setattr__(self, "action_state_ids", action_states)
        if self.state_event_ids is None:
            object.__setattr__(self, "state_event_ids", None)
        else:
            decoded_events: dict[str, tuple[str, ...]] = {}
            for key, values in dict(self.state_event_ids).items():
                decoded_events[_identifier(key, "state_event_ids key")] = tuple(
                    _identifier(item, "state_event_ids value") for item in values
                )
            object.__setattr__(self, "state_event_ids", decoded_events)
        bindings = tuple(
            item if isinstance(item, UiActionBinding) else UiActionBinding.from_dict(item)
            for item in self.action_bindings
        )
        object.__setattr__(self, "action_bindings", bindings)
        confirmations = tuple(
            item
            if isinstance(item, UiConfirmationObservation)
            else UiConfirmationObservation.from_dict(item)
            for item in self.confirmations
        )
        object.__setattr__(self, "confirmations", confirmations)
        runtime = tuple(
            item
            if isinstance(item, UiActionRuntimeObservation)
            else UiActionRuntimeObservation.from_dict(item)
            for item in self.runtime_observations
        )
        object.__setattr__(self, "runtime_observations", runtime)
        inputs = tuple(
            item
            if isinstance(item, UiFormInputObservation)
            else UiFormInputObservation.from_dict(item)
            for item in self.form_inputs
        )
        object.__setattr__(self, "form_inputs", inputs)
        errors = tuple(
            item
            if isinstance(item, UiValidationErrorObservation)
            else UiValidationErrorObservation.from_dict(item)
            for item in self.validation_errors
        )
        object.__setattr__(self, "validation_errors", errors)
        submission = self.form_submission
        if submission is not None and not isinstance(
            submission, UiFormSubmissionObservation
        ):
            submission = UiFormSubmissionObservation.from_dict(
                _mapping(submission, "form_submission")
            )
        object.__setattr__(self, "form_submission", submission)
        modals = tuple(
            item
            if isinstance(item, UiModalFocusObservation)
            else UiModalFocusObservation.from_dict(item)
            for item in self.modal_focus
        )
        object.__setattr__(self, "modal_focus", modals)
        nodes = tuple(
            item
            if isinstance(item, UiDomNodeObservation)
            else UiDomNodeObservation.from_dict(item)
            for item in self.dom_nodes
        )
        object.__setattr__(self, "dom_nodes", nodes)
        presentation = tuple(
            item
            if isinstance(item, UiPresentationObservation)
            else UiPresentationObservation.from_dict(item)
            for item in self.presentation_components
        )
        object.__setattr__(self, "presentation_components", presentation)
        policy = self.policy
        if policy is not None and not isinstance(policy, UiPolicyObservation):
            policy = UiPolicyObservation.from_dict(_mapping(policy, "policy"))
        object.__setattr__(self, "policy", policy)
        bindings_src = tuple(
            item
            if isinstance(item, UiConstraintSourceBinding)
            else UiConstraintSourceBinding.from_dict(item)
            for item in self.source_bindings
        )
        object.__setattr__(self, "source_bindings", bindings_src)
        unresolved = tuple(_text(item, "unresolved item") for item in self.unresolved)
        if len(unresolved) != len(set(unresolved)):
            raise GuiInvariantEngineError("unresolved must be unique")
        object.__setattr__(self, "unresolved", unresolved)
        if self.interface != UI_INVARIANT_WORLD_INTERFACE:
            raise GuiInvariantEngineError(
                f"unsupported UiInvariantWorld interface: {self.interface!r}"
            )
        if self.schema_version != UI_INVARIANT_WORLD_SCHEMA:
            raise GuiInvariantEngineError(
                f"unsupported UiInvariantWorld schema_version: {self.schema_version!r}"
            )
        object.__setattr__(self, "interface", UI_INVARIANT_WORLD_INTERFACE)
        object.__setattr__(self, "schema_version", UI_INVARIANT_WORLD_SCHEMA)

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_bindings": [item.to_dict() for item in self.action_bindings],
            "action_state_ids": dict(self.action_state_ids),
            "analysis_classification": self.analysis_classification.value,
            "application_id": self.application_id,
            "async_effects": [item.to_dict() for item in self.async_effects],
            "confirmations": [item.to_dict() for item in self.confirmations],
            "dom_nodes": [item.to_dict() for item in self.dom_nodes],
            "events": [item.to_dict() for item in self.events],
            "form_inputs": [item.to_dict() for item in self.form_inputs],
            "form_submission": (
                None if self.form_submission is None else self.form_submission.to_dict()
            ),
            "initial_state_id": self.initial_state_id,
            "interface": self.interface,
            "machine_id": self.machine_id,
            "modal_focus": [item.to_dict() for item in self.modal_focus],
            "policy": None if self.policy is None else self.policy.to_dict(),
            "presentation_components": [
                item.to_dict() for item in self.presentation_components
            ],
            "repository_revision": self.repository_revision,
            "required_action_ids": list(self.required_action_ids),
            "runtime_observations": [item.to_dict() for item in self.runtime_observations],
            "schema_version": self.schema_version,
            "screen_id": self.screen_id,
            "source_bindings": [item.to_dict() for item in self.source_bindings],
            "state_event_ids": (
                None
                if self.state_event_ids is None
                else {key: list(value) for key, value in self.state_event_ids.items()}
            ),
            "states": [item.to_dict() for item in self.states],
            "transitions": [item.to_dict() for item in self.transitions],
            "unresolved": list(self.unresolved),
            "validation_errors": [item.to_dict() for item in self.validation_errors],
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any] | Any) -> UiInvariantWorld:
        payload = _mapping(value, "UiInvariantWorld")
        _reject_unknown(payload, _WORLD_FIELDS, "UiInvariantWorld")
        submission_raw = payload.get("form_submission")
        policy_raw = payload.get("policy")
        state_event_raw = payload.get("state_event_ids")
        state_event_ids: Mapping[str, tuple[str, ...]] | None
        if state_event_raw is None:
            state_event_ids = None
        else:
            mapping = _mapping(state_event_raw, "state_event_ids")
            state_event_ids = {
                key: tuple(_sequence(values, f"state_event_ids[{key}]"))
                for key, values in mapping.items()
            }
        return cls(
            application_id=payload.get("application_id", ""),
            screen_id=payload.get("screen_id", ""),
            machine_id=payload.get("machine_id", ""),
            repository_revision=payload.get("repository_revision", ""),
            initial_state_id=payload.get("initial_state_id", ""),
            states=tuple(
                _decode_state(item)
                for item in _sequence(payload.get("states", ()), "states")
            ),
            events=tuple(
                _decode_event(item)
                for item in _sequence(payload.get("events", ()), "events")
            ),
            transitions=tuple(
                _decode_transition(item)
                for item in _sequence(payload.get("transitions", ()), "transitions")
            ),
            analysis_classification=payload.get(
                "analysis_classification", AnalysisClassification.EXACT.value
            ),
            async_effects=tuple(payload.get("async_effects", ())),
            required_action_ids=tuple(payload.get("required_action_ids", ())),
            action_state_ids=dict(payload.get("action_state_ids", {}) or {}),
            state_event_ids=state_event_ids,
            action_bindings=tuple(payload.get("action_bindings", ())),
            confirmations=tuple(payload.get("confirmations", ())),
            runtime_observations=tuple(payload.get("runtime_observations", ())),
            form_inputs=tuple(payload.get("form_inputs", ())),
            validation_errors=tuple(payload.get("validation_errors", ())),
            form_submission=submission_raw,
            modal_focus=tuple(payload.get("modal_focus", ())),
            dom_nodes=tuple(payload.get("dom_nodes", ())),
            presentation_components=tuple(payload.get("presentation_components", ())),
            policy=policy_raw,
            source_bindings=tuple(payload.get("source_bindings", ())),
            unresolved=tuple(payload.get("unresolved", ())),
            interface=payload.get("interface", UI_INVARIANT_WORLD_INTERFACE),
            schema_version=payload.get("schema_version", UI_INVARIANT_WORLD_SCHEMA),
        )


# ---------------------------------------------------------------------------
# Catalog, verdicts, violations, report
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class UiInvariantRule:
    """One finite catalog entry.  Every required rule is always evaluated."""

    rule_id: str
    check_id: str
    property_kind: str
    family: UiInvariantFamily
    summary: str
    requires_observations: bool
    adapter_property: UiConstraintPropertyKind | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "adapter_property": (
                None if self.adapter_property is None else self.adapter_property.value
            ),
            "check_id": self.check_id,
            "family": self.family.value,
            "property_kind": self.property_kind,
            "requires_observations": self.requires_observations,
            "rule_id": self.rule_id,
            "summary": self.summary,
        }


def _rule(
    property_kind: str,
    family: UiInvariantFamily,
    summary: str,
    *,
    requires_observations: bool,
    adapter_property: UiConstraintPropertyKind | None = None,
) -> UiInvariantRule:
    slug = property_kind.replace("_", "-")
    return UiInvariantRule(
        rule_id=f"invariant:{slug}",
        check_id=f"check:{slug}",
        property_kind=property_kind,
        family=family,
        summary=summary,
        requires_observations=requires_observations,
        adapter_property=adapter_property,
    )


REQUIRED_INVARIANT_RULES: Final[tuple[UiInvariantRule, ...]] = (
    _rule(
        "defined_transition_targets",
        UiInvariantFamily.STATE_COMPLETENESS,
        "No transition targets an undefined state, source, or event.",
        requires_observations=False,
        adapter_property=UiConstraintPropertyKind.DEFINED_TRANSITION_TARGETS,
    ),
    _rule(
        "event_outcome_coverage",
        UiInvariantFamily.STATE_COMPLETENESS,
        "Every declared event in a reachable state has an outcome or explicit no-op.",
        requires_observations=False,
        adapter_property=UiConstraintPropertyKind.EVENT_OUTCOME_COVERAGE,
    ),
    _rule(
        "failure_recovery",
        UiInvariantFamily.STATE_COMPLETENESS,
        "A nonterminal failure has a recovery or explicit terminal explanation.",
        requires_observations=False,
        adapter_property=UiConstraintPropertyKind.FAILURE_RECOVERY,
    ),
    _rule(
        "async_effect_completeness",
        UiInvariantFamily.STATE_COMPLETENESS,
        "Each represented asynchronous operation has loading and failure behavior.",
        requires_observations=True,
        adapter_property=UiConstraintPropertyKind.ASYNC_EFFECT_COMPLETENESS,
    ),
    _rule(
        "reachable_required_action",
        UiInvariantFamily.STATE_COMPLETENESS,
        "Required actions are not reachable only through impossible states.",
        requires_observations=True,
        adapter_property=UiConstraintPropertyKind.REACHABLE_REQUIRED_ACTION,
    ),
    _rule(
        "single_initial_state",
        UiInvariantFamily.STATE_COMPLETENESS,
        "The machine declares exactly one initial state.",
        requires_observations=False,
        adapter_property=UiConstraintPropertyKind.SINGLE_INITIAL_STATE,
    ),
    _rule(
        "no_duplicate_state_ids",
        UiInvariantFamily.STATE_COMPLETENESS,
        "State identifiers are unique.",
        requires_observations=False,
        adapter_property=UiConstraintPropertyKind.NO_DUPLICATE_STATE_IDS,
    ),
    _rule(
        "confirmation_bound_action",
        UiInvariantFamily.DESTRUCTIVE_POLICY,
        "Destructive actions require confirmation bound to exact action and arguments.",
        requires_observations=True,
    ),
    _rule(
        "presentation_no_credentials",
        UiInvariantFamily.DESTRUCTIVE_POLICY,
        "Presentation components do not access credentials.",
        requires_observations=True,
    ),
    _rule(
        "policy_not_browser_authoritative",
        UiInvariantFamily.DESTRUCTIVE_POLICY,
        "Browser policy output is never authoritative.",
        requires_observations=True,
    ),
    _rule(
        "no_hidden_dispatch",
        UiInvariantFamily.DESTRUCTIVE_POLICY,
        "Prohibited or disabled actions have no executable hidden dispatch path.",
        requires_observations=True,
    ),
    _rule(
        "single_action_binding",
        UiInvariantFamily.DESTRUCTIVE_POLICY,
        "Displayed actions resolve to exactly one intended method and schema.",
        requires_observations=True,
    ),
    _rule(
        "runtime_action_reevaluation",
        UiInvariantFamily.DESTRUCTIVE_POLICY,
        "Current action and arguments are re-evaluated at runtime.",
        requires_observations=True,
    ),
    _rule(
        "stale_policy_cannot_authorize",
        UiInvariantFamily.DESTRUCTIVE_POLICY,
        "A stale policy decision cannot authorize the current action.",
        requires_observations=True,
    ),
    _rule(
        "form_accessible_names",
        UiInvariantFamily.FORM_INTEGRITY,
        "Every input has an accessible name.",
        requires_observations=True,
    ),
    _rule(
        "form_required_state",
        UiInvariantFamily.FORM_INTEGRITY,
        "Required inputs expose required-state semantics.",
        requires_observations=True,
    ),
    _rule(
        "form_error_association",
        UiInvariantFamily.FORM_INTEGRITY,
        "Errors associate with the relevant field.",
        requires_observations=True,
    ),
    _rule(
        "form_submission_validation",
        UiInvariantFamily.FORM_INTEGRITY,
        "Submission does not silently discard validation failure.",
        requires_observations=True,
    ),
    _rule(
        "form_success_after_effect",
        UiInvariantFamily.FORM_INTEGRITY,
        "Success follows confirmed effect completion.",
        requires_observations=True,
    ),
    _rule(
        "modal_focus_lifecycle",
        UiInvariantFamily.STRUCTURE_ACCESSIBILITY,
        "Modal open/Tab/Escape/close/hidden focus obligations hold.",
        requires_observations=True,
    ),
    _rule(
        "unique_dom_ids",
        UiInvariantFamily.STRUCTURE_ACCESSIBILITY,
        "Rendered scenarios have no duplicate IDs.",
        requires_observations=True,
    ),
    _rule(
        "interactive_accessible_names",
        UiInvariantFamily.STRUCTURE_ACCESSIBILITY,
        "Interactive controls have accessible names.",
        requires_observations=True,
    ),
    _rule(
        "image_text_alternatives",
        UiInvariantFamily.STRUCTURE_ACCESSIBILITY,
        "Meaningful images have alternatives and decorative images are hidden.",
        requires_observations=True,
    ),
    _rule(
        "keyboard_activation",
        UiInvariantFamily.STRUCTURE_ACCESSIBILITY,
        "Nonnative controls have keyboard activation.",
        requires_observations=True,
    ),
    _rule(
        "heading_structure",
        UiInvariantFamily.STRUCTURE_ACCESSIBILITY,
        "Heading structure remains intelligible.",
        requires_observations=True,
    ),
)

REQUIRED_INVARIANT_RULE_IDS: Final[tuple[str, ...]] = tuple(
    rule.rule_id for rule in REQUIRED_INVARIANT_RULES
)
REQUIRED_INVARIANT_CHECK_IDS: Final[tuple[str, ...]] = tuple(
    rule.check_id for rule in REQUIRED_INVARIANT_RULES
)
REQUIRED_INVARIANT_PROPERTY_KINDS: Final[frozenset[str]] = frozenset(
    rule.property_kind for rule in REQUIRED_INVARIANT_RULES
)


_VIOLATION_FIELDS: Final = frozenset(
    {
        "check_id",
        "interface",
        "message",
        "path_event_ids",
        "path_state_ids",
        "path_transition_ids",
        "property_kind",
        "rule_id",
        "schema_version",
        "source_bindings",
        "status",
        "subject_ids",
        "violation_id",
    }
)


@dataclass(frozen=True, slots=True)
class UiInvariantViolation:
    """Minimal counterexample evidence (``UiInvariantViolation@1``)."""

    INTERFACE: ClassVar[str] = UI_INVARIANT_VIOLATION_INTERFACE
    SCHEMA_VERSION: ClassVar[str] = UI_INVARIANT_VIOLATION_SCHEMA

    violation_id: str
    rule_id: str
    check_id: str
    property_kind: str
    subject_ids: tuple[str, ...]
    message: str
    status: ConstraintCheckStatus | str = ConstraintCheckStatus.VIOLATED
    path_state_ids: tuple[str, ...] = ()
    path_event_ids: tuple[str, ...] = ()
    path_transition_ids: tuple[str, ...] = ()
    source_bindings: tuple[UiConstraintSourceBinding, ...] = ()
    interface: str = UI_INVARIANT_VIOLATION_INTERFACE
    schema_version: str = UI_INVARIANT_VIOLATION_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "violation_id", _identifier(self.violation_id, "violation_id")
        )
        object.__setattr__(self, "rule_id", _identifier(self.rule_id, "rule_id"))
        object.__setattr__(self, "check_id", _identifier(self.check_id, "check_id"))
        object.__setattr__(
            self, "property_kind", _text(self.property_kind, "property_kind")
        )
        subjects = tuple(_identifier(item, "subject_ids item") for item in self.subject_ids)
        if not subjects:
            raise GuiInvariantEngineError("violation requires at least one subject_id")
        object.__setattr__(self, "subject_ids", subjects)
        object.__setattr__(self, "message", _text(self.message, "message", allow_empty=True))
        status = _schema_enum(self.status, ConstraintCheckStatus, "status")
        if status is not ConstraintCheckStatus.VIOLATED:
            raise GuiInvariantEngineError(
                "UiInvariantViolation.status must be violated"
            )
        object.__setattr__(self, "status", status)
        object.__setattr__(
            self,
            "path_state_ids",
            tuple(_identifier(item, "path_state_ids item") for item in self.path_state_ids),
        )
        object.__setattr__(
            self,
            "path_event_ids",
            tuple(_identifier(item, "path_event_ids item") for item in self.path_event_ids),
        )
        object.__setattr__(
            self,
            "path_transition_ids",
            tuple(
                _identifier(item, "path_transition_ids item")
                for item in self.path_transition_ids
            ),
        )
        bindings = tuple(
            item
            if isinstance(item, UiConstraintSourceBinding)
            else UiConstraintSourceBinding.from_dict(item)
            for item in self.source_bindings
        )
        object.__setattr__(self, "source_bindings", bindings)
        if self.interface != UI_INVARIANT_VIOLATION_INTERFACE:
            raise GuiInvariantEngineError(
                f"unsupported UiInvariantViolation interface: {self.interface!r}"
            )
        if self.schema_version != UI_INVARIANT_VIOLATION_SCHEMA:
            raise GuiInvariantEngineError(
                f"unsupported UiInvariantViolation schema_version: "
                f"{self.schema_version!r}"
            )
        object.__setattr__(self, "interface", UI_INVARIANT_VIOLATION_INTERFACE)
        object.__setattr__(self, "schema_version", UI_INVARIANT_VIOLATION_SCHEMA)

    def to_dict(self) -> dict[str, Any]:
        return {
            "check_id": self.check_id,
            "interface": self.interface,
            "message": self.message,
            "path_event_ids": list(self.path_event_ids),
            "path_state_ids": list(self.path_state_ids),
            "path_transition_ids": list(self.path_transition_ids),
            "property_kind": self.property_kind,
            "rule_id": self.rule_id,
            "schema_version": self.schema_version,
            "source_bindings": [item.to_dict() for item in self.source_bindings],
            "status": self.status.value,
            "subject_ids": list(self.subject_ids),
            "violation_id": self.violation_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any] | Any) -> UiInvariantViolation:
        payload = _mapping(value, "UiInvariantViolation")
        _reject_unknown(payload, _VIOLATION_FIELDS, "UiInvariantViolation")
        return cls(
            violation_id=payload.get("violation_id", ""),
            rule_id=payload.get("rule_id", ""),
            check_id=payload.get("check_id", ""),
            property_kind=payload.get("property_kind", ""),
            subject_ids=tuple(payload.get("subject_ids", ())),
            message=payload.get("message", ""),
            status=payload.get("status", ConstraintCheckStatus.VIOLATED.value),
            path_state_ids=tuple(payload.get("path_state_ids", ())),
            path_event_ids=tuple(payload.get("path_event_ids", ())),
            path_transition_ids=tuple(payload.get("path_transition_ids", ())),
            source_bindings=tuple(payload.get("source_bindings", ())),
            interface=payload.get("interface", UI_INVARIANT_VIOLATION_INTERFACE),
            schema_version=payload.get(
                "schema_version", UI_INVARIANT_VIOLATION_SCHEMA
            ),
        )


_UNSUPPORTED_FIELDS: Final = frozenset(
    {"check_id", "message", "property_kind", "reason", "rule_id", "status"}
)


@dataclass(frozen=True, slots=True)
class UiUnsupportedPropertyMarker:
    """Marker that a required rule stayed unknown / unsupported."""

    rule_id: str
    check_id: str
    property_kind: str
    status: ConstraintCheckStatus | str
    reason: str
    message: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "rule_id", _identifier(self.rule_id, "rule_id"))
        object.__setattr__(self, "check_id", _identifier(self.check_id, "check_id"))
        object.__setattr__(
            self, "property_kind", _text(self.property_kind, "property_kind")
        )
        status = _schema_enum(self.status, ConstraintCheckStatus, "status")
        if status not in _UNKNOWN_STATUSES:
            raise GuiInvariantEngineError(
                "unsupported marker status must be inconclusive/unsupported/skipped/error"
            )
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "reason", _text(self.reason, "reason"))
        object.__setattr__(self, "message", _text(self.message, "message", allow_empty=True))

    def to_dict(self) -> dict[str, Any]:
        return {
            "check_id": self.check_id,
            "message": self.message,
            "property_kind": self.property_kind,
            "reason": self.reason,
            "rule_id": self.rule_id,
            "status": self.status.value,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any] | Any) -> UiUnsupportedPropertyMarker:
        payload = _mapping(value, "UiUnsupportedPropertyMarker")
        _reject_unknown(payload, _UNSUPPORTED_FIELDS, "UiUnsupportedPropertyMarker")
        return cls(
            rule_id=payload.get("rule_id", ""),
            check_id=payload.get("check_id", ""),
            property_kind=payload.get("property_kind", ""),
            status=payload.get("status", ConstraintCheckStatus.INCONCLUSIVE.value),
            reason=payload.get("reason", ""),
            message=payload.get("message", ""),
        )


@dataclass(frozen=True, slots=True)
class UiInvariantCheckResult:
    """Per-rule outcome with pass/fail/unknown semantics."""

    rule: UiInvariantRule
    status: ConstraintCheckStatus
    verdict: UiInvariantVerdict
    message: str
    violation: UiInvariantViolation | None = None
    unsupported: UiUnsupportedPropertyMarker | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "check_id": self.rule.check_id,
            "message": self.message,
            "property_kind": self.rule.property_kind,
            "rule_id": self.rule.rule_id,
            "status": self.status.value,
            "unsupported": None if self.unsupported is None else self.unsupported.to_dict(),
            "verdict": self.verdict.value,
            "violation": None if self.violation is None else self.violation.to_dict(),
        }


_REPORT_FIELDS: Final = frozenset(
    {
        "acceptance_outcome",
        "analysis_classification",
        "application_id",
        "authorizes",
        "bounded",
        "check_results",
        "disclaimer",
        "forbidden_claims_rejected",
        "full_accessibility_proof",
        "full_aesthetic_proof",
        "full_security_proof",
        "interface",
        "machine_id",
        "may_auto_accept",
        "receipt",
        "satisfying_rule_ids",
        "schema_version",
        "screen_id",
        "source_bindings",
        "unsupported_markers",
        "unresolved",
        "verification_status",
        "violations",
        "world_digest",
    }
)


@dataclass(frozen=True, slots=True)
class UiInvariantReport:
    """Aggregate engine result: receipt, violations, and fail-closed gate."""

    INTERFACE: ClassVar[str] = UI_INVARIANT_REPORT_INTERFACE
    SCHEMA_VERSION: ClassVar[str] = UI_INVARIANT_REPORT_SCHEMA

    application_id: str
    screen_id: str
    machine_id: str
    world_digest: str
    receipt: UiConstraintReceipt
    check_results: tuple[UiInvariantCheckResult, ...]
    violations: tuple[UiInvariantViolation, ...]
    unsupported_markers: tuple[UiUnsupportedPropertyMarker, ...]
    satisfying_rule_ids: tuple[str, ...]
    analysis_classification: AnalysisClassification
    verification_status: VerificationStatus
    acceptance_outcome: UiInvariantAcceptanceOutcome
    may_auto_accept: bool
    unresolved: tuple[str, ...]
    source_bindings: tuple[UiConstraintSourceBinding, ...]
    authorizes: bool = False
    bounded: bool = True
    forbidden_claims_rejected: bool = True
    full_accessibility_proof: bool = False
    full_security_proof: bool = False
    full_aesthetic_proof: bool = False
    disclaimer: str = INVARIANT_DISCLAIMER
    interface: str = UI_INVARIANT_REPORT_INTERFACE
    schema_version: str = UI_INVARIANT_REPORT_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(self, "authorizes", False)
        object.__setattr__(self, "full_accessibility_proof", False)
        object.__setattr__(self, "full_security_proof", False)
        object.__setattr__(self, "full_aesthetic_proof", False)
        object.__setattr__(self, "forbidden_claims_rejected", True)
        object.__setattr__(self, "bounded", True)
        object.__setattr__(self, "disclaimer", INVARIANT_DISCLAIMER)
        if self.may_auto_accept and self.acceptance_outcome is not (
            UiInvariantAcceptanceOutcome.ALLOW_AUTOMATIC
        ):
            raise GuiInvariantEngineError(
                "may_auto_accept requires acceptance_outcome=allow_automatic"
            )
        if self.may_auto_accept and self.unresolved:
            raise GuiInvariantEngineError(
                "unresolved premises cannot auto-accept"
            )
        if self.may_auto_accept and self.violations:
            raise GuiInvariantEngineError("violations cannot auto-accept")
        if self.may_auto_accept and self.unsupported_markers:
            raise GuiInvariantEngineError(
                "unknown/unsupported markers cannot auto-accept"
            )

    def result_for(self, property_kind: str) -> UiInvariantCheckResult:
        for item in self.check_results:
            if item.rule.property_kind == property_kind:
                return item
        raise KeyError(property_kind)

    def verdict_for(self, property_kind: str) -> UiInvariantVerdict:
        return self.result_for(property_kind).verdict

    def to_dict(self) -> dict[str, Any]:
        return {
            "acceptance_outcome": self.acceptance_outcome.value,
            "analysis_classification": self.analysis_classification.value,
            "application_id": self.application_id,
            "authorizes": self.authorizes,
            "bounded": self.bounded,
            "check_results": [item.to_dict() for item in self.check_results],
            "disclaimer": self.disclaimer,
            "forbidden_claims_rejected": self.forbidden_claims_rejected,
            "full_accessibility_proof": self.full_accessibility_proof,
            "full_aesthetic_proof": self.full_aesthetic_proof,
            "full_security_proof": self.full_security_proof,
            "interface": self.interface,
            "machine_id": self.machine_id,
            "may_auto_accept": self.may_auto_accept,
            "receipt": self.receipt.to_dict(),
            "satisfying_rule_ids": list(self.satisfying_rule_ids),
            "schema_version": self.schema_version,
            "screen_id": self.screen_id,
            "source_bindings": [item.to_dict() for item in self.source_bindings],
            "unsupported_markers": [item.to_dict() for item in self.unsupported_markers],
            "unresolved": list(self.unresolved),
            "verification_status": self.verification_status.value,
            "violations": [item.to_dict() for item in self.violations],
            "world_digest": self.world_digest,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any] | Any) -> UiInvariantReport:
        """Decode a previously emitted report (receipt + evidence only).

        ``check_results`` are reconstructed from receipt statuses plus stored
        violations / unsupported markers.  The catalog order is authoritative.
        """

        payload = _mapping(value, "UiInvariantReport")
        _reject_unknown(payload, _REPORT_FIELDS, "UiInvariantReport")
        receipt = (
            payload["receipt"]
            if isinstance(payload.get("receipt"), UiConstraintReceipt)
            else UiConstraintReceipt.from_dict(_mapping(payload.get("receipt"), "receipt"))
        )
        violations = tuple(
            item
            if isinstance(item, UiInvariantViolation)
            else UiInvariantViolation.from_dict(item)
            for item in _sequence(payload.get("violations", ()), "violations")
        )
        markers = tuple(
            item
            if isinstance(item, UiUnsupportedPropertyMarker)
            else UiUnsupportedPropertyMarker.from_dict(item)
            for item in _sequence(
                payload.get("unsupported_markers", ()), "unsupported_markers"
            )
        )
        stored_results = list(
            _sequence(payload.get("check_results", ()), "check_results")
        )
        results_by_check = {}
        for item in stored_results:
            if isinstance(item, UiInvariantCheckResult):
                results_by_check[item.rule.check_id] = item
                continue
            mapping = _mapping(item, "check_results item")
            results_by_check[str(mapping.get("check_id", ""))] = mapping
        status_by_check = {
            check_id: status
            for check_id, status in zip(
                receipt.check_ids, receipt.statuses, strict=True
            )
        }
        reconstructed: list[UiInvariantCheckResult] = []
        for rule in REQUIRED_INVARIANT_RULES:
            stored = results_by_check.get(rule.check_id)
            message = ""
            if isinstance(stored, UiInvariantCheckResult):
                reconstructed.append(stored)
                continue
            if isinstance(stored, Mapping):
                message = str(stored.get("message", ""))
                raw_status = stored.get("status")
                if raw_status:
                    status = parse_enum(
                        raw_status, ConstraintCheckStatus, "check_results.status"
                    )
                else:
                    status = status_by_check.get(
                        rule.check_id, ConstraintCheckStatus.INCONCLUSIVE
                    )
            else:
                status = status_by_check.get(
                    rule.check_id, ConstraintCheckStatus.INCONCLUSIVE
                )
            violation = next(
                (item for item in violations if item.check_id == rule.check_id), None
            )
            marker = next(
                (item for item in markers if item.check_id == rule.check_id), None
            )
            reconstructed.append(
                UiInvariantCheckResult(
                    rule=rule,
                    status=status,
                    verdict=_status_to_verdict(status),
                    message=message or (marker.message if marker else ""),
                    violation=violation,
                    unsupported=marker,
                )
            )
        return cls(
            application_id=payload.get("application_id", receipt.application_id),
            screen_id=payload.get("screen_id", receipt.screen_id),
            machine_id=payload.get("machine_id", ""),
            world_digest=payload.get("world_digest", ""),
            receipt=receipt,
            check_results=tuple(reconstructed),
            violations=violations,
            unsupported_markers=markers,
            satisfying_rule_ids=tuple(payload.get("satisfying_rule_ids", ())),
            analysis_classification=_schema_enum(
                payload.get("analysis_classification", receipt.analysis_classification),
                AnalysisClassification,
                "analysis_classification",
            ),
            verification_status=_schema_enum(
                payload.get("verification_status", receipt.verification_status),
                VerificationStatus,
                "verification_status",
            ),
            acceptance_outcome=_enum(
                payload.get("acceptance_outcome", "block_automatic"),
                UiInvariantAcceptanceOutcome,
                "acceptance_outcome",
            ),
            may_auto_accept=_bool(payload.get("may_auto_accept", False), "may_auto_accept"),
            unresolved=tuple(payload.get("unresolved", ())),
            source_bindings=tuple(
                item
                if isinstance(item, UiConstraintSourceBinding)
                else UiConstraintSourceBinding.from_dict(item)
                for item in payload.get("source_bindings", ())
            ),
            interface=payload.get("interface", UI_INVARIANT_REPORT_INTERFACE),
            schema_version=payload.get("schema_version", UI_INVARIANT_REPORT_SCHEMA),
        )


# ---------------------------------------------------------------------------
# Graph helpers (engine-local; used when adapter is not the primary checker)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _GraphIndex:
    states_by_id: Mapping[str, UiStateDefinition]
    events_by_id: Mapping[str, UiEventDefinition]
    outgoing: Mapping[str, tuple[UiTransitionDefinition, ...]]
    reachable: frozenset[str]


def _index_graph(world: UiInvariantWorld) -> _GraphIndex:
    states_by_id: dict[str, UiStateDefinition] = {}
    for state in world.states:
        states_by_id.setdefault(state.state_id, state)
    events_by_id: dict[str, UiEventDefinition] = {}
    for event in world.events:
        events_by_id.setdefault(event.event_id, event)
    outgoing: dict[str, list[UiTransitionDefinition]] = {
        state_id: [] for state_id in states_by_id
    }
    for transition in world.transitions:
        outgoing.setdefault(transition.from_state_id, []).append(transition)
    frozen_outgoing = {key: tuple(value) for key, value in outgoing.items()}
    reachable: set[str] = set()
    initial = world.initial_state_id
    if initial and initial in states_by_id:
        queue: deque[str] = deque([initial])
        reachable.add(initial)
        while queue:
            current = queue.popleft()
            for transition in frozen_outgoing.get(current, ()):
                destination = transition.to_state_id
                if destination in states_by_id and destination not in reachable:
                    reachable.add(destination)
                    queue.append(destination)
    return _GraphIndex(
        states_by_id=states_by_id,
        events_by_id=events_by_id,
        outgoing=frozen_outgoing,
        reachable=frozenset(reachable),
    )


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _LocalOutcome:
    status: ConstraintCheckStatus
    message: str
    subject_ids: tuple[str, ...] = ()
    path_state_ids: tuple[str, ...] = ()
    path_event_ids: tuple[str, ...] = ()
    path_transition_ids: tuple[str, ...] = ()
    reason: str = ""


class UiInvariantEngine:
    """``UiInvariantEngine@1`` — bounded UI invariant catalog runner.

    The engine never:

    * authorizes host actions or treats a receipt as permission;
    * auto-accepts when any required rule is fail or unknown;
    * auto-accepts unresolved, opaque, or heuristic premises;
    * claims complete accessibility, complete security, or beauty;
    * consults aesthetic scores or backend authorization oracles.
    """

    INTERFACE: ClassVar[str] = UI_INVARIANT_ENGINE_INTERFACE
    SCHEMA_VERSION: ClassVar[str] = UI_INVARIANT_ENGINE_SCHEMA
    VERSION: ClassVar[str] = UI_INVARIANT_ENGINE_VERSION

    def __init__(self, *, adapter: GuiFormalAdapter | None = None) -> None:
        self._adapter = adapter or create_gui_formal_adapter()

    @property
    def required_rules(self) -> tuple[UiInvariantRule, ...]:
        return REQUIRED_INVARIANT_RULES

    def check(self, world: UiInvariantWorld | Mapping[str, Any]) -> UiInvariantReport:
        if not isinstance(world, UiInvariantWorld):
            world = UiInvariantWorld.from_dict(_mapping(world, "world"))
        results: list[UiInvariantCheckResult] = []
        for rule in REQUIRED_INVARIANT_RULES:
            results.append(self._evaluate_rule(rule, world))
        return self._assemble_report(world, tuple(results))

    def _evaluate_rule(
        self, rule: UiInvariantRule, world: UiInvariantWorld
    ) -> UiInvariantCheckResult:
        if rule.property_kind in FORBIDDEN_CLAIM_KINDS:
            return self._unknown_result(
                rule,
                ConstraintCheckStatus.UNSUPPORTED,
                f"property_kind {rule.property_kind!r} is forbidden and cannot be proved",
                reason="forbidden_claim",
            )
        if (
            rule.adapter_property is not None
            and rule.property_kind not in _LOCAL_CHECKERS
        ):
            return self._from_adapter(rule, world)
        checker = _LOCAL_CHECKERS.get(rule.property_kind)
        if checker is None:
            return self._unknown_result(
                rule,
                ConstraintCheckStatus.UNSUPPORTED,
                f"unsupported property_kind {rule.property_kind}",
                reason="unsupported_property",
            )
        outcome = checker(world, _index_graph(world))
        return self._from_local(rule, world, outcome)

    def _from_adapter(
        self, rule: UiInvariantRule, world: UiInvariantWorld
    ) -> UiInvariantCheckResult:
        assert rule.adapter_property is not None
        premises: dict[str, Any] = {}
        if rule.adapter_property is UiConstraintPropertyKind.REACHABLE_REQUIRED_ACTION:
            premises["action_state_ids"] = dict(world.action_state_ids)
        try:
            problem = self._adapter.build_problem(
                problem_id=f"problem:{rule.property_kind}",
                check_id=rule.check_id,
                property_kind=rule.adapter_property,
                application_id=world.application_id,
                screen_id=world.screen_id,
                machine_id=world.machine_id,
                initial_state_id=world.initial_state_id,
                states=world.states,
                events=world.events,
                transitions=world.transitions,
                claim_kind="bounded_ui_invariant",
                analysis_classification=world.analysis_classification,
                async_effects=world.async_effects,
                required_action_ids=world.required_action_ids,
                premises=premises,
                source_bindings=world.source_bindings,
                unresolved=world.unresolved
                if world.analysis_classification
                in {AnalysisClassification.OPAQUE, AnalysisClassification.HEURISTIC}
                else (),
            )
            result = self._adapter.solve(problem)
        except Exception as error:  # noqa: BLE001 - fail closed
            return self._unknown_result(
                rule,
                ConstraintCheckStatus.ERROR,
                f"adapter evaluation failed: {error}",
                reason="adapter_error",
            )
        return self._from_adapter_result(rule, world, result)

    def _from_adapter_result(
        self,
        rule: UiInvariantRule,
        world: UiInvariantWorld,
        result: UiConstraintResult,
    ) -> UiInvariantCheckResult:
        if result.kind is UiConstraintResultKind.COUNTEREXAMPLE or (
            result.status is ConstraintCheckStatus.VIOLATED
        ):
            cex = result.counterexample
            violation = UiInvariantViolation(
                violation_id=(
                    cex.counterexample_id
                    if cex is not None
                    else _digest_id("violation", {"check": rule.check_id})
                ),
                rule_id=rule.rule_id,
                check_id=rule.check_id,
                property_kind=rule.property_kind,
                subject_ids=(
                    cex.subject_ids if cex is not None else (world.machine_id,)
                ),
                message=result.message or (cex.message if cex is not None else ""),
                path_state_ids=cex.path_state_ids if cex is not None else (),
                path_event_ids=cex.path_event_ids if cex is not None else (),
                path_transition_ids=cex.path_transition_ids if cex is not None else (),
                source_bindings=world.source_bindings,
            )
            return UiInvariantCheckResult(
                rule=rule,
                status=ConstraintCheckStatus.VIOLATED,
                verdict=UiInvariantVerdict.FAIL,
                message=result.message,
                violation=violation,
            )
        if result.status is ConstraintCheckStatus.SATISFIED:
            return UiInvariantCheckResult(
                rule=rule,
                status=ConstraintCheckStatus.SATISFIED,
                verdict=UiInvariantVerdict.PASS,
                message=result.message,
            )
        status = result.status
        if status not in _UNKNOWN_STATUSES:
            status = ConstraintCheckStatus.INCONCLUSIVE
        return self._unknown_result(
            rule,
            status,
            result.message,
            reason="incomplete_premises"
            if status is ConstraintCheckStatus.INCONCLUSIVE
            else status.value,
        )

    def _from_local(
        self,
        rule: UiInvariantRule,
        world: UiInvariantWorld,
        outcome: _LocalOutcome,
    ) -> UiInvariantCheckResult:
        if outcome.status is ConstraintCheckStatus.VIOLATED:
            subjects = outcome.subject_ids or (world.machine_id,)
            violation = UiInvariantViolation(
                violation_id=_digest_id(
                    "violation",
                    {
                        "check": rule.check_id,
                        "subjects": list(subjects),
                        "message": outcome.message,
                    },
                ),
                rule_id=rule.rule_id,
                check_id=rule.check_id,
                property_kind=rule.property_kind,
                subject_ids=subjects,
                message=outcome.message,
                path_state_ids=outcome.path_state_ids,
                path_event_ids=outcome.path_event_ids,
                path_transition_ids=outcome.path_transition_ids,
                source_bindings=world.source_bindings,
            )
            return UiInvariantCheckResult(
                rule=rule,
                status=ConstraintCheckStatus.VIOLATED,
                verdict=UiInvariantVerdict.FAIL,
                message=outcome.message,
                violation=violation,
            )
        if outcome.status is ConstraintCheckStatus.SATISFIED:
            return UiInvariantCheckResult(
                rule=rule,
                status=ConstraintCheckStatus.SATISFIED,
                verdict=UiInvariantVerdict.PASS,
                message=outcome.message,
            )
        status = (
            outcome.status
            if outcome.status in _UNKNOWN_STATUSES
            else ConstraintCheckStatus.INCONCLUSIVE
        )
        return self._unknown_result(
            rule,
            status,
            outcome.message,
            reason=outcome.reason or "incomplete_premises",
        )

    def _unknown_result(
        self,
        rule: UiInvariantRule,
        status: ConstraintCheckStatus,
        message: str,
        *,
        reason: str,
    ) -> UiInvariantCheckResult:
        marker = UiUnsupportedPropertyMarker(
            rule_id=rule.rule_id,
            check_id=rule.check_id,
            property_kind=rule.property_kind,
            status=status,
            reason=reason,
            message=message,
        )
        return UiInvariantCheckResult(
            rule=rule,
            status=status,
            verdict=UiInvariantVerdict.UNKNOWN,
            message=message,
            unsupported=marker,
        )

    def _assemble_report(
        self,
        world: UiInvariantWorld,
        results: tuple[UiInvariantCheckResult, ...],
    ) -> UiInvariantReport:
        if len(results) != len(REQUIRED_INVARIANT_RULES):
            raise GuiInvariantEngineError(
                "engine must emit exactly one result per required rule"
            )
        check_ids = [item.rule.check_id for item in results]
        if check_ids != list(REQUIRED_INVARIANT_CHECK_IDS):
            raise GuiInvariantEngineError("check_ids must follow the required catalog order")
        # UiConstraintReceipt@1 forbids duplicate status values and requires
        # statuses to be parallel with check_ids. The full per-rule catalog
        # lives on check_results; the receipt is a unique-status projection.
        receipt_check_ids: list[str] = []
        receipt_statuses: list[ConstraintCheckStatus] = []
        seen_statuses: set[ConstraintCheckStatus] = set()
        for item in results:
            if item.status in seen_statuses:
                continue
            seen_statuses.add(item.status)
            receipt_check_ids.append(item.rule.check_id)
            receipt_statuses.append(item.status)
        violations = tuple(item.violation for item in results if item.violation is not None)
        markers = tuple(
            item.unsupported for item in results if item.unsupported is not None
        )
        satisfying = tuple(
            item.rule.rule_id
            for item in results
            if item.status is ConstraintCheckStatus.SATISFIED
        )
        uncertain_analysis = world.analysis_classification in {
            AnalysisClassification.HEURISTIC,
            AnalysisClassification.OPAQUE,
        }
        all_satisfied = all(
            item.status is ConstraintCheckStatus.SATISFIED for item in results
        )
        may_auto_accept = (
            all_satisfied
            and not world.unresolved
            and not uncertain_analysis
            and world.analysis_classification is AnalysisClassification.EXACT
            and not violations
            and not markers
        )
        acceptance = (
            UiInvariantAcceptanceOutcome.ALLOW_AUTOMATIC
            if may_auto_accept
            else UiInvariantAcceptanceOutcome.BLOCK_AUTOMATIC
        )
        if any(item.status is ConstraintCheckStatus.VIOLATED for item in results):
            verification = VerificationStatus.INVALID
        elif may_auto_accept:
            verification = VerificationStatus.STRUCTURALLY_VALID
        else:
            verification = VerificationStatus.UNVERIFIED
        receipt = UiConstraintReceipt(
            receipt_id=_digest_id(
                "receipt",
                {
                    "application_id": world.application_id,
                    "screen_id": world.screen_id,
                    "check_ids": receipt_check_ids,
                    "statuses": [item.value for item in receipt_statuses],
                    "revision": world.repository_revision,
                },
            ),
            application_id=world.application_id,
            screen_id=world.screen_id,
            repository_revision=world.repository_revision,
            check_ids=receipt_check_ids,
            statuses=[item.value for item in receipt_statuses],
            violated_check_ids=[
                check_id
                for check_id, status in zip(
                    receipt_check_ids, receipt_statuses, strict=True
                )
                if status is ConstraintCheckStatus.VIOLATED
            ],
            unsupported_check_ids=[
                check_id
                for check_id, status in zip(
                    receipt_check_ids, receipt_statuses, strict=True
                )
                if status is ConstraintCheckStatus.UNSUPPORTED
            ],
            solver_id=ENGINE_SOLVER_ID,
            evidence_level=EvidenceLevel.STRUCTURAL.value,
            analysis_classification=world.analysis_classification.value,
            verification_status=verification.value,
            interface=UI_CONSTRAINT_RECEIPT_INTERFACE,
            schema_version=UI_CONSTRAINT_RECEIPT_SCHEMA,
        )
        world_digest = f"sha256:{_sha256_hex(_canonical_bytes(world.to_dict()))}"
        return UiInvariantReport(
            application_id=world.application_id,
            screen_id=world.screen_id,
            machine_id=world.machine_id,
            world_digest=world_digest,
            receipt=receipt,
            check_results=results,
            violations=violations,
            unsupported_markers=markers,
            satisfying_rule_ids=satisfying,
            analysis_classification=world.analysis_classification,
            verification_status=verification,
            acceptance_outcome=acceptance,
            may_auto_accept=may_auto_accept,
            unresolved=world.unresolved,
            source_bindings=world.source_bindings,
        )


def create_ui_invariant_engine(
    *, adapter: GuiFormalAdapter | None = None
) -> UiInvariantEngine:
    """Factory for ``UiInvariantEngine@1``."""

    return UiInvariantEngine(adapter=adapter)


# ---------------------------------------------------------------------------
# Local checkers
# ---------------------------------------------------------------------------


def _unknown(message: str, *, reason: str = "incomplete_premises") -> _LocalOutcome:
    return _LocalOutcome(
        status=ConstraintCheckStatus.INCONCLUSIVE,
        message=message,
        reason=reason,
    )


def _pass(message: str) -> _LocalOutcome:
    return _LocalOutcome(status=ConstraintCheckStatus.SATISFIED, message=message)


def _fail(
    message: str,
    *subject_ids: str,
    path_state_ids: tuple[str, ...] = (),
    path_event_ids: tuple[str, ...] = (),
    path_transition_ids: tuple[str, ...] = (),
) -> _LocalOutcome:
    return _LocalOutcome(
        status=ConstraintCheckStatus.VIOLATED,
        message=message,
        subject_ids=subject_ids,
        path_state_ids=path_state_ids,
        path_event_ids=path_event_ids,
        path_transition_ids=path_transition_ids,
    )


def _check_event_outcome_coverage(
    world: UiInvariantWorld, graph: _GraphIndex
) -> _LocalOutcome:
    """Per-state coverage when declared; otherwise machine-level outcomes."""

    if world.state_event_ids is not None:
        for state_id, event_ids in world.state_event_ids.items():
            if state_id not in graph.states_by_id:
                return _fail(
                    f"state_event_ids references undefined state {state_id}",
                    state_id,
                    path_state_ids=(state_id,),
                )
            if state_id not in graph.reachable:
                continue
            state = graph.states_by_id[state_id]
            if state.is_terminal:
                continue
            outgoing_events = {
                transition.event_id for transition in graph.outgoing.get(state_id, ())
            }
            for event_id in event_ids:
                if event_id not in graph.events_by_id:
                    return _fail(
                        f"state {state_id} declares undefined event {event_id}",
                        state_id,
                        event_id,
                        path_state_ids=(state_id,),
                        path_event_ids=(event_id,),
                    )
                if event_id not in outgoing_events:
                    return _fail(
                        f"reachable state {state_id} has no outcome or no-op for "
                        f"declared event {event_id}",
                        state_id,
                        event_id,
                        path_state_ids=(state_id,),
                        path_event_ids=(event_id,),
                    )
        missing_reachable = sorted(
            state_id
            for state_id in graph.reachable
            if state_id not in world.state_event_ids
            and not graph.states_by_id[state_id].is_terminal
        )
        if missing_reachable:
            return _unknown(
                "state_event_ids omits reachable nonterminal states: "
                + ", ".join(missing_reachable)
            )
        return _pass(
            "every declared event in a reachable state has an explicit outcome or no-op"
        )

    events_with_outcomes = {transition.event_id for transition in world.transitions}
    declared = set(graph.events_by_id)
    floating = sorted(declared - events_with_outcomes)
    if floating:
        return _unknown(
            "declared events without outcomes remain unknown "
            f"(not treated as no-ops): {', '.join(floating)}"
        )
    if not declared:
        return _unknown("event_outcome_coverage requires declared events")
    return _pass("every declared event has at least one explicit outcome or no-op")


def _check_confirmation_bound_action(
    world: UiInvariantWorld, graph: _GraphIndex
) -> _LocalOutcome:
    if not world.action_bindings:
        return _unknown(
            "confirmation_bound_action requires action_bindings observations"
        )
    destructive = [item for item in world.action_bindings if item.is_destructive]
    if not destructive:
        return _pass("no destructive actions declared under observed bindings")
    confirmations = {item.confirmation_id: item for item in world.confirmations}
    for binding in destructive:
        if not binding.requires_confirmation or not binding.confirmation_id:
            return _fail(
                f"destructive action {binding.action_id} lacks bound confirmation",
                binding.action_id,
            )
        confirmation = confirmations.get(binding.confirmation_id)
        if confirmation is None:
            return _fail(
                f"destructive action {binding.action_id} confirmation "
                f"{binding.confirmation_id} is not observed",
                binding.action_id,
                binding.confirmation_id,
            )
        if confirmation.action_id != binding.action_id:
            return _fail(
                f"confirmation {confirmation.confirmation_id} is bound to "
                f"{confirmation.action_id}, not {binding.action_id}",
                binding.action_id,
                confirmation.confirmation_id,
            )
        if not confirmation.argument_digest:
            return _fail(
                f"confirmation {confirmation.confirmation_id} lacks argument_digest",
                binding.action_id,
                confirmation.confirmation_id,
            )
    return _pass(
        "destructive actions bind exact confirmation identifiers and argument digests"
    )


def _check_presentation_no_credentials(
    world: UiInvariantWorld, graph: _GraphIndex
) -> _LocalOutcome:
    if not world.presentation_components:
        return _unknown(
            "presentation_no_credentials requires presentation_components observations"
        )
    for item in world.presentation_components:
        if item.is_presentation and item.accesses_credentials:
            return _fail(
                f"presentation component {item.component_id} accesses credentials",
                item.component_id,
            )
    return _pass("presentation components do not access credentials")


def _check_policy_not_browser_authoritative(
    world: UiInvariantWorld, graph: _GraphIndex
) -> _LocalOutcome:
    if world.policy is None and not world.runtime_observations:
        return _unknown(
            "policy_not_browser_authoritative requires policy or runtime observations"
        )
    if world.policy is not None:
        if world.policy.browser_policy_authoritative:
            return _fail(
                "browser policy output must not be authoritative",
                "policy:browser",
            )
        if not world.policy.host_authorization_authoritative:
            return _fail(
                "host authorization must remain authoritative for policy checks",
                "policy:host",
            )
    for item in world.runtime_observations:
        if item.browser_policy_authoritative_claim:
            return _fail(
                f"runtime observation for {item.action_id} treats browser policy "
                "as authoritative",
                item.action_id,
            )
    return _pass(
        "browser policy is non-authoritative under declared premises "
        "(not a complete security proof)"
    )


def _check_no_hidden_dispatch(
    world: UiInvariantWorld, graph: _GraphIndex
) -> _LocalOutcome:
    if not world.action_bindings:
        return _unknown("no_hidden_dispatch requires action_bindings observations")
    runtime = {item.action_id: item for item in world.runtime_observations}
    if not runtime:
        return _unknown("no_hidden_dispatch requires runtime_observations")
    for binding in world.action_bindings:
        observation = runtime.get(binding.action_id)
        if observation is None:
            return _unknown(
                f"missing runtime observation for action {binding.action_id}"
            )
        blocked = (
            observation.deontic_status
            in {UiDeonticStatus.PROHIBITED, UiDeonticStatus.UNAVAILABLE}
            or observation.presentation_visibility
            in {UiPresentationVisibility.DISABLED, UiPresentationVisibility.HIDDEN}
        )
        if not blocked:
            if observation.has_hidden_dispatch_path:
                return _fail(
                    f"action {binding.action_id} has a hidden dispatch path",
                    binding.action_id,
                )
            continue
        if observation.is_dispatchable or observation.has_hidden_dispatch_path:
            return _fail(
                f"prohibited/disabled action {binding.action_id} remains dispatchable",
                binding.action_id,
            )
    return _pass("prohibited and disabled actions have no executable hidden dispatch path")


def _check_single_action_binding(
    world: UiInvariantWorld, graph: _GraphIndex
) -> _LocalOutcome:
    if not world.action_bindings:
        return _unknown("single_action_binding requires action_bindings observations")
    seen: dict[str, UiActionBinding] = {}
    for binding in world.action_bindings:
        if binding.action_id in seen:
            other = seen[binding.action_id]
            if (other.method, other.schema_id) != (binding.method, binding.schema_id):
                return _fail(
                    f"displayed action {binding.action_id} resolves to multiple "
                    "method/schema targets",
                    binding.action_id,
                )
        seen[binding.action_id] = binding
        if not binding.method or not binding.schema_id:
            return _fail(
                f"displayed action {binding.action_id} is missing method or schema",
                binding.action_id,
            )
    runtime = {item.action_id: item for item in world.runtime_observations}
    for binding in world.action_bindings:
        observation = runtime.get(binding.action_id)
        if observation is None:
            continue
        if observation.resolution in {
            UiBindingResolution.AMBIGUOUS,
            UiBindingResolution.DYNAMIC,
            UiBindingResolution.UNRESOLVED,
        }:
            return _unknown(
                f"action {binding.action_id} binding resolution is "
                f"{observation.resolution.value}"
            )
        if observation.target_count != 1:
            return _fail(
                f"displayed action {binding.action_id} has {observation.target_count} "
                "method/schema targets",
                binding.action_id,
            )
    return _pass("displayed actions resolve to exactly one intended method and schema")


def _check_runtime_action_reevaluation(
    world: UiInvariantWorld, graph: _GraphIndex
) -> _LocalOutcome:
    if not world.action_bindings:
        return _unknown(
            "runtime_action_reevaluation requires action_bindings observations"
        )
    if not world.runtime_observations:
        return _unknown(
            "runtime_action_reevaluation requires runtime_observations"
        )
    runtime = {item.action_id: item for item in world.runtime_observations}
    for binding in world.action_bindings:
        observation = runtime.get(binding.action_id)
        if observation is None:
            return _unknown(
                f"missing runtime observation for action {binding.action_id}"
            )
        if not observation.runtime_reevaluated:
            return _fail(
                f"action {binding.action_id} was not re-evaluated at runtime",
                binding.action_id,
            )
        if observation.current_method != binding.method:
            return _fail(
                f"runtime method for {binding.action_id} disagrees with binding",
                binding.action_id,
            )
        if observation.current_schema_id != binding.schema_id:
            return _fail(
                f"runtime schema for {binding.action_id} disagrees with binding",
                binding.action_id,
            )
    return _pass("current action and arguments are re-evaluated at runtime")


def _check_stale_policy_cannot_authorize(
    world: UiInvariantWorld, graph: _GraphIndex
) -> _LocalOutcome:
    if not world.action_bindings:
        return _unknown(
            "stale_policy_cannot_authorize requires action_bindings observations"
        )
    if not world.runtime_observations:
        return _unknown(
            "stale_policy_cannot_authorize requires runtime_observations"
        )
    runtime = {item.action_id: item for item in world.runtime_observations}
    for binding in world.action_bindings:
        observation = runtime.get(binding.action_id)
        if observation is None:
            return _unknown(
                f"missing runtime observation for action {binding.action_id}"
            )
        if not observation.policy_fresh:
            return _fail(
                f"stale policy decision cannot authorize action {binding.action_id}",
                binding.action_id,
            )
        if observation.browser_policy_authoritative_claim:
            return _fail(
                f"browser policy cannot authorize action {binding.action_id}",
                binding.action_id,
            )
    return _pass("stale or browser policy decisions cannot authorize current actions")


def _check_form_accessible_names(
    world: UiInvariantWorld, graph: _GraphIndex
) -> _LocalOutcome:
    if not world.form_inputs:
        return _unknown("form_accessible_names requires form_inputs observations")
    for item in world.form_inputs:
        if not item.accessible_name.strip():
            return _fail(f"input {item.input_id} lacks accessible_name", item.input_id)
    return _pass(
        "declared form inputs expose accessible names "
        "(bounded structural check; not complete accessibility)"
    )


def _check_form_required_state(
    world: UiInvariantWorld, graph: _GraphIndex
) -> _LocalOutcome:
    if not world.form_inputs:
        return _unknown("form_required_state requires form_inputs observations")
    required_inputs = [item for item in world.form_inputs if item.required]
    if not required_inputs:
        return _pass("no required inputs declared under observed form_inputs")
    for item in required_inputs:
        if item.exposes_required_state is None:
            return _unknown(
                f"required input {item.input_id} has no required-state observation"
            )
        if item.exposes_required_state is False:
            return _fail(
                f"required input {item.input_id} does not expose required-state semantics",
                item.input_id,
            )
    return _pass("required inputs expose required-state semantics")


def _check_form_error_association(
    world: UiInvariantWorld, graph: _GraphIndex
) -> _LocalOutcome:
    if not world.form_inputs:
        return _unknown("form_error_association requires form_inputs observations")
    if not world.validation_errors:
        return _pass("no validation errors to associate")
    inputs = {item.input_id: item for item in world.form_inputs}
    for error in world.validation_errors:
        field = inputs.get(error.field_id)
        if field is None:
            return _fail(
                f"validation error {error.error_id} references unknown field "
                f"{error.field_id}",
                error.error_id,
                error.field_id,
            )
        if error.error_id not in field.associated_error_ids:
            return _fail(
                f"validation error {error.error_id} is not associated with field "
                f"{error.field_id}",
                error.error_id,
                error.field_id,
            )
    return _pass("validation errors associate with the relevant field")


def _check_form_submission_validation(
    world: UiInvariantWorld, graph: _GraphIndex
) -> _LocalOutcome:
    if world.form_submission is None:
        return _unknown(
            "form_submission_validation requires form_submission observations"
        )
    if world.form_submission.discards_validation_failure:
        return _fail(
            "submission silently discards validation failure",
            "form:submission",
        )
    return _pass("submission does not silently discard validation failure")


def _check_form_success_after_effect(
    world: UiInvariantWorld, graph: _GraphIndex
) -> _LocalOutcome:
    if world.form_submission is None:
        return _unknown(
            "form_success_after_effect requires form_submission observations"
        )
    if not world.form_submission.success_follows_confirmed_effect:
        return _fail(
            "success does not follow confirmed effect completion",
            "form:success",
        )
    return _pass("success follows confirmed effect completion")


_MODAL_FLAGS: Final[tuple[str, ...]] = (
    "opens_moves_focus_inside",
    "tab_contained",
    "escape_or_cancel_defined",
    "close_restores_focus",
    "hidden_not_focusable",
)


def _check_modal_focus_lifecycle(
    world: UiInvariantWorld, graph: _GraphIndex
) -> _LocalOutcome:
    if not world.modal_focus:
        return _unknown("modal_focus_lifecycle requires modal_focus observations")
    for modal in world.modal_focus:
        for flag in _MODAL_FLAGS:
            value = getattr(modal, flag)
            if value is None:
                return _unknown(f"modal {modal.modal_id} missing {flag} observation")
            if value is False:
                return _fail(
                    f"modal focus obligation failed: {flag}",
                    modal.modal_id,
                    flag,
                )
    return _pass(
        "declared modal focus lifecycle obligations hold "
        "(bounded structural check; not complete accessibility)"
    )


def _check_unique_dom_ids(world: UiInvariantWorld, graph: _GraphIndex) -> _LocalOutcome:
    if not world.dom_nodes:
        return _unknown("unique_dom_ids requires dom_nodes observations")
    seen: dict[str, str] = {}
    for node in world.dom_nodes:
        if not node.dom_id:
            continue
        previous = seen.get(node.dom_id)
        if previous is not None:
            return _fail(
                f"duplicate DOM id {node.dom_id!r} on {previous} and {node.node_id}",
                node.node_id,
                previous,
            )
        seen[node.dom_id] = node.node_id
    return _pass("rendered nodes have unique DOM ids")


def _check_interactive_accessible_names(
    world: UiInvariantWorld, graph: _GraphIndex
) -> _LocalOutcome:
    if not world.dom_nodes:
        return _unknown(
            "interactive_accessible_names requires dom_nodes observations"
        )
    interactive = [node for node in world.dom_nodes if node.interactive]
    if not interactive:
        return _pass("no interactive controls declared under observed DOM nodes")
    for node in interactive:
        if not node.accessible_name.strip():
            return _fail(
                f"interactive control {node.node_id} lacks accessible_name",
                node.node_id,
            )
    return _pass(
        "interactive controls have accessible names "
        "(bounded structural check; not complete accessibility)"
    )


def _check_image_text_alternatives(
    world: UiInvariantWorld, graph: _GraphIndex
) -> _LocalOutcome:
    if not world.dom_nodes:
        return _unknown("image_text_alternatives requires dom_nodes observations")
    images = [
        node for node in world.dom_nodes if node.image_kind is not UiImageKind.NONE
    ]
    if not images:
        return _pass("no images declared under observed DOM nodes")
    for node in images:
        if node.image_kind is UiImageKind.MEANINGFUL:
            if node.has_text_alternative is None:
                return _unknown(
                    f"meaningful image {node.node_id} has no text-alternative observation"
                )
            if not node.has_text_alternative:
                return _fail(
                    f"meaningful image {node.node_id} lacks a text alternative",
                    node.node_id,
                )
        elif node.image_kind is UiImageKind.DECORATIVE:
            if node.decorative_hidden is None:
                return _unknown(
                    f"decorative image {node.node_id} has no hidden observation"
                )
            if not node.decorative_hidden:
                return _fail(
                    f"decorative image {node.node_id} is not hidden from assistive tech",
                    node.node_id,
                )
    return _pass(
        "meaningful images have alternatives and decorative images are hidden "
        "(bounded structural check; not complete accessibility)"
    )


def _check_keyboard_activation(
    world: UiInvariantWorld, graph: _GraphIndex
) -> _LocalOutcome:
    if not world.dom_nodes:
        return _unknown("keyboard_activation requires dom_nodes observations")
    nonnative = [
        node
        for node in world.dom_nodes
        if node.interactive and not node.native_control
    ]
    if not nonnative:
        return _pass("no nonnative interactive controls declared")
    for node in nonnative:
        if node.has_keyboard_activation is None:
            return _unknown(
                f"nonnative control {node.node_id} has no keyboard-activation observation"
            )
        if not node.has_keyboard_activation:
            return _fail(
                f"nonnative control {node.node_id} lacks keyboard activation",
                node.node_id,
            )
    return _pass("nonnative controls have keyboard activation")


def _check_heading_structure(
    world: UiInvariantWorld, graph: _GraphIndex
) -> _LocalOutcome:
    if not world.dom_nodes:
        return _unknown("heading_structure requires dom_nodes observations")
    headings = [node for node in world.dom_nodes if node.heading_level is not None]
    if not headings:
        return _unknown(
            "heading_structure has no heading-level observations under declared DOM nodes"
        )
    first = headings[0].heading_level
    assert first is not None
    if first > 1:
        return _fail(
            f"heading structure skips level 1 (first heading is h{first})",
            headings[0].node_id,
        )
    previous = first
    for node in headings[1:]:
        level = node.heading_level
        assert level is not None
        if level > previous + 1:
            return _fail(
                f"heading structure skips from h{previous} to h{level} at {node.node_id}",
                node.node_id,
            )
        previous = level
    return _pass(
        "heading structure remains intelligible "
        "(bounded structural check; not complete accessibility)"
    )


_LOCAL_CHECKERS: Final[
    dict[str, Callable[[UiInvariantWorld, _GraphIndex], _LocalOutcome]]
] = {
    "event_outcome_coverage": _check_event_outcome_coverage,
    "confirmation_bound_action": _check_confirmation_bound_action,
    "presentation_no_credentials": _check_presentation_no_credentials,
    "policy_not_browser_authoritative": _check_policy_not_browser_authoritative,
    "no_hidden_dispatch": _check_no_hidden_dispatch,
    "single_action_binding": _check_single_action_binding,
    "runtime_action_reevaluation": _check_runtime_action_reevaluation,
    "stale_policy_cannot_authorize": _check_stale_policy_cannot_authorize,
    "form_accessible_names": _check_form_accessible_names,
    "form_required_state": _check_form_required_state,
    "form_error_association": _check_form_error_association,
    "form_submission_validation": _check_form_submission_validation,
    "form_success_after_effect": _check_form_success_after_effect,
    "modal_focus_lifecycle": _check_modal_focus_lifecycle,
    "unique_dom_ids": _check_unique_dom_ids,
    "interactive_accessible_names": _check_interactive_accessible_names,
    "image_text_alternatives": _check_image_text_alternatives,
    "keyboard_activation": _check_keyboard_activation,
    "heading_structure": _check_heading_structure,
}


__all__ = [
    "CANONICAL_JSON_PROFILE",
    "ENGINE_AUTHORIZES_ACTIONS",
    "ENGINE_SOLVER_ID",
    "FORBIDDEN_CLAIM_KINDS",
    "FULL_ACCESSIBILITY_PROOF",
    "FULL_AESTHETIC_PROOF",
    "FULL_SECURITY_PROOF",
    "INVARIANT_DISCLAIMER",
    "REQUIRED_INVARIANT_CHECK_IDS",
    "REQUIRED_INVARIANT_PROPERTY_KINDS",
    "REQUIRED_INVARIANT_RULE_IDS",
    "REQUIRED_INVARIANT_RULES",
    "UI_INVARIANT_ENGINE_INTERFACE",
    "UI_INVARIANT_ENGINE_SCHEMA",
    "UI_INVARIANT_ENGINE_VERSION",
    "UI_INVARIANT_REPORT_INTERFACE",
    "UI_INVARIANT_REPORT_SCHEMA",
    "UI_INVARIANT_VIOLATION_INTERFACE",
    "UI_INVARIANT_VIOLATION_SCHEMA",
    "UI_INVARIANT_WORLD_INTERFACE",
    "UI_INVARIANT_WORLD_SCHEMA",
    "GuiInvariantEngineError",
    "UiActionRuntimeObservation",
    "UiBindingResolution",
    "UiConfirmationObservation",
    "UiDeonticStatus",
    "UiDomNodeObservation",
    "UiFormInputObservation",
    "UiFormSubmissionObservation",
    "UiImageKind",
    "UiInvariantAcceptanceOutcome",
    "UiInvariantCheckResult",
    "UiInvariantEngine",
    "UiInvariantFamily",
    "UiInvariantReport",
    "UiInvariantRule",
    "UiInvariantVerdict",
    "UiInvariantViolation",
    "UiInvariantWorld",
    "UiModalFocusObservation",
    "UiPolicyObservation",
    "UiPresentationObservation",
    "UiPresentationVisibility",
    "UiUnsupportedPropertyMarker",
    "UiValidationErrorObservation",
    "create_ui_invariant_engine",
]
