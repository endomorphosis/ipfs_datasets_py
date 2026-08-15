"""Behavior state machines, transitions, and recovery (UIR-013)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Final, Iterable

from ..schema import UIIRValidationError

UI_BEHAVIOR_MODEL_INTERFACE: Final = "UIBehaviorModel@1"


class TransitionJoinKind(str, Enum):
    """Deterministic multi-source join semantics."""

    ALL = "all"
    ANY = "any"
    PRIORITY = "priority"


@dataclass(frozen=True, slots=True)
class BehaviorState:
    state_id: str
    label: str = ""
    parallel_region: str = ""
    terminal: bool = False


@dataclass(frozen=True, slots=True)
class BehaviorTransition:
    transition_id: str
    source_state_ids: tuple[str, ...]
    target_state_id: str
    event_id: str = ""
    guard_id: str = ""
    effect_ids: tuple[str, ...] = ()
    priority: int = 0
    join_kind: TransitionJoinKind = TransitionJoinKind.ALL
    cancelable: bool = True
    retryable: bool = False
    undoable: bool = False
    timeout_ms: int | None = None
    rollback_target_state_id: str = ""


@dataclass(frozen=True, slots=True)
class BehaviorModel:
    model_id: str
    states: tuple[BehaviorState, ...]
    transitions: tuple[BehaviorTransition, ...]
    initial_state_ids: tuple[str, ...]
    schema_version: str = "ui-behavior-model/v1"


def _require_ids(ids: Iterable[str], label: str) -> tuple[str, ...]:
    out: list[str] = []
    seen: set[str] = set()
    for item in ids:
        if not isinstance(item, str) or not item.strip():
            raise UIIRValidationError(f"{label} members must be non-empty strings")
        if item in seen:
            raise UIIRValidationError(f"Duplicate {label} member: {item!r}")
        seen.add(item)
        out.append(item)
    return tuple(out)


def validate_behavior_model(model: BehaviorModel) -> BehaviorModel:
    """Validate hierarchical/parallel behavior models fail-closed."""

    if not model.model_id.strip():
        raise UIIRValidationError("BehaviorModel.model_id must not be empty")
    if not model.states:
        raise UIIRValidationError("BehaviorModel.states must not be empty")
    if not model.initial_state_ids:
        raise UIIRValidationError("BehaviorModel.initial_state_ids must not be empty")
    state_ids = _require_ids((state.state_id for state in model.states), "state_id")
    known = set(state_ids)
    for initial in model.initial_state_ids:
        if initial not in known:
            raise UIIRValidationError(
                f"Unknown initial state {initial!r}"
            )
    # Deterministic transition priority: equal priority is rejected when
    # transitions share a source and event.
    by_key: dict[tuple[str, str, int], str] = {}
    for transition in model.transitions:
        if transition.target_state_id not in known:
            raise UIIRValidationError(
                f"Transition {transition.transition_id!r} targets unknown state "
                f"{transition.target_state_id!r}"
            )
        sources = _require_ids(transition.source_state_ids, "source_state_ids")
        for source in sources:
            if source not in known:
                raise UIIRValidationError(
                    f"Transition {transition.transition_id!r} references unknown "
                    f"source state {source!r}"
                )
            key = (source, transition.event_id, transition.priority)
            prior = by_key.get(key)
            if prior is not None:
                raise UIIRValidationError(
                    "Non-deterministic transition priority collision between "
                    f"{prior!r} and {transition.transition_id!r}"
                )
            by_key[key] = transition.transition_id
        if transition.timeout_ms is not None and transition.timeout_ms < 0:
            raise UIIRValidationError(
                f"Transition {transition.transition_id!r} timeout_ms must be >= 0"
            )
        if transition.rollback_target_state_id and (
            transition.rollback_target_state_id not in known
        ):
            raise UIIRValidationError(
                f"Transition {transition.transition_id!r} rollback target unknown"
            )
        # Arbitrary callbacks are rejected: effect_ids must be plain identifiers.
        for effect_id in transition.effect_ids:
            if "(" in effect_id or ")" in effect_id or "=>" in effect_id:
                raise UIIRValidationError(
                    f"Transition {transition.transition_id!r} rejects executable "
                    f"effect expression {effect_id!r}"
                )
    return model


__all__ = [
    "BehaviorModel",
    "BehaviorState",
    "BehaviorTransition",
    "TransitionJoinKind",
    "UI_BEHAVIOR_MODEL_INTERFACE",
    "validate_behavior_model",
]
