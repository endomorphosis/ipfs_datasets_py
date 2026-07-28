"""Admissibility policy profiles for the Intent / Legal / Security gate.

Profiles declare which constraint families and integrity checks a gate
evaluation must satisfy before it may return ``allow``.  Unknown or malformed
profile identifiers fail closed: they never resolve to a permissive policy.

Declared profiles (LIG-014 / plan §2.4):

* ``dev-offline`` — offline fixture development; ZKP optional; simulated ZKP
  receipts may be accepted when labeled; still never allows without constraints.
* ``security-lite`` — requires attested Security constraints; Legal optional.
* ``legal-strict`` — requires attested Legal and Security constraints (default).
* ``zkp-required`` — same as legal-strict plus mandatory ZKP verify; missing
  proofs abstain, never allow.

Interface: ``AdmissibilityProfile@1`` (see LIG-G060).  Join logic lives in
LIG-015; this module only owns profile identity, policy knobs, and fail-closed
resolution.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import Enum
from typing import Any, Final, Mapping

from .reasons import (
    AdmissibilityReason,
    AdmissibilityReasonCode,
    AdmissibilityStatus,
    default_status_for_reason,
    invalid_profile_reason,
)


ADMISSIBILITY_PROFILE_INTERFACE_VERSION: Final = "AdmissibilityProfile@1"
PROFILE_SCHEMA_VERSION: Final = "1"

# Pinned closed vocabulary of profile wire identifiers (plan §2.4).
PROFILE_ID_WIRE_VALUES: Final[tuple[str, ...]] = (
    "dev-offline",
    "legal-strict",
    "security-lite",
    "zkp-required",
)


class AdmissibilityProfileError(ValueError):
    """Raised when a profile cannot be resolved without guessing."""


class UnknownAdmissibilityProfileError(AdmissibilityProfileError):
    """Raised when a profile identifier is not in the closed vocabulary."""


class AdmissibilityProfileId(str, Enum):
    """Closed set of admissibility profile identifiers."""

    DEV_OFFLINE = "dev-offline"
    SECURITY_LITE = "security-lite"
    LEGAL_STRICT = "legal-strict"
    ZKP_REQUIRED = "zkp-required"


# Production default: never allows without constraints (LIG-G060 acceptance).
DEFAULT_PROFILE_ID: Final[AdmissibilityProfileId] = AdmissibilityProfileId.LEGAL_STRICT


@dataclass(frozen=True, slots=True)
class AdmissibilityProfile:
    """Immutable policy knobs for one admissibility profile.

    Every production profile sets ``allow_without_constraints`` to ``False`` so
    the default disposition without attested constraints is reject, not allow.
    """

    profile_id: AdmissibilityProfileId
    require_legal_constraints: bool
    require_security_constraints: bool
    require_zkp_verify: bool
    accept_simulated_zkp: bool
    allow_without_constraints: bool
    description: str = ""
    schema_version: str = PROFILE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.profile_id, AdmissibilityProfileId):
            object.__setattr__(self, "profile_id", parse_profile_id(self.profile_id))
        if self.allow_without_constraints:
            raise AdmissibilityProfileError(
                "profiles must not allow without constraints; fail closed"
            )
        if self.require_zkp_verify and self.accept_simulated_zkp:
            raise AdmissibilityProfileError(
                "zkp-required profiles must not accept simulated ZKP receipts"
            )
        if not isinstance(self.description, str):
            raise AdmissibilityProfileError("description must be a string")
        if not isinstance(self.schema_version, str) or not self.schema_version:
            raise AdmissibilityProfileError("schema_version must be a non-empty string")

    @property
    def id(self) -> str:
        """Wire identifier for this profile."""

        return self.profile_id.value

    def to_dict(self) -> dict[str, Any]:
        """Return a deterministic JSON-serializable policy map."""

        return {
            "accept_simulated_zkp": self.accept_simulated_zkp,
            "allow_without_constraints": self.allow_without_constraints,
            "description": self.description,
            "interface": ADMISSIBILITY_PROFILE_INTERFACE_VERSION,
            "profile_id": self.profile_id.value,
            "require_legal_constraints": self.require_legal_constraints,
            "require_security_constraints": self.require_security_constraints,
            "require_zkp_verify": self.require_zkp_verify,
            "schema_version": self.schema_version,
        }

    def config_digest(self) -> str:
        """Return a lowercase SHA-256 digest of the canonical policy map."""

        encoded = json.dumps(
            self.to_dict(),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
            allow_nan=False,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


def _build_registry() -> dict[AdmissibilityProfileId, AdmissibilityProfile]:
    return {
        AdmissibilityProfileId.DEV_OFFLINE: AdmissibilityProfile(
            profile_id=AdmissibilityProfileId.DEV_OFFLINE,
            require_legal_constraints=True,
            require_security_constraints=True,
            require_zkp_verify=False,
            accept_simulated_zkp=True,
            allow_without_constraints=False,
            description=(
                "Offline development profile: constraints required; ZKP optional; "
                "labeled simulated ZKP may be accepted; never allows without constraints."
            ),
        ),
        AdmissibilityProfileId.SECURITY_LITE: AdmissibilityProfile(
            profile_id=AdmissibilityProfileId.SECURITY_LITE,
            require_legal_constraints=False,
            require_security_constraints=True,
            require_zkp_verify=False,
            accept_simulated_zkp=False,
            allow_without_constraints=False,
            description=(
                "Security-lite profile: attested Security constraints required; "
                "Legal optional; simulated ZKP rejected; never allows without constraints."
            ),
        ),
        AdmissibilityProfileId.LEGAL_STRICT: AdmissibilityProfile(
            profile_id=AdmissibilityProfileId.LEGAL_STRICT,
            require_legal_constraints=True,
            require_security_constraints=True,
            require_zkp_verify=False,
            accept_simulated_zkp=False,
            allow_without_constraints=False,
            description=(
                "Legal-strict default profile: attested Legal and Security constraints "
                "required; ZKP optional; never allows without constraints."
            ),
        ),
        AdmissibilityProfileId.ZKP_REQUIRED: AdmissibilityProfile(
            profile_id=AdmissibilityProfileId.ZKP_REQUIRED,
            require_legal_constraints=True,
            require_security_constraints=True,
            require_zkp_verify=True,
            accept_simulated_zkp=False,
            allow_without_constraints=False,
            description=(
                "ZKP-required profile: Legal and Security constraints plus verified "
                "ZKP proofs; missing or simulated ZKP never allows."
            ),
        ),
    }


PROFILE_REGISTRY: Final[Mapping[AdmissibilityProfileId, AdmissibilityProfile]] = (
    _build_registry()
)


def stable_profile_id_values() -> tuple[str, ...]:
    """Return the pinned, sorted wire values of all profile identifiers."""

    return PROFILE_ID_WIRE_VALUES


def profile_id_set() -> frozenset[str]:
    """Return the closed set of profile wire identifiers."""

    return frozenset(PROFILE_ID_WIRE_VALUES)


def is_known_profile(value: object) -> bool:
    """Return True iff ``value`` names a declared profile."""

    if isinstance(value, AdmissibilityProfileId):
        return True
    if isinstance(value, AdmissibilityProfile):
        return True
    if not isinstance(value, str):
        return False
    return value.strip() in PROFILE_ID_WIRE_VALUES


def parse_profile_id(value: object) -> AdmissibilityProfileId:
    """Parse a profile identifier; unknown values fail closed with an error."""

    if isinstance(value, AdmissibilityProfileId):
        return value
    if isinstance(value, AdmissibilityProfile):
        return value.profile_id
    if not isinstance(value, str) or not value.strip():
        raise UnknownAdmissibilityProfileError(
            "admissibility profile id must be a non-empty string; fail closed"
        )
    normalized = value.strip()
    try:
        return AdmissibilityProfileId(normalized)
    except ValueError as exc:
        raise UnknownAdmissibilityProfileError(
            f"unknown admissibility profile {normalized!r}; fail closed"
        ) from exc


def get_profile(profile_id: AdmissibilityProfileId | str) -> AdmissibilityProfile:
    """Return the immutable policy for a known profile id."""

    resolved = parse_profile_id(profile_id)
    try:
        return PROFILE_REGISTRY[resolved]
    except KeyError as exc:  # pragma: no cover - registry covers every enum member
        raise UnknownAdmissibilityProfileError(
            f"admissibility profile {resolved.value!r} is not registered; fail closed"
        ) from exc


def resolve_profile(
    value: AdmissibilityProfileId | AdmissibilityProfile | str | None = None,
    *,
    default: AdmissibilityProfileId | None = DEFAULT_PROFILE_ID,
) -> AdmissibilityProfile:
    """Resolve a profile reference to an immutable policy object.

    * ``None`` resolves to ``default`` (``legal-strict`` unless overridden).
    * Known string/enum/profile values resolve to the registry entry.
    * Unknown or blank strings raise :class:`UnknownAdmissibilityProfileError`
      (fail closed; never map to a permissive policy).
    """

    if value is None:
        if default is None:
            raise UnknownAdmissibilityProfileError(
                "admissibility profile is required; fail closed"
            )
        return get_profile(default)
    if isinstance(value, AdmissibilityProfile):
        # Re-fetch from registry so callers cannot inject a loosened policy object
        # that claims a known id while mutating knobs.
        return get_profile(value.profile_id)
    return get_profile(value)


@dataclass(frozen=True, slots=True)
class ProfileResolution:
    """Result of a fail-closed profile resolution attempt.

    On success, ``profile`` is set and ``status`` is unset.  On failure,
    ``profile`` is ``None``, ``status`` is :attr:`AdmissibilityStatus.REJECT`,
    and ``reasons`` includes :attr:`AdmissibilityReasonCode.INVALID_PROFILE`.
    """

    ok: bool
    profile: AdmissibilityProfile | None
    status: AdmissibilityStatus | None
    reasons: tuple[AdmissibilityReason, ...]
    requested: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "profile": None if self.profile is None else self.profile.to_dict(),
            "profile_id": None if self.profile is None else self.profile.id,
            "requested": self.requested,
            "reasons": [reason.to_dict() for reason in self.reasons],
            "status": None if self.status is None else self.status.value,
        }


def resolve_profile_fail_closed(
    value: AdmissibilityProfileId | AdmissibilityProfile | str | None = None,
    *,
    default: AdmissibilityProfileId | None = DEFAULT_PROFILE_ID,
) -> ProfileResolution:
    """Resolve a profile without raising; invalid input fails closed as reject.

    This is the gate-facing entry point: unknown profiles never allow and never
    fall through to a looser policy.
    """

    requested: str | None
    if value is None:
        requested = None
    elif isinstance(value, AdmissibilityProfile):
        requested = value.id
    elif isinstance(value, AdmissibilityProfileId):
        requested = value.value
    else:
        requested = str(value) if value is not None else None

    try:
        profile = resolve_profile(value, default=default)
    except AdmissibilityProfileError:
        reason = invalid_profile_reason(value)
        status = default_status_for_reason(AdmissibilityReasonCode.INVALID_PROFILE)
        return ProfileResolution(
            ok=False,
            profile=None,
            status=status,
            reasons=(reason,),
            requested=requested,
        )
    return ProfileResolution(
        ok=True,
        profile=profile,
        status=None,
        reasons=(),
        requested=requested if requested is not None else profile.id,
    )


def list_profiles() -> tuple[AdmissibilityProfile, ...]:
    """Return all registered profiles in stable profile-id order."""

    return tuple(
        PROFILE_REGISTRY[AdmissibilityProfileId(wire)]
        for wire in PROFILE_ID_WIRE_VALUES
    )


# Sanity: enum members must match the pinned wire vocabulary exactly.
_enum_profile_values = tuple(sorted(member.value for member in AdmissibilityProfileId))
if _enum_profile_values != PROFILE_ID_WIRE_VALUES:
    raise RuntimeError(
        "AdmissibilityProfileId members drifted from PROFILE_ID_WIRE_VALUES; "
        f"enum={_enum_profile_values!r} pinned={PROFILE_ID_WIRE_VALUES!r}"
    )
if set(PROFILE_REGISTRY) != set(AdmissibilityProfileId):
    raise RuntimeError("PROFILE_REGISTRY must cover every AdmissibilityProfileId member")
if any(profile.allow_without_constraints for profile in PROFILE_REGISTRY.values()):
    raise RuntimeError("no registered profile may allow without constraints")


__all__ = [
    "ADMISSIBILITY_PROFILE_INTERFACE_VERSION",
    "DEFAULT_PROFILE_ID",
    "PROFILE_ID_WIRE_VALUES",
    "PROFILE_REGISTRY",
    "PROFILE_SCHEMA_VERSION",
    "AdmissibilityProfile",
    "AdmissibilityProfileError",
    "AdmissibilityProfileId",
    "ProfileResolution",
    "UnknownAdmissibilityProfileError",
    "get_profile",
    "is_known_profile",
    "list_profiles",
    "parse_profile_id",
    "profile_id_set",
    "resolve_profile",
    "resolve_profile_fail_closed",
    "stable_profile_id_values",
]
