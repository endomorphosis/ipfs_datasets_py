"""Typed heap, ownership, permission, and resource-algebra primitives.

``HeapModel`` describes a finite heap fragment above any solver encoding.  It
records locations, values, points-to cells, ownership, permissions, alias
classes, and resource-algebra units.  It deliberately contains no solver
request, execution status, or proof verdict.

Permissions are exact rationals in ``[0, 1]``.  Full ownership is permission
``1``.  Combining cells on the same location fails closed when the combined
permission would exceed one, which is how fractional-permission conservation
is enforced at construction time.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from fractions import Fraction
from math import gcd
from typing import Any, Final

from ipfs_datasets_py.logic.ir_core.claims import FrozenMap

HEAP_MODEL_INTERFACE: Final = "HeapModel@1"
HEAP_MODEL_SCHEMA_VERSION: Final = "heap-model/v1"
PERMISSION_SCHEMA_VERSION: Final = "heap-permission/v1"

_ID_RE = __import__("re").compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")


class HeapValidationError(ValueError):
    """Raised when heap, ownership, or permission semantics are malformed."""


class LocationKind(StrEnum):
    """Semantic category of a heap location."""

    ADDRESS = "address"
    FIELD = "field"
    ARRAY_CELL = "array_cell"
    OBJECT = "object"
    REGION = "region"
    ABSTRACT = "abstract"


class ValueKind(StrEnum):
    """Semantic category of a heap-stored value."""

    INTEGER = "integer"
    BOOLEAN = "boolean"
    POINTER = "pointer"
    STRUCT = "struct"
    ARRAY = "array"
    RESOURCE = "resource"
    ABSTRACT = "abstract"
    NULL = "null"


class OwnershipKind(StrEnum):
    """How a principal relates to a heap location."""

    EXCLUSIVE = "exclusive"
    SHARED = "shared"
    BORROWED = "borrowed"
    TRANSFERRED = "transferred"
    NONE = "none"


class AliasClassKind(StrEnum):
    """Declared alias relationship among locations."""

    MUST_ALIAS = "must_alias"
    MAY_ALIAS = "may_alias"
    MUST_NOT_ALIAS = "must_not_alias"


class ResourceAlgebraKind(StrEnum):
    """Closed vocabulary of resource algebras understood by the heap model."""

    DISJOINT_HEAP = "disjoint_heap"
    FRACTIONAL_PERMISSION = "fractional_permission"
    BINARY_PERMISSION = "binary_permission"
    COUNTING_PERMISSION = "counting_permission"
    CUSTOM = "custom"


def _text(value: object, label: str, *, optional: bool = False) -> str:
    if optional and value == "":
        return ""
    if (
        not isinstance(value, str)
        or not value
        or value.strip() != value
        or "\x00" in value
    ):
        qualifier = "an empty or " if optional else "a "
        raise HeapValidationError(
            f"{label} must be {qualifier}non-empty trimmed string without NUL bytes"
        )
    return value


def _identifier(value: object, label: str) -> str:
    result = _text(value, label)
    if not _ID_RE.fullmatch(result):
        raise HeapValidationError(f"{label} must be a stable identifier")
    return result


def _enum(value: object, enum_type: type[StrEnum], label: str) -> Any:
    try:
        return value if isinstance(value, enum_type) else enum_type(value)
    except (TypeError, ValueError) as error:
        choices = ", ".join(repr(item.value) for item in enum_type)
        raise HeapValidationError(f"{label} must be one of {choices}") from error


def _sequence(value: object, label: str) -> Sequence[Any]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise HeapValidationError(f"{label} must be a sequence")
    return value


def _identifiers(
    values: object,
    label: str,
    *,
    sort: bool = True,
    allow_empty: bool = True,
) -> tuple[str, ...]:
    result = tuple(
        _identifier(item, f"{label} item") for item in _sequence(values, label)
    )
    if not allow_empty and not result:
        raise HeapValidationError(f"{label} must not be empty")
    if len(result) != len(set(result)):
        raise HeapValidationError(f"{label} must not contain duplicates")
    return tuple(sorted(result)) if sort else result


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise HeapValidationError(f"{label} must be a mapping")
    return value


def _frozen(value: Mapping[str, Any] | FrozenMap, label: str) -> FrozenMap:
    try:
        return value if isinstance(value, FrozenMap) else FrozenMap(value)
    except (TypeError, ValueError) as error:
        raise HeapValidationError(
            f"{label} must contain immutable JSON-compatible data"
        ) from error


def _reject_unknown(
    value: Mapping[str, Any], allowed: frozenset[str], label: str
) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise HeapValidationError(f"unknown {label} field(s): {', '.join(unknown)}")


def _source_map(
    source_ref_ids: object,
    span_ids: object,
    *,
    owner: str,
    required: bool = True,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    sources = _identifiers(source_ref_ids, f"{owner}.source_ref_ids")
    spans = _identifiers(span_ids, f"{owner}.span_ids")
    if required and not sources and not spans:
        raise HeapValidationError(
            f"{owner} must be source mapped with source_ref_ids or span_ids"
        )
    return sources, spans


@dataclass(frozen=True, slots=True)
class Permission:
    """Exact permission amount in the closed interval ``[0, 1]``.

    Full write ownership is represented by ``1``.  Read-only fractional shares
    are strict positive amounts less than one.  Zero is the empty permission.
    """

    numerator: int
    denominator: int = 1

    def __post_init__(self) -> None:
        if isinstance(self.numerator, bool) or not isinstance(self.numerator, int):
            raise HeapValidationError("permission numerator must be an integer")
        if isinstance(self.denominator, bool) or not isinstance(
            self.denominator, int
        ):
            raise HeapValidationError("permission denominator must be an integer")
        if self.denominator <= 0:
            raise HeapValidationError("permission denominator must be positive")
        if self.numerator < 0:
            raise HeapValidationError("permission must be non-negative")
        if self.numerator > self.denominator:
            raise HeapValidationError(
                "permission is bounded to [0, 1]; numerator exceeds denominator"
            )
        divisor = gcd(self.numerator, self.denominator)
        object.__setattr__(self, "numerator", self.numerator // divisor)
        object.__setattr__(self, "denominator", self.denominator // divisor)

    @classmethod
    def full(cls) -> Permission:
        return cls(1, 1)

    @classmethod
    def none(cls) -> Permission:
        return cls(0, 1)

    @classmethod
    def half(cls) -> Permission:
        return cls(1, 2)

    @classmethod
    def from_fraction(cls, value: Fraction | Permission | Mapping[str, Any] | int) -> Permission:
        if isinstance(value, cls):
            return value
        if isinstance(value, Fraction):
            return cls(value.numerator, value.denominator)
        if isinstance(value, bool):
            raise HeapValidationError("permission must not be a boolean")
        if isinstance(value, int):
            if value not in (0, 1):
                raise HeapValidationError("integer permissions must be 0 or 1")
            return cls(value, 1)
        value = _mapping(value, "permission")
        _reject_unknown(
            value,
            frozenset({"numerator", "denominator", "schema_version"}),
            "permission",
        )
        return cls(
            numerator=value.get("numerator"),  # type: ignore[arg-type]
            denominator=value.get("denominator", 1),  # type: ignore[arg-type]
        )

    @property
    def fraction(self) -> Fraction:
        return Fraction(self.numerator, self.denominator)

    @property
    def is_full(self) -> bool:
        return self.numerator == self.denominator and self.denominator != 0

    @property
    def is_empty(self) -> bool:
        return self.numerator == 0

    @property
    def is_write(self) -> bool:
        return self.is_full

    @property
    def is_read(self) -> bool:
        return not self.is_empty

    def __add__(self, other: Permission) -> Permission:
        if not isinstance(other, Permission):
            return NotImplemented
        total = self.fraction + other.fraction
        if total > 1:
            raise HeapValidationError(
                f"permission conservation violated: {self.fraction} + "
                f"{other.fraction} exceeds 1"
            )
        return Permission(total.numerator, total.denominator)

    def __sub__(self, other: Permission) -> Permission:
        if not isinstance(other, Permission):
            return NotImplemented
        total = self.fraction - other.fraction
        if total < 0:
            raise HeapValidationError(
                f"permission conservation violated: cannot subtract "
                f"{other.fraction} from {self.fraction}"
            )
        return Permission(total.numerator, total.denominator)

    def compatible_with(self, other: Permission) -> bool:
        return self.fraction + other.fraction <= 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "denominator": self.denominator,
            "numerator": self.numerator,
            "schema_version": PERMISSION_SCHEMA_VERSION,
        }


@dataclass(frozen=True, slots=True)
class HeapLocation:
    """A typed location that may appear on the left of a points-to assertion."""

    location_id: str
    name: str
    kind: LocationKind | str
    type_name: str
    owner_id: str = ""
    source_ref_ids: tuple[str, ...] = ()
    span_ids: tuple[str, ...] = ()
    attributes: FrozenMap = field(default_factory=FrozenMap)

    def __post_init__(self) -> None:
        sources, spans = _source_map(
            self.source_ref_ids, self.span_ids, owner="HeapLocation"
        )
        object.__setattr__(
            self, "location_id", _identifier(self.location_id, "location_id")
        )
        object.__setattr__(self, "name", _text(self.name, "name"))
        object.__setattr__(self, "kind", _enum(self.kind, LocationKind, "kind"))
        object.__setattr__(self, "type_name", _text(self.type_name, "type_name"))
        object.__setattr__(
            self, "owner_id", _text(self.owner_id, "owner_id", optional=True)
        )
        object.__setattr__(self, "attributes", _frozen(self.attributes, "attributes"))
        object.__setattr__(self, "source_ref_ids", sources)
        object.__setattr__(self, "span_ids", spans)

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": self.attributes.to_dict(),
            "kind": self.kind.value,
            "location_id": self.location_id,
            "name": self.name,
            "owner_id": self.owner_id,
            "source_ref_ids": list(self.source_ref_ids),
            "span_ids": list(self.span_ids),
            "type_name": self.type_name,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> HeapLocation:
        value = _mapping(value, "heap location")
        _reject_unknown(
            value,
            frozenset(
                {
                    "attributes",
                    "kind",
                    "location_id",
                    "name",
                    "owner_id",
                    "source_ref_ids",
                    "span_ids",
                    "type_name",
                }
            ),
            "heap location",
        )
        return cls(
            location_id=value.get("location_id", ""),
            name=value.get("name", ""),
            kind=value.get("kind", ""),
            type_name=value.get("type_name", ""),
            owner_id=value.get("owner_id", ""),
            source_ref_ids=tuple(value.get("source_ref_ids", ())),
            span_ids=tuple(value.get("span_ids", ())),
            attributes=_frozen(
                _mapping(value.get("attributes", {}), "attributes"), "attributes"
            ),
        )


@dataclass(frozen=True, slots=True)
class HeapValue:
    """A typed value that may appear on the right of a points-to assertion."""

    value_id: str
    kind: ValueKind | str
    type_name: str
    literal: str = ""
    points_to_location_id: str = ""
    source_ref_ids: tuple[str, ...] = ()
    span_ids: tuple[str, ...] = ()
    attributes: FrozenMap = field(default_factory=FrozenMap)

    def __post_init__(self) -> None:
        sources, spans = _source_map(
            self.source_ref_ids, self.span_ids, owner="HeapValue"
        )
        kind = _enum(self.kind, ValueKind, "kind")
        object.__setattr__(self, "value_id", _identifier(self.value_id, "value_id"))
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "type_name", _text(self.type_name, "type_name"))
        object.__setattr__(
            self, "literal", _text(self.literal, "literal", optional=True)
        )
        target = _text(
            self.points_to_location_id, "points_to_location_id", optional=True
        )
        if kind is ValueKind.POINTER and not target and self.literal != "null":
            # Null pointer literals may omit a target; non-null pointers must name one.
            if not self.literal:
                raise HeapValidationError(
                    "pointer values require points_to_location_id or a null literal"
                )
        if kind is not ValueKind.POINTER and target:
            raise HeapValidationError(
                "points_to_location_id is only valid on pointer values"
            )
        if kind is ValueKind.NULL and target:
            raise HeapValidationError("null values cannot point to a location")
        object.__setattr__(self, "points_to_location_id", target)
        object.__setattr__(self, "attributes", _frozen(self.attributes, "attributes"))
        object.__setattr__(self, "source_ref_ids", sources)
        object.__setattr__(self, "span_ids", spans)

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": self.attributes.to_dict(),
            "kind": self.kind.value,
            "literal": self.literal,
            "points_to_location_id": self.points_to_location_id,
            "source_ref_ids": list(self.source_ref_ids),
            "span_ids": list(self.span_ids),
            "type_name": self.type_name,
            "value_id": self.value_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> HeapValue:
        value = _mapping(value, "heap value")
        _reject_unknown(
            value,
            frozenset(
                {
                    "attributes",
                    "kind",
                    "literal",
                    "points_to_location_id",
                    "source_ref_ids",
                    "span_ids",
                    "type_name",
                    "value_id",
                }
            ),
            "heap value",
        )
        return cls(
            value_id=value.get("value_id", ""),
            kind=value.get("kind", ""),
            type_name=value.get("type_name", ""),
            literal=value.get("literal", ""),
            points_to_location_id=value.get("points_to_location_id", ""),
            source_ref_ids=tuple(value.get("source_ref_ids", ())),
            span_ids=tuple(value.get("span_ids", ())),
            attributes=_frozen(
                _mapping(value.get("attributes", {}), "attributes"), "attributes"
            ),
        )


@dataclass(frozen=True, slots=True)
class PointsToCell:
    """A points-to assertion ``location |->^π value`` with explicit permission."""

    cell_id: str
    location_id: str
    value_id: str
    permission: Permission = field(default_factory=Permission.full)
    source_ref_ids: tuple[str, ...] = ()
    span_ids: tuple[str, ...] = ()
    attributes: FrozenMap = field(default_factory=FrozenMap)

    def __post_init__(self) -> None:
        sources, spans = _source_map(
            self.source_ref_ids, self.span_ids, owner="PointsToCell"
        )
        permission = Permission.from_fraction(self.permission)
        if permission.is_empty:
            raise HeapValidationError(
                "points-to cells require a strictly positive permission"
            )
        object.__setattr__(self, "cell_id", _identifier(self.cell_id, "cell_id"))
        object.__setattr__(
            self, "location_id", _identifier(self.location_id, "location_id")
        )
        object.__setattr__(self, "value_id", _identifier(self.value_id, "value_id"))
        object.__setattr__(self, "permission", permission)
        object.__setattr__(self, "attributes", _frozen(self.attributes, "attributes"))
        object.__setattr__(self, "source_ref_ids", sources)
        object.__setattr__(self, "span_ids", spans)

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": self.attributes.to_dict(),
            "cell_id": self.cell_id,
            "location_id": self.location_id,
            "permission": self.permission.to_dict(),
            "source_ref_ids": list(self.source_ref_ids),
            "span_ids": list(self.span_ids),
            "value_id": self.value_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> PointsToCell:
        value = _mapping(value, "points-to cell")
        _reject_unknown(
            value,
            frozenset(
                {
                    "attributes",
                    "cell_id",
                    "location_id",
                    "permission",
                    "source_ref_ids",
                    "span_ids",
                    "value_id",
                }
            ),
            "points-to cell",
        )
        return cls(
            cell_id=value.get("cell_id", ""),
            location_id=value.get("location_id", ""),
            value_id=value.get("value_id", ""),
            permission=Permission.from_fraction(value.get("permission", {"numerator": 1})),
            source_ref_ids=tuple(value.get("source_ref_ids", ())),
            span_ids=tuple(value.get("span_ids", ())),
            attributes=_frozen(
                _mapping(value.get("attributes", {}), "attributes"), "attributes"
            ),
        )


@dataclass(frozen=True, slots=True)
class OwnershipRecord:
    """Typed ownership claim over a location by a principal."""

    ownership_id: str
    location_id: str
    owner_id: str
    kind: OwnershipKind | str
    permission: Permission = field(default_factory=Permission.full)
    source_ref_ids: tuple[str, ...] = ()
    span_ids: tuple[str, ...] = ()
    attributes: FrozenMap = field(default_factory=FrozenMap)

    def __post_init__(self) -> None:
        sources, spans = _source_map(
            self.source_ref_ids, self.span_ids, owner="OwnershipRecord"
        )
        kind = _enum(self.kind, OwnershipKind, "kind")
        permission = Permission.from_fraction(self.permission)
        if kind is OwnershipKind.NONE and not permission.is_empty:
            raise HeapValidationError(
                "ownership kind 'none' requires empty permission"
            )
        if kind is OwnershipKind.EXCLUSIVE and not permission.is_full:
            raise HeapValidationError(
                "exclusive ownership requires full permission"
            )
        if kind is OwnershipKind.SHARED and permission.is_full:
            raise HeapValidationError(
                "shared ownership requires a fractional permission strictly less than 1"
            )
        if kind is not OwnershipKind.NONE and permission.is_empty:
            raise HeapValidationError(
                f"ownership kind {kind.value!r} requires a positive permission"
            )
        object.__setattr__(
            self, "ownership_id", _identifier(self.ownership_id, "ownership_id")
        )
        object.__setattr__(
            self, "location_id", _identifier(self.location_id, "location_id")
        )
        object.__setattr__(self, "owner_id", _identifier(self.owner_id, "owner_id"))
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "permission", permission)
        object.__setattr__(self, "attributes", _frozen(self.attributes, "attributes"))
        object.__setattr__(self, "source_ref_ids", sources)
        object.__setattr__(self, "span_ids", spans)

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": self.attributes.to_dict(),
            "kind": self.kind.value,
            "location_id": self.location_id,
            "owner_id": self.owner_id,
            "ownership_id": self.ownership_id,
            "permission": self.permission.to_dict(),
            "source_ref_ids": list(self.source_ref_ids),
            "span_ids": list(self.span_ids),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> OwnershipRecord:
        value = _mapping(value, "ownership record")
        _reject_unknown(
            value,
            frozenset(
                {
                    "attributes",
                    "kind",
                    "location_id",
                    "owner_id",
                    "ownership_id",
                    "permission",
                    "source_ref_ids",
                    "span_ids",
                }
            ),
            "ownership record",
        )
        return cls(
            ownership_id=value.get("ownership_id", ""),
            location_id=value.get("location_id", ""),
            owner_id=value.get("owner_id", ""),
            kind=value.get("kind", ""),
            permission=Permission.from_fraction(
                value.get("permission", {"numerator": 1})
            ),
            source_ref_ids=tuple(value.get("source_ref_ids", ())),
            span_ids=tuple(value.get("span_ids", ())),
            attributes=_frozen(
                _mapping(value.get("attributes", {}), "attributes"), "attributes"
            ),
        )


@dataclass(frozen=True, slots=True)
class AliasClass:
    """Typed aliasing declaration among heap locations."""

    alias_id: str
    kind: AliasClassKind | str
    location_ids: tuple[str, ...]
    type_name: str = ""
    source_ref_ids: tuple[str, ...] = ()
    span_ids: tuple[str, ...] = ()
    attributes: FrozenMap = field(default_factory=FrozenMap)

    def __post_init__(self) -> None:
        sources, spans = _source_map(
            self.source_ref_ids, self.span_ids, owner="AliasClass"
        )
        locations = _identifiers(
            self.location_ids, "location_ids", allow_empty=False
        )
        if len(locations) < 2:
            raise HeapValidationError(
                "alias classes require at least two location identifiers"
            )
        object.__setattr__(self, "alias_id", _identifier(self.alias_id, "alias_id"))
        object.__setattr__(self, "kind", _enum(self.kind, AliasClassKind, "kind"))
        object.__setattr__(self, "location_ids", locations)
        object.__setattr__(
            self, "type_name", _text(self.type_name, "type_name", optional=True)
        )
        object.__setattr__(self, "attributes", _frozen(self.attributes, "attributes"))
        object.__setattr__(self, "source_ref_ids", sources)
        object.__setattr__(self, "span_ids", spans)

    def to_dict(self) -> dict[str, Any]:
        return {
            "alias_id": self.alias_id,
            "attributes": self.attributes.to_dict(),
            "kind": self.kind.value,
            "location_ids": list(self.location_ids),
            "source_ref_ids": list(self.source_ref_ids),
            "span_ids": list(self.span_ids),
            "type_name": self.type_name,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> AliasClass:
        value = _mapping(value, "alias class")
        _reject_unknown(
            value,
            frozenset(
                {
                    "alias_id",
                    "attributes",
                    "kind",
                    "location_ids",
                    "source_ref_ids",
                    "span_ids",
                    "type_name",
                }
            ),
            "alias class",
        )
        return cls(
            alias_id=value.get("alias_id", ""),
            kind=value.get("kind", ""),
            location_ids=tuple(value.get("location_ids", ())),
            type_name=value.get("type_name", ""),
            source_ref_ids=tuple(value.get("source_ref_ids", ())),
            span_ids=tuple(value.get("span_ids", ())),
            attributes=_frozen(
                _mapping(value.get("attributes", {}), "attributes"), "attributes"
            ),
        )


@dataclass(frozen=True, slots=True)
class ResourceUnit:
    """Atomic resource in a resource algebra (heap cell, lock, credit, ...)."""

    unit_id: str
    name: str
    algebra_kind: ResourceAlgebraKind | str
    location_id: str = ""
    permission: Permission = field(default_factory=Permission.full)
    source_ref_ids: tuple[str, ...] = ()
    span_ids: tuple[str, ...] = ()
    attributes: FrozenMap = field(default_factory=FrozenMap)

    def __post_init__(self) -> None:
        sources, spans = _source_map(
            self.source_ref_ids, self.span_ids, owner="ResourceUnit"
        )
        kind = _enum(self.algebra_kind, ResourceAlgebraKind, "algebra_kind")
        permission = Permission.from_fraction(self.permission)
        location_id = _text(self.location_id, "location_id", optional=True)
        if kind is ResourceAlgebraKind.DISJOINT_HEAP and not location_id:
            raise HeapValidationError(
                "disjoint_heap resource units require location_id"
            )
        if kind is ResourceAlgebraKind.CUSTOM:
            # Custom algebras are admitted only when named in attributes so
            # downstream lowering cannot treat them as a known theory.
            custom_name = self.attributes.get("custom.algebra_name") if isinstance(
                self.attributes, FrozenMap
            ) else None
            # attributes not yet frozen; check raw mapping after freeze below
        object.__setattr__(self, "unit_id", _identifier(self.unit_id, "unit_id"))
        object.__setattr__(self, "name", _text(self.name, "name"))
        object.__setattr__(self, "algebra_kind", kind)
        object.__setattr__(self, "location_id", location_id)
        object.__setattr__(self, "permission", permission)
        attributes = _frozen(self.attributes, "attributes")
        if kind is ResourceAlgebraKind.CUSTOM:
            custom_name = attributes.get("custom.algebra_name")
            if not isinstance(custom_name, str) or not custom_name:
                raise HeapValidationError(
                    "custom resource algebras require attributes['custom.algebra_name']"
                )
        object.__setattr__(self, "attributes", attributes)
        object.__setattr__(self, "source_ref_ids", sources)
        object.__setattr__(self, "span_ids", spans)

    def to_dict(self) -> dict[str, Any]:
        return {
            "algebra_kind": self.algebra_kind.value,
            "attributes": self.attributes.to_dict(),
            "location_id": self.location_id,
            "name": self.name,
            "permission": self.permission.to_dict(),
            "source_ref_ids": list(self.source_ref_ids),
            "span_ids": list(self.span_ids),
            "unit_id": self.unit_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> ResourceUnit:
        value = _mapping(value, "resource unit")
        _reject_unknown(
            value,
            frozenset(
                {
                    "algebra_kind",
                    "attributes",
                    "location_id",
                    "name",
                    "permission",
                    "source_ref_ids",
                    "span_ids",
                    "unit_id",
                }
            ),
            "resource unit",
        )
        return cls(
            unit_id=value.get("unit_id", ""),
            name=value.get("name", ""),
            algebra_kind=value.get("algebra_kind", ""),
            location_id=value.get("location_id", ""),
            permission=Permission.from_fraction(
                value.get("permission", {"numerator": 1})
            ),
            source_ref_ids=tuple(value.get("source_ref_ids", ())),
            span_ids=tuple(value.get("span_ids", ())),
            attributes=_frozen(
                _mapping(value.get("attributes", {}), "attributes"), "attributes"
            ),
        )


@dataclass(frozen=True, slots=True)
class ResourceAlgebra:
    """Named resource algebra with its unit set and composition law."""

    algebra_id: str
    kind: ResourceAlgebraKind | str
    unit_ids: tuple[str, ...] = ()
    composition: str = "disjoint_sum"
    source_ref_ids: tuple[str, ...] = ()
    span_ids: tuple[str, ...] = ()
    attributes: FrozenMap = field(default_factory=FrozenMap)

    def __post_init__(self) -> None:
        sources, spans = _source_map(
            self.source_ref_ids, self.span_ids, owner="ResourceAlgebra"
        )
        kind = _enum(self.kind, ResourceAlgebraKind, "kind")
        composition = _text(self.composition, "composition")
        allowed = {
            "disjoint_sum",
            "permission_sum",
            "counting_sum",
            "custom",
        }
        if composition not in allowed:
            raise HeapValidationError(
                f"composition must be one of {sorted(allowed)}"
            )
        if kind is ResourceAlgebraKind.CUSTOM and composition != "custom":
            raise HeapValidationError(
                "custom resource algebras require composition='custom'"
            )
        object.__setattr__(
            self, "algebra_id", _identifier(self.algebra_id, "algebra_id")
        )
        object.__setattr__(self, "kind", kind)
        object.__setattr__(
            self, "unit_ids", _identifiers(self.unit_ids, "unit_ids")
        )
        object.__setattr__(self, "composition", composition)
        object.__setattr__(self, "attributes", _frozen(self.attributes, "attributes"))
        object.__setattr__(self, "source_ref_ids", sources)
        object.__setattr__(self, "span_ids", spans)

    def to_dict(self) -> dict[str, Any]:
        return {
            "algebra_id": self.algebra_id,
            "attributes": self.attributes.to_dict(),
            "composition": self.composition,
            "kind": self.kind.value,
            "source_ref_ids": list(self.source_ref_ids),
            "span_ids": list(self.span_ids),
            "unit_ids": list(self.unit_ids),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> ResourceAlgebra:
        value = _mapping(value, "resource algebra")
        _reject_unknown(
            value,
            frozenset(
                {
                    "algebra_id",
                    "attributes",
                    "composition",
                    "kind",
                    "source_ref_ids",
                    "span_ids",
                    "unit_ids",
                }
            ),
            "resource algebra",
        )
        return cls(
            algebra_id=value.get("algebra_id", ""),
            kind=value.get("kind", ""),
            unit_ids=tuple(value.get("unit_ids", ())),
            composition=value.get("composition", "disjoint_sum"),
            source_ref_ids=tuple(value.get("source_ref_ids", ())),
            span_ids=tuple(value.get("span_ids", ())),
            attributes=_frozen(
                _mapping(value.get("attributes", {}), "attributes"), "attributes"
            ),
        )


def combine_permissions(
    *permissions: Permission | Mapping[str, Any] | int,
) -> Permission:
    """Sum permissions under the conservation law; fail if the total exceeds 1."""

    total = Permission.none()
    for item in permissions:
        total = total + Permission.from_fraction(item)
    return total


def locations_are_disjoint(
    left: Sequence[str],
    right: Sequence[str],
) -> bool:
    """Return whether two location sets have empty intersection."""

    return not (set(left) & set(right))


@dataclass(frozen=True, slots=True)
class HeapModel:
    """Finite, typed heap fragment with ownership, aliasing, and resources.

    Construction validates:
    * source maps and identifier uniqueness;
    * points-to typing (location and value types agree when both are concrete);
    * permission conservation per location;
    * exclusive ownership uniqueness per location;
    * alias-class location references.
    """

    locations: tuple[HeapLocation, ...]
    values: tuple[HeapValue, ...]
    cells: tuple[PointsToCell, ...] = ()
    ownership: tuple[OwnershipRecord, ...] = ()
    aliases: tuple[AliasClass, ...] = ()
    resource_units: tuple[ResourceUnit, ...] = ()
    resource_algebras: tuple[ResourceAlgebra, ...] = ()
    metadata: FrozenMap = field(default_factory=FrozenMap)
    model_id: str = ""
    schema_version: str = HEAP_MODEL_SCHEMA_VERSION

    def __post_init__(self) -> None:
        record_types = {
            "locations": (HeapLocation, "location_id"),
            "values": (HeapValue, "value_id"),
            "cells": (PointsToCell, "cell_id"),
            "ownership": (OwnershipRecord, "ownership_id"),
            "aliases": (AliasClass, "alias_id"),
            "resource_units": (ResourceUnit, "unit_id"),
            "resource_algebras": (ResourceAlgebra, "algebra_id"),
        }
        for name, (record_type, id_field) in record_types.items():
            object.__setattr__(
                self,
                name,
                tuple(
                    sorted(
                        (
                            item
                            if isinstance(item, record_type)
                            else record_type.from_dict(_mapping(item, name))
                            for item in _sequence(getattr(self, name), name)
                        ),
                        key=lambda item: getattr(item, id_field),
                    )
                ),
            )
        object.__setattr__(self, "metadata", _frozen(self.metadata, "metadata"))
        if self.schema_version != HEAP_MODEL_SCHEMA_VERSION:
            raise HeapValidationError(
                f"unsupported schema_version {self.schema_version!r}"
            )
        self.validate()
        if self.model_id:
            # model_id is advisory here; SeparationLogicIR owns content addressing.
            object.__setattr__(self, "model_id", _identifier(self.model_id, "model_id"))

    @property
    def interface(self) -> str:
        return HEAP_MODEL_INTERFACE

    def location_ids(self) -> set[str]:
        return {item.location_id for item in self.locations}

    def value_ids(self) -> set[str]:
        return {item.value_id for item in self.values}

    def permission_at(self, location_id: str) -> Permission:
        total = Permission.none()
        for cell in self.cells:
            if cell.location_id == location_id:
                total = total + cell.permission
        return total

    def is_disjoint(self, left_location_ids: Sequence[str], right_location_ids: Sequence[str]) -> bool:
        return locations_are_disjoint(left_location_ids, right_location_ids)

    def validate(self) -> None:
        def unique(values: Sequence[object], attr: str, label: str) -> set[str]:
            ids = [getattr(item, attr) for item in values]
            if len(ids) != len(set(ids)):
                raise HeapValidationError(f"duplicate {label} identifiers")
            return set(ids)

        location_ids = unique(self.locations, "location_id", "location")
        value_ids = unique(self.values, "value_id", "value")
        unique(self.cells, "cell_id", "points-to cell")
        unique(self.ownership, "ownership_id", "ownership")
        unique(self.aliases, "alias_id", "alias class")
        unit_ids = unique(self.resource_units, "unit_id", "resource unit")
        unique(self.resource_algebras, "algebra_id", "resource algebra")

        if not self.locations:
            raise HeapValidationError("a heap model requires at least one location")

        values_by_id = {item.value_id: item for item in self.values}
        locations_by_id = {item.location_id: item for item in self.locations}

        for value in self.values:
            if value.points_to_location_id:
                if value.points_to_location_id not in location_ids:
                    raise HeapValidationError(
                        f"value {value.value_id} points to unknown location "
                        f"{value.points_to_location_id!r}"
                    )

        # Permission conservation and typed points-to.
        permission_totals: dict[str, Permission] = {}
        for cell in self.cells:
            if cell.location_id not in location_ids:
                raise HeapValidationError(
                    f"cell {cell.cell_id} references unknown location "
                    f"{cell.location_id!r}"
                )
            if cell.value_id not in value_ids:
                raise HeapValidationError(
                    f"cell {cell.cell_id} references unknown value {cell.value_id!r}"
                )
            location = locations_by_id[cell.location_id]
            value = values_by_id[cell.value_id]
            if (
                location.type_name
                and value.type_name
                and location.type_name != value.type_name
                and value.kind is not ValueKind.NULL
            ):
                # Pointer cells store a value of the location's declared type.
                # Allow abstract values to stand for any type.
                if (
                    value.kind is not ValueKind.ABSTRACT
                    and location.kind is not LocationKind.ABSTRACT
                ):
                    raise HeapValidationError(
                        f"cell {cell.cell_id} type mismatch: location type "
                        f"{location.type_name!r} vs value type {value.type_name!r}"
                    )
            prior = permission_totals.get(cell.location_id, Permission.none())
            try:
                permission_totals[cell.location_id] = prior + cell.permission
            except HeapValidationError as error:
                raise HeapValidationError(
                    f"permission conservation violated at location "
                    f"{cell.location_id!r}: {error}"
                ) from error

        # Ownership typing and exclusivity.
        exclusive_locations: set[str] = set()
        ownership_permission: dict[str, Permission] = {}
        for record in self.ownership:
            if record.location_id not in location_ids:
                raise HeapValidationError(
                    f"ownership {record.ownership_id} references unknown location "
                    f"{record.location_id!r}"
                )
            if record.kind is OwnershipKind.EXCLUSIVE:
                if record.location_id in exclusive_locations:
                    raise HeapValidationError(
                        f"location {record.location_id!r} has multiple exclusive owners"
                    )
                exclusive_locations.add(record.location_id)
            prior = ownership_permission.get(record.location_id, Permission.none())
            try:
                ownership_permission[record.location_id] = prior + record.permission
            except HeapValidationError as error:
                raise HeapValidationError(
                    f"ownership permission conservation violated at "
                    f"{record.location_id!r}: {error}"
                ) from error

        for alias in self.aliases:
            missing = sorted(set(alias.location_ids) - location_ids)
            if missing:
                raise HeapValidationError(
                    f"alias class {alias.alias_id} references unknown locations {missing}"
                )
            if alias.kind is AliasClassKind.MUST_NOT_ALIAS:
                # must-not-alias classes still list the pairwise participants
                pass
            if alias.type_name:
                mismatched = sorted(
                    {
                        locations_by_id[loc_id].type_name
                        for loc_id in alias.location_ids
                        if locations_by_id[loc_id].type_name != alias.type_name
                        and locations_by_id[loc_id].kind is not LocationKind.ABSTRACT
                    }
                )
                if mismatched:
                    raise HeapValidationError(
                        f"alias class {alias.alias_id} type_name {alias.type_name!r} "
                        f"conflicts with location types {mismatched}"
                    )

        for unit in self.resource_units:
            if unit.location_id and unit.location_id not in location_ids:
                raise HeapValidationError(
                    f"resource unit {unit.unit_id} references unknown location "
                    f"{unit.location_id!r}"
                )

        for algebra in self.resource_algebras:
            missing = sorted(set(algebra.unit_ids) - unit_ids)
            if missing:
                raise HeapValidationError(
                    f"resource algebra {algebra.algebra_id} references unknown units {missing}"
                )

    def to_dict(self) -> dict[str, Any]:
        return {
            "aliases": [item.to_dict() for item in self.aliases],
            "cells": [item.to_dict() for item in self.cells],
            "interface": HEAP_MODEL_INTERFACE,
            "locations": [item.to_dict() for item in self.locations],
            "metadata": self.metadata.to_dict(),
            "model_id": self.model_id,
            "ownership": [item.to_dict() for item in self.ownership],
            "resource_algebras": [item.to_dict() for item in self.resource_algebras],
            "resource_units": [item.to_dict() for item in self.resource_units],
            "schema_version": self.schema_version,
            "values": [item.to_dict() for item in self.values],
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> HeapModel:
        value = _mapping(value, "heap model")
        _reject_unknown(
            value,
            frozenset(
                {
                    "aliases",
                    "cells",
                    "interface",
                    "locations",
                    "metadata",
                    "model_id",
                    "ownership",
                    "resource_algebras",
                    "resource_units",
                    "schema_version",
                    "values",
                }
            ),
            "heap model",
        )
        if value.get("interface", HEAP_MODEL_INTERFACE) not in {
            HEAP_MODEL_INTERFACE,
            "",
        }:
            raise HeapValidationError("unsupported heap model interface")
        return cls(
            locations=tuple(value.get("locations", ())),
            values=tuple(value.get("values", ())),
            cells=tuple(value.get("cells", ())),
            ownership=tuple(value.get("ownership", ())),
            aliases=tuple(value.get("aliases", ())),
            resource_units=tuple(value.get("resource_units", ())),
            resource_algebras=tuple(value.get("resource_algebras", ())),
            metadata=_frozen(
                _mapping(value.get("metadata", {}), "metadata"), "metadata"
            ),
            model_id=value.get("model_id", ""),
            schema_version=value.get("schema_version", HEAP_MODEL_SCHEMA_VERSION),
        )


__all__ = [
    "HEAP_MODEL_INTERFACE",
    "HEAP_MODEL_SCHEMA_VERSION",
    "PERMISSION_SCHEMA_VERSION",
    "AliasClass",
    "AliasClassKind",
    "HeapLocation",
    "HeapModel",
    "HeapValidationError",
    "HeapValue",
    "LocationKind",
    "OwnershipKind",
    "OwnershipRecord",
    "Permission",
    "PointsToCell",
    "ResourceAlgebra",
    "ResourceAlgebraKind",
    "ResourceUnit",
    "ValueKind",
    "combine_permissions",
    "locations_are_disjoint",
]
