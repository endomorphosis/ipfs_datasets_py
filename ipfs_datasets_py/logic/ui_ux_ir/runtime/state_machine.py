"""Bounded UI state-machine runtime (UIR-054).

Interprets a closed :class:`~ipfs_datasets_py.logic.ui_ux_ir.model.behavior.BehaviorModel`
only. The runtime:

- evaluates guards in a closed expression language (no arbitrary code);
- chooses deterministic transitions by priority;
- stages state-only effects and external-effect requests without executing programs;
- handles parallel joins, timers, cancel, and rollback;
- fences events by state version so stale events cannot rewrite newer state; and
- fails closed on nontermination, ambiguous priority, and unsupported expressions.

External effects remain staged for the mediator (UIR-055); this module never
performs transport calls, policy grants, clock ambiguity, or renderer mutation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Final, Mapping, Sequence

from ..model.behavior import (
    BehaviorModel,
    BehaviorState,
    BehaviorTransition,
    TransitionJoinKind,
    validate_behavior_model,
)
from ..schema import UIIRValidationError

UI_STATE_RUNTIME_INTERFACE: Final = "UIStateRuntime@1"
STATE_MACHINE_ADAPTER_ID: Final = "runtime.state_machine@1"
STATE_MACHINE_SCHEMA_VERSION: Final = "ui-runtime-state-machine/v1"

# Hard bounds: every step and every multi-event trace must terminate.
DEFAULT_MAX_STEPS_PER_EVENT: Final = 32
DEFAULT_MAX_TRACE_LENGTH: Final = 256

_IDENTIFIER_RE: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")
_FORBIDDEN_EXPR_TOKENS: Final = (
    "=>",
    "->",
    "${",
    "{{",
    "}}",
    "javascript:",
    "eval(",
    "exec(",
    "lambda",
    "function",
    "callback",
    "handler(",
    "import ",
    "__",
)


class TransitionDisposition(str, Enum):
    """Outcome of one bounded step attempt."""

    APPLIED = "applied"
    NO_MATCH = "no_match"
    GUARD_FALSE = "guard_false"
    REJECT_STALE = "reject_stale"
    REJECT_AMBIGUOUS = "reject_ambiguous"
    REJECT_UNSUPPORTED = "reject_unsupported"
    REJECT_NONTERMINATION = "reject_nontermination"
    REJECT_INVALID = "reject_invalid"


class EffectKind(str, Enum):
    """Whether an effect is local state or an external request (never executed here)."""

    STATE_ONLY = "state_only"
    EXTERNAL_REQUEST = "external_request"


class UXPhase(str, Enum):
    """Closed UX lifecycle phases tracked by the runtime snapshot."""

    IDLE = "idle"
    FOCUSED = "focused"
    NAVIGATING = "navigating"
    CONFIRMING = "confirming"
    PENDING = "pending"
    RESULT_SUCCESS = "result_success"
    RESULT_FAILURE = "result_failure"
    RESULT_PARTIAL = "result_partial"
    ERROR = "error"
    RECOVERY = "recovery"
    UNAVAILABLE = "unavailable"
    DEGRADED = "degraded"


# Map well-known state id suffixes / exact ids to UX phases for fixtures.
_PHASE_BY_STATE_TOKEN: Final[Mapping[str, UXPhase]] = MappingProxyType(
    {
        "idle": UXPhase.IDLE,
        "focused": UXPhase.FOCUSED,
        "focus": UXPhase.FOCUSED,
        "navigating": UXPhase.NAVIGATING,
        "navigate": UXPhase.NAVIGATING,
        "confirming": UXPhase.CONFIRMING,
        "confirmation": UXPhase.CONFIRMING,
        "pending": UXPhase.PENDING,
        "result_success": UXPhase.RESULT_SUCCESS,
        "success": UXPhase.RESULT_SUCCESS,
        "result_failure": UXPhase.RESULT_FAILURE,
        "failure": UXPhase.RESULT_FAILURE,
        "result_partial": UXPhase.RESULT_PARTIAL,
        "partial": UXPhase.RESULT_PARTIAL,
        "error": UXPhase.ERROR,
        "recovery": UXPhase.RECOVERY,
        "unavailable": UXPhase.UNAVAILABLE,
        "degraded": UXPhase.DEGRADED,
    }
)


@dataclass(frozen=True, slots=True)
class EffectSpec:
    """Closed effect declaration: reference only, never executable code."""

    effect_id: str
    kind: EffectKind
    binding_ref: str = ""
    # Optional local variable assignment for STATE_ONLY effects.
    set_fact: str = ""
    set_value: bool = True


@dataclass(frozen=True, slots=True)
class StagedEffect:
    """Effect request emitted by a transition; external ones are never executed."""

    effect_id: str
    kind: EffectKind
    binding_ref: str = ""
    executed: bool = False
    set_fact: str = ""
    set_value: bool = True

    def __post_init__(self) -> None:
        if self.kind is EffectKind.EXTERNAL_REQUEST and self.executed:
            raise UIIRValidationError(
                f"External effect {self.effect_id!r} must remain staged (executed=False)"
            )


@dataclass(frozen=True, slots=True)
class ActiveTimer:
    """Timer armed when a timeout-bearing transition is applied."""

    timer_id: str
    source_transition_id: str
    deadline_ms: int
    rollback_target_state_id: str = ""


@dataclass(frozen=True, slots=True)
class RuntimeSnapshot:
    """Versioned runtime state. ``state_version`` is the fencing token."""

    active_state_ids: frozenset[str]
    state_version: int
    latest_timestamp_ms: int
    phase: UXPhase = UXPhase.IDLE
    focus_component_id: str = ""
    pending_confirmation: bool = False
    facts: Mapping[str, bool] = field(default_factory=lambda: MappingProxyType({}))
    staged_effects: tuple[StagedEffect, ...] = ()
    active_timers: tuple[ActiveTimer, ...] = ()
    last_transition_id: str = ""
    last_event_id: str = ""
    schema_version: str = STATE_MACHINE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.facts, Mapping):
            raise UIIRValidationError("RuntimeSnapshot.facts must be a mapping")
        if type(self.facts) is not MappingProxyType:
            object.__setattr__(
                self, "facts", MappingProxyType(dict(self.facts))
            )
        if self.state_version < 0:
            raise UIIRValidationError("state_version must be non-negative")
        if self.latest_timestamp_ms < 0:
            raise UIIRValidationError("latest_timestamp_ms must be non-negative")


@dataclass(frozen=True, slots=True)
class TransitionCandidate:
    """Selected or rejected transition candidate (never an invocation)."""

    transition_id: str
    source_state_ids: tuple[str, ...]
    target_state_id: str
    event_id: str
    effect_ids: tuple[str, ...]
    priority: int
    join_kind: TransitionJoinKind = TransitionJoinKind.ALL


@dataclass(frozen=True, slots=True)
class StepResult:
    """Result of one bounded step. External effects stay staged."""

    disposition: TransitionDisposition
    snapshot: RuntimeSnapshot
    candidate: TransitionCandidate | None = None
    staged_effects: tuple[StagedEffect, ...] = ()
    reason: str = ""
    adapter_id: str = STATE_MACHINE_ADAPTER_ID
    interface: str = UI_STATE_RUNTIME_INTERFACE
    schema_version: str = STATE_MACHINE_SCHEMA_VERSION
    notes: str = ""


@dataclass(frozen=True, slots=True)
class TraceResult:
    """Bounded multi-event execution receipt."""

    steps: tuple[StepResult, ...]
    final_snapshot: RuntimeSnapshot
    terminated: bool
    reason: str = ""
    adapter_id: str = STATE_MACHINE_ADAPTER_ID
    interface: str = UI_STATE_RUNTIME_INTERFACE


def _phase_for_states(active: frozenset[str]) -> UXPhase:
    """Derive UX phase from active state identifiers (deterministic)."""

    if not active:
        return UXPhase.IDLE
    # Prefer the most specific non-idle phase when parallel regions differ.
    ranked: list[tuple[int, UXPhase]] = []
    for state_id in sorted(active):
        token = state_id.rsplit(":", 1)[-1].lower()
        # Also try full id and last path segment.
        for key in (token, state_id.lower(), state_id.rsplit("/", 1)[-1].lower()):
            phase = _PHASE_BY_STATE_TOKEN.get(key)
            if phase is not None:
                # Higher rank for terminal-ish phases so they surface.
                rank = {
                    UXPhase.ERROR: 90,
                    UXPhase.RECOVERY: 85,
                    UXPhase.RESULT_FAILURE: 80,
                    UXPhase.RESULT_SUCCESS: 75,
                    UXPhase.RESULT_PARTIAL: 70,
                    UXPhase.PENDING: 60,
                    UXPhase.CONFIRMING: 50,
                    UXPhase.NAVIGATING: 40,
                    UXPhase.FOCUSED: 30,
                    UXPhase.DEGRADED: 25,
                    UXPhase.UNAVAILABLE: 20,
                    UXPhase.IDLE: 0,
                }.get(phase, 10)
                ranked.append((rank, phase))
                break
    if not ranked:
        return UXPhase.IDLE
    ranked.sort(key=lambda item: (-item[0], item[1].value))
    return ranked[0][1]


def _pending_for_phase(phase: UXPhase) -> bool:
    return phase in {UXPhase.CONFIRMING, UXPhase.PENDING}


def evaluate_guard(
    expression: str,
    facts: Mapping[str, bool],
    *,
    guard_id: str = "",
) -> bool:
    """Evaluate a closed guard expression against boolean facts.

    Supported forms (fail closed otherwise):
    - empty / ``true`` / ``always`` → True
    - ``false`` / ``never`` → False
    - ``fact:<id>`` or bare identifier → facts[id] is True
    - ``not:fact:<id>`` or ``not:<id>`` → facts[id] is not True
    - ``fact:<id>=true|false`` equality

    Unsupported tokens (``=>``, ``${``, callbacks, parentheses calls, …)
    raise :class:`UIIRValidationError`.
    """

    expr = (expression or "").strip()
    if not expr or expr.lower() in {"true", "always"}:
        return True
    if expr.lower() in {"false", "never"}:
        return False

    lowered = expr.lower()
    for token in _FORBIDDEN_EXPR_TOKENS:
        if token in lowered or token in expr:
            raise UIIRValidationError(
                f"Unsupported guard expression for {guard_id or 'guard'!r}: "
                f"forbidden token {token!r} in {expression!r}"
            )
    if any(ch in expr for ch in "()[];\"'`\\&|"):
        raise UIIRValidationError(
            f"Unsupported guard expression for {guard_id or 'guard'!r}: "
            f"executable syntax rejected in {expression!r}"
        )

    # Equality form: fact:name=true|false  or  name=true|false
    if "=" in expr:
        left, _, right = expr.partition("=")
        left = left.strip()
        right = right.strip().lower()
        if right not in {"true", "false"}:
            raise UIIRValidationError(
                f"Unsupported guard expression for {guard_id or 'guard'!r}: "
                f"equality value must be true|false in {expression!r}"
            )
        fact_id = left
        if fact_id.startswith("fact:"):
            fact_id = fact_id[5:]
        if not _IDENTIFIER_RE.fullmatch(fact_id):
            raise UIIRValidationError(
                f"Unsupported guard expression for {guard_id or 'guard'!r}: "
                f"invalid fact id in {expression!r}"
            )
        actual = bool(facts.get(fact_id, False))
        return actual is (right == "true")

    negated = False
    fact_id = expr
    if fact_id.startswith("not:"):
        negated = True
        fact_id = fact_id[4:]
    if fact_id.startswith("fact:"):
        fact_id = fact_id[5:]
    if not _IDENTIFIER_RE.fullmatch(fact_id):
        raise UIIRValidationError(
            f"Unsupported guard expression for {guard_id or 'guard'!r}: "
            f"invalid fact id in {expression!r}"
        )
    value = bool(facts.get(fact_id, False))
    return (not value) if negated else value


def _sources_enabled(
    transition: BehaviorTransition,
    active: frozenset[str],
) -> bool:
    sources = frozenset(transition.source_state_ids)
    if not sources:
        return False
    if transition.join_kind is TransitionJoinKind.ALL:
        return sources.issubset(active)
    if transition.join_kind is TransitionJoinKind.ANY:
        return bool(sources & active)
    if transition.join_kind is TransitionJoinKind.PRIORITY:
        # At least one source active; priority among transitions decides later.
        return bool(sources & active)
    raise UIIRValidationError(
        f"Unsupported join kind {transition.join_kind!r} on "
        f"{transition.transition_id!r}"
    )


def _candidate_from(transition: BehaviorTransition) -> TransitionCandidate:
    return TransitionCandidate(
        transition_id=transition.transition_id,
        source_state_ids=tuple(transition.source_state_ids),
        target_state_id=transition.target_state_id,
        event_id=transition.event_id,
        effect_ids=tuple(transition.effect_ids),
        priority=transition.priority,
        join_kind=transition.join_kind,
    )


class UIStateRuntime:
    """Bounded interpreter for a validated behavior model (UIStateRuntime@1)."""

    def __init__(
        self,
        model: BehaviorModel,
        *,
        guards: Mapping[str, str] | None = None,
        effects: Mapping[str, EffectSpec] | None = None,
        focus_order: Sequence[str] = (),
        max_steps_per_event: int = DEFAULT_MAX_STEPS_PER_EVENT,
        max_trace_length: int = DEFAULT_MAX_TRACE_LENGTH,
    ) -> None:
        self._model = validate_behavior_model(model)
        self._states: dict[str, BehaviorState] = {
            s.state_id: s for s in self._model.states
        }
        self._transitions: tuple[BehaviorTransition, ...] = self._model.transitions
        self._guards: Mapping[str, str] = MappingProxyType(dict(guards or {}))
        self._effects: Mapping[str, EffectSpec] = MappingProxyType(dict(effects or {}))
        self._focus_order: tuple[str, ...] = tuple(focus_order)
        if max_steps_per_event < 1:
            raise UIIRValidationError("max_steps_per_event must be >= 1")
        if max_trace_length < 1:
            raise UIIRValidationError("max_trace_length must be >= 1")
        self._max_steps_per_event = max_steps_per_event
        self._max_trace_length = max_trace_length
        # Reject ambiguous priorities at construction (defense in depth).
        self._assert_priority_determinism()

    @property
    def model(self) -> BehaviorModel:
        return self._model

    @property
    def interface(self) -> str:
        return UI_STATE_RUNTIME_INTERFACE

    def _assert_priority_determinism(self) -> None:
        by_key: dict[tuple[tuple[str, ...], str, int], str] = {}
        for transition in self._transitions:
            key = (
                tuple(sorted(transition.source_state_ids)),
                transition.event_id,
                transition.priority,
            )
            prior = by_key.get(key)
            if prior is not None:
                raise UIIRValidationError(
                    "Ambiguous transition priority between "
                    f"{prior!r} and {transition.transition_id!r}"
                )
            by_key[key] = transition.transition_id

    def initial_snapshot(
        self,
        *,
        timestamp_ms: int = 0,
        facts: Mapping[str, bool] | None = None,
        focus_component_id: str = "",
    ) -> RuntimeSnapshot:
        """Build the version-0 snapshot at declared initial states."""

        if timestamp_ms < 0:
            raise UIIRValidationError("timestamp_ms must be non-negative")
        active = frozenset(self._model.initial_state_ids)
        for state_id in active:
            if state_id not in self._states:
                raise UIIRValidationError(f"Unknown initial state {state_id!r}")
        focus = focus_component_id
        if not focus and self._focus_order:
            focus = self._focus_order[0]
        phase = _phase_for_states(active)
        return RuntimeSnapshot(
            active_state_ids=active,
            state_version=0,
            latest_timestamp_ms=timestamp_ms,
            phase=phase,
            focus_component_id=focus,
            pending_confirmation=_pending_for_phase(phase),
            facts=MappingProxyType(dict(facts or {})),
            staged_effects=(),
            active_timers=(),
        )

    def step(
        self,
        snapshot: RuntimeSnapshot,
        event_id: str,
        *,
        timestamp_ms: int | None = None,
        expected_state_version: int | None = None,
        facts: Mapping[str, bool] | None = None,
        focus_component_id: str | None = None,
        target_component_id: str = "",
    ) -> StepResult:
        """Apply at most one transition for ``event_id`` under fencing bounds.

        Parameters
        ----------
        expected_state_version:
            When provided, must equal ``snapshot.state_version`` or the event
            is rejected as stale (fencing).
        timestamp_ms:
            When provided and strictly less than ``snapshot.latest_timestamp_ms``,
            the event is rejected as stale.
        """

        if not isinstance(event_id, str) or not event_id.strip():
            raise UIIRValidationError("event_id must be a non-empty string")
        if not _IDENTIFIER_RE.fullmatch(event_id):
            raise UIIRValidationError(
                f"Unsupported event id expression {event_id!r}"
            )

        # --- fencing ---
        if (
            expected_state_version is not None
            and expected_state_version != snapshot.state_version
        ):
            return StepResult(
                disposition=TransitionDisposition.REJECT_STALE,
                snapshot=snapshot,
                reason=(
                    f"state_version fence: expected {expected_state_version}, "
                    f"current {snapshot.state_version}"
                ),
                notes="Stale events cannot override newer state",
            )
        ts = snapshot.latest_timestamp_ms if timestamp_ms is None else timestamp_ms
        if ts < 0:
            raise UIIRValidationError("timestamp_ms must be non-negative")
        if ts < snapshot.latest_timestamp_ms:
            return StepResult(
                disposition=TransitionDisposition.REJECT_STALE,
                snapshot=snapshot,
                reason=(
                    f"timestamp fence: event {ts} < state "
                    f"{snapshot.latest_timestamp_ms}"
                ),
                notes="Stale events cannot override newer state",
            )

        merged_facts = dict(snapshot.facts)
        if facts:
            merged_facts.update({str(k): bool(v) for k, v in facts.items()})

        # Built-in navigation focus updates (state-only, no external I/O).
        if event_id in {"focus", "navigate"} and target_component_id:
            return self._apply_focus_navigation(
                snapshot,
                event_id=event_id,
                timestamp_ms=ts,
                focus_component_id=target_component_id
                if event_id == "focus"
                else (focus_component_id or target_component_id),
                facts=merged_facts,
            )

        matching: list[BehaviorTransition] = []
        guard_blocked: list[BehaviorTransition] = []
        for transition in self._transitions:
            if transition.event_id and transition.event_id != event_id:
                continue
            if not transition.event_id:
                # Empty event_id is reserved for internal spontaneous edges; skip
                # external step matching unless event is the transition id.
                if event_id != transition.transition_id:
                    continue
            if not _sources_enabled(transition, snapshot.active_state_ids):
                continue
            try:
                guard_ok = self._eval_transition_guard(transition, merged_facts)
            except UIIRValidationError as exc:
                return StepResult(
                    disposition=TransitionDisposition.REJECT_UNSUPPORTED,
                    snapshot=snapshot,
                    candidate=_candidate_from(transition),
                    reason=str(exc),
                    notes="Unsupported expressions fail closed",
                )
            if not guard_ok:
                guard_blocked.append(transition)
                continue
            matching.append(transition)

        if not matching:
            if guard_blocked:
                return StepResult(
                    disposition=TransitionDisposition.GUARD_FALSE,
                    snapshot=snapshot,
                    candidate=_candidate_from(guard_blocked[0]),
                    reason=f"All guards false for event {event_id!r}",
                )
            return StepResult(
                disposition=TransitionDisposition.NO_MATCH,
                snapshot=snapshot,
                reason=f"No transition matches event {event_id!r}",
            )

        # Deterministic selection: highest priority, then stable transition_id.
        matching.sort(key=lambda t: (-t.priority, t.transition_id))
        best = matching[0]
        # Ambiguous if another enabled candidate shares the same priority.
        peers = [t for t in matching if t.priority == best.priority]
        if len(peers) > 1:
            ids = ", ".join(t.transition_id for t in peers)
            return StepResult(
                disposition=TransitionDisposition.REJECT_AMBIGUOUS,
                snapshot=snapshot,
                candidate=_candidate_from(best),
                reason=f"Ambiguous priority among transitions: {ids}",
                notes="Ambiguous priority fails closed",
            )

        return self._apply_transition(
            snapshot,
            best,
            event_id=event_id,
            timestamp_ms=ts,
            facts=merged_facts,
            focus_component_id=focus_component_id
            if focus_component_id is not None
            else snapshot.focus_component_id,
        )

    def step_timeout(
        self,
        snapshot: RuntimeSnapshot,
        *,
        now_ms: int,
        expected_state_version: int | None = None,
    ) -> StepResult:
        """Fire the earliest expired timer, if any, as a timeout event."""

        if now_ms < 0:
            raise UIIRValidationError("now_ms must be non-negative")
        expired = [t for t in snapshot.active_timers if t.deadline_ms <= now_ms]
        if not expired:
            return StepResult(
                disposition=TransitionDisposition.NO_MATCH,
                snapshot=snapshot,
                reason="No expired timers",
            )
        expired.sort(key=lambda t: (t.deadline_ms, t.timer_id))
        timer = expired[0]
        # Prefer an explicit timeout transition; else roll back if declared.
        timeout_event = f"timeout:{timer.source_transition_id}"
        result = self.step(
            snapshot,
            timeout_event,
            timestamp_ms=now_ms,
            expected_state_version=expected_state_version,
        )
        if result.disposition is TransitionDisposition.APPLIED:
            return result
        result = self.step(
            snapshot,
            "timeout",
            timestamp_ms=now_ms,
            expected_state_version=expected_state_version,
        )
        if result.disposition is TransitionDisposition.APPLIED:
            return result
        if timer.rollback_target_state_id:
            return self._force_states(
                snapshot,
                target_state_ids=frozenset({timer.rollback_target_state_id}),
                event_id="timeout",
                timestamp_ms=now_ms,
                transition_id=f"timeout-rollback:{timer.source_transition_id}",
                clear_timer_id=timer.timer_id,
            )
        return StepResult(
            disposition=TransitionDisposition.NO_MATCH,
            snapshot=snapshot,
            reason=f"Timer {timer.timer_id!r} expired without timeout transition",
        )

    def run_trace(
        self,
        events: Sequence[tuple[str, Mapping[str, object]] | str],
        *,
        initial: RuntimeSnapshot | None = None,
        max_trace_length: int | None = None,
    ) -> TraceResult:
        """Execute a bounded event trace deterministically.

        Each event is either an ``event_id`` string or ``(event_id, kwargs)``
        for :meth:`step`. Fails closed if the trace would exceed the bound.
        """

        bound = max_trace_length if max_trace_length is not None else self._max_trace_length
        if bound < 1:
            raise UIIRValidationError("max_trace_length must be >= 1")
        snapshot = initial if initial is not None else self.initial_snapshot()
        steps: list[StepResult] = []
        if len(events) > bound:
            return TraceResult(
                steps=(),
                final_snapshot=snapshot,
                terminated=False,
                reason=(
                    f"Nontermination: trace length {len(events)} exceeds bound {bound}"
                ),
            )
        for index, item in enumerate(events):
            if index >= bound:
                return TraceResult(
                    steps=tuple(steps),
                    final_snapshot=snapshot,
                    terminated=False,
                    reason=f"Nontermination: step index {index} exceeds bound {bound}",
                )
            if isinstance(item, str):
                event_id, kwargs = item, {}
            else:
                event_id, raw_kwargs = item[0], item[1]
                kwargs = dict(raw_kwargs)
            # Default fencing: always send current version when not provided.
            if "expected_state_version" not in kwargs:
                kwargs["expected_state_version"] = snapshot.state_version
            result = self.step(snapshot, event_id, **kwargs)  # type: ignore[arg-type]
            steps.append(result)
            if result.disposition is TransitionDisposition.APPLIED:
                snapshot = result.snapshot
            elif result.disposition in {
                TransitionDisposition.REJECT_STALE,
                TransitionDisposition.REJECT_AMBIGUOUS,
                TransitionDisposition.REJECT_UNSUPPORTED,
                TransitionDisposition.REJECT_NONTERMINATION,
                TransitionDisposition.REJECT_INVALID,
            }:
                return TraceResult(
                    steps=tuple(steps),
                    final_snapshot=snapshot,
                    terminated=True,
                    reason=result.reason or result.disposition.value,
                )
            # NO_MATCH / GUARD_FALSE leave snapshot unchanged and continue.
        return TraceResult(
            steps=tuple(steps),
            final_snapshot=snapshot,
            terminated=True,
            reason="trace_complete",
        )

    def _eval_transition_guard(
        self,
        transition: BehaviorTransition,
        facts: Mapping[str, bool],
    ) -> bool:
        if not transition.guard_id:
            return True
        if transition.guard_id not in self._guards:
            # Treat bare guard_id as a closed fact reference.
            return evaluate_guard(
                transition.guard_id, facts, guard_id=transition.guard_id
            )
        return evaluate_guard(
            self._guards[transition.guard_id],
            facts,
            guard_id=transition.guard_id,
        )

    def _stage_effects(
        self,
        transition: BehaviorTransition,
        facts: dict[str, bool],
    ) -> tuple[tuple[StagedEffect, ...], dict[str, bool]]:
        staged: list[StagedEffect] = []
        new_facts = dict(facts)
        for effect_id in transition.effect_ids:
            if any(tok in effect_id for tok in ("(", ")", "=>", "${", "{{")):
                raise UIIRValidationError(
                    f"Unsupported effect expression {effect_id!r}"
                )
            spec = self._effects.get(effect_id)
            if spec is None:
                # Default: external request staged by id reference only.
                staged.append(
                    StagedEffect(
                        effect_id=effect_id,
                        kind=EffectKind.EXTERNAL_REQUEST,
                        binding_ref=effect_id,
                        executed=False,
                    )
                )
                continue
            if spec.kind is EffectKind.STATE_ONLY:
                if spec.set_fact:
                    new_facts[spec.set_fact] = bool(spec.set_value)
                staged.append(
                    StagedEffect(
                        effect_id=spec.effect_id,
                        kind=EffectKind.STATE_ONLY,
                        binding_ref=spec.binding_ref or spec.effect_id,
                        executed=True,  # local state assignment applied in snapshot
                        set_fact=spec.set_fact,
                        set_value=spec.set_value,
                    )
                )
            else:
                staged.append(
                    StagedEffect(
                        effect_id=spec.effect_id,
                        kind=EffectKind.EXTERNAL_REQUEST,
                        binding_ref=spec.binding_ref or spec.effect_id,
                        executed=False,
                    )
                )
        return tuple(staged), new_facts

    def _next_active_states(
        self,
        snapshot: RuntimeSnapshot,
        transition: BehaviorTransition,
    ) -> frozenset[str]:
        active = set(snapshot.active_state_ids)
        sources = set(transition.source_state_ids)
        if transition.join_kind is TransitionJoinKind.ALL:
            active -= sources
        elif transition.join_kind is TransitionJoinKind.ANY:
            # Leave the matched sources that are active; remove only those that
            # participate and are currently active (any-join fires when ≥1).
            active -= sources & snapshot.active_state_ids
        else:  # PRIORITY
            # Exit the highest-priority (lexicographically first active) source.
            active_sources = sorted(sources & snapshot.active_state_ids)
            if active_sources:
                active.discard(active_sources[0])
        active.add(transition.target_state_id)
        # Drop unknown targets fail closed before this point via model validation.
        return frozenset(active)

    def _apply_transition(
        self,
        snapshot: RuntimeSnapshot,
        transition: BehaviorTransition,
        *,
        event_id: str,
        timestamp_ms: int,
        facts: Mapping[str, bool],
        focus_component_id: str,
    ) -> StepResult:
        try:
            staged, new_facts = self._stage_effects(transition, dict(facts))
        except UIIRValidationError as exc:
            return StepResult(
                disposition=TransitionDisposition.REJECT_UNSUPPORTED,
                snapshot=snapshot,
                candidate=_candidate_from(transition),
                reason=str(exc),
                notes="Unsupported expressions fail closed",
            )

        new_active = self._next_active_states(snapshot, transition)
        phase = _phase_for_states(new_active)

        # Timers: clear timers armed by the previous or current transition, then
        # arm a new timeout when this transition declares one.
        kept: list[ActiveTimer] = []
        drop_sources = {
            transition.transition_id,
            snapshot.last_transition_id,
        }
        for timer in snapshot.active_timers:
            if timer.source_transition_id in drop_sources:
                continue
            kept.append(timer)
        if transition.timeout_ms is not None:
            kept.append(
                ActiveTimer(
                    timer_id=f"timer:{transition.transition_id}",
                    source_transition_id=transition.transition_id,
                    deadline_ms=timestamp_ms + int(transition.timeout_ms),
                    rollback_target_state_id=transition.rollback_target_state_id,
                )
            )
        by_id = {t.timer_id: t for t in kept}
        timers = tuple(sorted(by_id.values(), key=lambda t: t.timer_id))

        focus = focus_component_id or snapshot.focus_component_id

        new_snapshot = RuntimeSnapshot(
            active_state_ids=new_active,
            state_version=snapshot.state_version + 1,
            latest_timestamp_ms=timestamp_ms,
            phase=phase,
            focus_component_id=focus,
            pending_confirmation=_pending_for_phase(phase),
            facts=MappingProxyType(new_facts),
            staged_effects=snapshot.staged_effects + staged,
            active_timers=timers,
            last_transition_id=transition.transition_id,
            last_event_id=event_id,
        )

        return StepResult(
            disposition=TransitionDisposition.APPLIED,
            snapshot=new_snapshot,
            candidate=_candidate_from(transition),
            staged_effects=staged,
            reason=f"Applied {transition.transition_id}",
            notes=(
                "External effects remain staged; runtime does not execute programs"
            ),
        )

    def _apply_focus_navigation(
        self,
        snapshot: RuntimeSnapshot,
        *,
        event_id: str,
        timestamp_ms: int,
        focus_component_id: str,
        facts: Mapping[str, bool],
    ) -> StepResult:
        """Handle focus/navigate as state-only updates when model edges exist.

        Prefer declared transitions; if none match, apply a pure focus update
        only when a matching focus-order component is named (state-only).
        """

        # Try model transitions first (e.g. idle --focus--> focused).
        matching: list[BehaviorTransition] = []
        for transition in self._transitions:
            if transition.event_id != event_id:
                continue
            if not _sources_enabled(transition, snapshot.active_state_ids):
                continue
            try:
                if not self._eval_transition_guard(transition, facts):
                    continue
            except UIIRValidationError as exc:
                return StepResult(
                    disposition=TransitionDisposition.REJECT_UNSUPPORTED,
                    snapshot=snapshot,
                    reason=str(exc),
                )
            matching.append(transition)
        if matching:
            matching.sort(key=lambda t: (-t.priority, t.transition_id))
            best = matching[0]
            peers = [t for t in matching if t.priority == best.priority]
            if len(peers) > 1:
                ids = ", ".join(t.transition_id for t in peers)
                return StepResult(
                    disposition=TransitionDisposition.REJECT_AMBIGUOUS,
                    snapshot=snapshot,
                    candidate=_candidate_from(best),
                    reason=f"Ambiguous priority among transitions: {ids}",
                )
            return self._apply_transition(
                snapshot,
                best,
                event_id=event_id,
                timestamp_ms=timestamp_ms,
                facts=facts,
                focus_component_id=focus_component_id,
            )

        if not focus_component_id.strip():
            return StepResult(
                disposition=TransitionDisposition.NO_MATCH,
                snapshot=snapshot,
                reason=f"No transition matches event {event_id!r}",
            )
        if self._focus_order and focus_component_id not in self._focus_order:
            return StepResult(
                disposition=TransitionDisposition.REJECT_INVALID,
                snapshot=snapshot,
                reason=f"Unknown focus target {focus_component_id!r}",
            )
        phase = (
            UXPhase.FOCUSED
            if event_id == "focus"
            else UXPhase.NAVIGATING
        )
        # Prefer model phase if still in a phase-bearing state.
        model_phase = _phase_for_states(snapshot.active_state_ids)
        if model_phase not in {UXPhase.IDLE, UXPhase.FOCUSED, UXPhase.NAVIGATING}:
            phase = model_phase
        new_snapshot = RuntimeSnapshot(
            active_state_ids=snapshot.active_state_ids,
            state_version=snapshot.state_version + 1,
            latest_timestamp_ms=timestamp_ms,
            phase=phase,
            focus_component_id=focus_component_id,
            pending_confirmation=snapshot.pending_confirmation,
            facts=MappingProxyType(dict(facts)),
            staged_effects=snapshot.staged_effects,
            active_timers=snapshot.active_timers,
            last_transition_id=f"builtin:{event_id}",
            last_event_id=event_id,
        )
        return StepResult(
            disposition=TransitionDisposition.APPLIED,
            snapshot=new_snapshot,
            reason=f"Applied builtin {event_id}",
            notes="Focus/navigation is state-only; no external effects",
        )

    def _force_states(
        self,
        snapshot: RuntimeSnapshot,
        *,
        target_state_ids: frozenset[str],
        event_id: str,
        timestamp_ms: int,
        transition_id: str,
        clear_timer_id: str = "",
    ) -> StepResult:
        for state_id in target_state_ids:
            if state_id not in self._states:
                return StepResult(
                    disposition=TransitionDisposition.REJECT_INVALID,
                    snapshot=snapshot,
                    reason=f"Unknown target state {state_id!r}",
                )
        timers = tuple(
            t for t in snapshot.active_timers if t.timer_id != clear_timer_id
        )
        phase = _phase_for_states(target_state_ids)
        new_snapshot = RuntimeSnapshot(
            active_state_ids=target_state_ids,
            state_version=snapshot.state_version + 1,
            latest_timestamp_ms=timestamp_ms,
            phase=phase,
            focus_component_id=snapshot.focus_component_id,
            pending_confirmation=_pending_for_phase(phase),
            facts=snapshot.facts,
            staged_effects=snapshot.staged_effects,
            active_timers=timers,
            last_transition_id=transition_id,
            last_event_id=event_id,
        )
        return StepResult(
            disposition=TransitionDisposition.APPLIED,
            snapshot=new_snapshot,
            candidate=TransitionCandidate(
                transition_id=transition_id,
                source_state_ids=tuple(sorted(snapshot.active_state_ids)),
                target_state_id=next(iter(sorted(target_state_ids))),
                event_id=event_id,
                effect_ids=(),
                priority=0,
            ),
            reason=f"Applied {transition_id}",
            notes="Timeout rollback path; external effects remain staged",
        )


def create_runtime(
    model: BehaviorModel,
    *,
    guards: Mapping[str, str] | None = None,
    effects: Mapping[str, EffectSpec] | None = None,
    focus_order: Sequence[str] = (),
    max_steps_per_event: int = DEFAULT_MAX_STEPS_PER_EVENT,
    max_trace_length: int = DEFAULT_MAX_TRACE_LENGTH,
) -> UIStateRuntime:
    """Factory for :class:`UIStateRuntime`."""

    return UIStateRuntime(
        model,
        guards=guards,
        effects=effects,
        focus_order=focus_order,
        max_steps_per_event=max_steps_per_event,
        max_trace_length=max_trace_length,
    )


__all__ = [
    "ActiveTimer",
    "DEFAULT_MAX_STEPS_PER_EVENT",
    "DEFAULT_MAX_TRACE_LENGTH",
    "EffectKind",
    "EffectSpec",
    "RuntimeSnapshot",
    "STATE_MACHINE_ADAPTER_ID",
    "STATE_MACHINE_SCHEMA_VERSION",
    "StagedEffect",
    "StepResult",
    "TraceResult",
    "TransitionCandidate",
    "TransitionDisposition",
    "UIStateRuntime",
    "UI_STATE_RUNTIME_INTERFACE",
    "UXPhase",
    "create_runtime",
    "evaluate_guard",
]
