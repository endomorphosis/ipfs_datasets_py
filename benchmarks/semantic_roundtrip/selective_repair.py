"""Selective, auditable Leanstral repair with structural candidate filtering.

This module implements the bounded intervention described by SRT-012.  A
deterministic constructor remains the baseline.  Leanstral is called only
when a preregistered trigger identifies a missing, contradictory, or
low-confidence canonical slot.  Every call and every candidate field change
is retained, including malformed, rejected, and failed attempts.

Hammer/cvc5 and Lean are deliberately represented by injected structural
validator bindings.  Their requests contain only the baseline IR, candidate
IR, allowed repair slots, and preregistered structural constraints: never
source text, gold IR, semantic scores, or adjudication.  Their receipts may
filter structurally invalid candidates but cannot establish source meaning.
"""

from __future__ import annotations

import hashlib
import json
import math
import socket
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Final, Protocol, runtime_checkable

from benchmarks.semantic_roundtrip.contracts import (
    RULE_FIELDS,
    AllowedAtomVocabulary,
    CanonicalRuleIR,
    ComponentStatus,
    ConstructorRequest,
    ConstructorResult,
    ContractError,
    FailureReason,
    RoundTripConstructor,
)
from benchmarks.semantic_roundtrip.constructors.autoencoder_guided import (
    CanonicalFieldChange,
    canonical_field_changes,
)
from benchmarks.semantic_roundtrip.constructors.leanstral import (
    CONSTRUCTOR_MAX_TOKENS,
    LEANSTRAL_ENDPOINT,
    LEANSTRAL_MODEL,
    CompletionClient,
    LeanstralClient,
    LeanstralClientError,
    LeanstralMalformedResponseError,
    LeanstralRequestError,
    LeanstralTimeoutError,
    LeanstralUnavailableError,
    canonical_ir_schema,
)


SELECTIVE_LEANSTRAL_REPAIR_INTERFACE: Final = "SelectiveLeanstralRepair@1"
HAMMER_CANDIDATE_SELECTOR_INTERFACE: Final = "HammerCandidateSelector@1"
SELECTIVE_REPAIR_POLICY_INTERFACE: Final = "SelectiveRepairPolicy@1"
SELECTIVE_REPAIR_RECEIPT_INTERFACE: Final = "SelectiveRepairCausalReceipt@1"
STRUCTURAL_VALIDATION_INTERFACE: Final = "StructuralCandidateValidation@1"
SELECTIVE_REPAIR_PROVIDER_ID: Final = "leanstral-local"
REPAIR_MAX_TOKENS: Final = CONSTRUCTOR_MAX_TOKENS

DEFAULT_LOW_CONFIDENCE_THRESHOLD: Final = 0.65
DEFAULT_MAX_REPAIR_SLOTS: Final = 4
DEFAULT_CANDIDATE_COUNT: Final = 2

DECLARED_SELECTION_RULES: Final = (
    "schema_valid",
    "nonempty",
    "same_rule_count",
    "only_triggered_fields_changed",
    "at_least_one_triggered_field_changed",
    "all_declared_structural_constraints_pass",
    "fewest_field_changes_then_call_order",
)
DECLARED_STRUCTURAL_CONSTRAINTS: Final = (
    "non_vacuous_candidate",
    "rule_cardinality_preserved",
    "untriggered_projection_preserved",
)

