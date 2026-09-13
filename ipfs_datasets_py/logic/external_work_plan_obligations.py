"""Planning proof obligations, bounded-plan terms, PlanDelta, assume-guarantee contracts, and equivalence elimination.

The terms, deltas, assume-guarantee records, and equivalence-elimination
records in this module describe a plan; they never grant execution or
completion authority.  Operational admission remains the responsibility of
the supervisor that independently verifies the recorded acceptance evidence.
PlanDelta, PlanAssumeGuarantee, and PlanEquivalenceElimination are
deliberately parallel to PlanTerms and PlanObligation: they are not a new
planner and are not a competing operational subsystem.  Accelerate owns
operational PlanDelta@1, assume-guarantee, and equivalence-elimination
admission; this record only names the impacted suffix, the preserved
unaffected set, model-free refill identities, compositional substitutions
whose guarantees apply only when assumptions are satisfied and current
admitted guarantee receipts exist, and equivalent-task and equivalent-plan
classes whose elimination requires current admitted equivalence evidence.
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
PLAN_EQUIVALENCE_ELIMINATION_SCHEMA: Final[str] = (
    "ipfs_datasets_py/logic/external-work-plan-equivalence-elimination@1"
)
PLAN_EQUIVALENCE_ELIMINATION_SCHEMA_VERSION: Final[str] = (
    "external-work-plan-equivalence-elimination/v1"
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
PLAN_EQUIVALENCE_ELIMINATION_FORBIDDEN_FIELDS: Final[frozenset[str]] = frozenset(
    PLAN_ASSUME_GUARANTEE_FORBIDDEN_FIELDS
    | {
        "self_granted_elimination",
        "history_rewrite",
    }
)
EQUIVALENCE_KINDS: Final[frozenset[str]] = frozenset(
    {
        "semantic_identity",
        "logical_equivalence",
        "canonical_equivalent",
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


def _validated_equivalence_kind(value: str, *, field: str) -> str:
    """Return an independently checkable equivalence kind."""
    kind = _validated_text(value, field=field)
    if kind.lower() in {"worker assertion", "model assertion", "self assertion"}:
        raise ObligationError("equivalence requires independent verification")
    if any(character.isspace() for character in kind):
        raise ObligationError(f"{field} must not contain whitespace")
    if kind not in EQUIVALENCE_KINDS:
        raise ObligationError(f"unsupported equivalence kind: {kind}")
    return kind


def _parse_nested_records(
    values: Any,
    *,
    field: str,
    record_type: type,
    parse_mapping,
) -> tuple[Any, ...]:
    """Return nested frozen records from a sequence of mappings or instances."""
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
        raise ObligationError(f"{field} must be a sequence")
    parsed = []
    for item in values:
        if isinstance(item, record_type):
            parsed.append(item)
        elif isinstance(item, Mapping):
            parsed.append(parse_mapping(item))
        else:
            raise ObligationError(f"{field} must contain {record_type.__name__} values")
    return tuple(parsed)


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
class EquivalentTaskClass:
    """One independently evidenced equivalent-task class.

    The retained task is the canonical representative.  Eliminated task
    identities remain named so history is preserved; they are not rewritten
    and this class never grants completion or operational admission
    authority.  Elimination requires current admitted equivalence evidence.
    """

    class_id: str
    retained_task_id: str
    eliminated_task_ids: tuple[str, ...]
    semantic_fingerprint: str
    admitted_equivalence_receipt_ids: tuple[str, ...]
    equivalence_kind: str = "semantic_identity"

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "class_id", _validated_identifier(self.class_id, field="class_id")
        )
        object.__setattr__(
            self,
            "retained_task_id",
            _validated_identifier(self.retained_task_id, field="retained_task_id"),
        )
        object.__setattr__(
            self,
            "eliminated_task_ids",
            _validated_ids(self.eliminated_task_ids, field="eliminated_task_ids"),
        )
        if not self.eliminated_task_ids:
            raise ObligationError("eliminated_task_ids must not be empty")
        if self.retained_task_id in self.eliminated_task_ids:
            raise ObligationError(
                "retained and eliminated task ids must be disjoint"
            )
        object.__setattr__(
            self,
            "semantic_fingerprint",
            _validated_identifier(
                self.semantic_fingerprint, field="semantic_fingerprint"
            ),
        )
        object.__setattr__(
            self,
            "admitted_equivalence_receipt_ids",
            _validated_ids(
                self.admitted_equivalence_receipt_ids,
                field="admitted_equivalence_receipt_ids",
            ),
        )
        if not self.admitted_equivalence_receipt_ids:
            raise ObligationError(
                "equivalent-task elimination requires current admitted equivalence"
            )
        object.__setattr__(
            self,
            "equivalence_kind",
            _validated_equivalence_kind(
                self.equivalence_kind, field="equivalence_kind"
            ),
        )

    def to_dict(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "class_id": self.class_id,
                "retained_task_id": self.retained_task_id,
                "eliminated_task_ids": list(self.eliminated_task_ids),
                "semantic_fingerprint": self.semantic_fingerprint,
                "admitted_equivalence_receipt_ids": list(
                    self.admitted_equivalence_receipt_ids
                ),
                "equivalence_kind": self.equivalence_kind,
            }
        )

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "EquivalentTaskClass":
        if not isinstance(payload, Mapping):
            raise ObligationError("equivalent-task class must be an object")
        allowed = {
            "class_id",
            "retained_task_id",
            "eliminated_task_ids",
            "semantic_fingerprint",
            "admitted_equivalence_receipt_ids",
            "equivalence_kind",
        }
        unknown = set(payload).difference(allowed)
        if unknown:
            raise ObligationError(
                f"unknown equivalent-task class field: {sorted(unknown)[0]}"
            )
        return cls(
            class_id=str(payload.get("class_id") or ""),
            retained_task_id=str(payload.get("retained_task_id") or ""),
            eliminated_task_ids=tuple(payload.get("eliminated_task_ids") or ()),
            semantic_fingerprint=str(payload.get("semantic_fingerprint") or ""),
            admitted_equivalence_receipt_ids=tuple(
                payload.get("admitted_equivalence_receipt_ids") or ()
            ),
            equivalence_kind=str(
                payload.get("equivalence_kind") or "semantic_identity"
            ),
        )


@dataclass(frozen=True)
class EquivalentPlanClass:
    """One independently evidenced equivalent-plan class.

    The retained plan is the canonical representative.  Eliminated plan
    identities remain named so history is preserved; they are not rewritten
    and this class never grants completion or operational admission
    authority.  Elimination requires current admitted equivalence evidence.
    """

    class_id: str
    retained_plan_id: str
    eliminated_plan_ids: tuple[str, ...]
    semantic_fingerprint: str
    admitted_equivalence_receipt_ids: tuple[str, ...]
    equivalence_kind: str = "semantic_identity"

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "class_id", _validated_identifier(self.class_id, field="class_id")
        )
        object.__setattr__(
            self,
            "retained_plan_id",
            _validated_identifier(self.retained_plan_id, field="retained_plan_id"),
        )
        object.__setattr__(
            self,
            "eliminated_plan_ids",
            _validated_ids(self.eliminated_plan_ids, field="eliminated_plan_ids"),
        )
        if not self.eliminated_plan_ids:
            raise ObligationError("eliminated_plan_ids must not be empty")
        if self.retained_plan_id in self.eliminated_plan_ids:
            raise ObligationError(
                "retained and eliminated plan ids must be disjoint"
            )
        object.__setattr__(
            self,
            "semantic_fingerprint",
            _validated_identifier(
                self.semantic_fingerprint, field="semantic_fingerprint"
            ),
        )
        object.__setattr__(
            self,
            "admitted_equivalence_receipt_ids",
            _validated_ids(
                self.admitted_equivalence_receipt_ids,
                field="admitted_equivalence_receipt_ids",
            ),
        )
        if not self.admitted_equivalence_receipt_ids:
            raise ObligationError(
                "equivalent-plan elimination requires current admitted equivalence"
            )
        object.__setattr__(
            self,
            "equivalence_kind",
            _validated_equivalence_kind(
                self.equivalence_kind, field="equivalence_kind"
            ),
        )

    def to_dict(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "class_id": self.class_id,
                "retained_plan_id": self.retained_plan_id,
                "eliminated_plan_ids": list(self.eliminated_plan_ids),
                "semantic_fingerprint": self.semantic_fingerprint,
                "admitted_equivalence_receipt_ids": list(
                    self.admitted_equivalence_receipt_ids
                ),
                "equivalence_kind": self.equivalence_kind,
            }
        )

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "EquivalentPlanClass":
        if not isinstance(payload, Mapping):
            raise ObligationError("equivalent-plan class must be an object")
        allowed = {
            "class_id",
            "retained_plan_id",
            "eliminated_plan_ids",
            "semantic_fingerprint",
            "admitted_equivalence_receipt_ids",
            "equivalence_kind",
        }
        unknown = set(payload).difference(allowed)
        if unknown:
            raise ObligationError(
                f"unknown equivalent-plan class field: {sorted(unknown)[0]}"
            )
        return cls(
            class_id=str(payload.get("class_id") or ""),
            retained_plan_id=str(payload.get("retained_plan_id") or ""),
            eliminated_plan_ids=tuple(payload.get("eliminated_plan_ids") or ()),
            semantic_fingerprint=str(payload.get("semantic_fingerprint") or ""),
            admitted_equivalence_receipt_ids=tuple(
                payload.get("admitted_equivalence_receipt_ids") or ()
            ),
            equivalence_kind=str(
                payload.get("equivalence_kind") or "semantic_identity"
            ),
        )


def _unique_equivalence_members(
    classes: Sequence[Any],
    *,
    retained_attr: str,
    eliminated_attr: str,
    label: str,
) -> None:
    """Fail closed when retained and eliminated identities collide or repeat."""
    class_ids = tuple(item.class_id for item in classes)
    if len(set(class_ids)) != len(class_ids):
        raise ObligationError(f"{label} class IDs must be unique")
    fingerprints = tuple(item.semantic_fingerprint for item in classes)
    if len(set(fingerprints)) != len(fingerprints):
        raise ObligationError(f"{label} semantic fingerprints must be unique")
    retained = tuple(getattr(item, retained_attr) for item in classes)
    if len(set(retained)) != len(retained):
        raise ObligationError(f"retained {label} ids must be unique")
    eliminated: list[str] = []
    for item in classes:
        eliminated.extend(getattr(item, eliminated_attr))
    if len(set(eliminated)) != len(eliminated):
        raise ObligationError(f"eliminated {label} ids must not contain duplicates")
    if set(retained) & set(eliminated):
        raise ObligationError(
            f"retained and eliminated {label} ids must be disjoint"
        )


@dataclass(frozen=True)
class PlanEquivalenceElimination:
    """Equivalent-task and equivalent-plan elimination contract.

    ``PlanEquivalenceElimination`` is deliberately parallel to :class:`PlanTerms`,
    :class:`PlanDelta`, and :class:`PlanAssumeGuarantee`.  It is not a new
    planner and is not a competing operational subsystem.  Equivalent-task
    and equivalent-plan elimination requires current admitted equivalence
    evidence.  It cannot grant completion authority.  Operational admission
    remains accelerate-owned; this record only names the retained
    representatives, the eliminated equivalents, and their independent
    equivalence receipts.  History cannot be rewritten.
    """

    base_plan_revision: str
    task_classes: tuple[EquivalentTaskClass, ...]
    plan_classes: tuple[EquivalentPlanClass, ...]
    schema: str = PLAN_EQUIVALENCE_ELIMINATION_SCHEMA
    schema_version: str = PLAN_EQUIVALENCE_ELIMINATION_SCHEMA_VERSION
    history_preserving: bool = True
    elimination_requires_admitted_equivalence: bool = True
    model_free: bool = True
    completion_authoritative: bool = False

    def __post_init__(self) -> None:
        if self.schema != PLAN_EQUIVALENCE_ELIMINATION_SCHEMA:
            raise ObligationError("unsupported equivalence elimination schema")
        if self.schema_version != PLAN_EQUIVALENCE_ELIMINATION_SCHEMA_VERSION:
            raise ObligationError(
                "unsupported equivalence elimination schema version"
            )
        if self.completion_authoritative:
            raise ObligationError(
                "equivalence elimination cannot grant completion authority"
            )
        if not self.history_preserving:
            raise ObligationError("equivalence elimination must preserve history")
        if not self.elimination_requires_admitted_equivalence:
            raise ObligationError(
                "equivalence elimination requires current admitted equivalence"
            )
        if not self.model_free:
            raise ObligationError("equivalence elimination must be model-free")
        object.__setattr__(
            self,
            "base_plan_revision",
            _validated_identifier(
                self.base_plan_revision, field="base_plan_revision"
            ),
        )
        task_classes = tuple(self.task_classes)
        if not all(isinstance(item, EquivalentTaskClass) for item in task_classes):
            raise ObligationError(
                "task_classes must contain EquivalentTaskClass values"
            )
        plan_classes = tuple(self.plan_classes)
        if not all(isinstance(item, EquivalentPlanClass) for item in plan_classes):
            raise ObligationError(
                "plan_classes must contain EquivalentPlanClass values"
            )
        if not task_classes and not plan_classes:
            raise ObligationError(
                "equivalence elimination requires a task or plan class"
            )
        _unique_equivalence_members(
            task_classes,
            retained_attr="retained_task_id",
            eliminated_attr="eliminated_task_ids",
            label="task",
        )
        _unique_equivalence_members(
            plan_classes,
            retained_attr="retained_plan_id",
            eliminated_attr="eliminated_plan_ids",
            label="plan",
        )
        object.__setattr__(self, "task_classes", task_classes)
        object.__setattr__(self, "plan_classes", plan_classes)
        object.__setattr__(self, "history_preserving", True)
        object.__setattr__(self, "elimination_requires_admitted_equivalence", True)
        object.__setattr__(self, "model_free", True)
        object.__setattr__(self, "completion_authoritative", False)

    @property
    def retained_task_ids(self) -> tuple[str, ...]:
        return tuple(item.retained_task_id for item in self.task_classes)

    @property
    def eliminated_task_ids(self) -> tuple[str, ...]:
        ids: list[str] = []
        for item in self.task_classes:
            ids.extend(item.eliminated_task_ids)
        return tuple(ids)

    @property
    def retained_plan_ids(self) -> tuple[str, ...]:
        return tuple(item.retained_plan_id for item in self.plan_classes)

    @property
    def eliminated_plan_ids(self) -> tuple[str, ...]:
        ids: list[str] = []
        for item in self.plan_classes:
            ids.extend(item.eliminated_plan_ids)
        return tuple(ids)

    def to_dict(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "schema": self.schema,
                "schema_version": self.schema_version,
                "base_plan_revision": self.base_plan_revision,
                "task_classes": [dict(item.to_dict()) for item in self.task_classes],
                "plan_classes": [dict(item.to_dict()) for item in self.plan_classes],
                "history_preserving": True,
                "elimination_requires_admitted_equivalence": True,
                "model_free": True,
                "completion_authoritative": False,
            }
        )

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "PlanEquivalenceElimination":
        if not isinstance(payload, Mapping):
            raise ObligationError("equivalence elimination must be an object")
        forbidden = set(payload).intersection(
            PLAN_EQUIVALENCE_ELIMINATION_FORBIDDEN_FIELDS
        )
        if forbidden:
            raise ObligationError(
                "equivalence elimination contains operational authority field(s): "
                f"{sorted(forbidden)[0]}"
            )
        allowed = {
            "schema",
            "schema_version",
            "base_plan_revision",
            "task_classes",
            "plan_classes",
            "history_preserving",
            "elimination_requires_admitted_equivalence",
            "model_free",
            "completion_authoritative",
        }
        unknown = set(payload).difference(allowed)
        if unknown:
            raise ObligationError(
                f"unknown equivalence elimination field: {sorted(unknown)[0]}"
            )
        return cls(
            base_plan_revision=str(payload.get("base_plan_revision") or ""),
            task_classes=_parse_nested_records(
                payload.get("task_classes") or (),
                field="task_classes",
                record_type=EquivalentTaskClass,
                parse_mapping=EquivalentTaskClass.from_dict,
            ),
            plan_classes=_parse_nested_records(
                payload.get("plan_classes") or (),
                field="plan_classes",
                record_type=EquivalentPlanClass,
                parse_mapping=EquivalentPlanClass.from_dict,
            ),
            schema=str(payload.get("schema", PLAN_EQUIVALENCE_ELIMINATION_SCHEMA)),
            schema_version=str(
                payload.get(
                    "schema_version", PLAN_EQUIVALENCE_ELIMINATION_SCHEMA_VERSION
                )
            ),
            history_preserving=bool(payload.get("history_preserving", True)),
            elimination_requires_admitted_equivalence=bool(
                payload.get("elimination_requires_admitted_equivalence", True)
            ),
            model_free=bool(payload.get("model_free", True)),
            completion_authoritative=bool(
                payload.get("completion_authoritative", False)
            ),
        )


def validate_plan_equivalence_elimination(
    value: Mapping[str, Any] | PlanEquivalenceElimination,
) -> PlanEquivalenceElimination:
    """Validate canonical equivalence elimination; no caller can self-admit it."""
    elimination = (
        value
        if isinstance(value, PlanEquivalenceElimination)
        else PlanEquivalenceElimination.from_dict(value)
    )
    if elimination.completion_authoritative:
        raise ObligationError(
            "equivalence elimination cannot grant completion authority"
        )
    if not elimination.history_preserving:
        raise ObligationError("equivalence elimination must preserve history")
    if not elimination.elimination_requires_admitted_equivalence:
        raise ObligationError(
            "equivalence elimination requires current admitted equivalence"
        )
    if not elimination.model_free:
        raise ObligationError("equivalence elimination must be model-free")
    return elimination


def _collapse_equivalent_ids(
    values: Sequence[str],
    *,
    field: str,
    replacement: Mapping[str, str],
) -> tuple[str, ...]:
    """Replace eliminated identities with their retained representative."""
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
        raise ObligationError(f"{field} must be a sequence")
    retained: list[str] = []
    seen: set[str] = set()
    for value in values:
        identity = _validated_identifier(value, field=field)
        canonical = replacement.get(identity, identity)
        if canonical in seen:
            continue
        seen.add(canonical)
        retained.append(canonical)
    return tuple(retained)


def eliminate_equivalent_tasks(
    task_ids: Sequence[str],
    value: Mapping[str, Any] | PlanEquivalenceElimination,
) -> tuple[str, ...]:
    """Return retained task identities after equivalent-task elimination.

    Eliminated task ids collapse onto the independently evidenced retained
    representative.  Unrelated ids are preserved.  The transform does not
    grant completion authority and does not rewrite accepted history.
    """
    elimination = validate_plan_equivalence_elimination(value)
    replacement = {
        eliminated: item.retained_task_id
        for item in elimination.task_classes
        for eliminated in item.eliminated_task_ids
    }
    return _collapse_equivalent_ids(
        task_ids, field="task_ids", replacement=replacement
    )


def eliminate_equivalent_plans(
    plan_ids: Sequence[str],
    value: Mapping[str, Any] | PlanEquivalenceElimination,
) -> tuple[str, ...]:
    """Return retained plan identities after equivalent-plan elimination.

    Eliminated plan ids collapse onto the independently evidenced retained
    representative.  Unrelated ids are preserved.  The transform does not
    grant completion authority and does not rewrite accepted history.
    """
    elimination = validate_plan_equivalence_elimination(value)
    replacement = {
        eliminated: item.retained_plan_id
        for item in elimination.plan_classes
        for eliminated in item.eliminated_plan_ids
    }
    return _collapse_equivalent_ids(
        plan_ids, field="plan_ids", replacement=replacement
    )


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
