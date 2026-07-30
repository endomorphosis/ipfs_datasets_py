"""Provider-neutral separation, ownership-transfer, and frame-obligation IR.

``SeparationLogicIR`` binds heap models and separation-logic formulas to exact
source bytes.  Separating conjunction (``*``) is a distinct connective from
ordinary conjunction (``∧``).  Frame inference produces explicit
:class:`FrameObligation` records; it never silently drops heap context.

Lowering to plain first-order logic is intentionally fail-closed.  Only heap
theories and formula fragments listed as FOL-lowerable are accepted; every
other construct raises :class:`SeparationLoweringError` so unsupported heap
theories cannot become uninterpreted FOL claims.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Final, Protocol

from ipfs_datasets_py.logic.ir_core.canonical import canonical_json_bytes
from ipfs_datasets_py.logic.ir_core.claims import FrozenMap
from ipfs_datasets_py.logic.ir_core.identity import (
    CanonicalIdentity,
    canonical_identity,
)
from ipfs_datasets_py.logic.ir_core.provenance import SourceRef, SourceSpan

from .heap import (
    HEAP_MODEL_SCHEMA_VERSION,
    AliasClass,
    HeapLocation,
    HeapModel,
    HeapValidationError,
    HeapValue,
    OwnershipRecord,
    Permission,
    PointsToCell,
    ResourceAlgebra,
    ResourceUnit,
    locations_are_disjoint,
)

SEPARATION_LOGIC_IR_INTERFACE: Final = "SeparationLogicIR@1"
SEPARATION_LOGIC_IR_SCHEMA_VERSION: Final = "separation-logic-ir/v1"
SEPARATION_LOGIC_IR_IDENTITY_DOMAIN: Final = (
    "logic.software-verification.separation"
)

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")
_OBSERVATIONAL_KEYS = frozenset(
    {
        "clock",
        "duration",
        "duration_ms",
        "elapsed",
        "elapsed_ms",
        "ended_at",
        "environment",
        "finished_at",
        "host",
        "hostname",
        "resource_usage",
        "started_at",
        "timing",
        "wall_time",
    }
)


class SeparationValidationError(ValueError):
    """Raised when separation-logic semantics are malformed or ambiguous."""


class SeparationLoweringError(SeparationValidationError):
    """Raised when a heap theory or formula cannot lower to plain FOL."""


class _SourceMapped(Protocol):
    @property
    def source_ref_ids(self) -> tuple[str, ...]: ...

    @property
    def span_ids(self) -> tuple[str, ...]: ...


class HeapTheory(StrEnum):
    """Closed vocabulary of heap theories for ``SeparationLogicIR@1``.

    Only :attr:`CLASSICAL_SL` and :attr:`FRACTIONAL_PERMISSION` currently admit
    a partial FOL encoding, and even then only for a restricted pure fragment.
    Theories such as :attr:`CUSTOM` and :attr:`SEPARATION_LOGIC_WITH_WAND` never
    lower silently.
    """

    CLASSICAL_SL = "classical_sl"
    FRACTIONAL_PERMISSION = "fractional_permission"
    BINARY_PERMISSION = "binary_permission"
    COUNTING_PERMISSION = "counting_permission"
    SEPARATION_LOGIC_WITH_WAND = "separation_logic_with_wand"
    HIGHER_ORDER_SL = "higher_order_sl"
    CUSTOM = "custom"


# Theories that may partially lower pure (non-spatial) subformulas to FOL.
_FOL_PARTIAL_THEORIES: Final[frozenset[HeapTheory]] = frozenset(
    {
        HeapTheory.CLASSICAL_SL,
        HeapTheory.FRACTIONAL_PERMISSION,
        HeapTheory.BINARY_PERMISSION,
    }
)

# Spatial connectives that never have a silent FOL encoding.
_SPATIAL_CONNECTIVES: Final[frozenset[str]] = frozenset(
    {
        "emp",
        "points_to",
        "sep_conj",
        "wand",
        "septraction",
    }
)


class FormulaKind(StrEnum):
    """Connectives and atoms of the separation-logic formula language.

    ``SEP_CONJ`` is separating conjunction ``*``.  ``AND`` is ordinary
    classical conjunction ``∧``.  The two are intentionally distinct values
    so callers cannot confuse them and so identity encodings differ.
    """

    EMP = "emp"
    TRUE = "true"
    FALSE = "false"
    PURE = "pure"
    POINTS_TO = "points_to"
    SEP_CONJ = "sep_conj"
    AND = "and"
    OR = "or"
    NOT = "not"
    IMPLIES = "implies"
    WAND = "wand"
    SEPTRACTION = "septraction"
    EXISTS = "exists"
    FORALL = "forall"


class FrameObligationKind(StrEnum):
    """Why a frame fragment must be preserved across a command or proof step."""

    FRAME_RULE = "frame_rule"
    MODIFIES_CLAUSE = "modifies_clause"
    OWNERSHIP_TRANSFER = "ownership_transfer"
    RESOURCE_INVARIANT = "resource_invariant"
    CALLER_CONTEXT = "caller_context"
    MANUAL = "manual"


class OwnershipTransferKind(StrEnum):
    """Direction of an ownership/permission transfer between principals."""

    MOVE = "move"
    SHARE = "share"
    BORROW = "borrow"
    RETURN = "return"
    RELEASE = "release"


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
        raise SeparationValidationError(
            f"{label} must be {qualifier}non-empty trimmed string without NUL bytes"
        )
    return value


def _identifier(value: object, label: str) -> str:
    result = _text(value, label)
    if not _ID_RE.fullmatch(result):
        raise SeparationValidationError(f"{label} must be a stable identifier")
    return result


def _enum(value: object, enum_type: type[StrEnum], label: str) -> Any:
    try:
        return value if isinstance(value, enum_type) else enum_type(value)
    except (TypeError, ValueError) as error:
        choices = ", ".join(repr(item.value) for item in enum_type)
        raise SeparationValidationError(f"{label} must be one of {choices}") from error


def _sequence(value: object, label: str) -> Sequence[Any]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise SeparationValidationError(f"{label} must be a sequence")
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
        raise SeparationValidationError(f"{label} must not be empty")
    if len(result) != len(set(result)):
        raise SeparationValidationError(f"{label} must not contain duplicates")
    return tuple(sorted(result)) if sort else result


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise SeparationValidationError(f"{label} must be a mapping")
    return value


def _frozen(value: Mapping[str, Any] | FrozenMap, label: str) -> FrozenMap:
    try:
        return value if isinstance(value, FrozenMap) else FrozenMap(value)
    except (TypeError, ValueError) as error:
        raise SeparationValidationError(
            f"{label} must contain immutable JSON-compatible data"
        ) from error


def _reject_unknown(
    value: Mapping[str, Any], allowed: frozenset[str], label: str
) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise SeparationValidationError(
            f"unknown {label} field(s): {', '.join(unknown)}"
        )


def _source_map(
    source_ref_ids: object,
    span_ids: object,
    *,
    owner: str,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    sources = _identifiers(source_ref_ids, f"{owner}.source_ref_ids")
    spans = _identifiers(span_ids, f"{owner}.span_ids")
    if not sources and not spans:
        raise SeparationValidationError(
            f"{owner} must be source mapped with source_ref_ids or span_ids"
        )
    return sources, spans


def _reject_observations(value: Mapping[str, Any], *, label: str) -> None:
    offending: list[str] = []

    def visit(item: object, path: str) -> None:
        if isinstance(item, Mapping):
            for key, child in item.items():
                child_path = f"{path}.{key}" if path else key
                if key.casefold().replace("-", "_") in _OBSERVATIONAL_KEYS:
                    offending.append(child_path)
                visit(child, child_path)
        elif isinstance(item, tuple):
            for index, child in enumerate(item):
                visit(child, f"{path}[{index}]")

    visit(value, "")
    if offending:
        raise SeparationValidationError(
            f"{label} contains observational keys {sorted(offending)}; "
            "put runtime output in observations"
        )


@dataclass(frozen=True, slots=True)
class SeparationFormula:
    """Immutable separation-logic formula node.

    Spatial atoms and connectives keep their own kind tags.  In particular
    ``FormulaKind.SEP_CONJ`` and ``FormulaKind.AND`` are never interchangeable:
    they differ in :meth:`kind`, in :meth:`is_spatial`, and in the identity
    preimage.
    """

    formula_id: str
    kind: FormulaKind | str
    # Operand formula ids for compound connectives (order preserved).
    operand_ids: tuple[str, ...] = ()
    # Points-to atom fields.
    location_id: str = ""
    value_id: str = ""
    permission: Permission | None = None
    # Pure assertion text / expression identifier.
    pure_expression: str = ""
    pure_expression_id: str = ""
    # Quantifier binder.
    bound_variable: str = ""
    bound_type: str = ""
    source_ref_ids: tuple[str, ...] = ()
    span_ids: tuple[str, ...] = ()
    attributes: FrozenMap = field(default_factory=FrozenMap)

    def __post_init__(self) -> None:
        sources, spans = _source_map(
            self.source_ref_ids, self.span_ids, owner="SeparationFormula"
        )
        kind = _enum(self.kind, FormulaKind, "kind")
        operands = tuple(
            _identifier(item, "operand_ids item")
            for item in _sequence(self.operand_ids, "operand_ids")
        )
        if len(operands) != len(set(operands)):
            # Operand DAGs may intentionally reuse shared pure subtrees via
            # separate formula ids; duplicate *ids in one node* are still wrong.
            raise SeparationValidationError(
                "operand_ids must not contain duplicates within one formula node"
            )

        location_id = _text(self.location_id, "location_id", optional=True)
        value_id = _text(self.value_id, "value_id", optional=True)
        pure_expression = _text(
            self.pure_expression, "pure_expression", optional=True
        )
        pure_expression_id = _text(
            self.pure_expression_id, "pure_expression_id", optional=True
        )
        bound_variable = _text(
            self.bound_variable, "bound_variable", optional=True
        )
        bound_type = _text(self.bound_type, "bound_type", optional=True)

        permission: Permission | None
        if self.permission is None:
            permission = None
        else:
            permission = Permission.from_fraction(self.permission)

        if kind is FormulaKind.EMP:
            if operands or location_id or value_id or pure_expression or permission:
                raise SeparationValidationError(
                    "emp formulas take no operands, locations, values, or pure text"
                )
        elif kind is FormulaKind.TRUE or kind is FormulaKind.FALSE:
            if operands or location_id or value_id or pure_expression or permission:
                raise SeparationValidationError(
                    f"{kind.value} formulas take no operands or spatial atoms"
                )
        elif kind is FormulaKind.PURE:
            if not pure_expression and not pure_expression_id:
                raise SeparationValidationError(
                    "pure formulas require pure_expression or pure_expression_id"
                )
            if location_id or value_id or permission is not None:
                raise SeparationValidationError(
                    "pure formulas must not carry spatial points-to fields"
                )
            if operands:
                raise SeparationValidationError("pure formulas take no operands")
        elif kind is FormulaKind.POINTS_TO:
            if not location_id or not value_id:
                raise SeparationValidationError(
                    "points_to formulas require location_id and value_id"
                )
            if permission is None:
                permission = Permission.full()
            if permission.is_empty:
                raise SeparationValidationError(
                    "points_to formulas require a strictly positive permission"
                )
            if operands:
                raise SeparationValidationError("points_to formulas take no operands")
        elif kind in {
            FormulaKind.SEP_CONJ,
            FormulaKind.AND,
            FormulaKind.OR,
            FormulaKind.WAND,
            FormulaKind.SEPTRACTION,
            FormulaKind.IMPLIES,
        }:
            if len(operands) < 2:
                raise SeparationValidationError(
                    f"{kind.value} requires at least two operand_ids"
                )
            if location_id or value_id or permission is not None:
                raise SeparationValidationError(
                    f"{kind.value} must not carry points-to atom fields"
                )
        elif kind is FormulaKind.NOT:
            if len(operands) != 1:
                raise SeparationValidationError("not requires exactly one operand")
        elif kind in {FormulaKind.EXISTS, FormulaKind.FORALL}:
            if len(operands) != 1:
                raise SeparationValidationError(
                    f"{kind.value} requires exactly one body operand"
                )
            if not bound_variable:
                raise SeparationValidationError(
                    f"{kind.value} requires bound_variable"
                )
        else:  # pragma: no cover - enum exhaustiveness
            raise SeparationValidationError(f"unsupported formula kind {kind!r}")

        object.__setattr__(
            self, "formula_id", _identifier(self.formula_id, "formula_id")
        )
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "operand_ids", operands)
        object.__setattr__(self, "location_id", location_id)
        object.__setattr__(self, "value_id", value_id)
        object.__setattr__(self, "permission", permission)
        object.__setattr__(self, "pure_expression", pure_expression)
        object.__setattr__(self, "pure_expression_id", pure_expression_id)
        object.__setattr__(self, "bound_variable", bound_variable)
        object.__setattr__(self, "bound_type", bound_type)
        object.__setattr__(self, "attributes", _frozen(self.attributes, "attributes"))
        object.__setattr__(self, "source_ref_ids", sources)
        object.__setattr__(self, "span_ids", spans)

    @property
    def is_spatial(self) -> bool:
        return self.kind.value in _SPATIAL_CONNECTIVES

    @property
    def is_separating_conjunction(self) -> bool:
        return self.kind is FormulaKind.SEP_CONJ

    @property
    def is_ordinary_conjunction(self) -> bool:
        return self.kind is FormulaKind.AND

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": self.attributes.to_dict(),
            "bound_type": self.bound_type,
            "bound_variable": self.bound_variable,
            "formula_id": self.formula_id,
            "kind": self.kind.value,
            "location_id": self.location_id,
            "operand_ids": list(self.operand_ids),
            "permission": (
                self.permission.to_dict() if self.permission is not None else None
            ),
            "pure_expression": self.pure_expression,
            "pure_expression_id": self.pure_expression_id,
            "source_ref_ids": list(self.source_ref_ids),
            "span_ids": list(self.span_ids),
            "value_id": self.value_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> SeparationFormula:
        value = _mapping(value, "separation formula")
        _reject_unknown(
            value,
            frozenset(
                {
                    "attributes",
                    "bound_type",
                    "bound_variable",
                    "formula_id",
                    "kind",
                    "location_id",
                    "operand_ids",
                    "permission",
                    "pure_expression",
                    "pure_expression_id",
                    "source_ref_ids",
                    "span_ids",
                    "value_id",
                }
            ),
            "separation formula",
        )
        permission_raw = value.get("permission")
        permission: Permission | None
        if permission_raw is None:
            permission = None
        else:
            permission = Permission.from_fraction(permission_raw)
        return cls(
            formula_id=value.get("formula_id", ""),
            kind=value.get("kind", ""),
            operand_ids=tuple(value.get("operand_ids", ())),
            location_id=value.get("location_id", ""),
            value_id=value.get("value_id", ""),
            permission=permission,
            pure_expression=value.get("pure_expression", ""),
            pure_expression_id=value.get("pure_expression_id", ""),
            bound_variable=value.get("bound_variable", ""),
            bound_type=value.get("bound_type", ""),
            source_ref_ids=tuple(value.get("source_ref_ids", ())),
            span_ids=tuple(value.get("span_ids", ())),
            attributes=_frozen(
                _mapping(value.get("attributes", {}), "attributes"), "attributes"
            ),
        )


@dataclass(frozen=True, slots=True)
class FrameObligation:
    """Explicit frame that must be preserved across a proof or command step.

    Frame inference always materializes one of these records.  An empty
    ``frame_formula_id`` is rejected: the absence of a frame must be written
    as the ``emp`` formula, never as a missing obligation.
    """

    obligation_id: str
    kind: FrameObligationKind | str
    frame_formula_id: str
    footprint_location_ids: tuple[str, ...] = ()
    modified_location_ids: tuple[str, ...] = ()
    parent_formula_id: str = ""
    command_id: str = ""
    statement: str = ""
    source_ref_ids: tuple[str, ...] = ()
    span_ids: tuple[str, ...] = ()
    attributes: FrozenMap = field(default_factory=FrozenMap)

    def __post_init__(self) -> None:
        sources, spans = _source_map(
            self.source_ref_ids, self.span_ids, owner="FrameObligation"
        )
        footprint = _identifiers(
            self.footprint_location_ids, "footprint_location_ids"
        )
        modified = _identifiers(self.modified_location_ids, "modified_location_ids")
        if set(footprint) & set(modified):
            raise SeparationValidationError(
                "frame footprint and modified locations must be disjoint"
            )
        object.__setattr__(
            self, "obligation_id", _identifier(self.obligation_id, "obligation_id")
        )
        object.__setattr__(self, "kind", _enum(self.kind, FrameObligationKind, "kind"))
        object.__setattr__(
            self,
            "frame_formula_id",
            _identifier(self.frame_formula_id, "frame_formula_id"),
        )
        object.__setattr__(self, "footprint_location_ids", footprint)
        object.__setattr__(self, "modified_location_ids", modified)
        object.__setattr__(
            self,
            "parent_formula_id",
            _text(self.parent_formula_id, "parent_formula_id", optional=True),
        )
        object.__setattr__(
            self, "command_id", _text(self.command_id, "command_id", optional=True)
        )
        object.__setattr__(
            self, "statement", _text(self.statement, "statement", optional=True)
        )
        object.__setattr__(self, "attributes", _frozen(self.attributes, "attributes"))
        object.__setattr__(self, "source_ref_ids", sources)
        object.__setattr__(self, "span_ids", spans)

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": self.attributes.to_dict(),
            "command_id": self.command_id,
            "footprint_location_ids": list(self.footprint_location_ids),
            "frame_formula_id": self.frame_formula_id,
            "kind": self.kind.value,
            "modified_location_ids": list(self.modified_location_ids),
            "obligation_id": self.obligation_id,
            "parent_formula_id": self.parent_formula_id,
            "source_ref_ids": list(self.source_ref_ids),
            "span_ids": list(self.span_ids),
            "statement": self.statement,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> FrameObligation:
        value = _mapping(value, "frame obligation")
        _reject_unknown(
            value,
            frozenset(
                {
                    "attributes",
                    "command_id",
                    "footprint_location_ids",
                    "frame_formula_id",
                    "kind",
                    "modified_location_ids",
                    "obligation_id",
                    "parent_formula_id",
                    "source_ref_ids",
                    "span_ids",
                    "statement",
                }
            ),
            "frame obligation",
        )
        return cls(
            obligation_id=value.get("obligation_id", ""),
            kind=value.get("kind", ""),
            frame_formula_id=value.get("frame_formula_id", ""),
            footprint_location_ids=tuple(value.get("footprint_location_ids", ())),
            modified_location_ids=tuple(value.get("modified_location_ids", ())),
            parent_formula_id=value.get("parent_formula_id", ""),
            command_id=value.get("command_id", ""),
            statement=value.get("statement", ""),
            source_ref_ids=tuple(value.get("source_ref_ids", ())),
            span_ids=tuple(value.get("span_ids", ())),
            attributes=_frozen(
                _mapping(value.get("attributes", {}), "attributes"), "attributes"
            ),
        )


@dataclass(frozen=True, slots=True)
class OwnershipTransfer:
    """Explicit ownership or permission transfer between principals."""

    transfer_id: str
    kind: OwnershipTransferKind | str
    location_id: str
    from_owner_id: str
    to_owner_id: str
    permission: Permission = field(default_factory=Permission.full)
    formula_id: str = ""
    source_ref_ids: tuple[str, ...] = ()
    span_ids: tuple[str, ...] = ()
    attributes: FrozenMap = field(default_factory=FrozenMap)

    def __post_init__(self) -> None:
        sources, spans = _source_map(
            self.source_ref_ids, self.span_ids, owner="OwnershipTransfer"
        )
        kind = _enum(self.kind, OwnershipTransferKind, "kind")
        permission = Permission.from_fraction(self.permission)
        if permission.is_empty:
            raise SeparationValidationError(
                "ownership transfers require a strictly positive permission"
            )
        if kind is OwnershipTransferKind.MOVE and not permission.is_full:
            raise SeparationValidationError(
                "move transfers require full permission"
            )
        if kind is OwnershipTransferKind.SHARE and permission.is_full:
            raise SeparationValidationError(
                "share transfers require a fractional permission strictly less than 1"
            )
        from_owner = _identifier(self.from_owner_id, "from_owner_id")
        to_owner = _identifier(self.to_owner_id, "to_owner_id")
        if from_owner == to_owner:
            raise SeparationValidationError(
                "ownership transfer principals must differ"
            )
        object.__setattr__(
            self, "transfer_id", _identifier(self.transfer_id, "transfer_id")
        )
        object.__setattr__(self, "kind", kind)
        object.__setattr__(
            self, "location_id", _identifier(self.location_id, "location_id")
        )
        object.__setattr__(self, "from_owner_id", from_owner)
        object.__setattr__(self, "to_owner_id", to_owner)
        object.__setattr__(self, "permission", permission)
        object.__setattr__(
            self, "formula_id", _text(self.formula_id, "formula_id", optional=True)
        )
        object.__setattr__(self, "attributes", _frozen(self.attributes, "attributes"))
        object.__setattr__(self, "source_ref_ids", sources)
        object.__setattr__(self, "span_ids", spans)

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": self.attributes.to_dict(),
            "formula_id": self.formula_id,
            "from_owner_id": self.from_owner_id,
            "kind": self.kind.value,
            "location_id": self.location_id,
            "permission": self.permission.to_dict(),
            "source_ref_ids": list(self.source_ref_ids),
            "span_ids": list(self.span_ids),
            "to_owner_id": self.to_owner_id,
            "transfer_id": self.transfer_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> OwnershipTransfer:
        value = _mapping(value, "ownership transfer")
        _reject_unknown(
            value,
            frozenset(
                {
                    "attributes",
                    "formula_id",
                    "from_owner_id",
                    "kind",
                    "location_id",
                    "permission",
                    "source_ref_ids",
                    "span_ids",
                    "to_owner_id",
                    "transfer_id",
                }
            ),
            "ownership transfer",
        )
        return cls(
            transfer_id=value.get("transfer_id", ""),
            kind=value.get("kind", ""),
            location_id=value.get("location_id", ""),
            from_owner_id=value.get("from_owner_id", ""),
            to_owner_id=value.get("to_owner_id", ""),
            permission=Permission.from_fraction(
                value.get("permission", {"numerator": 1})
            ),
            formula_id=value.get("formula_id", ""),
            source_ref_ids=tuple(value.get("source_ref_ids", ())),
            span_ids=tuple(value.get("span_ids", ())),
            attributes=_frozen(
                _mapping(value.get("attributes", {}), "attributes"), "attributes"
            ),
        )


def infer_frame_obligation(
    *,
    obligation_id: str,
    precondition_formula_id: str,
    footprint_location_ids: Sequence[str],
    modified_location_ids: Sequence[str],
    frame_formula_id: str,
    kind: FrameObligationKind | str = FrameObligationKind.FRAME_RULE,
    command_id: str = "",
    statement: str = "",
    source_ref_ids: Sequence[str] = (),
    span_ids: Sequence[str] = (),
) -> FrameObligation:
    """Construct an explicit frame obligation from a footprint split.

    The caller supplies the frame formula (often ``emp`` or a residual heap
    assertion).  This helper only checks the disjointness discipline and
    materializes the obligation; it never invents or drops heap context.
    """

    footprint = _identifiers(footprint_location_ids, "footprint_location_ids")
    modified = _identifiers(modified_location_ids, "modified_location_ids")
    if not locations_are_disjoint(footprint, modified):
        raise SeparationValidationError(
            "frame inference requires footprint and modified locations to be disjoint"
        )
    return FrameObligation(
        obligation_id=obligation_id,
        kind=kind,
        frame_formula_id=frame_formula_id,
        footprint_location_ids=footprint,
        modified_location_ids=modified,
        parent_formula_id=precondition_formula_id,
        command_id=command_id,
        statement=statement
        or (
            f"Frame obligation: preserve {frame_formula_id} outside "
            f"modified locations {list(modified)}"
        ),
        source_ref_ids=tuple(source_ref_ids),
        span_ids=tuple(span_ids),
    )


@dataclass(frozen=True, slots=True)
class SeparationLogicIR:
    """Canonical, immutable, source-grounded separation-logic document.

    Interface: ``SeparationLogicIR@1``.
    """

    sources: tuple[SourceRef, ...]
    heap: HeapModel
    formulas: tuple[SeparationFormula, ...]
    root_formula_id: str
    spans: tuple[SourceSpan, ...] = ()
    frame_obligations: tuple[FrameObligation, ...] = ()
    ownership_transfers: tuple[OwnershipTransfer, ...] = ()
    heap_theory: HeapTheory | str = HeapTheory.CLASSICAL_SL
    metadata: FrozenMap = field(default_factory=FrozenMap)
    observations: FrozenMap = field(default_factory=FrozenMap)
    document_id: str = ""
    schema_version: str = SEPARATION_LOGIC_IR_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "sources",
            tuple(
                sorted(
                    (
                        item
                        if isinstance(item, SourceRef)
                        else SourceRef.from_dict(_mapping(item, "source"))
                        for item in _sequence(self.sources, "sources")
                    ),
                    key=lambda item: item.ref_id,
                )
            ),
        )
        object.__setattr__(
            self,
            "spans",
            tuple(
                sorted(
                    (
                        item
                        if isinstance(item, SourceSpan)
                        else SourceSpan.from_dict(_mapping(item, "span"))
                        for item in _sequence(self.spans, "spans")
                    ),
                    key=lambda item: item.span_id,
                )
            ),
        )
        heap = (
            self.heap
            if isinstance(self.heap, HeapModel)
            else HeapModel.from_dict(_mapping(self.heap, "heap"))
        )
        object.__setattr__(self, "heap", heap)
        object.__setattr__(
            self,
            "formulas",
            tuple(
                sorted(
                    (
                        item
                        if isinstance(item, SeparationFormula)
                        else SeparationFormula.from_dict(_mapping(item, "formula"))
                        for item in _sequence(self.formulas, "formulas")
                    ),
                    key=lambda item: item.formula_id,
                )
            ),
        )
        object.__setattr__(
            self,
            "frame_obligations",
            tuple(
                sorted(
                    (
                        item
                        if isinstance(item, FrameObligation)
                        else FrameObligation.from_dict(_mapping(item, "frame_obligation"))
                        for item in _sequence(
                            self.frame_obligations, "frame_obligations"
                        )
                    ),
                    key=lambda item: item.obligation_id,
                )
            ),
        )
        object.__setattr__(
            self,
            "ownership_transfers",
            tuple(
                sorted(
                    (
                        item
                        if isinstance(item, OwnershipTransfer)
                        else OwnershipTransfer.from_dict(
                            _mapping(item, "ownership_transfer")
                        )
                        for item in _sequence(
                            self.ownership_transfers, "ownership_transfers"
                        )
                    ),
                    key=lambda item: item.transfer_id,
                )
            ),
        )
        object.__setattr__(
            self, "root_formula_id", _identifier(self.root_formula_id, "root_formula_id")
        )
        object.__setattr__(
            self, "heap_theory", _enum(self.heap_theory, HeapTheory, "heap_theory")
        )
        metadata = _frozen(self.metadata, "metadata")
        observations = _frozen(self.observations, "observations")
        _reject_observations(metadata, label="metadata")
        object.__setattr__(self, "metadata", metadata)
        object.__setattr__(self, "observations", observations)

        if self.schema_version != SEPARATION_LOGIC_IR_SCHEMA_VERSION:
            raise SeparationValidationError(
                f"unsupported schema_version {self.schema_version!r}"
            )

        self.validate()
        computed = self._compute_identity()
        if self.document_id and self.document_id != computed.cid:
            raise SeparationValidationError(
                "document_id does not match canonical separation-logic semantics"
            )
        object.__setattr__(self, "document_id", computed.cid)

    @property
    def interface(self) -> str:
        return SEPARATION_LOGIC_IR_INTERFACE

    @property
    def identity(self) -> CanonicalIdentity:
        return self._compute_identity()

    @property
    def canonical_id(self) -> str:
        return self.document_id

    @property
    def sha256(self) -> str:
        return self.identity.hexdigest

    def _compute_identity(self) -> CanonicalIdentity:
        return canonical_identity(
            self.semantic_dict(),
            domain=SEPARATION_LOGIC_IR_IDENTITY_DOMAIN,
            schema_version=SEPARATION_LOGIC_IR_SCHEMA_VERSION,
        )

    def semantic_dict(self) -> dict[str, Any]:
        """Return the identity preimage, excluding runtime observations."""

        return {
            "formulas": [
                item.to_dict()
                for item in sorted(self.formulas, key=lambda item: item.formula_id)
            ],
            "frame_obligations": [
                item.to_dict()
                for item in sorted(
                    self.frame_obligations, key=lambda item: item.obligation_id
                )
            ],
            "heap": self.heap.to_dict(),
            "heap_theory": self.heap_theory.value,
            "interface": SEPARATION_LOGIC_IR_INTERFACE,
            "metadata": self.metadata.to_dict(),
            "ownership_transfers": [
                item.to_dict()
                for item in sorted(
                    self.ownership_transfers, key=lambda item: item.transfer_id
                )
            ],
            "root_formula_id": self.root_formula_id,
            "schema_version": self.schema_version,
            "sources": [
                item.to_dict()
                for item in sorted(self.sources, key=lambda item: item.ref_id)
            ],
            "spans": [
                item.to_dict()
                for item in sorted(self.spans, key=lambda item: item.span_id)
            ],
        }

    deterministic_dict = semantic_dict

    def to_dict(self) -> dict[str, Any]:
        result = self.semantic_dict()
        result["document_id"] = self.document_id
        result["observations"] = self.observations.to_dict()
        return result

    def semantic_bytes(self) -> bytes:
        return self.identity.canonical_bytes

    deterministic_bytes = semantic_bytes

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())

    def to_json(self) -> str:
        return self.canonical_bytes().decode("utf-8")

    def formula_by_id(self, formula_id: str) -> SeparationFormula:
        for formula in self.formulas:
            if formula.formula_id == formula_id:
                return formula
        raise SeparationValidationError(f"unknown formula {formula_id!r}")

    def spatial_formula_ids(self) -> tuple[str, ...]:
        return tuple(
            sorted(item.formula_id for item in self.formulas if item.is_spatial)
        )

    def validate(self) -> None:
        if not self.sources:
            raise SeparationValidationError(
                "a source-grounded SeparationLogicIR requires sources"
            )
        if not self.formulas:
            raise SeparationValidationError(
                "SeparationLogicIR requires at least one formula"
            )

        def unique(values: Sequence[object], attr: str, label: str) -> set[str]:
            ids = [getattr(item, attr) for item in values]
            if len(ids) != len(set(ids)):
                raise SeparationValidationError(f"duplicate {label} identifiers")
            return set(ids)

        source_ids = unique(self.sources, "ref_id", "source")
        unique(self.spans, "span_id", "span")
        formula_ids = unique(self.formulas, "formula_id", "formula")
        unique(self.frame_obligations, "obligation_id", "frame obligation")
        unique(self.ownership_transfers, "transfer_id", "ownership transfer")

        if self.root_formula_id not in formula_ids:
            raise SeparationValidationError(
                f"root_formula_id {self.root_formula_id!r} is not declared"
            )

        for source in self.sources:
            source.validate()
        spans_by_id = {item.span_id: item for item in self.spans}
        for span in self.spans:
            span.validate()
            if span.source_ref_id not in source_ids:
                raise SeparationValidationError(
                    f"span {span.span_id} references unknown source "
                    f"{span.source_ref_id!r}"
                )

        for item in (
            *self.formulas,
            *self.frame_obligations,
            *self.ownership_transfers,
            *self.heap.locations,
            *self.heap.values,
            *self.heap.cells,
            *self.heap.ownership,
            *self.heap.aliases,
            *self.heap.resource_units,
            *self.heap.resource_algebras,
        ):
            self._validate_source_map(item, source_ids, spans_by_id)

        location_ids = self.heap.location_ids()
        value_ids = self.heap.value_ids()
        formulas_by_id = {item.formula_id: item for item in self.formulas}

        for formula in self.formulas:
            for operand_id in formula.operand_ids:
                if operand_id not in formula_ids:
                    raise SeparationValidationError(
                        f"formula {formula.formula_id} references unknown operand "
                        f"{operand_id!r}"
                    )
                if operand_id == formula.formula_id:
                    raise SeparationValidationError(
                        f"formula {formula.formula_id} references itself"
                    )
            if formula.kind is FormulaKind.POINTS_TO:
                if formula.location_id not in location_ids:
                    raise SeparationValidationError(
                        f"points_to formula {formula.formula_id} references unknown "
                        f"location {formula.location_id!r}"
                    )
                if formula.value_id not in value_ids:
                    raise SeparationValidationError(
                        f"points_to formula {formula.formula_id} references unknown "
                        f"value {formula.value_id!r}"
                    )
            # Wand requires a heap theory that admits it.
            if formula.kind in {FormulaKind.WAND, FormulaKind.SEPTRACTION}:
                if self.heap_theory not in {
                    HeapTheory.SEPARATION_LOGIC_WITH_WAND,
                    HeapTheory.HIGHER_ORDER_SL,
                    HeapTheory.CUSTOM,
                }:
                    raise SeparationValidationError(
                        f"formula {formula.formula_id} uses {formula.kind.value} "
                        f"but heap_theory is {self.heap_theory.value!r}"
                    )

        self._reject_formula_cycles(formulas_by_id)

        for obligation in self.frame_obligations:
            if obligation.frame_formula_id not in formula_ids:
                raise SeparationValidationError(
                    f"frame obligation {obligation.obligation_id} references "
                    f"unknown frame formula {obligation.frame_formula_id!r}"
                )
            if (
                obligation.parent_formula_id
                and obligation.parent_formula_id not in formula_ids
            ):
                raise SeparationValidationError(
                    f"frame obligation {obligation.obligation_id} references "
                    f"unknown parent formula {obligation.parent_formula_id!r}"
                )
            missing_fp = sorted(
                set(obligation.footprint_location_ids) - location_ids
            )
            if missing_fp:
                raise SeparationValidationError(
                    f"frame obligation {obligation.obligation_id} has unknown "
                    f"footprint locations {missing_fp}"
                )
            missing_mod = sorted(
                set(obligation.modified_location_ids) - location_ids
            )
            if missing_mod:
                raise SeparationValidationError(
                    f"frame obligation {obligation.obligation_id} has unknown "
                    f"modified locations {missing_mod}"
                )

        for transfer in self.ownership_transfers:
            if transfer.location_id not in location_ids:
                raise SeparationValidationError(
                    f"ownership transfer {transfer.transfer_id} references unknown "
                    f"location {transfer.location_id!r}"
                )
            if transfer.formula_id and transfer.formula_id not in formula_ids:
                raise SeparationValidationError(
                    f"ownership transfer {transfer.transfer_id} references unknown "
                    f"formula {transfer.formula_id!r}"
                )

        # Fractional theories require non-full permissions to be expressible.
        if self.heap_theory is HeapTheory.BINARY_PERMISSION:
            for formula in self.formulas:
                if (
                    formula.kind is FormulaKind.POINTS_TO
                    and formula.permission is not None
                    and not formula.permission.is_full
                    and not formula.permission.is_empty
                ):
                    # Binary permission theory only admits 0/1; fractions fail.
                    if formula.permission.fraction not in (
                        Permission.none().fraction,
                        Permission.full().fraction,
                    ):
                        raise SeparationValidationError(
                            f"binary_permission theory rejects fractional "
                            f"permission on formula {formula.formula_id}"
                        )

    def _reject_formula_cycles(
        self, formulas_by_id: Mapping[str, SeparationFormula]
    ) -> None:
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(formula_id: str) -> None:
            if formula_id in visited:
                return
            if formula_id in visiting:
                raise SeparationValidationError(
                    f"formula graph contains a cycle at {formula_id!r}"
                )
            visiting.add(formula_id)
            formula = formulas_by_id[formula_id]
            for operand_id in formula.operand_ids:
                visit(operand_id)
            visiting.remove(formula_id)
            visited.add(formula_id)

        for formula_id in formulas_by_id:
            visit(formula_id)

    @classmethod
    def _validate_source_map(
        cls,
        item: _SourceMapped,
        source_ids: set[str],
        spans: Mapping[str, SourceSpan],
    ) -> None:
        sources = item.source_ref_ids
        span_ids = item.span_ids
        missing_sources = sorted(set(sources) - source_ids)
        if missing_sources:
            raise SeparationValidationError(
                f"source_ref_ids reference unknown sources {missing_sources}"
            )
        missing_spans = sorted(set(span_ids) - set(spans))
        if missing_spans:
            raise SeparationValidationError(
                f"span_ids reference unknown spans {missing_spans}"
            )
        if sources:
            unlisted = sorted(
                {
                    spans[span_id].source_ref_id
                    for span_id in span_ids
                    if spans[span_id].source_ref_id not in sources
                }
            )
            if unlisted:
                raise SeparationValidationError(
                    f"source-mapped item spans belong to unlisted sources {unlisted}"
                )

    def lower_to_fol(self) -> dict[str, Any]:
        """Attempt a fail-closed partial lowering of pure fragments to FOL.

        Spatial assertions (``emp``, points-to, ``*``, wand, septraction) never
        lower.  Unsupported heap theories raise immediately.  Successful pure
        lowerings are returned as a structured FOL sketch with an explicit
        residual of unlowered formula ids.
        """

        theory = self.heap_theory
        if theory not in _FOL_PARTIAL_THEORIES:
            raise SeparationLoweringError(
                f"heap theory {theory.value!r} cannot silently lower to plain FOL; "
                "supported partial theories are "
                f"{sorted(item.value for item in _FOL_PARTIAL_THEORIES)}"
            )
        if theory is HeapTheory.CUSTOM:
            raise SeparationLoweringError(
                "custom heap theories cannot lower to plain FOL"
            )

        formulas_by_id = {item.formula_id: item for item in self.formulas}
        pure_atoms: list[dict[str, Any]] = []
        residual: list[str] = []
        rejected_spatial: list[str] = []

        def lower_formula(formula_id: str) -> dict[str, Any] | None:
            formula = formulas_by_id[formula_id]
            if formula.is_spatial:
                rejected_spatial.append(formula_id)
                residual.append(formula_id)
                return None
            if formula.kind is FormulaKind.PURE:
                atom = {
                    "kind": "predicate",
                    "expression": formula.pure_expression,
                    "expression_id": formula.pure_expression_id,
                    "formula_id": formula.formula_id,
                }
                pure_atoms.append(atom)
                return atom
            if formula.kind is FormulaKind.TRUE:
                return {"kind": "true", "formula_id": formula.formula_id}
            if formula.kind is FormulaKind.FALSE:
                return {"kind": "false", "formula_id": formula.formula_id}
            if formula.kind is FormulaKind.AND:
                children = []
                for operand_id in formula.operand_ids:
                    child = lower_formula(operand_id)
                    if child is None:
                        residual.append(formula_id)
                        return None
                    children.append(child)
                return {
                    "kind": "and",
                    "operands": children,
                    "formula_id": formula.formula_id,
                }
            if formula.kind is FormulaKind.OR:
                children = []
                for operand_id in formula.operand_ids:
                    child = lower_formula(operand_id)
                    if child is None:
                        residual.append(formula_id)
                        return None
                    children.append(child)
                return {
                    "kind": "or",
                    "operands": children,
                    "formula_id": formula.formula_id,
                }
            if formula.kind is FormulaKind.NOT:
                child = lower_formula(formula.operand_ids[0])
                if child is None:
                    residual.append(formula_id)
                    return None
                return {
                    "kind": "not",
                    "operand": child,
                    "formula_id": formula.formula_id,
                }
            if formula.kind is FormulaKind.IMPLIES:
                left = lower_formula(formula.operand_ids[0])
                right = lower_formula(formula.operand_ids[1])
                if left is None or right is None:
                    residual.append(formula_id)
                    return None
                return {
                    "kind": "implies",
                    "left": left,
                    "right": right,
                    "formula_id": formula.formula_id,
                }
            if formula.kind in {FormulaKind.EXISTS, FormulaKind.FORALL}:
                body = lower_formula(formula.operand_ids[0])
                if body is None:
                    residual.append(formula_id)
                    return None
                return {
                    "kind": formula.kind.value,
                    "bound_variable": formula.bound_variable,
                    "bound_type": formula.bound_type,
                    "body": body,
                    "formula_id": formula.formula_id,
                }
            # Any other pure-looking connective is still rejected.
            residual.append(formula_id)
            return None

        root = lower_formula(self.root_formula_id)
        if rejected_spatial:
            # Spatial content in the root cone must never disappear into FOL.
            raise SeparationLoweringError(
                "spatial separation-logic constructs cannot silently lower to "
                f"plain FOL: {sorted(set(rejected_spatial))}"
            )
        if root is None:
            raise SeparationLoweringError(
                "root formula cannot lower to plain FOL; residual formulas "
                f"{sorted(set(residual))}"
            )
        return {
            "encoding": "fol-sketch/v1",
            "heap_theory": theory.value,
            "pure_atoms": pure_atoms,
            "residual_formula_ids": sorted(set(residual)),
            "root": root,
            "spatial_lowered": False,
        }

    def can_lower_to_fol(self) -> bool:
        try:
            self.lower_to_fol()
        except SeparationLoweringError:
            return False
        return True

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> SeparationLogicIR:
        value = _mapping(value, "separation document")
        _reject_unknown(
            value,
            frozenset(
                {
                    "document_id",
                    "formulas",
                    "frame_obligations",
                    "heap",
                    "heap_theory",
                    "interface",
                    "metadata",
                    "observations",
                    "ownership_transfers",
                    "root_formula_id",
                    "schema_version",
                    "sources",
                    "spans",
                }
            ),
            "separation document",
        )
        if value.get("interface", SEPARATION_LOGIC_IR_INTERFACE) not in {
            SEPARATION_LOGIC_IR_INTERFACE,
            "",
        }:
            raise SeparationValidationError("unsupported separation-logic interface")
        return cls(
            sources=tuple(value.get("sources", ())),
            spans=tuple(value.get("spans", ())),
            heap=HeapModel.from_dict(_mapping(value.get("heap", {}), "heap")),
            formulas=tuple(value.get("formulas", ())),
            root_formula_id=value.get("root_formula_id", ""),
            frame_obligations=tuple(value.get("frame_obligations", ())),
            ownership_transfers=tuple(value.get("ownership_transfers", ())),
            heap_theory=value.get("heap_theory", HeapTheory.CLASSICAL_SL.value),
            metadata=_frozen(
                _mapping(value.get("metadata", {}), "metadata"), "metadata"
            ),
            observations=_frozen(
                _mapping(value.get("observations", {}), "observations"),
                "observations",
            ),
            document_id=value.get("document_id", ""),
            schema_version=value.get(
                "schema_version", SEPARATION_LOGIC_IR_SCHEMA_VERSION
            ),
        )

    @classmethod
    def from_json(cls, value: str | bytes | bytearray) -> SeparationLogicIR:
        try:
            decoded = json.loads(value)
        except (TypeError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise SeparationValidationError(
                "separation-logic JSON is malformed"
            ) from error
        if not isinstance(decoded, Mapping):
            raise SeparationValidationError(
                "separation-logic JSON must contain an object"
            )
        return cls.from_dict(decoded)


# Convenience constructors used by tests and frontends.


def emp_formula(
    formula_id: str,
    *,
    source_ref_ids: Sequence[str] = (),
    span_ids: Sequence[str] = (),
) -> SeparationFormula:
    return SeparationFormula(
        formula_id,
        FormulaKind.EMP,
        source_ref_ids=tuple(source_ref_ids),
        span_ids=tuple(span_ids),
    )


def points_to_formula(
    formula_id: str,
    location_id: str,
    value_id: str,
    *,
    permission: Permission | None = None,
    source_ref_ids: Sequence[str] = (),
    span_ids: Sequence[str] = (),
) -> SeparationFormula:
    return SeparationFormula(
        formula_id,
        FormulaKind.POINTS_TO,
        location_id=location_id,
        value_id=value_id,
        permission=permission if permission is not None else Permission.full(),
        source_ref_ids=tuple(source_ref_ids),
        span_ids=tuple(span_ids),
    )


def sep_conj(
    formula_id: str,
    *operand_ids: str,
    source_ref_ids: Sequence[str] = (),
    span_ids: Sequence[str] = (),
) -> SeparationFormula:
    return SeparationFormula(
        formula_id,
        FormulaKind.SEP_CONJ,
        operand_ids=operand_ids,
        source_ref_ids=tuple(source_ref_ids),
        span_ids=tuple(span_ids),
    )


def ordinary_and(
    formula_id: str,
    *operand_ids: str,
    source_ref_ids: Sequence[str] = (),
    span_ids: Sequence[str] = (),
) -> SeparationFormula:
    return SeparationFormula(
        formula_id,
        FormulaKind.AND,
        operand_ids=operand_ids,
        source_ref_ids=tuple(source_ref_ids),
        span_ids=tuple(span_ids),
    )


def pure_formula(
    formula_id: str,
    expression: str,
    *,
    expression_id: str = "",
    source_ref_ids: Sequence[str] = (),
    span_ids: Sequence[str] = (),
) -> SeparationFormula:
    return SeparationFormula(
        formula_id,
        FormulaKind.PURE,
        pure_expression=expression,
        pure_expression_id=expression_id,
        source_ref_ids=tuple(source_ref_ids),
        span_ids=tuple(span_ids),
    )


__all__ = [
    "SEPARATION_LOGIC_IR_IDENTITY_DOMAIN",
    "SEPARATION_LOGIC_IR_INTERFACE",
    "SEPARATION_LOGIC_IR_SCHEMA_VERSION",
    "FormulaKind",
    "FrameObligation",
    "FrameObligationKind",
    "HeapTheory",
    "OwnershipTransfer",
    "OwnershipTransferKind",
    "SeparationFormula",
    "SeparationLogicIR",
    "SeparationLoweringError",
    "SeparationValidationError",
    "emp_formula",
    "infer_frame_obligation",
    "ordinary_and",
    "points_to_formula",
    "pure_formula",
    "sep_conj",
    # Re-exports used by tests for a single import surface.
    "AliasClass",
    "HeapLocation",
    "HeapModel",
    "HeapValidationError",
    "HeapValue",
    "OwnershipRecord",
    "Permission",
    "PointsToCell",
    "ResourceAlgebra",
    "ResourceUnit",
    "HEAP_MODEL_SCHEMA_VERSION",
]