_REPAIR_SYSTEM: Final = (
    "You are repairing explicitly identified slots in an existing canonical "
    "legal-rule IR. Return exactly one compact JSON object matching the "
    "schema. Change only the listed repair targets. Preserve every other "
    "field and rule. Do not add rules, explain, or claim semantic or proof "
    "authority."
)


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _sha(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _detail(value: object, fallback: str) -> str:
    text = " ".join(str(value or fallback).split())
    return (text or fallback)[:1000]


class RepairTriggerKind(str, Enum):
    """The only outcome-independent reasons that may open a repair slot."""

    MISSING = "missing"
    CONTRADICTORY = "contradictory"
    LOW_CONFIDENCE = "low_confidence"


class RepairAttemptStatus(str, Enum):
    """Terminal state of one selective-repair intervention."""

    NOT_TRIGGERED = "not_triggered"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    FAILED = "failed"
    BASELINE_FAILED = "baseline_failed"


class ModelCallStatus(str, Enum):
    """Whether a model invocation returned a response object."""

    RETURNED = "returned"
    FAILED = "failed"


class StructuralTool(str, Enum):
    """Permitted proof-tool families; neither is a semantic authority."""

    HAMMER_CVC5 = "hammer_cvc5"
    LEAN = "lean"


@dataclass(frozen=True, slots=True)
class RepairTrigger:
    """One compiler-declared, case-local canonical slot trigger."""

    rule_index: int
    canonical_field: str
    kind: RepairTriggerKind
    confidence: float | None = None
    evidence: str | None = None

    def __post_init__(self) -> None:
        if (
            isinstance(self.rule_index, bool)
            or not isinstance(self.rule_index, int)
            or self.rule_index < 0
        ):
            raise ContractError("repair trigger rule_index must be nonnegative")
        if self.canonical_field not in RULE_FIELDS:
            raise ContractError(
                f"unknown repair trigger field: {self.canonical_field!r}"
            )
        if not isinstance(self.kind, RepairTriggerKind):
            try:
                object.__setattr__(self, "kind", RepairTriggerKind(self.kind))
            except (TypeError, ValueError) as exc:
                raise ContractError("repair trigger kind is invalid") from exc
        if self.confidence is not None and (
            isinstance(self.confidence, bool)
            or not isinstance(self.confidence, (int, float))
            or not math.isfinite(float(self.confidence))
            or not 0.0 <= float(self.confidence) <= 1.0
        ):
            raise ContractError("repair confidence must be from zero to one")
        if self.kind is RepairTriggerKind.LOW_CONFIDENCE:
            if self.confidence is None:
                raise ContractError(
                    "low-confidence trigger requires a confidence"
                )
            object.__setattr__(self, "confidence", float(self.confidence))
        if self.evidence is not None:
            cleaned = " ".join(self.evidence.split())
            if not cleaned:
                raise ContractError("repair trigger evidence must be nonblank")
            object.__setattr__(self, "evidence", cleaned[:1000])

    @property
    def path(self) -> str:
        return f"rules[{self.rule_index}].{self.canonical_field}"

    def to_dict(self) -> dict[str, object]:
        return {
            "canonical_field": self.canonical_field,
            "confidence": self.confidence,
            "evidence": self.evidence,
            "kind": self.kind.value,
            "path": self.path,
            "rule_index": self.rule_index,
        }


@dataclass(frozen=True, slots=True)
class SelectiveRepairPolicy:
    """Frozen trigger, budget, structural, and selection preregistration."""

    low_confidence_threshold: float = DEFAULT_LOW_CONFIDENCE_THRESHOLD
    max_repair_slots: int = DEFAULT_MAX_REPAIR_SLOTS
    candidate_count: int = DEFAULT_CANDIDATE_COUNT
    eligible_triggers: tuple[RepairTriggerKind, ...] = tuple(
        RepairTriggerKind
    )
    structural_constraints: tuple[str, ...] = (
        DECLARED_STRUCTURAL_CONSTRAINTS
    )
    selection_rules: tuple[str, ...] = DECLARED_SELECTION_RULES

    def __post_init__(self) -> None:
        if (
            isinstance(self.low_confidence_threshold, bool)
            or not isinstance(self.low_confidence_threshold, (int, float))
            or not math.isfinite(float(self.low_confidence_threshold))
            or not 0.0 <= float(self.low_confidence_threshold) <= 1.0
        ):
            raise ContractError(
                "low_confidence_threshold must be from zero to one"
            )
        object.__setattr__(
            self,
            "low_confidence_threshold",
            float(self.low_confidence_threshold),
        )
        for name in ("max_repair_slots", "candidate_count"):
            value = getattr(self, name)
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or value < 1
            ):
                raise ContractError(f"{name} must be a positive integer")
        if self.max_repair_slots > len(RULE_FIELDS) * 16:
            raise ContractError("max_repair_slots exceeds the canonical bound")
        if self.candidate_count > 8:
            raise ContractError("candidate_count exceeds the call bound")
        try:
            eligible = tuple(
                RepairTriggerKind(item) for item in self.eligible_triggers
            )
        except (TypeError, ValueError) as exc:
            raise ContractError("eligible repair trigger is invalid") from exc
        if not eligible or len(set(eligible)) != len(eligible):
            raise ContractError(
                "eligible_triggers must be nonempty and unique"
            )
        object.__setattr__(self, "eligible_triggers", eligible)
        if tuple(self.selection_rules) != DECLARED_SELECTION_RULES:
            raise ContractError(
                "selection_rules must equal the frozen declared rules"
            )
        constraints = tuple(self.structural_constraints)
        if (
            not constraints
            or len(set(constraints)) != len(constraints)
            or any(
                item not in DECLARED_STRUCTURAL_CONSTRAINTS
                for item in constraints
            )
        ):
            raise ContractError(
                "structural_constraints must be a unique nonempty subset "
                "of the declared structural constraints"
            )
        object.__setattr__(self, "structural_constraints", constraints)

    @property
    def digest(self) -> str:
        return _sha(self.to_dict())

    def to_dict(self) -> dict[str, object]:
        return {
            "candidate_count": self.candidate_count,
            "eligible_triggers": [
                item.value for item in self.eligible_triggers
            ],
            "interface": SELECTIVE_REPAIR_POLICY_INTERFACE,
            "low_confidence_threshold": self.low_confidence_threshold,
            "max_repair_slots": self.max_repair_slots,
            "selection_rules": list(self.selection_rules),
            "structural_constraints": list(self.structural_constraints),
        }

    def validate_triggers(
        self,
        baseline: CanonicalRuleIR,
        triggers: Sequence[RepairTrigger],
    ) -> tuple[RepairTrigger, ...]:
        if not isinstance(baseline, CanonicalRuleIR):
            raise ContractError("repair baseline must be CanonicalRuleIR")
        if isinstance(triggers, (str, bytes, bytearray)):
            raise ContractError("repair triggers must be a sequence")
        try:
            normalized = tuple(
                item
                if isinstance(item, RepairTrigger)
                else RepairTrigger(**dict(item))  # type: ignore[arg-type]
                for item in triggers
            )
        except (TypeError, ValueError) as exc:
            raise ContractError(
                "repair triggers must be RepairTrigger records"
            ) from exc
        if len(normalized) > self.max_repair_slots:
            raise ContractError("repair triggers exceed the preregistered bound")
        paths: set[str] = set()
        for trigger in normalized:
            if trigger.rule_index >= len(baseline.rules):
                raise ContractError(
                    f"repair trigger {trigger.path} is outside the baseline"
                )
            if trigger.kind not in self.eligible_triggers:
                raise ContractError(
                    f"repair trigger {trigger.kind.value} was not preregistered"
                )
            if trigger.path in paths:
                raise ContractError(
                    f"duplicate repair trigger for {trigger.path}"
                )
            paths.add(trigger.path)
            current = getattr(
                baseline.rules[trigger.rule_index],
                trigger.canonical_field,
            )
            if (
                trigger.kind is RepairTriggerKind.MISSING
                and current not in ("", ())
            ):
                raise ContractError(
                    f"missing trigger targets nonempty slot {trigger.path}"
                )
            if (
                trigger.kind is RepairTriggerKind.LOW_CONFIDENCE
                and trigger.confidence is not None
                and trigger.confidence >= self.low_confidence_threshold
            ):
                raise ContractError(
                    f"{trigger.path} confidence is not below the "
                    "preregistered threshold"
                )
        return tuple(
            sorted(
                normalized,
                key=lambda item: (
                    item.rule_index,
                    RULE_FIELDS.index(item.canonical_field),
                    item.kind.value,
                ),
            )
        )


