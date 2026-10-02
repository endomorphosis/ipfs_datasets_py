"""Evidence-backed objective lifecycle and completion decisions.

Goal completion is intentionally a two-phase operation.  Finishing the tasks
associated with a goal only makes the goal *provisionally* complete.  A later
evaluation may verify it after every acceptance criterion has fresh,
tree-bound, passing evidence with content-addressed provenance.

The types in this module are independent of the markdown objective tracker so
they can also be used by daemons, APIs, and persisted graph consumers.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from enum import Enum
from hashlib import sha256
import json
from typing import Any, Iterable, Mapping, Sequence

from ..proof.formal_verification_contracts import (
    AssuranceLevel,
    CodeProofObligation,
    ContractValidationError,
    EvidenceFreshness,
    ProofReceipt,
    ProofVerdict,
    assurance_satisfies,
)


GOAL_COMPLETION_SCHEMA_VERSION = 1
GOAL_COMPLETION_MIGRATION_SCHEMA_VERSION = 1
DEFAULT_EVIDENCE_FRESHNESS_SECONDS = 3600.0
DEFAULT_CLOCK_SKEW_SECONDS = 300.0
CHANNEL_PROOF_REVISION_NAMESPACE = "documentation-semantic-channel-proof"
CHANNEL_EVIDENCE_PROVENANCE_NAMESPACE = "documentation-completion-receipt"


class GoalState(str, Enum):
    """Canonical states in the goal lifecycle."""

    ACTIVE = "active"
    PROVISIONALLY_COMPLETE = "provisionally_complete"
    VERIFIED_COMPLETE = "verified_complete"
    ANALYSIS_INCONCLUSIVE = "analysis_inconclusive"
    BLOCKED = "blocked"
    REOPENED = "reopened"


TERMINAL_TASK_STATUSES = frozenset({"completed", "complete", "done", "skipped"})


def skip_provisional_goal_closeout(
    *,
    active_task_id: str = "",
    implementation_in_progress: bool = False,
    task_statuses: Mapping[str, Any] | None = None,
    task_counts: Mapping[str, Any] | None = None,
) -> str | None:
    """Return why extra-gate must not CAS goals, or None if provisional closeout may run.

    All-tasks-complete is only provisional. This never authorizes verified
    completion or board completion_authority. A missing portal projection is
    not a skip when live task counts already show every task terminal.
    """
    if str(active_task_id or "").strip() or implementation_in_progress is True:
        return "active_implementation"
    statuses = task_statuses if isinstance(task_statuses, Mapping) else {}
    if statuses:
        if any(
            str(value or "").strip().lower() not in TERMINAL_TASK_STATUSES
            for value in statuses.values()
        ):
            return "tasks_not_all_terminal"
        return None
    counts = task_counts if isinstance(task_counts, Mapping) else {}
    leftover = []
    for key, value in counts.items():
        try:
            count = int(value or 0)
        except (TypeError, ValueError):
            continue
        if count > 0 and str(key).lower() not in TERMINAL_TASK_STATUSES:
            leftover.append(str(key))
    if leftover:
        return "tasks_not_all_terminal"
    if counts:
        return None
    return "task_statuses_unavailable"


_GOAL_STATE_ALIASES = {
    "active": GoalState.ACTIVE,
    "todo": GoalState.ACTIVE,
    "open": GoalState.ACTIVE,
    "in_progress": GoalState.ACTIVE,
    "provisional": GoalState.PROVISIONALLY_COMPLETE,
    "provisionally_complete": GoalState.PROVISIONALLY_COMPLETE,
    "provisionally_completed": GoalState.PROVISIONALLY_COMPLETE,
    "verified": GoalState.VERIFIED_COMPLETE,
    "verified_complete": GoalState.VERIFIED_COMPLETE,
    # Compatibility is deliberately confined to normalization.  New writers
    # always persist the more precise verified_complete spelling.
    "complete": GoalState.VERIFIED_COMPLETE,
    "completed": GoalState.VERIFIED_COMPLETE,
    "done": GoalState.VERIFIED_COMPLETE,
    "analysis_inconclusive": GoalState.ANALYSIS_INCONCLUSIVE,
    "inconclusive": GoalState.ANALYSIS_INCONCLUSIVE,
    "blocked": GoalState.BLOCKED,
    "reopened": GoalState.REOPENED,
}

LEGACY_COMPLETED_GOAL_STATES = frozenset({"complete", "completed", "done"})


def is_legacy_completed_goal_state(value: GoalState | str | None) -> bool:
    """Return whether *value* is an ambiguous pre-lifecycle completion label.

    This check intentionally happens before :func:`normalize_goal_state`.
    Normalization retains the historical ``completed -> verified_complete``
    alias for compatibility readers, while migration must not interpret that
    alias as proof that the modern completion gate passed.
    """

    if isinstance(value, GoalState):
        return False
    normalized = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    return normalized in LEGACY_COMPLETED_GOAL_STATES


def normalize_goal_state(value: GoalState | str | None) -> GoalState:
    """Return a canonical state, accepting documented legacy spellings."""

    if isinstance(value, GoalState):
        return value
    normalized = str(value or "active").strip().lower().replace("-", "_").replace(" ", "_")
    try:
        return _GOAL_STATE_ALIASES[normalized]
    except KeyError as exc:
        choices = ", ".join(state.value for state in GoalState)
        raise ValueError(f"unknown goal state {value!r}; expected one of: {choices}") from exc


LEGAL_GOAL_TRANSITIONS: Mapping[GoalState, frozenset[GoalState]] = {
    GoalState.ACTIVE: frozenset(
        {
            GoalState.PROVISIONALLY_COMPLETE,
            GoalState.ANALYSIS_INCONCLUSIVE,
            GoalState.BLOCKED,
        }
    ),
    GoalState.PROVISIONALLY_COMPLETE: frozenset(
        {
            GoalState.VERIFIED_COMPLETE,
            GoalState.REOPENED,
            GoalState.ANALYSIS_INCONCLUSIVE,
            GoalState.BLOCKED,
        }
    ),
    GoalState.VERIFIED_COMPLETE: frozenset({GoalState.REOPENED}),
    GoalState.ANALYSIS_INCONCLUSIVE: frozenset(
        {GoalState.ACTIVE, GoalState.REOPENED, GoalState.BLOCKED, GoalState.PROVISIONALLY_COMPLETE}
    ),
    GoalState.BLOCKED: frozenset({GoalState.REOPENED}),
    GoalState.REOPENED: frozenset(
        {
            GoalState.ACTIVE,
            GoalState.PROVISIONALLY_COMPLETE,
            GoalState.ANALYSIS_INCONCLUSIVE,
            GoalState.BLOCKED,
        }
    ),
}


def legal_goal_transitions(state: GoalState | str) -> frozenset[GoalState]:
    return LEGAL_GOAL_TRANSITIONS[normalize_goal_state(state)]


def is_terminal_goal_state(state: GoalState | str) -> bool:
    """Whether no work should be scheduled until an explicit transition."""

    return normalize_goal_state(state) in {GoalState.VERIFIED_COMPLETE, GoalState.BLOCKED}


def is_schedulable_goal_state(state: GoalState | str) -> bool:
    """Whether backlog generation may schedule work for the goal.

    Provisional and inconclusive goals still have unmet proof or analysis
    obligations.  Excluding them from scheduling would leave those
    nonterminal states unable to produce the evidence needed to advance.
    """

    return normalize_goal_state(state) in {
        GoalState.ACTIVE,
        GoalState.PROVISIONALLY_COMPLETE,
        GoalState.ANALYSIS_INCONCLUSIVE,
        GoalState.REOPENED,
    }


class IllegalGoalTransitionError(ValueError):
    """Raised when a caller attempts a transition outside the state machine."""


# Concise public spelling retained for callers which do not use the Error
# suffix convention.
IllegalGoalTransition = IllegalGoalTransitionError


def _utc_datetime(value: datetime | str | None, *, field_name: str) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, str):
        text = value.strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            value = datetime.fromisoformat(text)
        except ValueError as exc:
            raise ValueError(f"{field_name} must be an ISO-8601 timestamp") from exc
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a datetime or ISO-8601 string")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _now(value: datetime | str | None) -> datetime:
    return _utc_datetime(value, field_name="now") or datetime.now(timezone.utc)


def _criterion_key(value: object) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _json_value(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_json_value(item) for item in value]
    return value


def _canonical_json(value: Any) -> str:
    """Return a stable representation suitable for persisted identities."""

    return json.dumps(
        _json_value(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    )


def _namespaced_sha256_revision(value: Any, namespace: str) -> str:
    """Return the canonical namespaced revision used by channel producers.

    Unlike the more permissive internal fingerprint helper, completion
    evidence is an externally persisted authorization artifact.  Its digest
    therefore uses the producer contract's exact JSON encoding and rejects
    non-JSON values instead of stringifying them.
    """

    canonical = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    digest = sha256()
    digest.update(str(namespace).encode("utf-8"))
    digest.update(b"\0")
    digest.update(canonical)
    return f"sha256:{digest.hexdigest()}"


def _stable_fingerprint(prefix: str, value: Any) -> str:
    return f"{prefix}-{sha256(_canonical_json(value).encode('utf-8')).hexdigest()[:32]}"


def _string_tuple(values: Any) -> tuple[str, ...]:
    if values is None:
        return ()
    if isinstance(values, str):
        values = (values,)
    elif isinstance(values, Mapping):
        scalar = next(
            (
                values.get(key)
                for key in (
                    "criterion",
                    "acceptance_criterion",
                    "receipt_id",
                    "receipt_cid",
                    "provenance_cid",
                    "id",
                    "value",
                )
                if values.get(key) is not None
            ),
            _canonical_json(values),
        )
        values = (scalar,)
    elif not isinstance(values, Iterable):
        values = (values,)
    result: list[str] = []
    for value in values:
        item = " ".join(str(value or "").split())
        if item and item not in result:
            result.append(item)
    return tuple(sorted(result, key=lambda item: (item.casefold(), item)))


def _mapping_tuple(values: Any) -> tuple[dict[str, Any], ...]:
    if values is None:
        return ()
    if isinstance(values, Mapping):
        values = (values,)
    elif isinstance(values, (str, bytes)) or not isinstance(values, Iterable):
        values = (values,)
    result: dict[str, dict[str, Any]] = {}
    for value in values:
        if isinstance(value, Mapping):
            payload = {str(key): _json_value(item) for key, item in value.items()}
        else:
            payload = {"value": _json_value(value)}
        result[_canonical_json(payload)] = payload
    return tuple(result[key] for key in sorted(result))


_ASSURANCE_ALIASES = {
    "": AssuranceLevel.UNVERIFIED,
    "none": AssuranceLevel.UNVERIFIED,
    "unverified": AssuranceLevel.UNVERIFIED,
    "candidate": AssuranceLevel.CANDIDATE,
    "solver_checked": AssuranceLevel.SOLVER_CHECKED,
    "solver_verified": AssuranceLevel.SOLVER_CHECKED,
    "kernel_verified": AssuranceLevel.KERNEL_VERIFIED,
    "attested": AssuranceLevel.ATTESTED,
}


def _assurance_level(value: Any) -> AssuranceLevel | None:
    """Best-effort assurance normalization for untrusted persisted evidence."""

    if isinstance(value, AssuranceLevel):
        return value
    normalized = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    return _ASSURANCE_ALIASES.get(normalized)


def _proof_verdict(value: Any) -> ProofVerdict | None:
    if isinstance(value, ProofVerdict):
        return value
    try:
        return ProofVerdict(str(value or "").strip().lower())
    except ValueError:
        return None


def _proof_freshness(value: Any) -> EvidenceFreshness | None:
    if isinstance(value, EvidenceFreshness):
        return value
    try:
        return EvidenceFreshness(str(value or "").strip().lower())
    except ValueError:
        return None


CONTRADICTION_KINDS = frozenset(
    {
        "mapped_finding",
        "failed_validation",
        "changed_surface",
        "invalidated_receipt",
        "child_reopened",
        "dependency_reopened",
    }
)


@dataclass(frozen=True)
class ContradictionEvidence:
    """Content-addressed evidence which invalidates a completion claim.

    ``fingerprint`` deliberately excludes ``detected_at`` and scheduled work.
    Replaying the same source receipt therefore cannot manufacture another
    contradiction merely because a daemon ran later or chose an equivalent
    scheduling representation.
    """

    goal_id: str
    kind: str
    summary: str = ""
    impacted_criteria: tuple[str, ...] = ()
    invalidated_evidence: tuple[str, ...] = ()
    source_receipt: Mapping[str, Any] = field(default_factory=dict)
    scheduled_work: tuple[Mapping[str, Any], ...] = ()
    source_receipt_id: str = ""
    invalidation_event_id: str = ""
    changed_inputs: tuple[Mapping[str, Any], ...] = ()
    affected_obligation_ids: tuple[str, ...] = ()
    affected_receipt_ids: tuple[str, ...] = ()
    source_tree: str = ""
    invalidation_records: tuple[Mapping[str, Any], ...] = ()
    historical_receipts: tuple[Mapping[str, Any], ...] = ()
    dependency_edges: tuple[Mapping[str, Any], ...] = ()
    conflict_edges: tuple[Mapping[str, Any], ...] = ()
    fingerprint: str = ""
    detected_at: datetime | str | None = None
    schema_version: int = GOAL_COMPLETION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        goal_id = str(self.goal_id or "").strip()
        if not goal_id:
            raise ValueError("contradiction evidence requires goal_id")
        kind = str(self.kind or "").strip().casefold().replace("-", "_").replace(" ", "_")
        aliases = {
            "novel_finding": "mapped_finding",
            "novel_mapped_finding": "mapped_finding",
            "validation_failed": "failed_validation",
            "surface_changed": "changed_surface",
            "evidence_surface_changed": "changed_surface",
            "audit_receipt_invalidated": "invalidated_receipt",
            "invalid_audit_receipt": "invalidated_receipt",
        }
        kind = aliases.get(kind, kind)
        if kind not in CONTRADICTION_KINDS:
            choices = ", ".join(sorted(CONTRADICTION_KINDS))
            raise ValueError(
                f"unknown contradiction kind {self.kind!r}; expected one of: {choices}"
            )
        source = {
            str(key): _json_value(value) for key, value in dict(self.source_receipt or {}).items()
        }
        source_id = str(
            self.source_receipt_id
            or source.get("receipt_id")
            or source.get("receipt_cid")
            or source.get("provenance_cid")
            or source.get("finding_id")
            or source.get("fingerprint")
            or ""
        ).strip()
        criteria = _string_tuple(self.impacted_criteria)
        invalidated = _string_tuple(self.invalidated_evidence)
        scheduled_input: Any = self.scheduled_work
        if isinstance(scheduled_input, (str, bytes)):
            text = str(scheduled_input).strip()
            scheduled_input = ({"task_id": text},) if text else ()
        elif scheduled_input is not None and not isinstance(scheduled_input, (Mapping, Iterable)):
            scheduled_input = ({"value": _json_value(scheduled_input)},)
        scheduled = _mapping_tuple(scheduled_input)
        event_id = str(
            self.invalidation_event_id
            or source.get("event_id")
            or source.get("invalidation_id")
            or ""
        ).strip()
        changed_inputs = _mapping_tuple(self.changed_inputs)
        affected_obligations = _string_tuple(self.affected_obligation_ids)
        affected_receipts = _string_tuple(self.affected_receipt_ids)
        source_tree = str(
            self.source_tree or source.get("source_tree") or source.get("source_tree_id") or ""
        ).strip()
        invalidation_records = _mapping_tuple(self.invalidation_records)
        historical_receipts = _mapping_tuple(self.historical_receipts)
        dependency_edges = _mapping_tuple(self.dependency_edges)
        conflict_edges = _mapping_tuple(self.conflict_edges)
        identity = {
            "goal_id": goal_id,
            "kind": kind,
            "impacted_criteria": criteria,
            "invalidated_evidence": invalidated,
            "source_receipt_id": source_id,
            "source_receipt": source,
        }
        # Preserve the established contradiction identity for legacy records.
        # New proof-invalidation provenance is content-addressed as well, but
        # scheduled replacement work and timestamps remain deliberately
        # excluded so replay cannot manufacture another contradiction.
        if any(
            (
                event_id,
                changed_inputs,
                affected_obligations,
                affected_receipts,
                source_tree,
                invalidation_records,
                historical_receipts,
                dependency_edges,
                conflict_edges,
            )
        ):
            identity.update(
                {
                    "invalidation_event_id": event_id,
                    "changed_inputs": changed_inputs,
                    "affected_obligation_ids": affected_obligations,
                    "affected_receipt_ids": affected_receipts,
                    "source_tree": source_tree,
                    "invalidation_records": invalidation_records,
                    "historical_receipts": historical_receipts,
                    "dependency_edges": dependency_edges,
                    "conflict_edges": conflict_edges,
                }
            )
        object.__setattr__(self, "goal_id", goal_id)
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "summary", " ".join(str(self.summary or "").split()))
        object.__setattr__(self, "impacted_criteria", criteria)
        object.__setattr__(self, "invalidated_evidence", invalidated)
        object.__setattr__(self, "source_receipt", source)
        object.__setattr__(self, "scheduled_work", scheduled)
        object.__setattr__(self, "source_receipt_id", source_id)
        object.__setattr__(self, "invalidation_event_id", event_id)
        object.__setattr__(self, "changed_inputs", changed_inputs)
        object.__setattr__(self, "affected_obligation_ids", affected_obligations)
        object.__setattr__(self, "affected_receipt_ids", affected_receipts)
        object.__setattr__(self, "source_tree", source_tree)
        object.__setattr__(self, "invalidation_records", invalidation_records)
        object.__setattr__(self, "historical_receipts", historical_receipts)
        object.__setattr__(self, "dependency_edges", dependency_edges)
        object.__setattr__(self, "conflict_edges", conflict_edges)
        object.__setattr__(
            self,
            "fingerprint",
            str(self.fingerprint or _stable_fingerprint("contradiction", identity)),
        )
        object.__setattr__(
            self, "detected_at", _utc_datetime(self.detected_at, field_name="detected_at")
        )

    @property
    def contradiction_id(self) -> str:
        return self.fingerprint

    @property
    def replacement_tasks(self) -> tuple[Mapping[str, Any], ...]:
        """Deterministic replacement work scheduled by proof invalidation."""

        return self.scheduled_work

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "schema": "ipfs_accelerate_py.agent_supervisor.contradiction.v1",
            "schema_version": self.schema_version,
            "contradiction_id": self.fingerprint,
            "fingerprint": self.fingerprint,
            "goal_id": self.goal_id,
            "kind": self.kind,
            "summary": self.summary,
            "impacted_criteria": list(self.impacted_criteria),
            "invalidated_evidence": list(self.invalidated_evidence),
            "source_receipt_id": self.source_receipt_id,
            "source_receipt": _json_value(self.source_receipt),
            "scheduled_work": _json_value(self.scheduled_work),
            "detected_at": _json_value(self.detected_at),
        }
        if any(
            (
                self.invalidation_event_id,
                self.changed_inputs,
                self.affected_obligation_ids,
                self.affected_receipt_ids,
                self.source_tree,
                self.invalidation_records,
                self.historical_receipts,
                self.dependency_edges,
                self.conflict_edges,
            )
        ):
            payload.update(
                {
                    "replacement_tasks": _json_value(self.replacement_tasks),
                    "invalidation_event_id": self.invalidation_event_id,
                    "changed_inputs": _json_value(self.changed_inputs),
                    "affected_obligation_ids": list(self.affected_obligation_ids),
                    "affected_receipt_ids": list(self.affected_receipt_ids),
                    "source_tree": self.source_tree,
                    "invalidation_records": _json_value(self.invalidation_records),
                    "historical_receipts": _json_value(self.historical_receipts),
                    "dependency_edges": _json_value(self.dependency_edges),
                    "conflict_edges": _json_value(self.conflict_edges),
                }
            )
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ContradictionEvidence":
        return cls(
            goal_id=str(payload.get("goal_id", "")),
            kind=str(payload.get("kind", payload.get("contradiction_kind", ""))),
            summary=str(
                payload.get(
                    "summary",
                    payload.get(
                        "description", payload.get("contradiction", payload.get("explanation", ""))
                    ),
                )
            ),
            impacted_criteria=payload.get("impacted_criteria", payload.get("criteria", ())) or (),
            invalidated_evidence=payload.get(
                "invalidated_evidence", payload.get("evidence_ids", ())
            )
            or (),
            source_receipt=payload.get("source_receipt", payload.get("receipt", {})) or {},
            scheduled_work=payload.get(
                "scheduled_work",
                payload.get("replacement_tasks", payload.get("newly_scheduled_work", ())),
            )
            or (),
            source_receipt_id=str(
                payload.get(
                    "source_receipt_id",
                    payload.get(
                        "finding_id", payload.get("receipt_id", payload.get("receipt_cid", ""))
                    ),
                )
            ),
            invalidation_event_id=str(
                payload.get(
                    "invalidation_event_id",
                    payload.get("event_id", payload.get("proof_invalidation_id", "")),
                )
            ),
            changed_inputs=payload.get("changed_inputs", payload.get("invalidated_inputs", ()))
            or (),
            affected_obligation_ids=payload.get(
                "affected_obligation_ids",
                payload.get("obligation_ids", payload.get("invalidated_obligation_ids", ())),
            )
            or (),
            affected_receipt_ids=payload.get(
                "affected_receipt_ids",
                payload.get("receipt_ids", payload.get("invalidated_receipt_ids", ())),
            )
            or (),
            source_tree=str(
                payload.get(
                    "source_tree",
                    payload.get(
                        "source_tree_id",
                        payload.get(
                            "repository_tree",
                            payload.get("repository_tree_id", payload.get("tree_id", "")),
                        ),
                    ),
                )
            ),
            invalidation_records=payload.get(
                "invalidation_records", payload.get("invalidations", ())
            )
            or (),
            historical_receipts=payload.get(
                "historical_receipts", payload.get("invalidated_receipts", ())
            )
            or (),
            dependency_edges=payload.get("dependency_edges", ()) or (),
            conflict_edges=payload.get("conflict_edges", ()) or (),
            fingerprint=str(payload.get("fingerprint", payload.get("contradiction_id", ""))),
            detected_at=payload.get("detected_at"),
            schema_version=int(payload.get("schema_version", GOAL_COMPLETION_SCHEMA_VERSION)),
        )


_PROOF_INVALIDATION_EVENT_FIELDS = (
    "event_id",
    "invalidation_id",
    "changed_inputs",
    "affected_obligation_ids",
    "affected_receipt_ids",
    "affected_criteria",
    "affected_goal_ids",
    "criteria_by_goal",
    "bindings",
    "evidence_bindings",
    "source_tree",
    "source_tree_id",
    "repository_tree",
    "repository_tree_id",
    "tree_id",
    "invalidation_records",
    "historical_receipts",
    "replacement_tasks",
    "dependency_edges",
    "conflict_edges",
    "result_index_id",
    "schema_version",
)


def _proof_invalidation_mapping(value: Any) -> dict[str, Any]:
    """Project a typed or persisted proof invalidation to a plain mapping."""

    if isinstance(value, Mapping):
        payload = dict(value)
    else:
        to_dict = getattr(value, "to_dict", None)
        if callable(to_dict):
            projected = to_dict()
            if not isinstance(projected, Mapping):
                raise TypeError("proof invalidation to_dict() must return a mapping")
            payload = dict(projected)
        else:
            payload = {
                name: getattr(value, name)
                for name in _PROOF_INVALIDATION_EVENT_FIELDS
                if hasattr(value, name)
            }
            if not payload:
                raise TypeError("proof invalidation must be an event object or mapping")

    # Accept the orchestration result as a convenience in addition to its
    # event.  The canonical ProofInvalidationResult uses ``event``; aliases
    # cover early persisted packet spellings.
    has_event_fields = any(
        name in payload
        for name in (
            "changed_inputs",
            "affected_obligation_ids",
            "affected_receipt_ids",
            "affected_goal_ids",
            "affected_criteria",
        )
    )
    if not has_event_fields:
        for name in ("event", "receipt", "invalidation_event", "invalidation_receipt"):
            nested = payload.get(name)
            if nested is not None:
                return _proof_invalidation_mapping(nested)
        for name in ("event", "receipt", "invalidation_event", "invalidation_receipt"):
            nested = getattr(value, name, None)
            if nested is not None:
                return _proof_invalidation_mapping(nested)
    return {str(key): _json_value(item) for key, item in payload.items()}


def _proof_invalidation_records(value: Any) -> tuple[dict[str, Any], ...]:
    """Normalize possibly typed records without losing their payload."""

    if value in (None, ""):
        return ()
    if isinstance(value, Mapping):
        values: Iterable[Any] = (value,)
    elif isinstance(value, (str, bytes)) or not isinstance(value, Iterable):
        values = (value,)
    else:
        values = value
    records: list[dict[str, Any]] = []
    for item in values:
        if isinstance(item, Mapping):
            record = dict(item)
        else:
            to_dict = getattr(item, "to_dict", None)
            if callable(to_dict):
                projected = to_dict()
                record = dict(projected) if isinstance(projected, Mapping) else {"value": projected}
            else:
                record = {
                    name: getattr(item, name)
                    for name in (
                        "goal_id",
                        "goal_ids",
                        "criterion_id",
                        "acceptance_criterion",
                        "criterion",
                        "obligation_id",
                        "receipt_id",
                        "provenance_id",
                        "task_id",
                        "depends_on",
                        "dependency_ids",
                        "conflicts_with",
                        "conflict_ids",
                    )
                    if hasattr(item, name)
                }
                if not record:
                    record = {"value": item}
        records.append({str(key): _json_value(member) for key, member in record.items()})
    return _mapping_tuple(records)


def _proof_invalidation_ids(value: Any, *field_names: str) -> tuple[str, ...]:
    if value in (None, ""):
        return ()
    if isinstance(value, Mapping):
        values: Iterable[Any] = (value,)
    elif isinstance(value, (str, bytes)) or not isinstance(value, Iterable):
        values = (value,)
    else:
        values = value
    result: list[Any] = []
    for item in values:
        if isinstance(item, Mapping):
            selected = next(
                (item.get(name) for name in field_names if item.get(name) not in (None, "")),
                "",
            )
            result.append(selected)
        else:
            result.append(item)
    return _string_tuple(result)


def _goal_ids_from_invalidation_record(record: Mapping[str, Any]) -> tuple[str, ...]:
    values: list[Any] = []
    for name in ("goal_id", "affected_goal_id", "owner_goal_id"):
        if record.get(name) not in (None, ""):
            values.append(record.get(name))
    for name in ("goal_ids", "affected_goal_ids", "owner_goal_ids"):
        value = record.get(name)
        if isinstance(value, str):
            values.append(value)
        elif isinstance(value, Iterable) and not isinstance(value, (bytes, Mapping)):
            values.extend(value)
    return _string_tuple(values)


def _records_for_invalidation_goal(
    records: Sequence[Mapping[str, Any]], goal_id: str
) -> tuple[dict[str, Any], ...]:
    """Keep records explicitly assigned to a goal plus shared records."""

    return _mapping_tuple(
        record
        for record in records
        if not _goal_ids_from_invalidation_record(record)
        or goal_id in _goal_ids_from_invalidation_record(record)
    )


def contradictions_from_proof_invalidation(
    invalidation: Any,
    *,
    detected_at: datetime | str | None = None,
) -> list[ContradictionEvidence]:
    """Convert one transitive proof invalidation into per-goal contradictions.

    The adapter intentionally uses structural typing.  This keeps
    :mod:`goal_completion` independent of the proof index while accepting
    both a typed ``ProofInvalidationEvent`` and its persisted mapping.  Only
    explicitly affected goals receive contradictions; unrelated completed
    goals therefore remain stable.

    Event and contradiction identities exclude detection time.  Replaying an
    identical invalidation yields the same contradiction IDs and replacement
    task records, allowing :func:`reopen_goal_for_contradictions` to absorb the
    replay through its existing receipt ledger.
    """

    payload = _proof_invalidation_mapping(invalidation)
    changed_inputs = _proof_invalidation_records(
        payload.get("changed_inputs", payload.get("invalidated_inputs", ()))
    )
    obligation_ids = _proof_invalidation_ids(
        payload.get(
            "affected_obligation_ids",
            payload.get("invalidated_obligation_ids", payload.get("obligation_ids", ())),
        ),
        "obligation_id",
        "subject_id",
        "id",
    )
    receipt_ids = _proof_invalidation_ids(
        payload.get(
            "affected_receipt_ids",
            payload.get("invalidated_receipt_ids", payload.get("receipt_ids", ())),
        ),
        "receipt_id",
        "receipt_cid",
        "provenance_id",
        "subject_id",
        "id",
    )
    source_tree = str(
        payload.get(
            "source_tree",
            payload.get(
                "source_tree_id",
                payload.get(
                    "repository_tree",
                    payload.get("repository_tree_id", payload.get("tree_id", "")),
                ),
            ),
        )
        or ""
    ).strip()
    invalidation_records = _proof_invalidation_records(
        payload.get("invalidation_records", payload.get("invalidations", ()))
    )
    historical_receipts = _proof_invalidation_records(
        payload.get(
            "historical_receipts",
            payload.get("invalidated_receipts", payload.get("receipt_history", ())),
        )
    )
    replacement_tasks = _proof_invalidation_records(
        payload.get(
            "replacement_tasks",
            payload.get("scheduled_work", payload.get("newly_scheduled_work", ())),
        )
    )
    dependency_edges = _proof_invalidation_records(payload.get("dependency_edges", ()))
    conflict_edges = _proof_invalidation_records(payload.get("conflict_edges", ()))

    criterion_records = _proof_invalidation_records(
        payload.get("affected_criteria", payload.get("criteria", ()))
    )
    binding_records = _proof_invalidation_records(
        payload.get(
            "evidence_bindings",
            payload.get("bindings", payload.get("proof_bindings", ())),
        )
    )
    all_bindings = _mapping_tuple((*criterion_records, *binding_records))

    criteria_by_goal: dict[str, set[str]] = {}
    global_criteria: set[str] = set()
    goal_ids: set[str] = set(
        _proof_invalidation_ids(
            payload.get("affected_goal_ids", payload.get("goal_ids", ())),
            "goal_id",
            "id",
        )
    )
    for record in all_bindings:
        criterion = str(
            record.get(
                "acceptance_criterion",
                record.get("criterion", record.get("criterion_id", record.get("value", ""))),
            )
            or ""
        ).strip()
        record_goals = _goal_ids_from_invalidation_record(record)
        goal_ids.update(record_goals)
        if not criterion:
            continue
        if record_goals:
            for goal_id in record_goals:
                criteria_by_goal.setdefault(goal_id, set()).add(criterion)
        else:
            global_criteria.add(criterion)

    indexed_criteria = payload.get("criteria_by_goal")
    if isinstance(indexed_criteria, Mapping):
        for raw_goal_id, raw_criteria in indexed_criteria.items():
            goal_id = str(raw_goal_id or "").strip()
            if not goal_id:
                continue
            goal_ids.add(goal_id)
            records = _proof_invalidation_records(raw_criteria)
            for record in records:
                criterion = str(
                    record.get(
                        "acceptance_criterion",
                        record.get(
                            "criterion", record.get("criterion_id", record.get("value", ""))
                        ),
                    )
                    or ""
                ).strip()
                if criterion:
                    criteria_by_goal.setdefault(goal_id, set()).add(criterion)

    # Goal-aware replacement records are useful compatibility evidence when a
    # producer persisted an early packet without affected_goal_ids.
    for record in replacement_tasks:
        goal_ids.update(_goal_ids_from_invalidation_record(record))

    event_id = str(
        payload.get(
            "event_id",
            payload.get(
                "invalidation_id",
                payload.get("receipt_id", payload.get("content_id", "")),
            ),
        )
        or ""
    ).strip()
    if not event_id:
        event_id = _stable_fingerprint(
            "proof-invalidation",
            {
                "changed_inputs": changed_inputs,
                "affected_obligation_ids": obligation_ids,
                "affected_receipt_ids": receipt_ids,
                "affected_goal_ids": sorted(goal_ids),
                "affected_criteria": all_bindings,
                "source_tree": source_tree,
                "invalidation_records": invalidation_records,
            },
        )

    changed_labels = tuple(
        str(
            record.get(
                "key",
                (
                    f"{record.get('kind')}:{record.get('value')}"
                    if record.get("kind") and record.get("value")
                    else record.get("value", "")
                ),
            )
            or ""
        ).strip()
        for record in changed_inputs
    )
    changed_summary = ", ".join(item for item in changed_labels if item)

    contradictions: list[ContradictionEvidence] = []
    for goal_id in sorted(goal_ids, key=lambda item: (item.casefold(), item)):
        goal_tasks = _records_for_invalidation_goal(replacement_tasks, goal_id)
        goal_dependency_edges = _records_for_invalidation_goal(dependency_edges, goal_id)
        goal_conflict_edges = _records_for_invalidation_goal(conflict_edges, goal_id)
        impacted = _string_tuple((*global_criteria, *criteria_by_goal.get(goal_id, ())))
        summary = f"Proof evidence for goal {goal_id} was invalidated by semantic change" + (
            f": {changed_summary}." if changed_summary else "."
        )
        fingerprint = _stable_fingerprint(
            "proof-invalidation-contradiction",
            {"event_id": event_id, "goal_id": goal_id},
        )
        contradictions.append(
            ContradictionEvidence(
                goal_id=goal_id,
                kind="invalidated_receipt",
                summary=summary,
                impacted_criteria=impacted,
                invalidated_evidence=receipt_ids,
                source_receipt=payload,
                source_receipt_id=event_id,
                scheduled_work=goal_tasks,
                invalidation_event_id=event_id,
                changed_inputs=changed_inputs,
                affected_obligation_ids=obligation_ids,
                affected_receipt_ids=receipt_ids,
                source_tree=source_tree,
                invalidation_records=invalidation_records,
                historical_receipts=historical_receipts,
                dependency_edges=goal_dependency_edges,
                conflict_edges=goal_conflict_edges,
                fingerprint=fingerprint,
                detected_at=detected_at,
            )
        )
    return contradictions


# Early integration packets used the noun-first spelling.  Keep it as a
# public alias while documenting contradictions_from_proof_invalidation as
# the canonical API.
proof_invalidation_contradictions = contradictions_from_proof_invalidation


@dataclass(frozen=True)
class CompletionEvidence:
    """Proof offered for one acceptance criterion.

    Fields are permissive at construction time so incomplete external records
    can be evaluated and rejected with actionable reasons instead of failing
    deserialization.  ``producer_id``/``tree_id`` are compatibility aliases for
    the more descriptive canonical fields.

    Formal proof fields are an additive contract.  Legacy validation evidence
    remains readable and continues to represent validation only.  It acquires
    proof assurance solely when it embeds a canonical :class:`ProofReceipt`
    whose content identity and provider-independent projections can be
    re-derived.
    """

    acceptance_criterion: str
    producing_task_or_scan: str = ""
    validation_receipt: Mapping[str, Any] | str | None = None
    repository_tree: str = ""
    freshness: Mapping[str, Any] | str | bool | None = None
    provenance_cid: str = ""
    producer_id: str = ""
    producer_kind: str = "task"
    producer_channel: str = ""
    channel_proof_revision: str = ""
    repository_id: str = ""
    tree_id: str = ""
    objective_revision: str = ""
    analyzer_version: str = ""
    configuration_revision: str = ""
    observed_at: datetime | str | None = None
    fresh_until: datetime | str | None = None
    validation_passed: bool | None = None
    contradictory: bool = False
    contradiction: str = ""
    obligation_id: str = ""
    proof_receipt_id: str = ""
    required_assurance: AssuranceLevel | str = AssuranceLevel.UNVERIFIED
    authoritative_assurance: AssuranceLevel | str = AssuranceLevel.UNVERIFIED
    assurance: AssuranceLevel | str | None = None
    proof_verdict: ProofVerdict | str = ""
    proof_freshness: EvidenceFreshness | str = ""
    proof_receipt: Mapping[str, Any] | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: int = GOAL_COMPLETION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "acceptance_criterion", str(self.acceptance_criterion or "").strip()
        )
        producer = str(self.producing_task_or_scan or self.producer_id or "").strip()
        object.__setattr__(self, "producing_task_or_scan", producer)
        object.__setattr__(self, "producer_id", str(self.producer_id or producer).strip())
        object.__setattr__(self, "producer_kind", str(self.producer_kind or "task").strip().lower())
        object.__setattr__(
            self,
            "producer_channel",
            str(self.producer_channel or "").strip(),
        )
        object.__setattr__(
            self,
            "channel_proof_revision",
            str(self.channel_proof_revision or "").strip(),
        )
        tree = str(self.repository_tree or self.tree_id or "").strip()
        object.__setattr__(self, "repository_tree", tree)
        object.__setattr__(self, "tree_id", str(self.tree_id or tree).strip())
        object.__setattr__(self, "repository_id", str(self.repository_id or "").strip())
        object.__setattr__(self, "objective_revision", str(self.objective_revision or "").strip())
        object.__setattr__(self, "analyzer_version", str(self.analyzer_version or "").strip())
        object.__setattr__(
            self,
            "configuration_revision",
            str(self.configuration_revision or "").strip(),
        )
        object.__setattr__(self, "provenance_cid", str(self.provenance_cid or "").strip())
        object.__setattr__(
            self, "observed_at", _utc_datetime(self.observed_at, field_name="observed_at")
        )
        object.__setattr__(
            self, "fresh_until", _utc_datetime(self.fresh_until, field_name="fresh_until")
        )
        object.__setattr__(self, "obligation_id", str(self.obligation_id or "").strip())
        object.__setattr__(self, "proof_receipt_id", str(self.proof_receipt_id or "").strip())
        required = _assurance_level(self.required_assurance)
        normalized_authoritative = _assurance_level(self.authoritative_assurance)
        actual_source = self.authoritative_assurance
        if (
            self.assurance not in (None, "")
            and normalized_authoritative is AssuranceLevel.UNVERIFIED
        ):
            actual_source = self.assurance
        actual = _assurance_level(actual_source)
        object.__setattr__(
            self,
            "required_assurance",
            required if required is not None else str(self.required_assurance or "").strip(),
        )
        object.__setattr__(
            self,
            "authoritative_assurance",
            actual if actual is not None else str(actual_source or "").strip(),
        )
        object.__setattr__(
            self,
            "assurance",
            actual if actual is not None else str(actual_source or "").strip(),
        )
        verdict = _proof_verdict(self.proof_verdict)
        object.__setattr__(
            self,
            "proof_verdict",
            verdict if verdict is not None else str(self.proof_verdict or "").strip(),
        )
        proof_freshness = _proof_freshness(self.proof_freshness)
        object.__setattr__(
            self,
            "proof_freshness",
            proof_freshness
            if proof_freshness is not None
            else str(self.proof_freshness or "").strip(),
        )
        receipt_value = self.proof_receipt
        if isinstance(receipt_value, ProofReceipt):
            receipt_value = receipt_value.to_dict()
        object.__setattr__(
            self,
            "proof_receipt",
            dict(receipt_value) if isinstance(receipt_value, Mapping) else None,
        )
        object.__setattr__(self, "metadata", dict(self.metadata or {}))
        object.__setattr__(self, "schema_version", int(self.schema_version))

    @property
    def evidence_cid(self) -> str:
        return self.provenance_cid

    @property
    def proof_obligation_id(self) -> str:
        return self.obligation_id

    @property
    def formal_proof_receipt_id(self) -> str:
        return self.proof_receipt_id

    @property
    def actual_assurance(self) -> AssuranceLevel | str:
        return self.authoritative_assurance

    @property
    def receipt_freshness(self) -> EvidenceFreshness | str:
        return self.proof_freshness

    @property
    def proof_tree_id(self) -> str:
        return self.repository_tree

    @property
    def provenance_id(self) -> str:
        return self.provenance_cid

    @property
    def proof_provenance_id(self) -> str:
        return self.provenance_cid

    @property
    def requires_proof(self) -> bool:
        required = _assurance_level(self.required_assurance)
        return bool(required is not None and required is not AssuranceLevel.UNVERIFIED)

    @property
    def assurance_satisfied(self) -> bool:
        required = _assurance_level(self.required_assurance)
        actual = _assurance_level(self.authoritative_assurance)
        if required is None or actual is None:
            return False
        has_proof_reference = bool(
            self.obligation_id or self.proof_receipt_id or self.proof_receipt
        )
        if not has_proof_reference:
            return assurance_satisfies(actual, required)
        if not isinstance(self.proof_receipt, Mapping):
            return False
        try:
            receipt = ProofReceipt.from_dict(self.proof_receipt)
            receipt_finished_at = _utc_datetime(
                receipt.finished_at,
                field_name="proof receipt finished_at",
            )
        except (ContractValidationError, TypeError, ValueError):
            return False
        return bool(
            receipt_finished_at is not None
            and self.observed_at == receipt_finished_at
            and self.obligation_id == receipt.obligation_id
            and self.proof_receipt_id == receipt.receipt_id
            and self.repository_tree == receipt.repository_tree_id
            and (not self.repository_id or self.repository_id == receipt.repository_id)
            and actual is receipt.authoritative_assurance
            and _proof_verdict(self.proof_verdict) is receipt.authoritative_verdict
            and receipt.authoritative_verdict is ProofVerdict.PROVED
            and _proof_freshness(self.proof_freshness) is receipt.freshness
            and receipt.freshness is EvidenceFreshness.CURRENT
            and assurance_satisfies(receipt.authoritative_assurance, required)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "acceptance_criterion": self.acceptance_criterion,
            "producing_task_or_scan": self.producing_task_or_scan,
            "producer_id": self.producer_id,
            "producer_kind": self.producer_kind,
            "producer_channel": self.producer_channel,
            "channel_proof_revision": self.channel_proof_revision,
            "validation_receipt": _json_value(self.validation_receipt),
            "repository_id": self.repository_id,
            "repository_tree": self.repository_tree,
            "tree_id": self.tree_id,
            "objective_revision": self.objective_revision,
            "analyzer_version": self.analyzer_version,
            "configuration_revision": self.configuration_revision,
            "freshness": _json_value(self.freshness),
            "observed_at": _json_value(self.observed_at),
            "fresh_until": _json_value(self.fresh_until),
            "provenance_cid": self.provenance_cid,
            "validation_passed": self.validation_passed,
            "contradictory": self.contradictory,
            "contradiction": self.contradiction,
            "obligation_id": self.obligation_id,
            "proof_obligation_id": self.obligation_id,
            "proof_receipt_id": self.proof_receipt_id,
            "required_assurance": _json_value(self.required_assurance),
            "authoritative_assurance": _json_value(self.authoritative_assurance),
            "assurance": _json_value(self.authoritative_assurance),
            "assurance_satisfied": self.assurance_satisfied,
            "proof_verdict": _json_value(self.proof_verdict),
            "proof_freshness": _json_value(self.proof_freshness),
            "proof_receipt": _json_value(self.proof_receipt),
            "metadata": _json_value(self.metadata),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "CompletionEvidence":
        values = dict(payload)
        source_schema = values.get("schema_version", values.get("version"))
        if source_schema in (0, "0"):
            metadata = dict(values.get("metadata") or {})
            metadata.setdefault("source_schema_version", 0)
            values["metadata"] = metadata
            values["schema_version"] = GOAL_COMPLETION_SCHEMA_VERSION
        # Common persisted receipt spellings.
        values.setdefault(
            "acceptance_criterion",
            values.get(
                "criterion", values.get("acceptance", values.get("acceptance_criteria", ""))
            ),
        )
        values.setdefault(
            "producing_task_or_scan",
            values.get(
                "producer_id",
                values.get("producer", values.get("task_id", values.get("scan_id", ""))),
            ),
        )
        values.setdefault(
            "repository_tree",
            values.get(
                "tree_id", values.get("tree_identity", values.get("repository_tree_id", ""))
            ),
        )
        binding = values.get("binding")
        binding = binding if isinstance(binding, Mapping) else {}
        values.setdefault(
            "objective_revision",
            values.get("objective_id", binding.get("objective_revision", "")),
        )
        values.setdefault(
            "analyzer_version",
            values.get(
                "analyzer_revision",
                values.get("analyzer_id", binding.get("analyzer_version", "")),
            ),
        )
        values.setdefault(
            "configuration_revision",
            values.get(
                "configuration_id",
                binding.get("configuration_revision", binding.get("configuration_id", "")),
            ),
        )
        values.setdefault("provenance_cid", values.get("receipt_cid", values.get("cid", "")))
        values.setdefault(
            "validation_receipt", values.get("validation", values.get("receipt", None))
        )
        values.setdefault("freshness", values.get("fresh", values.get("freshness_status", None)))
        values.setdefault(
            "obligation_id",
            values.get("proof_obligation_id", values.get("formal_obligation_id", "")),
        )
        values.setdefault(
            "proof_receipt_id",
            values.get("formal_proof_receipt_id", values.get("trusted_proof_receipt_id", "")),
        )
        values.setdefault(
            "authoritative_assurance",
            values.get("assurance", values.get("actual_assurance", AssuranceLevel.UNVERIFIED)),
        )
        values.setdefault(
            "proof_verdict",
            values.get("authoritative_verdict", values.get("formal_proof_verdict", "")),
        )
        values.setdefault(
            "proof_freshness",
            values.get("receipt_freshness", values.get("formal_proof_freshness", "")),
        )
        values.setdefault(
            "proof_receipt",
            values.get("trusted_proof_receipt", values.get("formal_proof_receipt")),
        )
        values.setdefault(
            "observed_at",
            values.get("finished_at", values.get("generated_at", values.get("created_at", None))),
        )
        allowed = cls.__dataclass_fields__
        return cls(**{key: value for key, value in values.items() if key in allowed})

    @classmethod
    def from_scan_receipt(
        cls,
        *,
        acceptance_criterion: str,
        receipt: Any,
        validation_receipt: Mapping[str, Any] | str,
        validation_passed: bool = True,
    ) -> "CompletionEvidence":
        """Build evidence from a typed REF-200 scan receipt."""

        safe = bool(getattr(receipt, "safe_for_completion_reasoning", False))
        return cls(
            acceptance_criterion=acceptance_criterion,
            producing_task_or_scan=f"scan:{getattr(receipt, 'analyzer_version', '')}",
            producer_kind="scan",
            validation_receipt=validation_receipt,
            validation_passed=validation_passed,
            repository_id=str(getattr(receipt, "repository_id", "")),
            repository_tree=str(getattr(receipt, "tree_id", "")),
            observed_at=getattr(receipt, "finished_at", None),
            freshness={"fresh": True},
            provenance_cid=str(getattr(receipt, "receipt_cid", "")),
            metadata={
                "safe_for_completion_reasoning": safe,
                "terminal_reason": str(
                    getattr(
                        getattr(receipt, "terminal_reason", ""),
                        "value",
                        getattr(receipt, "terminal_reason", ""),
                    )
                ),
            },
        )

    @classmethod
    def from_proof_receipt(
        cls,
        *,
        acceptance_criterion: str,
        receipt: ProofReceipt | None = None,
        proof_receipt: ProofReceipt | None = None,
        obligation: CodeProofObligation | str | None = None,
        required_assurance: AssuranceLevel | str | None = None,
        producing_task_or_scan: str = "",
        validation_receipt: Mapping[str, Any] | str | None = None,
        validation_passed: bool | None = None,
        observed_at: datetime | str | None = None,
        fresh_until: datetime | str | None = None,
        provenance_cid: str = "",
        metadata: Mapping[str, Any] | None = None,
    ) -> "CompletionEvidence":
        """Map one canonical trusted receipt into criterion evidence.

        Validation and proof are intentionally separate inputs.  A proved
        theorem does not manufacture a passing test result, and a passing test
        does not manufacture formal assurance.
        """

        if proof_receipt is not None and receipt is not None and proof_receipt is not receipt:
            raise ValueError("receipt and proof_receipt must identify the same receipt")
        selected = proof_receipt or receipt
        if not isinstance(selected, ProofReceipt):
            raise TypeError("proof_receipt must be a canonical ProofReceipt")
        if isinstance(obligation, CodeProofObligation):
            obligation_id = obligation.obligation_id
            obligation_required = obligation.required_assurance
            producer = producing_task_or_scan or obligation.task_id
            if selected.obligation_id != obligation_id:
                raise ValueError("proof receipt does not bind the supplied obligation")
            if selected.repository_tree_id != obligation.repository_tree_id:
                raise ValueError("proof receipt and obligation bind different repository trees")
            if obligation.repository_id and selected.repository_id != obligation.repository_id:
                raise ValueError("proof receipt and obligation bind different repositories")
        else:
            obligation_id = str(obligation or selected.obligation_id).strip()
            obligation_required = AssuranceLevel.KERNEL_VERIFIED
            producer = producing_task_or_scan
            if obligation_id and selected.obligation_id != obligation_id:
                raise ValueError("proof receipt does not bind the supplied obligation")
        required = required_assurance if required_assurance is not None else obligation_required
        normalized_required = _assurance_level(required)
        if normalized_required is None:
            raise ValueError(f"unknown required assurance {required!r}")
        reference = selected.completion_reference(normalized_required)
        proof_finished_at = selected.finished_at or None
        combined_metadata = dict(metadata or {})
        combined_metadata.update(
            {
                "proof_assurance_reason_codes": list(reference["reason_codes"]),
                "proof_plan_id": selected.plan_id,
                "proof_attempt_id": selected.attempt_id,
                "proof_policy_id": selected.policy_id,
                "kernel_id": selected.kernel_id,
            }
        )
        return cls(
            acceptance_criterion=acceptance_criterion,
            producing_task_or_scan=producer or f"proof:{selected.attempt_id}",
            producer_kind="task",
            validation_receipt=validation_receipt,
            validation_passed=validation_passed,
            repository_id=selected.repository_id,
            repository_tree=selected.repository_tree_id,
            observed_at=observed_at if observed_at is not None else proof_finished_at,
            fresh_until=fresh_until,
            freshness=selected.freshness is EvidenceFreshness.CURRENT,
            provenance_cid=provenance_cid or selected.receipt_id,
            obligation_id=selected.obligation_id,
            proof_receipt_id=selected.receipt_id,
            required_assurance=normalized_required,
            authoritative_assurance=selected.authoritative_assurance,
            proof_verdict=selected.authoritative_verdict,
            proof_freshness=selected.freshness,
            proof_receipt=selected.to_dict(),
            metadata=combined_metadata,
        )


@dataclass(frozen=True)
class EvidenceValidationResult:
    evidence: CompletionEvidence
    valid: bool
    reason_codes: tuple[str, ...] = ()
    actionable_reasons: tuple[str, ...] = ()
    validation_succeeded: bool | None = None
    assurance_satisfied: bool | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "valid": self.valid,
            "reason_codes": list(self.reason_codes),
            "actionable_reasons": list(self.actionable_reasons),
            "evidence": self.evidence.to_dict(),
        }
        if _proof_requirement_payload(self) is not None:
            payload.update(
                {
                    "validation_succeeded": self.validation_succeeded,
                    "assurance_satisfied": self.assurance_satisfied,
                    "required_assurance": _json_value(self.evidence.required_assurance),
                    "authoritative_assurance": _json_value(self.evidence.authoritative_assurance),
                }
            )
        return payload


def _proof_requirement_payload(
    result: EvidenceValidationResult,
    *,
    goal_id: str = "",
) -> dict[str, Any] | None:
    evidence = result.evidence
    required = _assurance_level(evidence.required_assurance)
    has_reference = bool(
        evidence.obligation_id
        or evidence.proof_receipt_id
        or evidence.proof_receipt
        or (required is not None and required is not AssuranceLevel.UNVERIFIED)
    )
    if not has_reference:
        return None
    return {
        "goal_id": str(goal_id or ""),
        "acceptance_criterion": evidence.acceptance_criterion,
        "obligation_id": evidence.obligation_id,
        "proof_receipt_id": evidence.proof_receipt_id,
        "required_assurance": _json_value(evidence.required_assurance),
        "authoritative_assurance": _json_value(evidence.authoritative_assurance),
        "proof_verdict": _json_value(evidence.proof_verdict),
        "freshness": _json_value(evidence.proof_freshness),
        "repository_tree": evidence.repository_tree,
        "provenance_id": evidence.provenance_cid,
        "validation_succeeded": result.validation_succeeded,
        "assurance_satisfied": result.assurance_satisfied,
        "satisfied": result.assurance_satisfied is True,
        "contradicted": "contradictory_evidence" in result.reason_codes
        or "contradicted_proof" in result.reason_codes,
        "reason_codes": list(result.reason_codes),
    }


def _validation_passed(evidence: CompletionEvidence) -> bool | None:
    declared = (
        _bool_value(evidence.validation_passed) if evidence.validation_passed is not None else None
    )
    receipt = evidence.validation_receipt
    if not isinstance(receipt, Mapping):
        return declared
    # A positive convenience flag must never override a terminal failure in
    # the receipt it summarizes.  Persisted records occasionally contain both
    # during interrupted status updates, and completion must fail closed.
    attempted = _bool_value(receipt.get("attempted")) if "attempted" in receipt else None
    if attempted is False:
        return False
    for flag in ("timed_out", "cancelled", "canceled", "skipped", "partial"):
        if _bool_value(receipt.get(flag)) is True:
            return False
    receipt_result: bool | None = None
    if "passed" in receipt:
        receipt_result = _bool_value(receipt["passed"])
    elif "returncode" in receipt:
        try:
            receipt_result = int(receipt["returncode"]) == 0 and attempted is not False
        except (TypeError, ValueError):
            receipt_result = False
    status = str(receipt.get("status", receipt.get("terminal_reason", ""))).strip().lower()
    if status in {"passed", "pass", "succeeded", "success", "verified", "ok"}:
        status_result: bool | None = True
    elif status in {
        "failed",
        "failure",
        "error",
        "timed_out",
        "timeout",
        "cancelled",
        "canceled",
        "skipped",
        "unattempted",
        "partial",
        "duplicate_only",
        "duplicate-only",
        "unsupported",
        "disabled",
        "cooldown",
    }:
        status_result = False
    else:
        status_result = None
    outcomes = [item for item in (declared, receipt_result, status_result) if item is not None]
    if False in outcomes:
        return False
    return True if True in outcomes else None


def _bool_value(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in {0, 1}:
        return bool(value)
    normalized = str(value or "").strip().lower()
    if normalized in {"true", "yes", "1", "passed", "fresh"}:
        return True
    if normalized in {"false", "no", "0", "failed", "stale"}:
        return False
    return None


def _freshness_claim(evidence: CompletionEvidence) -> bool | None:
    value = evidence.freshness
    if isinstance(value, bool):
        return value
    if isinstance(value, Mapping):
        for key in ("fresh", "is_fresh"):
            if key in value:
                return _bool_value(value[key])
        status = str(value.get("status", "")).strip().lower()
        if status:
            return status == "fresh"
        return None
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"fresh", "current", "true", "yes"}:
            return True
        if normalized in {"stale", "expired", "false", "no"}:
            return False
    return None


def validate_completion_evidence(
    evidence: CompletionEvidence | Mapping[str, Any],
    *,
    repository_tree: str = "",
    repository_id: str = "",
    objective_revision: str = "",
    analyzer_version: str = "",
    configuration_revision: str = "",
    require_artifact_binding: bool = False,
    now: datetime | str | None = None,
    freshness_seconds: float = DEFAULT_EVIDENCE_FRESHNESS_SECONDS,
    clock_skew_seconds: float = DEFAULT_CLOCK_SKEW_SECONDS,
) -> EvidenceValidationResult:
    """Validate one evidence record, collecting every actionable defect."""

    if not isinstance(evidence, CompletionEvidence):
        evidence = CompletionEvidence.from_dict(evidence)
    reason_codes: list[str] = []
    reasons: list[str] = []

    def reject(code: str, reason: str) -> None:
        if code not in reason_codes:
            reason_codes.append(code)
            reasons.append(reason)

    if not evidence.acceptance_criterion:
        reject(
            "missing_acceptance_criterion", "Name the acceptance criterion this evidence proves."
        )
    if evidence.schema_version != GOAL_COMPLETION_SCHEMA_VERSION:
        reject(
            "unsupported_schema_version",
            "Migrate the evidence record to the current completion schema.",
        )
    if not evidence.producing_task_or_scan:
        reject("missing_producer", "Record the producing task or scan for this evidence.")
    if evidence.producer_kind not in {"task", "scan"}:
        reject("invalid_producer_kind", "Set producer_kind to 'task' or 'scan'.")
    if not evidence.validation_receipt:
        reject("missing_validation_receipt", "Attach the validation receipt for this criterion.")
    passed = _validation_passed(evidence)
    if passed is not True:
        code = "failed_validation" if passed is False else "unknown_validation_result"
        reject(code, "Run the criterion validation successfully and attach a passing receipt.")
    if not evidence.repository_tree:
        reject(
            "missing_repository_tree",
            "Bind the evidence to the repository tree that was validated.",
        )
    elif evidence.tree_id and evidence.tree_id != evidence.repository_tree:
        reject(
            "repository_tree_alias_mismatch",
            "Use one canonical repository tree value throughout the evidence record.",
        )
    elif repository_tree and evidence.repository_tree != str(repository_tree):
        reject(
            "repository_tree_mismatch", "Regenerate evidence against the current repository tree."
        )
    if require_artifact_binding and not evidence.repository_id:
        reject(
            "missing_repository_id",
            "Bind completion evidence to the repository that was validated.",
        )
    elif repository_id and evidence.repository_id and evidence.repository_id != str(repository_id):
        reject("repository_mismatch", "Use evidence produced by the current repository.")
    if require_artifact_binding:
        if not evidence.objective_revision:
            reject(
                "missing_objective_revision",
                "Bind completion evidence to the canonical semantic objective revision.",
            )
        elif objective_revision and evidence.objective_revision != str(objective_revision):
            reject(
                "objective_revision_mismatch",
                "Regenerate completion evidence after the goal or its acceptance policy changed.",
            )
        if not evidence.analyzer_version:
            reject(
                "missing_analyzer_version",
                "Bind completion evidence to the analyzer version that produced it.",
            )
        elif analyzer_version and evidence.analyzer_version != str(analyzer_version):
            reject(
                "analyzer_version_mismatch",
                "Regenerate completion evidence with the analyzer version bound by the completion gate.",
            )
        if not evidence.configuration_revision:
            reject(
                "missing_configuration_revision",
                "Bind completion evidence to the analyzer configuration revision.",
            )
        elif configuration_revision and evidence.configuration_revision != str(
            configuration_revision
        ):
            reject(
                "configuration_revision_mismatch",
                "Regenerate completion evidence with the configuration bound by the completion gate.",
            )
    if not evidence.provenance_cid:
        reject("missing_provenance_cid", "Persist the evidence and attach its provenance CID.")
    source_policy = evidence.metadata.get("evidence_source_policy")
    if not isinstance(source_policy, Mapping) and evidence.acceptance_criterion:
        try:
            # Local import preserves the contract module's independence while
            # ensuring API callers cannot bypass the objective source policy
            # by skipping the markdown tracker.
            from .objective_graph import completion_evidence_source_decision

            source_policy = completion_evidence_source_decision(
                evidence,
                repository_tree=str(repository_tree or evidence.repository_tree),
            ).to_dict()
        except (TypeError, ValueError):
            source_policy = {
                "satisfies": False,
                "reason_codes": ["source_policy_evaluation_failed"],
            }
    if isinstance(source_policy, Mapping) and source_policy.get("satisfies") is not True:
        source_reasons = source_policy.get("reason_codes")
        if isinstance(source_reasons, str):
            source_reasons = (source_reasons,)
        if not isinstance(source_reasons, (list, tuple)):
            source_reasons = ()
        reject(
            "evidence_source_forbidden",
            "Use an exact typed receipt from an allowed implementation, validation, proof, benchmark, or runtime source.",
        )
        for source_reason in source_reasons:
            normalized_reason = str(source_reason).strip()
            if normalized_reason:
                reject(
                    f"evidence_source_{normalized_reason}",
                    f"Repair the evidence source policy violation: {normalized_reason}.",
                )

    receipt = (
        evidence.validation_receipt if isinstance(evidence.validation_receipt, Mapping) else {}
    )
    receipt_channel = str(receipt.get("producer_channel") or "").strip()
    receipt_channel_revision = str(receipt.get("channel_proof_revision") or "").strip()
    channel_proof = receipt.get("channel_proof")
    metadata_channel = str(evidence.metadata.get("producer_channel") or "").strip()
    metadata_channel_revision = str(evidence.metadata.get("channel_proof_revision") or "").strip()
    channel_binding_claimed = bool(
        evidence.producer_channel
        or evidence.channel_proof_revision
        or receipt_channel
        or receipt_channel_revision
        or channel_proof
        or metadata_channel
        or metadata_channel_revision
    )
    channel_binding_required = bool(require_artifact_binding or channel_binding_claimed)
    if channel_binding_required:
        if not evidence.producer_channel:
            reject(
                "missing_producer_channel",
                "Bind completion evidence to the producer channel required by its acceptance criterion.",
            )
        if not evidence.channel_proof_revision:
            reject(
                "missing_channel_proof_revision",
                "Bind completion evidence to the canonical revision of its channel proof.",
            )
        if not isinstance(evidence.validation_receipt, Mapping):
            reject(
                "missing_channel_proof",
                "Embed the channel proof in a structured validation receipt.",
            )
        else:
            if not receipt_channel:
                reject(
                    "missing_receipt_producer_channel",
                    "Record the producer channel in the validation receipt wrapper.",
                )
            elif evidence.producer_channel and receipt_channel != evidence.producer_channel:
                reject(
                    "producer_channel_mismatch",
                    "Use one producer channel throughout the evidence record and validation receipt.",
                )
            if not receipt_channel_revision:
                reject(
                    "missing_receipt_channel_proof_revision",
                    "Record the canonical channel proof revision in the validation receipt wrapper.",
                )
            elif (
                evidence.channel_proof_revision
                and receipt_channel_revision != evidence.channel_proof_revision
            ):
                reject(
                    "channel_proof_revision_mismatch",
                    "Use one channel proof revision throughout the evidence record and validation receipt.",
                )
            if not isinstance(channel_proof, Mapping):
                reject(
                    "missing_channel_proof",
                    "Embed the structured proof produced by the declared channel.",
                )
            else:
                proof_channel = str(channel_proof.get("channel") or "").strip()
                if not proof_channel:
                    reject(
                        "missing_channel_proof_channel",
                        "Bind the embedded channel proof to its producer channel.",
                    )
                elif evidence.producer_channel and proof_channel != evidence.producer_channel:
                    reject(
                        "producer_channel_mismatch",
                        "Use a channel proof produced by the evidence record's declared channel.",
                    )
                try:
                    derived_channel_revision = _namespaced_sha256_revision(
                        dict(channel_proof),
                        CHANNEL_PROOF_REVISION_NAMESPACE,
                    )
                except (TypeError, ValueError):
                    reject(
                        "invalid_channel_proof",
                        "Regenerate the channel proof with canonical JSON values.",
                    )
                else:
                    if (
                        evidence.channel_proof_revision
                        and evidence.channel_proof_revision != derived_channel_revision
                    ):
                        reject(
                            "channel_proof_revision_mismatch",
                            "Regenerate the channel proof revision from the embedded canonical proof.",
                        )
                    if (
                        receipt_channel_revision
                        and receipt_channel_revision != derived_channel_revision
                    ):
                        reject(
                            "channel_proof_revision_mismatch",
                            "Regenerate the validation receipt from the embedded canonical channel proof.",
                        )
            try:
                derived_provenance = _namespaced_sha256_revision(
                    {
                        key: value
                        for key, value in evidence.validation_receipt.items()
                        if key != "executed_at"
                    },
                    CHANNEL_EVIDENCE_PROVENANCE_NAMESPACE,
                )
            except (TypeError, ValueError):
                reject(
                    "invalid_channel_receipt",
                    "Regenerate the validation receipt with canonical JSON values.",
                )
            else:
                if evidence.provenance_cid != derived_provenance:
                    reject(
                        "provenance_cid_mismatch",
                        "Regenerate provenance from the canonical validation receipt wrapper.",
                    )
        if (
            metadata_channel
            and evidence.producer_channel
            and metadata_channel != evidence.producer_channel
        ):
            reject(
                "producer_channel_mismatch",
                "Use one producer channel throughout evidence metadata and the typed record.",
            )
        if (
            metadata_channel_revision
            and evidence.channel_proof_revision
            and metadata_channel_revision != evidence.channel_proof_revision
        ):
            reject(
                "channel_proof_revision_mismatch",
                "Use one channel proof revision throughout evidence metadata and the typed record.",
            )

    required = _assurance_level(evidence.required_assurance)
    declared_assurance = _assurance_level(evidence.authoritative_assurance)
    proof_supplied = bool(
        evidence.obligation_id
        or evidence.proof_receipt_id
        or evidence.proof_receipt
        or evidence.proof_verdict
        or evidence.proof_freshness
        or (declared_assurance is not None and declared_assurance is not AssuranceLevel.UNVERIFIED)
    )
    proof_required = bool(required is not None and required is not AssuranceLevel.UNVERIFIED)
    assurance_ok: bool | None = True if not proof_required and not proof_supplied else False
    if required is None:
        reject(
            "invalid_required_assurance",
            "Use a recognized required assurance level from the canonical proof trust lattice.",
        )
    if declared_assurance is None:
        reject(
            "invalid_authoritative_assurance",
            "Regenerate the completion mapping from a canonical proof receipt.",
        )
    if proof_required or proof_supplied:
        if not evidence.obligation_id:
            reject(
                "missing_proof_obligation",
                "Bind proof-required evidence to its canonical obligation identity.",
            )
        if not evidence.proof_receipt_id:
            reject(
                "missing_proof_receipt",
                "Attach the canonical proof receipt identity for this criterion.",
            )
        if not isinstance(evidence.proof_receipt, Mapping):
            reject(
                "untrusted_proof_reference",
                "Embed the canonical proof receipt so its verdict and assurance can be re-derived.",
            )
        else:
            try:
                trusted_receipt = ProofReceipt.from_dict(evidence.proof_receipt)
            except (ContractValidationError, TypeError, ValueError) as exc:
                reject(
                    "invalid_proof_receipt",
                    f"Regenerate the proof completion mapping from an untampered canonical receipt ({exc}).",
                )
            else:
                receipt_verdict = trusted_receipt.authoritative_verdict
                receipt_assurance = trusted_receipt.authoritative_assurance
                receipt_freshness = trusted_receipt.freshness
                if evidence.proof_receipt_id != trusted_receipt.receipt_id:
                    reject(
                        "proof_receipt_identity_mismatch",
                        "Use the content identity derived from the embedded canonical proof receipt.",
                    )
                if evidence.obligation_id != trusted_receipt.obligation_id:
                    reject(
                        "proof_obligation_mismatch",
                        "Use a proof receipt for the exact obligation required by this criterion.",
                    )
                if evidence.repository_tree != trusted_receipt.repository_tree_id:
                    reject(
                        "proof_tree_mismatch",
                        "Regenerate proof and completion evidence against the same repository tree.",
                    )
                if (
                    evidence.repository_id
                    and evidence.repository_id != trusted_receipt.repository_id
                ):
                    reject(
                        "proof_repository_mismatch",
                        "Use proof evidence produced by the current repository.",
                    )
                if declared_assurance is None or declared_assurance is not receipt_assurance:
                    reject(
                        "proof_assurance_mismatch",
                        "Derive authoritative assurance from the embedded receipt instead of a summary claim.",
                    )
                declared_verdict = _proof_verdict(evidence.proof_verdict)
                if declared_verdict is None or declared_verdict is not receipt_verdict:
                    reject(
                        "proof_verdict_mismatch",
                        "Derive the proof verdict from the embedded receipt.",
                    )
                declared_freshness = _proof_freshness(evidence.proof_freshness)
                if declared_freshness is None or declared_freshness is not receipt_freshness:
                    reject(
                        "proof_freshness_mismatch",
                        "Derive proof freshness from the embedded receipt.",
                    )
                receipt_finished_at: datetime | None = None
                if not trusted_receipt.finished_at:
                    reject(
                        "missing_proof_observed_at",
                        "Use a proof receipt with a completion timestamp so freshness can be checked.",
                    )
                else:
                    try:
                        receipt_finished_at = _utc_datetime(
                            trusted_receipt.finished_at,
                            field_name="proof receipt finished_at",
                        )
                    except (TypeError, ValueError):
                        reject(
                            "invalid_proof_observed_at",
                            "Regenerate the proof receipt with a valid timezone-aware completion timestamp.",
                        )
                if receipt_finished_at is not None and evidence.observed_at != receipt_finished_at:
                    reject(
                        "proof_observed_at_mismatch",
                        "Use the proof receipt completion timestamp as completion-evidence observed_at.",
                    )
                if receipt_freshness is not EvidenceFreshness.CURRENT:
                    reject(
                        "stale_proof_receipt",
                        "Regenerate the formal proof because its bound inputs are stale or unknown.",
                    )
                if receipt_verdict is not ProofVerdict.PROVED:
                    verdict_code = {
                        ProofVerdict.DISPROVED: "contradicted_proof",
                        ProofVerdict.INCONCLUSIVE: "inconclusive_proof",
                        ProofVerdict.UNSUPPORTED: "unsupported_proof",
                        ProofVerdict.ERROR: "proof_error",
                        ProofVerdict.CANCELLED: "proof_cancelled",
                    }.get(receipt_verdict, "unproved_receipt")
                    reject(
                        verdict_code,
                        f"Resolve the {receipt_verdict.value} proof obligation before completion.",
                    )
                if required is not None and not assurance_satisfies(receipt_assurance, required):
                    reject(
                        "required_assurance_not_satisfied",
                        "Produce fresh trusted proof evidence at the criterion's required assurance level.",
                    )
                assurance_ok = bool(
                    required is not None
                    and receipt_verdict is ProofVerdict.PROVED
                    and receipt_freshness is EvidenceFreshness.CURRENT
                    and assurance_satisfies(receipt_assurance, required)
                    and evidence.proof_receipt_id == trusted_receipt.receipt_id
                    and evidence.obligation_id == trusted_receipt.obligation_id
                    and evidence.repository_tree == trusted_receipt.repository_tree_id
                    and declared_assurance is receipt_assurance
                    and declared_verdict is receipt_verdict
                    and declared_freshness is receipt_freshness
                    and receipt_finished_at is not None
                    and evidence.observed_at == receipt_finished_at
                    and (
                        not evidence.repository_id
                        or evidence.repository_id == trusted_receipt.repository_id
                    )
                    and (
                        not repository_tree
                        or trusted_receipt.repository_tree_id == str(repository_tree)
                    )
                    and (not repository_id or trusted_receipt.repository_id == str(repository_id))
                )

    receipt = evidence.validation_receipt
    reconciliation_receipt = evidence.metadata.get("reconciliation_validation_receipt")
    if evidence.metadata.get("external_operational_completion") is True and isinstance(
        reconciliation_receipt, Mapping
    ):
        # The external producer receipt remains immutable and bound to the
        # committed source tree inspected by the external authority.  A local
        # reconciliation rerun is a distinct receipt that binds that verified
        # external result to the supervisor's control-file-excluding tree.
        receipt = reconciliation_receipt
    if isinstance(receipt, Mapping):
        receipt_tree = str(receipt.get("tree_id", receipt.get("tree_identity", "")) or "")
        if receipt_tree and evidence.repository_tree and receipt_tree != evidence.repository_tree:
            reject(
                "validation_tree_mismatch",
                "Use a validation receipt for the same repository tree as the evidence.",
            )

    current = _now(now)
    freshness_claim = _freshness_claim(evidence)
    if freshness_claim is not True:
        if proof_required or proof_supplied:
            assurance_ok = False
        code = "stale_evidence" if freshness_claim is False else "missing_freshness"
        detail = (
            "Evidence is stale; regenerate it and record a fresh status."
            if freshness_claim is False
            else "Refresh the evidence and record an explicit fresh status."
        )
        reject(code, detail)
    observed = evidence.observed_at
    if observed is None:
        if proof_required or proof_supplied:
            assurance_ok = False
        reject("missing_observed_at", "Record observed_at so evidence freshness can be checked.")
    else:
        if observed > current + timedelta(seconds=max(0.0, float(clock_skew_seconds))):
            if proof_required or proof_supplied:
                assurance_ok = False
            reject("future_evidence", "Correct the evidence timestamp; it is in the future.")
        if current - observed > timedelta(seconds=max(0.0, float(freshness_seconds))):
            if proof_required or proof_supplied:
                assurance_ok = False
            reject(
                "stale_evidence", "Regenerate evidence because its freshness window has expired."
            )
    if evidence.fresh_until is not None and current > evidence.fresh_until:
        if proof_required or proof_supplied:
            assurance_ok = False
        reject(
            "stale_evidence", "Regenerate evidence because its declared freshness deadline passed."
        )
    if evidence.producer_kind == "scan":
        safe = evidence.metadata.get("safe_for_completion_reasoning")
        if safe is not True:
            reject(
                "unsafe_scan_receipt",
                "Use an exhaustive scan receipt marked safe for completion reasoning.",
            )
    if evidence.contradictory or evidence.contradiction.strip():
        detail = evidence.contradiction.strip()
        assurance_ok = False if proof_required or proof_supplied else assurance_ok
        reject(
            "contradictory_evidence",
            "Resolve contradictory evidence before verification"
            + (f": {detail}" if detail else "."),
        )
    return EvidenceValidationResult(
        evidence=evidence,
        valid=not reason_codes,
        reason_codes=tuple(reason_codes),
        actionable_reasons=tuple(reasons),
        validation_succeeded=passed,
        assurance_satisfied=assurance_ok,
    )


@dataclass(frozen=True)
class GoalTransition:
    previous_state: GoalState
    state: GoalState
    reason: str
    transitioned_at: datetime
    evidence_cids: tuple[str, ...] = ()
    evidence: tuple[CompletionEvidence, ...] = ()

    @property
    def from_state(self) -> GoalState:
        return self.previous_state

    @property
    def to_state(self) -> GoalState:
        return self.state

    @property
    def next_state(self) -> GoalState:
        return self.state

    def to_dict(self) -> dict[str, Any]:
        return {
            "previous_state": self.previous_state.value,
            "from_state": self.previous_state.value,
            "state": self.state.value,
            "next_state": self.state.value,
            "to_state": self.state.value,
            "reason": self.reason,
            "transitioned_at": self.transitioned_at.isoformat(),
            "evidence_cids": list(self.evidence_cids),
            "evidence": [item.to_dict() for item in self.evidence],
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "GoalTransition":
        return cls(
            previous_state=normalize_goal_state(
                payload.get("previous_state", payload.get("from_state"))
            ),
            state=normalize_goal_state(
                payload.get("state", payload.get("to_state", payload.get("next_state")))
            ),
            reason=str(payload.get("reason", "")),
            transitioned_at=_utc_datetime(
                payload.get("transitioned_at", payload.get("timestamp", payload.get("created_at"))),
                field_name="transitioned_at",
            )
            or datetime.now(timezone.utc),
            evidence_cids=tuple(
                str(item) for item in payload.get("evidence_cids", ()) if str(item)
            ),
            evidence=tuple(
                CompletionEvidence.from_dict(item)
                for item in payload.get("evidence", ())
                if isinstance(item, Mapping)
            ),
        )


@dataclass
class GoalLifecycle:
    """Mutable state holder which enforces and audits lifecycle transitions."""

    goal_id: str = ""
    state: GoalState | str = GoalState.ACTIVE
    history: list[GoalTransition] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.state = normalize_goal_state(self.state)
        self.goal_id = str(self.goal_id or "").strip()

    def can_transition(self, target: GoalState | str) -> bool:
        return normalize_goal_state(target) in legal_goal_transitions(self.state)

    def transition(
        self,
        target: GoalState | str,
        *,
        reason: str,
        evidence: Iterable[CompletionEvidence | str] = (),
        now: datetime | str | None = None,
    ) -> GoalState:
        target_state = normalize_goal_state(target)
        if not self.can_transition(target_state):
            legal = ", ".join(
                item.value
                for item in sorted(legal_goal_transitions(self.state), key=lambda item: item.value)
            )
            raise IllegalGoalTransitionError(
                f"illegal goal transition for {self.goal_id or '<unnamed goal>'}: "
                f"{self.state.value} -> {target_state.value}; legal targets: {legal or 'none'}"
            )
        explanation = str(reason or "").strip()
        if not explanation:
            raise ValueError("goal transitions require a non-empty reason")
        cids: list[str] = []
        records: list[CompletionEvidence] = []
        for item in evidence:
            cid = (
                item.provenance_cid
                if isinstance(item, CompletionEvidence)
                else str(item or "").strip()
            )
            if isinstance(item, CompletionEvidence):
                records.append(item)
            if cid and cid not in cids:
                cids.append(cid)
        transition = GoalTransition(
            previous_state=self.state,
            state=target_state,
            reason=explanation,
            transitioned_at=_now(now),
            evidence_cids=tuple(cids),
            evidence=tuple(records),
        )
        self.state = target_state
        self.history.append(transition)
        return self.state

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": GOAL_COMPLETION_SCHEMA_VERSION,
            "goal_id": self.goal_id,
            "state": self.state.value,
            "history": [item.to_dict() for item in self.history],
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "GoalLifecycle":
        history = (
            payload.get("history", payload.get("transitions", payload.get("events", ()))) or ()
        )
        return cls(
            goal_id=str(payload.get("goal_id", "")),
            state=normalize_goal_state(
                payload.get("state", payload.get("status", payload.get("lifecycle_state")))
            ),
            history=[
                GoalTransition.from_dict(item) for item in history if isinstance(item, Mapping)
            ],
        )


def _contradiction(value: ContradictionEvidence | Mapping[str, Any]) -> ContradictionEvidence:
    return (
        value
        if isinstance(value, ContradictionEvidence)
        else ContradictionEvidence.from_dict(value)
    )


def _records_for_goal(records: Any, goal_id: str) -> tuple[dict[str, Any], ...]:
    if isinstance(records, Mapping):
        # A goal-indexed mapping is the common daemon representation; a
        # receipt record itself is recognized by its identity/state fields.
        if goal_id in records and not any(
            key in records for key in ("receipt_id", "goal_id", "state", "contradiction_ids")
        ):
            records = records.get(goal_id, ())
        else:
            records = (records,)
    return tuple(
        payload
        for payload in _mapping_tuple(records)
        if not str(payload.get("goal_id", "")).strip()
        or str(payload.get("goal_id", "")).strip() == goal_id
    )


def _handled_contradiction_ids(receipts: Sequence[Mapping[str, Any]]) -> set[str]:
    handled: set[str] = set()
    for receipt in receipts:
        values = receipt.get("contradiction_ids", receipt.get("contradictions", ()))
        if isinstance(values, str):
            values = (values,)
        if isinstance(values, Mapping):
            values = (values,)
        for value in values or ():
            if isinstance(value, Mapping):
                identity = value.get("contradiction_id", value.get("fingerprint", ""))
            else:
                identity = value
            if str(identity or "").strip():
                handled.add(str(identity).strip())
    return handled


@dataclass(frozen=True)
class ReopenDecision:
    """Idempotent, receipt-bearing decision for one goal recalculation."""

    goal_id: str
    previous_state: GoalState
    state: GoalState
    reopened: bool
    idempotent: bool
    contradictions: tuple[ContradictionEvidence, ...] = ()
    impacted_criteria: tuple[str, ...] = ()
    invalidated_evidence: tuple[str, ...] = ()
    source_receipts: tuple[Mapping[str, Any], ...] = ()
    newly_scheduled_work: tuple[Mapping[str, Any], ...] = ()
    historical_completion_receipts: tuple[Mapping[str, Any], ...] = ()
    reopening_receipt: Mapping[str, Any] = field(default_factory=dict)
    reason_codes: tuple[str, ...] = ()
    schema_version: int = GOAL_COMPLETION_SCHEMA_VERSION

    @property
    def changed(self) -> bool:
        return self.state is not self.previous_state

    @property
    def contradiction_ids(self) -> tuple[str, ...]:
        return tuple(item.contradiction_id for item in self.contradictions)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "ipfs_accelerate_py.agent_supervisor.goal_reopen_decision.v1",
            "schema_version": self.schema_version,
            "goal_id": self.goal_id,
            "previous_state": self.previous_state.value,
            "state": self.state.value,
            "reopened": self.reopened,
            "changed": self.changed,
            "idempotent": self.idempotent,
            "contradiction_ids": list(self.contradiction_ids),
            "contradictions": [item.to_dict() for item in self.contradictions],
            "impacted_criteria": list(self.impacted_criteria),
            "invalidated_evidence": list(self.invalidated_evidence),
            "source_receipts": _json_value(self.source_receipts),
            "newly_scheduled_work": _json_value(self.newly_scheduled_work),
            # Historical receipts are copied, never replaced by the reopen
            # receipt.  Consumers may keep both ledgers independently.
            "historical_completion_receipts": _json_value(self.historical_completion_receipts),
            "reopening_receipt": _json_value(self.reopening_receipt),
            "reason_codes": list(self.reason_codes),
        }


# Descriptive spelling for consumers that prefer the domain prefix.
GoalReopenDecision = ReopenDecision


def reopen_goal_for_contradictions(
    *,
    goal_id: str,
    current_state: GoalState | str,
    contradictions: Sequence[ContradictionEvidence | Mapping[str, Any]],
    historical_completion_receipts: Any = (),
    existing_reopen_receipts: Any = (),
    now: datetime | str | None = None,
) -> ReopenDecision:
    """Reopen a completed goal once for each distinct relevant contradiction.

    Contradictions assigned to another goal are intentionally ignored.  This
    is the key churn guard for unrelated dynamic findings.
    """

    canonical_goal_id = str(goal_id or "").strip()
    if not canonical_goal_id:
        raise ValueError("goal_id is required")
    previous = normalize_goal_state(current_state)
    relevant_by_id: dict[str, ContradictionEvidence] = {}
    for value in contradictions:
        item = _contradiction(value)
        if item.goal_id == canonical_goal_id:
            relevant_by_id[item.contradiction_id] = item
    relevant = tuple(relevant_by_id[key] for key in sorted(relevant_by_id))
    historical = _records_for_goal(historical_completion_receipts, canonical_goal_id)
    existing = _records_for_goal(existing_reopen_receipts, canonical_goal_id)
    handled = _handled_contradiction_ids(existing)
    novel = tuple(item for item in relevant if item.contradiction_id not in handled)
    completed = previous in {GoalState.PROVISIONALLY_COMPLETE, GoalState.VERIFIED_COMPLETE}
    already_reopened = previous is GoalState.REOPENED
    should_record = bool(novel and (completed or already_reopened))
    replayed_reopening = bool(
        relevant
        and not novel
        and any(
            str(receipt.get("state", receipt.get("next_state", ""))).strip()
            == GoalState.REOPENED.value
            for receipt in existing
        )
    )
    # Persisted goal state and receipt writes are not necessarily atomic.  A
    # durable reopening receipt wins over an older verified state on replay,
    # but does not create another receipt or schedule duplicate work.
    next_state = GoalState.REOPENED if should_record or replayed_reopening else previous
    reopened = bool(should_record and completed)
    impacted = _string_tuple(
        item for contradiction in novel for item in contradiction.impacted_criteria
    )
    invalidated = _string_tuple(
        item for contradiction in novel for item in contradiction.invalidated_evidence
    )
    sources = _mapping_tuple(item.source_receipt for item in novel if item.source_receipt)
    scheduled = _mapping_tuple(
        item for contradiction in novel for item in contradiction.scheduled_work
    )
    if novel and not scheduled:
        scheduled = _mapping_tuple(
            {
                "kind": "goal_work_request",
                "request_id": _stable_fingerprint(
                    "work",
                    {"goal_id": canonical_goal_id, "contradiction_id": item.contradiction_id},
                ),
                "goal_id": canonical_goal_id,
                "contradiction_id": item.contradiction_id,
                "reason": item.kind,
            }
            for item in novel
        )
    current = _now(now)
    reopening_receipt: dict[str, Any] = {}
    if should_record:
        identity = {
            "goal_id": canonical_goal_id,
            "previous_state": previous.value,
            "state": GoalState.REOPENED.value,
            "contradiction_ids": [item.contradiction_id for item in novel],
        }
        reopening_receipt = {
            "schema": "ipfs_accelerate_py.agent_supervisor.goal_reopening_receipt.v1",
            "schema_version": GOAL_COMPLETION_SCHEMA_VERSION,
            "receipt_id": _stable_fingerprint("reopen", identity),
            "goal_id": canonical_goal_id,
            "previous_state": previous.value,
            "state": GoalState.REOPENED.value,
            "reopened_at": current.isoformat(),
            "contradiction_ids": [item.contradiction_id for item in novel],
            "contradictions": [item.to_dict() for item in novel],
            "impacted_criteria": list(impacted),
            "invalidated_evidence": list(invalidated),
            "source_receipts": _json_value(sources),
            "newly_scheduled_work": _json_value(scheduled),
            "historical_completion_receipt_ids": [
                str(item.get("receipt_id", item.get("receipt_cid", item.get("provenance_cid", ""))))
                for item in historical
                if str(
                    item.get("receipt_id", item.get("receipt_cid", item.get("provenance_cid", "")))
                )
            ],
        }
    if not relevant:
        reasons = ()
    elif not novel:
        reasons = ("contradiction_already_recorded",)
    elif should_record:
        reasons = (
            ("completion_evidence_contradicted", "goal_reopened")
            if reopened
            else ("additional_contradiction_recorded",)
        )
    else:
        reasons = ("goal_not_completed",)
    return ReopenDecision(
        goal_id=canonical_goal_id,
        previous_state=previous,
        state=next_state,
        reopened=reopened,
        idempotent=bool(relevant and not novel),
        contradictions=novel,
        impacted_criteria=impacted,
        invalidated_evidence=invalidated,
        source_receipts=sources,
        newly_scheduled_work=scheduled,
        historical_completion_receipts=historical,
        reopening_receipt=reopening_receipt,
        reason_codes=reasons,
    )


def _goal_payloads(goals: Any) -> dict[str, dict[str, Any]]:
    if isinstance(goals, Mapping):
        if "goal_id" in goals or "id" in goals:
            values = (goals,)
        else:
            values = []
            for goal_id, value in goals.items():
                payload = dict(value) if isinstance(value, Mapping) else {"state": value}
                payload.setdefault("goal_id", goal_id)
                values.append(payload)
    else:
        values = goals or ()
    result: dict[str, dict[str, Any]] = {}
    for value in values:
        if isinstance(value, GoalLifecycle):
            payload = value.to_dict()
        elif isinstance(value, Mapping):
            payload = dict(value)
        else:
            to_dict = getattr(value, "to_dict", None)
            payload = dict(to_dict()) if callable(to_dict) else dict(vars(value))
        # ``ObjectiveGoal`` stores markdown fields under ``fields`` and does
        # not expose a custom serializer.  Flatten that representation at the
        # lifecycle boundary so direct callers receive the same state/link
        # behavior as the objective-task janitor's mapping projection.
        nested_fields = payload.get("fields")
        if isinstance(nested_fields, Mapping):
            payload = {
                **dict(nested_fields),
                **{key: item for key, item in payload.items() if key != "fields"},
            }
        goal_id = str(payload.get("goal_id", payload.get("id", ""))).strip()
        if goal_id:
            result[goal_id] = payload
    return result


def _goal_links(payload: Mapping[str, Any], names: Sequence[str]) -> tuple[str, ...]:
    values: list[Any] = []
    for name in names:
        value = payload.get(name)
        if isinstance(value, str):
            values.extend(part.strip() for part in value.replace(";", ",").split(","))
        elif isinstance(value, Iterable) and not isinstance(value, (str, bytes, Mapping)):
            values.extend(value)
    return _string_tuple(values)


def reconcile_goal_reopenings(
    goals: Any,
    contradictions: Sequence[ContradictionEvidence | Mapping[str, Any]],
    *,
    historical_completion_receipts: Any = (),
    existing_reopen_receipts: Any = (),
    now: datetime | str | None = None,
) -> dict[str, ReopenDecision]:
    """Recalculate directly affected, ancestor, and dependent goal states.

    Propagation evidence is itself content-addressed and references the source
    contradiction.  A replay consequently yields the same IDs and is absorbed
    by the same idempotency ledger as a direct contradiction.
    """

    payloads = _goal_payloads(goals)
    direct = sorted(
        (_contradiction(item) for item in contradictions), key=lambda item: item.contradiction_id
    )
    by_goal: dict[str, list[ContradictionEvidence]] = {goal_id: [] for goal_id in payloads}
    for item in direct:
        if item.goal_id in by_goal:
            by_goal[item.goal_id].append(item)

    propagation: dict[str, list[tuple[str, str]]] = {goal_id: [] for goal_id in payloads}
    for goal_id, payload in payloads.items():
        for parent_id in _goal_links(
            payload, ("parent_goal_id", "parent_id", "parents", "parent_goal_ids")
        ):
            if parent_id in propagation:
                propagation[goal_id].append((parent_id, "child_reopened"))
        for dependency_id in _goal_links(
            payload, ("depends_on", "dependencies", "dependency_goal_ids")
        ):
            if dependency_id in propagation:
                propagation[dependency_id].append((goal_id, "dependency_reopened"))
    for goal_id in propagation:
        propagation[goal_id].sort()

    # Breadth-first closure is deterministic and safe in the presence of goal
    # graph cycles because (target, root contradiction) pairs are visited once.
    # Only an effectively reopened source propagates.  An active or blocked
    # goal receiving a finding has no completion claim to invalidate and must
    # not churn otherwise completed relatives.
    reopenable = {
        goal_id
        for goal_id, payload in payloads.items()
        if normalize_goal_state(payload.get("state", payload.get("status", GoalState.ACTIVE.value)))
        in {GoalState.PROVISIONALLY_COMPLETE, GoalState.VERIFIED_COMPLETE, GoalState.REOPENED}
    }
    queue: list[tuple[str, ContradictionEvidence]] = [
        (item.goal_id, item) for item in direct if item.goal_id in reopenable
    ]
    visited = {(goal_id, item.contradiction_id) for goal_id, item in queue}
    cursor = 0
    while cursor < len(queue):
        source_goal, root = queue[cursor]
        cursor += 1
        for target_goal, kind in propagation.get(source_goal, ()):
            key = (target_goal, root.contradiction_id)
            if key in visited:
                continue
            visited.add(key)
            criterion_values = payloads[target_goal].get("acceptance_criteria", ())
            synthetic = ContradictionEvidence(
                goal_id=target_goal,
                kind=kind,
                summary=(
                    f"Child goal {source_goal} was reopened by contradiction {root.contradiction_id}."
                    if kind == "child_reopened"
                    else f"Dependency goal {source_goal} was reopened by contradiction {root.contradiction_id}."
                ),
                impacted_criteria=_string_tuple(criterion_values),
                invalidated_evidence=(f"goal:{source_goal}",),
                source_receipt={
                    "source_goal_id": source_goal,
                    "root_contradiction_id": root.contradiction_id,
                    "kind": kind,
                },
                source_receipt_id=root.contradiction_id,
                scheduled_work=(
                    {"goal_id": target_goal, "reason": kind, "source_goal_id": source_goal},
                ),
                detected_at=root.detected_at,
            )
            by_goal[target_goal].append(synthetic)
            if target_goal in reopenable:
                queue.append((target_goal, root))

    decisions: dict[str, ReopenDecision] = {}
    for goal_id in sorted(goal_id for goal_id, values in by_goal.items() if values):
        payload = payloads[goal_id]
        decisions[goal_id] = reopen_goal_for_contradictions(
            goal_id=goal_id,
            current_state=payload.get("state", payload.get("status", GoalState.ACTIVE.value)),
            contradictions=by_goal[goal_id],
            historical_completion_receipts=_records_for_goal(
                historical_completion_receipts, goal_id
            ),
            existing_reopen_receipts=_records_for_goal(existing_reopen_receipts, goal_id),
            now=now,
        )
    return decisions


def discover_goal_contradictions(
    coverage: Any,
    *,
    previous_coverage: Any = None,
    completed_goal_ids: Sequence[str] = (),
    known_finding_ids: Sequence[str] = (),
    scheduled_work: Any = (),
    detected_at: datetime | str | None = None,
) -> list[ContradictionEvidence]:
    """Discover coverage contradictions without creating an import cycle."""

    from .goal_coverage import detect_goal_coverage_contradictions

    return detect_goal_coverage_contradictions(
        coverage,
        previous_coverage=previous_coverage,
        completed_goal_ids=completed_goal_ids,
        known_finding_ids=known_finding_ids,
        scheduled_work=scheduled_work,
        detected_at=detected_at,
    )


@dataclass(frozen=True)
class GoalCompletionDecision:
    """Fail-closed result of evaluating all completion evidence for a goal."""

    previous_state: GoalState
    state: GoalState
    tasks_complete: bool
    verified: bool
    acceptance_criteria: tuple[str, ...]
    missing_criteria: tuple[str, ...]
    invalid_criteria: tuple[str, ...]
    evidence_results: tuple[EvidenceValidationResult, ...]
    reason_codes: tuple[str, ...]
    actionable_reasons: tuple[str, ...]
    gate: "CompletionGateResult | None" = None
    schema_version: int = GOAL_COMPLETION_SCHEMA_VERSION

    @property
    def next_state(self) -> GoalState:
        return self.state

    @property
    def provisional(self) -> bool:
        return self.state is GoalState.PROVISIONALLY_COMPLETE

    @property
    def can_verify(self) -> bool:
        return self.verified

    @property
    def evidence(self) -> list[CompletionEvidence]:
        return [result.evidence for result in self.evidence_results]

    @property
    def proof_requirements(self) -> tuple[Mapping[str, Any], ...]:
        """Local and descendant proof demands, retained without summarizing loss."""

        requirements = [
            payload
            for result in self.evidence_results
            if (payload := _proof_requirement_payload(result)) is not None
        ]
        if self.gate is not None:
            child_check = next(
                (check for check in self.gate.checks if check.name == "child_goals"),
                None,
            )
            if child_check is not None:
                values = child_check.evidence.get("proof_requirements", ())
                if isinstance(values, (list, tuple)):
                    requirements.extend(dict(item) for item in values if isinstance(item, Mapping))
        deduplicated: dict[str, Mapping[str, Any]] = {}
        for item in requirements:
            identity = _canonical_json(
                {
                    "goal_id": item.get("goal_id", ""),
                    "acceptance_criterion": item.get("acceptance_criterion", ""),
                    "obligation_id": item.get("obligation_id", ""),
                    "proof_receipt_id": item.get("proof_receipt_id", ""),
                    "required_assurance": item.get("required_assurance", ""),
                }
            )
            deduplicated[identity] = item
        return tuple(deduplicated[key] for key in sorted(deduplicated))

    @property
    def proof_requirements_satisfied(self) -> bool:
        return all(item.get("assurance_satisfied") is True for item in self.proof_requirements)

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "previous_state": self.previous_state.value,
            "state": self.state.value,
            "next_state": self.state.value,
            "tasks_complete": self.tasks_complete,
            "verified": self.verified,
            "provisional": self.provisional,
            "acceptance_criteria": list(self.acceptance_criteria),
            "missing_criteria": list(self.missing_criteria),
            "invalid_criteria": list(self.invalid_criteria),
            "reason_codes": list(self.reason_codes),
            "actionable_reasons": list(self.actionable_reasons),
            "evidence": [item.to_dict() for item in self.evidence],
            "evidence_results": [result.to_dict() for result in self.evidence_results],
            "proof_requirements": _json_value(self.proof_requirements),
            "proof_requirements_satisfied": self.proof_requirements_satisfied,
            "completion_gate": self.gate.to_dict() if self.gate is not None else None,
        }
        diagnostics = completion_diagnostics(self)
        payload["diagnostics"] = diagnostics
        # Frequently queried dimensions are also top-level during the rollout
        # so older status consumers need not understand the nested projection.
        for key in (
            "confidence",
            "uncovered_criteria",
            "stale_evidence",
            "analyzer_health",
            "exhaustion_quorum",
            "reopen_reasons",
        ):
            payload[key] = diagnostics[key]
        return payload


def completion_diagnostics(decision: GoalCompletionDecision) -> dict[str, Any]:
    """Project a compact, truthful operator view of a completion decision.

    Confidence is an explainable proof-completeness ratio, not a probability.
    A verified goal is the only state reported at ``1.0``.  Missing inputs
    remain explicit rather than being converted to optimistic defaults.
    """

    criteria = tuple(decision.acceptance_criteria)
    covered_keys = {
        _criterion_key(result.evidence.acceptance_criterion)
        for result in decision.evidence_results
        if result.valid
    }
    uncovered = list(dict.fromkeys((*decision.missing_criteria, *decision.invalid_criteria)))
    valid_criteria = sum(1 for criterion in criteria if _criterion_key(criterion) in covered_keys)
    criterion_ratio = valid_criteria / len(criteria) if criteria else 0.0
    gate_checks = tuple(decision.gate.checks) if decision.gate is not None else ()
    gate_ratio = (
        sum(1 for check in gate_checks if check.passed) / len(gate_checks) if gate_checks else 0.0
    )
    confidence = 1.0 if decision.verified else round((criterion_ratio + gate_ratio) / 2.0, 6)

    stale_evidence: list[dict[str, Any]] = []
    for result in decision.evidence_results:
        stale_codes = [code for code in result.reason_codes if "stale" in code or "future" in code]
        if stale_codes:
            stale_evidence.append(
                {
                    "provenance_cid": result.evidence.provenance_cid,
                    "acceptance_criterion": result.evidence.acceptance_criterion,
                    "reason_codes": stale_codes,
                }
            )

    checks = {check.name: check for check in gate_checks}
    coverage_check = checks.get("mandatory_coverage")
    if coverage_check and not coverage_check.passed:
        coverage_evidence = dict(coverage_check.evidence)
        for criterion in coverage_evidence.get("missing_criteria", ()):
            if criterion not in uncovered:
                uncovered.append(str(criterion))
        if coverage_evidence.get("freshness_error") in {"stale", "future"}:
            stale_evidence.append(
                {
                    "kind": "coverage",
                    "reason": str(coverage_evidence["freshness_error"]),
                }
            )

    health_check = checks.get("analyzer_health")
    health_payload = dict(health_check.evidence) if health_check else {}
    health_status = str(
        health_payload.get("status")
        or health_payload.get("health")
        or ("healthy" if health_check and health_check.passed else "missing")
    )
    quorum_check = checks.get("exhaustion_quorum")
    quorum_payload = dict(quorum_check.evidence) if quorum_check else {}
    raw_quorum = quorum_payload.get("quorum")
    raw_quorum = dict(raw_quorum) if isinstance(raw_quorum, Mapping) else {}
    for member_id in quorum_payload.get("stale_members", ()):
        stale_evidence.append({"kind": "exhaustion_quorum_member", "member_id": str(member_id)})
    reopen_reasons = list(decision.reason_codes) if decision.state is GoalState.REOPENED else []

    return {
        "schema": "ipfs_accelerate_py.agent_supervisor.goal_completion_diagnostics@1",
        "schema_version": GOAL_COMPLETION_SCHEMA_VERSION,
        "lifecycle_state": decision.state.value,
        "confidence": confidence,
        "confidence_basis": {
            "meaning": "proof_completeness_ratio",
            "valid_criteria": valid_criteria,
            "criterion_count": len(criteria),
            "passed_gate_checks": sum(1 for check in gate_checks if check.passed),
            "gate_check_count": len(gate_checks),
        },
        "uncovered_criteria": uncovered,
        "stale_evidence": stale_evidence,
        "analyzer_health": {
            "status": health_status,
            "passed": bool(health_check and health_check.passed),
            "reason_code": health_check.reason_code if health_check else "analyzer_health_missing",
            "evidence": health_payload,
        },
        "exhaustion_quorum": {
            "satisfied": bool(quorum_check and quorum_check.passed),
            "reason_code": quorum_check.reason_code
            if quorum_check
            else "exhaustion_quorum_missing",
            "required_members": raw_quorum.get("required_members", raw_quorum.get("required")),
            "member_count": raw_quorum.get("member_count", raw_quorum.get("count")),
            "stale_members": list(quorum_payload.get("stale_members", ())),
            "evidence": raw_quorum,
        },
        "reopen_reasons": reopen_reasons,
        "reason_codes": list(decision.reason_codes),
        "actionable_reasons": list(decision.actionable_reasons),
    }


def _mapping_value(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        payload = to_dict()
        if isinstance(payload, Mapping):
            return {str(key): _json_value(item) for key, item in payload.items()}
    return {"value": _json_value(value)}


def _gate_datetime(value: Any) -> datetime | None:
    """Best-effort timestamp parsing for untrusted persisted gate proof."""

    try:
        return _utc_datetime(value, field_name="completion gate timestamp")
    except (TypeError, ValueError):
        return None


def _gate_count(value: Any) -> int | None:
    """Return a non-negative integer without accepting booleans or fractions."""

    if isinstance(value, bool):
        return None
    try:
        count = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    try:
        if float(value) != count:
            return None
    except (TypeError, ValueError, OverflowError):
        return None
    return count if count >= 0 else None


@dataclass(frozen=True)
class CompletionGateCheck:
    """One independently inspectable fail-closed completion requirement."""

    name: str
    passed: bool
    reason_code: str = ""
    reason: str = ""
    evidence: Mapping[str, Any] = field(default_factory=dict)
    pass_code: str = ""
    pass_reason: str = ""

    @property
    def outcome_code(self) -> str:
        return self.pass_code if self.passed else self.reason_code

    @property
    def outcome_reason(self) -> str:
        return self.pass_reason if self.passed else self.reason

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "passed": self.passed,
            "reason_code": self.reason_code,
            "reason": self.reason,
            "outcome_code": self.outcome_code,
            "outcome_reason": self.outcome_reason,
            "evidence": _json_value(self.evidence),
        }


@dataclass(frozen=True)
class CompletionGateResult:
    """Machine-readable verdict and the exact evidence evaluated."""

    passed: bool
    checks: tuple[CompletionGateCheck, ...]
    evaluated_evidence: Mapping[str, Any]
    schema_version: int = GOAL_COMPLETION_SCHEMA_VERSION

    @property
    def reason_codes(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(check.reason_code for check in self.checks if check.reason_code))

    @property
    def actionable_reasons(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(check.reason for check in self.checks if check.reason))

    @property
    def pass_reason_codes(self) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(
                check.pass_code for check in self.checks if check.passed and check.pass_code
            )
        )

    @property
    def fail_reason_codes(self) -> tuple[str, ...]:
        return self.reason_codes

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "ipfs_accelerate_py.agent_supervisor.completion_gate.v1",
            "schema_version": self.schema_version,
            "passed": self.passed,
            "reason_codes": list(self.reason_codes),
            "pass_reason_codes": list(self.pass_reason_codes),
            "fail_reason_codes": list(self.fail_reason_codes),
            "actionable_reasons": list(self.actionable_reasons),
            "checks": [check.to_dict() for check in self.checks],
            "evaluated_evidence": _json_value(self.evaluated_evidence),
        }


def evaluate_completion_gate(
    *,
    acceptance_criteria: Sequence[str] | str | None,
    evidence_results: Sequence[EvidenceValidationResult | Mapping[str, Any]] = (),
    coverage: Any = None,
    analyzer_health: Any = None,
    exhaustion_quorum: Any = None,
    child_goals: Sequence[Any] = (),
    required_child_goal_ids: Sequence[str] = (),
    analysis_result: Any = None,
    repository_tree: str = "",
    repository_id: str = "",
    objective_revision: str = "",
    completion_binding: Any = None,
    require_artifact_binding: bool = False,
    now: datetime | str | None = None,
    freshness_seconds: float = DEFAULT_EVIDENCE_FRESHNESS_SECONDS,
    clock_skew_seconds: float = DEFAULT_CLOCK_SKEW_SECONDS,
) -> CompletionGateResult:
    """Evaluate coverage, validation, health, quorum, and descendants.

    Inputs accept typed domain records or their persisted mapping forms.  Any
    absent, unsupported, partial, stale, skipped, failed, timed-out, or
    duplicate-only proof fails closed.
    """

    criteria = _acceptance_criteria(acceptance_criteria)
    current = _now(now)
    max_age = timedelta(seconds=max(0.0, float(freshness_seconds)))
    clock_skew = timedelta(seconds=max(0.0, float(clock_skew_seconds)))
    coverage_payload = _mapping_value(coverage)
    health_payload = _mapping_value(analyzer_health)
    quorum_payload = _mapping_value(exhaustion_quorum)
    analysis_payload = _mapping_value(analysis_result)
    binding_payload = _mapping_value(completion_binding)
    bound_analyzer_version = str(binding_payload.get("analyzer_version") or "")
    bound_configuration_revision = str(
        binding_payload.get("configuration_revision")
        or binding_payload.get("configuration_id")
        or ""
    )
    child_payloads = [_mapping_value(item) for item in child_goals]
    raw_result_payloads = [_mapping_value(item) for item in evidence_results]
    normalized_results: list[EvidenceValidationResult] = []
    for item in evidence_results:
        if isinstance(item, EvidenceValidationResult):
            normalized_results.append(item)
            continue
        source = item.get("evidence", item) if isinstance(item, Mapping) else {}
        try:
            record = CompletionEvidence.from_dict(source if isinstance(source, Mapping) else {})
            normalized_results.append(
                validate_completion_evidence(
                    record,
                    repository_tree=repository_tree,
                    repository_id=repository_id,
                    objective_revision=objective_revision,
                    analyzer_version=bound_analyzer_version,
                    configuration_revision=bound_configuration_revision,
                    require_artifact_binding=require_artifact_binding,
                    now=current,
                    freshness_seconds=freshness_seconds,
                    clock_skew_seconds=clock_skew_seconds,
                )
            )
        except (TypeError, ValueError) as exc:
            placeholder = CompletionEvidence(
                acceptance_criterion="",
                metadata={"malformed_evidence": _json_value(source), "error": str(exc)},
            )
            normalized_results.append(
                EvidenceValidationResult(
                    placeholder,
                    False,
                    ("malformed_evidence",),
                    ("Repair or regenerate the malformed persisted completion evidence.",),
                )
            )
    evidence_results = tuple(normalized_results)
    result_payloads = [item.to_dict() for item in evidence_results]
    checks: list[CompletionGateCheck] = []

    def add_check(
        name: str,
        passed: bool,
        fail_code: str,
        fail_reason: str,
        check_evidence: Mapping[str, Any],
        pass_code: str,
        pass_reason: str,
    ) -> None:
        checks.append(
            CompletionGateCheck(
                name=name,
                passed=passed,
                reason_code="" if passed else fail_code,
                reason="" if passed else fail_reason,
                evidence=check_evidence,
                pass_code=pass_code,
                pass_reason=pass_reason,
            )
        )

    if require_artifact_binding:
        binding_errors: list[str] = []
        required_binding_fields = {
            "repository_id": repository_id,
            "tree_id": repository_tree,
            "objective_revision": objective_revision,
            "analyzer_version": bound_analyzer_version,
            "configuration_revision": bound_configuration_revision,
        }
        for field_name, expected in required_binding_fields.items():
            key = "configuration_revision" if field_name == "configuration_revision" else field_name
            actual = binding_payload.get(key)
            if field_name == "configuration_revision" and not actual:
                actual = binding_payload.get("configuration_id")
            if not str(actual or "").strip():
                binding_errors.append(f"missing_{field_name}")
            elif expected and str(actual) != str(expected):
                binding_errors.append(f"{field_name}_mismatch")

        bound_surfaces = {
            "coverage": coverage_payload,
            "analyzer_health": health_payload,
            "exhaustion_quorum": (
                quorum_payload.get("binding")
                if isinstance(quorum_payload.get("binding"), Mapping)
                else {}
            ),
        }
        for surface_name, surface in bound_surfaces.items():
            surface_binding = (
                surface.get("binding")
                if isinstance(surface, Mapping) and isinstance(surface.get("binding"), Mapping)
                else surface
            )
            if not isinstance(surface_binding, Mapping):
                binding_errors.append(f"{surface_name}_binding_missing")
                continue
            for field_name in (
                "repository_id",
                "tree_id",
                "objective_revision",
                "analyzer_version",
                "configuration_revision",
            ):
                expected = required_binding_fields[field_name]
                actual = surface_binding.get(field_name)
                if field_name == "configuration_revision" and not actual:
                    actual = surface_binding.get("configuration_id")
                if not str(actual or "").strip():
                    binding_errors.append(f"{surface_name}_missing_{field_name}")
                elif expected and str(actual) != str(expected):
                    binding_errors.append(f"{surface_name}_{field_name}_mismatch")
        add_check(
            "artifact_binding",
            not binding_errors,
            "completion_artifact_binding_invalid",
            (
                "Regenerate gate and evidence artifacts against the current semantic "
                "objective, analyzer, configuration, repository, and tree."
            ),
            {
                "binding": binding_payload,
                "expected_objective_revision": objective_revision,
                "errors": binding_errors,
            },
            "completion_artifact_binding_verified",
            "Completion artifacts are bound to the current objective and analyzer policy.",
        )

    coverage_rows = coverage_payload.get("criteria")
    if not isinstance(coverage_rows, list):
        coverage_rows = []
    by_criterion: dict[str, list[Mapping[str, Any]]] = {}
    for row in coverage_rows:
        if not isinstance(row, Mapping):
            continue
        # AcceptanceCoverage.to_dict() uses ``criterion``.  The aliases make
        # the gate tolerant of earlier graph projections without weakening
        # the required exact normalized-text match.
        criterion_text = row.get(
            "criterion",
            row.get("acceptance_criterion", row.get("acceptance", "")),
        )
        key = _criterion_key(criterion_text)
        if key:
            by_criterion.setdefault(key, []).append(row)
    channel_binding_applicable = bool(
        require_artifact_binding
        or any(
            str(
                row.get("required_producer_channel") or row.get("channel_proof_revision") or ""
            ).strip()
            for rows in by_criterion.values()
            for row in rows
        )
    )
    channel_binding_errors: list[dict[str, Any]] = []
    criterion_channel_matches: dict[str, bool] = {}
    for criterion in criteria:
        criterion_key = _criterion_key(criterion)
        rows = by_criterion.get(criterion_key, ())
        valid_candidates = [
            item
            for item in evidence_results
            if item.valid and _criterion_key(item.evidence.acceptance_criterion) == criterion_key
        ]
        criterion_matches = bool(valid_candidates)
        for row_index, row in enumerate(rows):
            required_channel = str(row.get("required_producer_channel") or "").strip()
            required_channel_revision = str(row.get("channel_proof_revision") or "").strip()
            row_evidence = {
                "criterion": criterion,
                "coverage_row_index": row_index,
                "required_producer_channel": required_channel,
                "required_channel_proof_revision": required_channel_revision,
                "observed_producer_channels": sorted(
                    {
                        item.evidence.producer_channel
                        for item in valid_candidates
                        if item.evidence.producer_channel
                    }
                ),
                "observed_channel_proof_revisions": sorted(
                    {
                        item.evidence.channel_proof_revision
                        for item in valid_candidates
                        if item.evidence.channel_proof_revision
                    }
                ),
            }
            if not required_channel:
                if required_channel_revision:
                    criterion_matches = False
                    channel_binding_errors.append(
                        {
                            **row_evidence,
                            "code": "required_producer_channel_missing",
                        }
                    )
                elif require_artifact_binding:
                    criterion_matches = False
                    channel_binding_errors.append(
                        {
                            **row_evidence,
                            "code": "required_producer_channel_missing",
                        }
                    )
                continue
            if require_artifact_binding and not required_channel_revision:
                criterion_matches = False
                channel_binding_errors.append(
                    {
                        **row_evidence,
                        "code": "required_channel_proof_revision_missing",
                    }
                )
            channel_candidates = [
                item
                for item in valid_candidates
                if item.evidence.producer_channel == required_channel
            ]
            if not channel_candidates:
                criterion_matches = False
                channel_binding_errors.append(
                    {
                        **row_evidence,
                        "code": (
                            "missing_producer_channel"
                            if not row_evidence["observed_producer_channels"]
                            else "producer_channel_mismatch"
                        ),
                    }
                )
                continue
            if required_channel_revision and not any(
                item.evidence.channel_proof_revision == required_channel_revision
                for item in channel_candidates
            ):
                criterion_matches = False
                channel_binding_errors.append(
                    {
                        **row_evidence,
                        "code": "channel_proof_revision_mismatch",
                    }
                )
        criterion_channel_matches[criterion_key] = criterion_matches
    missing_coverage = [
        criterion for criterion in criteria if _criterion_key(criterion) not in by_criterion
    ]
    unverified_coverage = [
        criterion
        for criterion in criteria
        if _criterion_key(criterion) in by_criterion
        and not all(
            str(row.get("status") or "").strip().lower() == "verified"
            and ("verified" not in row or _bool_value(row.get("verified")) is True)
            for row in by_criterion[_criterion_key(criterion)]
        )
    ]
    coverage_tree = str(
        coverage_payload.get("repository_tree") or coverage_payload.get("tree_id") or ""
    )
    coverage_tree_mismatch = bool(repository_tree and coverage_tree != repository_tree)
    coverage_declared_false = (
        "verified" in coverage_payload and _bool_value(coverage_payload.get("verified")) is not True
    )
    coverage_declared_reasons = coverage_payload.get("reason_codes")
    coverage_declared_reasons = (
        list(coverage_declared_reasons)
        if isinstance(coverage_declared_reasons, (list, tuple))
        else []
    )
    coverage_evaluated_at_value = coverage_payload.get("evaluated_at")
    coverage_evaluated_at = _gate_datetime(coverage_evaluated_at_value)
    has_coverage_time = (
        coverage_evaluated_at_value is not None and coverage_evaluated_at_value != ""
    )
    coverage_fresh = has_coverage_time
    coverage_freshness_error = ""
    if not has_coverage_time:
        coverage_freshness_error = "missing"
    else:
        if coverage_evaluated_at is None:
            coverage_fresh = False
            coverage_freshness_error = "malformed"
        elif coverage_evaluated_at > current + clock_skew:
            coverage_fresh = False
            coverage_freshness_error = "future"
        elif current - coverage_evaluated_at > max_age:
            coverage_fresh = False
            coverage_freshness_error = "stale"
    coverage_ok = bool(criteria) and not missing_coverage and not unverified_coverage
    coverage_ok = bool(
        coverage_ok and not coverage_declared_false and not coverage_declared_reasons
    )
    coverage_ok = bool(coverage_ok and not coverage_tree_mismatch and coverage_fresh)
    if not coverage_rows or missing_coverage:
        coverage_code = "coverage_missing"
    elif unverified_coverage or coverage_declared_false or coverage_declared_reasons:
        coverage_code = "coverage_unverified"
    elif coverage_tree_mismatch:
        coverage_code = "coverage_tree_mismatch"
    else:
        coverage_code = "coverage_stale"
    add_check(
        "mandatory_coverage",
        coverage_ok,
        coverage_code,
        "Map every mandatory acceptance criterion to fresh, verified implementation and validation proof bound to the current tree.",
        {
            "missing_criteria": missing_coverage,
            "unverified_criteria": unverified_coverage,
            "tree_mismatch": coverage_tree_mismatch,
            "freshness_error": coverage_freshness_error,
            "declared_verified": coverage_payload.get("verified"),
            "declared_reason_codes": coverage_declared_reasons,
            "coverage": coverage_payload,
        },
        "coverage_verified",
        "Every mandatory acceptance criterion has fresh, verified coverage.",
    )

    if channel_binding_applicable:
        channel_binding_ok = bool(criteria) and not channel_binding_errors
        channel_binding_code = (
            str(channel_binding_errors[0].get("code") or "")
            if channel_binding_errors
            else "producer_channel_binding_incomplete"
        )
        add_check(
            "producer_channel_binding",
            channel_binding_ok,
            channel_binding_code,
            (
                "Produce fresh validation evidence from each coverage row's "
                "required producer channel and channel proof revision."
            ),
            {
                "require_artifact_binding": require_artifact_binding,
                "errors": channel_binding_errors,
            },
            "producer_channel_binding_verified",
            "Every mandatory criterion is proven by its required producer channel.",
        )

    each_criterion_valid = bool(criteria) and all(
        criterion_channel_matches.get(_criterion_key(criterion), False)
        if channel_binding_applicable
        else any(
            item.valid
            and _criterion_key(item.evidence.acceptance_criterion) == _criterion_key(criterion)
            for item in evidence_results
        )
        for criterion in criteria
    )
    invalid_results = [item.to_dict() for item in evidence_results if not item.valid]
    # The exact submitted evidence set is authoritative.  A fresh receipt
    # cannot mask a stale, failed, or contradictory receipt submitted beside
    # it for the same decision.
    validation_ok = bool(each_criterion_valid and evidence_results and not invalid_results)
    add_check(
        "required_validations",
        validation_ok,
        "validation_evidence_incomplete",
        "Every submitted validation proof must be fresh and passing, and every mandatory criterion must have one.",
        {"results": result_payloads, "invalid_results": invalid_results},
        "validations_verified",
        "Every mandatory criterion has fresh, passing validation evidence.",
    )

    health_status = (
        str(
            health_payload.get("status")
            or health_payload.get("health")
            or ("healthy" if health_payload.get("healthy") is True else "")
        )
        .strip()
        .lower()
    )
    health_declared = (
        _bool_value(health_payload.get("healthy")) if "healthy" in health_payload else None
    )
    health_safe = (
        _bool_value(health_payload.get("safe_for_completion_reasoning"))
        if "safe_for_completion_reasoning" in health_payload
        else None
    )
    health_exhaustive = (
        _bool_value(health_payload.get("exhaustive")) if "exhaustive" in health_payload else None
    )
    health_reason_codes = health_payload.get("reason_codes")
    health_reason_codes = (
        list(health_reason_codes) if isinstance(health_reason_codes, (list, tuple)) else []
    )
    health_failure_flags = [
        field_name
        for field_name in (
            "partial",
            "skipped",
            "failed",
            "timed_out",
            "unsupported",
            "duplicate_only",
            "inconclusive",
        )
        if _bool_value(health_payload.get(field_name)) is True
    ]
    health_contradictions = health_payload.get("contradictions")
    health_ok = (
        health_status == "healthy"
        and ("healthy" not in health_payload or health_declared is True)
        and health_safe is True
        and health_exhaustive is True
        and not health_reason_codes
        and not health_failure_flags
        and not health_payload.get("error")
        and not health_contradictions
    )
    if not health_status:
        health_code = "analyzer_health_missing"
    elif health_status != "healthy" or health_declared is False:
        health_code = "analyzer_unhealthy"
    else:
        health_code = "analyzer_completion_unsafe"
    add_check(
        "analyzer_health",
        health_ok,
        health_code,
        "Require an explicitly healthy analyzer that is safe for completion reasoning.",
        health_payload,
        "analyzer_healthy",
        "Analyzer health is explicitly healthy and completion-safe.",
    )

    declared_values = [
        _bool_value(quorum_payload[key])
        for key in ("satisfied", "quorum_met")
        if key in quorum_payload
    ]
    binding = (
        quorum_payload.get("binding") if isinstance(quorum_payload.get("binding"), Mapping) else {}
    )
    binding_mismatch: list[str] = []
    if quorum_payload and repository_tree and str(binding.get("tree_id") or "") != repository_tree:
        binding_mismatch.append("tree_id")
    if (
        quorum_payload
        and repository_id
        and str(binding.get("repository_id") or "") != repository_id
    ):
        binding_mismatch.append("repository_id")
    required_members = _gate_count(
        quorum_payload.get("required_members", quorum_payload.get("required"))
    )
    members_present = "members" in quorum_payload or "eligible_members" in quorum_payload
    raw_members = quorum_payload.get("members", quorum_payload.get("eligible_members", ()))
    members = list(raw_members) if isinstance(raw_members, (list, tuple)) else []
    declared_member_count = _gate_count(
        quorum_payload.get("member_count", quorum_payload.get("count"))
    )
    member_count = (
        len(members) if declared_member_count is None and members_present else declared_member_count
    )
    quorum_inconsistencies: list[str] = []
    if required_members is None or required_members < 1:
        quorum_inconsistencies.append("invalid_required_members")
    if member_count is None:
        quorum_inconsistencies.append("missing_member_count")
    if members_present and not isinstance(raw_members, (list, tuple)):
        quorum_inconsistencies.append("invalid_members")
    if not members:
        quorum_inconsistencies.append("missing_quorum_members")
    if (
        members_present
        and declared_member_count is not None
        and declared_member_count != len(members)
    ):
        quorum_inconsistencies.append("member_count_mismatch")
    if (
        required_members is not None
        and member_count is not None
        and member_count < required_members
    ):
        quorum_inconsistencies.append("insufficient_members")
    member_ids: list[str] = []
    receipt_cids: list[str] = []
    independence_keys: list[tuple[str, str]] = []
    eligible_member_ids: list[str] = []
    producer_ids: list[str] = []
    implementation_keys: list[str] = []
    child_receipt_sha256s: list[str] = []
    stale_members: list[str] = []
    for index, member in enumerate(members):
        if not isinstance(member, Mapping):
            quorum_inconsistencies.append(f"invalid_member:{index}")
            continue
        raw_receipt = (
            member.get("receipt") if isinstance(member.get("receipt"), Mapping) else member
        )
        member_id = str(member.get("member_id") or raw_receipt.get("producer_id") or "").strip()
        receipt_cid = str(
            member.get("receipt_cid")
            or raw_receipt.get("child_receipt_sha256")
            or raw_receipt.get("source_receipt_sha256")
            or ""
        ).strip()
        if not member_id or not receipt_cid:
            quorum_inconsistencies.append(f"incomplete_member:{index}")
        member_ids.append(member_id)
        receipt_cids.append(receipt_cid)
        member_binding = member.get("binding") if isinstance(member.get("binding"), Mapping) else {}
        if not member_binding:
            quorum_inconsistencies.append(f"missing_member_binding:{index}")
        elif binding and any(
            str(member_binding.get(key) or "") != str(binding.get(key) or "")
            for key in (
                "repository_id",
                "tree_id",
                "analyzer_version",
                "configuration_revision",
                "objective_revision",
            )
            if binding.get(key)
        ):
            quorum_inconsistencies.append(f"member_binding_mismatch:{index}")
        finished_value = (
            member.get("finished_at")
            or member.get("executed_at")
            or member.get("generated_at")
            or raw_receipt.get("finished_at")
            or raw_receipt.get("executed_at")
            or raw_receipt.get("generated_at")
        )
        finished_at = _gate_datetime(finished_value)
        if finished_value is None or finished_value == "" or finished_at is None:
            stale_members.append(member_id or str(index))
        elif finished_at > current + clock_skew or current - finished_at > max_age:
            stale_members.append(member_id or str(index))

        # Eligibility is derived from exact receipt facts.  Neither a
        # top-level ``satisfied`` boolean nor arbitrary member/channel labels
        # can manufacture an independent completion vote.
        metadata = (
            raw_receipt.get("metadata") if isinstance(raw_receipt.get("metadata"), Mapping) else {}
        )
        raw_health = raw_receipt.get("analyzer_health")
        if not isinstance(raw_health, Mapping):
            raw_health = metadata.get("analyzer_health")
        raw_health = raw_health if isinstance(raw_health, Mapping) else {}
        raw_health_status = (
            str(
                raw_health.get("status")
                or raw_receipt.get("health")
                or metadata.get("health")
                or ("healthy" if raw_receipt.get("healthy") is True else "")
                or ""
            )
            .strip()
            .lower()
        )
        raw_healthy = _bool_value(
            raw_health.get(
                "healthy",
                raw_receipt.get("healthy"),
            )
        )
        raw_passed = raw_receipt.get(
            "passed",
            raw_receipt.get("validation_passed"),
        )
        member_passed = _bool_value(raw_passed)
        if member_passed is None:
            member_passed = str(raw_receipt.get("status") or "").strip().lower() in {
                "passed",
                "pass",
                "success",
                "succeeded",
                "verified",
                "ok",
            }
        member_safe = _bool_value(
            raw_receipt.get(
                "safe_for_completion_reasoning",
                raw_health.get(
                    "safe_for_completion_reasoning",
                    metadata.get("safe_for_completion_reasoning"),
                ),
            )
        )
        member_exhaustive = _bool_value(
            raw_receipt.get(
                "exhaustive",
                raw_health.get("exhaustive", metadata.get("exhaustive")),
            )
        )
        member_conclusive = _bool_value(raw_receipt.get("conclusive"))
        if member_conclusive is None:
            member_conclusive = (
                str(raw_receipt.get("outcome") or "").strip().lower() == "conclusive"
            )
        contradiction_value = raw_receipt.get(
            "contradicted",
            raw_receipt.get("contradictory"),
        )
        explicit_uncontradicted = _bool_value(raw_receipt.get("uncontradicted"))
        member_uncontradicted = (
            contradiction_value is False and explicit_uncontradicted is not False
        ) or (contradiction_value is None and explicit_uncontradicted is True)
        contradictions = raw_receipt.get(
            "contradictions",
            raw_receipt.get("contradiction_receipts", ()),
        )
        if contradictions:
            member_uncontradicted = False
        scan_mode = (
            str(raw_receipt.get("scan_mode") or member.get("scan_mode") or "")
            .strip()
            .lower()
            .replace("-", "_")
        )
        if scan_mode == "audit" or scan_mode.endswith("_audit"):
            derived_channel = "audit"
        elif "exhaustive" in scan_mode:
            derived_channel = "exhaustive"
        else:
            derived_channel = ""
        analyzer_version = str(
            raw_receipt.get("analyzer_version") or member_binding.get("analyzer_version") or ""
        ).strip()
        producer_id = str(raw_receipt.get("producer_id") or member.get("producer_id") or "").strip()
        implementation = raw_receipt.get(
            "implementation",
            member.get("implementation"),
        )
        if isinstance(implementation, str):
            normalized_implementation: Any = " ".join(implementation.split())
            has_implementation = bool(normalized_implementation)
        elif isinstance(implementation, Mapping):
            normalized_implementation = _json_value(dict(implementation))
            has_implementation = bool(implementation)
        elif isinstance(implementation, (list, tuple)):
            normalized_implementation = [
                " ".join(item.split()) for item in implementation if isinstance(item, str)
            ]
            has_implementation = bool(implementation) and (
                len(normalized_implementation) == len(implementation)
                and all(normalized_implementation)
            )
        else:
            normalized_implementation = None
            has_implementation = False
        raw_child_receipt_binding = raw_receipt.get(
            "child_receipt_binding",
            raw_receipt.get(
                "child_tree_binding",
                raw_receipt.get(
                    "source_tree_binding",
                    member.get("child_receipt_binding", ""),
                ),
            ),
        )
        child_receipt_binding = str(raw_child_receipt_binding or "").strip()
        child_receipt_sha256 = str(
            raw_receipt.get(
                "child_receipt_sha256",
                raw_receipt.get(
                    "source_receipt_sha256",
                    member.get(
                        "child_receipt_sha256",
                        member.get("source_receipt_sha256", ""),
                    ),
                ),
            )
            or ""
        ).strip()
        child_receipt_sha256_digest = child_receipt_sha256.lower()
        if child_receipt_sha256_digest.startswith("sha256:"):
            child_receipt_sha256_digest = child_receipt_sha256_digest[7:]
        try:
            child_sha_is_valid = (
                len(child_receipt_sha256_digest) == 64 and int(child_receipt_sha256_digest, 16) >= 0
            )
        except ValueError:
            child_sha_is_valid = False
        canonical_child_sha = f"sha256:{child_receipt_sha256_digest}" if child_sha_is_valid else ""
        aggregate_tree_binding = str(
            raw_receipt.get(
                "aggregate_tree_binding",
                raw_receipt.get(
                    "tree_binding",
                    member.get("aggregate_tree_binding", ""),
                ),
            )
            or ""
        ).strip()
        implementation_identity = (
            _stable_fingerprint(
                "completion-quorum-implementation",
                normalized_implementation,
            )
            if has_implementation
            else ""
        )
        if producer_id and has_implementation:
            producer_ids.append(producer_id)
            implementation_keys.append(implementation_identity)
            if canonical_child_sha:
                child_receipt_sha256s.append(canonical_child_sha)
            derived_channel = "producer:" + _stable_fingerprint(
                "completion-quorum-producer",
                {
                    "producer_id": producer_id,
                    "implementation": normalized_implementation,
                },
            )
        eligibility_errors: list[str] = []
        if member_passed is not True:
            eligibility_errors.append("not_passing")
        member_status = str(raw_receipt.get("status") or "").strip().lower()
        if member_status and member_status not in {
            "passed",
            "pass",
            "success",
            "succeeded",
            "verified",
            "ok",
        }:
            eligibility_errors.append("contradictory_status")
        healthy_was_declared = "healthy" in raw_health or "healthy" in raw_receipt
        if raw_health_status != "healthy" or (healthy_was_declared and raw_healthy is not True):
            eligibility_errors.append("not_healthy")
        if member_exhaustive is not True:
            eligibility_errors.append("not_exhaustive")
        if member_safe is not True:
            eligibility_errors.append("not_completion_safe")
        if member_conclusive is not True:
            eligibility_errors.append("not_conclusive")
        if not member_uncontradicted:
            eligibility_errors.append("not_explicitly_uncontradicted")
        member_reason_codes = [
            str(item)
            for source in (
                raw_receipt.get("reason_codes"),
                raw_health.get("reason_codes"),
            )
            if isinstance(source, (list, tuple))
            for item in source
            if str(item)
        ]
        member_failure_flags = [
            field_name
            for field_name in (
                "partial",
                "skipped",
                "failed",
                "timed_out",
                "unsupported",
                "duplicate_only",
                "inconclusive",
            )
            if (
                _bool_value(raw_receipt.get(field_name)) is True
                or _bool_value(raw_health.get(field_name)) is True
            )
        ]
        if member_reason_codes or member_failure_flags or raw_receipt.get("error"):
            eligibility_errors.append("contradictory_failure_evidence")
        if not derived_channel:
            eligibility_errors.append("independence_channel_not_derivable")
        if producer_id or has_implementation:
            if not producer_id or not has_implementation:
                eligibility_errors.append("producer_identity_incomplete")
            if not child_receipt_binding:
                eligibility_errors.append("child_receipt_binding_missing")
            if not child_receipt_sha256:
                eligibility_errors.append("child_receipt_sha256_missing")
            elif not child_sha_is_valid:
                eligibility_errors.append("child_receipt_sha256_invalid")
            if not aggregate_tree_binding:
                eligibility_errors.append("aggregate_tree_binding_missing")
            elif (
                binding
                and str(binding.get("tree_id") or "")
                and aggregate_tree_binding != str(binding.get("tree_id"))
            ):
                eligibility_errors.append("aggregate_tree_binding_mismatch")
        if not analyzer_version:
            eligibility_errors.append("analyzer_version_missing")
        if eligibility_errors:
            quorum_inconsistencies.append(
                f"ineligible_member:{index}:{','.join(eligibility_errors)}"
            )
        else:
            independence_keys.append((derived_channel, analyzer_version))
            eligible_member_ids.append(member_id or str(index))
    if len(set(member_ids)) != len(member_ids):
        quorum_inconsistencies.append("duplicate_member_id")
    if len(set(receipt_cids)) != len(receipt_cids):
        quorum_inconsistencies.append("duplicate_receipt_cid")
    if len(set(producer_ids)) != len(producer_ids):
        quorum_inconsistencies.append("duplicate_producer_id")
    if len(set(implementation_keys)) != len(implementation_keys):
        quorum_inconsistencies.append("duplicate_producer_implementation")
    if len(set(child_receipt_sha256s)) != len(child_receipt_sha256s):
        quorum_inconsistencies.append("duplicate_child_receipt_sha256")
    if len(set(independence_keys)) != len(independence_keys):
        quorum_inconsistencies.append("duplicate_derived_independence_channel")
    if stale_members:
        quorum_inconsistencies.append("stale_quorum_members")
    derived_member_count = len(set(independence_keys))
    derived_quorum = bool(
        required_members is not None
        and required_members > 0
        and derived_member_count >= required_members
    )
    if declared_member_count is not None and declared_member_count != derived_member_count:
        quorum_inconsistencies.append("derived_member_count_mismatch")
    if declared_values and any(value is not derived_quorum for value in declared_values):
        quorum_inconsistencies.append("declared_quorum_mismatch")
    quorum_ok = bool(
        quorum_payload and derived_quorum and not binding_mismatch and not quorum_inconsistencies
    )
    if not quorum_payload:
        quorum_code = "exhaustion_quorum_missing"
    elif derived_quorum and binding_mismatch:
        quorum_code = "exhaustion_quorum_binding_mismatch"
    elif (
        not derived_quorum and declared_values and all(value is False for value in declared_values)
    ):
        quorum_code = "exhaustion_quorum_unsatisfied"
    elif quorum_inconsistencies:
        quorum_code = "exhaustion_quorum_inconsistent"
    else:
        quorum_code = "exhaustion_quorum_unsatisfied"
    add_check(
        "exhaustion_quorum",
        quorum_ok,
        quorum_code,
        "Require the configured number of independent, fresh, healthy exhaustive receipts bound to the current repository tree.",
        {
            "binding_mismatch": binding_mismatch,
            "inconsistencies": quorum_inconsistencies,
            "stale_members": stale_members,
            "eligible_member_ids": eligible_member_ids,
            "derived_member_count": derived_member_count,
            "quorum": quorum_payload,
        },
        "exhaustion_quorum_satisfied",
        "The configured exhaustion quorum is satisfied by independent proof.",
    )

    unsafe_analysis = False
    effective_analysis = analysis_payload
    if isinstance(analysis_payload.get("receipt"), Mapping):
        effective_analysis = dict(analysis_payload["receipt"])
    terminal = ""
    safe: bool | None = None
    if effective_analysis:
        terminal = (
            str(effective_analysis.get("terminal_reason") or effective_analysis.get("status") or "")
            .strip()
            .lower()
            .replace("-", "_")
        )
        safe = _bool_value(effective_analysis.get("safe_for_completion_reasoning"))
        unsafe_analysis = safe is not True or terminal not in {"exhausted", "healthy_exhausted"}
    add_check(
        "analysis_terminal_state",
        not unsafe_analysis,
        "analysis_not_completion_safe",
        "Analysis was partial, skipped, failed, timed out, duplicate-only, unsupported, or not explicitly completion-safe.",
        {
            "analysis": analysis_payload,
            "effective_terminal_reason": terminal,
            "effective_safe": safe,
        },
        "analysis_completion_safe" if effective_analysis else "analysis_not_supplied",
        "Analysis proof is exhausted and completion-safe."
        if effective_analysis
        else "No optional standalone analysis result was supplied; quorum proof remains authoritative.",
    )

    bad_children: list[dict[str, Any]] = []
    descendants: list[dict[str, Any]] = []

    def collect_descendants(values: Sequence[dict[str, Any]]) -> None:
        for child in values:
            descendants.append(child)
            gate_value = child.get("completion_gate", child.get("gate"))
            gate_value = gate_value if isinstance(gate_value, Mapping) else {}
            evaluated_value = gate_value.get("evaluated_evidence")
            evaluated_value = evaluated_value if isinstance(evaluated_value, Mapping) else {}
            nested = evaluated_value.get("child_goals", child.get("child_goals", ()))
            if isinstance(nested, (list, tuple)):
                collect_descendants([_mapping_value(item) for item in nested])

    collect_descendants(child_payloads)
    required_child_ids = tuple(
        dict.fromkeys(
            str(goal_id).strip() for goal_id in required_child_goal_ids if str(goal_id).strip()
        )
    )
    observed_child_ids = [str(child.get("goal_id") or "").strip() for child in descendants]
    missing_child_ids = sorted(set(required_child_ids) - set(observed_child_ids))
    unexpected_child_ids = (
        sorted(set(observed_child_ids) - set(required_child_ids)) if required_child_ids else []
    )
    duplicate_child_ids = sorted(
        {
            goal_id
            for goal_id in observed_child_ids
            if goal_id and observed_child_ids.count(goal_id) > 1
        }
    )
    child_set_mismatch = bool(
        required_child_ids
        and (
            missing_child_ids
            or unexpected_child_ids
            or duplicate_child_ids
            or any(not goal_id for goal_id in observed_child_ids)
        )
    )
    descendant_proof_requirements: list[dict[str, Any]] = []
    seen_proof_requirements: set[str] = set()

    def add_child_requirement(value: Mapping[str, Any], child: Mapping[str, Any]) -> None:
        requirement = {str(key): _json_value(item) for key, item in value.items()}
        requirement.setdefault("goal_id", str(child.get("goal_id") or ""))
        identity = _canonical_json(
            {
                "goal_id": requirement.get("goal_id", ""),
                "acceptance_criterion": requirement.get("acceptance_criterion", ""),
                "obligation_id": requirement.get(
                    "obligation_id", requirement.get("proof_obligation_id", "")
                ),
                "proof_receipt_id": requirement.get("proof_receipt_id", ""),
                "required_assurance": requirement.get("required_assurance", ""),
            }
        )
        if identity not in seen_proof_requirements:
            seen_proof_requirements.add(identity)
            descendant_proof_requirements.append(requirement)

    for child in descendants:
        explicit = child.get("proof_requirements", ())
        if isinstance(explicit, Mapping):
            explicit = (explicit,)
        if isinstance(explicit, (list, tuple)):
            for requirement in explicit:
                if isinstance(requirement, Mapping):
                    add_child_requirement(requirement, child)
        child_results = child.get("evidence_results", ())
        if isinstance(child_results, (list, tuple)):
            for raw_result in child_results:
                if not isinstance(raw_result, Mapping):
                    continue
                raw_evidence = raw_result.get("evidence", raw_result)
                if not isinstance(raw_evidence, Mapping):
                    continue
                required_value = _assurance_level(
                    raw_evidence.get("required_assurance", AssuranceLevel.UNVERIFIED)
                )
                if (
                    required_value is AssuranceLevel.UNVERIFIED
                    and not raw_evidence.get("obligation_id")
                    and not raw_evidence.get("proof_receipt_id")
                ):
                    continue
                add_child_requirement(
                    {
                        "acceptance_criterion": raw_evidence.get("acceptance_criterion", ""),
                        "obligation_id": raw_evidence.get(
                            "obligation_id", raw_evidence.get("proof_obligation_id", "")
                        ),
                        "proof_receipt_id": raw_evidence.get("proof_receipt_id", ""),
                        "required_assurance": raw_evidence.get(
                            "required_assurance", AssuranceLevel.UNVERIFIED.value
                        ),
                        "authoritative_assurance": raw_evidence.get(
                            "authoritative_assurance",
                            raw_evidence.get("assurance", AssuranceLevel.UNVERIFIED.value),
                        ),
                        "proof_verdict": raw_evidence.get(
                            "proof_verdict", raw_evidence.get("authoritative_verdict", "")
                        ),
                        "freshness": raw_evidence.get(
                            "proof_freshness", raw_evidence.get("receipt_freshness", "")
                        ),
                        "assurance_satisfied": raw_result.get(
                            "assurance_satisfied",
                            raw_evidence.get("assurance_satisfied"),
                        ),
                        "contradicted": raw_evidence.get("contradictory", False),
                        "reason_codes": raw_result.get("reason_codes", ()),
                    },
                    child,
                )

    unsatisfied_proof_requirements: list[dict[str, Any]] = []
    proof_failure_codes: set[str] = set()
    for requirement in descendant_proof_requirements:
        required = _assurance_level(
            requirement.get("required_assurance", AssuranceLevel.UNVERIFIED)
        )
        actual = _assurance_level(
            requirement.get(
                "authoritative_assurance",
                requirement.get("assurance", AssuranceLevel.UNVERIFIED),
            )
        )
        verdict = _proof_verdict(
            requirement.get("proof_verdict", requirement.get("authoritative_verdict", ""))
        )
        freshness = _proof_freshness(
            requirement.get("freshness", requirement.get("proof_freshness", ""))
        )
        raw_codes = requirement.get("reason_codes", ())
        if isinstance(raw_codes, str):
            raw_codes = (raw_codes,)
        reason_set = {str(code) for code in raw_codes if str(code)}
        failures: list[str] = []
        if required is None:
            failures.append("child_proof_requirement_invalid")
        elif required is not AssuranceLevel.UNVERIFIED:
            if (
                requirement.get("contradicted") is True
                or "contradicted_proof" in reason_set
                or "contradictory_evidence" in reason_set
                or verdict is ProofVerdict.DISPROVED
            ):
                failures.append("child_proof_contradicted")
            if "unsupported_proof" in reason_set or verdict is ProofVerdict.UNSUPPORTED:
                failures.append("child_proof_unsupported")
            if "inconclusive_proof" in reason_set or verdict in {
                ProofVerdict.INCONCLUSIVE,
                ProofVerdict.ERROR,
                ProofVerdict.CANCELLED,
            }:
                failures.append("child_proof_inconclusive")
            if "stale_proof_receipt" in reason_set or freshness in {
                EvidenceFreshness.STALE,
                EvidenceFreshness.UNKNOWN,
            }:
                failures.append("child_proof_stale")
            assurance_declared = requirement.get(
                "assurance_satisfied", requirement.get("satisfied")
            )
            derived_satisfied = bool(
                actual is not None
                and assurance_satisfies(actual, required)
                and verdict is ProofVerdict.PROVED
                and freshness is EvidenceFreshness.CURRENT
            )
            if assurance_declared is not True or not derived_satisfied:
                failures.append("child_required_assurance_not_satisfied")
        if failures:
            failed = dict(requirement)
            failed["failure_codes"] = list(dict.fromkeys(failures))
            unsatisfied_proof_requirements.append(failed)
            proof_failure_codes.update(failures)

    for child in descendants:
        state = str(child.get("state") or child.get("next_state") or "").lower()
        gate_value = child.get("completion_gate", child.get("gate"))
        gate_value = gate_value if isinstance(gate_value, Mapping) else {}
        verified = child.get("verified") is True and state == GoalState.VERIFIED_COMPLETE.value
        if not verified or gate_value.get("passed") is False:
            bad_children.append(child)
    child_ok = not child_set_mismatch and not bad_children and not unsatisfied_proof_requirements
    child_code = ""
    if child_set_mismatch:
        child_code = "child_goal_set_mismatch"
    elif proof_failure_codes:
        for candidate in (
            "child_proof_contradicted",
            "child_proof_unsupported",
            "child_proof_inconclusive",
            "child_proof_stale",
            "child_required_assurance_not_satisfied",
            "child_proof_requirement_invalid",
        ):
            if candidate in proof_failure_codes:
                child_code = candidate
                break
    elif bad_children:
        states = {
            str(item.get("state") or item.get("next_state") or "").lower() for item in bad_children
        }
        child_code = (
            "child_analysis_inconclusive"
            if GoalState.ANALYSIS_INCONCLUSIVE.value in states
            else ("child_reopened" if GoalState.REOPENED.value in states else "child_unverified")
        )
    add_check(
        "child_goals",
        child_ok,
        child_code,
        "Every descendant must remain verified with all proof requirements fresh, conclusive, uncontradicted, and satisfied.",
        {
            "children": child_payloads,
            "descendants": descendants,
            "required_child_goal_ids": list(required_child_ids),
            "observed_child_goal_ids": observed_child_ids,
            "missing_child_goal_ids": missing_child_ids,
            "unexpected_child_goal_ids": unexpected_child_ids,
            "duplicate_child_goal_ids": duplicate_child_ids,
            "unverified_children": bad_children,
            "proof_requirements": descendant_proof_requirements,
            "unsatisfied_proof_requirements": unsatisfied_proof_requirements,
        },
        "descendant_proofs_verified",
        "Every supplied descendant and its aggregated proof requirements remain verified.",
    )

    evaluated = {
        "acceptance_criteria": list(criteria),
        "coverage": coverage_payload,
        "validation_evidence": raw_result_payloads,
        "analyzer_health": health_payload,
        "exhaustion_quorum": quorum_payload,
        "analysis_result": analysis_payload,
        "child_goals": child_payloads,
        "required_child_goal_ids": list(required_child_ids),
        "proof_requirements": descendant_proof_requirements,
        "repository_tree": repository_tree,
        "repository_id": repository_id,
        "evaluated_at": current.isoformat(),
        "freshness_seconds": max(0.0, float(freshness_seconds)),
    }
    result = CompletionGateResult(all(check.passed for check in checks), tuple(checks), evaluated)
    try:
        from ipfs_accelerate_py.agent_supervisor.runtime.supervisor_meta_index import (
            mirror_work_record,
        )

        mirror_work_record(
            catalog_kind="metadata",
            record_kind="completion_gate",
            record_ref=str(repository_tree or repository_id or "completion-gate"),
            tree_id=str(repository_tree),
            subject_kind="tree_id" if repository_tree else "record_cid",
            subject_ref=str(repository_tree or repository_id or "completion-gate"),
        )
    except Exception:
        pass
    return result


def _acceptance_criteria(values: Sequence[str] | str | None) -> tuple[str, ...]:
    if values is None:
        return ()
    if isinstance(values, str):
        # Acceptance fields conventionally delimit independent criteria with
        # semicolons.  Do not split commas: prose commonly contains them.
        source = values.split(";")
    else:
        source = values
    result: list[str] = []
    seen: set[str] = set()
    for value in source:
        criterion = str(value or "").strip()
        key = _criterion_key(criterion)
        if criterion and key not in seen:
            seen.add(key)
            result.append(criterion)
    return tuple(result)


def evaluate_goal_completion(
    *,
    current_state: GoalState | str = GoalState.ACTIVE,
    acceptance_criteria: Sequence[str] | str | None = None,
    evidence: Sequence[CompletionEvidence | Mapping[str, Any]] = (),
    tasks_complete: bool = False,
    repository_tree: str = "",
    repository_id: str = "",
    objective_revision: str = "",
    completion_binding: Any = None,
    require_artifact_binding: bool = False,
    now: datetime | str | None = None,
    freshness_seconds: float = DEFAULT_EVIDENCE_FRESHNESS_SECONDS,
    clock_skew_seconds: float = DEFAULT_CLOCK_SKEW_SECONDS,
    analysis_inconclusive: bool = False,
    blocked_reason: str = "",
    coverage: Any = None,
    analyzer_health: Any = None,
    exhaustion_quorum: Any = None,
    child_goals: Sequence[Any] = (),
    required_child_goal_ids: Sequence[str] = (),
    analysis_result: Any = None,
    require_completion_gate: bool = True,
) -> GoalCompletionDecision:
    """Evaluate a goal without ever inferring verification from task status.

    Verification is only reachable from ``provisionally_complete``.  This
    makes the two-phase contract observable and prevents a single task status
    update from atomically manufacturing verified completion.
    """

    previous = normalize_goal_state(current_state)
    records = [
        item if isinstance(item, CompletionEvidence) else CompletionEvidence.from_dict(item)
        for item in evidence
    ]
    criteria = _acceptance_criteria(acceptance_criteria)
    if acceptance_criteria is None and records:
        criteria = _acceptance_criteria([item.acceptance_criterion for item in records])
    binding_payload = _mapping_value(completion_binding)
    bound_analyzer_version = str(binding_payload.get("analyzer_version") or "")
    bound_configuration_revision = str(
        binding_payload.get("configuration_revision")
        or binding_payload.get("configuration_id")
        or ""
    )
    results = tuple(
        validate_completion_evidence(
            item,
            repository_tree=repository_tree,
            repository_id=repository_id,
            objective_revision=objective_revision,
            analyzer_version=bound_analyzer_version,
            configuration_revision=bound_configuration_revision,
            require_artifact_binding=require_artifact_binding,
            now=now,
            freshness_seconds=freshness_seconds,
            clock_skew_seconds=clock_skew_seconds,
        )
        for item in records
    )
    by_criterion: dict[str, list[EvidenceValidationResult]] = {}
    for result in results:
        by_criterion.setdefault(_criterion_key(result.evidence.acceptance_criterion), []).append(
            result
        )

    missing: list[str] = []
    invalid: list[str] = []
    reason_codes: list[str] = []
    reasons: list[str] = []

    def add_reason(code: str, reason: str) -> None:
        if code not in reason_codes:
            reason_codes.append(code)
            reasons.append(reason)

    # Preserve defects on unbound records too (for example a record missing
    # its acceptance-criterion name).  Otherwise the caller would only see a
    # generic missing-criterion message and could not repair the source data.
    for result in results:
        for code, reason in zip(result.reason_codes, result.actionable_reasons):
            add_reason(code, reason)

    if not criteria:
        add_reason(
            "missing_acceptance_criteria",
            "Define explicit acceptance criteria before verifying the goal.",
        )
    for criterion in criteria:
        candidates = by_criterion.get(_criterion_key(criterion), [])
        if not candidates:
            missing.append(criterion)
            add_reason(
                "missing_criterion_evidence", f"Produce completion evidence for: {criterion}"
            )
            continue
        # Contradiction always fails closed, even if another record is valid.
        contradicted = any("contradictory_evidence" in item.reason_codes for item in candidates)
        if contradicted or not any(item.valid for item in candidates):
            invalid.append(criterion)
            for item in candidates:
                for code, reason in zip(item.reason_codes, item.actionable_reasons):
                    add_reason(code, f"{criterion}: {reason}")

    gate = (
        evaluate_completion_gate(
            acceptance_criteria=criteria,
            evidence_results=results,
            coverage=coverage,
            analyzer_health=analyzer_health,
            exhaustion_quorum=exhaustion_quorum,
            child_goals=child_goals,
            required_child_goal_ids=required_child_goal_ids,
            analysis_result=analysis_result,
            repository_tree=repository_tree,
            repository_id=repository_id,
            objective_revision=objective_revision,
            completion_binding=binding_payload,
            require_artifact_binding=require_artifact_binding,
            now=now,
            freshness_seconds=freshness_seconds,
            clock_skew_seconds=clock_skew_seconds,
        )
        if require_completion_gate
        else None
    )
    if gate is not None:
        for check in gate.checks:
            if not check.passed and check.reason_code:
                add_reason(check.reason_code, check.reason)
    all_valid = bool(criteria) and not missing and not invalid and (gate is None or gate.passed)
    verified = bool(
        tasks_complete
        and all_valid
        and previous
        in {
            GoalState.PROVISIONALLY_COMPLETE,
            GoalState.VERIFIED_COMPLETE,
        }
    )

    if blocked_reason:
        next_state = (
            GoalState.REOPENED if previous is GoalState.VERIFIED_COMPLETE else GoalState.BLOCKED
        )
        add_reason("goal_blocked", str(blocked_reason).strip())
        if previous is GoalState.VERIFIED_COMPLETE:
            add_reason(
                "verification_invalidated", "Reopen the verified goal before recording its blocker."
            )
    elif analysis_inconclusive:
        if previous is GoalState.VERIFIED_COMPLETE:
            next_state = GoalState.REOPENED
            add_reason(
                "verification_invalidated",
                "Reopen the verified goal because completion analysis became inconclusive.",
            )
        elif previous is GoalState.BLOCKED:
            next_state = GoalState.BLOCKED
        else:
            next_state = GoalState.ANALYSIS_INCONCLUSIVE
        add_reason(
            "analysis_inconclusive",
            "Analysis was inconclusive; run the indicated fallback before claiming completion.",
        )
    elif previous is GoalState.VERIFIED_COMPLETE and (not tasks_complete or not all_valid):
        next_state = GoalState.REOPENED
        add_reason(
            "verification_invalidated",
            "Reopen the goal because its completion evidence is no longer valid.",
        )
    elif verified:
        next_state = GoalState.VERIFIED_COMPLETE
    elif tasks_complete and previous in {
        GoalState.ACTIVE,
        GoalState.REOPENED,
        GoalState.ANALYSIS_INCONCLUSIVE,
        GoalState.PROVISIONALLY_COMPLETE,
    }:
        next_state = GoalState.PROVISIONALLY_COMPLETE
        if all_valid and previous is not GoalState.PROVISIONALLY_COMPLETE:
            add_reason(
                "provisional_transition_required",
                "Record provisional completion, then verify in a separate lifecycle transition.",
            )
        elif not all_valid:
            add_reason(
                "verification_evidence_incomplete",
                "Task completion is provisional until every criterion has valid evidence.",
            )
    elif previous in {GoalState.PROVISIONALLY_COMPLETE, GoalState.REOPENED} and not tasks_complete:
        next_state = GoalState.REOPENED
        add_reason(
            "tasks_incomplete",
            "Complete the remaining producing tasks before requesting verification.",
        )
    else:
        next_state = previous
        if not tasks_complete:
            add_reason(
                "tasks_incomplete",
                "Complete the goal's producing tasks before requesting completion.",
            )

    decision = GoalCompletionDecision(
        previous_state=previous,
        state=next_state,
        tasks_complete=bool(tasks_complete),
        verified=verified,
        acceptance_criteria=criteria,
        missing_criteria=tuple(missing),
        invalid_criteria=tuple(invalid),
        evidence_results=results,
        reason_codes=tuple(reason_codes),
        actionable_reasons=tuple(reasons),
        gate=gate,
    )
    try:
        from ipfs_accelerate_py.agent_supervisor.runtime.supervisor_meta_index import (
            mirror_work_record,
        )

        mirror_work_record(
            catalog_kind="metadata",
            record_kind="goal_completion",
            record_ref=str(repository_tree or repository_id or "goal-completion"),
            tree_id=str(repository_tree),
            subject_kind="tree_id" if repository_tree else "record_cid",
            subject_ref=str(repository_tree or repository_id or "goal-completion"),
        )
    except Exception:
        pass
    return decision


@dataclass(frozen=True)
class LegacyGoalMigrationDecision:
    """Auditable, replay-stable classification of one legacy completed goal."""

    goal_id: str
    legacy_state: str
    state: GoalState
    verified: bool
    migration_id: str
    reason_codes: tuple[str, ...]
    actionable_reasons: tuple[str, ...]
    completion_decision: GoalCompletionDecision
    schema_version: int = GOAL_COMPLETION_MIGRATION_SCHEMA_VERSION

    @property
    def changed(self) -> bool:
        return is_legacy_completed_goal_state(self.legacy_state)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "ipfs_accelerate_py.agent_supervisor.goal_completion_migration@1",
            "schema_version": self.schema_version,
            "migration_id": self.migration_id,
            "goal_id": self.goal_id,
            "legacy_state": self.legacy_state,
            "state": self.state.value,
            "verified": self.verified,
            "changed": self.changed,
            "reason_codes": list(self.reason_codes),
            "actionable_reasons": list(self.actionable_reasons),
            "diagnostics": completion_diagnostics(self.completion_decision),
            "completion_decision": self.completion_decision.to_dict(),
        }


def migrate_legacy_goal_completion(
    *,
    goal_id: str,
    legacy_state: GoalState | str,
    acceptance_criteria: Sequence[str] | str | None,
    evidence: Sequence[CompletionEvidence | Mapping[str, Any]] = (),
    tasks_complete: bool = True,
    coverage: Any = None,
    analyzer_health: Any = None,
    exhaustion_quorum: Any = None,
    child_goals: Sequence[Any] = (),
    analysis_result: Any = None,
    analysis_inconclusive: bool = False,
    repository_tree: str = "",
    repository_id: str = "",
    objective_revision: str = "",
    completion_binding: Any = None,
    require_artifact_binding: bool = False,
    now: datetime | str | None = None,
    freshness_seconds: float = DEFAULT_EVIDENCE_FRESHNESS_SECONDS,
    clock_skew_seconds: float = DEFAULT_CLOCK_SKEW_SECONDS,
) -> LegacyGoalMigrationDecision:
    """Classify an old ``completed`` claim using today's completion proof.

    The function is pure and idempotent: its migration identity excludes wall
    clock time and repeated calls with equivalent inputs return the same ID.
    Missing or malformed proof fails closed to provisional completion.  A
    legacy claim may become verified only when the same full gate used for new
    goals passes.
    """

    raw_state = str(getattr(legacy_state, "value", legacy_state) or "").strip().lower()
    if not is_legacy_completed_goal_state(raw_state):
        raise ValueError(f"goal {goal_id!r} is not in a legacy completed state: {raw_state!r}")
    records = tuple(
        item if isinstance(item, CompletionEvidence) else CompletionEvidence.from_dict(item)
        for item in evidence
    )
    decision = evaluate_goal_completion(
        current_state=GoalState.PROVISIONALLY_COMPLETE,
        acceptance_criteria=acceptance_criteria,
        evidence=records,
        tasks_complete=tasks_complete,
        repository_tree=repository_tree,
        repository_id=repository_id,
        objective_revision=objective_revision,
        completion_binding=completion_binding,
        require_artifact_binding=require_artifact_binding,
        now=now,
        freshness_seconds=freshness_seconds,
        clock_skew_seconds=clock_skew_seconds,
        coverage=coverage,
        analyzer_health=analyzer_health,
        exhaustion_quorum=exhaustion_quorum,
        child_goals=child_goals,
        analysis_result=analysis_result,
        analysis_inconclusive=analysis_inconclusive,
    )
    # Migration never turns an ambiguous historical claim into reopened or
    # inconclusive.  Those transitions presuppose a trustworthy modern claim;
    # until one exists the faithful classification is provisional.
    migrated_state = (
        GoalState.VERIFIED_COMPLETE if decision.verified else GoalState.PROVISIONALLY_COMPLETE
    )
    reason_codes = decision.reason_codes
    reasons = decision.actionable_reasons
    if not decision.verified:
        reason_codes = tuple(dict.fromkeys(("legacy_completion_unverified", *reason_codes)))
        reasons = tuple(
            dict.fromkeys(
                (
                    "Legacy completion lacked sufficient modern proof and was migrated provisionally.",
                    *reasons,
                )
            )
        )
    decision = replace(
        decision,
        state=migrated_state,
        verified=migrated_state is GoalState.VERIFIED_COMPLETE,
        reason_codes=reason_codes,
        actionable_reasons=reasons,
    )
    identity_payload = {
        "schema_version": GOAL_COMPLETION_MIGRATION_SCHEMA_VERSION,
        "goal_id": str(goal_id or "").strip(),
        "legacy_state": raw_state,
        "state": migrated_state.value,
        "tasks_complete": bool(tasks_complete),
        "acceptance_criteria": list(_acceptance_criteria(acceptance_criteria)),
        "evidence": [record.to_dict() for record in records],
        "repository_tree": str(repository_tree or ""),
        "repository_id": str(repository_id or ""),
        "freshness_seconds": max(0.0, float(freshness_seconds)),
        "clock_skew_seconds": max(0.0, float(clock_skew_seconds)),
        "analysis_inconclusive": bool(analysis_inconclusive),
        "gate": {
            "coverage": _mapping_value(coverage),
            "analyzer_health": _mapping_value(analyzer_health),
            "exhaustion_quorum": _mapping_value(exhaustion_quorum),
            "child_goals": [_mapping_value(item) for item in child_goals],
            "analysis_result": _mapping_value(analysis_result),
        },
    }
    return LegacyGoalMigrationDecision(
        goal_id=str(goal_id or "").strip(),
        legacy_state=raw_state,
        state=migrated_state,
        verified=decision.verified,
        migration_id=_stable_fingerprint("goal-migration", identity_payload),
        reason_codes=reason_codes,
        actionable_reasons=reasons,
        completion_decision=decision,
    )


def _implementation_obligations(value: Any) -> tuple[CodeProofObligation, ...]:
    """Normalize a fresh implementation-obligation set without trusting maps.

    ``ImplementationObligationSet`` lives in :mod:`code_proof_obligations`.
    Structural access here avoids a module-level dependency cycle and keeps
    persisted callers compatible.  Mapping obligations are accepted only when
    the canonical proof contract can reconstruct and authenticate their
    content identity.
    """

    if value is None:
        return ()
    source = getattr(value, "obligations", value)
    if isinstance(source, Mapping):
        source = source.get("obligations", source.get("required_obligations", source))
    if isinstance(source, CodeProofObligation):
        items: Iterable[Any] = (source,)
    elif isinstance(source, Mapping):
        items = (source,)
    elif isinstance(source, Iterable) and not isinstance(source, (str, bytes)):
        items = source
    else:
        items = (source,)

    obligations: dict[str, CodeProofObligation] = {}
    for item in items:
        if isinstance(item, CodeProofObligation):
            obligation = item
        elif isinstance(item, Mapping):
            try:
                obligation = CodeProofObligation.from_dict(item)
            except (ContractValidationError, TypeError, ValueError):
                # Malformed or model-asserted obligation maps are not silently
                # converted into proof requirements.  The empty/partial set
                # subsequently fails the completion decision closed.
                continue
        else:
            continue
        obligations[obligation.obligation_id] = obligation
    return tuple(obligations[key] for key in sorted(obligations))


def _implementation_binding_id(value: Any) -> str:
    binding = getattr(value, "binding", value)
    if isinstance(binding, Mapping):
        return str(
            binding.get("binding_id") or binding.get("implementation_binding_id") or ""
        ).strip()
    return str(
        getattr(binding, "binding_id", "")
        or getattr(binding, "implementation_binding_id", "")
        or ""
    ).strip()


def _receipt_obligation_id(value: Any) -> str:
    if isinstance(value, ProofReceipt):
        return value.obligation_id
    if isinstance(value, Mapping):
        return str(value.get("obligation_id", "") or "").strip()
    return str(getattr(value, "obligation_id", "") or "").strip()


def _receipt_identity(value: Any) -> str:
    if isinstance(value, ProofReceipt):
        return value.receipt_id
    if isinstance(value, Mapping):
        return str(
            value.get("receipt_id")
            or value.get("content_id")
            or value.get("proof_receipt_id")
            or ""
        ).strip()
    return str(getattr(value, "receipt_id", "") or getattr(value, "content_id", "") or "").strip()


def _code_proof_result_payload(
    result: Any,
    *,
    obligation_id: str,
    receipt: Any,
) -> dict[str, Any]:
    to_dict = getattr(result, "to_dict", None)
    if callable(to_dict):
        payload = to_dict()
        payload = dict(payload) if isinstance(payload, Mapping) else {}
    elif isinstance(result, Mapping):
        payload = dict(result)
    else:
        payload = {
            name: getattr(result, name)
            for name in (
                "valid",
                "reason_codes",
                "stale",
                "contradictory",
                "receipt_id",
                "binding_id",
                "authoritative_assurance",
                "authoritative_verdict",
            )
            if hasattr(result, name)
        }
    payload.setdefault("obligation_id", obligation_id)
    payload.setdefault("receipt_id", _receipt_identity(receipt))
    payload["valid"] = bool(payload.get("valid", False))
    payload["stale"] = bool(payload.get("stale", False))
    payload["contradictory"] = bool(payload.get("contradictory", False))
    payload["reason_codes"] = list(_string_tuple(payload.get("reason_codes", ())))
    return {str(key): _json_value(item) for key, item in payload.items()}


@dataclass(frozen=True)
class CodeProofCompletionDecision:
    """Aggregate fresh implementation proofs into a goal lifecycle decision.

    Planning consistency and observed plan conformance are deliberately absent
    from the success predicate.  They may explain *which* implementation was
    requested, but only canonical receipts accepted by
    ``validate_code_proof_receipt_bindings`` can satisfy implementation
    obligations.
    """

    previous_state: GoalState
    state: GoalState
    tasks_complete: bool
    verified: bool
    binding_id: str = ""
    required_obligation_ids: tuple[str, ...] = ()
    satisfied_obligation_ids: tuple[str, ...] = ()
    unsatisfied_obligation_ids: tuple[str, ...] = ()
    receipt_results: tuple[Mapping[str, Any], ...] = ()
    reason_codes: tuple[str, ...] = ()
    actionable_reasons: tuple[str, ...] = ()
    schema_version: int = GOAL_COMPLETION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "previous_state", normalize_goal_state(self.previous_state))
        object.__setattr__(self, "state", normalize_goal_state(self.state))
        object.__setattr__(self, "tasks_complete", bool(self.tasks_complete))
        object.__setattr__(self, "verified", bool(self.verified))
        object.__setattr__(self, "binding_id", str(self.binding_id or "").strip())
        for name in (
            "required_obligation_ids",
            "satisfied_obligation_ids",
            "unsatisfied_obligation_ids",
            "reason_codes",
            "actionable_reasons",
        ):
            object.__setattr__(self, name, _string_tuple(getattr(self, name)))
        object.__setattr__(
            self,
            "receipt_results",
            tuple(dict(item) for item in self.receipt_results),
        )
        object.__setattr__(self, "schema_version", int(self.schema_version))

    @property
    def reopened(self) -> bool:
        return self.state is GoalState.REOPENED

    @property
    def stale(self) -> bool:
        return any(bool(item.get("stale", False)) for item in self.receipt_results)

    @property
    def contradictory(self) -> bool:
        return any(bool(item.get("contradictory", False)) for item in self.receipt_results)

    @property
    def validation_results(self) -> tuple[Mapping[str, Any], ...]:
        """Compatibility alias for callers using the validator's noun."""

        return self.receipt_results

    @property
    def all_obligations_satisfied(self) -> bool:
        return bool(self.required_obligation_ids) and not self.unsatisfied_obligation_ids

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "ipfs_accelerate_py/agent-supervisor/code-proof-goal-completion@1",
            "schema_version": self.schema_version,
            "previous_state": self.previous_state.value,
            "state": self.state.value,
            "tasks_complete": self.tasks_complete,
            "verified": self.verified,
            "reopened": self.reopened,
            "binding_id": self.binding_id,
            "required_obligation_ids": list(self.required_obligation_ids),
            "satisfied_obligation_ids": list(self.satisfied_obligation_ids),
            "unsatisfied_obligation_ids": list(self.unsatisfied_obligation_ids),
            "all_obligations_satisfied": self.all_obligations_satisfied,
            "stale": self.stale,
            "contradictory": self.contradictory,
            "receipt_results": _json_value(self.receipt_results),
            "reason_codes": list(self.reason_codes),
            "actionable_reasons": list(self.actionable_reasons),
        }


