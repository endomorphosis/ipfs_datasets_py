"""Refinement relations, simulations, and boundedness disclosures.

``RefinementIR@1`` describes forward and backward simulation between abstract
and concrete systems, refinement obligations, and explicit schedule bounds.
It is deliberately free of solver requests and proof verdicts.

Bounded schedules never claim unbounded refinement: any obligation or
simulation that carries a finite step/state bound must set
``claims_unbounded_refinement`` to false, and construction fails closed
otherwise.  Simulation relations are validated structurally against their
declared state spaces and transition couples.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, ClassVar, Final

from ipfs_datasets_py.logic.ir_core.canonical import canonical_json_bytes
from ipfs_datasets_py.logic.ir_core.claims import FrozenMap
from ipfs_datasets_py.logic.ir_core.identity import (
    CanonicalIdentity,
    canonical_identity,
)

REFINEMENT_IR_INTERFACE: Final = "RefinementIR@1"
REFINEMENT_IR_SCHEMA_VERSION: Final = "refinement-ir/v1"
REFINEMENT_IR_IDENTITY_DOMAIN: Final = "logic.software-verification.refinement"

SYSTEM_SCHEMA_VERSION: Final = "refinement-system/v1"
STATE_SCHEMA_VERSION: Final = "refinement-state/v1"
TRANSITION_SCHEMA_VERSION: Final = "refinement-transition/v1"
COUPLE_SCHEMA_VERSION: Final = "simulation-couple/v1"
SIMULATION_SCHEMA_VERSION: Final = "simulation-relation/v1"
OBLIGATION_SCHEMA_VERSION: Final = "refinement-obligation/v1"
BOUNDEDNESS_SCHEMA_VERSION: Final = "refinement-boundedness/v1"

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")


class RefinementValidationError(ValueError):
    """Raised when refinement or simulation semantics are malformed."""


class SystemLevel(StrEnum):
    """Whether a system is the abstract specification or concrete implementation."""

    ABSTRACT = "abstract"
    CONCRETE = "concrete"


class SimulationDirection(StrEnum):
    """Direction of a simulation relation.

    Forward simulation: every abstract transition is matched by a concrete one.
    Backward simulation: every concrete transition is matched by an abstract one.
    """

    FORWARD = "forward"
    BACKWARD = "backward"


class RefinementKind(StrEnum):
    """Kind of refinement obligation."""

    TRACE = "trace"
    STATE = "state"
    SIMULATION = "simulation"
    BISEIMULATION = "bisimulation"
    DATA = "data"
    ACTION = "action"


class BoundednessKind(StrEnum):
    """Whether a refinement claim is finite-bounded or unbounded."""

    BOUNDED = "bounded"
    UNBOUNDED = "unbounded"


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value or value.strip() != value or "\x00" in value:
        raise RefinementValidationError(
            f"{label} must be a non-empty trimmed string without NUL bytes"
        )
    return value


def _optional_text(value: object, label: str) -> str:
    if value == "" or value is None:
        return ""
    return _text(value, label)


def _identifier(value: object, label: str) -> str:
    result = _text(value, label)
    if not _ID_RE.fullmatch(result):
        raise RefinementValidationError(f"{label} must be a stable identifier")
    return result


def _ids(
    values: Sequence[str] | object,
    label: str,
    *,
    preserve_order: bool = False,
) -> tuple[str, ...]:
    if isinstance(values, (str, bytes, bytearray)) or not isinstance(values, Sequence):
        raise RefinementValidationError(f"{label} must be a sequence of identifiers")
    result = tuple(_identifier(item, f"{label} item") for item in values)
    if len(result) != len(set(result)):
        raise RefinementValidationError(f"{label} must not contain duplicates")
    return result if preserve_order else tuple(sorted(result))


def _enum(value: object, enum_type: type[StrEnum], label: str) -> Any:
    try:
        return value if isinstance(value, enum_type) else enum_type(value)
    except (TypeError, ValueError) as error:
        choices = ", ".join(repr(item.value) for item in enum_type)
        raise RefinementValidationError(f"{label} must be one of {choices}") from error


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise RefinementValidationError(f"{label} must be a mapping")
    return value


def _frozen(value: Mapping[str, Any] | FrozenMap, label: str) -> FrozenMap:
    try:
        return value if isinstance(value, FrozenMap) else FrozenMap(value)
    except (TypeError, ValueError) as error:
        raise RefinementValidationError(
            f"{label} must contain immutable JSON-compatible data: {error}"
        ) from error


def _reject_unknown(value: Mapping[str, Any], allowed: frozenset[str], label: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise RefinementValidationError(f"unknown {label} field(s): {', '.join(unknown)}")


def _bool(value: object, label: str) -> bool:
    if not isinstance(value, bool):
        raise RefinementValidationError(f"{label} must be a boolean")
    return value


def _non_bool_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise RefinementValidationError(f"{label} must be an integer")
    return value


def _known(values: Sequence[str], known: set[str], label: str) -> None:
    missing = sorted(set(values) - known)
    if missing:
        raise RefinementValidationError(f"{label} references unknown ids {missing}")


def _coerce_records(
    values: Sequence[object],
    cls: type[Any],
    label: str,
    id_field: str,
) -> tuple[Any, ...]:
    records = tuple(
        item if isinstance(item, cls) else cls.from_dict(_mapping(item, label))
        for item in values
    )
    return tuple(sorted(records, key=lambda item: getattr(item, id_field)))


@dataclass(frozen=True, slots=True)
class RefinementState:
    """A named state in an abstract or concrete refinement system."""

    state_id: str
    label: str
    is_initial: bool = False
    is_terminal: bool = False
    predicate_statement: str = "true"
    attributes: FrozenMap = field(default_factory=FrozenMap)
    schema_version: str = STATE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "state_id", _identifier(self.state_id, "state_id"))
        object.__setattr__(self, "label", _text(self.label, "label"))
        object.__setattr__(self, "is_initial", _bool(self.is_initial, "is_initial"))
        object.__setattr__(self, "is_terminal", _bool(self.is_terminal, "is_terminal"))
        object.__setattr__(
            self,
            "predicate_statement",
            _text(self.predicate_statement, "predicate_statement"),
        )
        object.__setattr__(self, "attributes", _frozen(self.attributes, "attributes"))
        if self.schema_version != STATE_SCHEMA_VERSION:
            raise RefinementValidationError(
                f"unsupported refinement-state schema_version {self.schema_version!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": self.attributes.to_dict(),
            "is_initial": self.is_initial,
            "is_terminal": self.is_terminal,
            "label": self.label,
            "predicate_statement": self.predicate_statement,
            "schema_version": self.schema_version,
            "state_id": self.state_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> RefinementState:
        value = _mapping(value, "refinement state")
        _reject_unknown(
            value,
            frozenset(
                {
                    "state_id",
                    "label",
                    "is_initial",
                    "is_terminal",
                    "predicate_statement",
                    "attributes",
                    "schema_version",
                }
            ),
            "refinement state",
        )
        return cls(
            state_id=value.get("state_id", ""),
            label=value.get("label", ""),
            is_initial=value.get("is_initial", False),
            is_terminal=value.get("is_terminal", False),
            predicate_statement=value.get("predicate_statement", "true"),
            attributes=_frozen(
                _mapping(value.get("attributes", {}), "attributes"), "attributes"
            ),
            schema_version=value.get("schema_version", STATE_SCHEMA_VERSION),
        )


@dataclass(frozen=True, slots=True)
class RefinementTransition:
    """A labeled transition between refinement states."""

    transition_id: str
    source_state_id: str
    target_state_id: str
    action_label: str
    is_stutter: bool = False
    attributes: FrozenMap = field(default_factory=FrozenMap)
    schema_version: str = TRANSITION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "transition_id", _identifier(self.transition_id, "transition_id")
        )
        object.__setattr__(
            self, "source_state_id", _identifier(self.source_state_id, "source_state_id")
        )
        object.__setattr__(
            self, "target_state_id", _identifier(self.target_state_id, "target_state_id")
        )
        object.__setattr__(
            self, "action_label", _text(self.action_label, "action_label")
        )
        object.__setattr__(self, "is_stutter", _bool(self.is_stutter, "is_stutter"))
        object.__setattr__(self, "attributes", _frozen(self.attributes, "attributes"))
        if self.schema_version != TRANSITION_SCHEMA_VERSION:
            raise RefinementValidationError(
                f"unsupported refinement-transition schema_version "
                f"{self.schema_version!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_label": self.action_label,
            "attributes": self.attributes.to_dict(),
            "is_stutter": self.is_stutter,
            "schema_version": self.schema_version,
            "source_state_id": self.source_state_id,
            "target_state_id": self.target_state_id,
            "transition_id": self.transition_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> RefinementTransition:
        value = _mapping(value, "refinement transition")
        _reject_unknown(
            value,
            frozenset(
                {
                    "transition_id",
                    "source_state_id",
                    "target_state_id",
                    "action_label",
                    "is_stutter",
                    "attributes",
                    "schema_version",
                }
            ),
            "refinement transition",
        )
        return cls(
            transition_id=value.get("transition_id", ""),
            source_state_id=value.get("source_state_id", ""),
            target_state_id=value.get("target_state_id", ""),
            action_label=value.get("action_label", ""),
            is_stutter=value.get("is_stutter", False),
            attributes=_frozen(
                _mapping(value.get("attributes", {}), "attributes"), "attributes"
            ),
            schema_version=value.get("schema_version", TRANSITION_SCHEMA_VERSION),
        )


@dataclass(frozen=True, slots=True)
class RefinementSystem:
    """An abstract or concrete labeled transition system under refinement."""

    system_id: str
    level: SystemLevel | str
    name: str
    states: tuple[RefinementState, ...]
    transitions: tuple[RefinementTransition, ...] = ()
    concurrency_document_id: str = ""
    attributes: FrozenMap = field(default_factory=FrozenMap)
    schema_version: str = SYSTEM_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "system_id", _identifier(self.system_id, "system_id"))
        object.__setattr__(self, "level", _enum(self.level, SystemLevel, "level"))
        object.__setattr__(self, "name", _text(self.name, "name"))
        states = tuple(
            item
            if isinstance(item, RefinementState)
            else RefinementState.from_dict(_mapping(item, "refinement state"))
            for item in self.states
        )
        if not states:
            raise RefinementValidationError("refinement system requires at least one state")
        state_ids = [item.state_id for item in states]
        if len(state_ids) != len(set(state_ids)):
            raise RefinementValidationError("refinement state identifiers must be unique")
        if not any(item.is_initial for item in states):
            raise RefinementValidationError(
                "refinement system requires at least one initial state"
            )
        known_states = set(state_ids)
        transitions = tuple(
            item
            if isinstance(item, RefinementTransition)
            else RefinementTransition.from_dict(_mapping(item, "refinement transition"))
            for item in self.transitions
        )
        transition_ids = [item.transition_id for item in transitions]
        if len(transition_ids) != len(set(transition_ids)):
            raise RefinementValidationError(
                "refinement transition identifiers must be unique"
            )
        for transition in transitions:
            _known(
                (transition.source_state_id, transition.target_state_id),
                known_states,
                f"transition {transition.transition_id} endpoints",
            )
        concurrency_document_id = _optional_text(
            self.concurrency_document_id, "concurrency_document_id"
        )
        if concurrency_document_id:
            concurrency_document_id = _identifier(
                concurrency_document_id, "concurrency_document_id"
            )
        object.__setattr__(
            self, "states", tuple(sorted(states, key=lambda item: item.state_id))
        )
        object.__setattr__(
            self,
            "transitions",
            tuple(sorted(transitions, key=lambda item: item.transition_id)),
        )
        object.__setattr__(self, "concurrency_document_id", concurrency_document_id)
        object.__setattr__(self, "attributes", _frozen(self.attributes, "attributes"))
        if self.schema_version != SYSTEM_SCHEMA_VERSION:
            raise RefinementValidationError(
                f"unsupported refinement-system schema_version {self.schema_version!r}"
            )

    @property
    def state_ids(self) -> tuple[str, ...]:
        return tuple(item.state_id for item in self.states)

    @property
    def initial_state_ids(self) -> tuple[str, ...]:
        return tuple(item.state_id for item in self.states if item.is_initial)

    def successors(self, state_id: str) -> tuple[RefinementTransition, ...]:
        state_id = _identifier(state_id, "state_id")
        if state_id not in set(self.state_ids):
            raise RefinementValidationError(f"unknown state {state_id}")
        return tuple(
            transition
            for transition in self.transitions
            if transition.source_state_id == state_id
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": self.attributes.to_dict(),
            "concurrency_document_id": self.concurrency_document_id,
            "level": self.level.value,
            "name": self.name,
            "schema_version": self.schema_version,
            "states": [item.to_dict() for item in self.states],
            "system_id": self.system_id,
            "transitions": [item.to_dict() for item in self.transitions],
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> RefinementSystem:
        value = _mapping(value, "refinement system")
        _reject_unknown(
            value,
            frozenset(
                {
                    "system_id",
                    "level",
                    "name",
                    "states",
                    "transitions",
                    "concurrency_document_id",
                    "attributes",
                    "schema_version",
                }
            ),
            "refinement system",
        )
        return cls(
            system_id=value.get("system_id", ""),
            level=value.get("level", ""),
            name=value.get("name", ""),
            states=tuple(
                RefinementState.from_dict(_mapping(item, "refinement state"))
                for item in value.get("states", ())
            ),
            transitions=tuple(
                RefinementTransition.from_dict(_mapping(item, "refinement transition"))
                for item in value.get("transitions", ())
            ),
            concurrency_document_id=value.get("concurrency_document_id", ""),
            attributes=_frozen(
                _mapping(value.get("attributes", {}), "attributes"), "attributes"
            ),
            schema_version=value.get("schema_version", SYSTEM_SCHEMA_VERSION),
        )


@dataclass(frozen=True, slots=True)
class SimulationCouple:
    """A related abstract/concrete state pair under a simulation relation."""

    couple_id: str
    abstract_state_id: str
    concrete_state_id: str
    statement: str = "related"
    attributes: FrozenMap = field(default_factory=FrozenMap)
    schema_version: str = COUPLE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "couple_id", _identifier(self.couple_id, "couple_id"))
        object.__setattr__(
            self,
            "abstract_state_id",
            _identifier(self.abstract_state_id, "abstract_state_id"),
        )
        object.__setattr__(
            self,
            "concrete_state_id",
            _identifier(self.concrete_state_id, "concrete_state_id"),
        )
        object.__setattr__(self, "statement", _text(self.statement, "statement"))
        object.__setattr__(self, "attributes", _frozen(self.attributes, "attributes"))
        if self.schema_version != COUPLE_SCHEMA_VERSION:
            raise RefinementValidationError(
                f"unsupported simulation-couple schema_version {self.schema_version!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "abstract_state_id": self.abstract_state_id,
            "attributes": self.attributes.to_dict(),
            "concrete_state_id": self.concrete_state_id,
            "couple_id": self.couple_id,
            "schema_version": self.schema_version,
            "statement": self.statement,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> SimulationCouple:
        value = _mapping(value, "simulation couple")
        _reject_unknown(
            value,
            frozenset(
                {
                    "couple_id",
                    "abstract_state_id",
                    "concrete_state_id",
                    "statement",
                    "attributes",
                    "schema_version",
                }
            ),
            "simulation couple",
        )
        return cls(
            couple_id=value.get("couple_id", ""),
            abstract_state_id=value.get("abstract_state_id", ""),
            concrete_state_id=value.get("concrete_state_id", ""),
            statement=value.get("statement", "related"),
            attributes=_frozen(
                _mapping(value.get("attributes", {}), "attributes"), "attributes"
            ),
            schema_version=value.get("schema_version", COUPLE_SCHEMA_VERSION),
        )


@dataclass(frozen=True, slots=True)
class SimulationRelation:
    """A forward or backward simulation between abstract and concrete systems.

    Validation is structural: related states must exist, initial couples must
    cover all abstract (forward) or concrete (backward) initials, and every
    related source transition of the leading side must have a matching
    related target transition of the trailing side (allowing stutter).
    """

    relation_id: str
    direction: SimulationDirection | str
    abstract_system_id: str
    concrete_system_id: str
    couples: tuple[SimulationCouple, ...]
    statement: str = "simulation"
    claims_unbounded_refinement: bool = False
    max_matching_steps: int | None = None
    attributes: FrozenMap = field(default_factory=FrozenMap)
    schema_version: str = SIMULATION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "relation_id", _identifier(self.relation_id, "relation_id")
        )
        object.__setattr__(
            self, "direction", _enum(self.direction, SimulationDirection, "direction")
        )
        object.__setattr__(
            self,
            "abstract_system_id",
            _identifier(self.abstract_system_id, "abstract_system_id"),
        )
        object.__setattr__(
            self,
            "concrete_system_id",
            _identifier(self.concrete_system_id, "concrete_system_id"),
        )
        if self.abstract_system_id == self.concrete_system_id:
            raise RefinementValidationError(
                "simulation abstract and concrete systems must differ"
            )
        couples = tuple(
            item
            if isinstance(item, SimulationCouple)
            else SimulationCouple.from_dict(_mapping(item, "simulation couple"))
            for item in self.couples
        )
        if not couples:
            raise RefinementValidationError(
                "simulation relation requires at least one state couple"
            )
        couple_ids = [item.couple_id for item in couples]
        if len(couple_ids) != len(set(couple_ids)):
            raise RefinementValidationError("simulation couple identifiers must be unique")
        object.__setattr__(
            self, "couples", tuple(sorted(couples, key=lambda item: item.couple_id))
        )
        object.__setattr__(self, "statement", _text(self.statement, "statement"))
        claims = _bool(
            self.claims_unbounded_refinement, "claims_unbounded_refinement"
        )
        max_matching_steps = self.max_matching_steps
        if max_matching_steps is not None:
            max_matching_steps = _non_bool_int(max_matching_steps, "max_matching_steps")
            if max_matching_steps < 1:
                raise RefinementValidationError(
                    "max_matching_steps must be a positive integer when set"
                )
            if claims:
                raise RefinementValidationError(
                    "bounded schedules never claim unbounded refinement"
                )
        object.__setattr__(self, "claims_unbounded_refinement", claims)
        object.__setattr__(self, "max_matching_steps", max_matching_steps)
        object.__setattr__(self, "attributes", _frozen(self.attributes, "attributes"))
        if self.schema_version != SIMULATION_SCHEMA_VERSION:
            raise RefinementValidationError(
                f"unsupported simulation schema_version {self.schema_version!r}"
            )

    def related_pairs(self) -> frozenset[tuple[str, str]]:
        return frozenset(
            (item.abstract_state_id, item.concrete_state_id) for item in self.couples
        )

    def validate_against(
        self,
        abstract: RefinementSystem,
        concrete: RefinementSystem,
    ) -> None:
        """Validate structural simulation conditions against the two systems."""

        if abstract.system_id != self.abstract_system_id:
            raise RefinementValidationError(
                f"simulation {self.relation_id} abstract system mismatch"
            )
        if concrete.system_id != self.concrete_system_id:
            raise RefinementValidationError(
                f"simulation {self.relation_id} concrete system mismatch"
            )
        if abstract.level is not SystemLevel.ABSTRACT:
            raise RefinementValidationError(
                f"system {abstract.system_id} must have level 'abstract'"
            )
        if concrete.level is not SystemLevel.CONCRETE:
            raise RefinementValidationError(
                f"system {concrete.system_id} must have level 'concrete'"
            )

        abstract_ids = set(abstract.state_ids)
        concrete_ids = set(concrete.state_ids)
        related = self.related_pairs()
        for couple in self.couples:
            _known(
                (couple.abstract_state_id,),
                abstract_ids,
                f"couple {couple.couple_id}.abstract_state_id",
            )
            _known(
                (couple.concrete_state_id,),
                concrete_ids,
                f"couple {couple.couple_id}.concrete_state_id",
            )

        abstract_initials = set(abstract.initial_state_ids)
        concrete_initials = set(concrete.initial_state_ids)
        if self.direction is SimulationDirection.FORWARD:
            for initial in abstract_initials:
                if not any(
                    abstract_id == initial and concrete_id in concrete_initials
                    for abstract_id, concrete_id in related
                ):
                    raise RefinementValidationError(
                        f"forward simulation {self.relation_id} must relate abstract "
                        f"initial state {initial} to a concrete initial state"
                    )
            self._validate_forward_steps(abstract, concrete, related)
        else:
            for initial in concrete_initials:
                if not any(
                    concrete_id == initial and abstract_id in abstract_initials
                    for abstract_id, concrete_id in related
                ):
                    raise RefinementValidationError(
                        f"backward simulation {self.relation_id} must relate concrete "
                        f"initial state {initial} to an abstract initial state"
                    )
            self._validate_backward_steps(abstract, concrete, related)

    def _validate_forward_steps(
        self,
        abstract: RefinementSystem,
        concrete: RefinementSystem,
        related: frozenset[tuple[str, str]],
    ) -> None:
        for abstract_state, concrete_state in related:
            for transition in abstract.successors(abstract_state):
                if transition.is_stutter:
                    # Stutter on the abstract side is matched by remaining related.
                    if (transition.target_state_id, concrete_state) not in related:
                        # Abstract stutter may also step the concrete side.
                        if not self._has_matching_concrete(
                            concrete,
                            concrete_state,
                            transition.action_label,
                            transition.target_state_id,
                            related,
                            allow_stutter=True,
                        ):
                            raise RefinementValidationError(
                                f"forward simulation {self.relation_id} fails to match "
                                f"abstract stutter {transition.transition_id}"
                            )
                    continue
                if not self._has_matching_concrete(
                    concrete,
                    concrete_state,
                    transition.action_label,
                    transition.target_state_id,
                    related,
                    allow_stutter=True,
                ):
                    raise RefinementValidationError(
                        f"forward simulation {self.relation_id} fails to match "
                        f"abstract transition {transition.transition_id} from related "
                        f"pair ({abstract_state}, {concrete_state})"
                    )

    def _validate_backward_steps(
        self,
        abstract: RefinementSystem,
        concrete: RefinementSystem,
        related: frozenset[tuple[str, str]],
    ) -> None:
        for abstract_state, concrete_state in related:
            for transition in concrete.successors(concrete_state):
                if transition.is_stutter:
                    if (abstract_state, transition.target_state_id) not in related:
                        if not self._has_matching_abstract(
                            abstract,
                            abstract_state,
                            transition.action_label,
                            transition.target_state_id,
                            related,
                            allow_stutter=True,
                        ):
                            raise RefinementValidationError(
                                f"backward simulation {self.relation_id} fails to match "
                                f"concrete stutter {transition.transition_id}"
                            )
                    continue
                if not self._has_matching_abstract(
                    abstract,
                    abstract_state,
                    transition.action_label,
                    transition.target_state_id,
                    related,
                    allow_stutter=True,
                ):
                    raise RefinementValidationError(
                        f"backward simulation {self.relation_id} fails to match "
                        f"concrete transition {transition.transition_id} from related "
                        f"pair ({abstract_state}, {concrete_state})"
                    )

    def _has_matching_concrete(
        self,
        concrete: RefinementSystem,
        concrete_state: str,
        action_label: str,
        abstract_target: str,
        related: frozenset[tuple[str, str]],
        *,
        allow_stutter: bool,
    ) -> bool:
        # Direct matching transition.
        for transition in concrete.successors(concrete_state):
            if transition.action_label != action_label and not (
                allow_stutter and transition.is_stutter
            ):
                if transition.action_label != action_label:
                    continue
            if transition.action_label == action_label or (
                allow_stutter and transition.is_stutter
            ):
                if (abstract_target, transition.target_state_id) in related:
                    if transition.action_label == action_label or transition.is_stutter:
                        if transition.action_label == action_label:
                            return True
        for transition in concrete.successors(concrete_state):
            if transition.action_label == action_label and (
                abstract_target,
                transition.target_state_id,
            ) in related:
                return True
        if allow_stutter:
            # Finite concrete stutter chain then matching action.
            visited: set[str] = set()
            frontier = [concrete_state]
            depth = 0
            limit = self.max_matching_steps or len(concrete.states)
            while frontier and depth <= limit:
                current = frontier.pop()
                if current in visited:
                    continue
                visited.add(current)
                for transition in concrete.successors(current):
                    if transition.is_stutter and transition.target_state_id not in visited:
                        frontier.append(transition.target_state_id)
                    if transition.action_label == action_label and (
                        abstract_target,
                        transition.target_state_id,
                    ) in related:
                        return True
                depth += 1
        return False

    def _has_matching_abstract(
        self,
        abstract: RefinementSystem,
        abstract_state: str,
        action_label: str,
        concrete_target: str,
        related: frozenset[tuple[str, str]],
        *,
        allow_stutter: bool,
    ) -> bool:
        for transition in abstract.successors(abstract_state):
            if transition.action_label == action_label and (
                transition.target_state_id,
                concrete_target,
            ) in related:
                return True
        if allow_stutter:
            visited: set[str] = set()
            frontier = [abstract_state]
            depth = 0
            limit = self.max_matching_steps or len(abstract.states)
            while frontier and depth <= limit:
                current = frontier.pop()
                if current in visited:
                    continue
                visited.add(current)
                for transition in abstract.successors(current):
                    if transition.is_stutter and transition.target_state_id not in visited:
                        frontier.append(transition.target_state_id)
                    if transition.action_label == action_label and (
                        transition.target_state_id,
                        concrete_target,
                    ) in related:
                        return True
                depth += 1
        return False

    def to_dict(self) -> dict[str, Any]:
        return {
            "abstract_system_id": self.abstract_system_id,
            "attributes": self.attributes.to_dict(),
            "claims_unbounded_refinement": self.claims_unbounded_refinement,
            "concrete_system_id": self.concrete_system_id,
            "couples": [item.to_dict() for item in self.couples],
            "direction": self.direction.value,
            "max_matching_steps": self.max_matching_steps,
            "relation_id": self.relation_id,
            "schema_version": self.schema_version,
            "statement": self.statement,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> SimulationRelation:
        value = _mapping(value, "simulation relation")
        _reject_unknown(
            value,
            frozenset(
                {
                    "relation_id",
                    "direction",
                    "abstract_system_id",
                    "concrete_system_id",
                    "couples",
                    "statement",
                    "claims_unbounded_refinement",
                    "max_matching_steps",
                    "attributes",
                    "schema_version",
                }
            ),
            "simulation relation",
        )
        return cls(
            relation_id=value.get("relation_id", ""),
            direction=value.get("direction", ""),
            abstract_system_id=value.get("abstract_system_id", ""),
            concrete_system_id=value.get("concrete_system_id", ""),
            couples=tuple(
                SimulationCouple.from_dict(_mapping(item, "simulation couple"))
                for item in value.get("couples", ())
            ),
            statement=value.get("statement", "simulation"),
            claims_unbounded_refinement=value.get(
                "claims_unbounded_refinement", False
            ),
            max_matching_steps=value.get("max_matching_steps"),
            attributes=_frozen(
                _mapping(value.get("attributes", {}), "attributes"), "attributes"
            ),
            schema_version=value.get("schema_version", SIMULATION_SCHEMA_VERSION),
        )


@dataclass(frozen=True, slots=True)
class RefinementBoundedness:
    """Explicit disclosure of schedule or state-space bounds for refinement.

    When ``kind`` is :attr:`BoundednessKind.BOUNDED`, ``max_steps`` must be set
    and ``claims_unbounded_refinement`` must be false.  Unbounded claims must
    not carry finite schedule bounds.
    """

    boundedness_id: str
    kind: BoundednessKind | str
    statement: str
    max_steps: int | None = None
    max_states: int | None = None
    claims_unbounded_refinement: bool = False
    attributes: FrozenMap = field(default_factory=FrozenMap)
    schema_version: str = BOUNDEDNESS_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "boundedness_id",
            _identifier(self.boundedness_id, "boundedness_id"),
        )
        kind = _enum(self.kind, BoundednessKind, "kind")
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "statement", _text(self.statement, "statement"))
        max_steps = self.max_steps
        max_states = self.max_states
        if max_steps is not None:
            max_steps = _non_bool_int(max_steps, "max_steps")
            if max_steps < 1:
                raise RefinementValidationError("max_steps must be positive when set")
        if max_states is not None:
            max_states = _non_bool_int(max_states, "max_states")
            if max_states < 1:
                raise RefinementValidationError("max_states must be positive when set")
        claims = _bool(
            self.claims_unbounded_refinement, "claims_unbounded_refinement"
        )
        if kind is BoundednessKind.BOUNDED:
            if max_steps is None and max_states is None:
                raise RefinementValidationError(
                    "bounded refinement requires max_steps or max_states"
                )
            if claims:
                raise RefinementValidationError(
                    "bounded schedules never claim unbounded refinement"
                )
        else:
            if max_steps is not None or max_states is not None:
                raise RefinementValidationError(
                    "unbounded refinement must not declare finite schedule bounds"
                )
            if not claims:
                # Unbounded kind without the claim flag is still allowed as a
                # modeling disclosure, but the claim flag defaults false so
                # callers must set it deliberately when asserting unboundedness.
                pass
        object.__setattr__(self, "max_steps", max_steps)
        object.__setattr__(self, "max_states", max_states)
        object.__setattr__(self, "claims_unbounded_refinement", claims)
        object.__setattr__(self, "attributes", _frozen(self.attributes, "attributes"))
        if self.schema_version != BOUNDEDNESS_SCHEMA_VERSION:
            raise RefinementValidationError(
                f"unsupported boundedness schema_version {self.schema_version!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": self.attributes.to_dict(),
            "boundedness_id": self.boundedness_id,
            "claims_unbounded_refinement": self.claims_unbounded_refinement,
            "kind": self.kind.value,
            "max_states": self.max_states,
            "max_steps": self.max_steps,
            "schema_version": self.schema_version,
            "statement": self.statement,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> RefinementBoundedness:
        value = _mapping(value, "refinement boundedness")
        _reject_unknown(
            value,
            frozenset(
                {
                    "boundedness_id",
                    "kind",
                    "statement",
                    "max_steps",
                    "max_states",
                    "claims_unbounded_refinement",
                    "attributes",
                    "schema_version",
                }
            ),
            "refinement boundedness",
        )
        return cls(
            boundedness_id=value.get("boundedness_id", ""),
            kind=value.get("kind", ""),
            statement=value.get("statement", ""),
            max_steps=value.get("max_steps"),
            max_states=value.get("max_states"),
            claims_unbounded_refinement=value.get(
                "claims_unbounded_refinement", False
            ),
            attributes=_frozen(
                _mapping(value.get("attributes", {}), "attributes"), "attributes"
            ),
            schema_version=value.get("schema_version", BOUNDEDNESS_SCHEMA_VERSION),
        )


@dataclass(frozen=True, slots=True)
class RefinementObligation:
    """A refinement proof obligation, not a proof result."""

    obligation_id: str
    kind: RefinementKind | str
    statement: str
    abstract_system_id: str
    concrete_system_id: str
    simulation_relation_id: str = ""
    boundedness_id: str = ""
    claims_unbounded_refinement: bool = False
    attributes: FrozenMap = field(default_factory=FrozenMap)
    schema_version: str = OBLIGATION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "obligation_id", _identifier(self.obligation_id, "obligation_id")
        )
        object.__setattr__(self, "kind", _enum(self.kind, RefinementKind, "kind"))
        object.__setattr__(self, "statement", _text(self.statement, "statement"))
        object.__setattr__(
            self,
            "abstract_system_id",
            _identifier(self.abstract_system_id, "abstract_system_id"),
        )
        object.__setattr__(
            self,
            "concrete_system_id",
            _identifier(self.concrete_system_id, "concrete_system_id"),
        )
        simulation_relation_id = _optional_text(
            self.simulation_relation_id, "simulation_relation_id"
        )
        if simulation_relation_id:
            simulation_relation_id = _identifier(
                simulation_relation_id, "simulation_relation_id"
            )
        if self.kind is RefinementKind.SIMULATION and not simulation_relation_id:
            raise RefinementValidationError(
                "simulation obligations require simulation_relation_id"
            )
        if self.kind is RefinementKind.BISEIMULATION and not simulation_relation_id:
            raise RefinementValidationError(
                "bisimulation obligations require simulation_relation_id"
            )
        boundedness_id = _optional_text(self.boundedness_id, "boundedness_id")
        if boundedness_id:
            boundedness_id = _identifier(boundedness_id, "boundedness_id")
        claims = _bool(
            self.claims_unbounded_refinement, "claims_unbounded_refinement"
        )
        object.__setattr__(self, "simulation_relation_id", simulation_relation_id)
        object.__setattr__(self, "boundedness_id", boundedness_id)
        object.__setattr__(self, "claims_unbounded_refinement", claims)
        object.__setattr__(self, "attributes", _frozen(self.attributes, "attributes"))
        if self.schema_version != OBLIGATION_SCHEMA_VERSION:
            raise RefinementValidationError(
                f"unsupported obligation schema_version {self.schema_version!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "abstract_system_id": self.abstract_system_id,
            "attributes": self.attributes.to_dict(),
            "boundedness_id": self.boundedness_id,
            "claims_unbounded_refinement": self.claims_unbounded_refinement,
            "concrete_system_id": self.concrete_system_id,
            "kind": self.kind.value,
            "obligation_id": self.obligation_id,
            "schema_version": self.schema_version,
            "simulation_relation_id": self.simulation_relation_id,
            "statement": self.statement,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> RefinementObligation:
        value = _mapping(value, "refinement obligation")
        _reject_unknown(
            value,
            frozenset(
                {
                    "obligation_id",
                    "kind",
                    "statement",
                    "abstract_system_id",
                    "concrete_system_id",
                    "simulation_relation_id",
                    "boundedness_id",
                    "claims_unbounded_refinement",
                    "attributes",
                    "schema_version",
                }
            ),
            "refinement obligation",
        )
        return cls(
            obligation_id=value.get("obligation_id", ""),
            kind=value.get("kind", ""),
            statement=value.get("statement", ""),
            abstract_system_id=value.get("abstract_system_id", ""),
            concrete_system_id=value.get("concrete_system_id", ""),
            simulation_relation_id=value.get("simulation_relation_id", ""),
            boundedness_id=value.get("boundedness_id", ""),
            claims_unbounded_refinement=value.get(
                "claims_unbounded_refinement", False
            ),
            attributes=_frozen(
                _mapping(value.get("attributes", {}), "attributes"), "attributes"
            ),
            schema_version=value.get("schema_version", OBLIGATION_SCHEMA_VERSION),
        )


@dataclass(frozen=True, slots=True)
class RefinementIR:
    """Canonical refinement document (``RefinementIR@1``).

    Construction validates that:

    * abstract and concrete systems are level-tagged and closed;
    * forward/backward simulation relations validate structurally;
    * obligations resolve against declared systems and simulations; and
    * bounded schedules never claim unbounded refinement.
    """

    systems: tuple[RefinementSystem, ...]
    simulations: tuple[SimulationRelation, ...] = ()
    obligations: tuple[RefinementObligation, ...] = ()
    boundedness: tuple[RefinementBoundedness, ...] = ()
    metadata: FrozenMap = field(default_factory=FrozenMap)
    document_id: str = ""
    schema_version: str = REFINEMENT_IR_SCHEMA_VERSION

    INTERFACE: ClassVar[str] = REFINEMENT_IR_INTERFACE

    def __post_init__(self) -> None:
        systems = tuple(
            item
            if isinstance(item, RefinementSystem)
            else RefinementSystem.from_dict(_mapping(item, "refinement system"))
            for item in self.systems
        )
        object.__setattr__(
            self,
            "systems",
            tuple(sorted(systems, key=lambda item: item.system_id)),
        )
        simulations = tuple(
            item
            if isinstance(item, SimulationRelation)
            else SimulationRelation.from_dict(_mapping(item, "simulation"))
            for item in self.simulations
        )
        object.__setattr__(
            self,
            "simulations",
            tuple(sorted(simulations, key=lambda item: item.relation_id)),
        )
        object.__setattr__(
            self,
            "obligations",
            _coerce_records(
                self.obligations, RefinementObligation, "obligation", "obligation_id"
            ),
        )
        object.__setattr__(
            self,
            "boundedness",
            _coerce_records(
                self.boundedness,
                RefinementBoundedness,
                "boundedness",
                "boundedness_id",
            ),
        )
        object.__setattr__(self, "metadata", _frozen(self.metadata, "metadata"))
        if self.schema_version != REFINEMENT_IR_SCHEMA_VERSION:
            raise RefinementValidationError(
                f"unsupported schema_version {self.schema_version!r}"
            )
        self.validate()
        identity = self._compute_identity()
        if self.document_id and self.document_id != identity.cid:
            raise RefinementValidationError(
                "document_id does not match canonical refinement semantics"
            )
        object.__setattr__(self, "document_id", identity.cid)

    @property
    def interface(self) -> str:
        return REFINEMENT_IR_INTERFACE

    @property
    def identity(self) -> CanonicalIdentity:
        return self._compute_identity()

    @property
    def canonical_id(self) -> str:
        return self.document_id

    def system(self, system_id: str) -> RefinementSystem:
        system_id = _identifier(system_id, "system_id")
        for item in self.systems:
            if item.system_id == system_id:
                return item
        raise RefinementValidationError(f"unknown refinement system {system_id}")

    def abstract_systems(self) -> tuple[RefinementSystem, ...]:
        return tuple(item for item in self.systems if item.level is SystemLevel.ABSTRACT)

    def concrete_systems(self) -> tuple[RefinementSystem, ...]:
        return tuple(item for item in self.systems if item.level is SystemLevel.CONCRETE)

    def validate(self) -> None:
        def unique(values: Sequence[object], attr: str, label: str) -> set[str]:
            ids = [getattr(item, attr) for item in values]
            if len(ids) != len(set(ids)):
                raise RefinementValidationError(f"duplicate {label} identifiers")
            return set(ids)

        if not self.systems:
            raise RefinementValidationError(
                "RefinementIR requires at least one refinement system"
            )

        system_ids = unique(self.systems, "system_id", "system")
        simulation_ids = unique(self.simulations, "relation_id", "simulation")
        obligation_ids = unique(self.obligations, "obligation_id", "obligation")
        boundedness_ids = unique(self.boundedness, "boundedness_id", "boundedness")
        del obligation_ids

        systems_by_id = {item.system_id: item for item in self.systems}
        if not self.abstract_systems():
            raise RefinementValidationError(
                "RefinementIR requires at least one abstract system"
            )
        if not self.concrete_systems():
            raise RefinementValidationError(
                "RefinementIR requires at least one concrete system"
            )

        for simulation in self.simulations:
            if simulation.abstract_system_id not in system_ids:
                raise RefinementValidationError(
                    f"simulation {simulation.relation_id} references unknown abstract "
                    f"system"
                )
            if simulation.concrete_system_id not in system_ids:
                raise RefinementValidationError(
                    f"simulation {simulation.relation_id} references unknown concrete "
                    f"system"
                )
            abstract = systems_by_id[simulation.abstract_system_id]
            concrete = systems_by_id[simulation.concrete_system_id]
            simulation.validate_against(abstract, concrete)
            if (
                simulation.max_matching_steps is not None
                and simulation.claims_unbounded_refinement
            ):
                raise RefinementValidationError(
                    "bounded schedules never claim unbounded refinement"
                )

        for obligation in self.obligations:
            _known(
                (obligation.abstract_system_id, obligation.concrete_system_id),
                system_ids,
                f"obligation {obligation.obligation_id} systems",
            )
            if systems_by_id[obligation.abstract_system_id].level is not SystemLevel.ABSTRACT:
                raise RefinementValidationError(
                    f"obligation {obligation.obligation_id} abstract_system_id must "
                    "reference an abstract system"
                )
            if systems_by_id[obligation.concrete_system_id].level is not SystemLevel.CONCRETE:
                raise RefinementValidationError(
                    f"obligation {obligation.obligation_id} concrete_system_id must "
                    "reference a concrete system"
                )
            if obligation.simulation_relation_id:
                _known(
                    (obligation.simulation_relation_id,),
                    simulation_ids,
                    f"obligation {obligation.obligation_id}.simulation_relation_id",
                )
            if obligation.boundedness_id:
                _known(
                    (obligation.boundedness_id,),
                    boundedness_ids,
                    f"obligation {obligation.obligation_id}.boundedness_id",
                )
                bound = next(
                    item
                    for item in self.boundedness
                    if item.boundedness_id == obligation.boundedness_id
                )
                if (
                    bound.kind is BoundednessKind.BOUNDED
                    and obligation.claims_unbounded_refinement
                ):
                    raise RefinementValidationError(
                        "bounded schedules never claim unbounded refinement"
                    )
                if (
                    bound.kind is BoundednessKind.BOUNDED
                    and bound.claims_unbounded_refinement
                ):
                    raise RefinementValidationError(
                        "bounded schedules never claim unbounded refinement"
                    )

        for bound in self.boundedness:
            if bound.kind is BoundednessKind.BOUNDED and bound.claims_unbounded_refinement:
                raise RefinementValidationError(
                    "bounded schedules never claim unbounded refinement"
                )

    def semantic_dict(self) -> dict[str, Any]:
        return {
            "boundedness": [item.to_dict() for item in self.boundedness],
            "interface": REFINEMENT_IR_INTERFACE,
            "metadata": self.metadata.to_dict(),
            "obligations": [item.to_dict() for item in self.obligations],
            "schema_version": self.schema_version,
            "simulations": [item.to_dict() for item in self.simulations],
            "systems": [item.to_dict() for item in self.systems],
        }

    deterministic_dict = semantic_dict

    def to_dict(self) -> dict[str, Any]:
        result = self.semantic_dict()
        result["document_id"] = self.document_id
        return result

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())

    def semantic_bytes(self) -> bytes:
        return self.identity.canonical_bytes

    def _compute_identity(self) -> CanonicalIdentity:
        return canonical_identity(
            self.semantic_dict(),
            domain=REFINEMENT_IR_IDENTITY_DOMAIN,
            schema_version=self.schema_version,
        )

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> RefinementIR:
        value = _mapping(value, "refinement ir")
        _reject_unknown(
            value,
            frozenset(
                {
                    "systems",
                    "simulations",
                    "obligations",
                    "boundedness",
                    "metadata",
                    "document_id",
                    "schema_version",
                    "interface",
                }
            ),
            "refinement ir",
        )
        return cls(
            systems=tuple(
                RefinementSystem.from_dict(_mapping(item, "refinement system"))
                for item in value.get("systems", ())
            ),
            simulations=tuple(
                SimulationRelation.from_dict(_mapping(item, "simulation"))
                for item in value.get("simulations", ())
            ),
            obligations=tuple(
                RefinementObligation.from_dict(_mapping(item, "obligation"))
                for item in value.get("obligations", ())
            ),
            boundedness=tuple(
                RefinementBoundedness.from_dict(_mapping(item, "boundedness"))
                for item in value.get("boundedness", ())
            ),
            metadata=_frozen(
                _mapping(value.get("metadata", {}), "metadata"), "metadata"
            ),
            document_id=value.get("document_id", ""),
            schema_version=value.get("schema_version", REFINEMENT_IR_SCHEMA_VERSION),
        )


__all__ = [
    "BOUNDEDNESS_SCHEMA_VERSION",
    "COUPLE_SCHEMA_VERSION",
    "OBLIGATION_SCHEMA_VERSION",
    "REFINEMENT_IR_IDENTITY_DOMAIN",
    "REFINEMENT_IR_INTERFACE",
    "REFINEMENT_IR_SCHEMA_VERSION",
    "SIMULATION_SCHEMA_VERSION",
    "STATE_SCHEMA_VERSION",
    "SYSTEM_SCHEMA_VERSION",
    "TRANSITION_SCHEMA_VERSION",
    "BoundednessKind",
    "RefinementBoundedness",
    "RefinementIR",
    "RefinementKind",
    "RefinementObligation",
    "RefinementState",
    "RefinementSystem",
    "RefinementTransition",
    "RefinementValidationError",
    "SimulationCouple",
    "SimulationDirection",
    "SimulationRelation",
    "SystemLevel",
]