@dataclass(frozen=True, slots=True)
class ModelCallRecord:
    """Content-bound record for every attempted Leanstral invocation."""

    call_id: str
    ordinal: int
    endpoint: str
    model: str
    prompt_sha256: str
    schema_sha256: str
    status: ModelCallStatus
    response_sha256: str | None = None
    failure_reason: FailureReason | None = None
    failure_detail: str | None = None

    def __post_init__(self) -> None:
        if not self.call_id or not self.prompt_sha256 or not self.schema_sha256:
            raise ContractError("model call identity digests must be nonempty")
        if (
            isinstance(self.ordinal, bool)
            or not isinstance(self.ordinal, int)
            or self.ordinal < 0
        ):
            raise ContractError("model call ordinal must be nonnegative")
        if self.endpoint != LEANSTRAL_ENDPOINT or self.model != LEANSTRAL_MODEL:
            raise ContractError("model call drifted from frozen Leanstral")
        if not isinstance(self.status, ModelCallStatus):
            raise ContractError("model call status is invalid")
        if self.status is ModelCallStatus.RETURNED:
            if (
                self.response_sha256 is None
                or self.failure_reason is not None
                or self.failure_detail is not None
            ):
                raise ContractError(
                    "returned model call requires only a response digest"
                )
        elif self.failure_reason is None or self.response_sha256 is not None:
            raise ContractError(
                "failed model call requires a reason and no response digest"
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "cache_prompt": False,
            "call_id": self.call_id,
            "endpoint": self.endpoint,
            "failure_detail": self.failure_detail,
            "failure_reason": (
                self.failure_reason.value
                if self.failure_reason is not None
                else None
            ),
            "max_tokens": REPAIR_MAX_TOKENS,
            "model": self.model,
            "ordinal": self.ordinal,
            "prompt_sha256": self.prompt_sha256,
            "provider_id": SELECTIVE_REPAIR_PROVIDER_ID,
            "response_sha256": self.response_sha256,
            "schema_name": "semantic_roundtrip_selective_repair_v1",
            "schema_sha256": self.schema_sha256,
            "seed": 0,
            "status": self.status.value,
            "system_sha256": hashlib.sha256(
                _REPAIR_SYSTEM.encode("utf-8")
            ).hexdigest(),
            "temperature": 0,
        }


@dataclass(frozen=True, slots=True)
class ModelCandidate:
    """One returned model payload paired with its mandatory call record."""

    call: ModelCallRecord
    payload: object

    def __post_init__(self) -> None:
        if self.call.status is not ModelCallStatus.RETURNED:
            raise ContractError("model candidate requires a returned call")


@dataclass(frozen=True, slots=True)
class StructuralValidationRequest:
    """Source- and gold-free request visible to a proof validator."""

    baseline_ir: CanonicalRuleIR
    candidate_ir: CanonicalRuleIR
    allowed_field_paths: tuple[str, ...]
    changed_field_paths: tuple[str, ...]
    constraints: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.baseline_ir, CanonicalRuleIR) or not isinstance(
            self.candidate_ir, CanonicalRuleIR
        ):
            raise ContractError("structural validation requires canonical IRs")
        object.__setattr__(
            self, "allowed_field_paths", tuple(self.allowed_field_paths)
        )
        object.__setattr__(
            self, "changed_field_paths", tuple(self.changed_field_paths)
        )
        object.__setattr__(self, "constraints", tuple(self.constraints))
        if not self.allowed_field_paths:
            raise ContractError(
                "structural validation requires bounded allowed fields"
            )
        if not self.constraints or any(
            item not in DECLARED_STRUCTURAL_CONSTRAINTS
            for item in self.constraints
        ):
            raise ContractError("structural validation constraint is invalid")

    def to_dict(self) -> dict[str, object]:
        return {
            "allowed_field_paths": list(self.allowed_field_paths),
            "baseline_ir": self.baseline_ir.to_dict(),
            "candidate_ir": self.candidate_ir.to_dict(),
            "changed_field_paths": list(self.changed_field_paths),
            "constraints": list(self.constraints),
            "semantic_authority": False,
        }


@dataclass(frozen=True, slots=True)
class StructuralValidationReceipt:
    """Non-authoritative proof-tool result for declared structure only."""

    validator_id: str
    tool: StructuralTool
    constraints: tuple[str, ...]
    passed: bool
    detail: str | None = None
    semantic_authority: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.validator_id, str) or not self.validator_id.strip():
            raise ContractError("validator_id must be nonblank")
        if not isinstance(self.tool, StructuralTool):
            try:
                object.__setattr__(self, "tool", StructuralTool(self.tool))
            except (TypeError, ValueError) as exc:
                raise ContractError("structural validation tool is invalid") from exc
        object.__setattr__(self, "constraints", tuple(self.constraints))
        if (
            not self.constraints
            or len(set(self.constraints)) != len(self.constraints)
            or any(
                item not in DECLARED_STRUCTURAL_CONSTRAINTS
                for item in self.constraints
            )
        ):
            raise ContractError(
                "receipt constraints must be declared structural constraints"
            )
        if not isinstance(self.passed, bool):
            raise ContractError("structural validation passed must be boolean")
        if self.semantic_authority is not False:
            raise ContractError(
                "Hammer/cvc5/Lean cannot claim semantic authority"
            )
        if self.detail is not None and not self.detail.strip():
            raise ContractError("structural validation detail must be nonblank")

    def to_dict(self) -> dict[str, object]:
        return {
            "constraints": list(self.constraints),
            "detail": self.detail,
            "interface": STRUCTURAL_VALIDATION_INTERFACE,
            "passed": self.passed,
            "semantic_authority": False,
            "tool": self.tool.value,
            "validator_id": self.validator_id,
        }


StructuralValidatorCallable = Callable[
    [StructuralValidationRequest], StructuralValidationReceipt
]


@dataclass(frozen=True, slots=True)
class StructuralValidatorBinding:
    """Preregistered proof-tool identity and its exact structural remit."""

    validator_id: str
    tool: StructuralTool
    constraints: tuple[str, ...]
    validate: StructuralValidatorCallable = field(
        repr=False, compare=False, hash=False
    )

    def __post_init__(self) -> None:
        if not isinstance(self.validator_id, str) or not self.validator_id.strip():
            raise ContractError("validator_id must be nonblank")
        if not isinstance(self.tool, StructuralTool):
            try:
                object.__setattr__(self, "tool", StructuralTool(self.tool))
            except (TypeError, ValueError) as exc:
                raise ContractError("structural validator tool is invalid") from exc
        object.__setattr__(self, "constraints", tuple(self.constraints))
        if (
            not self.constraints
            or len(set(self.constraints)) != len(self.constraints)
            or any(
                item not in DECLARED_STRUCTURAL_CONSTRAINTS
                for item in self.constraints
            )
        ):
            raise ContractError(
                "validator constraints must be declared structural constraints"
            )
        if not callable(self.validate):
            raise ContractError("structural validator must be callable")