def evaluate_code_proof_goal_completion(
    *,
    current_state: GoalState | str,
    binding: Any,
    required_obligations: Any = None,
    receipts: Sequence[Any] = (),
    plan_assurance: Any = None,
    tasks_complete: bool = True,
) -> CodeProofCompletionDecision:
    """Evaluate generated-code correctness against fresh bound obligations.

    ``binding`` is an ``ImplementationResultBinding`` or an
    ``ImplementationObligationSet``.  The latter is also accepted as
    ``required_obligations``.  Imports are deliberately local so this module
    remains usable by the obligation compiler while it constructs a completion
    packet.

    A provisional or verified completion is reopened when a required receipt
    is stale or contradictory.  Other incomplete proof states remain
    provisional (or reopen an already verified goal), preserving the existing
    two-phase lifecycle.
    """

    from ..proof.code_proof_obligations import validate_code_proof_receipt_bindings

    previous = normalize_goal_state(current_state)
    obligation_set = required_obligations
    obligations = _implementation_obligations(obligation_set)
    if not obligations and required_obligations is not binding:
        # Convenience for callers which supply the ImplementationObligationSet
        # as ``binding`` and omit/empty the redundant obligations argument.
        obligations = _implementation_obligations(binding)
        obligation_set = binding
    validation_binding = (
        obligation_set if getattr(obligation_set, "binding", None) is not None else binding
    )
    receipt_items = tuple(receipts or ())
    binding_id = _implementation_binding_id(validation_binding)

    reasons: list[str] = []
    actionable: list[str] = []

    def reject(code: str, detail: str) -> None:
        if code not in reasons:
            reasons.append(code)
            actionable.append(detail)

    if not binding_id:
        reject(
            "missing_implementation_binding",
            "Bind completion to the accepted plan, repository tree, changed scope, assumptions, and validation bounds.",
        )
    if not obligations:
        reject(
            "missing_code_proof_obligations",
            "Derive fresh implementation obligations from the completed code change before verification.",
        )
    if not tasks_complete:
        reject(
            "tasks_incomplete",
            "Finish the implementation task before evaluating generated-code proof receipts.",
        )

    # PlanAssurance is useful context but is never evidence of generated-code
    # correctness.  Detect the one prohibited crossing explicitly so a plan
    # consistency/conformance receipt cannot be replayed as a code proof.
    planning_receipt_ids: set[str] = set()
    if plan_assurance is not None:
        for name in ("consistency_receipt_ids", "conformance_receipt_ids"):
            value = (
                plan_assurance.get(name, ())
                if isinstance(plan_assurance, Mapping)
                else getattr(plan_assurance, name, ())
            )
            planning_receipt_ids.update(_string_tuple(value))
        if receipt_items and any(
            _receipt_identity(item) in planning_receipt_ids
            for item in receipt_items
            if _receipt_identity(item)
        ):
            reject(
                "plan_receipt_reused_as_code_proof",
                "Use independent code-proof receipts; plan consistency and conformance receipts cannot prove generated code.",
            )
        if not receipt_items:
            reject(
                "plan_assurance_not_code_proof",
                "Plan assurance cannot replace fresh implementation proof receipts.",
            )

    result_payloads: list[dict[str, Any]] = []
    satisfied: list[str] = []
    unsatisfied: list[str] = []
    stale_required = False
    contradictory_required = False

    for obligation in obligations:
        candidates = [
            item
            for item in receipt_items
            if _receipt_obligation_id(item) == obligation.obligation_id
        ]
        valid_for_obligation = False
        if not candidates:
            unsatisfied.append(obligation.obligation_id)
            reject(
                "missing_code_proof_receipt",
                f"Produce a fresh code-proof receipt for obligation {obligation.obligation_id}.",
            )
            continue
        for receipt in candidates:
            try:
                result = validate_code_proof_receipt_bindings(
                    receipt,
                    validation_binding,
                    obligation=obligation,
                    required_assurance=obligation.required_assurance,
                    plan_assurance=plan_assurance,
                )
                payload = _code_proof_result_payload(
                    result,
                    obligation_id=obligation.obligation_id,
                    receipt=receipt,
                )
            except (ContractValidationError, TypeError, ValueError) as exc:
                payload = {
                    "obligation_id": obligation.obligation_id,
                    "receipt_id": _receipt_identity(receipt),
                    "valid": False,
                    "stale": False,
                    "contradictory": False,
                    "reason_codes": ["invalid_code_proof_receipt"],
                    "error": str(exc),
                }
            result_payloads.append(payload)
            if payload["valid"]:
                valid_for_obligation = True
            stale_required = stale_required or bool(payload["stale"])
            contradictory_required = contradictory_required or bool(payload["contradictory"])
            for code in payload["reason_codes"]:
                reject(
                    str(code),
                    f"Regenerate or repair the code-proof receipt for obligation {obligation.obligation_id} ({code}).",
                )
        if valid_for_obligation:
            satisfied.append(obligation.obligation_id)
        else:
            unsatisfied.append(obligation.obligation_id)

    # Receipts that do not correspond to the fresh obligation set are cached
    # history, not affirmative evidence.  Record their rejection explicitly;
    # otherwise a caller could mistake a nonempty receipt list for coverage.
    required_ids = {item.obligation_id for item in obligations}
    for receipt in receipt_items:
        receipt_obligation = _receipt_obligation_id(receipt)
        if receipt_obligation not in required_ids:
            result_payloads.append(
                {
                    "obligation_id": receipt_obligation,
                    "receipt_id": _receipt_identity(receipt),
                    "valid": False,
                    "stale": True,
                    "contradictory": False,
                    "reason_codes": ["receipt_not_required_by_fresh_obligation_set"],
                }
            )
            stale_required = True
            reject(
                "receipt_not_required_by_fresh_obligation_set",
                "Discard cached receipts that are not members of the fresh implementation-obligation set.",
            )

    proof_complete = bool(
        tasks_complete
        and binding_id
        and obligations
        and not unsatisfied
        and "plan_receipt_reused_as_code_proof" not in reasons
    )
    must_reopen = bool(stale_required or contradictory_required)
    if previous is GoalState.VERIFIED_COMPLETE and not proof_complete:
        must_reopen = True
    if must_reopen and previous in {
        GoalState.PROVISIONALLY_COMPLETE,
        GoalState.VERIFIED_COMPLETE,
    }:
        state = GoalState.REOPENED
        reject(
            "code_proof_completion_reopened",
            "Reopen the goal because a required implementation-proof binding is stale, contradictory, or no longer satisfied.",
        )
    elif proof_complete and previous is GoalState.PROVISIONALLY_COMPLETE:
        state = GoalState.VERIFIED_COMPLETE
    elif proof_complete and previous is GoalState.VERIFIED_COMPLETE:
        state = GoalState.VERIFIED_COMPLETE
    elif tasks_complete and previous in {
        GoalState.ACTIVE,
        GoalState.REOPENED,
        GoalState.ANALYSIS_INCONCLUSIVE,
    }:
        state = GoalState.PROVISIONALLY_COMPLETE
        if proof_complete:
            reject(
                "provisional_transition_required",
                "Record provisional completion before the separate verified-completion transition.",
            )
    elif previous is GoalState.VERIFIED_COMPLETE:
        state = GoalState.REOPENED
    else:
        state = previous

    if obligations and unsatisfied:
        reject(
            "code_proof_obligations_unsatisfied",
            "Generated code remains unverified until every fresh implementation obligation has an accepted receipt.",
        )
    verified = bool(state is GoalState.VERIFIED_COMPLETE and proof_complete)
    decision = CodeProofCompletionDecision(
        previous_state=previous,
        state=state,
        tasks_complete=tasks_complete,
        verified=verified,
        binding_id=binding_id,
        required_obligation_ids=tuple(item.obligation_id for item in obligations),
        satisfied_obligation_ids=tuple(satisfied),
        unsatisfied_obligation_ids=tuple(unsatisfied),
        receipt_results=tuple(result_payloads),
        reason_codes=tuple(reasons),
        actionable_reasons=tuple(actionable),
    )
    try:
        from ipfs_accelerate_py.agent_supervisor.runtime.supervisor_meta_index import (
            mirror_work_record,
        )

        mirror_work_record(
            catalog_kind="proof_cache",
            record_kind="code_proof_goal_completion",
            record_ref=str(binding_id or "code-proof-completion"),
            subject_kind="record_cid",
            subject_ref=str(binding_id or "code-proof-completion"),
        )
    except Exception:
        pass
    return decision


