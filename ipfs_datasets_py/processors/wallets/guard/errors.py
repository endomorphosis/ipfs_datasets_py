"""Fail-closed errors for the custody-neutral transaction preflight guard.

These exceptions never authorize signing or broadcast.  Callers must treat
every raised error as a hard block on automated transaction use.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


class GuardError(ValueError):
    """Base error for wallet transaction guard contracts."""

    def __init__(
        self,
        message: str,
        *,
        reason_code: str = "guard.error",
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.reason_code = reason_code
        self.details = dict(details or {})


class GuardValidationError(GuardError):
    """Raised when a request, intent, or candidate fails structural validation."""

    def __init__(
        self,
        message: str,
        *,
        reason_code: str = "guard.validation",
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message, reason_code=reason_code, details=details)


class GuardPolicyError(GuardError):
    """Raised when policy composition cannot produce a safe decision."""

    def __init__(
        self,
        message: str,
        *,
        reason_code: str = "guard.policy",
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message, reason_code=reason_code, details=details)


class GuardCapabilityError(GuardError):
    """Raised when capability issuance, revalidation, or consumption fails closed."""

    def __init__(
        self,
        message: str,
        *,
        reason_code: str = "guard.capability",
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message, reason_code=reason_code, details=details)


class GuardConsumptionRaceError(GuardCapabilityError):
    """Raised when a one-use capability is already consumed (replay / race)."""

    def __init__(
        self,
        message: str = "admissibility capability already consumed",
        *,
        capability_id: str = "",
        reason_code: str = "guard.consumption_race",
        details: Mapping[str, Any] | None = None,
    ) -> None:
        payload = dict(details or {})
        if capability_id:
            payload.setdefault("capability_id", capability_id)
        super().__init__(message, reason_code=reason_code, details=payload)
        self.capability_id = capability_id


class GuardForbiddenSurfaceError(GuardError):
    """Raised when a request attempts a forbidden custody or approval surface."""

    def __init__(
        self,
        message: str,
        *,
        reason_code: str = "guard.forbidden_surface",
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message, reason_code=reason_code, details=details)


__all__ = [
    "GuardCapabilityError",
    "GuardConsumptionRaceError",
    "GuardError",
    "GuardForbiddenSurfaceError",
    "GuardPolicyError",
    "GuardValidationError",
]