@dataclass(frozen=True, slots=True)
class CandidateEvaluation:
    """Complete disposition of one returned model candidate."""

    call_id: str
    ordinal: int
    response_sha256: str
    canonical_ir: CanonicalRuleIR | None
    schema_valid: bool
    nonempty: bool
    field_changes: tuple[CanonicalFieldChange, ...]
    structural_receipts: tuple[StructuralValidationReceipt, ...]
    accepted: bool
    rejection_reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.call_id or not self.response_sha256:
            raise ContractError("candidate call and response identities are required")
        if (
            isinstance(self.ordinal, bool)
            or not isinstance(self.ordinal, int)
            or self.ordinal < 0
        ):
            raise ContractError("candidate ordinal must be nonnegative")
        if not isinstance(self.schema_valid, bool) or not isinstance(
            self.nonempty, bool
        ):
            raise ContractError("candidate validity flags must be booleans")
        if self.schema_valid != isinstance(self.canonical_ir, CanonicalRuleIR):
            raise ContractError(
                "schema-valid candidate disposition must retain canonical IR"
            )
        if self.nonempty != bool(
            self.canonical_ir is not None and not self.canonical_ir.is_empty
        ):
            raise ContractError("candidate nonempty disposition is inconsistent")
        object.__setattr__(self, "field_changes", tuple(self.field_changes))
        object.__setattr__(
            self, "structural_receipts", tuple(self.structural_receipts)
        )
        object.__setattr__(
            self, "rejection_reasons", tuple(self.rejection_reasons)
        )
        if not all(
            isinstance(item, CanonicalFieldChange)
            for item in self.field_changes
        ):
            raise ContractError("candidate field changes are invalid")
        if not all(
            isinstance(item, StructuralValidationReceipt)
            for item in self.structural_receipts
        ):
            raise ContractError("candidate structural receipts are invalid")
        if not isinstance(self.accepted, bool):
            raise ContractError("candidate accepted must be boolean")
        if self.accepted:
            if (
                not self.schema_valid
                or not self.nonempty
                or not self.field_changes
                or self.rejection_reasons
                or any(not item.passed for item in self.structural_receipts)
            ):
                raise ContractError("accepted candidate disposition is invalid")
        elif not self.rejection_reasons:
            raise ContractError("rejected candidate requires a reason")

    @property
    def changed_fields(self) -> tuple[str, ...]:
        changed = {item.canonical_field for item in self.field_changes}
        return tuple(field for field in RULE_FIELDS if field in changed)

    @property
    def changed_field_paths(self) -> tuple[str, ...]:
        return tuple(_change_path(item) for item in self.field_changes)

    def to_dict(self) -> dict[str, object]:
        return {
            "accepted": self.accepted,
            "call_id": self.call_id,
            "canonical_ir": (
                self.canonical_ir.to_dict()
                if self.canonical_ir is not None
                else None
            ),
            "changed_field_paths": list(self.changed_field_paths),
            "changed_fields": list(self.changed_fields),
            "field_changes": [
                item.to_dict() for item in self.field_changes
            ],
            "nonempty": self.nonempty,
            "ordinal": self.ordinal,
            "rejection_reasons": list(self.rejection_reasons),
            "response_sha256": self.response_sha256,
            "schema_valid": self.schema_valid,
            "structural_receipts": [
                item.to_dict() for item in self.structural_receipts
            ],
        }


@dataclass(frozen=True, slots=True)
class CandidateSelection:
    """All candidate dispositions plus the deterministic selected ordinal."""

    evaluations: tuple[CandidateEvaluation, ...]
    selected_ordinal: int | None
    selection_rules: tuple[str, ...] = DECLARED_SELECTION_RULES

    def __post_init__(self) -> None:
        object.__setattr__(self, "evaluations", tuple(self.evaluations))
        ordinals = [item.ordinal for item in self.evaluations]
        if len(set(ordinals)) != len(ordinals):
            raise ContractError("candidate ordinals must be unique")
        if tuple(self.selection_rules) != DECLARED_SELECTION_RULES:
            raise ContractError("candidate selection rules drifted")
        accepted = {
            item.ordinal for item in self.evaluations if item.accepted
        }
        if self.selected_ordinal is not None and (
            self.selected_ordinal not in accepted
        ):
            raise ContractError("selected candidate was not accepted")
        if accepted and self.selected_ordinal is None:
            raise ContractError("accepted candidates require a selection")
        if accepted:
            expected = min(
                (item for item in self.evaluations if item.accepted),
                key=lambda item: (
                    len(item.field_changes),
                    item.ordinal,
                    item.response_sha256,
                ),
            )
            if self.selected_ordinal != expected.ordinal:
                raise ContractError(
                    "selected candidate violates the preregistered ranking"
                )

    @property
    def selected(self) -> CandidateEvaluation | None:
        return next(
            (
                item
                for item in self.evaluations
                if item.ordinal == self.selected_ordinal
            ),
            None,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "evaluations": [item.to_dict() for item in self.evaluations],
            "selected_ordinal": self.selected_ordinal,
            "selection_rules": list(self.selection_rules),
        }


def _change_path(change: CanonicalFieldChange) -> str:
    if (
        change.baseline_rule_index is None
        or change.guided_rule_index is None
    ):
        return change.path
    return (
        f"rules[{change.baseline_rule_index}]."
        f"{change.canonical_field}"
    )


def _failed_structural_receipt(
    binding: StructuralValidatorBinding,
    detail: str,
) -> StructuralValidationReceipt:
    return StructuralValidationReceipt(
        validator_id=binding.validator_id,
        tool=binding.tool,
        constraints=binding.constraints,
        passed=False,
        detail=_detail(detail, "structural validator failed"),
    )


