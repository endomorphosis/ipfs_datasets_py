"""Typed state schemas, valuations, predicates, labels, and variants.

This module is deliberately free of TLA+, SMT-LIB, and model-checker syntax.
It describes *what* a state space looks like and which predicates characterize
it.  Transition relations, action systems, fairness, and Kripke structures
live in :mod:`.transitions`.

State schemas are typed and deterministic: variable order is fixed by
identifier, finite domains declare explicit bounds, and incomplete or
ill-typed valuations fail closed.
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

STATE_SCHEMA_INTERFACE: Final = "StateSchema@1"
STATE_SCHEMA_VERSION: Final = "state-schema/v1"
STATE_SCHEMA_IDENTITY_DOMAIN: Final = "logic.software-verification.state-schema"
STATE_VARIABLE_SCHEMA_VERSION: Final = "state-variable/v1"
STATE_VALUATION_SCHEMA_VERSION: Final = "state-valuation/v1"
STATE_PREDICATE_SCHEMA_VERSION: Final = "state-predicate/v1"
STATE_LABEL_SCHEMA_VERSION: Final = "state-label/v1"
VARIANT_MEASURE_SCHEMA_VERSION: Final = "state-variant/v1"
FINITE_BOUND_SCHEMA_VERSION: Final = "state-finite-bound/v1"

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")


class StateValidationError(ValueError):
    """Raised when state schemas, valuations, or predicates are malformed."""


class StateTypeKind(StrEnum):
    """Provider-neutral state variable type kinds."""

    BOOLEAN = "boolean"
    INTEGER = "integer"
    ENUMERATION = "enumeration"
    SET = "set"
    MAP = "map"
    OPAQUE = "opaque"


class Boundedness(StrEnum):
    """Whether a domain is finite with explicit bounds or unbounded."""

    FINITE = "finite"
    UNBOUNDED = "unbounded"


class PredicateRole(StrEnum):
    """Distinct roles for state-space predicates.

    Roles are not interchangeable: an initial predicate cannot be treated as a
    next-state relation, an invariant, or a fairness constraint.
    """

    INITIAL = "initial"
    NEXT = "next"
    INVARIANT = "invariant"
    FAIRNESS = "fairness"
    GUARD = "guard"
    VARIANT = "variant"
    LABEL = "label"


class LabelKind(StrEnum):
    """How a state label is interpreted."""

    ATOMIC_PROPOSITION = "atomic_proposition"
    STATE_PREDICATE = "state_predicate"
    ACTION_NAME = "action_name"


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value or value.strip() != value or "\x00" in value:
        raise StateValidationError(
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
        raise StateValidationError(f"{label} must be a stable identifier")
    return result


def _ids(
    values: Sequence[str] | object,
    label: str,
    *,
    preserve_order: bool = False,
) -> tuple[str, ...]:
    if isinstance(values, (str, bytes, bytearray)) or not isinstance(values, Sequence):
        raise StateValidationError(f"{label} must be a sequence of identifiers")
    result = tuple(_identifier(item, f"{label} item") for item in values)
    if len(result) != len(set(result)):
        raise StateValidationError(f"{label} must not contain duplicates")
    return result if preserve_order else tuple(sorted(result))


def _enum(value: object, enum_type: type[StrEnum], label: str) -> Any:
    try:
        return value if isinstance(value, enum_type) else enum_type(value)
    except (TypeError, ValueError) as error:
        choices = ", ".join(repr(item.value) for item in enum_type)
        raise StateValidationError(f"{label} must be one of {choices}") from error


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise StateValidationError(f"{label} must be a mapping")
    return value


def _frozen(value: Mapping[str, Any] | FrozenMap, label: str) -> FrozenMap:
    try:
        return value if isinstance(value, FrozenMap) else FrozenMap(value)
    except (TypeError, ValueError) as error:
        raise StateValidationError(
            f"{label} must contain immutable JSON-compatible data: {error}"
        ) from error


def _reject_unknown(value: Mapping[str, Any], allowed: frozenset[str], label: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise StateValidationError(f"unknown {label} field(s): {', '.join(unknown)}")


def _bool(value: object, label: str) -> bool:
    if not isinstance(value, bool):
        raise StateValidationError(f"{label} must be a boolean")
    return value


def _non_bool_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise StateValidationError(f"{label} must be an integer")
    return value


def _known(values: Sequence[str], known: set[str], label: str) -> None:
    missing = sorted(set(values) - known)
    if missing:
        raise StateValidationError(f"{label} references unknown ids {missing}")


@dataclass(frozen=True, slots=True)
class FiniteDomainBound:
    """An explicit finite domain bound for a state variable.

    Finite bounds must be declared; unbounded domains use
    :attr:`Boundedness.UNBOUNDED` on the variable instead of omitting this
    record.
    """

    bound_id: str
    lower: int | None = None
    upper: int | None = None
    members: tuple[str, ...] = ()
    cardinality: int | None = None
    schema_version: str = FINITE_BOUND_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "bound_id", _identifier(self.bound_id, "bound_id"))
        members = _ids(self.members, "members", preserve_order=True)
        object.__setattr__(self, "members", members)
        lower = self.lower
        upper = self.upper
        cardinality = self.cardinality
        if lower is not None:
            lower = _non_bool_int(lower, "lower")
            object.__setattr__(self, "lower", lower)
        if upper is not None:
            upper = _non_bool_int(upper, "upper")
            object.__setattr__(self, "upper", upper)
        if cardinality is not None:
            cardinality = _non_bool_int(cardinality, "cardinality")
            if cardinality < 0:
                raise StateValidationError("cardinality must be non-negative")
            object.__setattr__(self, "cardinality", cardinality)
        if lower is not None and upper is not None and lower > upper:
            raise StateValidationError("finite bound lower must not exceed upper")
        if not members and lower is None and upper is None and cardinality is None:
            raise StateValidationError(
                "finite domain bounds require members, an integer range, or cardinality"
            )
        if self.schema_version != FINITE_BOUND_SCHEMA_VERSION:
            raise StateValidationError(
                f"unsupported finite-bound schema_version {self.schema_version!r}"
            )

    def contains_integer(self, value: int) -> bool:
        if self.lower is not None and value < self.lower:
            return False
        if self.upper is not None and value > self.upper:
            return False
        return True

    def contains_member(self, value: str) -> bool:
        return not self.members or value in self.members

    def to_dict(self) -> dict[str, Any]:
        return {
            "bound_id": self.bound_id,
            "cardinality": self.cardinality,
            "lower": self.lower,
            "members": list(self.members),
            "schema_version": self.schema_version,
            "upper": self.upper,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> FiniteDomainBound:
        value = _mapping(value, "finite domain bound")
        _reject_unknown(
            value,
            frozenset(
                {
                    "bound_id",
                    "lower",
                    "upper",
                    "members",
                    "cardinality",
                    "schema_version",
                }
            ),
            "finite domain bound",
        )
        return cls(
            bound_id=value.get("bound_id", ""),
            lower=value.get("lower"),
            upper=value.get("upper"),
            members=tuple(value.get("members", ())),
            cardinality=value.get("cardinality"),
            schema_version=value.get("schema_version", FINITE_BOUND_SCHEMA_VERSION),
        )


@dataclass(frozen=True, slots=True)
class StateVariable:
    """One typed state variable with explicit domain boundedness."""

    variable_id: str
    name: str
    type_kind: StateTypeKind | str
    boundedness: Boundedness | str = Boundedness.UNBOUNDED
    domain_bound: FiniteDomainBound | None = None
    element_type_kind: StateTypeKind | str | None = None
    description: str = ""
    attributes: FrozenMap = field(default_factory=FrozenMap)
    source_ref_ids: tuple[str, ...] = ()
    schema_version: str = STATE_VARIABLE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "variable_id", _identifier(self.variable_id, "variable_id"))
        object.__setattr__(self, "name", _text(self.name, "name"))
        type_kind = _enum(self.type_kind, StateTypeKind, "type_kind")
        boundedness = _enum(self.boundedness, Boundedness, "boundedness")
        object.__setattr__(self, "type_kind", type_kind)
        object.__setattr__(self, "boundedness", boundedness)
        object.__setattr__(
            self, "description", _optional_text(self.description, "description")
        )
        object.__setattr__(self, "attributes", _frozen(self.attributes, "attributes"))
        object.__setattr__(
            self, "source_ref_ids", _ids(self.source_ref_ids, "source_ref_ids")
        )

        domain_bound = self.domain_bound
        if isinstance(domain_bound, Mapping):
            domain_bound = FiniteDomainBound.from_dict(domain_bound)
        if domain_bound is not None and not isinstance(domain_bound, FiniteDomainBound):
            raise StateValidationError("domain_bound must be a FiniteDomainBound")
        object.__setattr__(self, "domain_bound", domain_bound)

        element_type = self.element_type_kind
        if element_type is not None and element_type != "":
            element_type = _enum(element_type, StateTypeKind, "element_type_kind")
        else:
            element_type = None
        object.__setattr__(self, "element_type_kind", element_type)

        if boundedness is Boundedness.FINITE and domain_bound is None:
            raise StateValidationError(
                f"finite variable {self.variable_id} requires an explicit domain_bound"
            )
        if boundedness is Boundedness.UNBOUNDED and domain_bound is not None:
            raise StateValidationError(
                f"unbounded variable {self.variable_id} must not declare domain_bound"
            )
        if type_kind is StateTypeKind.BOOLEAN and boundedness is Boundedness.UNBOUNDED:
            # Booleans are inherently finite {false, true}.
            raise StateValidationError(
                f"boolean variable {self.variable_id} must declare finite boundedness"
            )
        if type_kind is StateTypeKind.ENUMERATION:
            if boundedness is not Boundedness.FINITE:
                raise StateValidationError(
                    f"enumeration variable {self.variable_id} must be finite"
                )
            assert domain_bound is not None
            if not domain_bound.members:
                raise StateValidationError(
                    f"enumeration variable {self.variable_id} requires domain members"
                )
        if type_kind in {StateTypeKind.SET, StateTypeKind.MAP} and element_type is None:
            raise StateValidationError(
                f"{type_kind.value} variable {self.variable_id} requires element_type_kind"
            )
        if (
            type_kind not in {StateTypeKind.SET, StateTypeKind.MAP}
            and element_type is not None
        ):
            raise StateValidationError(
                "element_type_kind is only valid for set or map variables"
            )
        if self.schema_version != STATE_VARIABLE_SCHEMA_VERSION:
            raise StateValidationError(
                f"unsupported state-variable schema_version {self.schema_version!r}"
            )

    def accepts_value(self, value: object) -> bool:
        """Return whether ``value`` is well-typed for this variable."""

        kind = self.type_kind
        if kind is StateTypeKind.BOOLEAN:
            return isinstance(value, bool)
        if kind is StateTypeKind.INTEGER:
            if isinstance(value, bool) or not isinstance(value, int):
                return False
            if self.domain_bound is not None:
                return self.domain_bound.contains_integer(value)
            return True
        if kind is StateTypeKind.ENUMERATION:
            return isinstance(value, str) and (
                self.domain_bound is None or self.domain_bound.contains_member(value)
            )
        if kind is StateTypeKind.OPAQUE:
            return isinstance(value, str) and bool(value)
        if kind is StateTypeKind.SET:
            if isinstance(value, (str, bytes, bytearray)) or not isinstance(
                value, Sequence
            ):
                return False
            if len(value) != len(set(value)):
                return False
            element_kind = self.element_type_kind
            assert element_kind is not None
            for item in value:
                if not _element_accepts(element_kind, item, self.domain_bound):
                    return False
            if (
                self.domain_bound is not None
                and self.domain_bound.cardinality is not None
                and len(value) > self.domain_bound.cardinality
            ):
                return False
            return True
        if kind is StateTypeKind.MAP:
            if not isinstance(value, Mapping):
                return False
            element_kind = self.element_type_kind
            assert element_kind is not None
            for key, item in value.items():
                if not isinstance(key, str) or not key:
                    return False
                if not _element_accepts(element_kind, item, self.domain_bound):
                    return False
            return True
        return False

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": self.attributes.to_dict(),
            "boundedness": self.boundedness.value,
            "description": self.description,
            "domain_bound": None if self.domain_bound is None else self.domain_bound.to_dict(),
            "element_type_kind": None
            if self.element_type_kind is None
            else self.element_type_kind.value,
            "name": self.name,
            "schema_version": self.schema_version,
            "source_ref_ids": list(self.source_ref_ids),
            "type_kind": self.type_kind.value,
            "variable_id": self.variable_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> StateVariable:
        value = _mapping(value, "state variable")
        _reject_unknown(
            value,
            frozenset(
                {
                    "variable_id",
                    "name",
                    "type_kind",
                    "boundedness",
                    "domain_bound",
                    "element_type_kind",
                    "description",
                    "attributes",
                    "source_ref_ids",
                    "schema_version",
                }
            ),
            "state variable",
        )
        domain = value.get("domain_bound")
        return cls(
            variable_id=value.get("variable_id", ""),
            name=value.get("name", ""),
            type_kind=value.get("type_kind", ""),
            boundedness=value.get("boundedness", Boundedness.UNBOUNDED.value),
            domain_bound=None
            if domain is None
            else FiniteDomainBound.from_dict(_mapping(domain, "domain_bound")),
            element_type_kind=value.get("element_type_kind"),
            description=value.get("description", ""),
            attributes=_frozen(
                _mapping(value.get("attributes", {}), "attributes"), "attributes"
            ),
            source_ref_ids=tuple(value.get("source_ref_ids", ())),
            schema_version=value.get("schema_version", STATE_VARIABLE_SCHEMA_VERSION),
        )


def _element_accepts(
    kind: StateTypeKind,
    value: object,
    domain_bound: FiniteDomainBound | None,
) -> bool:
    if kind is StateTypeKind.BOOLEAN:
        return isinstance(value, bool)
    if kind is StateTypeKind.INTEGER:
        if isinstance(value, bool) or not isinstance(value, int):
            return False
        return domain_bound is None or domain_bound.contains_integer(value)
    if kind is StateTypeKind.ENUMERATION:
        return isinstance(value, str) and (
            domain_bound is None or domain_bound.contains_member(value)
        )
    if kind is StateTypeKind.OPAQUE:
        return isinstance(value, str) and bool(value)
    return False


@dataclass(frozen=True, slots=True)
class StateSchema:
    """A deterministic, typed collection of state variables.

    Variable order in the schema identity is sorted by ``variable_id`` so two
    equivalent schemas always serialize identically.
    """

    variables: tuple[StateVariable, ...]
    schema_id: str = ""
    metadata: FrozenMap = field(default_factory=FrozenMap)
    schema_version: str = STATE_SCHEMA_VERSION

    INTERFACE: ClassVar[str] = STATE_SCHEMA_INTERFACE

    def __post_init__(self) -> None:
        variables = tuple(
            item
            if isinstance(item, StateVariable)
            else StateVariable.from_dict(_mapping(item, "state variable"))
            for item in self.variables
        )
        variables = tuple(sorted(variables, key=lambda item: item.variable_id))
        object.__setattr__(self, "variables", variables)
        object.__setattr__(self, "metadata", _frozen(self.metadata, "metadata"))
        if self.schema_version != STATE_SCHEMA_VERSION:
            raise StateValidationError(
                f"unsupported state-schema schema_version {self.schema_version!r}"
            )
        self.validate()
        identity = self._compute_identity()
        if self.schema_id and self.schema_id != identity.cid:
            raise StateValidationError(
                "schema_id does not match canonical state-schema content"
            )
        object.__setattr__(self, "schema_id", identity.cid)

    @property
    def identity(self) -> CanonicalIdentity:
        return self._compute_identity()

    @property
    def canonical_id(self) -> str:
        return self.schema_id

    @property
    def variable_ids(self) -> tuple[str, ...]:
        return tuple(item.variable_id for item in self.variables)

    @property
    def variables_by_id(self) -> Mapping[str, StateVariable]:
        return {item.variable_id: item for item in self.variables}

    def validate(self) -> None:
        if not self.variables:
            raise StateValidationError("a state schema requires at least one variable")
        ids = [item.variable_id for item in self.variables]
        if len(ids) != len(set(ids)):
            raise StateValidationError("state variable identifiers must be unique")
        names = [item.name for item in self.variables]
        if len(names) != len(set(names)):
            raise StateValidationError("state variable names must be unique")

    def require_variables(self, variable_ids: Sequence[str], *, label: str) -> None:
        _known(tuple(variable_ids), set(self.variable_ids), label)

    def semantic_dict(self) -> dict[str, Any]:
        return {
            "interface": STATE_SCHEMA_INTERFACE,
            "metadata": self.metadata.to_dict(),
            "schema_version": self.schema_version,
            "variables": [item.to_dict() for item in self.variables],
        }

    deterministic_dict = semantic_dict

    def to_dict(self) -> dict[str, Any]:
        result = self.semantic_dict()
        result["schema_id"] = self.schema_id
        return result

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())

    def _compute_identity(self) -> CanonicalIdentity:
        return canonical_identity(
            self.semantic_dict(),
            domain=STATE_SCHEMA_IDENTITY_DOMAIN,
            schema_version=self.schema_version,
        )

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> StateSchema:
        value = _mapping(value, "state schema")
        _reject_unknown(
            value,
            frozenset(
                {
                    "variables",
                    "schema_id",
                    "metadata",
                    "schema_version",
                    "interface",
                }
            ),
            "state schema",
        )
        return cls(
            variables=tuple(
                StateVariable.from_dict(_mapping(item, "state variable"))
                for item in value.get("variables", ())
            ),
            schema_id=value.get("schema_id", ""),
            metadata=_frozen(_mapping(value.get("metadata", {}), "metadata"), "metadata"),
            schema_version=value.get("schema_version", STATE_SCHEMA_VERSION),
        )


@dataclass(frozen=True, slots=True)
class StateValuation:
    """A complete assignment of values to every variable in a schema."""

    valuation_id: str
    assignments: FrozenMap
    schema_version: str = STATE_VALUATION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "valuation_id", _identifier(self.valuation_id, "valuation_id")
        )
        object.__setattr__(
            self, "assignments", _frozen(self.assignments, "assignments")
        )
        if not self.assignments:
            raise StateValidationError("a state valuation requires assignments")
        for key in self.assignments:
            _identifier(key, "assignment variable_id")
        if self.schema_version != STATE_VALUATION_SCHEMA_VERSION:
            raise StateValidationError(
                f"unsupported state-valuation schema_version {self.schema_version!r}"
            )

    def get(self, variable_id: str) -> Any:
        variable_id = _identifier(variable_id, "variable_id")
        if variable_id not in self.assignments:
            raise StateValidationError(
                f"valuation {self.valuation_id} has no assignment for {variable_id}"
            )
        return self.assignments[variable_id]

    def validate_against(self, schema: StateSchema) -> None:
        """Fail closed when the valuation is incomplete, surplus, or ill-typed."""

        expected = set(schema.variable_ids)
        actual = set(self.assignments)
        missing = sorted(expected - actual)
        surplus = sorted(actual - expected)
        if missing:
            raise StateValidationError(
                f"valuation {self.valuation_id} is missing assignments {missing}"
            )
        if surplus:
            raise StateValidationError(
                f"valuation {self.valuation_id} has unknown variables {surplus}"
            )
        for variable in schema.variables:
            value = self.assignments[variable.variable_id]
            if not variable.accepts_value(value):
                raise StateValidationError(
                    f"valuation {self.valuation_id} assigns ill-typed value "
                    f"to {variable.variable_id}"
                )

    def to_dict(self) -> dict[str, Any]:
        return {
            "assignments": self.assignments.to_dict(),
            "schema_version": self.schema_version,
            "valuation_id": self.valuation_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> StateValuation:
        value = _mapping(value, "state valuation")
        _reject_unknown(
            value,
            frozenset({"valuation_id", "assignments", "schema_version"}),
            "state valuation",
        )
        return cls(
            valuation_id=value.get("valuation_id", ""),
            assignments=_frozen(
                _mapping(value.get("assignments", {}), "assignments"), "assignments"
            ),
            schema_version=value.get("schema_version", STATE_VALUATION_SCHEMA_VERSION),
        )


@dataclass(frozen=True, slots=True)
class StatePredicate:
    """A role-tagged predicate over the state space.

    Roles are part of the identity.  The same expression with role
    ``initial`` is not interchangeable with role ``invariant`` or ``next``.
    """

    predicate_id: str
    role: PredicateRole | str
    statement: str
    expression: FrozenMap = field(default_factory=FrozenMap)
    subject_variable_ids: tuple[str, ...] = ()
    attributes: FrozenMap = field(default_factory=FrozenMap)
    source_ref_ids: tuple[str, ...] = ()
    schema_version: str = STATE_PREDICATE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "predicate_id", _identifier(self.predicate_id, "predicate_id")
        )
        object.__setattr__(self, "role", _enum(self.role, PredicateRole, "role"))
        object.__setattr__(self, "statement", _text(self.statement, "statement"))
        object.__setattr__(self, "expression", _frozen(self.expression, "expression"))
        object.__setattr__(
            self,
            "subject_variable_ids",
            _ids(self.subject_variable_ids, "subject_variable_ids"),
        )
        object.__setattr__(self, "attributes", _frozen(self.attributes, "attributes"))
        object.__setattr__(
            self, "source_ref_ids", _ids(self.source_ref_ids, "source_ref_ids")
        )
        if self.schema_version != STATE_PREDICATE_SCHEMA_VERSION:
            raise StateValidationError(
                f"unsupported state-predicate schema_version {self.schema_version!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": self.attributes.to_dict(),
            "expression": self.expression.to_dict(),
            "predicate_id": self.predicate_id,
            "role": self.role.value,
            "schema_version": self.schema_version,
            "source_ref_ids": list(self.source_ref_ids),
            "statement": self.statement,
            "subject_variable_ids": list(self.subject_variable_ids),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> StatePredicate:
        value = _mapping(value, "state predicate")
        _reject_unknown(
            value,
            frozenset(
                {
                    "predicate_id",
                    "role",
                    "statement",
                    "expression",
                    "subject_variable_ids",
                    "attributes",
                    "source_ref_ids",
                    "schema_version",
                }
            ),
            "state predicate",
        )
        return cls(
            predicate_id=value.get("predicate_id", ""),
            role=value.get("role", ""),
            statement=value.get("statement", ""),
            expression=_frozen(
                _mapping(value.get("expression", {}), "expression"), "expression"
            ),
            subject_variable_ids=tuple(value.get("subject_variable_ids", ())),
            attributes=_frozen(
                _mapping(value.get("attributes", {}), "attributes"), "attributes"
            ),
            source_ref_ids=tuple(value.get("source_ref_ids", ())),
            schema_version=value.get("schema_version", STATE_PREDICATE_SCHEMA_VERSION),
        )


@dataclass(frozen=True, slots=True)
class StateLabel:
    """An atomic label or named proposition attached to states or actions."""

    label_id: str
    name: str
    kind: LabelKind | str = LabelKind.ATOMIC_PROPOSITION
    expression: FrozenMap = field(default_factory=FrozenMap)
    subject_variable_ids: tuple[str, ...] = ()
    attributes: FrozenMap = field(default_factory=FrozenMap)
    source_ref_ids: tuple[str, ...] = ()
    schema_version: str = STATE_LABEL_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "label_id", _identifier(self.label_id, "label_id"))
        object.__setattr__(self, "name", _identifier(self.name, "name"))
        object.__setattr__(self, "kind", _enum(self.kind, LabelKind, "kind"))
        object.__setattr__(self, "expression", _frozen(self.expression, "expression"))
        object.__setattr__(
            self,
            "subject_variable_ids",
            _ids(self.subject_variable_ids, "subject_variable_ids"),
        )
        object.__setattr__(self, "attributes", _frozen(self.attributes, "attributes"))
        object.__setattr__(
            self, "source_ref_ids", _ids(self.source_ref_ids, "source_ref_ids")
        )
        if self.schema_version != STATE_LABEL_SCHEMA_VERSION:
            raise StateValidationError(
                f"unsupported state-label schema_version {self.schema_version!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": self.attributes.to_dict(),
            "expression": self.expression.to_dict(),
            "kind": self.kind.value,
            "label_id": self.label_id,
            "name": self.name,
            "schema_version": self.schema_version,
            "source_ref_ids": list(self.source_ref_ids),
            "subject_variable_ids": list(self.subject_variable_ids),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> StateLabel:
        value = _mapping(value, "state label")
        _reject_unknown(
            value,
            frozenset(
                {
                    "label_id",
                    "name",
                    "kind",
                    "expression",
                    "subject_variable_ids",
                    "attributes",
                    "source_ref_ids",
                    "schema_version",
                }
            ),
            "state label",
        )
        return cls(
            label_id=value.get("label_id", ""),
            name=value.get("name", ""),
            kind=value.get("kind", LabelKind.ATOMIC_PROPOSITION.value),
            expression=_frozen(
                _mapping(value.get("expression", {}), "expression"), "expression"
            ),
            subject_variable_ids=tuple(value.get("subject_variable_ids", ())),
            attributes=_frozen(
                _mapping(value.get("attributes", {}), "attributes"), "attributes"
            ),
            source_ref_ids=tuple(value.get("source_ref_ids", ())),
            schema_version=value.get("schema_version", STATE_LABEL_SCHEMA_VERSION),
        )


@dataclass(frozen=True, slots=True)
class VariantMeasure:
    """A ranking function / variant used for termination or progress."""

    variant_id: str
    statement: str
    expression: FrozenMap = field(default_factory=FrozenMap)
    subject_variable_ids: tuple[str, ...] = ()
    well_founded_order: str = "natural_numbers"
    attributes: FrozenMap = field(default_factory=FrozenMap)
    source_ref_ids: tuple[str, ...] = ()
    schema_version: str = VARIANT_MEASURE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "variant_id", _identifier(self.variant_id, "variant_id")
        )
        object.__setattr__(self, "statement", _text(self.statement, "statement"))
        object.__setattr__(self, "expression", _frozen(self.expression, "expression"))
        object.__setattr__(
            self,
            "subject_variable_ids",
            _ids(self.subject_variable_ids, "subject_variable_ids"),
        )
        object.__setattr__(
            self,
            "well_founded_order",
            _text(self.well_founded_order, "well_founded_order"),
        )
        object.__setattr__(self, "attributes", _frozen(self.attributes, "attributes"))
        object.__setattr__(
            self, "source_ref_ids", _ids(self.source_ref_ids, "source_ref_ids")
        )
        if self.schema_version != VARIANT_MEASURE_SCHEMA_VERSION:
            raise StateValidationError(
                f"unsupported variant schema_version {self.schema_version!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": self.attributes.to_dict(),
            "expression": self.expression.to_dict(),
            "schema_version": self.schema_version,
            "source_ref_ids": list(self.source_ref_ids),
            "statement": self.statement,
            "subject_variable_ids": list(self.subject_variable_ids),
            "variant_id": self.variant_id,
            "well_founded_order": self.well_founded_order,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> VariantMeasure:
        value = _mapping(value, "variant measure")
        _reject_unknown(
            value,
            frozenset(
                {
                    "variant_id",
                    "statement",
                    "expression",
                    "subject_variable_ids",
                    "well_founded_order",
                    "attributes",
                    "source_ref_ids",
                    "schema_version",
                }
            ),
            "variant measure",
        )
        return cls(
            variant_id=value.get("variant_id", ""),
            statement=value.get("statement", ""),
            expression=_frozen(
                _mapping(value.get("expression", {}), "expression"), "expression"
            ),
            subject_variable_ids=tuple(value.get("subject_variable_ids", ())),
            well_founded_order=value.get("well_founded_order", "natural_numbers"),
            attributes=_frozen(
                _mapping(value.get("attributes", {}), "attributes"), "attributes"
            ),
            source_ref_ids=tuple(value.get("source_ref_ids", ())),
            schema_version=value.get("schema_version", VARIANT_MEASURE_SCHEMA_VERSION),
        )


__all__ = [
    "FINITE_BOUND_SCHEMA_VERSION",
    "STATE_LABEL_SCHEMA_VERSION",
    "STATE_PREDICATE_SCHEMA_VERSION",
    "STATE_SCHEMA_IDENTITY_DOMAIN",
    "STATE_SCHEMA_INTERFACE",
    "STATE_SCHEMA_VERSION",
    "STATE_VALUATION_SCHEMA_VERSION",
    "STATE_VARIABLE_SCHEMA_VERSION",
    "VARIANT_MEASURE_SCHEMA_VERSION",
    "Boundedness",
    "FiniteDomainBound",
    "LabelKind",
    "PredicateRole",
    "StateLabel",
    "StatePredicate",
    "StateSchema",
    "StateTypeKind",
    "StateValidationError",
    "StateValuation",
    "StateVariable",
    "VariantMeasure",
]
