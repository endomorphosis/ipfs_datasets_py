"""Planning proof obligations, bounded-plan terms, PlanDelta, and assume-guarantee contracts.

The terms, deltas, and assume-guarantee records in this module describe a
plan; they never grant execution or completion authority.  Operational
admission remains the responsibility of the supervisor that independently verifies
the recorded acceptance evidence.  PlanDelta and PlanAssumeGuarantee are
deliberately parallel to PlanTerms and PlanObligation: they are not a new
planner and are not a competing operational subsystem.  Accelerate owns
operational PlanDelta@1 and assume-guarantee admission; this record only names
the impacted suffix, the preserved unaffected set, model-free refill
identities, and compositional substitutions whose guarantees apply only when
assumptions are satisfied and current admitted guarantee receipts exist.
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
PLAN_DELTA_SCHEMA: Final[str] = (
    "ipfs_datasets_py/logic/external-work-plan-delta@1"
)
PLAN_DELTA_SCHEMA_VERSION: Final[str] = "external-work-plan-delta/v1"
PLAN_ASSUME_GUARANTEE_SCHEMA: Final[str] = (
    "ipfs_datasets_py/logic/external-work-plan-assume-guarantee@1"
)
PLAN_ASSUME_GUARANTEE_SCHEMA_VERSION: Final[str] = (
    "external-work-plan-assume-guarantee/v1"
)
KINDS: Final[frozenset[str]] = frozenset(
    {
        "child_covers_parent",
        "safe_parallel_effects",
        "validation_before_acceptance",
        "immutable_criteria",
        "no_self_granted_authority",
    }
)
PLAN_DELTA_FORBIDDEN_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "admission_receipt_cid",
        "authorization_decision",
        "completion_decision",
        "fencing_epoch",
        "items",
        "lease_id",
        "policy_id",
        "policy_revision",
        "request_cid",
        "roots",
        "scan_receipt_cid",
    }
)
PLAN_ASSUME_GUARANTEE_FORBIDDEN_FIELDS: Final[frozenset[str]] = frozenset(
    PLAN_DELTA_FORBIDDEN_FIELDS
    | {
        "discharge_decision",
        "operational_admission",
        "self_granted_substitution",
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


def _validated_identifier(value: str, *, field: str) -> str:
    """Return a non-empty compact identifier without whitespace."""
    if not isinstance(value, str):
        raise ObligationError(f"{field} must be text")
    normalized = value.strip()
    if not normalized:
        raise ObligationError(f"{field} must not be empty")
    if any(character.isspace() for character in normalized):
        raise ObligationError(f"{field} must not contain whitespace")
    return normalized


def _validated_ids(values: Sequence[str], *, field: str) -> tuple[str, ...]:
    """Return a duplicate-free tuple of compact identifiers."""
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
        raise ObligationError(f"{field} must be a sequence")
    normalized = tuple(
        _validated_identifier(value, field=field) for value in values
    )
    if len(set(normalized)) != len(normalized):
        raise ObligationError(f"{field} must not contain duplicates")
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
class PlanDelta:
    """Semantic identity of a plan impact suffix.

    ``PlanDelta`` is deliberately parallel to :class:`PlanTerms`.  It is not a
    new planner, not an impact analyzer, and not a competing operational subsystem.
    It cannot grant completion authority.  Operational admission remains
    accelerate-owned PlanDelta@1; this record only names the impacted suffix,
    the preserved unaffected set, and model-free refill identities.
    """

    base_plan_revision: str
    triggering_event_id: str
    impacted_task_ids: tuple[str, ...]
    preserved_task_ids: tuple[str, ...]
    preserved_receipt_ids: tuple[str, ...]
    refill_task_ids: tuple[str, ...]
    schema: str = PLAN_DELTA_SCHEMA
    schema_version: str = PLAN_DELTA_SCHEMA_VERSION
    history_preserving: bool = True
    model_free_refill: bool = True
    completion_authoritative: bool = False

    def __post_init__(self) -> None:
        if self.schema != PLAN_DELTA_SCHEMA:
            raise ObligationError("unsupported plan delta schema")
        if self.schema_version != PLAN_DELTA_SCHEMA_VERSION:
            raise ObligationError("unsupported plan delta schema version")
        if self.completion_authoritative:
            raise ObligationError("plan delta cannot grant completion authority")
        if not self.history_preserving:
            raise ObligationError("plan delta must preserve history")
        if not self.model_free_refill:
            raise ObligationError("plan delta refill must be model-free")
        object.__setattr__(
            self,
            "base_plan_revision",
            _validated_identifier(
                self.base_plan_revision, field="base_plan_revision"
            ),
        )
        object.__setattr__(
            self,
            "triggering_event_id",
            _validated_identifier(
                self.triggering_event_id, field="triggering_event_id"
            ),
        )
        object.__setattr__(
            self,
            "impacted_task_ids",
            _validated_ids(self.impacted_task_ids, field="impacted_task_ids"),
        )
        object.__setattr__(
            self,
            "preserved_task_ids",
            _validated_ids(self.preserved_task_ids, field="preserved_task_ids"),
        )
        object.__setattr__(
            self,
            "preserved_receipt_ids",
            _validated_ids(
                self.preserved_receipt_ids, field="preserved_receipt_ids"
            ),
        )
        object.__setattr__(
            self,
            "refill_task_ids",
            _validated_ids(self.refill_task_ids, field="refill_task_ids"),
        )
        impacted = set(self.impacted_task_ids)
        preserved = set(self.preserved_task_ids)
        if impacted & preserved:
            raise ObligationError(
                "impacted and preserved task ids must be disjoint"
            )
        if not set(self.refill_task_ids).issubset(impacted):
            raise ObligationError(
                "refill task ids must be a subset of the impacted suffix"
            )
        object.__setattr__(self, "history_preserving", True)
        object.__setattr__(self, "model_free_refill", True)
        object.__setattr__(self, "completion_authoritative", False)

    def to_dict(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "schema": self.schema,
                "schema_version": self.schema_version,
                "base_plan_revision": self.base_plan_revision,
                "triggering_event_id": self.triggering_event_id,
                "impacted_task_ids": list(self.impacted_task_ids),
                "preserved_task_ids": list(self.preserved_task_ids),
                "preserved_receipt_ids": list(self.preserved_receipt_ids),
                "refill_task_ids": list(self.refill_task_ids),
                "history_preserving": True,
                "model_free_refill": True,
                "completion_authoritative": False,
            }
        )

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "PlanDelta":
        if not isinstance(payload, Mapping):
            raise ObligationError("plan delta must be an object")
        forbidden = set(payload).intersection(PLAN_DELTA_FORBIDDEN_FIELDS)
        if forbidden:
            raise ObligationError(
                "plan delta contains operational authority field(s): "
                f"{sorted(forbidden)[0]}"
            )
        allowed = {
            "schema",
            "schema_version",
            "base_plan_revision",
            "triggering_event_id",
            "impacted_task_ids",
            "preserved_task_ids",
            "preserved_receipt_ids",
            "refill_task_ids",
            "history_preserving",
            "model_free_refill",
            "completion_authoritative",
        }
        unknown = set(payload).difference(allowed)
        if unknown:
            raise ObligationError(f"unknown plan delta field: {sorted(unknown)[0]}")
        return cls(
            base_plan_revision=str(payload.get("base_plan_revision") or ""),
            triggering_event_id=str(payload.get("triggering_event_id") or ""),
            impacted_task_ids=tuple(payload.get("impacted_task_ids") or ()),
            preserved_task_ids=tuple(payload.get("preserved_task_ids") or ()),
            preserved_receipt_ids=tuple(payload.get("preserved_receipt_ids") or ()),
            refill_task_ids=tuple(payload.get("refill_task_ids") or ()),
            schema=str(payload.get("schema", PLAN_DELTA_SCHEMA)),
            schema_version=str(
                payload.get("schema_version", PLAN_DELTA_SCHEMA_VERSION)
            ),
            history_preserving=bool(payload.get("history_preserving", True)),
            model_free_refill=bool(payload.get("model_free_refill", True)),
            completion_authoritative=bool(
                payload.get("completion_authoritative", False)
            ),
        )


def validate_plan_delta(value: Mapping[str, Any] | PlanDelta) -> PlanDelta:
    """Validate canonical delta identity; no caller can self-admit it."""
    delta = value if isinstance(value, PlanDelta) else PlanDelta.from_dict(value)
    if delta.completion_authoritative:
        raise ObligationError("plan delta cannot grant completion authority")
    if not delta.history_preserving:
        raise ObligationError("plan delta must preserve history")
    if not delta.model_free_refill:
        raise ObligationError("plan delta refill must be model-free")
    return delta


@dataclass(frozen=True)
class AssumeGuaranteeSubstitution:
    """One producer-guarantee to consumer-assumption planning edge.

    Guarantees may be substituted only when the named assumptions are
    satisfied and current admitted guarantee receipts are present.  The edge
    itself never grants completion or operational admission authority.
    """

    substitution_id: str
    producer_component_id: str
    consumer_component_id: str
    guarantees: tuple[str, ...]
    assumptions: tuple[str, ...]
    admitted_guarantee_receipt_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "substitution_id",
            _validated_identifier(self.substitution_id, field="substitution_id"),
        )
        object.__setattr__(
            self,
            "producer_component_id",
            _validated_identifier(
                self.producer_component_id, field="producer_component_id"
            ),
        )
        object.__setattr__(
            self,
            "consumer_component_id",
            _validated_identifier(
                self.consumer_component_id, field="consumer_component_id"
            ),
        )
        guarantees = tuple(
            _validated_text(value, field="guarantees") for value in self.guarantees
        )
        if not guarantees:
            raise ObligationError("guarantees must not be empty")
        if len(set(guarantees)) != len(guarantees):
            raise ObligationError("guarantees must not contain duplicates")
        object.__setattr__(self, "guarantees", guarantees)
        assumptions = tuple(
            _validated_text(value, field="assumptions") for value in self.assumptions
        )
        if not assumptions:
            raise ObligationError("assumptions must not be empty")
        if len(set(assumptions)) != len(assumptions):
            raise ObligationError("assumptions must not contain duplicates")
        object.__setattr__(self, "assumptions", assumptions)
        object.__setattr__(
            self,
            "admitted_guarantee_receipt_ids",
            _validated_ids(
                self.admitted_guarantee_receipt_ids,
                field="admitted_guarantee_receipt_ids",
            ),
        )
        if not self.admitted_guarantee_receipt_ids:
            raise ObligationError(
                "assume-guarantee substitution requires current admitted guarantees"
            )

    def to_dict(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "substitution_id": self.substitution_id,
                "producer_component_id": self.producer_component_id,
                "consumer_component_id": self.consumer_component_id,
                "guarantees": list(self.guarantees),
                "assumptions": list(self.assumptions),
                "admitted_guarantee_receipt_ids": list(
                    self.admitted_guarantee_receipt_ids
                ),
            }
        )

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "AssumeGuaranteeSubstitution":
        if not isinstance(payload, Mapping):
            raise ObligationError("assume-guarantee substitution must be an object")
        allowed = {
            "substitution_id",
            "producer_component_id",
            "consumer_component_id",
            "guarantees",
            "assumptions",
            "admitted_guarantee_receipt_ids",
        }
        unknown = set(payload).difference(allowed)
        if unknown:
            raise ObligationError(
                f"unknown assume-guarantee substitution field: {sorted(unknown)[0]}"
            )
        return cls(
            substitution_id=str(payload.get("substitution_id") or ""),
            producer_component_id=str(payload.get("producer_component_id") or ""),
            consumer_component_id=str(payload.get("consumer_component_id") or ""),
            guarantees=tuple(payload.get("guarantees") or ()),
            assumptions=tuple(payload.get("assumptions") or ()),
            admitted_guarantee_receipt_ids=tuple(
                payload.get("admitted_guarantee_receipt_ids") or ()
            ),
        )


@dataclass(frozen=True)
class PlanAssumeGuarantee:
    """Compositional assume-guarantee planning contract.

    ``PlanAssumeGuarantee`` is deliberately parallel to :class:`PlanTerms` and
    :class:`PlanDelta`.  It is not a new planner and is not a competing
    operational subsystem.  Assume-guarantee substitution requires current
    admitted guarantees and satisfied assumptions.  It cannot grant completion
    authority.  Operational admission remains accelerate-owned; this record
    only names the compositional substitutions and their preconditions.
    """

    base_plan_revision: str
    substitutions: tuple[AssumeGuaranteeSubstitution, ...]
    satisfied_assumptions: tuple[str, ...]
    schema: str = PLAN_ASSUME_GUARANTEE_SCHEMA
    schema_version: str = PLAN_ASSUME_GUARANTEE_SCHEMA_VERSION
    substitution_requires_admitted_guarantees: bool = True
    substitution_requires_satisfied_assumptions: bool = True
    completion_authoritative: bool = False

    def __post_init__(self) -> None:
        if self.schema != PLAN_ASSUME_GUARANTEE_SCHEMA:
            raise ObligationError("unsupported assume-guarantee schema")
        if self.schema_version != PLAN_ASSUME_GUARANTEE_SCHEMA_VERSION:
            raise ObligationError("unsupported assume-guarantee schema version")
        if self.completion_authoritative:
            raise ObligationError(
                "assume-guarantee contract cannot grant completion authority"
            )
        if not self.substitution_requires_admitted_guarantees:
            raise ObligationError(
                "assume-guarantee substitution requires current admitted guarantees"
            )
        if not self.substitution_requires_satisfied_assumptions:
            raise ObligationError(
                "assume-guarantee substitution requires satisfied assumptions"
            )
        object.__setattr__(
            self,
            "base_plan_revision",
            _validated_identifier(
                self.base_plan_revision, field="base_plan_revision"
            ),
        )
        substitutions = tuple(self.substitutions)
        if not substitutions:
            raise ObligationError("substitutions must not be empty")
        if not all(
            isinstance(item, AssumeGuaranteeSubstitution) for item in substitutions
        ):
            raise ObligationError(
                "substitutions must contain AssumeGuaranteeSubstitution values"
            )
        if len({item.substitution_id for item in substitutions}) != len(substitutions):
            raise ObligationError("substitution IDs must be unique")
        object.__setattr__(self, "substitutions", substitutions)
        satisfied = tuple(
            _validated_text(value, field="satisfied_assumptions")
            for value in self.satisfied_assumptions
        )
        if len(set(satisfied)) != len(satisfied):
            raise ObligationError("satisfied_assumptions must not contain duplicates")
        object.__setattr__(self, "satisfied_assumptions", satisfied)
        required_assumptions = {
            assumption
            for item in substitutions
            for assumption in item.assumptions
        }
        missing = sorted(required_assumptions.difference(satisfied))
        if missing:
            raise ObligationError(
                "assume-guarantee substitution requires satisfied assumptions"
            )
        object.__setattr__(self, "substitution_requires_admitted_guarantees", True)
        object.__setattr__(self, "substitution_requires_satisfied_assumptions", True)
        object.__setattr__(self, "completion_authoritative", False)

    def to_dict(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "schema": self.schema,
                "schema_version": self.schema_version,
                "base_plan_revision": self.base_plan_revision,
                "substitutions": [dict(item.to_dict()) for item in self.substitutions],
                "satisfied_assumptions": list(self.satisfied_assumptions),
                "substitution_requires_admitted_guarantees": True,
                "substitution_requires_satisfied_assumptions": True,
                "completion_authoritative": False,
            }
        )

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "PlanAssumeGuarantee":
        if not isinstance(payload, Mapping):
            raise ObligationError("assume-guarantee contract must be an object")
        forbidden = set(payload).intersection(PLAN_ASSUME_GUARANTEE_FORBIDDEN_FIELDS)
        if forbidden:
            raise ObligationError(
                "assume-guarantee contract contains operational authority field(s): "
                f"{sorted(forbidden)[0]}"
            )
        allowed = {
            "schema",
            "schema_version",
            "base_plan_revision",
            "substitutions",
            "satisfied_assumptions",
            "substitution_requires_admitted_guarantees",
            "substitution_requires_satisfied_assumptions",
            "completion_authoritative",
        }
        unknown = set(payload).difference(allowed)
        if unknown:
            raise ObligationError(
                f"unknown assume-guarantee field: {sorted(unknown)[0]}"
            )
        raw_substitutions = payload.get("substitutions", ())
        if not isinstance(raw_substitutions, Sequence) or isinstance(
            raw_substitutions, (str, bytes)
        ):
            raise ObligationError("substitutions must be a sequence")
        substitutions = []
        for item in raw_substitutions:
            if isinstance(item, AssumeGuaranteeSubstitution):
                substitutions.append(item)
            elif isinstance(item, Mapping):
                substitutions.append(AssumeGuaranteeSubstitution.from_dict(item))
            else:
                raise ObligationError("assume-guarantee substitution must be an object")
        return cls(
            base_plan_revision=str(payload.get("base_plan_revision") or ""),
            substitutions=tuple(substitutions),
            satisfied_assumptions=tuple(payload.get("satisfied_assumptions") or ()),
            schema=str(payload.get("schema", PLAN_ASSUME_GUARANTEE_SCHEMA)),
            schema_version=str(
                payload.get(
                    "schema_version", PLAN_ASSUME_GUARANTEE_SCHEMA_VERSION
                )
            ),
            substitution_requires_admitted_guarantees=bool(
                payload.get("substitution_requires_admitted_guarantees", True)
            ),
            substitution_requires_satisfied_assumptions=bool(
                payload.get("substitution_requires_satisfied_assumptions", True)
            ),
            completion_authoritative=bool(
                payload.get("completion_authoritative", False)
            ),
        )


def validate_plan_assume_guarantee(
    value: Mapping[str, Any] | PlanAssumeGuarantee,
) -> PlanAssumeGuarantee:
    """Validate canonical assume-guarantee contract; no caller can self-admit it."""
    contract = (
        value
        if isinstance(value, PlanAssumeGuarantee)
        else PlanAssumeGuarantee.from_dict(value)
    )
    if contract.completion_authoritative:
        raise ObligationError(
            "assume-guarantee contract cannot grant completion authority"
        )
    if not contract.substitution_requires_admitted_guarantees:
        raise ObligationError(
            "assume-guarantee substitution requires current admitted guarantees"
        )
    if not contract.substitution_requires_satisfied_assumptions:
        raise ObligationError(
            "assume-guarantee substitution requires satisfied assumptions"
        )
    return contract


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