class HammerCandidateSelector:
    """Fail-closed structural filter with deterministic, nonsemantic ranking."""

    interface: Final = HAMMER_CANDIDATE_SELECTOR_INTERFACE

    def __init__(
        self,
        policy: SelectiveRepairPolicy | None = None,
        *,
        validators: Sequence[StructuralValidatorBinding] = (),
    ) -> None:
        self._policy = policy or SelectiveRepairPolicy()
        if not isinstance(self._policy, SelectiveRepairPolicy):
            raise ContractError("selector policy must be SelectiveRepairPolicy")
        self._validators = tuple(validators)
        if not all(
            isinstance(item, StructuralValidatorBinding)
            for item in self._validators
        ):
            raise ContractError(
                "validators must be StructuralValidatorBinding records"
            )
        identities = [item.validator_id for item in self._validators]
        if len(set(identities)) != len(identities):
            raise ContractError("structural validator identities must be unique")
        covered = {
            constraint
            for binding in self._validators
            for constraint in binding.constraints
        }
        expected = set(self._policy.structural_constraints)
        if covered and covered != expected:
            raise ContractError(
                "validator bindings must cover exactly the preregistered "
                "structural constraints"
            )

    @property
    def policy(self) -> SelectiveRepairPolicy:
        return self._policy

    @property
    def validators(self) -> tuple[StructuralValidatorBinding, ...]:
        return self._validators

    @property
    def capability_available(self) -> bool:
        return bool(self._validators)

    @property
    def identity(self) -> str:
        validators = ",".join(
            f"{item.tool.value}:{item.validator_id}"
            for item in self._validators
        ) or "unavailable"
        return f"{self.interface}:{self._policy.digest}:{validators}"

    def select(
        self,
        baseline_ir: CanonicalRuleIR,
        candidates: Sequence[ModelCandidate],
        allowed_atom_vocabulary: AllowedAtomVocabulary,
        triggers: Sequence[RepairTrigger],
    ) -> CandidateSelection:
        """Evaluate every candidate without source, gold, or semantic scores."""

        if not isinstance(baseline_ir, CanonicalRuleIR):
            raise ContractError("selector baseline must be CanonicalRuleIR")
        normalized_triggers = self._policy.validate_triggers(
            baseline_ir, triggers
        )
        allowed_paths = tuple(item.path for item in normalized_triggers)
        evaluations: list[CandidateEvaluation] = []
        for candidate in candidates:
            if not isinstance(candidate, ModelCandidate):
                raise ContractError(
                    "selector candidates must be ModelCandidate records"
                )
            reasons: list[str] = []
            receipts: list[StructuralValidationReceipt] = []
            changes: tuple[CanonicalFieldChange, ...] = ()
            canonical_ir: CanonicalRuleIR | None = None
            try:
                canonical_ir = CanonicalRuleIR.from_dict(
                    candidate.payload, allowed_atom_vocabulary
                )
                schema_valid = True
            except (ContractError, TypeError, ValueError) as exc:
                schema_valid = False
                reasons.append(f"schema_invalid:{_detail(exc, 'invalid IR')}")
            nonempty = bool(
                canonical_ir is not None and not canonical_ir.is_empty
            )
            if schema_valid and not nonempty:
                reasons.append("empty_candidate")
            if canonical_ir is not None:
                changes = canonical_field_changes(
                    baseline_ir, canonical_ir
                )
                if len(canonical_ir.rules) != len(baseline_ir.rules):
                    reasons.append("rule_cardinality_changed")
                if any(
                    item.baseline_rule_index is None
                    or item.guided_rule_index is None
                    for item in changes
                ):
                    reasons.append("rule_added_or_removed")
                changed_paths = tuple(_change_path(item) for item in changes)
                outside = sorted(set(changed_paths) - set(allowed_paths))
                if outside:
                    reasons.append(
                        "untriggered_fields_changed:" + ",".join(outside)
                    )
                if not changes:
                    reasons.append("no_triggered_field_changed")

            locally_valid = schema_valid and nonempty and not reasons
            if locally_valid and canonical_ir is not None:
                if not self._validators:
                    reasons.append("structural_validator_unavailable")
                else:
                    request_base = {
                        "baseline_ir": baseline_ir,
                        "candidate_ir": canonical_ir,
                        "allowed_field_paths": allowed_paths,
                        "changed_field_paths": tuple(
                            _change_path(item) for item in changes
                        ),
                    }
                    for binding in self._validators:
                        validation_request = StructuralValidationRequest(
                            **request_base,
                            constraints=binding.constraints,
                        )
                        try:
                            receipt = binding.validate(validation_request)
                            if not isinstance(
                                receipt, StructuralValidationReceipt
                            ):
                                raise ContractError(
                                    "validator returned a non-receipt"
                                )
                            if (
                                receipt.validator_id != binding.validator_id
                                or receipt.tool is not binding.tool
                                or receipt.constraints != binding.constraints
                            ):
                                raise ContractError(
                                    "validator receipt drifted from its binding"
                                )
                        except BaseException as exc:
                            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                                raise
                            receipt = _failed_structural_receipt(
                                binding,
                                "structural validator failed: "
                                + type(exc).__name__,
                            )
                        receipts.append(receipt)
                        if not receipt.passed:
                            reasons.append(
                                f"structural_rejection:{binding.validator_id}"
                            )

            evaluations.append(
                CandidateEvaluation(
                    call_id=candidate.call.call_id,
                    ordinal=candidate.call.ordinal,
                    response_sha256=candidate.call.response_sha256 or "",
                    canonical_ir=canonical_ir,
                    schema_valid=schema_valid,
                    nonempty=nonempty,
                    field_changes=changes,
                    structural_receipts=tuple(receipts),
                    accepted=not reasons,
                    rejection_reasons=tuple(reasons),
                )
            )
        accepted = [item for item in evaluations if item.accepted]
        selected = min(
            accepted,
            key=lambda item: (
                len(item.field_changes),
                item.ordinal,
                item.response_sha256,
            ),
            default=None,
        )
        return CandidateSelection(
            evaluations=tuple(evaluations),
            selected_ordinal=selected.ordinal if selected is not None else None,
        )


@runtime_checkable
class RepairTriggerDetector(Protocol):
    """Preregistered detector boundary for compiler-produced slot evidence."""

    @property
    def identity(self) -> str:
        """Return a stable, outcome-independent detector identity."""

    def detect(
        self,
        request: ConstructorRequest,
        baseline_ir: CanonicalRuleIR,
    ) -> Sequence[RepairTrigger]:
        """Return bounded case-local trigger evidence."""


class MissingCanonicalSlotDetector:
    """Conservative default that opens only objectively empty scalar slots."""

    identity: Final = "MissingCanonicalSlotDetector@1"

    def detect(
        self,
        request: ConstructorRequest,
        baseline_ir: CanonicalRuleIR,
    ) -> tuple[RepairTrigger, ...]:
        del request
        result: list[RepairTrigger] = []
        for index, rule in enumerate(baseline_ir.rules):
            # Empty object is valid for intransitive rules; actor and action
            # are the only unambiguously required scalar semantic slots.
            for canonical_field in ("actor", "action"):
                if getattr(rule, canonical_field) == "":
                    result.append(
                        RepairTrigger(
                            index,
                            canonical_field,
                            RepairTriggerKind.MISSING,
                            evidence="empty required scalar slot",
                        )
                    )
        return tuple(result)


