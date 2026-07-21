"""Closed-loop lineage for LegalIR compiler repair cycles.

Leanstral, Hammer, Codex, and the modal TODO queue each produce useful repair
evidence, but only the next deterministic compiler cycle can prove whether a
patch helped.  This module keeps those boundaries explicit: it links every
piece of repair evidence with stable identities and timestamps, classifies the
closed-loop outcome, and exports future-prioritization records only when the
outcome was observed by deterministic compiler evidence.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from types import MappingProxyType
from typing import Any, Final, Optional


COMPILER_REPAIR_LINEAGE_SCHEMA_VERSION: Final = "legal-ir-compiler-repair-lineage-v1"
COMPILER_REPAIR_PRIORITIZATION_SCHEMA_VERSION: Final = (
    "legal-ir-compiler-repair-prioritization-v1"
)

STATE_SNAPSHOT = "state_snapshot"
METRIC_GAP = "metric_gap"
LEANSTRAL_AUDIT = "leanstral_audit"
HAMMER_RECEIPT = "hammer_receipt"
RULE_GAP_REPORT = "rule_gap_report"
TODO = "todo"
CODEX_ATTEMPT = "codex_attempt"
VALIDATION = "validation"
MERGE = "merge"
NEXT_CYCLE_OBSERVATION = "next_cycle_observation"

REQUIRED_REPAIR_EVIDENCE_KINDS: Final[tuple[str, ...]] = (
    STATE_SNAPSHOT,
    METRIC_GAP,
    LEANSTRAL_AUDIT,
    HAMMER_RECEIPT,
    RULE_GAP_REPORT,
    TODO,
    CODEX_ATTEMPT,
    VALIDATION,
    MERGE,
    NEXT_CYCLE_OBSERVATION,
)
VALID_REPAIR_EVIDENCE_KINDS: Final[frozenset[str]] = frozenset(
    REQUIRED_REPAIR_EVIDENCE_KINDS
)

DETERMINISTIC_EVIDENCE_DEFAULTS: Final[frozenset[str]] = frozenset(
    {
        STATE_SNAPSHOT,
        METRIC_GAP,
        HAMMER_RECEIPT,
        RULE_GAP_REPORT,
        TODO,
        VALIDATION,
        MERGE,
        NEXT_CYCLE_OBSERVATION,
    }
)

_OPERATIONAL_FAILURE_STATUSES: Final[frozenset[str]] = frozenset(
    {
        "action_failed",
        "apply_conflict",
        "apply_failed",
        "cancelled",
        "canceled",
        "failed_to_apply",
        "infrastructure_failure",
        "interrupted",
        "lock_timeout",
        "main_apply_dirty_target",
        "main_apply_dirty_target_repair_failed",
        "main_apply_lock_timeout",
        "malformed_response",
        "missing",
        "not_measured",
        "provider_timeout",
        "resource_exhaustion",
        "timeout",
        "transport",
        "unavailable",
        "worktree_unavailable",
    }
)
_MERGE_ACCEPTED_STATUSES: Final[frozenset[str]] = frozenset(
    {"applied", "committed", "merged", "passed", "skipped"}
)
_VALIDATION_FAILED_STATUSES: Final[frozenset[str]] = frozenset(
    {"deterministic_test_failure", "failed", "failed_validation", "rejected"}
)
_PASSED_OR_ACCEPTED_STATUSES: Final[frozenset[str]] = frozenset(
    {
        "accepted",
        "applied",
        "completed",
        "improved",
        "measured",
        "merged",
        "passed",
        "passed_with_tradeoff",
        "succeeded",
        "verified",
    }
)


class CompilerRepairLineageError(RuntimeError):
    """Base class for closed-loop repair lineage failures."""


class CompilerRepairLineageValidationError(CompilerRepairLineageError, ValueError):
    """Raised when a lineage record is incomplete or ambiguous."""


class CompilerRepairOutcome(str, Enum):
    """Stable outcome classes for one closed compiler repair loop."""

    ACCEPTED_BENEFIT = "accepted_benefit"
    NEUTRAL_CHANGE = "neutral_change"
    QUALITY_REGRESSION = "quality_regression"
    DISPROVEN_HYPOTHESIS = "disproven_hypothesis"
    STALE_EVIDENCE = "stale_evidence"
    OPERATIONAL_FAILURE = "operational_failure"

    @classmethod
    def coerce(cls, value: "CompilerRepairOutcome | str") -> "CompilerRepairOutcome":
        if isinstance(value, cls):
            return value
        normalized = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
        aliases = {
            "accepted": cls.ACCEPTED_BENEFIT,
            "accepted_improvement": cls.ACCEPTED_BENEFIT,
            "benefit": cls.ACCEPTED_BENEFIT,
            "improved": cls.ACCEPTED_BENEFIT,
            "neutral": cls.NEUTRAL_CHANGE,
            "no_change": cls.NEUTRAL_CHANGE,
            "regressed": cls.QUALITY_REGRESSION,
            "metric_regression": cls.QUALITY_REGRESSION,
            "quality_regressed": cls.QUALITY_REGRESSION,
            "unsupported_hypothesis": cls.DISPROVEN_HYPOTHESIS,
            "rejected_hypothesis": cls.DISPROVEN_HYPOTHESIS,
            "stale": cls.STALE_EVIDENCE,
            "failed_operationally": cls.OPERATIONAL_FAILURE,
            "infrastructure_failure": cls.OPERATIONAL_FAILURE,
        }
        if normalized in aliases:
            return aliases[normalized]
        try:
            return cls(normalized)
        except ValueError as exc:
            expected = ", ".join(outcome.value for outcome in cls)
            raise ValueError(f"unsupported compiler repair outcome {value!r}; expected {expected}") from exc


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _canonical_timestamp(value: Any, *, field_name: str = "observed_at") -> str:
    text = str(value or "").strip()
    if not text:
        raise CompilerRepairLineageValidationError(f"{field_name} must be a timestamp")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise CompilerRepairLineageValidationError(
            f"{field_name} must be an ISO-8601 timestamp"
        ) from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def _json_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise CompilerRepairLineageValidationError(
                "lineage payload contains a non-finite float"
            )
        return value
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {
            str(key): _json_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_json_value(item) for item in value]
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        return _json_value(to_dict())
    if hasattr(value, "__dict__"):
        return _json_value(
            {
                str(key): item
                for key, item in vars(value).items()
                if not str(key).startswith("_")
            }
        )
    return str(value)


def _stable_digest(value: Any) -> str:
    payload = json.dumps(
        _json_value(value),
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _atom(value: Any, *, name: str, default: str = "") -> str:
    text = str(value or default).strip()
    if not text:
        raise CompilerRepairLineageValidationError(f"{name} must be non-empty")
    if any(character in text for character in "\r\n\0"):
        raise CompilerRepairLineageValidationError(f"{name} contains invalid characters")
    return text


def _optional_atom(value: Any) -> str:
    text = str(value or "").strip()
    if any(character in text for character in "\r\n\0"):
        raise CompilerRepairLineageValidationError("lineage text contains invalid characters")
    return text


def _freeze_mapping(value: Mapping[str, Any]) -> Mapping[str, Any]:
    return MappingProxyType(_json_value(dict(value)))


def _as_sequence(value: Any) -> tuple[Any, ...]:
    if value is None:
        return ()
    if isinstance(value, (str, bytes, bytearray)):
        return (value,)
    if isinstance(value, Sequence):
        return tuple(value)
    return (value,)


def _status_tokens(payload: Mapping[str, Any]) -> tuple[str, ...]:
    keys = (
        "apply_status",
        "codex_exec_status",
        "exec_status",
        "main_apply_status",
        "main_apply_validation_status",
        "merge_status",
        "outcome",
        "patch_status",
        "result",
        "status",
        "target_metric_status",
        "validation_status",
    )
    tokens: list[str] = []
    for key in keys:
        value = payload.get(key)
        if value is None:
            continue
        token = str(value).strip().lower().replace("-", "_").replace(" ", "_")
        if token:
            tokens.append(token)
    for nested_key in (
        "codex_exec",
        "holdout_target_metric_validation",
        "main_apply_validation",
        "target_metric_validation",
        "validation",
    ):
        nested = payload.get(nested_key)
        if isinstance(nested, Mapping):
            tokens.extend(_status_tokens(nested))
    return tuple(dict.fromkeys(tokens))


def _numeric_mapping(value: Any, prefix: str = "") -> dict[str, float]:
    result: dict[str, float] = {}
    if isinstance(value, Mapping):
        for key, item in value.items():
            child_key = f"{prefix}.{key}" if prefix else str(key)
            result.update(_numeric_mapping(item, child_key))
        return result
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for index, item in enumerate(value):
            child_key = f"{prefix}.{index}" if prefix else str(index)
            result.update(_numeric_mapping(item, child_key))
        return result
    if not prefix or isinstance(value, bool):
        return result
    try:
        number = float(value)
    except (TypeError, ValueError):
        return result
    if math.isfinite(number):
        result[prefix] = number
    return result


def _metric_deltas(payload: Mapping[str, Any]) -> dict[str, float]:
    deltas: dict[str, float] = {}
    for key in ("metric_deltas", "holdout_metric_deltas", "weighted_metric_deltas"):
        deltas.update(_numeric_mapping(payload.get(key) or {}))
    for nested_key in (
        "next_cycle_observation",
        "target_metric_validation",
        "holdout_target_metric_validation",
        "validation_report",
    ):
        nested = payload.get(nested_key)
        if isinstance(nested, Mapping):
            deltas.update(_metric_deltas(nested))
    return {key: round(value, 12) for key, value in sorted(deltas.items())}


def _objective_delta(payload: Mapping[str, Any]) -> Optional[float]:
    for key in (
        "objective_delta",
        "holdout_objective_delta",
        "target_metric_objective_delta",
        "weighted_objective_delta",
    ):
        if key not in payload:
            continue
        try:
            value = float(payload[key])
        except (TypeError, ValueError):
            continue
        if math.isfinite(value):
            return round(value, 12)
    for nested_key in (
        "next_cycle_observation",
        "target_metric_validation",
        "holdout_target_metric_validation",
        "validation_report",
    ):
        nested = payload.get(nested_key)
        if isinstance(nested, Mapping):
            value = _objective_delta(nested)
            if value is not None:
                return value
    return None


def _string_list(value: Any) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(str(item).strip() for item in _as_sequence(value) if str(item).strip())
    )


def _stable_id_from_mapping(kind: str, payload: Mapping[str, Any]) -> str:
    for key in (
        "stable_id",
        "evidence_id",
        "id",
        "snapshot_id",
        "gap_id",
        "audit_id",
        "request_id",
        "receipt_id",
        "report_id",
        "todo_id",
        "attempt_id",
        "packet_id",
        "validation_id",
        "merge_id",
        "observation_id",
    ):
        value = str(payload.get(key) or "").strip()
        if value:
            return value
    nested = payload.get("payload")
    if isinstance(nested, Mapping):
        for key in (
            "stable_id",
            "evidence_id",
            "id",
            "snapshot_id",
            "gap_id",
            "audit_id",
            "request_id",
            "receipt_id",
            "report_id",
            "todo_id",
            "attempt_id",
            "packet_id",
            "validation_id",
            "merge_id",
            "observation_id",
        ):
            value = str(nested.get(key) or "").strip()
            if value:
                return value
    return f"{kind}:{_stable_digest(payload)[:24]}"


def _timestamp_from_mapping(payload: Mapping[str, Any]) -> str:
    for key in (
        "observed_at",
        "timestamp",
        "created_at",
        "completed_at",
        "validated_at",
        "merged_at",
        "started_at",
        "finished_at",
        "updated_at",
    ):
        value = str(payload.get(key) or "").strip()
        if value:
            return value
    nested = payload.get("payload")
    if isinstance(nested, Mapping):
        for key in (
            "observed_at",
            "timestamp",
            "created_at",
            "completed_at",
            "validated_at",
            "merged_at",
            "started_at",
            "finished_at",
            "updated_at",
        ):
            value = str(nested.get(key) or "").strip()
            if value:
                return value
    raise CompilerRepairLineageValidationError(
        "evidence mapping must include observed_at or another timestamp field"
    )


@dataclass(frozen=True, slots=True)
class CompilerRepairEvidenceRef:
    """One immutable evidence handle in a closed-loop repair chain."""

    kind: str
    stable_id: str
    observed_at: str
    payload: Mapping[str, Any] = field(default_factory=dict)
    source: str = ""
    deterministic: bool = False
    observed: bool = True
    payload_digest: str = ""

    def __post_init__(self) -> None:
        kind = _atom(self.kind, name="kind")
        if kind not in VALID_REPAIR_EVIDENCE_KINDS:
            raise CompilerRepairLineageValidationError(
                f"unsupported repair evidence kind {kind!r}"
            )
        stable_id = _atom(self.stable_id, name="stable_id")
        payload = self.payload if isinstance(self.payload, Mapping) else {}
        frozen_payload = _freeze_mapping(payload)
        payload_digest = str(self.payload_digest or "").strip() or _stable_digest(
            frozen_payload
        )
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "stable_id", stable_id)
        object.__setattr__(
            self,
            "observed_at",
            _canonical_timestamp(self.observed_at, field_name=f"{kind}.observed_at"),
        )
        object.__setattr__(self, "payload", frozen_payload)
        object.__setattr__(self, "source", _optional_atom(self.source))
        object.__setattr__(self, "deterministic", bool(self.deterministic))
        object.__setattr__(self, "observed", bool(self.observed))
        object.__setattr__(self, "payload_digest", payload_digest)

    @property
    def identity(self) -> str:
        return f"{self.kind}:{self.stable_id}"

    def to_dict(self, *, include_payload: bool = True) -> dict[str, Any]:
        payload = {
            "deterministic": self.deterministic,
            "identity": self.identity,
            "kind": self.kind,
            "observed": self.observed,
            "observed_at": self.observed_at,
            "payload_digest": self.payload_digest,
            "source": self.source,
            "stable_id": self.stable_id,
        }
        if include_payload:
            payload["payload"] = _json_value(self.payload)
        return payload

    @classmethod
    def from_mapping(
        cls,
        payload: Mapping[str, Any],
        *,
        kind: Optional[str] = None,
    ) -> "CompilerRepairEvidenceRef":
        evidence_kind = str(kind or payload.get("kind") or "").strip()
        if not evidence_kind:
            raise CompilerRepairLineageValidationError("evidence kind must be supplied")
        deterministic = payload.get("deterministic")
        if deterministic is None:
            deterministic = evidence_kind in DETERMINISTIC_EVIDENCE_DEFAULTS
        raw_payload = payload.get("payload")
        if not isinstance(raw_payload, Mapping):
            raw_payload = {
                key: value
                for key, value in payload.items()
                if key
                not in {
                    "deterministic",
                    "identity",
                    "kind",
                    "observed",
                    "observed_at",
                    "payload",
                    "payload_digest",
                    "source",
                    "stable_id",
                }
            }
        return cls(
            kind=evidence_kind,
            stable_id=_stable_id_from_mapping(evidence_kind, payload),
            observed_at=_timestamp_from_mapping(payload),
            payload=raw_payload,
            source=str(payload.get("source") or ""),
            deterministic=bool(deterministic),
            observed=bool(payload.get("observed", True)),
            payload_digest=str(payload.get("payload_digest") or ""),
        )


@dataclass(frozen=True, slots=True)
class CompilerRepairLineageLink:
    """A deterministic edge linking two evidence handles."""

    source_kind: str
    source_id: str
    target_kind: str
    target_id: str
    relation: str
    observed_at: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_kind", _atom(self.source_kind, name="source_kind"))
        object.__setattr__(self, "source_id", _atom(self.source_id, name="source_id"))
        object.__setattr__(self, "target_kind", _atom(self.target_kind, name="target_kind"))
        object.__setattr__(self, "target_id", _atom(self.target_id, name="target_id"))
        object.__setattr__(self, "relation", _atom(self.relation, name="relation"))
        object.__setattr__(
            self,
            "observed_at",
            _canonical_timestamp(self.observed_at, field_name="link.observed_at"),
        )

    @property
    def stable_id(self) -> str:
        return "repair-link:" + _stable_digest(
            {
                "relation": self.relation,
                "source_id": self.source_id,
                "source_kind": self.source_kind,
                "target_id": self.target_id,
                "target_kind": self.target_kind,
            }
        )[:24]

    def to_dict(self) -> dict[str, Any]:
        return {
            "observed_at": self.observed_at,
            "relation": self.relation,
            "source_id": self.source_id,
            "source_kind": self.source_kind,
            "stable_id": self.stable_id,
            "target_id": self.target_id,
            "target_kind": self.target_kind,
        }


@dataclass(frozen=True, slots=True)
class CompilerRepairClassification:
    """Outcome and deterministic evidence summary for one lineage."""

    outcome: CompilerRepairOutcome
    reason: str
    observed_at: str
    metric_deltas: Mapping[str, float] = field(default_factory=dict)
    objective_delta: Optional[float] = None
    regressed_metrics: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    deterministic_next_cycle: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "outcome", CompilerRepairOutcome.coerce(self.outcome))
        object.__setattr__(
            self,
            "observed_at",
            _canonical_timestamp(self.observed_at, field_name="classification.observed_at"),
        )
        object.__setattr__(
            self,
            "metric_deltas",
            MappingProxyType(
                {
                    str(key): float(value)
                    for key, value in sorted(dict(self.metric_deltas or {}).items())
                    if math.isfinite(float(value))
                }
            ),
        )
        object.__setattr__(self, "regressed_metrics", _string_list(self.regressed_metrics))
        object.__setattr__(self, "evidence_ids", _string_list(self.evidence_ids))
        if self.objective_delta is not None:
            objective_delta = float(self.objective_delta)
            if not math.isfinite(objective_delta):
                raise CompilerRepairLineageValidationError(
                    "objective_delta must be finite when present"
                )
            object.__setattr__(self, "objective_delta", round(objective_delta, 12))

    def to_dict(self) -> dict[str, Any]:
        return {
            "deterministic_next_cycle": self.deterministic_next_cycle,
            "evidence_ids": list(self.evidence_ids),
            "metric_deltas": dict(self.metric_deltas),
            "objective_delta": self.objective_delta,
            "observed_at": self.observed_at,
            "outcome": self.outcome.value,
            "reason": self.reason,
            "regressed_metrics": list(self.regressed_metrics),
        }


@dataclass(frozen=True, slots=True)
class CompilerRepairPrioritizationSignal:
    """One deterministic closed-loop input allowed into future prioritization."""

    lineage_id: str
    task_id: str
    todo_id: str
    outcome: CompilerRepairOutcome
    observed_at: str
    eligible: bool
    weight_delta: float
    reason: str
    metric_deltas: Mapping[str, float] = field(default_factory=dict)
    target_metrics: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    schema_version: str = COMPILER_REPAIR_PRIORITIZATION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "lineage_id", _atom(self.lineage_id, name="lineage_id"))
        object.__setattr__(self, "task_id", _optional_atom(self.task_id))
        object.__setattr__(self, "todo_id", _optional_atom(self.todo_id))
        object.__setattr__(self, "outcome", CompilerRepairOutcome.coerce(self.outcome))
        object.__setattr__(
            self,
            "observed_at",
            _canonical_timestamp(self.observed_at, field_name="signal.observed_at"),
        )
        weight_delta = float(self.weight_delta)
        if not math.isfinite(weight_delta):
            raise CompilerRepairLineageValidationError("weight_delta must be finite")
        object.__setattr__(self, "weight_delta", round(weight_delta, 12))
        object.__setattr__(
            self,
            "metric_deltas",
            MappingProxyType(
                {
                    str(key): float(value)
                    for key, value in sorted(dict(self.metric_deltas or {}).items())
                    if math.isfinite(float(value))
                }
            ),
        )
        object.__setattr__(self, "target_metrics", _string_list(self.target_metrics))
        object.__setattr__(self, "evidence_ids", _string_list(self.evidence_ids))
        if self.schema_version != COMPILER_REPAIR_PRIORITIZATION_SCHEMA_VERSION:
            raise CompilerRepairLineageValidationError(
                "prioritization signal schema version is stale"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "eligible": bool(self.eligible),
            "evidence_ids": list(self.evidence_ids),
            "lineage_id": self.lineage_id,
            "metric_deltas": dict(self.metric_deltas),
            "observed_at": self.observed_at,
            "outcome": self.outcome.value,
            "reason": self.reason,
            "schema_version": self.schema_version,
            "task_id": self.task_id,
            "target_metrics": list(self.target_metrics),
            "todo_id": self.todo_id,
            "weight_delta": self.weight_delta,
        }


@dataclass(frozen=True, slots=True)
class CompilerRepairLineage:
    """A complete attribution chain from state evidence to next-cycle outcome."""

    task_id: str
    attempt: int
    evidence_refs: tuple[CompilerRepairEvidenceRef, ...]
    links: tuple[CompilerRepairLineageLink, ...] = ()
    created_at: str = field(default_factory=_utc_now)
    schema_version: str = COMPILER_REPAIR_LINEAGE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if int(self.attempt) < 1:
            raise CompilerRepairLineageValidationError("attempt must be at least one")
        object.__setattr__(self, "task_id", _optional_atom(self.task_id))
        object.__setattr__(self, "attempt", int(self.attempt))
        evidence = tuple(
            item
            if isinstance(item, CompilerRepairEvidenceRef)
            else CompilerRepairEvidenceRef.from_mapping(item)  # type: ignore[arg-type]
            for item in self.evidence_refs
        )
        _require_complete_evidence(evidence)
        object.__setattr__(self, "evidence_refs", evidence)
        links = tuple(self.links or _default_links(evidence))
        object.__setattr__(self, "links", links)
        _require_linked_evidence(evidence, links)
        object.__setattr__(
            self,
            "created_at",
            _canonical_timestamp(self.created_at, field_name="lineage.created_at"),
        )
        if self.schema_version != COMPILER_REPAIR_LINEAGE_SCHEMA_VERSION:
            raise CompilerRepairLineageValidationError("lineage schema version is stale")

    @property
    def stable_id(self) -> str:
        return "compiler-repair-lineage:" + _stable_digest(
            {
                "attempt": self.attempt,
                "evidence": [
                    {
                        "kind": ref.kind,
                        "observed_at": ref.observed_at,
                        "payload_digest": ref.payload_digest,
                        "stable_id": ref.stable_id,
                    }
                    for ref in self.evidence_refs
                ],
                "schema_version": self.schema_version,
                "task_id": self.task_id,
            }
        )[:32]

    @property
    def evidence_by_kind(self) -> Mapping[str, CompilerRepairEvidenceRef]:
        return MappingProxyType({ref.kind: ref for ref in self.evidence_refs})

    @property
    def todo_id(self) -> str:
        todo_ref = self.evidence_by_kind[TODO]
        return str(todo_ref.payload.get("todo_id") or todo_ref.stable_id)

    def classify(self) -> CompilerRepairClassification:
        return CompilerRepairLineageClassifier().classify(self)

    def prioritization_signal(self) -> CompilerRepairPrioritizationSignal:
        classification = self.classify()
        return prioritization_signal_from_lineage(self, classification=classification)

    def to_dict(self, *, include_payload: bool = True) -> dict[str, Any]:
        classification = self.classify()
        return {
            "attempt": self.attempt,
            "classification": classification.to_dict(),
            "created_at": self.created_at,
            "evidence_refs": [
                ref.to_dict(include_payload=include_payload) for ref in self.evidence_refs
            ],
            "links": [link.to_dict() for link in self.links],
            "schema_version": self.schema_version,
            "stable_id": self.stable_id,
            "task_id": self.task_id,
        }

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "CompilerRepairLineage":
        return cls(
            task_id=str(payload.get("task_id") or ""),
            attempt=int(payload.get("attempt") or 1),
            evidence_refs=tuple(
                CompilerRepairEvidenceRef.from_mapping(item)
                for item in payload.get("evidence_refs", ()) or ()
                if isinstance(item, Mapping)
            ),
            links=tuple(
                CompilerRepairLineageLink(
                    source_kind=str(item.get("source_kind") or ""),
                    source_id=str(item.get("source_id") or ""),
                    target_kind=str(item.get("target_kind") or ""),
                    target_id=str(item.get("target_id") or ""),
                    relation=str(item.get("relation") or "caused"),
                    observed_at=str(item.get("observed_at") or payload.get("created_at") or ""),
                )
                for item in payload.get("links", ()) or ()
                if isinstance(item, Mapping)
            ),
            created_at=str(payload.get("created_at") or _utc_now()),
            schema_version=str(payload.get("schema_version") or ""),
        )


class CompilerRepairLineageClassifier:
    """Classify a complete compiler repair lineage from observed artifacts."""

    def classify(self, lineage: CompilerRepairLineage) -> CompilerRepairClassification:
        refs = lineage.evidence_by_kind
        next_ref = refs[NEXT_CYCLE_OBSERVATION]
        validation_ref = refs[VALIDATION]
        merge_ref = refs[MERGE]
        evidence_ids = tuple(ref.identity for ref in lineage.evidence_refs)
        next_payload = dict(next_ref.payload)
        validation_payload = dict(validation_ref.payload)
        merge_payload = dict(merge_ref.payload)
        combined = _merge_payloads(validation_payload, next_payload)
        metric_deltas = _metric_deltas(combined)
        objective_delta = _objective_delta(combined)
        regressed_metrics = _regressed_metrics(combined)

        if _has_stale_evidence(refs):
            return CompilerRepairClassification(
                CompilerRepairOutcome.STALE_EVIDENCE,
                reason="lineage_contains_stale_or_mismatched_state_evidence",
                observed_at=next_ref.observed_at,
                metric_deltas=metric_deltas,
                objective_delta=objective_delta,
                regressed_metrics=regressed_metrics,
                evidence_ids=evidence_ids,
                deterministic_next_cycle=next_ref.deterministic and next_ref.observed,
            )

        if _operational_failure(refs):
            return CompilerRepairClassification(
                CompilerRepairOutcome.OPERATIONAL_FAILURE,
                reason="codex_validation_merge_or_observation_was_operationally_incomplete",
                observed_at=next_ref.observed_at,
                metric_deltas=metric_deltas,
                objective_delta=objective_delta,
                regressed_metrics=regressed_metrics,
                evidence_ids=evidence_ids,
                deterministic_next_cycle=next_ref.deterministic and next_ref.observed,
            )

        if _is_quality_regression(combined, regressed_metrics, objective_delta):
            return CompilerRepairClassification(
                CompilerRepairOutcome.QUALITY_REGRESSION,
                reason="deterministic_compiler_metrics_regressed",
                observed_at=next_ref.observed_at,
                metric_deltas=metric_deltas,
                objective_delta=objective_delta,
                regressed_metrics=regressed_metrics,
                evidence_ids=evidence_ids,
                deterministic_next_cycle=next_ref.deterministic and next_ref.observed,
            )

        if _is_disproven(validation_payload, next_payload):
            return CompilerRepairClassification(
                CompilerRepairOutcome.DISPROVEN_HYPOTHESIS,
                reason="deterministic_validation_or_next_cycle_disproved_patch_hypothesis",
                observed_at=next_ref.observed_at,
                metric_deltas=metric_deltas,
                objective_delta=objective_delta,
                regressed_metrics=regressed_metrics,
                evidence_ids=evidence_ids,
                deterministic_next_cycle=next_ref.deterministic and next_ref.observed,
            )

        if _is_accepted_benefit(next_payload, validation_payload, merge_payload, objective_delta):
            return CompilerRepairClassification(
                CompilerRepairOutcome.ACCEPTED_BENEFIT,
                reason="deterministic_next_cycle_observed_target_benefit",
                observed_at=next_ref.observed_at,
                metric_deltas=metric_deltas,
                objective_delta=objective_delta,
                regressed_metrics=regressed_metrics,
                evidence_ids=evidence_ids,
                deterministic_next_cycle=next_ref.deterministic and next_ref.observed,
            )

        return CompilerRepairClassification(
            CompilerRepairOutcome.NEUTRAL_CHANGE,
            reason="deterministic_next_cycle_observed_no_material_metric_movement",
            observed_at=next_ref.observed_at,
            metric_deltas=metric_deltas,
            objective_delta=objective_delta,
            regressed_metrics=regressed_metrics,
            evidence_ids=evidence_ids,
            deterministic_next_cycle=next_ref.deterministic and next_ref.observed,
        )


def _merge_payloads(*payloads: Mapping[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for payload in payloads:
        for key, value in payload.items():
            if isinstance(value, Mapping) and isinstance(merged.get(key), Mapping):
                merged[key] = _merge_payloads(merged[key], value)  # type: ignore[arg-type]
            else:
                merged[key] = value
    return merged


def _require_complete_evidence(evidence: Sequence[CompilerRepairEvidenceRef]) -> None:
    seen: dict[str, CompilerRepairEvidenceRef] = {}
    for ref in evidence:
        if ref.kind in seen:
            raise CompilerRepairLineageValidationError(
                f"lineage contains duplicate evidence kind {ref.kind!r}"
            )
        seen[ref.kind] = ref
    missing = [kind for kind in REQUIRED_REPAIR_EVIDENCE_KINDS if kind not in seen]
    if missing:
        raise CompilerRepairLineageValidationError(
            "lineage is missing required evidence kinds: " + ", ".join(missing)
        )


def _default_links(
    evidence: Sequence[CompilerRepairEvidenceRef],
) -> tuple[CompilerRepairLineageLink, ...]:
    by_kind = {ref.kind: ref for ref in evidence}
    links: list[CompilerRepairLineageLink] = []
    for source_kind, target_kind in zip(
        REQUIRED_REPAIR_EVIDENCE_KINDS,
        REQUIRED_REPAIR_EVIDENCE_KINDS[1:],
    ):
        source = by_kind[source_kind]
        target = by_kind[target_kind]
        links.append(
            CompilerRepairLineageLink(
                source_kind=source.kind,
                source_id=source.stable_id,
                target_kind=target.kind,
                target_id=target.stable_id,
                relation=f"{source.kind}_to_{target.kind}",
                observed_at=max(source.observed_at, target.observed_at),
            )
        )
    return tuple(links)


def _require_linked_evidence(
    evidence: Sequence[CompilerRepairEvidenceRef],
    links: Sequence[CompilerRepairLineageLink],
) -> None:
    identities = {(ref.kind, ref.stable_id) for ref in evidence}
    for link in links:
        if (link.source_kind, link.source_id) not in identities:
            raise CompilerRepairLineageValidationError(
                f"link source {link.source_kind}:{link.source_id} is not in evidence"
            )
        if (link.target_kind, link.target_id) not in identities:
            raise CompilerRepairLineageValidationError(
                f"link target {link.target_kind}:{link.target_id} is not in evidence"
            )
    linked_pairs = {
        (link.source_kind, link.target_kind)
        for link in links
        if link.source_kind in VALID_REPAIR_EVIDENCE_KINDS
        and link.target_kind in VALID_REPAIR_EVIDENCE_KINDS
    }
    missing_pairs = [
        (left, right)
        for left, right in zip(
            REQUIRED_REPAIR_EVIDENCE_KINDS,
            REQUIRED_REPAIR_EVIDENCE_KINDS[1:],
        )
        if (left, right) not in linked_pairs
    ]
    if missing_pairs:
        raise CompilerRepairLineageValidationError(
            "lineage links do not connect required cycle edges: "
            + ", ".join(f"{left}->{right}" for left, right in missing_pairs)
        )


def _regressed_metrics(payload: Mapping[str, Any]) -> tuple[str, ...]:
    names: list[str] = []
    for key in (
        "hard_regressed_metrics",
        "holdout_hard_regressed_metrics",
        "holdout_regressed_metrics",
        "raw_regressed_metrics",
        "regressed_metrics",
        "target_metric_hard_regressed_metrics",
    ):
        names.extend(_string_list(payload.get(key)))
    for nested_key in (
        "target_metric_validation",
        "holdout_target_metric_validation",
        "validation_report",
    ):
        nested = payload.get(nested_key)
        if isinstance(nested, Mapping):
            names.extend(_regressed_metrics(nested))
    return _string_list(names)


def _payload_boolean(payload: Mapping[str, Any], *keys: str) -> bool:
    return any(bool(payload.get(key)) for key in keys)


def _has_stale_evidence(refs: Mapping[str, CompilerRepairEvidenceRef]) -> bool:
    for ref in refs.values():
        payload = ref.payload
        statuses = _status_tokens(payload)
        if any(status == "stale" or status.endswith("_stale") for status in statuses):
            return True
        if _payload_boolean(payload, "stale", "is_stale", "stale_evidence"):
            return True
    state_payload = refs[STATE_SNAPSHOT].payload
    next_payload = refs[NEXT_CYCLE_OBSERVATION].payload
    state_hash = str(
        state_payload.get("state_hash")
        or state_payload.get("snapshot_hash")
        or state_payload.get("autoencoder_state_hash")
        or ""
    ).strip()
    observed_source_state = str(
        next_payload.get("source_state_hash")
        or next_payload.get("expected_state_hash")
        or ""
    ).strip()
    if state_hash and observed_source_state and state_hash != observed_source_state:
        return True
    compiler_commit = str(state_payload.get("compiler_commit") or "").strip()
    observed_commit = str(
        next_payload.get("source_compiler_commit")
        or next_payload.get("expected_compiler_commit")
        or ""
    ).strip()
    return bool(compiler_commit and observed_commit and compiler_commit != observed_commit)


def _operational_failure(refs: Mapping[str, CompilerRepairEvidenceRef]) -> bool:
    next_ref = refs[NEXT_CYCLE_OBSERVATION]
    if not (next_ref.observed and next_ref.deterministic):
        return True

    codex_statuses = _status_tokens(refs[CODEX_ATTEMPT].payload)
    if any(status in _OPERATIONAL_FAILURE_STATUSES for status in codex_statuses):
        return True
    if codex_statuses and not any(status in _PASSED_OR_ACCEPTED_STATUSES for status in codex_statuses):
        return True

    merge_statuses = _status_tokens(refs[MERGE].payload)
    if any(status in _OPERATIONAL_FAILURE_STATUSES for status in merge_statuses):
        return True
    if merge_statuses and not any(status in _MERGE_ACCEPTED_STATUSES for status in merge_statuses):
        return True

    validation_statuses = _status_tokens(refs[VALIDATION].payload)
    if any(status in {"skipped", "unavailable", "not_measured"} for status in validation_statuses):
        return True
    next_statuses = _status_tokens(refs[NEXT_CYCLE_OBSERVATION].payload)
    return any(status in {"skipped", "unavailable", "not_measured"} for status in next_statuses)


def _is_quality_regression(
    payload: Mapping[str, Any],
    regressed_metrics: Sequence[str],
    objective_delta: Optional[float],
) -> bool:
    statuses = _status_tokens(payload)
    if "regressed" in statuses or "metric_regression" in statuses:
        return True
    if regressed_metrics:
        return True
    if objective_delta is not None and objective_delta < 0.0:
        return True
    return any(delta < 0.0 for delta in _metric_deltas(payload).values())


def _is_disproven(
    validation_payload: Mapping[str, Any],
    next_payload: Mapping[str, Any],
) -> bool:
    statuses = set(_status_tokens(validation_payload)) | set(_status_tokens(next_payload))
    if statuses & {
        "disproven",
        "hypothesis_disproven",
        "unsupported_hypothesis",
        "validation_rejected",
    }:
        return True
    if statuses & _VALIDATION_FAILED_STATUSES:
        return True
    reason_text = " ".join(
        str(value or "").lower()
        for payload in (validation_payload, next_payload)
        for value in (payload.get("reason"), payload.get("failure_reason"))
    )
    return "unsupported_hypothesis" in reason_text or "disproven" in reason_text


def _is_accepted_benefit(
    next_payload: Mapping[str, Any],
    validation_payload: Mapping[str, Any],
    merge_payload: Mapping[str, Any],
    objective_delta: Optional[float],
) -> bool:
    statuses = (
        set(_status_tokens(next_payload))
        | set(_status_tokens(validation_payload))
        | set(_status_tokens(merge_payload))
    )
    if not (statuses & _PASSED_OR_ACCEPTED_STATUSES):
        return False
    next_statuses = set(_status_tokens(next_payload))
    if next_statuses & {"accepted_benefit", "improved"}:
        return True
    if objective_delta is not None and objective_delta > 0.0:
        return True
    return any(delta > 0.0 for delta in _metric_deltas(next_payload).values())


def build_compiler_repair_lineage(
    *,
    state_snapshot: Mapping[str, Any] | CompilerRepairEvidenceRef,
    metric_gap: Mapping[str, Any] | CompilerRepairEvidenceRef,
    leanstral_audit: Mapping[str, Any] | CompilerRepairEvidenceRef,
    hammer_receipt: Mapping[str, Any] | CompilerRepairEvidenceRef,
    rule_gap_report: Mapping[str, Any] | CompilerRepairEvidenceRef,
    todo: Mapping[str, Any] | CompilerRepairEvidenceRef,
    codex_attempt: Mapping[str, Any] | CompilerRepairEvidenceRef,
    validation: Mapping[str, Any] | CompilerRepairEvidenceRef,
    merge: Mapping[str, Any] | CompilerRepairEvidenceRef,
    next_cycle_observation: Mapping[str, Any] | CompilerRepairEvidenceRef,
    task_id: str = "",
    attempt: int = 1,
    created_at: Optional[str] = None,
) -> CompilerRepairLineage:
    """Build and validate a complete closed-loop repair lineage."""

    raw_by_kind: tuple[tuple[str, Mapping[str, Any] | CompilerRepairEvidenceRef], ...] = (
        (STATE_SNAPSHOT, state_snapshot),
        (METRIC_GAP, metric_gap),
        (LEANSTRAL_AUDIT, leanstral_audit),
        (HAMMER_RECEIPT, hammer_receipt),
        (RULE_GAP_REPORT, rule_gap_report),
        (TODO, todo),
        (CODEX_ATTEMPT, codex_attempt),
        (VALIDATION, validation),
        (MERGE, merge),
        (NEXT_CYCLE_OBSERVATION, next_cycle_observation),
    )
    refs: list[CompilerRepairEvidenceRef] = []
    for kind, value in raw_by_kind:
        if isinstance(value, CompilerRepairEvidenceRef):
            if value.kind != kind:
                raise CompilerRepairLineageValidationError(
                    f"expected {kind} evidence, got {value.kind}"
                )
            refs.append(value)
            continue
        data = dict(value)
        data.setdefault("kind", kind)
        data.setdefault("deterministic", kind in DETERMINISTIC_EVIDENCE_DEFAULTS)
        refs.append(CompilerRepairEvidenceRef.from_mapping(data, kind=kind))
    return CompilerRepairLineage(
        task_id=task_id,
        attempt=attempt,
        evidence_refs=tuple(refs),
        created_at=created_at or max(ref.observed_at for ref in refs),
    )


def compiler_repair_lineage_to_json(
    lineage: CompilerRepairLineage,
    *,
    include_payload: bool = True,
) -> str:
    """Serialize a lineage with canonical key order for artifacts and caches."""

    return json.dumps(
        lineage.to_dict(include_payload=include_payload),
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def compiler_repair_lineage_from_json(payload: str) -> CompilerRepairLineage:
    """Deserialize a lineage artifact produced by this module."""

    data = json.loads(payload)
    if not isinstance(data, Mapping):
        raise CompilerRepairLineageValidationError("lineage JSON must decode to a mapping")
    return CompilerRepairLineage.from_mapping(data)


def prioritization_signal_from_lineage(
    lineage: CompilerRepairLineage,
    *,
    classification: Optional[CompilerRepairClassification] = None,
) -> CompilerRepairPrioritizationSignal:
    """Return the future-prioritization signal for a lineage.

    The returned signal may be ineligible.  Call
    :func:`future_prioritization_records` to get only admissible observed
    deterministic records.
    """

    resolved = classification or lineage.classify()
    refs = lineage.evidence_by_kind
    next_ref = refs[NEXT_CYCLE_OBSERVATION]
    todo_ref = refs[TODO]
    raw_target_metrics: Any = todo_ref.payload.get("target_metrics")
    metadata = todo_ref.payload.get("metadata")
    if not raw_target_metrics and isinstance(metadata, Mapping):
        raw_target_metrics = metadata.get("target_metrics")
    target_metrics = _string_list(raw_target_metrics)
    eligible = (
        next_ref.observed
        and next_ref.deterministic
        and resolved.outcome
        not in {
            CompilerRepairOutcome.STALE_EVIDENCE,
            CompilerRepairOutcome.OPERATIONAL_FAILURE,
        }
    )
    reason = resolved.reason if eligible else "no_observed_deterministic_next_cycle_outcome"
    weight_delta = 0.0
    if eligible:
        if resolved.outcome is CompilerRepairOutcome.ACCEPTED_BENEFIT:
            weight_delta = _positive_signal_weight(resolved)
        elif resolved.outcome is CompilerRepairOutcome.QUALITY_REGRESSION:
            weight_delta = -max(_positive_signal_weight(resolved), 1.0)
        elif resolved.outcome is CompilerRepairOutcome.DISPROVEN_HYPOTHESIS:
            weight_delta = -1.0
        else:
            weight_delta = 0.0
    return CompilerRepairPrioritizationSignal(
        lineage_id=lineage.stable_id,
        task_id=lineage.task_id,
        todo_id=lineage.todo_id,
        outcome=resolved.outcome,
        observed_at=resolved.observed_at,
        eligible=eligible,
        weight_delta=weight_delta,
        reason=reason,
        metric_deltas=resolved.metric_deltas,
        target_metrics=target_metrics,
        evidence_ids=resolved.evidence_ids,
    )


def _positive_signal_weight(classification: CompilerRepairClassification) -> float:
    candidates = [abs(value) for value in classification.metric_deltas.values()]
    if classification.objective_delta is not None:
        candidates.append(abs(float(classification.objective_delta)))
    return round(max(candidates, default=1.0), 12)


def future_prioritization_records(
    lineages: Sequence[CompilerRepairLineage],
    *,
    include_neutral: bool = True,
) -> tuple[dict[str, Any], ...]:
    """Return only observed deterministic closed-loop outcomes for prioritizers."""

    records: list[dict[str, Any]] = []
    for lineage in lineages:
        signal = lineage.prioritization_signal()
        if not signal.eligible:
            continue
        if not include_neutral and signal.outcome is CompilerRepairOutcome.NEUTRAL_CHANGE:
            continue
        records.append(signal.to_dict())
    return tuple(
        sorted(
            records,
            key=lambda item: (
                str(item["observed_at"]),
                str(item["lineage_id"]),
            ),
        )
    )


def observed_deterministic_prioritization_records(
    lineages: Sequence[CompilerRepairLineage],
    *,
    include_neutral: bool = True,
) -> tuple[dict[str, Any], ...]:
    """Alias documenting the hard rule for future prioritization inputs."""

    return future_prioritization_records(lineages, include_neutral=include_neutral)


__all__ = [
    "CODEX_ATTEMPT",
    "COMPILER_REPAIR_LINEAGE_SCHEMA_VERSION",
    "COMPILER_REPAIR_PRIORITIZATION_SCHEMA_VERSION",
    "CompilerRepairClassification",
    "CompilerRepairEvidenceRef",
    "CompilerRepairLineage",
    "CompilerRepairLineageClassifier",
    "CompilerRepairLineageError",
    "CompilerRepairLineageLink",
    "CompilerRepairLineageValidationError",
    "CompilerRepairOutcome",
    "CompilerRepairPrioritizationSignal",
    "HAMMER_RECEIPT",
    "LEANSTRAL_AUDIT",
    "MERGE",
    "METRIC_GAP",
    "NEXT_CYCLE_OBSERVATION",
    "REQUIRED_REPAIR_EVIDENCE_KINDS",
    "RULE_GAP_REPORT",
    "STATE_SNAPSHOT",
    "TODO",
    "VALIDATION",
    "build_compiler_repair_lineage",
    "compiler_repair_lineage_from_json",
    "compiler_repair_lineage_to_json",
    "future_prioritization_records",
    "observed_deterministic_prioritization_records",
    "prioritization_signal_from_lineage",
]