# Names used by older prototypes and external consumers.
GoalLifecycleState = GoalState
CompletionDecision = GoalCompletionDecision
assess_goal_completion = evaluate_goal_completion
evaluate_proof_goal_completion = evaluate_code_proof_goal_completion
evaluate_implementation_completion = evaluate_code_proof_goal_completion


__all__ = [
    "CONTRADICTION_KINDS",
    "CodeProofCompletionDecision",
    "CompletionDecision",
    "CompletionGateCheck",
    "CompletionGateResult",
    "CompletionEvidence",
    "ContradictionEvidence",
    "DEFAULT_CLOCK_SKEW_SECONDS",
    "DEFAULT_EVIDENCE_FRESHNESS_SECONDS",
    "EvidenceValidationResult",
    "GOAL_COMPLETION_SCHEMA_VERSION",
    "GOAL_COMPLETION_MIGRATION_SCHEMA_VERSION",
    "GoalCompletionDecision",
    "GoalLifecycle",
    "GoalLifecycleState",
    "LegacyGoalMigrationDecision",
    "LEGACY_COMPLETED_GOAL_STATES",
    "GoalReopenDecision",
    "GoalState",
    "GoalTransition",
    "IllegalGoalTransition",
    "IllegalGoalTransitionError",
    "LEGAL_GOAL_TRANSITIONS",
    "ReopenDecision",
    "assess_goal_completion",
    "discover_goal_contradictions",
    "evaluate_goal_completion",
    "evaluate_code_proof_goal_completion",
    "evaluate_implementation_completion",
    "evaluate_proof_goal_completion",
    "evaluate_completion_gate",
    "completion_diagnostics",
    "contradictions_from_proof_invalidation",
    "is_legacy_completed_goal_state",
    "is_schedulable_goal_state",
    "is_terminal_goal_state",
    "legal_goal_transitions",
    "normalize_goal_state",
    "proof_invalidation_contradictions",
    "migrate_legacy_goal_completion",
    "reconcile_goal_reopenings",
    "reopen_goal_for_contradictions",
    "validate_completion_evidence",
]