@dataclass(frozen=True, slots=True)
class SelectiveRepairReceipt:
    """Causal receipt retaining every trigger, call, and candidate outcome."""

    status: RepairAttemptStatus
    policy: SelectiveRepairPolicy
    detector_identity: str
    baseline_identity: str
    selector_identity: str
    triggers: tuple[RepairTrigger, ...]
    model_calls: tuple[ModelCallRecord, ...]
    selection: CandidateSelection | None
    detail: str | None = None
    baseline_retained: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.status, RepairAttemptStatus):
            raise ContractError("selective repair status is invalid")
        if not isinstance(self.policy, SelectiveRepairPolicy):
            raise ContractError("receipt policy is invalid")
        for name in (
            "detector_identity",
            "baseline_identity",
            "selector_identity",
        ):
            if not isinstance(getattr(self, name), str) or not getattr(
                self, name
            ).strip():
                raise ContractError(f"{name} must be nonblank")
        if self.baseline_retained is not True:
            raise ContractError("the unrepaired baseline must be retained")
        object.__setattr__(self, "triggers", tuple(self.triggers))
        object.__setattr__(self, "model_calls", tuple(self.model_calls))
        if not all(isinstance(item, RepairTrigger) for item in self.triggers):
            raise ContractError("receipt triggers are invalid")
        if not all(
            isinstance(item, ModelCallRecord) for item in self.model_calls
        ):
            raise ContractError("receipt model calls are invalid")
        if len(self.model_calls) > self.policy.candidate_count:
            raise ContractError("receipt exceeds the preregistered call count")
        call_ids = [item.call_id for item in self.model_calls]
        if len(set(call_ids)) != len(call_ids):
            raise ContractError("receipt model call identities must be unique")
        if self.status is RepairAttemptStatus.NOT_TRIGGERED and (
            self.triggers or self.model_calls or self.selection is not None
        ):
            raise ContractError("untriggered repair cannot contain attempts")
        if self.status is RepairAttemptStatus.ACCEPTED and (
            self.selection is None or self.selection.selected is None
        ):
            raise ContractError("accepted repair requires selected candidate")
        if self.selection is not None:
            returned = {
                item.call_id
                for item in self.model_calls
                if item.status is ModelCallStatus.RETURNED
            }
            evaluated = {
                item.call_id for item in self.selection.evaluations
            }
            if returned != evaluated:
                raise ContractError(
                    "every returned model call must have one candidate "
                    "evaluation"
                )
        if self.detail is not None and not self.detail.strip():
            raise ContractError("repair receipt detail must be nonblank")

    @property
    def repair_attempted(self) -> bool:
        return bool(self.model_calls)

    @property
    def changed_fields(self) -> tuple[str, ...]:
        changed = {
            field
            for evaluation in (
                self.selection.evaluations if self.selection is not None else ()
            )
            for field in evaluation.changed_fields
        }
        return tuple(item for item in RULE_FIELDS if item in changed)

    @property
    def score_disposition(self) -> str:
        if self.status is RepairAttemptStatus.ACCEPTED:
            return "selected_candidate"
        if self.status is RepairAttemptStatus.NOT_TRIGGERED:
            return "unrepaired_baseline"
        return "failure_loss_one"

    @property
    def forced_loss(self) -> float | None:
        """Return the protocol loss forced for a failed repair arm."""

        if self.status in {
            RepairAttemptStatus.REJECTED,
            RepairAttemptStatus.FAILED,
            RepairAttemptStatus.BASELINE_FAILED,
        }:
            return 1.0
        return None

    def to_dict(self) -> dict[str, object]:
        return {
            "baseline_identity": self.baseline_identity,
            "baseline_retained": True,
            "changed_fields": list(self.changed_fields),
            "detail": self.detail,
            "detector_identity": self.detector_identity,
            "forced_loss": self.forced_loss,
            "interface": SELECTIVE_REPAIR_RECEIPT_INTERFACE,
            "model_calls": [item.to_dict() for item in self.model_calls],
            "policy": self.policy.to_dict(),
            "policy_sha256": self.policy.digest,
            "repair_attempted": self.repair_attempted,
            "score_disposition": self.score_disposition,
            "selection": (
                self.selection.to_dict()
                if self.selection is not None
                else None
            ),
            "selector_identity": self.selector_identity,
            "status": self.status.value,
            "triggers": [item.to_dict() for item in self.triggers],
        }


@dataclass(frozen=True, slots=True)
class SelectiveRepairConstruction:
    """Scored repair-arm result paired with its untouched baseline and receipt."""

    result: ConstructorResult
    baseline_result: ConstructorResult
    receipt: SelectiveRepairReceipt

    def __post_init__(self) -> None:
        if not isinstance(self.result, ConstructorResult) or not isinstance(
            self.baseline_result, ConstructorResult
        ):
            raise ContractError("repair construction results are invalid")
        if not isinstance(self.receipt, SelectiveRepairReceipt):
            raise ContractError("repair construction receipt is invalid")

    @property
    def scoring_result(self) -> ConstructorResult:
        """Result for the repair arm; rejected/failed attempts remain failures."""

        return self.result

    @property
    def unrepaired_baseline(self) -> ConstructorResult:
        return self.baseline_result

    @property
    def diagnostics(self) -> SelectiveRepairReceipt:
        return self.receipt

    @property
    def causal_receipt(self) -> dict[str, object]:
        return self.receipt.to_dict()


def _failure_result(reason: FailureReason, detail: str) -> ConstructorResult:
    return ConstructorResult(
        ComponentStatus.FAILED,
        failure_reason=reason,
        failure_detail=_detail(detail, "selective repair failed"),
    )


def _model_failure(exc: BaseException) -> tuple[FailureReason, str]:
    if isinstance(exc, (LeanstralTimeoutError, TimeoutError, socket.timeout)):
        return FailureReason.TIMEOUT, "Leanstral repair request timed out"
    if isinstance(exc, LeanstralUnavailableError):
        return (
            FailureReason.CAPABILITY_UNAVAILABLE,
            _detail(exc, "Leanstral repair capability is unavailable"),
        )
    if isinstance(
        exc,
        (
            LeanstralMalformedResponseError,
            LeanstralRequestError,
            ContractError,
            json.JSONDecodeError,
            TypeError,
            ValueError,
        ),
    ):
        return (
            FailureReason.INVALID_OUTPUT,
            _detail(exc, "Leanstral repair returned invalid output"),
        )
    if isinstance(exc, LeanstralClientError):
        return FailureReason.EXCEPTION, _detail(exc, "Leanstral repair failed")
    return (
        FailureReason.EXCEPTION,
        f"Leanstral repair raised {type(exc).__name__}",
    )


def _repair_prompt(
    request: ConstructorRequest,
    baseline_ir: CanonicalRuleIR,
    triggers: Sequence[RepairTrigger],
) -> str:
    return (
        "Repair the listed TARGET_SLOTS using the source. The entire returned "
        "IR must preserve the baseline outside those slots. Missing means an "
        "empty slot, contradictory means compiler evidence conflicts, and "
        "low_confidence means confidence was below the frozen threshold.\n"
        "ALLOWED_ATOMS_JSON:\n"
        + _canonical_json(request.allowed_atom_vocabulary.to_dict())
        + "\nBASELINE_CANONICAL_IR_JSON:\n"
        + _canonical_json(baseline_ir.to_dict())
        + "\nTARGET_SLOTS_JSON:\n"
        + _canonical_json([item.to_dict() for item in triggers])
        + "\nSOURCE_TEXT_JSON_STRING:\n"
        + _canonical_json(request.source_text)
    )


