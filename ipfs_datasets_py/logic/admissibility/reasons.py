"""Closed, enum-stable reason codes for Intent admissibility decisions.

This module defines the wire vocabulary for gate outcomes (allow / reject /
abstain) and the machine-readable reason codes bound into every decision.  The
vocabulary is intentionally closed: unknown codes fail closed rather than being
coerced into a free-form string.  LIG-015's join engine consumes these codes; it
must never invent ad-hoc reason strings that bypass this enum.

Interface: ``AdmissibilityReason@1`` (see LIG-G060).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Final, Mapping


ADMISSIBILITY_REASON_INTERFACE_VERSION: Final = "AdmissibilityReason@1"

# Pinned closed vocabulary.  Tests and downstream digests treat this tuple as
# the authoritative enum-stable order for reason wire values.
REASON_CODE_WIRE_VALUES: Final[tuple[str, ...]] = (
    "constraint_contradiction",
    "corpus_unavailable",
    "integrity_failure",
    "invalid_intent",
    "invalid_profile",
    "legal_hard_constraint",
    "missing_evidence",
    "no_constraints",
    "obligations_supported",
    "prover_unavailable",
    "security_hard_constraint",
    "semantics_unsupported",
    "zkp_missing",
    "zkp_verify_failed",
)


class AdmissibilityReasonError(ValueError):
    """Raised when a reason code or status cannot be resolved without guessing."""


class AdmissibilityStatus(str, Enum):
    """Terminal gate disposition under a declared policy profile.

    ``allow`` requires full support under the profile; ``reject`` is a hard
    forbid or integrity failure; ``abstain`` never promotes to allow.
    """

    ALLOW = "allow"
    REJECT = "reject"
    ABSTAIN = "abstain"


class AdmissibilityReasonCode(str, Enum):
    """Closed, enum-stable machine-readable reason codes.

    Wire values are snake_case strings.  Members must not be renamed or
    reassigned without a versioned migration; callers may pin
    :data:`REASON_CODE_WIRE_VALUES` / :func:`stable_reason_code_values`.
    """

    CONSTRAINT_CONTRADICTION = "constraint_contradiction"
    CORPUS_UNAVAILABLE = "corpus_unavailable"
    INTEGRITY_FAILURE = "integrity_failure"
    INVALID_INTENT = "invalid_intent"
    INVALID_PROFILE = "invalid_profile"
    LEGAL_HARD_CONSTRAINT = "legal_hard_constraint"
    MISSING_EVIDENCE = "missing_evidence"
    NO_CONSTRAINTS = "no_constraints"
    OBLIGATIONS_SUPPORTED = "obligations_supported"
    PROVER_UNAVAILABLE = "prover_unavailable"
    SECURITY_HARD_CONSTRAINT = "security_hard_constraint"
    SEMANTICS_UNSUPPORTED = "semantics_unsupported"
    ZKP_MISSING = "zkp_missing"
    ZKP_VERIFY_FAILED = "zkp_verify_failed"


# Default fail-closed status for each reason when no richer context is known.
# Join logic (LIG-015) may override when multiple reasons apply; invalid
# profile always rejects (never allows).
_DEFAULT_STATUS_FOR_REASON: Final[dict[AdmissibilityReasonCode, AdmissibilityStatus]] = {
    AdmissibilityReasonCode.OBLIGATIONS_SUPPORTED: AdmissibilityStatus.ALLOW,
    AdmissibilityReasonCode.LEGAL_HARD_CONSTRAINT: AdmissibilityStatus.REJECT,
    AdmissibilityReasonCode.SECURITY_HARD_CONSTRAINT: AdmissibilityStatus.REJECT,
    AdmissibilityReasonCode.CONSTRAINT_CONTRADICTION: AdmissibilityStatus.REJECT,
    AdmissibilityReasonCode.INTEGRITY_FAILURE: AdmissibilityStatus.REJECT,
    AdmissibilityReasonCode.NO_CONSTRAINTS: AdmissibilityStatus.REJECT,
    AdmissibilityReasonCode.INVALID_PROFILE: AdmissibilityStatus.REJECT,
    AdmissibilityReasonCode.INVALID_INTENT: AdmissibilityStatus.REJECT,
    AdmissibilityReasonCode.MISSING_EVIDENCE: AdmissibilityStatus.ABSTAIN,
    AdmissibilityReasonCode.PROVER_UNAVAILABLE: AdmissibilityStatus.ABSTAIN,
    AdmissibilityReasonCode.ZKP_MISSING: AdmissibilityStatus.ABSTAIN,
    AdmissibilityReasonCode.ZKP_VERIFY_FAILED: AdmissibilityStatus.ABSTAIN,
    AdmissibilityReasonCode.SEMANTICS_UNSUPPORTED: AdmissibilityStatus.ABSTAIN,
    AdmissibilityReasonCode.CORPUS_UNAVAILABLE: AdmissibilityStatus.ABSTAIN,
}


def stable_reason_code_values() -> tuple[str, ...]:
    """Return the pinned, sorted wire values of all reason codes.

    The order is lexicographic over the enum wire values and is the contract
    tests assert for enum stability.
    """

    return REASON_CODE_WIRE_VALUES


def reason_code_set() -> frozenset[str]:
    """Return the closed set of reason wire values."""

    return frozenset(REASON_CODE_WIRE_VALUES)


def parse_status(value: object) -> AdmissibilityStatus:
    """Parse a status wire value; unknown values fail closed."""

    if isinstance(value, AdmissibilityStatus):
        return value
    if not isinstance(value, str) or not value.strip():
        raise AdmissibilityReasonError(
            "admissibility status must be a non-empty string; fail closed"
        )
    normalized = value.strip()
    try:
        return AdmissibilityStatus(normalized)
    except ValueError as exc:
        raise AdmissibilityReasonError(
            f"unknown admissibility status {normalized!r}; fail closed"
        ) from exc


def parse_reason_code(value: object) -> AdmissibilityReasonCode:
    """Parse a reason code wire value; unknown codes fail closed."""

    if isinstance(value, AdmissibilityReasonCode):
        return value
    if not isinstance(value, str) or not value.strip():
        raise AdmissibilityReasonError(
            "reason code must be a non-empty string; fail closed"
        )
    normalized = value.strip()
    try:
        return AdmissibilityReasonCode(normalized)
    except ValueError as exc:
        raise AdmissibilityReasonError(
            f"unknown admissibility reason code {normalized!r}; fail closed"
        ) from exc


def default_status_for_reason(code: AdmissibilityReasonCode | str) -> AdmissibilityStatus:
    """Return the default fail-closed status associated with a reason code."""

    resolved = parse_reason_code(code)
    return _DEFAULT_STATUS_FOR_REASON[resolved]


@dataclass(frozen=True, slots=True)
class AdmissibilityReason:
    """One structured reason bound into an admissibility decision."""

    code: AdmissibilityReasonCode
    message: str = ""
    detail: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.code, AdmissibilityReasonCode):
            object.__setattr__(self, "code", parse_reason_code(self.code))
        if not isinstance(self.message, str):
            raise AdmissibilityReasonError("reason message must be a string")
        if self.detail is not None and not isinstance(self.detail, Mapping):
            raise AdmissibilityReasonError("reason detail must be a mapping when provided")

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation."""

        payload: dict[str, Any] = {
            "code": self.code.value,
            "message": self.message,
        }
        if self.detail is not None:
            payload["detail"] = dict(self.detail)
        return payload

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> AdmissibilityReason:
        """Reconstruct a reason from a mapping; unknown codes fail closed."""

        if not isinstance(value, Mapping):
            raise AdmissibilityReasonError("reason payload must be a mapping")
        code = parse_reason_code(value.get("code"))
        message = value.get("message", "")
        if message is None:
            message = ""
        if not isinstance(message, str):
            raise AdmissibilityReasonError("reason message must be a string")
        detail = value.get("detail")
        if detail is not None and not isinstance(detail, Mapping):
            raise AdmissibilityReasonError("reason detail must be a mapping when provided")
        return cls(code=code, message=message, detail=dict(detail) if detail is not None else None)


