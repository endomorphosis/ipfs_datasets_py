"""Bounded formal adapter for GUI state/action constraints (VGO-020).

Wire interfaces:

* ``GuiFormalAdapter@1`` — translate finite UI constraints into exact graph
  obligations or cvc5-compatible SMT vectors, then classify outcomes.
* ``UiConstraintProblem@1`` — closed, source-grounded constraint problem.
* ``UiConstraintResult@1`` — typed outcome that never elevates structural or
  solver results into beauty, complete accessibility, complete security, or
  unbounded correctness claims.

Conflict policy
---------------
Reuse the existing finite-graph and ``SoftwareVerificationSMTCompiler@1``
boundary.  Do not create a theorem-prover platform or proof cache.  Missing
solvers and incomplete premises fail closed as ``unavailable`` / ``unknown``.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from collections import deque
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, ClassVar, Final

from .models import (
    SourceSpan,
    UiEventDefinition,
    UiStateDefinition,
    UiTransitionDefinition,
)
from .schema import (
    CANONICAL_JSON_PROFILE,
    AnalysisClassification,
    ConstraintCheckStatus,
    EvidenceLevel,
    UiStateKind,
    VerificationStatus,
    parse_enum,
)

# ---------------------------------------------------------------------------
# Interface / schema identities
# ---------------------------------------------------------------------------

GUI_FORMAL_ADAPTER_INTERFACE: Final = "GuiFormalAdapter@1"
GUI_FORMAL_ADAPTER_SCHEMA: Final = "gui-formal-adapter/v1"
GUI_FORMAL_ADAPTER_VERSION: Final = "gui-formal-adapter@1.0.0"

UI_CONSTRAINT_PROBLEM_INTERFACE: Final = "UiConstraintProblem@1"
UI_CONSTRAINT_PROBLEM_SCHEMA: Final = "ui-constraint-problem/v1"

UI_CONSTRAINT_RESULT_INTERFACE: Final = "UiConstraintResult@1"
UI_CONSTRAINT_RESULT_SCHEMA: Final = "ui-constraint-result/v1"

ADAPTER_SOLVER_ID_FINITE_GRAPH: Final = "solver:finite-graph"
ADAPTER_SOLVER_ID_CVC5: Final = "solver:cvc5"
ADAPTER_SOLVER_ID_NONE: Final = "solver:none"

# Claims that must never appear as proved/satisfied solver conclusions.
FORBIDDEN_CLAIM_KINDS: Final[frozenset[str]] = frozenset(
    {
        "beauty",
        "complete_accessibility",
        "complete_security",
        "unbounded_correctness",
    }
)

# Align with gui_optimizer schema identifier vocabulary (includes # and @).
_IDENTIFIER_RE: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/#@-]{0,255}$")
_MAX_STATES: Final = 256
_MAX_EVENTS: Final = 256
_MAX_TRANSITIONS: Final = 1_024
_MAX_PREMISES: Final = 256
_MAX_ASYNC_EFFECTS: Final = 128
_MAX_SOURCE_BINDINGS: Final = 64

# Supported bounded property identifiers (closed vocabulary).
SUPPORTED_PROPERTY_KINDS: Final[frozenset[str]] = frozenset(
    {
        "defined_transition_targets",
        "failure_recovery",
        "async_effect_completeness",
        "event_outcome_coverage",
        "reachable_required_action",
        "single_initial_state",
        "no_duplicate_state_ids",
        "confirmation_bound_action",
        "form_accessible_names",
        "modal_focus_lifecycle",
        "policy_not_browser_authoritative",
    }
)

class GuiFormalAdapterError(ValueError):
    """Raised when a formal-adapter problem cannot be constructed safely."""


class UiConstraintResultKind(str, Enum):
    """Closed outcome vocabulary for bounded UI constraint checks.

    These values are deliberately non-interchangeable:

    * ``proved_bounded_property`` — exhaustive finite or solver proof of a
      *bounded* property under explicit premises;
    * ``counterexample`` — concrete witness that a bounded property fails;
    * ``structural_result`` — exact finite-graph structural conclusion that is
      not elevated to theorem-prover authority;
    * ``unavailable`` — required backend/solver capability is missing;
    * ``unknown`` — premises incomplete, opaque, or the property is unsupported.
    """

    PROVED_BOUNDED_PROPERTY = "proved_bounded_property"
    COUNTEREXAMPLE = "counterexample"
    STRUCTURAL_RESULT = "structural_result"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


class UiConstraintBackend(str, Enum):
    """Backend used (or requested) for a constraint problem."""

    FINITE_GRAPH = "finite_graph"
    CVC5_SMT = "cvc5_smt"
    AUTO = "auto"


class UiConstraintPropertyKind(str, Enum):
    """Closed bounded property kinds admitted by the adapter."""

    DEFINED_TRANSITION_TARGETS = "defined_transition_targets"
    FAILURE_RECOVERY = "failure_recovery"
    ASYNC_EFFECT_COMPLETENESS = "async_effect_completeness"
    EVENT_OUTCOME_COVERAGE = "event_outcome_coverage"
    REACHABLE_REQUIRED_ACTION = "reachable_required_action"
    SINGLE_INITIAL_STATE = "single_initial_state"
    NO_DUPLICATE_STATE_IDS = "no_duplicate_state_ids"
    CONFIRMATION_BOUND_ACTION = "confirmation_bound_action"
    FORM_ACCESSIBLE_NAMES = "form_accessible_names"
    MODAL_FOCUS_LIFECYCLE = "modal_focus_lifecycle"
    POLICY_NOT_BROWSER_AUTHORITATIVE = "policy_not_browser_authoritative"


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _reject_unknown(value: Mapping[str, Any], allowed: frozenset[str], label: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise GuiFormalAdapterError(f"unknown {label} field(s): {', '.join(unknown)}")


def _text(value: object, label: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise GuiFormalAdapterError(f"{label} must be a string")
    if "\x00" in value:
        raise GuiFormalAdapterError(f"{label} must not contain NUL bytes")
    if value.strip() != value:
        raise GuiFormalAdapterError(f"{label} must be trimmed")
    if not allow_empty and not value:
        raise GuiFormalAdapterError(f"{label} must be a non-empty string")
    return value


def _identifier(value: object, label: str) -> str:
    text = _text(value, label)
    if not _IDENTIFIER_RE.fullmatch(text):
        raise GuiFormalAdapterError(f"{label} is not a valid identifier")
    return text


def _enum(value: object, enum_type: type[Enum], label: str) -> Any:
    try:
        return value if isinstance(value, enum_type) else enum_type(value)
    except (TypeError, ValueError) as error:
        choices = ", ".join(repr(item.value) for item in enum_type)
        raise GuiFormalAdapterError(f"{label} must be one of {choices}") from error


def _schema_enum(value: object, enum_type: type[Enum], label: str) -> Any:
    """Parse a schema enum, accepting either wire strings or enum members."""

    if isinstance(value, enum_type):
        return value
    if isinstance(value, Enum):
        value = value.value
    try:
        return parse_enum(value, enum_type, label)
    except Exception as error:  # noqa: BLE001 - normalize to adapter error
        raise GuiFormalAdapterError(str(error)) from error


def _bool(value: object, label: str) -> bool:
    if not isinstance(value, bool):
        raise GuiFormalAdapterError(f"{label} must be a boolean")
    return value


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise GuiFormalAdapterError(f"{label} must be a mapping")
    return value


def _sequence(value: object, label: str) -> Sequence[Any]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise GuiFormalAdapterError(f"{label} must be a sequence")
    return value


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


# ---------------------------------------------------------------------------
# Wire records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class UiConstraintSourceBinding:
    """Constraint-to-source provenance for one obligation fragment."""

    binding_id: str
    subject_id: str
    source_span: SourceSpan | None = None
    evidence: str = ""
    schema_version: str = "ui-constraint-source-binding/v1"

    def __post_init__(self) -> None:
        object.__setattr__(self, "binding_id", _identifier(self.binding_id, "binding_id"))
        object.__setattr__(self, "subject_id", _identifier(self.subject_id, "subject_id"))
        object.__setattr__(
            self, "evidence", _text(self.evidence, "evidence", allow_empty=True)
        )
        if self.source_span is not None and not isinstance(self.source_span, SourceSpan):
            raise GuiFormalAdapterError("source_span must be a SourceSpan or None")
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "binding_id": self.binding_id,
            "evidence": self.evidence,
            "schema_version": self.schema_version,
            "source_span": None if self.source_span is None else self.source_span.to_dict(),
            "subject_id": self.subject_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any] | Any) -> UiConstraintSourceBinding:
        payload = _mapping(value, "UiConstraintSourceBinding")
        _reject_unknown(
            payload,
            frozenset(
                {
                    "binding_id",
                    "evidence",
                    "schema_version",
                    "source_span",
                    "subject_id",
                }
            ),
            "UiConstraintSourceBinding",
        )
        span_raw = payload.get("source_span")
        span: SourceSpan | None
        if span_raw is None:
            span = None
        elif isinstance(span_raw, SourceSpan):
            span = span_raw
        else:
            span = SourceSpan.from_dict(_mapping(span_raw, "source_span"))
        return cls(
            binding_id=payload.get("binding_id", ""),
            subject_id=payload.get("subject_id", ""),
            source_span=span,
            evidence=payload.get("evidence", ""),
            schema_version=payload.get(
                "schema_version", "ui-constraint-source-binding/v1"
            ),
        )


@dataclass(frozen=True, slots=True)
class UiAsyncEffectPremise:
    """Observed loading/success/failure facts for one asynchronous effect."""

    effect_id: str
    has_loading: bool
    has_success: bool
    has_failure: bool
    source_identity: str = ""
    evidence: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "effect_id", _identifier(self.effect_id, "effect_id"))
        object.__setattr__(self, "has_loading", _bool(self.has_loading, "has_loading"))
        object.__setattr__(self, "has_success", _bool(self.has_success, "has_success"))
        object.__setattr__(self, "has_failure", _bool(self.has_failure, "has_failure"))
        object.__setattr__(
            self,
            "source_identity",
            _text(self.source_identity, "source_identity", allow_empty=True),
        )
        object.__setattr__(
            self, "evidence", _text(self.evidence, "evidence", allow_empty=True)
        )

    @property
    def complete(self) -> bool:
        return self.has_loading and self.has_success and self.has_failure

    def to_dict(self) -> dict[str, Any]:
        return {
            "complete": self.complete,
            "effect_id": self.effect_id,
            "evidence": self.evidence,
            "has_failure": self.has_failure,
            "has_loading": self.has_loading,
            "has_success": self.has_success,
            "source_identity": self.source_identity,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any] | Any) -> UiAsyncEffectPremise:
        payload = _mapping(value, "UiAsyncEffectPremise")
        _reject_unknown(
            payload,
            frozenset(
                {
                    "complete",
                    "effect_id",
                    "evidence",
                    "has_failure",
                    "has_loading",
                    "has_success",
                    "source_identity",
                }
            ),
            "UiAsyncEffectPremise",
        )
        return cls(
            effect_id=payload.get("effect_id", ""),
            has_loading=payload.get("has_loading", False),
            has_success=payload.get("has_success", False),
            has_failure=payload.get("has_failure", False),
            source_identity=payload.get("source_identity", ""),
            evidence=payload.get("evidence", ""),
        )


@dataclass(frozen=True, slots=True)
class UiConstraintCounterexample:
    """Minimal witness that a bounded property is violated."""

    counterexample_id: str
    property_kind: str
    subject_ids: tuple[str, ...]
    path_state_ids: tuple[str, ...] = ()
    path_event_ids: tuple[str, ...] = ()
    path_transition_ids: tuple[str, ...] = ()
    message: str = ""
    schema_version: str = "ui-constraint-counterexample/v1"

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "counterexample_id",
            _identifier(self.counterexample_id, "counterexample_id"),
        )
        object.__setattr__(
            self, "property_kind", _text(self.property_kind, "property_kind")
        )
        subjects = tuple(
            _identifier(item, "subject_ids item") for item in self.subject_ids
        )
        if not subjects:
            raise GuiFormalAdapterError("counterexample requires at least one subject_id")
        object.__setattr__(self, "subject_ids", subjects)
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
        object.__setattr__(
            self, "message", _text(self.message, "message", allow_empty=True)
        )
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "counterexample_id": self.counterexample_id,
            "message": self.message,
            "path_event_ids": list(self.path_event_ids),
            "path_state_ids": list(self.path_state_ids),
            "path_transition_ids": list(self.path_transition_ids),
            "property_kind": self.property_kind,
            "schema_version": self.schema_version,
            "subject_ids": list(self.subject_ids),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any] | Any) -> UiConstraintCounterexample:
        payload = _mapping(value, "UiConstraintCounterexample")
        _reject_unknown(
            payload,
            frozenset(
                {
                    "counterexample_id",
                    "message",
                    "path_event_ids",
                    "path_state_ids",
                    "path_transition_ids",
                    "property_kind",
                    "schema_version",
                    "subject_ids",
                }
            ),
            "UiConstraintCounterexample",
        )
        return cls(
            counterexample_id=payload.get("counterexample_id", ""),
            property_kind=payload.get("property_kind", ""),
            subject_ids=tuple(payload.get("subject_ids", ())),
            path_state_ids=tuple(payload.get("path_state_ids", ())),
            path_event_ids=tuple(payload.get("path_event_ids", ())),
            path_transition_ids=tuple(payload.get("path_transition_ids", ())),
            message=payload.get("message", ""),
            schema_version=payload.get(
                "schema_version", "ui-constraint-counterexample/v1"
            ),
        )


_PROBLEM_FIELDS: Final = frozenset(
    {
        "analysis_classification",
        "application_id",
        "async_effects",
        "backend",
        "check_id",
        "claim_kind",
        "events",
        "initial_state_id",
        "interface",
        "machine_id",
        "premises",
        "problem_id",
        "property_kind",
        "required_action_ids",
        "schema_version",
        "screen_id",
        "source_bindings",
        "states",
        "transitions",
        "unresolved",
    }
)


@dataclass(frozen=True, slots=True)
class UiConstraintProblem:
    """Closed finite UI constraint problem (``UiConstraintProblem@1``)."""

    INTERFACE: ClassVar[str] = UI_CONSTRAINT_PROBLEM_INTERFACE
    SCHEMA_VERSION: ClassVar[str] = UI_CONSTRAINT_PROBLEM_SCHEMA

    problem_id: str
    check_id: str
    property_kind: UiConstraintPropertyKind | str
    application_id: str
    screen_id: str
    machine_id: str
    initial_state_id: str
    states: tuple[UiStateDefinition, ...]
    events: tuple[UiEventDefinition, ...]
    transitions: tuple[UiTransitionDefinition, ...]
    backend: UiConstraintBackend | str = UiConstraintBackend.AUTO
    claim_kind: str = "bounded_ui_invariant"
    analysis_classification: AnalysisClassification | str = AnalysisClassification.EXACT
    async_effects: tuple[UiAsyncEffectPremise, ...] = ()
    required_action_ids: tuple[str, ...] = ()
    premises: Mapping[str, Any] = field(default_factory=dict)
    source_bindings: tuple[UiConstraintSourceBinding, ...] = ()
    unresolved: tuple[str, ...] = ()
    interface: str = UI_CONSTRAINT_PROBLEM_INTERFACE
    schema_version: str = UI_CONSTRAINT_PROBLEM_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(self, "problem_id", _identifier(self.problem_id, "problem_id"))
        object.__setattr__(self, "check_id", _identifier(self.check_id, "check_id"))
        property_kind = _enum(
            self.property_kind, UiConstraintPropertyKind, "property_kind"
        )
        object.__setattr__(self, "property_kind", property_kind)
        object.__setattr__(
            self, "application_id", _identifier(self.application_id, "application_id")
        )
        object.__setattr__(self, "screen_id", _identifier(self.screen_id, "screen_id"))
        object.__setattr__(self, "machine_id", _identifier(self.machine_id, "machine_id"))
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
            raise GuiFormalAdapterError(f"states exceeds bound {_MAX_STATES}")
        if len(events) > _MAX_EVENTS:
            raise GuiFormalAdapterError(f"events exceeds bound {_MAX_EVENTS}")
        if len(transitions) > _MAX_TRANSITIONS:
            raise GuiFormalAdapterError(f"transitions exceeds bound {_MAX_TRANSITIONS}")
        for index, state in enumerate(states):
            if not isinstance(state, UiStateDefinition):
                raise GuiFormalAdapterError(
                    f"states[{index}] must be a UiStateDefinition"
                )
        for index, event in enumerate(events):
            if not isinstance(event, UiEventDefinition):
                raise GuiFormalAdapterError(
                    f"events[{index}] must be a UiEventDefinition"
                )
        for index, transition in enumerate(transitions):
            if not isinstance(transition, UiTransitionDefinition):
                raise GuiFormalAdapterError(
                    f"transitions[{index}] must be a UiTransitionDefinition"
                )
        object.__setattr__(self, "states", states)
        object.__setattr__(self, "events", events)
        object.__setattr__(self, "transitions", transitions)
        object.__setattr__(
            self, "backend", _enum(self.backend, UiConstraintBackend, "backend")
        )
        claim_kind = _text(self.claim_kind, "claim_kind")
        if claim_kind in FORBIDDEN_CLAIM_KINDS:
            raise GuiFormalAdapterError(
                f"claim_kind {claim_kind!r} is forbidden; the adapter never "
                "admits beauty, complete accessibility, complete security, or "
                "unbounded correctness as solver claims"
            )
        object.__setattr__(self, "claim_kind", claim_kind)
        object.__setattr__(
            self,
            "analysis_classification",
            _schema_enum(
                self.analysis_classification,
                AnalysisClassification,
                "analysis_classification",
            ),
        )
        async_effects = tuple(self.async_effects)
        if len(async_effects) > _MAX_ASYNC_EFFECTS:
            raise GuiFormalAdapterError(
                f"async_effects exceeds bound {_MAX_ASYNC_EFFECTS}"
            )
        normalized_effects: list[UiAsyncEffectPremise] = []
        for index, effect in enumerate(async_effects):
            if isinstance(effect, UiAsyncEffectPremise):
                normalized_effects.append(effect)
            else:
                normalized_effects.append(
                    UiAsyncEffectPremise.from_dict(_mapping(effect, f"async_effects[{index}]"))
                )
        object.__setattr__(self, "async_effects", tuple(normalized_effects))
        required = tuple(
            _identifier(item, "required_action_ids item")
            for item in self.required_action_ids
        )
        if len(required) != len(set(required)):
            raise GuiFormalAdapterError("required_action_ids must be unique")
        object.__setattr__(self, "required_action_ids", required)
        premises = dict(self.premises) if self.premises is not None else {}
        if not isinstance(premises, dict):
            raise GuiFormalAdapterError("premises must be a mapping")
        if len(premises) > _MAX_PREMISES:
            raise GuiFormalAdapterError(f"premises exceeds bound {_MAX_PREMISES}")
        # Premises are JSON-closed opaque facts; reject non-JSON scalars later via
        # canonicalization when needed.  Keep a shallow copy for immutability.
        object.__setattr__(self, "premises", dict(premises))
        bindings = tuple(self.source_bindings)
        if len(bindings) > _MAX_SOURCE_BINDINGS:
            raise GuiFormalAdapterError(
                f"source_bindings exceeds bound {_MAX_SOURCE_BINDINGS}"
            )
        normalized_bindings: list[UiConstraintSourceBinding] = []
        for index, binding in enumerate(bindings):
            if isinstance(binding, UiConstraintSourceBinding):
                normalized_bindings.append(binding)
            else:
                normalized_bindings.append(
                    UiConstraintSourceBinding.from_dict(
                        _mapping(binding, f"source_bindings[{index}]")
                    )
                )
        object.__setattr__(self, "source_bindings", tuple(normalized_bindings))
        unresolved = tuple(
            _text(item, "unresolved item") for item in self.unresolved
        )
        if len(unresolved) != len(set(unresolved)):
            raise GuiFormalAdapterError("unresolved must be unique")
        object.__setattr__(self, "unresolved", unresolved)
        if self.interface != UI_CONSTRAINT_PROBLEM_INTERFACE:
            raise GuiFormalAdapterError(
                f"unsupported UiConstraintProblem interface: {self.interface!r}"
            )
        if self.schema_version != UI_CONSTRAINT_PROBLEM_SCHEMA:
            raise GuiFormalAdapterError(
                f"unsupported UiConstraintProblem schema_version: "
                f"{self.schema_version!r}"
            )
        object.__setattr__(self, "interface", UI_CONSTRAINT_PROBLEM_INTERFACE)
        object.__setattr__(self, "schema_version", UI_CONSTRAINT_PROBLEM_SCHEMA)

    def to_dict(self) -> dict[str, Any]:
        return {
            "analysis_classification": self.analysis_classification.value,
            "application_id": self.application_id,
            "async_effects": [item.to_dict() for item in self.async_effects],
            "backend": self.backend.value,
            "check_id": self.check_id,
            "claim_kind": self.claim_kind,
            "events": [item.to_dict() for item in self.events],
            "initial_state_id": self.initial_state_id,
            "interface": self.interface,
            "machine_id": self.machine_id,
            "premises": dict(self.premises),
            "problem_id": self.problem_id,
            "property_kind": self.property_kind.value,
            "required_action_ids": list(self.required_action_ids),
            "schema_version": self.schema_version,
            "screen_id": self.screen_id,
            "source_bindings": [item.to_dict() for item in self.source_bindings],
            "states": [item.to_dict() for item in self.states],
            "transitions": [item.to_dict() for item in self.transitions],
            "unresolved": list(self.unresolved),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any] | Any) -> UiConstraintProblem:
        payload = _mapping(value, "UiConstraintProblem")
        _reject_unknown(payload, _PROBLEM_FIELDS, "UiConstraintProblem")
        states = tuple(
            item
            if isinstance(item, UiStateDefinition)
            else UiStateDefinition.from_dict(item)
            for item in _sequence(payload.get("states", ()), "states")
        )
        events = tuple(
            item
            if isinstance(item, UiEventDefinition)
            else UiEventDefinition.from_dict(item)
            for item in _sequence(payload.get("events", ()), "events")
        )
        transitions = tuple(
            item
            if isinstance(item, UiTransitionDefinition)
            else UiTransitionDefinition.from_dict(item)
            for item in _sequence(payload.get("transitions", ()), "transitions")
        )
        return cls(
            problem_id=payload.get("problem_id", ""),
            check_id=payload.get("check_id", ""),
            property_kind=payload.get("property_kind", ""),
            application_id=payload.get("application_id", ""),
            screen_id=payload.get("screen_id", ""),
            machine_id=payload.get("machine_id", ""),
            initial_state_id=payload.get("initial_state_id", ""),
            states=states,
            events=events,
            transitions=transitions,
            backend=payload.get("backend", UiConstraintBackend.AUTO.value),
            claim_kind=payload.get("claim_kind", "bounded_ui_invariant"),
            analysis_classification=payload.get(
                "analysis_classification", AnalysisClassification.EXACT.value
            ),
            async_effects=tuple(payload.get("async_effects", ())),
            required_action_ids=tuple(payload.get("required_action_ids", ())),
            premises=dict(payload.get("premises", {}) or {}),
            source_bindings=tuple(payload.get("source_bindings", ())),
            unresolved=tuple(payload.get("unresolved", ())),
            interface=payload.get("interface", UI_CONSTRAINT_PROBLEM_INTERFACE),
            schema_version=payload.get(
                "schema_version", UI_CONSTRAINT_PROBLEM_SCHEMA
            ),
        )


_RESULT_FIELDS: Final = frozenset(
    {
        "analysis_classification",
        "backend",
        "bounded",
        "check_id",
        "counterexample",
        "evidence_level",
        "forbidden_claims_rejected",
        "interface",
        "kind",
        "message",
        "problem_id",
        "property_kind",
        "result_id",
        "schema_version",
        "smt_compilation_digest",
        "smtlib",
        "solver_id",
        "source_bindings",
        "status",
        "verification_status",
    }
)


@dataclass(frozen=True, slots=True)
class UiConstraintResult:
    """Typed constraint outcome (``UiConstraintResult@1``).

    A solver or graph result never asserts beauty, complete accessibility,
    complete security, or unbounded correctness.  ``bounded`` is always true
    for conclusive positive outcomes; non-conclusive outcomes keep
    ``forbidden_claims_rejected`` true as an explicit refusal record.
    """

    INTERFACE: ClassVar[str] = UI_CONSTRAINT_RESULT_INTERFACE
    SCHEMA_VERSION: ClassVar[str] = UI_CONSTRAINT_RESULT_SCHEMA

    result_id: str
    problem_id: str
    check_id: str
    property_kind: str
    kind: UiConstraintResultKind | str
    status: ConstraintCheckStatus | str
    backend: UiConstraintBackend | str
    solver_id: str
    evidence_level: EvidenceLevel | str
    analysis_classification: AnalysisClassification | str
    verification_status: VerificationStatus | str
    message: str = ""
    bounded: bool = True
    forbidden_claims_rejected: bool = True
    counterexample: UiConstraintCounterexample | None = None
    smtlib: str = ""
    smt_compilation_digest: str = ""
    source_bindings: tuple[UiConstraintSourceBinding, ...] = ()
    interface: str = UI_CONSTRAINT_RESULT_INTERFACE
    schema_version: str = UI_CONSTRAINT_RESULT_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(self, "result_id", _identifier(self.result_id, "result_id"))
        object.__setattr__(self, "problem_id", _identifier(self.problem_id, "problem_id"))
        object.__setattr__(self, "check_id", _identifier(self.check_id, "check_id"))
        object.__setattr__(
            self, "property_kind", _text(self.property_kind, "property_kind")
        )
        kind = _enum(self.kind, UiConstraintResultKind, "kind")
        object.__setattr__(self, "kind", kind)
        status = _schema_enum(self.status, ConstraintCheckStatus, "status")
        object.__setattr__(self, "status", status)
        backend = _enum(self.backend, UiConstraintBackend, "backend")
        if backend is UiConstraintBackend.AUTO:
            raise GuiFormalAdapterError(
                "UiConstraintResult.backend must resolve to a concrete backend"
            )
        object.__setattr__(self, "backend", backend)
        object.__setattr__(
            self,
            "solver_id",
            _text(self.solver_id, "solver_id", allow_empty=True),
        )
        object.__setattr__(
            self,
            "evidence_level",
            _schema_enum(self.evidence_level, EvidenceLevel, "evidence_level"),
        )
        object.__setattr__(
            self,
            "analysis_classification",
            _schema_enum(
                self.analysis_classification,
                AnalysisClassification,
                "analysis_classification",
            ),
        )
        object.__setattr__(
            self,
            "verification_status",
            _schema_enum(
                self.verification_status, VerificationStatus, "verification_status"
            ),
        )
        object.__setattr__(
            self, "message", _text(self.message, "message", allow_empty=True)
        )
        object.__setattr__(self, "bounded", _bool(self.bounded, "bounded"))
        object.__setattr__(
            self,
            "forbidden_claims_rejected",
            _bool(self.forbidden_claims_rejected, "forbidden_claims_rejected"),
        )
        if not self.forbidden_claims_rejected:
            raise GuiFormalAdapterError(
                "UiConstraintResult must keep forbidden_claims_rejected=true"
            )
        if kind is UiConstraintResultKind.PROVED_BOUNDED_PROPERTY:
            if not self.bounded:
                raise GuiFormalAdapterError(
                    "proved_bounded_property requires bounded=true"
                )
            if status is not ConstraintCheckStatus.SATISFIED:
                raise GuiFormalAdapterError(
                    "proved_bounded_property requires status=satisfied"
                )
            if self.property_kind in FORBIDDEN_CLAIM_KINDS:
                raise GuiFormalAdapterError(
                    "proved results must not use forbidden property kinds"
                )
            if self.verification_status is VerificationStatus.VERIFIED and (
                self.evidence_level is EvidenceLevel.HEURISTIC
            ):
                raise GuiFormalAdapterError(
                    "heuristic evidence cannot yield verification_status=verified"
                )
        if kind is UiConstraintResultKind.COUNTEREXAMPLE:
            if self.counterexample is None:
                raise GuiFormalAdapterError(
                    "counterexample results require a counterexample witness"
                )
            if status is not ConstraintCheckStatus.VIOLATED:
                raise GuiFormalAdapterError(
                    "counterexample results require status=violated"
                )
        if kind is UiConstraintResultKind.UNAVAILABLE:
            if status not in {
                ConstraintCheckStatus.UNSUPPORTED,
                ConstraintCheckStatus.ERROR,
                ConstraintCheckStatus.INCONCLUSIVE,
            }:
                raise GuiFormalAdapterError(
                    "unavailable results require unsupported/error/inconclusive status"
                )
        if kind is UiConstraintResultKind.UNKNOWN:
            if status not in {
                ConstraintCheckStatus.INCONCLUSIVE,
                ConstraintCheckStatus.UNSUPPORTED,
                ConstraintCheckStatus.SKIPPED,
                ConstraintCheckStatus.ERROR,
            }:
                raise GuiFormalAdapterError(
                    "unknown results require inconclusive/unsupported/skipped/error status"
                )
        if self.counterexample is not None and not isinstance(
            self.counterexample, UiConstraintCounterexample
        ):
            raise GuiFormalAdapterError(
                "counterexample must be a UiConstraintCounterexample or None"
            )
        object.__setattr__(
            self, "smtlib", _text(self.smtlib, "smtlib", allow_empty=True)
        )
        object.__setattr__(
            self,
            "smt_compilation_digest",
            _text(
                self.smt_compilation_digest,
                "smt_compilation_digest",
                allow_empty=True,
            ),
        )
        bindings = tuple(self.source_bindings)
        normalized: list[UiConstraintSourceBinding] = []
        for index, binding in enumerate(bindings):
            if isinstance(binding, UiConstraintSourceBinding):
                normalized.append(binding)
            else:
                normalized.append(
                    UiConstraintSourceBinding.from_dict(
                        _mapping(binding, f"source_bindings[{index}]")
                    )
                )
        object.__setattr__(self, "source_bindings", tuple(normalized))
        if self.interface != UI_CONSTRAINT_RESULT_INTERFACE:
            raise GuiFormalAdapterError(
                f"unsupported UiConstraintResult interface: {self.interface!r}"
            )
        if self.schema_version != UI_CONSTRAINT_RESULT_SCHEMA:
            raise GuiFormalAdapterError(
                f"unsupported UiConstraintResult schema_version: "
                f"{self.schema_version!r}"
            )
        object.__setattr__(self, "interface", UI_CONSTRAINT_RESULT_INTERFACE)
        object.__setattr__(self, "schema_version", UI_CONSTRAINT_RESULT_SCHEMA)

    def to_dict(self) -> dict[str, Any]:
        return {
            "analysis_classification": self.analysis_classification.value,
            "backend": self.backend.value,
            "bounded": self.bounded,
            "check_id": self.check_id,
            "counterexample": (
                None if self.counterexample is None else self.counterexample.to_dict()
            ),
            "evidence_level": self.evidence_level.value,
            "forbidden_claims_rejected": self.forbidden_claims_rejected,
            "interface": self.interface,
            "kind": self.kind.value,
            "message": self.message,
            "problem_id": self.problem_id,
            "property_kind": self.property_kind,
            "result_id": self.result_id,
            "schema_version": self.schema_version,
            "smt_compilation_digest": self.smt_compilation_digest,
            "smtlib": self.smtlib,
            "solver_id": self.solver_id,
            "source_bindings": [item.to_dict() for item in self.source_bindings],
            "status": self.status.value,
            "verification_status": self.verification_status.value,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any] | Any) -> UiConstraintResult:
        payload = _mapping(value, "UiConstraintResult")
        _reject_unknown(payload, _RESULT_FIELDS, "UiConstraintResult")
        counter_raw = payload.get("counterexample")
        counter: UiConstraintCounterexample | None
        if counter_raw is None:
            counter = None
        elif isinstance(counter_raw, UiConstraintCounterexample):
            counter = counter_raw
        else:
            counter = UiConstraintCounterexample.from_dict(
                _mapping(counter_raw, "counterexample")
            )
        return cls(
            result_id=payload.get("result_id", ""),
            problem_id=payload.get("problem_id", ""),
            check_id=payload.get("check_id", ""),
            property_kind=payload.get("property_kind", ""),
            kind=payload.get("kind", ""),
            status=payload.get("status", ""),
            backend=payload.get("backend", ""),
            solver_id=payload.get("solver_id", ""),
            evidence_level=payload.get("evidence_level", ""),
            analysis_classification=payload.get("analysis_classification", ""),
            verification_status=payload.get("verification_status", ""),
            message=payload.get("message", ""),
            bounded=payload.get("bounded", True),
            forbidden_claims_rejected=payload.get("forbidden_claims_rejected", True),
            counterexample=counter,
            smtlib=payload.get("smtlib", ""),
            smt_compilation_digest=payload.get("smt_compilation_digest", ""),
            source_bindings=tuple(payload.get("source_bindings", ())),
            interface=payload.get("interface", UI_CONSTRAINT_RESULT_INTERFACE),
            schema_version=payload.get(
                "schema_version", UI_CONSTRAINT_RESULT_SCHEMA
            ),
        )


# ---------------------------------------------------------------------------
# Finite graph engine
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _GraphIndex:
    states_by_id: Mapping[str, UiStateDefinition]
    events_by_id: Mapping[str, UiEventDefinition]
    transitions: tuple[UiTransitionDefinition, ...]
    outgoing: Mapping[str, tuple[UiTransitionDefinition, ...]]
    reachable: frozenset[str]
    initial_state_id: str


def _index_graph(problem: UiConstraintProblem) -> _GraphIndex:
    states_by_id: dict[str, UiStateDefinition] = {}
    for state in problem.states:
        if state.state_id in states_by_id:
            # Duplicates are reported by the no_duplicate_state_ids check; keep first.
            continue
        states_by_id[state.state_id] = state
    events_by_id: dict[str, UiEventDefinition] = {}
    for event in problem.events:
        if event.event_id not in events_by_id:
            events_by_id[event.event_id] = event
    outgoing: dict[str, list[UiTransitionDefinition]] = {
        state_id: [] for state_id in states_by_id
    }
    for transition in problem.transitions:
        outgoing.setdefault(transition.from_state_id, []).append(transition)
    frozen_outgoing = {
        key: tuple(value) for key, value in sorted(outgoing.items())
    }
    initial = problem.initial_state_id
    reachable: set[str] = set()
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
        transitions=problem.transitions,
        outgoing=frozen_outgoing,
        reachable=frozenset(reachable),
        initial_state_id=initial,
    )


@dataclass(frozen=True, slots=True)
class _GraphCheckOutcome:
    ok: bool
    unknown: bool
    message: str
    counterexample: UiConstraintCounterexample | None = None
    structural_only: bool = True


def _check_defined_transition_targets(
    problem: UiConstraintProblem, graph: _GraphIndex
) -> _GraphCheckOutcome:
    for transition in graph.transitions:
        if transition.from_state_id not in graph.states_by_id:
            return _GraphCheckOutcome(
                ok=False,
                unknown=False,
                message=(
                    f"transition {transition.transition_id} references undefined "
                    f"source state {transition.from_state_id}"
                ),
                counterexample=UiConstraintCounterexample(
                    counterexample_id=_digest_id(
                        "cex",
                        {
                            "t": transition.transition_id,
                            "p": "defined_transition_targets",
                        },
                    ),
                    property_kind="defined_transition_targets",
                    subject_ids=(transition.transition_id, transition.from_state_id),
                    path_transition_ids=(transition.transition_id,),
                    message="undefined transition source",
                ),
            )
        if transition.to_state_id not in graph.states_by_id:
            return _GraphCheckOutcome(
                ok=False,
                unknown=False,
                message=(
                    f"transition {transition.transition_id} targets undefined "
                    f"state {transition.to_state_id}"
                ),
                counterexample=UiConstraintCounterexample(
                    counterexample_id=_digest_id(
                        "cex",
                        {
                            "t": transition.transition_id,
                            "p": "defined_transition_targets",
                        },
                    ),
                    property_kind="defined_transition_targets",
                    subject_ids=(transition.transition_id, transition.to_state_id),
                    path_transition_ids=(transition.transition_id,),
                    path_state_ids=(transition.from_state_id,),
                    path_event_ids=(transition.event_id,),
                    message="undefined transition destination",
                ),
            )
        if transition.event_id not in graph.events_by_id:
            return _GraphCheckOutcome(
                ok=False,
                unknown=False,
                message=(
                    f"transition {transition.transition_id} references undefined "
                    f"event {transition.event_id}"
                ),
                counterexample=UiConstraintCounterexample(
                    counterexample_id=_digest_id(
                        "cex",
                        {
                            "t": transition.transition_id,
                            "p": "defined_transition_targets",
                        },
                    ),
                    property_kind="defined_transition_targets",
                    subject_ids=(transition.transition_id, transition.event_id),
                    path_transition_ids=(transition.transition_id,),
                    message="undefined transition event",
                ),
            )
    return _GraphCheckOutcome(
        ok=True,
        unknown=False,
        message="all transitions reference defined states and events",
    )


def _check_failure_recovery(
    problem: UiConstraintProblem, graph: _GraphIndex
) -> _GraphCheckOutcome:
    for state in graph.states_by_id.values():
        if state.kind is not UiStateKind.FAILURE or state.is_terminal:
            continue
        if state.state_id not in graph.reachable and graph.reachable:
            # Unreachable nonterminal failures are not required to recover.
            continue
        has_recovery = False
        for transition in graph.outgoing.get(state.state_id, ()):
            destination = graph.states_by_id.get(transition.to_state_id)
            if destination is None:
                continue
            if destination.kind is UiStateKind.RECOVERY or destination.is_terminal:
                has_recovery = True
                break
        if not has_recovery:
            return _GraphCheckOutcome(
                ok=False,
                unknown=False,
                message=(
                    f"nonterminal failure state {state.state_id} lacks recovery "
                    "or terminal explanation"
                ),
                counterexample=UiConstraintCounterexample(
                    counterexample_id=_digest_id(
                        "cex", {"s": state.state_id, "p": "failure_recovery"}
                    ),
                    property_kind="failure_recovery",
                    subject_ids=(state.state_id,),
                    path_state_ids=(state.state_id,),
                    message="failure without recovery",
                ),
            )
    return _GraphCheckOutcome(
        ok=True,
        unknown=False,
        message="reachable nonterminal failures have recovery or terminal paths",
    )


def _check_async_effect_completeness(
    problem: UiConstraintProblem, graph: _GraphIndex
) -> _GraphCheckOutcome:
    if not problem.async_effects:
        return _GraphCheckOutcome(
            ok=False,
            unknown=True,
            message=(
                "async_effect_completeness requires explicit async_effects premises"
            ),
        )
    for effect in problem.async_effects:
        if not effect.complete:
            return _GraphCheckOutcome(
                ok=False,
                unknown=False,
                message=(
                    f"async effect {effect.effect_id} lacks observed "
                    "loading/success/failure facts"
                ),
                counterexample=UiConstraintCounterexample(
                    counterexample_id=_digest_id(
                        "cex",
                        {"e": effect.effect_id, "p": "async_effect_completeness"},
                    ),
                    property_kind="async_effect_completeness",
                    subject_ids=(effect.effect_id,),
                    message="incomplete async effect",
                ),
            )
    return _GraphCheckOutcome(
        ok=True,
        unknown=False,
        message="all declared async effects expose loading/success/failure",
    )


def _check_event_outcome_coverage(
    problem: UiConstraintProblem, graph: _GraphIndex
) -> _GraphCheckOutcome:
    """Every event that appears on a reachable state must have an outcome or noop.

    Declared events with no transitions anywhere remain unknown rather than
    invented no-ops.
    """

    events_with_outcomes = {
        transition.event_id for transition in graph.transitions
    }
    declared_events = set(graph.events_by_id)
    floating = sorted(declared_events - events_with_outcomes)
    if floating:
        return _GraphCheckOutcome(
            ok=False,
            unknown=True,
            message=(
                "declared events without outcomes remain unknown "
                f"(not treated as no-ops): {', '.join(floating)}"
            ),
        )
    # Reachable states: every non-noop transition from them is already an outcome.
    # Explicit no-ops count as defined outcomes.
    return _GraphCheckOutcome(
        ok=True,
        unknown=False,
        message="every declared event has at least one explicit outcome or no-op",
    )


def _check_reachable_required_action(
    problem: UiConstraintProblem, graph: _GraphIndex
) -> _GraphCheckOutcome:
    if not problem.required_action_ids:
        return _GraphCheckOutcome(
            ok=False,
            unknown=True,
            message="reachable_required_action requires required_action_ids premises",
        )
    action_states = problem.premises.get("action_state_ids")
    if not isinstance(action_states, Mapping):
        return _GraphCheckOutcome(
            ok=False,
            unknown=True,
            message=(
                "reachable_required_action requires premises.action_state_ids "
                "mapping action_id -> state_id"
            ),
        )
    for action_id in problem.required_action_ids:
        state_id = action_states.get(action_id)
        if not isinstance(state_id, str) or not state_id:
            return _GraphCheckOutcome(
                ok=False,
                unknown=True,
                message=f"missing action_state_ids entry for {action_id}",
            )
        if state_id not in graph.states_by_id:
            return _GraphCheckOutcome(
                ok=False,
                unknown=False,
                message=f"required action {action_id} bound to undefined state {state_id}",
                counterexample=UiConstraintCounterexample(
                    counterexample_id=_digest_id(
                        "cex", {"a": action_id, "p": "reachable_required_action"}
                    ),
                    property_kind="reachable_required_action",
                    subject_ids=(action_id, state_id),
                    message="required action bound to undefined state",
                ),
            )
        if state_id not in graph.reachable:
            return _GraphCheckOutcome(
                ok=False,
                unknown=False,
                message=(
                    f"required action {action_id} is only available in "
                    f"unreachable state {state_id}"
                ),
                counterexample=UiConstraintCounterexample(
                    counterexample_id=_digest_id(
                        "cex", {"a": action_id, "p": "reachable_required_action"}
                    ),
                    property_kind="reachable_required_action",
                    subject_ids=(action_id, state_id),
                    path_state_ids=(state_id,),
                    message="required action unreachable",
                ),
            )
    return _GraphCheckOutcome(
        ok=True,
        unknown=False,
        message="required actions are bound to reachable states",
    )


def _check_single_initial_state(
    problem: UiConstraintProblem, graph: _GraphIndex
) -> _GraphCheckOutcome:
    initials = [state for state in graph.states_by_id.values() if state.is_initial]
    if len(initials) == 1:
        if problem.initial_state_id and problem.initial_state_id != initials[0].state_id:
            return _GraphCheckOutcome(
                ok=False,
                unknown=False,
                message=(
                    f"initial_state_id {problem.initial_state_id} disagrees with "
                    f"marked initial {initials[0].state_id}"
                ),
                counterexample=UiConstraintCounterexample(
                    counterexample_id=_digest_id(
                        "cex", {"p": "single_initial_state"}
                    ),
                    property_kind="single_initial_state",
                    subject_ids=(problem.initial_state_id, initials[0].state_id),
                    message="initial state disagreement",
                ),
            )
        return _GraphCheckOutcome(
            ok=True,
            unknown=False,
            message="exactly one initial state",
        )
    if len(initials) == 0:
        return _GraphCheckOutcome(
            ok=False,
            unknown=True,
            message="no explicit initial state; cannot prove single_initial_state",
        )
    return _GraphCheckOutcome(
        ok=False,
        unknown=False,
        message=(
            "multiple initial states: "
            + ", ".join(sorted(state.state_id for state in initials))
        ),
        counterexample=UiConstraintCounterexample(
            counterexample_id=_digest_id("cex", {"p": "single_initial_state"}),
            property_kind="single_initial_state",
            subject_ids=tuple(sorted(state.state_id for state in initials)),
            message="multiple initial states",
        ),
    )


def _check_no_duplicate_state_ids(
    problem: UiConstraintProblem, graph: _GraphIndex
) -> _GraphCheckOutcome:
    seen: set[str] = set()
    for state in problem.states:
        if state.state_id in seen:
            return _GraphCheckOutcome(
                ok=False,
                unknown=False,
                message=f"duplicate state_id {state.state_id}",
                counterexample=UiConstraintCounterexample(
                    counterexample_id=_digest_id(
                        "cex", {"s": state.state_id, "p": "no_duplicate_state_ids"}
                    ),
                    property_kind="no_duplicate_state_ids",
                    subject_ids=(state.state_id,),
                    message="duplicate state id",
                ),
            )
        seen.add(state.state_id)
    return _GraphCheckOutcome(
        ok=True,
        unknown=False,
        message="state identifiers are unique",
    )


def _check_confirmation_bound_action(
    problem: UiConstraintProblem, graph: _GraphIndex
) -> _GraphCheckOutcome:
    destructive = problem.premises.get("destructive_action_ids")
    confirmations = problem.premises.get("confirmation_by_action")
    if not isinstance(destructive, Sequence) or isinstance(
        destructive, (str, bytes, bytearray)
    ):
        return _GraphCheckOutcome(
            ok=False,
            unknown=True,
            message=(
                "confirmation_bound_action requires premises.destructive_action_ids"
            ),
        )
    if not isinstance(confirmations, Mapping):
        return _GraphCheckOutcome(
            ok=False,
            unknown=True,
            message=(
                "confirmation_bound_action requires premises.confirmation_by_action"
            ),
        )
    for action_id in destructive:
        if not isinstance(action_id, str) or not action_id:
            return _GraphCheckOutcome(
                ok=False,
                unknown=True,
                message="destructive_action_ids entries must be non-empty strings",
            )
        confirmation_id = confirmations.get(action_id)
        if not isinstance(confirmation_id, str) or not confirmation_id:
            return _GraphCheckOutcome(
                ok=False,
                unknown=False,
                message=(
                    f"destructive action {action_id} lacks bound confirmation_id"
                ),
                counterexample=UiConstraintCounterexample(
                    counterexample_id=_digest_id(
                        "cex", {"a": action_id, "p": "confirmation_bound_action"}
                    ),
                    property_kind="confirmation_bound_action",
                    subject_ids=(action_id,),
                    message="destructive action without confirmation",
                ),
            )
    return _GraphCheckOutcome(
        ok=True,
        unknown=False,
        message="destructive actions bind exact confirmation identifiers",
    )


def _check_form_accessible_names(
    problem: UiConstraintProblem, graph: _GraphIndex
) -> _GraphCheckOutcome:
    inputs = problem.premises.get("form_inputs")
    if not isinstance(inputs, Sequence) or isinstance(inputs, (str, bytes, bytearray)):
        return _GraphCheckOutcome(
            ok=False,
            unknown=True,
            message="form_accessible_names requires premises.form_inputs sequence",
        )
    if not inputs:
        return _GraphCheckOutcome(
            ok=False,
            unknown=True,
            message="form_accessible_names has no form_inputs premises",
        )
    for index, item in enumerate(inputs):
        if not isinstance(item, Mapping):
            return _GraphCheckOutcome(
                ok=False,
                unknown=True,
                message=f"form_inputs[{index}] must be a mapping",
            )
        input_id = item.get("input_id")
        accessible_name = item.get("accessible_name")
        if not isinstance(input_id, str) or not input_id:
            return _GraphCheckOutcome(
                ok=False,
                unknown=True,
                message=f"form_inputs[{index}].input_id missing",
            )
        if not isinstance(accessible_name, str) or not accessible_name.strip():
            return _GraphCheckOutcome(
                ok=False,
                unknown=False,
                message=f"input {input_id} lacks accessible_name",
                counterexample=UiConstraintCounterexample(
                    counterexample_id=_digest_id(
                        "cex", {"i": input_id, "p": "form_accessible_names"}
                    ),
                    property_kind="form_accessible_names",
                    subject_ids=(input_id,),
                    message="missing accessible name",
                ),
            )
    return _GraphCheckOutcome(
        ok=True,
        unknown=False,
        message=(
            "declared form inputs expose accessible names "
            "(bounded structural check; not complete accessibility)"
        ),
    )


def _check_modal_focus_lifecycle(
    problem: UiConstraintProblem, graph: _GraphIndex
) -> _GraphCheckOutcome:
    lifecycle = problem.premises.get("modal_focus")
    if not isinstance(lifecycle, Mapping):
        return _GraphCheckOutcome(
            ok=False,
            unknown=True,
            message="modal_focus_lifecycle requires premises.modal_focus mapping",
        )
    required_flags = (
        "opens_moves_focus_inside",
        "tab_contained",
        "escape_or_cancel_defined",
        "close_restores_focus",
        "hidden_not_focusable",
    )
    missing = [flag for flag in required_flags if flag not in lifecycle]
    if missing:
        return _GraphCheckOutcome(
            ok=False,
            unknown=True,
            message=f"modal_focus missing flags: {', '.join(missing)}",
        )
    for flag in required_flags:
        value = lifecycle[flag]
        if not isinstance(value, bool):
            return _GraphCheckOutcome(
                ok=False,
                unknown=True,
                message=f"modal_focus.{flag} must be a boolean observation",
            )
        if value is False:
            return _GraphCheckOutcome(
                ok=False,
                unknown=False,
                message=f"modal focus obligation failed: {flag}",
                counterexample=UiConstraintCounterexample(
                    counterexample_id=_digest_id(
                        "cex", {"f": flag, "p": "modal_focus_lifecycle"}
                    ),
                    property_kind="modal_focus_lifecycle",
                    subject_ids=(flag,),
                    message=f"modal focus flag false: {flag}",
                ),
            )
    return _GraphCheckOutcome(
        ok=True,
        unknown=False,
        message=(
            "declared modal focus lifecycle obligations hold "
            "(bounded structural check; not complete accessibility)"
        ),
    )


def _check_policy_not_browser_authoritative(
    problem: UiConstraintProblem, graph: _GraphIndex
) -> _GraphCheckOutcome:
    policy = problem.premises.get("policy")
    if not isinstance(policy, Mapping):
        return _GraphCheckOutcome(
            ok=False,
            unknown=True,
            message=(
                "policy_not_browser_authoritative requires premises.policy mapping"
            ),
        )
    browser_authoritative = policy.get("browser_policy_authoritative")
    if not isinstance(browser_authoritative, bool):
        return _GraphCheckOutcome(
            ok=False,
            unknown=True,
            message="policy.browser_policy_authoritative must be a boolean",
        )
    if browser_authoritative:
        return _GraphCheckOutcome(
            ok=False,
            unknown=False,
            message="browser policy output must not be authoritative",
            counterexample=UiConstraintCounterexample(
                counterexample_id=_digest_id(
                    "cex", {"p": "policy_not_browser_authoritative"}
                ),
                property_kind="policy_not_browser_authoritative",
                subject_ids=("policy:browser",),
                message="browser policy treated as authoritative",
            ),
        )
    host_authoritative = policy.get("host_authorization_authoritative")
    if host_authoritative is False:
        return _GraphCheckOutcome(
            ok=False,
            unknown=False,
            message="host authorization must remain authoritative for policy checks",
            counterexample=UiConstraintCounterexample(
                counterexample_id=_digest_id(
                    "cex", {"p": "policy_not_browser_authoritative"}
                ),
                property_kind="policy_not_browser_authoritative",
                subject_ids=("policy:host",),
                message="host authorization not authoritative",
            ),
        )
    return _GraphCheckOutcome(
        ok=True,
        unknown=False,
        message=(
            "browser policy is non-authoritative under declared premises "
            "(not a complete security proof)"
        ),
    )


_GRAPH_CHECKERS: Final[
    dict[UiConstraintPropertyKind, Callable[[UiConstraintProblem, _GraphIndex], _GraphCheckOutcome]]
] = {
    UiConstraintPropertyKind.DEFINED_TRANSITION_TARGETS: _check_defined_transition_targets,
    UiConstraintPropertyKind.FAILURE_RECOVERY: _check_failure_recovery,
    UiConstraintPropertyKind.ASYNC_EFFECT_COMPLETENESS: _check_async_effect_completeness,
    UiConstraintPropertyKind.EVENT_OUTCOME_COVERAGE: _check_event_outcome_coverage,
    UiConstraintPropertyKind.REACHABLE_REQUIRED_ACTION: _check_reachable_required_action,
    UiConstraintPropertyKind.SINGLE_INITIAL_STATE: _check_single_initial_state,
    UiConstraintPropertyKind.NO_DUPLICATE_STATE_IDS: _check_no_duplicate_state_ids,
    UiConstraintPropertyKind.CONFIRMATION_BOUND_ACTION: _check_confirmation_bound_action,
    UiConstraintPropertyKind.FORM_ACCESSIBLE_NAMES: _check_form_accessible_names,
    UiConstraintPropertyKind.MODAL_FOCUS_LIFECYCLE: _check_modal_focus_lifecycle,
    UiConstraintPropertyKind.POLICY_NOT_BROWSER_AUTHORITATIVE: (
        _check_policy_not_browser_authoritative
    ),
}


# ---------------------------------------------------------------------------
# SMT / cvc5 boundary
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Cvc5Capability:
    """Result of a fail-closed cvc5 capability probe."""

    available: bool
    executable: str = ""
    version: str = ""
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "executable": self.executable,
            "reason": self.reason,
            "version": self.version,
        }


def probe_cvc5(
    *,
    which: Callable[[str], str | None] | None = None,
    version_runner: Callable[[str], str] | None = None,
) -> Cvc5Capability:
    """Probe cvc5 availability without claiming usability on a failed probe.

    The authoritative validation environment uses a sealed PATH; callers may
    inject ``which`` / ``version_runner`` only for tests.  A missing binary is
    reported as unavailable, never silently treated as a successful backend.
    """

    lookup = which or shutil.which
    executable = lookup("cvc5")
    if not executable:
        return Cvc5Capability(
            available=False,
            reason="cvc5 executable not found on PATH",
        )
    version = ""
    if version_runner is not None:
        try:
            version = version_runner(executable).strip()
        except Exception as error:  # noqa: BLE001 - probe must fail closed
            return Cvc5Capability(
                available=False,
                executable=executable,
                reason=f"cvc5 version probe failed: {error}",
            )
    return Cvc5Capability(available=True, executable=executable, version=version)


def _compile_cvc5_vector(problem: UiConstraintProblem) -> tuple[str, str]:
    """Emit a cvc5-compatible SMT-LIB vector for a finite UI graph property.

    Compilation uses the shared semantic SMT compiler.  It does not execute
    the solver and does not cache proofs.

    The vector is a bounded verification condition over the finite declared
    state/transition set: each transition contributes a named Boolean that is
    true exactly when its endpoints and event are declared.  The goal is the
    conjunction of those facts.  Under theorem-by-negation, ``unsat`` means
    every finite endpoint is declared; ``sat`` means at least one is not.
    """

    from ipfs_datasets_py.logic.backends.smt.compiler import (
        BOOL_SORT,
        SmtFeature,
        SmtFunDecl,
        SmtNamedAssertion,
        SmtObligation,
        SmtQueryMode,
        SoftwareVerificationSMTCompiler,
        smt_sanitize,
        term_and,
        term_eq,
        term_symbol,
        term_true,
        term_false,
    )

    known_states = {state.state_id for state in problem.states}
    known_events = {event.event_id for event in problem.events}

    # One Boolean const per transition: true iff endpoints/events are declared.
    transition_consts: list[SmtFunDecl] = []
    assumptions: list[SmtNamedAssertion] = []
    goal_parts = []
    for index, transition in enumerate(problem.transitions):
        name = smt_sanitize(transition.transition_id, prefix=f"tr{index}")
        transition_consts.append(
            SmtFunDecl(name=name, range=BOOL_SORT, is_const=True)
        )
        well_defined = (
            transition.from_state_id in known_states
            and transition.to_state_id in known_states
            and transition.event_id in known_events
        )
        # Pin the const to the finite-graph ground truth for this transition.
        assumptions.append(
            SmtNamedAssertion(
                formula=term_eq(
                    term_symbol(name),
                    term_true() if well_defined else term_false(),
                ),
                name=f"bind_{name}",
            )
        )
        goal_parts.append(term_symbol(name))

    if not goal_parts:
        # Empty transition set: the vacuous bounded property holds.
        goal_parts.append(term_true())

    goal = term_and(*goal_parts) if len(goal_parts) > 1 else goal_parts[0]
    obligation = SmtObligation(
        obligation_id=smt_sanitize(problem.problem_id, prefix="obl"),
        query_mode=SmtQueryMode.THEOREM_BY_NEGATION,
        features=(
            SmtFeature.STATE_TRANSITIONS,
            SmtFeature.EQUALITY,
            SmtFeature.VERIFICATION_CONDITIONS,
        ),
        goal=goal,
        assumptions=tuple(assumptions),
        functions=tuple(transition_consts),
        request_unsat_core=True,
        property_ids=(f"property:{problem.property_kind.value}",),
        attributes={
            "application_id": problem.application_id,
            "screen_id": problem.screen_id,
            "machine_id": problem.machine_id,
            "claim_kind": problem.claim_kind,
            "bounded": True,
            "forbidden_claims": sorted(FORBIDDEN_CLAIM_KINDS),
            "encoding": "finite-transition-endpoint-membership",
        },
    )
    compilation = SoftwareVerificationSMTCompiler().compile(obligation)
    # Result fields require trimmed text; SmtScript.source ends with "\n".
    smtlib = compilation.smtlib.strip()
    digest = f"sha256:{_sha256_hex(smtlib.encode('utf-8'))}"
    return smtlib, digest


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------


class GuiFormalAdapter:
    """``GuiFormalAdapter@1`` — bounded UI constraint translation and checking.

    The adapter never:

    * caches proofs;
    * elevates structural graph results into aesthetic or complete-security
      claims;
    * invents missing transitions, confirmations, or accessible names;
    * treats browser policy as host authorization authority.
    """

    INTERFACE: ClassVar[str] = GUI_FORMAL_ADAPTER_INTERFACE
    SCHEMA_VERSION: ClassVar[str] = GUI_FORMAL_ADAPTER_SCHEMA
    VERSION: ClassVar[str] = GUI_FORMAL_ADAPTER_VERSION

    def __init__(
        self,
        *,
        cvc5_probe: Callable[[], Cvc5Capability] | None = None,
        smt_runner: Callable[[str], str] | None = None,
    ) -> None:
        self._cvc5_probe = cvc5_probe or probe_cvc5
        # Optional pure function: SMT-LIB script -> solver stdout ("sat"/"unsat"/...).
        # When None, cvc5 is never executed — only probed and compiled.
        self._smt_runner = smt_runner

    def probe_solver(self) -> Cvc5Capability:
        return self._cvc5_probe()

    def build_problem(
        self,
        *,
        problem_id: str,
        check_id: str,
        property_kind: UiConstraintPropertyKind | str,
        application_id: str,
        screen_id: str,
        machine_id: str,
        initial_state_id: str,
        states: Sequence[UiStateDefinition | Mapping[str, Any]],
        events: Sequence[UiEventDefinition | Mapping[str, Any]],
        transitions: Sequence[UiTransitionDefinition | Mapping[str, Any]],
        backend: UiConstraintBackend | str = UiConstraintBackend.AUTO,
        claim_kind: str = "bounded_ui_invariant",
        analysis_classification: AnalysisClassification | str = AnalysisClassification.EXACT,
        async_effects: Sequence[UiAsyncEffectPremise | Mapping[str, Any]] = (),
        required_action_ids: Sequence[str] = (),
        premises: Mapping[str, Any] | None = None,
        source_bindings: Sequence[UiConstraintSourceBinding | Mapping[str, Any]] = (),
        unresolved: Sequence[str] = (),
    ) -> UiConstraintProblem:
        decoded_states = tuple(
            item
            if isinstance(item, UiStateDefinition)
            else UiStateDefinition.from_dict(item)
            for item in states
        )
        decoded_events = tuple(
            item
            if isinstance(item, UiEventDefinition)
            else UiEventDefinition.from_dict(item)
            for item in events
        )
        decoded_transitions = tuple(
            item
            if isinstance(item, UiTransitionDefinition)
            else UiTransitionDefinition.from_dict(item)
            for item in transitions
        )
        return UiConstraintProblem(
            problem_id=problem_id,
            check_id=check_id,
            property_kind=property_kind,
            application_id=application_id,
            screen_id=screen_id,
            machine_id=machine_id,
            initial_state_id=initial_state_id,
            states=decoded_states,
            events=decoded_events,
            transitions=decoded_transitions,
            backend=backend,
            claim_kind=claim_kind,
            analysis_classification=analysis_classification,
            async_effects=tuple(async_effects),
            required_action_ids=tuple(required_action_ids),
            premises=dict(premises or {}),
            source_bindings=tuple(source_bindings),
            unresolved=tuple(unresolved),
        )

    def compile_cvc5_vector(self, problem: UiConstraintProblem) -> dict[str, str]:
        """Return a cvc5-compatible SMT-LIB vector without executing the solver."""

        if not isinstance(problem, UiConstraintProblem):
            raise GuiFormalAdapterError("problem must be a UiConstraintProblem")
        smtlib, digest = _compile_cvc5_vector(problem)
        return {
            "smtlib": smtlib,
            "smt_compilation_digest": digest,
            "solver_id": ADAPTER_SOLVER_ID_CVC5,
            "query_mode": "theorem_by_negation",
            "bounded": "true",
        }

    def solve(self, problem: UiConstraintProblem | Mapping[str, Any]) -> UiConstraintResult:
        """Solve one constraint problem with typed fail-closed outcomes."""

        if not isinstance(problem, UiConstraintProblem):
            problem = UiConstraintProblem.from_dict(_mapping(problem, "problem"))
        if problem.claim_kind in FORBIDDEN_CLAIM_KINDS:
            raise GuiFormalAdapterError(
                f"refusing forbidden claim_kind {problem.claim_kind!r}"
            )
        if problem.property_kind.value in FORBIDDEN_CLAIM_KINDS:
            return self._result(
                problem,
                kind=UiConstraintResultKind.UNKNOWN,
                status=ConstraintCheckStatus.UNSUPPORTED,
                backend=UiConstraintBackend.FINITE_GRAPH,
                solver_id=ADAPTER_SOLVER_ID_NONE,
                evidence_level=EvidenceLevel.STRUCTURAL,
                verification_status=VerificationStatus.UNVERIFIED,
                message=(
                    f"property_kind {problem.property_kind.value!r} is forbidden "
                    "and cannot be proved"
                ),
                bounded=True,
            )
        if problem.unresolved and problem.analysis_classification in {
            AnalysisClassification.OPAQUE,
            AnalysisClassification.HEURISTIC,
        }:
            return self._result(
                problem,
                kind=UiConstraintResultKind.UNKNOWN,
                status=ConstraintCheckStatus.INCONCLUSIVE,
                backend=UiConstraintBackend.FINITE_GRAPH,
                solver_id=ADAPTER_SOLVER_ID_FINITE_GRAPH,
                evidence_level=EvidenceLevel.HEURISTIC,
                verification_status=VerificationStatus.UNVERIFIED,
                message=(
                    "opaque/heuristic unresolved premises prevent a bounded proof: "
                    + ", ".join(problem.unresolved)
                ),
                bounded=True,
            )

        backend = problem.backend
        if backend is UiConstraintBackend.AUTO:
            # Prefer exact finite graph; SMT is opt-in via backend=cvc5_smt.
            backend = UiConstraintBackend.FINITE_GRAPH

        if backend is UiConstraintBackend.CVC5_SMT:
            return self._solve_cvc5(problem)
        return self._solve_graph(problem)

    def _solve_graph(self, problem: UiConstraintProblem) -> UiConstraintResult:
        checker = _GRAPH_CHECKERS.get(problem.property_kind)
        if checker is None:
            return self._result(
                problem,
                kind=UiConstraintResultKind.UNKNOWN,
                status=ConstraintCheckStatus.UNSUPPORTED,
                backend=UiConstraintBackend.FINITE_GRAPH,
                solver_id=ADAPTER_SOLVER_ID_FINITE_GRAPH,
                evidence_level=EvidenceLevel.STRUCTURAL,
                verification_status=VerificationStatus.UNVERIFIED,
                message=f"unsupported property_kind {problem.property_kind.value}",
                bounded=True,
            )
        graph = _index_graph(problem)
        outcome = checker(problem, graph)
        if outcome.unknown:
            return self._result(
                problem,
                kind=UiConstraintResultKind.UNKNOWN,
                status=ConstraintCheckStatus.INCONCLUSIVE,
                backend=UiConstraintBackend.FINITE_GRAPH,
                solver_id=ADAPTER_SOLVER_ID_FINITE_GRAPH,
                evidence_level=EvidenceLevel.STRUCTURAL,
                verification_status=VerificationStatus.UNVERIFIED,
                message=outcome.message,
                bounded=True,
            )
        if not outcome.ok:
            return self._result(
                problem,
                kind=UiConstraintResultKind.COUNTEREXAMPLE,
                status=ConstraintCheckStatus.VIOLATED,
                backend=UiConstraintBackend.FINITE_GRAPH,
                solver_id=ADAPTER_SOLVER_ID_FINITE_GRAPH,
                evidence_level=EvidenceLevel.STRUCTURAL,
                verification_status=VerificationStatus.INVALID,
                message=outcome.message,
                bounded=True,
                counterexample=outcome.counterexample,
            )
        # Successful finite-graph conclusions are structural results, not
        # theorem-prover "verified" claims — except for purely exhaustive
        # structural properties on exact analysis, which may be labeled
        # proved_bounded_property with structural evidence.
        exhaustive = problem.property_kind in {
            UiConstraintPropertyKind.DEFINED_TRANSITION_TARGETS,
            UiConstraintPropertyKind.NO_DUPLICATE_STATE_IDS,
            UiConstraintPropertyKind.SINGLE_INITIAL_STATE,
            UiConstraintPropertyKind.FAILURE_RECOVERY,
            UiConstraintPropertyKind.EVENT_OUTCOME_COVERAGE,
        }
        exact = problem.analysis_classification is AnalysisClassification.EXACT
        if exhaustive and exact and not problem.unresolved:
            return self._result(
                problem,
                kind=UiConstraintResultKind.PROVED_BOUNDED_PROPERTY,
                status=ConstraintCheckStatus.SATISFIED,
                backend=UiConstraintBackend.FINITE_GRAPH,
                solver_id=ADAPTER_SOLVER_ID_FINITE_GRAPH,
                evidence_level=EvidenceLevel.STRUCTURAL,
                verification_status=VerificationStatus.STRUCTURALLY_VALID,
                message=outcome.message,
                bounded=True,
            )
        return self._result(
            problem,
            kind=UiConstraintResultKind.STRUCTURAL_RESULT,
            status=ConstraintCheckStatus.SATISFIED,
            backend=UiConstraintBackend.FINITE_GRAPH,
            solver_id=ADAPTER_SOLVER_ID_FINITE_GRAPH,
            evidence_level=EvidenceLevel.STRUCTURAL,
            verification_status=VerificationStatus.STRUCTURALLY_VALID,
            message=outcome.message,
            bounded=True,
        )

    def _solve_cvc5(self, problem: UiConstraintProblem) -> UiConstraintResult:
        capability = self.probe_solver()
        smtlib = ""
        digest = ""
        try:
            smtlib, digest = _compile_cvc5_vector(problem)
        except Exception as error:  # noqa: BLE001 - compilation failure is unknown
            return self._result(
                problem,
                kind=UiConstraintResultKind.UNKNOWN,
                status=ConstraintCheckStatus.ERROR,
                backend=UiConstraintBackend.CVC5_SMT,
                solver_id=ADAPTER_SOLVER_ID_CVC5,
                evidence_level=EvidenceLevel.STRUCTURAL,
                verification_status=VerificationStatus.UNVERIFIED,
                message=f"SMT compilation failed: {error}",
                bounded=True,
            )
        if not capability.available:
            return self._result(
                problem,
                kind=UiConstraintResultKind.UNAVAILABLE,
                status=ConstraintCheckStatus.UNSUPPORTED,
                backend=UiConstraintBackend.CVC5_SMT,
                solver_id=ADAPTER_SOLVER_ID_CVC5,
                evidence_level=EvidenceLevel.STRUCTURAL,
                verification_status=VerificationStatus.UNVERIFIED,
                message=(
                    "cvc5 solver unavailable: "
                    + (capability.reason or "capability probe failed")
                ),
                bounded=True,
                smtlib=smtlib,
                smt_compilation_digest=digest,
            )
        if self._smt_runner is None:
            # Capability present but no execution path: still unavailable for
            # proved outcomes; vector remains attached for offline use.
            return self._result(
                problem,
                kind=UiConstraintResultKind.UNAVAILABLE,
                status=ConstraintCheckStatus.UNSUPPORTED,
                backend=UiConstraintBackend.CVC5_SMT,
                solver_id=ADAPTER_SOLVER_ID_CVC5,
                evidence_level=EvidenceLevel.STRUCTURAL,
                verification_status=VerificationStatus.UNVERIFIED,
                message=(
                    "cvc5 executable is present but solver execution is not "
                    "enabled for this adapter instance (compile-only mode)"
                ),
                bounded=True,
                smtlib=smtlib,
                smt_compilation_digest=digest,
            )
        try:
            raw = self._smt_runner(smtlib).strip().lower()
        except Exception as error:  # noqa: BLE001 - solver errors fail closed
            return self._result(
                problem,
                kind=UiConstraintResultKind.UNKNOWN,
                status=ConstraintCheckStatus.ERROR,
                backend=UiConstraintBackend.CVC5_SMT,
                solver_id=ADAPTER_SOLVER_ID_CVC5,
                evidence_level=EvidenceLevel.STRUCTURAL,
                verification_status=VerificationStatus.UNVERIFIED,
                message=f"cvc5 execution failed: {error}",
                bounded=True,
                smtlib=smtlib,
                smt_compilation_digest=digest,
            )
        # theorem_by_negation: unsat => property holds under premises.
        first = raw.splitlines()[0] if raw else ""
        if first == "unsat":
            return self._result(
                problem,
                kind=UiConstraintResultKind.PROVED_BOUNDED_PROPERTY,
                status=ConstraintCheckStatus.SATISFIED,
                backend=UiConstraintBackend.CVC5_SMT,
                solver_id=ADAPTER_SOLVER_ID_CVC5,
                evidence_level=EvidenceLevel.AUTOMATED,
                verification_status=VerificationStatus.VERIFIED,
                message=(
                    "cvc5 proved the bounded property under explicit finite premises "
                    "(not beauty/complete accessibility/complete security/"
                    "unbounded correctness)"
                ),
                bounded=True,
                smtlib=smtlib,
                smt_compilation_digest=digest,
            )
        if first == "sat":
            return self._result(
                problem,
                kind=UiConstraintResultKind.COUNTEREXAMPLE,
                status=ConstraintCheckStatus.VIOLATED,
                backend=UiConstraintBackend.CVC5_SMT,
                solver_id=ADAPTER_SOLVER_ID_CVC5,
                evidence_level=EvidenceLevel.AUTOMATED,
                verification_status=VerificationStatus.INVALID,
                message="cvc5 found a model refuting the bounded property",
                bounded=True,
                smtlib=smtlib,
                smt_compilation_digest=digest,
                counterexample=UiConstraintCounterexample(
                    counterexample_id=_digest_id(
                        "cex",
                        {
                            "problem": problem.problem_id,
                            "property": problem.property_kind.value,
                        },
                    ),
                    property_kind=problem.property_kind.value,
                    subject_ids=(problem.machine_id,),
                    message="smt model (sat under theorem-by-negation)",
                ),
            )
        return self._result(
            problem,
            kind=UiConstraintResultKind.UNKNOWN,
            status=ConstraintCheckStatus.INCONCLUSIVE,
            backend=UiConstraintBackend.CVC5_SMT,
            solver_id=ADAPTER_SOLVER_ID_CVC5,
            evidence_level=EvidenceLevel.AUTOMATED,
            verification_status=VerificationStatus.UNVERIFIED,
            message=f"cvc5 returned non-conclusive answer: {first or raw!r}",
            bounded=True,
            smtlib=smtlib,
            smt_compilation_digest=digest,
        )

    def _result(
        self,
        problem: UiConstraintProblem,
        *,
        kind: UiConstraintResultKind,
        status: ConstraintCheckStatus,
        backend: UiConstraintBackend,
        solver_id: str,
        evidence_level: EvidenceLevel,
        verification_status: VerificationStatus,
        message: str,
        bounded: bool,
        counterexample: UiConstraintCounterexample | None = None,
        smtlib: str = "",
        smt_compilation_digest: str = "",
    ) -> UiConstraintResult:
        result_id = _digest_id(
            "result",
            {
                "problem_id": problem.problem_id,
                "check_id": problem.check_id,
                "kind": kind.value,
                "status": status.value,
                "property_kind": problem.property_kind.value,
                "message": message,
            },
        )
        return UiConstraintResult(
            result_id=result_id,
            problem_id=problem.problem_id,
            check_id=problem.check_id,
            property_kind=problem.property_kind.value,
            kind=kind,
            status=status,
            backend=backend,
            solver_id=solver_id,
            evidence_level=evidence_level,
            analysis_classification=problem.analysis_classification,
            verification_status=verification_status,
            message=message,
            bounded=bounded,
            forbidden_claims_rejected=True,
            counterexample=counterexample,
            smtlib=smtlib.strip() if smtlib else "",
            smt_compilation_digest=(
                smt_compilation_digest.strip() if smt_compilation_digest else ""
            ),
            source_bindings=problem.source_bindings,
        )


def create_gui_formal_adapter(
    *,
    cvc5_probe: Callable[[], Cvc5Capability] | None = None,
    smt_runner: Callable[[str], str] | None = None,
) -> GuiFormalAdapter:
    """Factory for ``GuiFormalAdapter@1``."""

    return GuiFormalAdapter(cvc5_probe=cvc5_probe, smt_runner=smt_runner)


__all__ = [
    "ADAPTER_SOLVER_ID_CVC5",
    "ADAPTER_SOLVER_ID_FINITE_GRAPH",
    "ADAPTER_SOLVER_ID_NONE",
    "CANONICAL_JSON_PROFILE",
    "Cvc5Capability",
    "FORBIDDEN_CLAIM_KINDS",
    "GUI_FORMAL_ADAPTER_INTERFACE",
    "GUI_FORMAL_ADAPTER_SCHEMA",
    "GUI_FORMAL_ADAPTER_VERSION",
    "GuiFormalAdapter",
    "GuiFormalAdapterError",
    "SUPPORTED_PROPERTY_KINDS",
    "UI_CONSTRAINT_PROBLEM_INTERFACE",
    "UI_CONSTRAINT_PROBLEM_SCHEMA",
    "UI_CONSTRAINT_RESULT_INTERFACE",
    "UI_CONSTRAINT_RESULT_SCHEMA",
    "UiAsyncEffectPremise",
    "UiConstraintBackend",
    "UiConstraintCounterexample",
    "UiConstraintProblem",
    "UiConstraintPropertyKind",
    "UiConstraintResult",
    "UiConstraintResultKind",
    "UiConstraintSourceBinding",
    "create_gui_formal_adapter",
    "probe_cvc5",
]
