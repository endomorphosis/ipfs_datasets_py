"""Action systems, transition relations, fairness, and Kripke structures.

``StateTransitionIR@1`` assembles a typed state schema with actions (each
exposing an explicit read/write frame), transition relations, fairness
constraints, invariants, variants, labels, and an optional finite Kripke
structure.  The module never emits TLA+ or SMT syntax and never runs a model
checker; invalid or ambiguous transition systems fail closed at construction.
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

from .state import (
    PredicateRole,
    StateLabel,
    StatePredicate,
    StateSchema,
    StateValidationError,
    StateValuation,
    StateVariable,
    VariantMeasure,
    _enum as _state_enum,
    _frozen as _state_frozen,
    _identifier as _state_identifier,
    _ids as _state_ids,
    _known as _state_known,
    _mapping as _state_mapping,
    _reject_unknown as _state_reject_unknown,
    _text as _state_text,
)

STATE_TRANSITION_IR_INTERFACE: Final = "StateTransitionIR@1"
STATE_TRANSITION_IR_SCHEMA_VERSION: Final = "state-transition-ir/v1"
STATE_TRANSITION_IR_IDENTITY_DOMAIN: Final = (
    "logic.software-verification.state-transition"
)
ACTION_FRAME_SCHEMA_VERSION: Final = "action-frame/v1"
ACTION_SCHEMA_VERSION: Final = "action/v1"
TRANSITION_RELATION_SCHEMA_VERSION: Final = "transition-relation/v1"
FAIRNESS_SCHEMA_VERSION: Final = "fairness-constraint/v1"
KRIPKE_WORLD_SCHEMA_VERSION: Final = "kripke-world/v1"
KRIPKE_EDGE_SCHEMA_VERSION: Final = "kripke-edge/v1"
KRIPKE_STRUCTURE_SCHEMA_VERSION: Final = "kripke-structure/v1"

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")


class TransitionValidationError(ValueError):
    """Raised when actions, transitions, fairness, or Kripke models are invalid."""


class FairnessKind(StrEnum):
    """Standard fairness strengths over action or predicate sets."""

    WEAK = "weak"
    STRONG = "strong"
    UNCONDITIONAL = "unconditional"


class TransitionKind(StrEnum):
    """How a transition relation is expressed."""

    ACTION = "action"
    RELATION = "relation"
    STUTTER = "stutter"


def _text(value: object, label: str) -> str:
    try:
        return _state_text(value, label)
    except StateValidationError as error:
        raise TransitionValidationError(str(error)) from error


def _identifier(value: object, label: str) -> str:
    try:
        return _state_identifier(value, label)
    except StateValidationError as error:
        raise TransitionValidationError(str(error)) from error


def _ids(
    values: Sequence[str] | object,
    label: str,
    *,
    preserve_order: bool = False,
) -> tuple[str, ...]:
    try:
        return _state_ids(values, label, preserve_order=preserve_order)
    except StateValidationError as error:
        raise TransitionValidationError(str(error)) from error


def _enum(value: object, enum_type: type[StrEnum], label: str) -> Any:
    try:
        return _state_enum(value, enum_type, label)
    except StateValidationError as error:
        raise TransitionValidationError(str(error)) from error


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    try:
        return _state_mapping(value, label)
    except StateValidationError as error:
        raise TransitionValidationError(str(error)) from error


def _frozen(value: Mapping[str, Any] | FrozenMap, label: str) -> FrozenMap:
    try:
        return _state_frozen(value, label)
    except StateValidationError as error:
        raise TransitionValidationError(str(error)) from error


def _reject_unknown(value: Mapping[str, Any], allowed: frozenset[str], label: str) -> None:
    try:
        _state_reject_unknown(value, allowed, label)
    except StateValidationError as error:
        raise TransitionValidationError(str(error)) from error


def _known(values: Sequence[str], known: set[str], label: str) -> None:
    try:
        _state_known(values, known, label)
    except StateValidationError as error:
        raise TransitionValidationError(str(error)) from error


def _bool(value: object, label: str) -> bool:
    if not isinstance(value, bool):
        raise TransitionValidationError(f"{label} must be a boolean")
    return value


@dataclass(frozen=True, slots=True)
class ActionFrame:
    """Explicit read and write sets for an action.

    Empty tuples with ``allows_all_*`` false mean "none", never "unspecified".
    """

    reads: tuple[str, ...] = ()
    writes: tuple[str, ...] = ()
    allows_all_reads: bool = False
    allows_all_writes: bool = False
    schema_version: str = ACTION_FRAME_SCHEMA_VERSION

    def __post_init__(self) -> None:
        reads = _ids(self.reads, "reads")
        writes = _ids(self.writes, "writes")
        allows_all_reads = _bool(self.allows_all_reads, "allows_all_reads")
        allows_all_writes = _bool(self.allows_all_writes, "allows_all_writes")
        if allows_all_reads and reads:
            raise TransitionValidationError("reads cannot accompany allows_all_reads")
        if allows_all_writes and writes:
            raise TransitionValidationError("writes cannot accompany allows_all_writes")
        object.__setattr__(self, "reads", reads)
        object.__setattr__(self, "writes", writes)
        object.__setattr__(self, "allows_all_reads", allows_all_reads)
        object.__setattr__(self, "allows_all_writes", allows_all_writes)
        if self.schema_version != ACTION_FRAME_SCHEMA_VERSION:
            raise TransitionValidationError(
                f"unsupported action-frame schema_version {self.schema_version!r}"
            )

    def permits_access(
        self,
        *,
        read_variable_ids: Sequence[str] = (),
        write_variable_ids: Sequence[str] = (),
    ) -> bool:
        reads = set(read_variable_ids)
        writes = set(write_variable_ids)
        return (self.allows_all_reads or reads <= set(self.reads)) and (
            self.allows_all_writes or writes <= set(self.writes)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "allows_all_reads": self.allows_all_reads,
            "allows_all_writes": self.allows_all_writes,
            "reads": list(self.reads),
            "schema_version": self.schema_version,
            "writes": list(self.writes),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> ActionFrame:
        value = _mapping(value, "action frame")
        _reject_unknown(
            value,
            frozenset(
                {
                    "reads",
                    "writes",
                    "allows_all_reads",
                    "allows_all_writes",
                    "schema_version",
                }
            ),
            "action frame",
        )
        return cls(
            reads=tuple(value.get("reads", ())),
            writes=tuple(value.get("writes", ())),
            allows_all_reads=value.get("allows_all_reads", False),
            allows_all_writes=value.get("allows_all_writes", False),
            schema_version=value.get("schema_version", ACTION_FRAME_SCHEMA_VERSION),
        )


@dataclass(frozen=True, slots=True)
class Action:
    """A named action with a guard, next-state relation, and read/write frame."""

    action_id: str
    name: str
    frame: ActionFrame
    guard_predicate_id: str = ""
    next_predicate_id: str = ""
    label_ids: tuple[str, ...] = ()
    enables_stutter: bool = False
    attributes: FrozenMap = field(default_factory=FrozenMap)
    source_ref_ids: tuple[str, ...] = ()
    schema_version: str = ACTION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "action_id", _identifier(self.action_id, "action_id"))
        object.__setattr__(self, "name", _text(self.name, "name"))
        frame = self.frame
        if isinstance(frame, Mapping):
            frame = ActionFrame.from_dict(frame)
        if not isinstance(frame, ActionFrame):
            raise TransitionValidationError("frame must be an ActionFrame")
        object.__setattr__(self, "frame", frame)
        guard = self.guard_predicate_id
        next_pred = self.next_predicate_id
        object.__setattr__(
            self,
            "guard_predicate_id",
            "" if not guard else _identifier(guard, "guard_predicate_id"),
        )
        object.__setattr__(
            self,
            "next_predicate_id",
            "" if not next_pred else _identifier(next_pred, "next_predicate_id"),
        )
        if not self.guard_predicate_id and not self.next_predicate_id:
            raise TransitionValidationError(
                f"action {self.action_id} requires a guard or next predicate"
            )
        object.__setattr__(self, "label_ids", _ids(self.label_ids, "label_ids"))
        object.__setattr__(
            self, "enables_stutter", _bool(self.enables_stutter, "enables_stutter")
        )
        object.__setattr__(self, "attributes", _frozen(self.attributes, "attributes"))
        object.__setattr__(
            self, "source_ref_ids", _ids(self.source_ref_ids, "source_ref_ids")
        )
        if self.schema_version != ACTION_SCHEMA_VERSION:
            raise TransitionValidationError(
                f"unsupported action schema_version {self.schema_version!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_id": self.action_id,
            "attributes": self.attributes.to_dict(),
            "enables_stutter": self.enables_stutter,
            "frame": self.frame.to_dict(),
            "guard_predicate_id": self.guard_predicate_id,
            "label_ids": list(self.label_ids),
            "name": self.name,
            "next_predicate_id": self.next_predicate_id,
            "schema_version": self.schema_version,
            "source_ref_ids": list(self.source_ref_ids),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> Action:
        value = _mapping(value, "action")
        _reject_unknown(
            value,
            frozenset(
                {
                    "action_id",
                    "name",
                    "frame",
                    "guard_predicate_id",
                    "next_predicate_id",
                    "label_ids",
                    "enables_stutter",
                    "attributes",
                    "source_ref_ids",
                    "schema_version",
                }
            ),
            "action",
        )
        return cls(
            action_id=value.get("action_id", ""),
            name=value.get("name", ""),
            frame=ActionFrame.from_dict(_mapping(value.get("frame", {}), "frame")),
            guard_predicate_id=value.get("guard_predicate_id", ""),
            next_predicate_id=value.get("next_predicate_id", ""),
            label_ids=tuple(value.get("label_ids", ())),
            enables_stutter=value.get("enables_stutter", False),
            attributes=_frozen(
                _mapping(value.get("attributes", {}), "attributes"), "attributes"
            ),
            source_ref_ids=tuple(value.get("source_ref_ids", ())),
            schema_version=value.get("schema_version", ACTION_SCHEMA_VERSION),
        )


@dataclass(frozen=True, slots=True)
class TransitionRelation:
    """A named transition relation over pre/post states or actions."""

    relation_id: str
    kind: TransitionKind | str
    statement: str
    action_ids: tuple[str, ...] = ()
    predicate_id: str = ""
    allows_stutter: bool = False
    attributes: FrozenMap = field(default_factory=FrozenMap)
    source_ref_ids: tuple[str, ...] = ()
    schema_version: str = TRANSITION_RELATION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "relation_id", _identifier(self.relation_id, "relation_id")
        )
        kind = _enum(self.kind, TransitionKind, "kind")
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "statement", _text(self.statement, "statement"))
        action_ids = _ids(self.action_ids, "action_ids")
        object.__setattr__(self, "action_ids", action_ids)
        predicate_id = self.predicate_id
        object.__setattr__(
            self,
            "predicate_id",
            "" if not predicate_id else _identifier(predicate_id, "predicate_id"),
        )
        object.__setattr__(
            self, "allows_stutter", _bool(self.allows_stutter, "allows_stutter")
        )
        object.__setattr__(self, "attributes", _frozen(self.attributes, "attributes"))
        object.__setattr__(
            self, "source_ref_ids", _ids(self.source_ref_ids, "source_ref_ids")
        )
        if kind is TransitionKind.ACTION and not action_ids:
            raise TransitionValidationError(
                f"action transition {self.relation_id} requires action_ids"
            )
        if kind is TransitionKind.RELATION and not self.predicate_id:
            raise TransitionValidationError(
                f"relation transition {self.relation_id} requires predicate_id"
            )
        if kind is TransitionKind.STUTTER and (action_ids or self.predicate_id):
            raise TransitionValidationError(
                f"stutter transition {self.relation_id} must not reference actions or predicates"
            )
        if kind is not TransitionKind.ACTION and action_ids:
            raise TransitionValidationError(
                "action_ids are only valid for action transitions"
            )
        if kind is not TransitionKind.RELATION and self.predicate_id:
            raise TransitionValidationError(
                "predicate_id is only valid for relation transitions"
            )
        if self.schema_version != TRANSITION_RELATION_SCHEMA_VERSION:
            raise TransitionValidationError(
                f"unsupported transition-relation schema_version {self.schema_version!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_ids": list(self.action_ids),
            "allows_stutter": self.allows_stutter,
            "attributes": self.attributes.to_dict(),
            "kind": self.kind.value,
            "predicate_id": self.predicate_id,
            "relation_id": self.relation_id,
            "schema_version": self.schema_version,
            "source_ref_ids": list(self.source_ref_ids),
            "statement": self.statement,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> TransitionRelation:
        value = _mapping(value, "transition relation")
        _reject_unknown(
            value,
            frozenset(
                {
                    "relation_id",
                    "kind",
                    "statement",
                    "action_ids",
                    "predicate_id",
                    "allows_stutter",
                    "attributes",
                    "source_ref_ids",
                    "schema_version",
                }
            ),
            "transition relation",
        )
        return cls(
            relation_id=value.get("relation_id", ""),
            kind=value.get("kind", ""),
            statement=value.get("statement", ""),
            action_ids=tuple(value.get("action_ids", ())),
            predicate_id=value.get("predicate_id", ""),
            allows_stutter=value.get("allows_stutter", False),
            attributes=_frozen(
                _mapping(value.get("attributes", {}), "attributes"), "attributes"
            ),
            source_ref_ids=tuple(value.get("source_ref_ids", ())),
            schema_version=value.get(
                "schema_version", TRANSITION_RELATION_SCHEMA_VERSION
            ),
        )


@dataclass(frozen=True, slots=True)
class FairnessConstraint:
    """A fairness obligation over actions or fairness-role predicates."""

    fairness_id: str
    kind: FairnessKind | str
    statement: str
    action_ids: tuple[str, ...] = ()
    predicate_id: str = ""
    attributes: FrozenMap = field(default_factory=FrozenMap)
    source_ref_ids: tuple[str, ...] = ()
    schema_version: str = FAIRNESS_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "fairness_id", _identifier(self.fairness_id, "fairness_id")
        )
        object.__setattr__(self, "kind", _enum(self.kind, FairnessKind, "kind"))
        object.__setattr__(self, "statement", _text(self.statement, "statement"))
        action_ids = _ids(self.action_ids, "action_ids")
        object.__setattr__(self, "action_ids", action_ids)
        predicate_id = self.predicate_id
        object.__setattr__(
            self,
            "predicate_id",
            "" if not predicate_id else _identifier(predicate_id, "predicate_id"),
        )
        if not action_ids and not self.predicate_id:
            raise TransitionValidationError(
                f"fairness constraint {self.fairness_id} requires action_ids or predicate_id"
            )
        if action_ids and self.predicate_id:
            raise TransitionValidationError(
                f"fairness constraint {self.fairness_id} cannot mix action_ids and predicate_id"
            )
        object.__setattr__(self, "attributes", _frozen(self.attributes, "attributes"))
        object.__setattr__(
            self, "source_ref_ids", _ids(self.source_ref_ids, "source_ref_ids")
        )
        if self.schema_version != FAIRNESS_SCHEMA_VERSION:
            raise TransitionValidationError(
                f"unsupported fairness schema_version {self.schema_version!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_ids": list(self.action_ids),
            "attributes": self.attributes.to_dict(),
            "fairness_id": self.fairness_id,
            "kind": self.kind.value,
            "predicate_id": self.predicate_id,
            "schema_version": self.schema_version,
            "source_ref_ids": list(self.source_ref_ids),
            "statement": self.statement,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> FairnessConstraint:
        value = _mapping(value, "fairness constraint")
        _reject_unknown(
            value,
            frozenset(
                {
                    "fairness_id",
                    "kind",
                    "statement",
                    "action_ids",
                    "predicate_id",
                    "attributes",
                    "source_ref_ids",
                    "schema_version",
                }
            ),
            "fairness constraint",
        )
        return cls(
            fairness_id=value.get("fairness_id", ""),
            kind=value.get("kind", ""),
            statement=value.get("statement", ""),
            action_ids=tuple(value.get("action_ids", ())),
            predicate_id=value.get("predicate_id", ""),
            attributes=_frozen(
                _mapping(value.get("attributes", {}), "attributes"), "attributes"
            ),
            source_ref_ids=tuple(value.get("source_ref_ids", ())),
            schema_version=value.get("schema_version", FAIRNESS_SCHEMA_VERSION),
        )


@dataclass(frozen=True, slots=True)
class KripkeWorld:
    """One world in a finite Kripke structure."""

    world_id: str
    valuation_id: str = ""
    label_ids: tuple[str, ...] = ()
    attributes: FrozenMap = field(default_factory=FrozenMap)
    schema_version: str = KRIPKE_WORLD_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "world_id", _identifier(self.world_id, "world_id"))
        valuation_id = self.valuation_id
        object.__setattr__(
            self,
            "valuation_id",
            "" if not valuation_id else _identifier(valuation_id, "valuation_id"),
        )
        object.__setattr__(self, "label_ids", _ids(self.label_ids, "label_ids"))
        object.__setattr__(self, "attributes", _frozen(self.attributes, "attributes"))
        if self.schema_version != KRIPKE_WORLD_SCHEMA_VERSION:
            raise TransitionValidationError(
                f"unsupported kripke-world schema_version {self.schema_version!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": self.attributes.to_dict(),
            "label_ids": list(self.label_ids),
            "schema_version": self.schema_version,
            "valuation_id": self.valuation_id,
            "world_id": self.world_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> KripkeWorld:
        value = _mapping(value, "kripke world")
        _reject_unknown(
            value,
            frozenset(
                {
                    "world_id",
                    "valuation_id",
                    "label_ids",
                    "attributes",
                    "schema_version",
                }
            ),
            "kripke world",
        )
        return cls(
            world_id=value.get("world_id", ""),
            valuation_id=value.get("valuation_id", ""),
            label_ids=tuple(value.get("label_ids", ())),
            attributes=_frozen(
                _mapping(value.get("attributes", {}), "attributes"), "attributes"
            ),
            schema_version=value.get("schema_version", KRIPKE_WORLD_SCHEMA_VERSION),
        )


@dataclass(frozen=True, slots=True)
class KripkeEdge:
    """A directed accessibility edge in a finite Kripke structure."""

    edge_id: str
    source_world_id: str
    target_world_id: str
    action_id: str = ""
    label_ids: tuple[str, ...] = ()
    attributes: FrozenMap = field(default_factory=FrozenMap)
    schema_version: str = KRIPKE_EDGE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "edge_id", _identifier(self.edge_id, "edge_id"))
        object.__setattr__(
            self,
            "source_world_id",
            _identifier(self.source_world_id, "source_world_id"),
        )
        object.__setattr__(
            self,
            "target_world_id",
            _identifier(self.target_world_id, "target_world_id"),
        )
        action_id = self.action_id
        object.__setattr__(
            self,
            "action_id",
            "" if not action_id else _identifier(action_id, "action_id"),
        )
        object.__setattr__(self, "label_ids", _ids(self.label_ids, "label_ids"))
        object.__setattr__(self, "attributes", _frozen(self.attributes, "attributes"))
        if self.schema_version != KRIPKE_EDGE_SCHEMA_VERSION:
            raise TransitionValidationError(
                f"unsupported kripke-edge schema_version {self.schema_version!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_id": self.action_id,
            "attributes": self.attributes.to_dict(),
            "edge_id": self.edge_id,
            "label_ids": list(self.label_ids),
            "schema_version": self.schema_version,
            "source_world_id": self.source_world_id,
            "target_world_id": self.target_world_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> KripkeEdge:
        value = _mapping(value, "kripke edge")
        _reject_unknown(
            value,
            frozenset(
                {
                    "edge_id",
                    "source_world_id",
                    "target_world_id",
                    "action_id",
                    "label_ids",
                    "attributes",
                    "schema_version",
                }
            ),
            "kripke edge",
        )
        return cls(
            edge_id=value.get("edge_id", ""),
            source_world_id=value.get("source_world_id", ""),
            target_world_id=value.get("target_world_id", ""),
            action_id=value.get("action_id", ""),
            label_ids=tuple(value.get("label_ids", ())),
            attributes=_frozen(
                _mapping(value.get("attributes", {}), "attributes"), "attributes"
            ),
            schema_version=value.get("schema_version", KRIPKE_EDGE_SCHEMA_VERSION),
        )


@dataclass(frozen=True, slots=True)
class KripkeStructure:
    """A finite Kripke structure over labeled worlds and accessibility edges."""

    structure_id: str
    worlds: tuple[KripkeWorld, ...]
    edges: tuple[KripkeEdge, ...]
    initial_world_ids: tuple[str, ...]
    attributes: FrozenMap = field(default_factory=FrozenMap)
    schema_version: str = KRIPKE_STRUCTURE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "structure_id", _identifier(self.structure_id, "structure_id")
        )
        worlds = tuple(
            item
            if isinstance(item, KripkeWorld)
            else KripkeWorld.from_dict(_mapping(item, "kripke world"))
            for item in self.worlds
        )
        edges = tuple(
            item
            if isinstance(item, KripkeEdge)
            else KripkeEdge.from_dict(_mapping(item, "kripke edge"))
            for item in self.edges
        )
        worlds = tuple(sorted(worlds, key=lambda item: item.world_id))
        edges = tuple(sorted(edges, key=lambda item: item.edge_id))
        object.__setattr__(self, "worlds", worlds)
        object.__setattr__(self, "edges", edges)
        object.__setattr__(
            self,
            "initial_world_ids",
            _ids(self.initial_world_ids, "initial_world_ids"),
        )
        object.__setattr__(self, "attributes", _frozen(self.attributes, "attributes"))
        if self.schema_version != KRIPKE_STRUCTURE_SCHEMA_VERSION:
            raise TransitionValidationError(
                f"unsupported kripke-structure schema_version {self.schema_version!r}"
            )
        self.validate()

    def validate(self) -> None:
        if not self.worlds:
            raise TransitionValidationError("a Kripke structure requires at least one world")
        world_ids = [item.world_id for item in self.worlds]
        if len(world_ids) != len(set(world_ids)):
            raise TransitionValidationError("Kripke world identifiers must be unique")
        edge_ids = [item.edge_id for item in self.edges]
        if len(edge_ids) != len(set(edge_ids)):
            raise TransitionValidationError("Kripke edge identifiers must be unique")
        known_worlds = set(world_ids)
        _known(self.initial_world_ids, known_worlds, "initial_world_ids")
        if not self.initial_world_ids:
            raise TransitionValidationError(
                "a Kripke structure requires at least one initial world"
            )
        for edge in self.edges:
            _known((edge.source_world_id,), known_worlds, f"edge {edge.edge_id}.source")
            _known((edge.target_world_id,), known_worlds, f"edge {edge.edge_id}.target")

    def successors(self, world_id: str) -> tuple[str, ...]:
        world_id = _identifier(world_id, "world_id")
        known = {item.world_id for item in self.worlds}
        if world_id not in known:
            raise TransitionValidationError(f"unknown world {world_id}")
        return tuple(
            edge.target_world_id
            for edge in self.edges
            if edge.source_world_id == world_id
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": self.attributes.to_dict(),
            "edges": [item.to_dict() for item in self.edges],
            "initial_world_ids": list(self.initial_world_ids),
            "schema_version": self.schema_version,
            "structure_id": self.structure_id,
            "worlds": [item.to_dict() for item in self.worlds],
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> KripkeStructure:
        value = _mapping(value, "kripke structure")
        _reject_unknown(
            value,
            frozenset(
                {
                    "structure_id",
                    "worlds",
                    "edges",
                    "initial_world_ids",
                    "attributes",
                    "schema_version",
                }
            ),
            "kripke structure",
        )
        return cls(
            structure_id=value.get("structure_id", ""),
            worlds=tuple(
                KripkeWorld.from_dict(_mapping(item, "kripke world"))
                for item in value.get("worlds", ())
            ),
            edges=tuple(
                KripkeEdge.from_dict(_mapping(item, "kripke edge"))
                for item in value.get("edges", ())
            ),
            initial_world_ids=tuple(value.get("initial_world_ids", ())),
            attributes=_frozen(
                _mapping(value.get("attributes", {}), "attributes"), "attributes"
            ),
            schema_version=value.get(
                "schema_version", KRIPKE_STRUCTURE_SCHEMA_VERSION
            ),
        )


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
class StateTransitionIR:
    """Canonical closed action-system and Kripke document (``StateTransitionIR@1``).

    Construction validates that:

    * the state schema is typed and deterministic;
    * every action exposes a read/write frame over known variables;
    * initial, next, invariant, and fairness predicates keep distinct roles;
    * finite bounds remain explicit on finite variables;
    * transition relations, fairness, valuations, and Kripke edges resolve
      closed-world against declared identifiers; and
    * ambiguous sole-next action systems fail closed.
    """

    schema: StateSchema
    predicates: tuple[StatePredicate, ...]
    actions: tuple[Action, ...] = ()
    transitions: tuple[TransitionRelation, ...] = ()
    fairness: tuple[FairnessConstraint, ...] = ()
    labels: tuple[StateLabel, ...] = ()
    variants: tuple[VariantMeasure, ...] = ()
    valuations: tuple[StateValuation, ...] = ()
    kripke: KripkeStructure | None = None
    metadata: FrozenMap = field(default_factory=FrozenMap)
    document_id: str = ""
    schema_version: str = STATE_TRANSITION_IR_SCHEMA_VERSION

    INTERFACE: ClassVar[str] = STATE_TRANSITION_IR_INTERFACE

    def __post_init__(self) -> None:
        schema = self.schema
        if isinstance(schema, Mapping):
            schema = StateSchema.from_dict(schema)
        if not isinstance(schema, StateSchema):
            raise TransitionValidationError("schema must be a StateSchema")
        object.__setattr__(self, "schema", schema)

        object.__setattr__(
            self,
            "predicates",
            _coerce_records(self.predicates, StatePredicate, "predicate", "predicate_id"),
        )
        object.__setattr__(
            self,
            "actions",
            _coerce_records(self.actions, Action, "action", "action_id"),
        )
        object.__setattr__(
            self,
            "transitions",
            _coerce_records(
                self.transitions, TransitionRelation, "transition", "relation_id"
            ),
        )
        object.__setattr__(
            self,
            "fairness",
            _coerce_records(self.fairness, FairnessConstraint, "fairness", "fairness_id"),
        )
        object.__setattr__(
            self,
            "labels",
            _coerce_records(self.labels, StateLabel, "label", "label_id"),
        )
        object.__setattr__(
            self,
            "variants",
            _coerce_records(self.variants, VariantMeasure, "variant", "variant_id"),
        )
        object.__setattr__(
            self,
            "valuations",
            _coerce_records(
                self.valuations, StateValuation, "valuation", "valuation_id"
            ),
        )

        kripke = self.kripke
        if isinstance(kripke, Mapping):
            kripke = KripkeStructure.from_dict(kripke)
        if kripke is not None and not isinstance(kripke, KripkeStructure):
            raise TransitionValidationError("kripke must be a KripkeStructure")
        object.__setattr__(self, "kripke", kripke)
        object.__setattr__(self, "metadata", _frozen(self.metadata, "metadata"))

        if self.schema_version != STATE_TRANSITION_IR_SCHEMA_VERSION:
            raise TransitionValidationError(
                f"unsupported schema_version {self.schema_version!r}"
            )

        self.validate()
        identity = self._compute_identity()
        if self.document_id and self.document_id != identity.cid:
            raise TransitionValidationError(
                "document_id does not match canonical state-transition semantics"
            )
        object.__setattr__(self, "document_id", identity.cid)

    @property
    def interface(self) -> str:
        return STATE_TRANSITION_IR_INTERFACE

    @property
    def identity(self) -> CanonicalIdentity:
        return self._compute_identity()

    @property
    def canonical_id(self) -> str:
        return self.document_id

    def predicates_by_role(self, role: PredicateRole | str) -> tuple[StatePredicate, ...]:
        role_value = role if isinstance(role, PredicateRole) else PredicateRole(role)
        return tuple(item for item in self.predicates if item.role is role_value)

    def validate(self) -> None:
        variable_ids = set(self.schema.variable_ids)

        def unique(values: Sequence[object], attr: str, label: str) -> set[str]:
            ids = [getattr(item, attr) for item in values]
            if len(ids) != len(set(ids)):
                raise TransitionValidationError(f"duplicate {label} identifiers")
            return set(ids)

        predicate_ids = unique(self.predicates, "predicate_id", "predicate")
        action_ids = unique(self.actions, "action_id", "action")
        transition_ids = unique(self.transitions, "relation_id", "transition")
        fairness_ids = unique(self.fairness, "fairness_id", "fairness")
        label_ids = unique(self.labels, "label_id", "label")
        variant_ids = unique(self.variants, "variant_id", "variant")
        valuation_ids = unique(self.valuations, "valuation_id", "valuation")
        del transition_ids, fairness_ids, variant_ids  # uniqueness only

        label_names = [item.name for item in self.labels]
        if len(label_names) != len(set(label_names)):
            raise TransitionValidationError("state label names must be unique")

        action_names = [item.name for item in self.actions]
        if len(action_names) != len(set(action_names)):
            raise TransitionValidationError("action names must be unique")

        if not self.predicates_by_role(PredicateRole.INITIAL):
            raise TransitionValidationError(
                "StateTransitionIR requires at least one initial predicate"
            )
        if not self.actions and not self.transitions:
            raise TransitionValidationError(
                "StateTransitionIR requires actions or transition relations"
            )

        predicates_by_id = {item.predicate_id: item for item in self.predicates}
        for predicate in self.predicates:
            _known(
                predicate.subject_variable_ids,
                variable_ids,
                f"predicate {predicate.predicate_id}.subject_variable_ids",
            )

        for label in self.labels:
            _known(
                label.subject_variable_ids,
                variable_ids,
                f"label {label.label_id}.subject_variable_ids",
            )

        for variant in self.variants:
            _known(
                variant.subject_variable_ids,
                variable_ids,
                f"variant {variant.variant_id}.subject_variable_ids",
            )

        for action in self.actions:
            frame = action.frame
            if not frame.allows_all_reads:
                _known(frame.reads, variable_ids, f"action {action.action_id}.frame.reads")
            if not frame.allows_all_writes:
                _known(
                    frame.writes, variable_ids, f"action {action.action_id}.frame.writes"
                )
            if action.guard_predicate_id:
                if action.guard_predicate_id not in predicate_ids:
                    raise TransitionValidationError(
                        f"action {action.action_id} references unknown guard "
                        f"{action.guard_predicate_id}"
                    )
                guard = predicates_by_id[action.guard_predicate_id]
                if guard.role is not PredicateRole.GUARD:
                    raise TransitionValidationError(
                        f"action {action.action_id} guard must have role 'guard', "
                        f"got {guard.role.value!r}"
                    )
            if action.next_predicate_id:
                if action.next_predicate_id not in predicate_ids:
                    raise TransitionValidationError(
                        f"action {action.action_id} references unknown next predicate "
                        f"{action.next_predicate_id}"
                    )
                next_pred = predicates_by_id[action.next_predicate_id]
                if next_pred.role is not PredicateRole.NEXT:
                    raise TransitionValidationError(
                        f"action {action.action_id} next predicate must have role 'next', "
                        f"got {next_pred.role.value!r}"
                    )
            _known(action.label_ids, label_ids, f"action {action.action_id}.label_ids")

        for relation in self.transitions:
            _known(
                relation.action_ids,
                action_ids,
                f"transition {relation.relation_id}.action_ids",
            )
            if relation.predicate_id:
                if relation.predicate_id not in predicate_ids:
                    raise TransitionValidationError(
                        f"transition {relation.relation_id} references unknown predicate "
                        f"{relation.predicate_id}"
                    )
                pred = predicates_by_id[relation.predicate_id]
                if pred.role is not PredicateRole.NEXT:
                    raise TransitionValidationError(
                        f"transition {relation.relation_id} predicate must have role 'next', "
                        f"got {pred.role.value!r}"
                    )

        for constraint in self.fairness:
            _known(
                constraint.action_ids,
                action_ids,
                f"fairness {constraint.fairness_id}.action_ids",
            )
            if constraint.predicate_id:
                if constraint.predicate_id not in predicate_ids:
                    raise TransitionValidationError(
                        f"fairness {constraint.fairness_id} references unknown predicate "
                        f"{constraint.predicate_id}"
                    )
                pred = predicates_by_id[constraint.predicate_id]
                if pred.role is not PredicateRole.FAIRNESS:
                    raise TransitionValidationError(
                        f"fairness {constraint.fairness_id} predicate must have role "
                        f"'fairness', got {pred.role.value!r}"
                    )

        for valuation in self.valuations:
            try:
                valuation.validate_against(self.schema)
            except StateValidationError as error:
                raise TransitionValidationError(str(error)) from error

        # Role separation: invariants and fairness must not be used as initial.
        for predicate in self.predicates:
            if predicate.role is PredicateRole.INITIAL and not predicate.statement:
                raise TransitionValidationError(
                    f"initial predicate {predicate.predicate_id} requires a statement"
                )

        # Ambiguous sole-next: two actions that both claim to be the exclusive
        # next-state relation without guards fail closed.
        exclusive_next = [
            action
            for action in self.actions
            if action.next_predicate_id
            and not action.guard_predicate_id
            and not action.enables_stutter
            and action.attributes.to_dict().get("exclusive_next") is True
        ]
        if len(exclusive_next) > 1:
            ids = sorted(item.action_id for item in exclusive_next)
            raise TransitionValidationError(
                f"ambiguous exclusive next actions {ids}; invalid transitions fail closed"
            )

        if self.kripke is not None:
            for world in self.kripke.worlds:
                if world.valuation_id:
                    _known(
                        (world.valuation_id,),
                        valuation_ids,
                        f"world {world.world_id}.valuation_id",
                    )
                _known(
                    world.label_ids,
                    label_ids,
                    f"world {world.world_id}.label_ids",
                )
            for edge in self.kripke.edges:
                if edge.action_id:
                    _known(
                        (edge.action_id,),
                        action_ids,
                        f"edge {edge.edge_id}.action_id",
                    )
                _known(
                    edge.label_ids,
                    label_ids,
                    f"edge {edge.edge_id}.label_ids",
                )

    def semantic_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "actions": [item.to_dict() for item in self.actions],
            "fairness": [item.to_dict() for item in self.fairness],
            "interface": STATE_TRANSITION_IR_INTERFACE,
            "labels": [item.to_dict() for item in self.labels],
            "metadata": self.metadata.to_dict(),
            "predicates": [item.to_dict() for item in self.predicates],
            "schema": self.schema.semantic_dict(),
            "schema_version": self.schema_version,
            "transitions": [item.to_dict() for item in self.transitions],
            "valuations": [item.to_dict() for item in self.valuations],
            "variants": [item.to_dict() for item in self.variants],
        }
        if self.kripke is not None:
            result["kripke"] = self.kripke.to_dict()
        else:
            result["kripke"] = None
        return result

    deterministic_dict = semantic_dict

    def to_dict(self) -> dict[str, Any]:
        result = self.semantic_dict()
        result["document_id"] = self.document_id
        # Include full schema identity in export form.
        result["schema"] = self.schema.to_dict()
        return result

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())

    def semantic_bytes(self) -> bytes:
        return self.identity.canonical_bytes

    def _compute_identity(self) -> CanonicalIdentity:
        return canonical_identity(
            self.semantic_dict(),
            domain=STATE_TRANSITION_IR_IDENTITY_DOMAIN,
            schema_version=self.schema_version,
        )

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> StateTransitionIR:
        value = _mapping(value, "state transition ir")
        _reject_unknown(
            value,
            frozenset(
                {
                    "schema",
                    "predicates",
                    "actions",
                    "transitions",
                    "fairness",
                    "labels",
                    "variants",
                    "valuations",
                    "kripke",
                    "metadata",
                    "document_id",
                    "schema_version",
                    "interface",
                }
            ),
            "state transition ir",
        )
        kripke_raw = value.get("kripke")
        return cls(
            schema=StateSchema.from_dict(_mapping(value.get("schema", {}), "schema")),
            predicates=tuple(
                StatePredicate.from_dict(_mapping(item, "predicate"))
                for item in value.get("predicates", ())
            ),
            actions=tuple(
                Action.from_dict(_mapping(item, "action"))
                for item in value.get("actions", ())
            ),
            transitions=tuple(
                TransitionRelation.from_dict(_mapping(item, "transition"))
                for item in value.get("transitions", ())
            ),
            fairness=tuple(
                FairnessConstraint.from_dict(_mapping(item, "fairness"))
                for item in value.get("fairness", ())
            ),
            labels=tuple(
                StateLabel.from_dict(_mapping(item, "label"))
                for item in value.get("labels", ())
            ),
            variants=tuple(
                VariantMeasure.from_dict(_mapping(item, "variant"))
                for item in value.get("variants", ())
            ),
            valuations=tuple(
                StateValuation.from_dict(_mapping(item, "valuation"))
                for item in value.get("valuations", ())
            ),
            kripke=None
            if kripke_raw is None
            else KripkeStructure.from_dict(_mapping(kripke_raw, "kripke")),
            metadata=_frozen(_mapping(value.get("metadata", {}), "metadata"), "metadata"),
            document_id=value.get("document_id", ""),
            schema_version=value.get(
                "schema_version", STATE_TRANSITION_IR_SCHEMA_VERSION
            ),
        )


# Re-export schema building blocks commonly needed alongside transitions.
__all__ = [
    "ACTION_FRAME_SCHEMA_VERSION",
    "ACTION_SCHEMA_VERSION",
    "FAIRNESS_SCHEMA_VERSION",
    "KRIPKE_EDGE_SCHEMA_VERSION",
    "KRIPKE_STRUCTURE_SCHEMA_VERSION",
    "KRIPKE_WORLD_SCHEMA_VERSION",
    "STATE_TRANSITION_IR_IDENTITY_DOMAIN",
    "STATE_TRANSITION_IR_INTERFACE",
    "STATE_TRANSITION_IR_SCHEMA_VERSION",
    "TRANSITION_RELATION_SCHEMA_VERSION",
    "Action",
    "ActionFrame",
    "FairnessConstraint",
    "FairnessKind",
    "KripkeEdge",
    "KripkeStructure",
    "KripkeWorld",
    "StateTransitionIR",
    "TransitionKind",
    "TransitionRelation",
    "TransitionValidationError",
    # Convenience re-exports used by tests and frontends.
    "PredicateRole",
    "StateLabel",
    "StatePredicate",
    "StateSchema",
    "StateValuation",
    "StateVariable",
    "VariantMeasure",
]