class SelectiveLeanstralRepair:
    """Round-trip constructor wrapper implementing selective learned repair."""

    interface: Final = SELECTIVE_LEANSTRAL_REPAIR_INTERFACE
    provider_id: Final = SELECTIVE_REPAIR_PROVIDER_ID

    def __init__(
        self,
        base_constructor: RoundTripConstructor | None = None,
        *,
        client: CompletionClient | None = None,
        policy: SelectiveRepairPolicy | None = None,
        selector: HammerCandidateSelector | None = None,
        trigger_detector: RepairTriggerDetector | None = None,
    ) -> None:
        if base_constructor is None:
            from benchmarks.semantic_roundtrip.constructors.typed_deontic import (
                TypedDeonticCanonicalConstructor,
            )

            base_constructor = TypedDeonticCanonicalConstructor()
        if not isinstance(base_constructor, RoundTripConstructor):
            raise ContractError(
                "base_constructor must implement RoundTripConstructor"
            )
        self._policy = policy or (
            selector.policy if selector is not None else SelectiveRepairPolicy()
        )
        if not isinstance(self._policy, SelectiveRepairPolicy):
            raise ContractError("repair policy must be SelectiveRepairPolicy")
        self._selector = selector or HammerCandidateSelector(self._policy)
        if not isinstance(self._selector, HammerCandidateSelector):
            raise ContractError("selector must be HammerCandidateSelector")
        if self._selector.policy != self._policy:
            raise ContractError(
                "repair and selector policies must be the same preregistration"
            )
        self._client = client or LeanstralClient()
        if (
            self._client.endpoint.rstrip("/") != LEANSTRAL_ENDPOINT
            or self._client.model != LEANSTRAL_MODEL
        ):
            raise ContractError(
                "repair client must bind the frozen Leanstral endpoint/model"
            )
        detector = trigger_detector or MissingCanonicalSlotDetector()
        if not isinstance(detector, RepairTriggerDetector):
            raise ContractError(
                "trigger_detector must expose a stable identity and detect"
            )
        if not detector.identity.strip():
            raise ContractError("trigger detector identity must be nonblank")
        self._base_constructor = base_constructor
        self._trigger_detector = detector

    @property
    def base_constructor(self) -> RoundTripConstructor:
        return self._base_constructor

    @property
    def policy(self) -> SelectiveRepairPolicy:
        return self._policy

    @property
    def selector(self) -> HammerCandidateSelector:
        return self._selector

    @property
    def identity(self) -> str:
        return (
            f"{self.interface}:{self._base_constructor.identity}:"
            f"{self._trigger_detector.identity}:{self._policy.digest}:"
            f"{self._selector.identity}:{LEANSTRAL_ENDPOINT}:{LEANSTRAL_MODEL}"
        )

    def _receipt(
        self,
        status: RepairAttemptStatus,
        *,
        triggers: tuple[RepairTrigger, ...] = (),
        calls: tuple[ModelCallRecord, ...] = (),
        selection: CandidateSelection | None = None,
        detail: str | None = None,
    ) -> SelectiveRepairReceipt:
        return SelectiveRepairReceipt(
            status=status,
            policy=self._policy,
            detector_identity=self._trigger_detector.identity,
            baseline_identity=self._base_constructor.identity,
            selector_identity=self._selector.identity,
            triggers=triggers,
            model_calls=calls,
            selection=selection,
            detail=detail,
        )

    def repair(
        self,
        request: ConstructorRequest,
        baseline_ir: CanonicalRuleIR,
        triggers: Sequence[RepairTrigger],
        *,
        baseline_result: ConstructorResult | None = None,
    ) -> SelectiveRepairConstruction:
        """Attempt repair against an already-bound unrepaired baseline."""

        if not isinstance(request, ConstructorRequest):
            raise ContractError("repair request must be ConstructorRequest")
        if not isinstance(baseline_ir, CanonicalRuleIR):
            raise ContractError("repair baseline must be CanonicalRuleIR")
        retained = baseline_result or ConstructorResult(
            ComponentStatus.SUCCESS, canonical_ir=baseline_ir
        )
        if (
            retained.status is not ComponentStatus.SUCCESS
            or retained.canonical_ir != baseline_ir
        ):
            raise ContractError(
                "baseline_result must be the successful supplied baseline"
            )
        try:
            baseline_ir.validate_vocabulary(
                request.allowed_atom_vocabulary
            )
            if baseline_ir.is_empty:
                raise ContractError("repair baseline must be nonempty")
        except ContractError as exc:
            result = _failure_result(FailureReason.INVALID_OUTPUT, str(exc))
            return SelectiveRepairConstruction(
                result,
                retained,
                self._receipt(
                    RepairAttemptStatus.FAILED,
                    detail=_detail(exc, "repair baseline validation failed"),
                ),
            )
        try:
            normalized = self._policy.validate_triggers(
                baseline_ir, triggers
            )
        except ContractError as exc:
            result = _failure_result(FailureReason.INVALID_OUTPUT, str(exc))
            return SelectiveRepairConstruction(
                result,
                retained,
                self._receipt(
                    RepairAttemptStatus.FAILED,
                    triggers=tuple(
                        item
                        for item in (
                            triggers
                            if isinstance(triggers, Sequence)
                            and not isinstance(
                                triggers, (str, bytes, bytearray)
                            )
                            else ()
                        )
                        if isinstance(item, RepairTrigger)
                    ),
                    detail=_detail(exc, "repair trigger validation failed"),
                ),
            )
        if not normalized:
            return SelectiveRepairConstruction(
                retained,
                retained,
                self._receipt(RepairAttemptStatus.NOT_TRIGGERED),
            )

        prompt = _repair_prompt(request, baseline_ir, normalized)
        schema = canonical_ir_schema(request.allowed_atom_vocabulary)
        prompt_sha256 = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        schema_sha256 = _sha(schema)
        call_records: list[ModelCallRecord] = []
        candidates: list[ModelCandidate] = []
        for ordinal in range(self._policy.candidate_count):
            call_id = _sha(
                {
                    "baseline": baseline_ir.to_dict(),
                    "ordinal": ordinal,
                    "policy_sha256": self._policy.digest,
                    "prompt_sha256": prompt_sha256,
                }
            )
            try:
                payload = self._client.complete_json(
                    system=_REPAIR_SYSTEM,
                    prompt=prompt,
                    schema_name="semantic_roundtrip_selective_repair_v1",
                    schema=schema,
                    max_tokens=REPAIR_MAX_TOKENS,
                )
                response_sha256 = _sha(payload)
                record = ModelCallRecord(
                    call_id=call_id,
                    ordinal=ordinal,
                    endpoint=LEANSTRAL_ENDPOINT,
                    model=LEANSTRAL_MODEL,
                    prompt_sha256=prompt_sha256,
                    schema_sha256=schema_sha256,
                    status=ModelCallStatus.RETURNED,
                    response_sha256=response_sha256,
                )
                candidates.append(ModelCandidate(record, payload))
            except BaseException as exc:
                if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                    raise
                reason, failure_detail = _model_failure(exc)
                record = ModelCallRecord(
                    call_id=call_id,
                    ordinal=ordinal,
                    endpoint=LEANSTRAL_ENDPOINT,
                    model=LEANSTRAL_MODEL,
                    prompt_sha256=prompt_sha256,
                    schema_sha256=schema_sha256,
                    status=ModelCallStatus.FAILED,
                    failure_reason=reason,
                    failure_detail=failure_detail,
                )
            call_records.append(record)

        selection = self._selector.select(
            baseline_ir,
            candidates,
            request.allowed_atom_vocabulary,
            normalized,
        )
        selected = selection.selected
        if selected is not None:
            assert selected.canonical_ir is not None
            result = ConstructorResult(
                ComponentStatus.SUCCESS,
                canonical_ir=selected.canonical_ir,
            )
            return SelectiveRepairConstruction(
                result,
                retained,
                self._receipt(
                    RepairAttemptStatus.ACCEPTED,
                    triggers=normalized,
                    calls=tuple(call_records),
                    selection=selection,
                ),
            )

        if candidates:
            detail = "every returned repair candidate was rejected"
            reason = FailureReason.INVALID_OUTPUT
            status = RepairAttemptStatus.REJECTED
        else:
            detail = "all preregistered Leanstral repair calls failed"
            reason = FailureReason.RETRY_EXHAUSTED
            status = RepairAttemptStatus.FAILED
        return SelectiveRepairConstruction(
            _failure_result(reason, detail),
            retained,
            self._receipt(
                status,
                triggers=normalized,
                calls=tuple(call_records),
                selection=selection,
                detail=detail,
            ),
        )

    def construct_with_diagnostics(
        self,
        request: ConstructorRequest,
        *,
        triggers: Sequence[RepairTrigger] | None = None,
    ) -> SelectiveRepairConstruction:
        """Run the baseline then the preregistered detector/repair policy."""

        if not isinstance(request, ConstructorRequest):
            failed = _failure_result(
                FailureReason.INVALID_OUTPUT,
                "request must be ConstructorRequest",
            )
            return SelectiveRepairConstruction(
                failed,
                failed,
                self._receipt(
                    RepairAttemptStatus.BASELINE_FAILED,
                    detail="request must be ConstructorRequest",
                ),
            )
        try:
            baseline = self._base_constructor.construct(request)
        except BaseException as exc:
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                raise
            baseline = _failure_result(
                FailureReason.EXCEPTION,
                f"baseline constructor raised {type(exc).__name__}",
            )
        if not isinstance(baseline, ConstructorResult):
            baseline = _failure_result(
                FailureReason.INVALID_OUTPUT,
                "baseline constructor returned a non-ConstructorResult",
            )
        if baseline.status is ComponentStatus.FAILED:
            return SelectiveRepairConstruction(
                baseline,
                baseline,
                self._receipt(
                    RepairAttemptStatus.BASELINE_FAILED,
                    detail="baseline failed before selective repair",
                ),
            )
        assert baseline.canonical_ir is not None
        if triggers is None:
            try:
                triggers = self._trigger_detector.detect(
                    request, baseline.canonical_ir
                )
            except BaseException as exc:
                if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                    raise
                failed = _failure_result(
                    FailureReason.EXCEPTION,
                    f"repair trigger detector raised {type(exc).__name__}",
                )
                return SelectiveRepairConstruction(
                    failed,
                    baseline,
                    self._receipt(
                        RepairAttemptStatus.FAILED,
                        detail=failed.failure_detail,
                    ),
                )
        return self.repair(
            request,
            baseline.canonical_ir,
            triggers,
            baseline_result=baseline,
        )

    construct_with_receipt = construct_with_diagnostics

    def construct(self, request: ConstructorRequest) -> ConstructorResult:
        """Return the scored repair arm while diagnostics retain its baseline."""

        return self.construct_with_diagnostics(request).result


