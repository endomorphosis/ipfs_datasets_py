"""Planning proof obligations and bounded-plan terms.

The terms in this module describe a plan; they never grant execution or
completion authority.  Operational admission remains the responsibility of
the supervisor that independently verifies the recorded acceptance evidence.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Final


OBLIGATION_SCHEMA: Final[str] = (
    "ipfs_datasets_py/logic/external-work-plan-obligations@1"
)
PLAN_TERMS_SCHEMA: Final[str] = (
    "ipfs_datasets_py/logic/external-work-plan-terms@1"
)
PLAN_TERMS_SCHEMA_VERSION: Final[str] = "external-work-plan-terms/v1"
KINDS: Final[frozenset[str]] = frozenset(
    {
        "child_covers_parent",
        "safe_parallel_effects",
        "validation_before_acceptance",
        "immutable_criteria",
        "no_self_granted_authority",
    }
)


class ObligationError(ValueError):
    """Plan obligation failed."""


def _validated_text(value: str, *, field: str) -> str:
    """Return a non-empty, canonical textual contract term."""
    if not isinstance(value, str):
        raise ObligationError(f"{field} must be text")
    normalized = " ".join(value.split())
    if not normalized:
        raise ObligationError(f"{field} must not be empty")
    return normalized


@dataclass(frozen=True)
class AcceptanceCondition:
    """One independently checkable condition for accepting a plan result."""

    condition_id: str
    description: str
    verification_method: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "condition_id", _validated_text(self.condition_id, field="condition_id")
        )
        object.__setattr__(
            self, "description", _validated_text(self.description, field="description")
        )
        method = _validated_text(self.verification_method, field="verification_method")
        if method.lower() in {"worker assertion", "model assertion", "self assertion"}:
            raise ObligationError("acceptance requires independent verification")
        object.__setattr__(self, "verification_method", method)

    def to_dict(self) -> Mapping[str, str]:
        return MappingProxyType(
            {
                "condition_id": self.condition_id,
                "description": self.description,
                "verification_method": self.verification_method,
            }
        )


@dataclass(frozen=True)
class PlanTerms:
    """Immutable assumptions, guarantees, limits, and acceptance conditions.

    ``PlanTerms`` is deliberately parallel to :class:`PlanObligation`.  It is
    not a new planner.  Assumptions bound when guarantees apply; non-goals prevent
    an implementation from silently claiming extra authority or outcomes.
    """

    assumptions: tuple[str, ...]
    guarantees: tuple[str, ...]
    non_goals: tuple[str, ...]
    acceptance_conditions: tuple[AcceptanceCondition, ...]
    schema: str = PLAN_TERMS_SCHEMA
    schema_version: str = PLAN_TERMS_SCHEMA_VERSION
    completion_authoritative: bool = False

    def __post_init__(self) -> None:
        if self.schema != PLAN_TERMS_SCHEMA:
            raise ObligationError("unsupported plan terms schema")
        if self.schema_version != PLAN_TERMS_SCHEMA_VERSION:
            raise ObligationError("unsupported plan terms schema version")
        if self.completion_authoritative:
            raise ObligationError("plan terms cannot grant completion authority")
        for field in ("assumptions", "guarantees", "non_goals"):
            values = tuple(_validated_text(value, field=field) for value in getattr(self, field))
            if not values:
                raise ObligationError(f"{field} must not be empty")
            if len(set(values)) != len(values):
                raise ObligationError(f"{field} must not contain duplicates")
            object.__setattr__(self, field, values)
        conditions = tuple(self.acceptance_conditions)
        if not conditions:
            raise ObligationError("acceptance_conditions must not be empty")
        if not all(isinstance(item, AcceptanceCondition) for item in conditions):
            raise ObligationError("acceptance_conditions must contain AcceptanceCondition values")
        if len({item.condition_id for item in conditions}) != len(conditions):
            raise ObligationError("acceptance condition IDs must be unique")
        object.__setattr__(self, "acceptance_conditions", conditions)

    def to_dict(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "schema": self.schema,
                "schema_version": self.schema_version,
                "assumptions": list(self.assumptions),
                "guarantees": list(self.guarantees),
                "non_goals": list(self.non_goals),
                "acceptance_conditions": [dict(item.to_dict()) for item in self.acceptance_conditions],
                "completion_authoritative": False,
            }
        )

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "PlanTerms":
        allowed = {
            "schema", "schema_version", "assumptions", "guarantees", "non_goals",
            "acceptance_conditions", "completion_authoritative",
        }
        unknown = set(payload).difference(allowed)
        if unknown:
            raise ObligationError(f"unknown plan terms field: {sorted(unknown)[0]}")
        raw_conditions = payload.get("acceptance_conditions", ())
        if not isinstance(raw_conditions, Sequence) or isinstance(raw_conditions, (str, bytes)):
            raise ObligationError("acceptance_conditions must be a sequence")
        conditions = []
        for item in raw_conditions:
            if isinstance(item, AcceptanceCondition):
                conditions.append(item)
            elif isinstance(item, Mapping):
                conditions.append(AcceptanceCondition(**dict(item)))
            else:
                raise ObligationError("acceptance condition must be an object")
        return cls(
            assumptions=tuple(payload.get("assumptions", ())),
            guarantees=tuple(payload.get("guarantees", ())),
            non_goals=tuple(payload.get("non_goals", ())),
            acceptance_conditions=tuple(conditions),
            schema=str(payload.get("schema", PLAN_TERMS_SCHEMA)),
            schema_version=str(payload.get("schema_version", PLAN_TERMS_SCHEMA_VERSION)),
            completion_authoritative=bool(payload.get("completion_authoritative", False)),
        )


def validate_plan_terms(value: Mapping[str, Any] | PlanTerms) -> PlanTerms:
    """Validate and return canonical terms; no caller can self-admit them."""
    terms = value if isinstance(value, PlanTerms) else PlanTerms.from_dict(value)
    if terms.completion_authoritative:
        raise ObligationError("plan terms cannot grant completion authority")
    return terms


@dataclass(frozen=True)
class PlanObligation:
    kind: str
    holds: bool
    reason_code: str = "holds"

    def __post_init__(self) -> None:
        if self.kind not in KINDS:
            raise ObligationError(f"unknown obligation: {self.kind}")
        if self.kind == "no_self_granted_authority" and not self.holds:
            raise ObligationError("self-granted authority is not admitted")

    def to_dict(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "schema": OBLIGATION_SCHEMA,
                "kind": self.kind,
                "holds": bool(self.holds),
                "reason_code": self.reason_code,
            }
        )


def prove(obligations: Sequence[Mapping[str, Any] | PlanObligation]) -> tuple[PlanObligation, ...]:
    compiled = []
    for item in obligations:
        if isinstance(item, PlanObligation):
            compiled.append(item)
        else:
            compiled.append(
                PlanObligation(
                    kind=str(item.get("kind") or ""),
                    holds=bool(item.get("holds", True)),
                    reason_code=str(item.get("reason_code") or "holds"),
                )
            )
    missing = KINDS.difference(item.kind for item in compiled)
    if missing:
        raise ObligationError(f"missing obligation {sorted(missing)[0]}")
    if any(not item.holds for item in compiled):
        raise ObligationError("plan obligations do not all hold")
    return tuple(compiled)