def invalid_profile_reason(profile_value: object) -> AdmissibilityReason:
    """Build the standard fail-closed reason for an unrecognized profile."""

    return AdmissibilityReason(
        code=AdmissibilityReasonCode.INVALID_PROFILE,
        message="admissibility profile is unknown or malformed; fail closed",
        detail={"profile": None if profile_value is None else str(profile_value)},
    )


# Sanity: enum members must match the pinned wire vocabulary exactly.
_enum_values = tuple(sorted(member.value for member in AdmissibilityReasonCode))
if _enum_values != REASON_CODE_WIRE_VALUES:
    raise RuntimeError(
        "AdmissibilityReasonCode members drifted from REASON_CODE_WIRE_VALUES; "
        f"enum={_enum_values!r} pinned={REASON_CODE_WIRE_VALUES!r}"
    )
if set(_DEFAULT_STATUS_FOR_REASON) != set(AdmissibilityReasonCode):
    raise RuntimeError(
        "default status map must cover every AdmissibilityReasonCode member"
    )


__all__ = [
    "ADMISSIBILITY_REASON_INTERFACE_VERSION",
    "REASON_CODE_WIRE_VALUES",
    "AdmissibilityReason",
    "AdmissibilityReasonCode",
    "AdmissibilityReasonError",
    "AdmissibilityStatus",
    "default_status_for_reason",
    "invalid_profile_reason",
    "parse_reason_code",
    "parse_status",
    "reason_code_set",
    "stable_reason_code_values",
]