SelectiveRepairResult = SelectiveRepairConstruction
SelectiveLeanstralCanonicalConstructor = SelectiveLeanstralRepair


assert isinstance(SelectiveLeanstralRepair(), RoundTripConstructor)


__all__ = [
    "SELECTIVE_LEANSTRAL_REPAIR_INTERFACE",
    "HAMMER_CANDIDATE_SELECTOR_INTERFACE",
    "SELECTIVE_REPAIR_POLICY_INTERFACE",
    "SELECTIVE_REPAIR_RECEIPT_INTERFACE",
    "STRUCTURAL_VALIDATION_INTERFACE",
    "SELECTIVE_REPAIR_PROVIDER_ID",
    "REPAIR_MAX_TOKENS",
    "DEFAULT_LOW_CONFIDENCE_THRESHOLD",
    "DEFAULT_MAX_REPAIR_SLOTS",
    "DEFAULT_CANDIDATE_COUNT",
    "DECLARED_SELECTION_RULES",
    "DECLARED_STRUCTURAL_CONSTRAINTS",
    "RepairTriggerKind",
    "RepairAttemptStatus",
    "ModelCallStatus",
    "StructuralTool",
    "RepairTrigger",
    "SelectiveRepairPolicy",
    "ModelCallRecord",
    "ModelCandidate",
    "StructuralValidationRequest",
    "StructuralValidationReceipt",
    "StructuralValidatorBinding",
    "CandidateEvaluation",
    "CandidateSelection",
    "HammerCandidateSelector",
    "RepairTriggerDetector",
    "MissingCanonicalSlotDetector",
    "SelectiveRepairReceipt",
    "SelectiveRepairConstruction",
    "SelectiveRepairResult",
    "SelectiveLeanstralRepair",
    "SelectiveLeanstralCanonicalConstructor",
]
