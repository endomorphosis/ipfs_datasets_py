"""Language-neutral program and control-flow semantics.

The records in this module describe source programs; they do not execute a
program and they do not encode a particular solver language.  ``ProgramIR``
performs closed-world validation of symbols, expression dependencies, command
evaluation order, function scopes, and control-flow graphs.  Consequently a
frontend cannot silently leave a name unresolved or construct a partial CFG.
"""

from __future__ import annotations

import re
from collections import defaultdict, deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Final

from ipfs_datasets_py.logic.ir_core.canonical import canonical_json_bytes
from ipfs_datasets_py.logic.ir_core.claims import FrozenMap
from ipfs_datasets_py.logic.ir_core.identity import CanonicalIdentity, canonical_identity
from ipfs_datasets_py.logic.ir_core.provenance import SourceRef, SourceSpan

PROGRAM_IR_SCHEMA_VERSION: Final = "program-ir/v1"
PROGRAM_IR_IDENTITY_DOMAIN: Final = "logic.software-verification.program"

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")


class ProgramValidationError(ValueError):
    """Raised when program semantics are incomplete or inconsistent."""


class SymbolKind(str, Enum):
    GLOBAL = "global"
    PARAMETER = "parameter"
    LOCAL = "local"
    RESULT = "result"
    EXCEPTION = "exception"
    FUNCTION = "function"


class ExpressionKind(str, Enum):
    LITERAL = "literal"
    SYMBOL = "symbol"
    UNARY = "unary"
    BINARY = "binary"
    CONDITIONAL = "conditional"
    CALL = "call"
    FIELD = "field"
    INDEX = "index"
    QUANTIFIED = "quantified"
    OLD = "old"
    RESULT = "result"
    UNDEFINED = "undefined"


class CommandKind(str, Enum):
    SKIP = "skip"
    ASSIGN = "assign"
    ASSUME = "assume"
    ASSERT = "assert"
    CALL = "call"
    RETURN = "return"
    THROW = "throw"
    HAVOC = "havoc"
    ALLOCATE = "allocate"
    DEALLOCATE = "deallocate"
    ATOMIC = "atomic"
    UNDEFINED = "undefined"


class EdgeKind(str, Enum):
    NORMAL = "normal"
    TRUE = "true"
    FALSE = "false"
    EXCEPTION = "exception"
    RETURN = "return"
    BREAK = "break"
    CONTINUE = "continue"


class Purity(str, Enum):
    """Explicit source-level purity classification.

    ``UNKNOWN`` is intentionally distinct from ``IMPURE``.  Downstream tools
    must not promote an unknown declaration to a pure one.
    """

    PURE = "pure"
    READ_ONLY = "read_only"
    IMPURE = "impure"
    UNKNOWN = "unknown"


class UndefinedBehaviorConsequence(str, Enum):
    TRAP = "trap"
    NONDETERMINISTIC = "nondeterministic"
    UNCONSTRAINED = "unconstrained"
    LANGUAGE_DEFINED = "language_defined"


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise ProgramValidationError(
            f"{label} must be a non-empty string without surrounding whitespace"
        )
    if "\x00" in value:
        raise ProgramValidationError(f"{label} must not contain NUL bytes")
    return value


def _optional_text(value: object, label: str) -> str:
    if value == "":
        return ""
    return _text(value, label)


def _identifier(value: object, label: str) -> str:
    result = _text(value, label)
    if not _ID_RE.fullmatch(result):
        raise ProgramValidationError(f"{label} must be a stable identifier")
    return result


def _ids(
    values: Sequence[str],
    label: str,
    *,
    preserve_order: bool = False,
) -> tuple[str, ...]:
    if isinstance(values, (str, bytes, bytearray)) or not isinstance(values, Sequence):
        raise ProgramValidationError(f"{label} must be a sequence of identifiers")
    result = tuple(_identifier(item, f"{label} item") for item in values)
    if len(result) != len(set(result)):
        raise ProgramValidationError(f"{label} must not contain duplicates")
    return result if preserve_order else tuple(sorted(result))


def _source_map(
    source_ref_ids: Sequence[str],
    span_ids: Sequence[str],
    owner: str,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    sources = _ids(source_ref_ids, f"{owner}.source_ref_ids")
    spans = _ids(span_ids, f"{owner}.span_ids")
    if not sources and not spans:
        raise ProgramValidationError(
            f"{owner} must be source mapped with source_ref_ids or span_ids"
        )
    return sources, spans


def _enum(value: object, enum_type: type[Enum], label: str) -> Any:
    try:
        return value if isinstance(value, enum_type) else enum_type(value)
    except (TypeError, ValueError) as error:
        choices = ", ".join(item.value for item in enum_type)
        raise ProgramValidationError(f"{label} must be one of {choices}") from error


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ProgramValidationError(f"{label} must be a mapping")
    return value


def _frozen(value: Mapping[str, Any] | FrozenMap, label: str) -> FrozenMap:
    try:
        return value if isinstance(value, FrozenMap) else FrozenMap(value)
    except (TypeError, ValueError) as error:
        raise ProgramValidationError(
            f"{label} must contain JSON-compatible data: {error}"
        ) from error


def _known(values: Sequence[str], known: set[str], label: str) -> None:
    missing = sorted(set(values) - known)
    if missing:
        raise ProgramValidationError(f"{label} references unknown ids {missing}")


@dataclass(frozen=True, slots=True)
class ProgramSymbol:
    symbol_id: str
    name: str
    type_ref: str
    kind: SymbolKind | str
    source_ref_ids: tuple[str, ...] = ()
    span_ids: tuple[str, ...] = ()
    attributes: FrozenMap = field(default_factory=FrozenMap)

    def __post_init__(self) -> None:
        sources, spans = _source_map(self.source_ref_ids, self.span_ids, "ProgramSymbol")
        object.__setattr__(self, "symbol_id", _identifier(self.symbol_id, "symbol_id"))
        object.__setattr__(self, "name", _text(self.name, "name"))
        object.__setattr__(self, "type_ref", _text(self.type_ref, "type_ref"))
        object.__setattr__(self, "kind", _enum(self.kind, SymbolKind, "kind"))
        object.__setattr__(self, "source_ref_ids", sources)
        object.__setattr__(self, "span_ids", spans)
        object.__setattr__(self, "attributes", _frozen(self.attributes, "attributes"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": self.attributes.to_dict(),
            "kind": self.kind.value,
            "name": self.name,
            "source_ref_ids": list(self.source_ref_ids),
            "span_ids": list(self.span_ids),
            "symbol_id": self.symbol_id,
            "type_ref": self.type_ref,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ProgramSymbol":
        return cls(
            symbol_id=value.get("symbol_id", ""),
            name=value.get("name", ""),
            type_ref=value.get("type_ref", ""),
            kind=value.get("kind", ""),
            source_ref_ids=tuple(value.get("source_ref_ids", ())),
            span_ids=tuple(value.get("span_ids", ())),
            attributes=_frozen(_mapping(value.get("attributes", {}), "attributes"), "attributes"),
        )


@dataclass(frozen=True, slots=True)
class ProgramExpression:
    """One typed expression with explicit operand evaluation order."""

    expression_id: str
    kind: ExpressionKind | str
    type_ref: str
    operand_ids: tuple[str, ...] = ()
    evaluation_order: tuple[str, ...] = ()
    symbol_ids: tuple[str, ...] = ()
    operator: str = ""
    attributes: FrozenMap = field(default_factory=FrozenMap)
    source_ref_ids: tuple[str, ...] = ()
    span_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        sources, spans = _source_map(self.source_ref_ids, self.span_ids, "ProgramExpression")
        operands = _ids(self.operand_ids, "operand_ids", preserve_order=True)
        order = _ids(
            self.evaluation_order or operands,
            "evaluation_order",
            preserve_order=True,
        )
        if len(order) != len(operands) or set(order) != set(operands):
            raise ProgramValidationError(
                "evaluation_order must contain every operand_id exactly once"
            )
        kind = _enum(self.kind, ExpressionKind, "kind")
        symbols = _ids(self.symbol_ids, "symbol_ids")
        if kind in {ExpressionKind.SYMBOL, ExpressionKind.RESULT} and len(symbols) != 1:
            raise ProgramValidationError(
                f"{kind.value} expressions must reference exactly one symbol"
            )
        if kind is ExpressionKind.LITERAL and (operands or symbols):
            raise ProgramValidationError("literal expressions cannot reference operands or symbols")
        if (
            kind
            in {
                ExpressionKind.UNARY,
                ExpressionKind.FIELD,
                ExpressionKind.OLD,
            }
            and len(operands) != 1
        ):
            raise ProgramValidationError(f"{kind.value} expressions require exactly one operand")
        if kind is ExpressionKind.BINARY and len(operands) != 2:
            raise ProgramValidationError("binary expressions require exactly two operands")
        if kind is ExpressionKind.CONDITIONAL and len(operands) != 3:
            raise ProgramValidationError(
                "conditional expressions require condition, then, and else operands"
            )
        if (
            kind
            in {
                ExpressionKind.UNARY,
                ExpressionKind.BINARY,
                ExpressionKind.FIELD,
                ExpressionKind.INDEX,
                ExpressionKind.QUANTIFIED,
            }
            and not self.operator
        ):
            raise ProgramValidationError(f"{kind.value} expressions require operator")
        object.__setattr__(self, "expression_id", _identifier(self.expression_id, "expression_id"))
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "type_ref", _text(self.type_ref, "type_ref"))
        object.__setattr__(self, "operand_ids", operands)
        object.__setattr__(self, "evaluation_order", order)
        object.__setattr__(self, "symbol_ids", symbols)
        object.__setattr__(self, "operator", _optional_text(self.operator, "operator"))
        object.__setattr__(self, "attributes", _frozen(self.attributes, "attributes"))
        object.__setattr__(self, "source_ref_ids", sources)
        object.__setattr__(self, "span_ids", spans)

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": self.attributes.to_dict(),
            "evaluation_order": list(self.evaluation_order),
            "expression_id": self.expression_id,
            "kind": self.kind.value,
            "operand_ids": list(self.operand_ids),
            "operator": self.operator,
            "source_ref_ids": list(self.source_ref_ids),
            "span_ids": list(self.span_ids),
            "symbol_ids": list(self.symbol_ids),
            "type_ref": self.type_ref,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ProgramExpression":
        return cls(
            expression_id=value.get("expression_id", ""),
            kind=value.get("kind", ""),
            type_ref=value.get("type_ref", ""),
            operand_ids=tuple(value.get("operand_ids", ())),
            evaluation_order=tuple(value.get("evaluation_order", ())),
            symbol_ids=tuple(value.get("symbol_ids", ())),
            operator=value.get("operator", ""),
            attributes=_frozen(_mapping(value.get("attributes", {}), "attributes"), "attributes"),
            source_ref_ids=tuple(value.get("source_ref_ids", ())),
            span_ids=tuple(value.get("span_ids", ())),
        )


@dataclass(frozen=True, slots=True)
class EffectSummary:
    """Explicit read/write/resource and observable effects."""

    reads: tuple[str, ...] = ()
    writes: tuple[str, ...] = ()
    allocates: tuple[str, ...] = ()
    deallocates: tuple[str, ...] = ()
    raises: tuple[str, ...] = ()
    performs_io: bool = False
    nondeterministic: bool = False
    synchronizes: bool = False

    def __post_init__(self) -> None:
        for name in ("reads", "writes", "allocates", "deallocates"):
            object.__setattr__(self, name, _ids(getattr(self, name), name))
        object.__setattr__(
            self,
            "raises",
            tuple(sorted(_text(item, "raises item") for item in self.raises)),
        )
        if len(self.raises) != len(set(self.raises)):
            raise ProgramValidationError("raises must not contain duplicates")
        for name in ("performs_io", "nondeterministic", "synchronizes"):
            if not isinstance(getattr(self, name), bool):
                raise ProgramValidationError(f"{name} must be boolean")

    @property
    def is_pure(self) -> bool:
        return not (
            self.writes
            or self.allocates
            or self.deallocates
            or self.raises
            or self.performs_io
            or self.nondeterministic
            or self.synchronizes
        )

    @property
    def is_read_only(self) -> bool:
        return not (
            self.writes
            or self.allocates
            or self.deallocates
            or self.performs_io
            or self.synchronizes
        )

    def symbol_ids(self) -> tuple[str, ...]:
        return tuple(sorted(set(self.reads + self.writes + self.allocates + self.deallocates)))

    def is_subset_of(self, other: "EffectSummary") -> bool:
        return (
            set(self.reads) <= set(other.reads)
            and set(self.writes) <= set(other.writes)
            and set(self.allocates) <= set(other.allocates)
            and set(self.deallocates) <= set(other.deallocates)
            and set(self.raises) <= set(other.raises)
            and (not self.performs_io or other.performs_io)
            and (not self.nondeterministic or other.nondeterministic)
            and (not self.synchronizes or other.synchronizes)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "allocates": list(self.allocates),
            "deallocates": list(self.deallocates),
            "nondeterministic": self.nondeterministic,
            "performs_io": self.performs_io,
            "raises": list(self.raises),
            "reads": list(self.reads),
            "synchronizes": self.synchronizes,
            "writes": list(self.writes),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "EffectSummary":
        return cls(
            reads=tuple(value.get("reads", ())),
            writes=tuple(value.get("writes", ())),
            allocates=tuple(value.get("allocates", ())),
            deallocates=tuple(value.get("deallocates", ())),
            raises=tuple(value.get("raises", ())),
            performs_io=value.get("performs_io", False),
            nondeterministic=value.get("nondeterministic", False),
            synchronizes=value.get("synchronizes", False),
        )


@dataclass(frozen=True, slots=True)
class UndefinedBehaviorCondition:
    condition_id: str
    expression_id: str
    description: str
    consequence: UndefinedBehaviorConsequence | str
    source_ref_ids: tuple[str, ...] = ()
    span_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        sources, spans = _source_map(
            self.source_ref_ids, self.span_ids, "UndefinedBehaviorCondition"
        )
        object.__setattr__(self, "condition_id", _identifier(self.condition_id, "condition_id"))
        object.__setattr__(self, "expression_id", _identifier(self.expression_id, "expression_id"))
        object.__setattr__(self, "description", _text(self.description, "description"))
        object.__setattr__(
            self,
            "consequence",
            _enum(self.consequence, UndefinedBehaviorConsequence, "consequence"),
        )
        object.__setattr__(self, "source_ref_ids", sources)
        object.__setattr__(self, "span_ids", spans)

    def to_dict(self) -> dict[str, Any]:
        return {
            "condition_id": self.condition_id,
            "consequence": self.consequence.value,
            "description": self.description,
            "expression_id": self.expression_id,
            "source_ref_ids": list(self.source_ref_ids),
            "span_ids": list(self.span_ids),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "UndefinedBehaviorCondition":
        return cls(
            condition_id=value.get("condition_id", ""),
            expression_id=value.get("expression_id", ""),
            description=value.get("description", ""),
            consequence=value.get("consequence", ""),
            source_ref_ids=tuple(value.get("source_ref_ids", ())),
            span_ids=tuple(value.get("span_ids", ())),
        )


@dataclass(frozen=True, slots=True)
class ProgramCommand:
    """One atomic command; block order supplies sequential composition."""

    command_id: str
    kind: CommandKind | str
    expression_ids: tuple[str, ...] = ()
    evaluation_order: tuple[str, ...] = ()
    target_symbol_ids: tuple[str, ...] = ()
    effects: EffectSummary = field(default_factory=EffectSummary)
    undefined_behavior: tuple[UndefinedBehaviorCondition, ...] = ()
    source_ref_ids: tuple[str, ...] = ()
    span_ids: tuple[str, ...] = ()
    attributes: FrozenMap = field(default_factory=FrozenMap)

    def __post_init__(self) -> None:
        sources, spans = _source_map(self.source_ref_ids, self.span_ids, "ProgramCommand")
        expressions = _ids(self.expression_ids, "expression_ids", preserve_order=True)
        order = _ids(
            self.evaluation_order or expressions,
            "evaluation_order",
            preserve_order=True,
        )
        if len(order) != len(expressions) or set(order) != set(expressions):
            raise ProgramValidationError(
                "command evaluation_order must contain every expression_id exactly once"
            )
        kind = _enum(self.kind, CommandKind, "kind")
        targets = _ids(self.target_symbol_ids, "target_symbol_ids")
        effects = (
            self.effects
            if isinstance(self.effects, EffectSummary)
            else EffectSummary.from_dict(_mapping(self.effects, "effects"))
        )
        undefined = tuple(
            item
            if isinstance(item, UndefinedBehaviorCondition)
            else UndefinedBehaviorCondition.from_dict(_mapping(item, "undefined_behavior item"))
            for item in self.undefined_behavior
        )
        if kind is CommandKind.ASSIGN and not targets:
            raise ProgramValidationError("assign commands require target_symbol_ids")
        if kind in {CommandKind.ASSUME, CommandKind.ASSERT} and len(expressions) != 1:
            raise ProgramValidationError(f"{kind.value} commands require exactly one expression")
        if kind is CommandKind.THROW and not effects.raises:
            raise ProgramValidationError("throw commands require an explicit raised type")
        if kind is CommandKind.UNDEFINED and not undefined:
            raise ProgramValidationError(
                "undefined commands require an explicit undefined_behavior condition"
            )
        ids = [item.condition_id for item in undefined]
        if len(ids) != len(set(ids)):
            raise ProgramValidationError("duplicate undefined behavior condition ids")
        object.__setattr__(self, "command_id", _identifier(self.command_id, "command_id"))
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "expression_ids", expressions)
        object.__setattr__(self, "evaluation_order", order)
        object.__setattr__(self, "target_symbol_ids", targets)
        object.__setattr__(self, "effects", effects)
        object.__setattr__(self, "undefined_behavior", undefined)
        object.__setattr__(self, "source_ref_ids", sources)
        object.__setattr__(self, "span_ids", spans)
        object.__setattr__(self, "attributes", _frozen(self.attributes, "attributes"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": self.attributes.to_dict(),
            "command_id": self.command_id,
            "effects": self.effects.to_dict(),
            "evaluation_order": list(self.evaluation_order),
            "expression_ids": list(self.expression_ids),
            "kind": self.kind.value,
            "source_ref_ids": list(self.source_ref_ids),
            "span_ids": list(self.span_ids),
            "target_symbol_ids": list(self.target_symbol_ids),
            "undefined_behavior": [item.to_dict() for item in self.undefined_behavior],
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ProgramCommand":
        return cls(
            command_id=value.get("command_id", ""),
            kind=value.get("kind", ""),
            expression_ids=tuple(value.get("expression_ids", ())),
            evaluation_order=tuple(value.get("evaluation_order", ())),
            target_symbol_ids=tuple(value.get("target_symbol_ids", ())),
            effects=EffectSummary.from_dict(_mapping(value.get("effects", {}), "effects")),
            undefined_behavior=tuple(
                UndefinedBehaviorCondition.from_dict(_mapping(item, "undefined_behavior item"))
                for item in value.get("undefined_behavior", ())
            ),
            source_ref_ids=tuple(value.get("source_ref_ids", ())),
            span_ids=tuple(value.get("span_ids", ())),
            attributes=_frozen(_mapping(value.get("attributes", {}), "attributes"), "attributes"),
        )


@dataclass(frozen=True, slots=True)
class BasicBlock:
    block_id: str
    command_ids: tuple[str, ...] = ()
    source_ref_ids: tuple[str, ...] = ()
    span_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        sources, spans = _source_map(self.source_ref_ids, self.span_ids, "BasicBlock")
        object.__setattr__(self, "block_id", _identifier(self.block_id, "block_id"))
        object.__setattr__(
            self,
            "command_ids",
            _ids(self.command_ids, "command_ids", preserve_order=True),
        )
        object.__setattr__(self, "source_ref_ids", sources)
        object.__setattr__(self, "span_ids", spans)

    def to_dict(self) -> dict[str, Any]:
        return {
            "block_id": self.block_id,
            "command_ids": list(self.command_ids),
            "source_ref_ids": list(self.source_ref_ids),
            "span_ids": list(self.span_ids),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "BasicBlock":
        return cls(
            block_id=value.get("block_id", ""),
            command_ids=tuple(value.get("command_ids", ())),
            source_ref_ids=tuple(value.get("source_ref_ids", ())),
            span_ids=tuple(value.get("span_ids", ())),
        )


@dataclass(frozen=True, slots=True)
class ControlFlowEdge:
    edge_id: str
    source_block_id: str
    target_block_id: str
    kind: EdgeKind | str = EdgeKind.NORMAL
    order: int = 0
    condition_expression_id: str = ""
    exception_type: str = ""

    def __post_init__(self) -> None:
        kind = _enum(self.kind, EdgeKind, "kind")
        if isinstance(self.order, bool) or not isinstance(self.order, int) or self.order < 0:
            raise ProgramValidationError("edge order must be a non-negative integer")
        condition = _optional_text(self.condition_expression_id, "condition_expression_id")
        if condition:
            condition = _identifier(condition, "condition_expression_id")
        exception = _optional_text(self.exception_type, "exception_type")
        if kind in {EdgeKind.TRUE, EdgeKind.FALSE} and not condition:
            raise ProgramValidationError(f"{kind.value} edges require condition_expression_id")
        if kind is EdgeKind.EXCEPTION and not exception:
            raise ProgramValidationError("exception edges require exception_type")
        if kind is not EdgeKind.EXCEPTION and exception:
            raise ProgramValidationError("exception_type is only valid for exception edges")
        object.__setattr__(self, "edge_id", _identifier(self.edge_id, "edge_id"))
        object.__setattr__(
            self,
            "source_block_id",
            _identifier(self.source_block_id, "source_block_id"),
        )
        object.__setattr__(
            self,
            "target_block_id",
            _identifier(self.target_block_id, "target_block_id"),
        )
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "condition_expression_id", condition)
        object.__setattr__(self, "exception_type", exception)

    def to_dict(self) -> dict[str, Any]:
        return {
            "condition_expression_id": self.condition_expression_id,
            "edge_id": self.edge_id,
            "exception_type": self.exception_type,
            "kind": self.kind.value,
            "order": self.order,
            "source_block_id": self.source_block_id,
            "target_block_id": self.target_block_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ControlFlowEdge":
        return cls(
            edge_id=value.get("edge_id", ""),
            source_block_id=value.get("source_block_id", ""),
            target_block_id=value.get("target_block_id", ""),
            kind=value.get("kind", EdgeKind.NORMAL.value),
            order=value.get("order", 0),
            condition_expression_id=value.get("condition_expression_id", ""),
            exception_type=value.get("exception_type", ""),
        )


@dataclass(frozen=True, slots=True)
class ControlFlowGraph:
    """A closed CFG with distinct normal and exceptional exits."""

    graph_id: str
    entry_block_id: str
    blocks: tuple[BasicBlock, ...]
    edges: tuple[ControlFlowEdge, ...]
    normal_exit_block_ids: tuple[str, ...]
    exceptional_exit_block_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        blocks = tuple(
            item if isinstance(item, BasicBlock) else BasicBlock.from_dict(_mapping(item, "block"))
            for item in self.blocks
        )
        edges = tuple(
            item
            if isinstance(item, ControlFlowEdge)
            else ControlFlowEdge.from_dict(_mapping(item, "edge"))
            for item in self.edges
        )
        object.__setattr__(self, "graph_id", _identifier(self.graph_id, "graph_id"))
        object.__setattr__(
            self, "entry_block_id", _identifier(self.entry_block_id, "entry_block_id")
        )
        object.__setattr__(self, "blocks", tuple(sorted(blocks, key=lambda item: item.block_id)))
        object.__setattr__(self, "edges", tuple(sorted(edges, key=lambda item: item.edge_id)))
        object.__setattr__(
            self,
            "normal_exit_block_ids",
            _ids(self.normal_exit_block_ids, "normal_exit_block_ids"),
        )
        object.__setattr__(
            self,
            "exceptional_exit_block_ids",
            _ids(self.exceptional_exit_block_ids, "exceptional_exit_block_ids"),
        )
        self.validate()

    @property
    def command_ids(self) -> tuple[str, ...]:
        return tuple(command for block in self.blocks for command in block.command_ids)

    def validate(
        self,
        *,
        known_command_ids: set[str] | None = None,
        known_expression_ids: set[str] | None = None,
    ) -> None:
        block_ids = [item.block_id for item in self.blocks]
        edge_ids = [item.edge_id for item in self.edges]
        if not block_ids:
            raise ProgramValidationError("a CFG requires at least one block")
        if len(block_ids) != len(set(block_ids)):
            raise ProgramValidationError("duplicate CFG block identifiers")
        if len(edge_ids) != len(set(edge_ids)):
            raise ProgramValidationError("duplicate CFG edge identifiers")
        known_blocks = set(block_ids)
        _known((self.entry_block_id,), known_blocks, f"CFG {self.graph_id}.entry")
        if not self.normal_exit_block_ids:
            raise ProgramValidationError("a CFG requires at least one normal exit")
        _known(
            self.normal_exit_block_ids,
            known_blocks,
            f"CFG {self.graph_id}.normal exits",
        )
        _known(
            self.exceptional_exit_block_ids,
            known_blocks,
            f"CFG {self.graph_id}.exceptional exits",
        )
        overlap = set(self.normal_exit_block_ids) & set(self.exceptional_exit_block_ids)
        if overlap:
            raise ProgramValidationError(
                f"normal and exceptional CFG exits must be separate: {sorted(overlap)}"
            )
        all_commands = list(self.command_ids)
        if len(all_commands) != len(set(all_commands)):
            raise ProgramValidationError("a command may occur in only one CFG block")
        if known_command_ids is not None:
            _known(all_commands, known_command_ids, f"CFG {self.graph_id}.commands")

        outgoing: dict[str, list[ControlFlowEdge]] = defaultdict(list)
        adjacency: dict[str, set[str]] = defaultdict(set)
        for edge in self.edges:
            _known(
                (edge.source_block_id, edge.target_block_id),
                known_blocks,
                f"edge {edge.edge_id}",
            )
            if known_expression_ids is not None and edge.condition_expression_id:
                _known(
                    (edge.condition_expression_id,),
                    known_expression_ids,
                    f"edge {edge.edge_id}.condition",
                )
            outgoing[edge.source_block_id].append(edge)
            adjacency[edge.source_block_id].add(edge.target_block_id)
        for block_id, block_edges in outgoing.items():
            orders = [edge.order for edge in block_edges]
            if len(orders) != len(set(orders)):
                raise ProgramValidationError(
                    f"outgoing edge order is ambiguous at block {block_id}"
                )
            if sorted(orders) != list(range(len(orders))):
                raise ProgramValidationError(
                    f"outgoing edge order at block {block_id} must be contiguous from zero"
                )
            kinds = {edge.kind for edge in block_edges}
            if (EdgeKind.TRUE in kinds) != (EdgeKind.FALSE in kinds):
                raise ProgramValidationError(
                    f"block {block_id} must have both true and false edges"
                )
            if EdgeKind.TRUE in kinds:
                true_edges = [edge for edge in block_edges if edge.kind is EdgeKind.TRUE]
                false_edges = [edge for edge in block_edges if edge.kind is EdgeKind.FALSE]
                if len(true_edges) != 1 or len(false_edges) != 1:
                    raise ProgramValidationError(
                        f"block {block_id} must have exactly one true and one false edge"
                    )
                if true_edges[0].condition_expression_id != false_edges[0].condition_expression_id:
                    raise ProgramValidationError(
                        f"true and false edges at block {block_id} must share one condition"
                    )

        exits = set(self.normal_exit_block_ids) | set(self.exceptional_exit_block_ids)
        terminal_with_edges = sorted(exits & set(outgoing))
        if terminal_with_edges:
            raise ProgramValidationError(f"CFG exit blocks must be terminal: {terminal_with_edges}")
        dead_ends = sorted(known_blocks - exits - set(outgoing))
        if dead_ends:
            raise ProgramValidationError(f"non-exit CFG blocks have no outgoing edge: {dead_ends}")
        reachable = {self.entry_block_id}
        queue = deque((self.entry_block_id,))
        while queue:
            current = queue.popleft()
            for target in adjacency[current]:
                if target not in reachable:
                    reachable.add(target)
                    queue.append(target)
        unreachable = sorted(known_blocks - reachable)
        if unreachable:
            raise ProgramValidationError(f"unreachable CFG blocks: {unreachable}")
        if not (reachable & set(self.normal_exit_block_ids)):
            raise ProgramValidationError("no normal exit is reachable from CFG entry")

    def to_dict(self) -> dict[str, Any]:
        return {
            "blocks": [
                item.to_dict() for item in sorted(self.blocks, key=lambda item: item.block_id)
            ],
            "edges": [item.to_dict() for item in sorted(self.edges, key=lambda item: item.edge_id)],
            "entry_block_id": self.entry_block_id,
            "exceptional_exit_block_ids": list(self.exceptional_exit_block_ids),
            "graph_id": self.graph_id,
            "normal_exit_block_ids": list(self.normal_exit_block_ids),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ControlFlowGraph":
        return cls(
            graph_id=value.get("graph_id", ""),
            entry_block_id=value.get("entry_block_id", ""),
            blocks=tuple(
                BasicBlock.from_dict(_mapping(item, "block")) for item in value.get("blocks", ())
            ),
            edges=tuple(
                ControlFlowEdge.from_dict(_mapping(item, "edge")) for item in value.get("edges", ())
            ),
            normal_exit_block_ids=tuple(value.get("normal_exit_block_ids", ())),
            exceptional_exit_block_ids=tuple(value.get("exceptional_exit_block_ids", ())),
        )


@dataclass(frozen=True, slots=True)
class ProgramFunction:
    function_id: str
    name: str
    cfg: ControlFlowGraph
    parameter_symbol_ids: tuple[str, ...] = ()
    local_symbol_ids: tuple[str, ...] = ()
    exception_symbol_ids: tuple[str, ...] = ()
    result_symbol_id: str = ""
    return_type: str = "void"
    purity: Purity | str = Purity.UNKNOWN
    effects: EffectSummary = field(default_factory=EffectSummary)
    declared_exceptions: tuple[str, ...] = ()
    source_ref_ids: tuple[str, ...] = ()
    span_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        sources, spans = _source_map(self.source_ref_ids, self.span_ids, "ProgramFunction")
        cfg = (
            self.cfg
            if isinstance(self.cfg, ControlFlowGraph)
            else ControlFlowGraph.from_dict(_mapping(self.cfg, "cfg"))
        )
        result = _optional_text(self.result_symbol_id, "result_symbol_id")
        if result:
            result = _identifier(result, "result_symbol_id")
        effects = (
            self.effects
            if isinstance(self.effects, EffectSummary)
            else EffectSummary.from_dict(_mapping(self.effects, "effects"))
        )
        exceptions = tuple(
            sorted(_text(item, "declared_exceptions item") for item in self.declared_exceptions)
        )
        if len(exceptions) != len(set(exceptions)):
            raise ProgramValidationError("declared_exceptions must not contain duplicates")
        purity = _enum(self.purity, Purity, "purity")
        if purity is Purity.PURE and not effects.is_pure:
            raise ProgramValidationError("pure functions cannot declare impure effects")
        if purity is Purity.READ_ONLY and not effects.is_read_only:
            raise ProgramValidationError("read-only functions cannot declare write effects")
        if set(effects.raises) - set(exceptions):
            raise ProgramValidationError("function effects raise undeclared exception types")
        object.__setattr__(self, "function_id", _identifier(self.function_id, "function_id"))
        object.__setattr__(self, "name", _text(self.name, "name"))
        object.__setattr__(self, "cfg", cfg)
        object.__setattr__(
            self,
            "parameter_symbol_ids",
            _ids(
                self.parameter_symbol_ids,
                "parameter_symbol_ids",
                preserve_order=True,
            ),
        )
        object.__setattr__(
            self, "local_symbol_ids", _ids(self.local_symbol_ids, "local_symbol_ids")
        )
        object.__setattr__(
            self,
            "exception_symbol_ids",
            _ids(self.exception_symbol_ids, "exception_symbol_ids"),
        )
        scoped_groups = (
            set(self.parameter_symbol_ids),
            set(self.local_symbol_ids),
            set(self.exception_symbol_ids),
            {result} if result else set(),
        )
        seen: set[str] = set()
        for group in scoped_groups:
            if seen & group:
                raise ProgramValidationError("function symbol scopes overlap")
            seen.update(group)
        object.__setattr__(self, "result_symbol_id", result)
        object.__setattr__(self, "return_type", _text(self.return_type, "return_type"))
        object.__setattr__(self, "purity", purity)
        object.__setattr__(self, "effects", effects)
        object.__setattr__(self, "declared_exceptions", exceptions)
        object.__setattr__(self, "source_ref_ids", sources)
        object.__setattr__(self, "span_ids", spans)

    @property
    def scoped_symbol_ids(self) -> tuple[str, ...]:
        values = self.parameter_symbol_ids + self.local_symbol_ids + self.exception_symbol_ids
        if self.result_symbol_id:
            values += (self.result_symbol_id,)
        return values

    def to_dict(self) -> dict[str, Any]:
        return {
            "cfg": self.cfg.to_dict(),
            "declared_exceptions": list(self.declared_exceptions),
            "effects": self.effects.to_dict(),
            "exception_symbol_ids": list(self.exception_symbol_ids),
            "function_id": self.function_id,
            "local_symbol_ids": list(self.local_symbol_ids),
            "name": self.name,
            "parameter_symbol_ids": list(self.parameter_symbol_ids),
            "purity": self.purity.value,
            "result_symbol_id": self.result_symbol_id,
            "return_type": self.return_type,
            "source_ref_ids": list(self.source_ref_ids),
            "span_ids": list(self.span_ids),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ProgramFunction":
        return cls(
            function_id=value.get("function_id", ""),
            name=value.get("name", ""),
            cfg=ControlFlowGraph.from_dict(_mapping(value.get("cfg", {}), "cfg")),
            parameter_symbol_ids=tuple(value.get("parameter_symbol_ids", ())),
            local_symbol_ids=tuple(value.get("local_symbol_ids", ())),
            result_symbol_id=value.get("result_symbol_id", ""),
            return_type=value.get("return_type", "void"),
            purity=value.get("purity", Purity.UNKNOWN.value),
            effects=EffectSummary.from_dict(_mapping(value.get("effects", {}), "effects")),
            exception_symbol_ids=tuple(value.get("exception_symbol_ids", ())),
            declared_exceptions=tuple(value.get("declared_exceptions", ())),
            source_ref_ids=tuple(value.get("source_ref_ids", ())),
            span_ids=tuple(value.get("span_ids", ())),
        )


@dataclass(frozen=True, slots=True)
class ProgramIR:
    """Canonical closed-world program document (``ProgramIR@1``)."""

    sources: tuple[SourceRef, ...]
    spans: tuple[SourceSpan, ...]
    symbols: tuple[ProgramSymbol, ...]
    expressions: tuple[ProgramExpression, ...]
    commands: tuple[ProgramCommand, ...]
    functions: tuple[ProgramFunction, ...]
    global_symbol_ids: tuple[str, ...] = ()
    metadata: FrozenMap = field(default_factory=FrozenMap)
    program_id: str = ""
    schema_version: str = PROGRAM_IR_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "sources",
            tuple(
                item
                if isinstance(item, SourceRef)
                else SourceRef.from_dict(_mapping(item, "source"))
                for item in self.sources
            ),
        )
        object.__setattr__(
            self,
            "spans",
            tuple(
                item
                if isinstance(item, SourceSpan)
                else SourceSpan.from_dict(_mapping(item, "span"))
                for item in self.spans
            ),
        )
        for name, cls in (
            ("symbols", ProgramSymbol),
            ("expressions", ProgramExpression),
            ("commands", ProgramCommand),
            ("functions", ProgramFunction),
        ):
            singular = name[:-1] if name != "classes" else "class"
            values = tuple(
                item if isinstance(item, cls) else cls.from_dict(_mapping(item, singular))
                for item in getattr(self, name)
            )
            identity_field = {
                "symbols": "symbol_id",
                "expressions": "expression_id",
                "commands": "command_id",
                "functions": "function_id",
            }[name]
            object.__setattr__(
                self,
                name,
                tuple(sorted(values, key=lambda item: getattr(item, identity_field))),
            )
        object.__setattr__(
            self, "sources", tuple(sorted(self.sources, key=lambda item: item.ref_id))
        )
        object.__setattr__(self, "spans", tuple(sorted(self.spans, key=lambda item: item.span_id)))
        object.__setattr__(
            self,
            "global_symbol_ids",
            _ids(self.global_symbol_ids, "global_symbol_ids"),
        )
        object.__setattr__(self, "metadata", _frozen(self.metadata, "metadata"))
        self.validate()
        identity = self._compute_identity()
        if self.program_id and self.program_id != identity.cid:
            raise ProgramValidationError("program_id does not match canonical program semantics")
        object.__setattr__(self, "program_id", identity.cid)

    @property
    def identity(self) -> CanonicalIdentity:
        return self._compute_identity()

    @property
    def canonical_id(self) -> str:
        return self.program_id

    def _compute_identity(self) -> CanonicalIdentity:
        return canonical_identity(
            self.semantic_dict(),
            domain=PROGRAM_IR_IDENTITY_DOMAIN,
            schema_version=PROGRAM_IR_SCHEMA_VERSION,
        )

    def semantic_dict(self) -> dict[str, Any]:
        return {
            "commands": [
                item.to_dict() for item in sorted(self.commands, key=lambda item: item.command_id)
            ],
            "expressions": [
                item.to_dict()
                for item in sorted(self.expressions, key=lambda item: item.expression_id)
            ],
            "functions": [
                item.to_dict() for item in sorted(self.functions, key=lambda item: item.function_id)
            ],
            "global_symbol_ids": list(self.global_symbol_ids),
            "metadata": self.metadata.to_dict(),
            "schema_version": self.schema_version,
            "sources": [
                item.to_dict() for item in sorted(self.sources, key=lambda item: item.ref_id)
            ],
            "spans": [item.to_dict() for item in sorted(self.spans, key=lambda item: item.span_id)],
            "symbols": [
                item.to_dict() for item in sorted(self.symbols, key=lambda item: item.symbol_id)
            ],
        }

    deterministic_dict = semantic_dict

    def to_dict(self) -> dict[str, Any]:
        value = self.semantic_dict()
        value["program_id"] = self.program_id
        return value

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())

    def semantic_bytes(self) -> bytes:
        return self.identity.canonical_bytes

    def to_json(self) -> str:
        return self.canonical_bytes().decode("utf-8")

    def validate(self) -> None:
        if self.schema_version != PROGRAM_IR_SCHEMA_VERSION:
            raise ProgramValidationError(f"unsupported schema_version {self.schema_version!r}")
        if not self.sources:
            raise ProgramValidationError("a source-grounded ProgramIR requires sources")
        if not self.functions:
            raise ProgramValidationError("ProgramIR requires at least one function")

        def unique(values: Sequence[object], attr: str, label: str) -> set[str]:
            ids = [getattr(item, attr) for item in values]
            if len(ids) != len(set(ids)):
                raise ProgramValidationError(f"duplicate {label} identifiers")
            return set(ids)

        source_ids = unique(self.sources, "ref_id", "source")
        unique(self.spans, "span_id", "span")
        symbol_ids = unique(self.symbols, "symbol_id", "symbol")
        expression_ids = unique(self.expressions, "expression_id", "expression")
        command_ids = unique(self.commands, "command_id", "command")
        unique(self.functions, "function_id", "function")
        graph_ids = [item.cfg.graph_id for item in self.functions]
        if len(graph_ids) != len(set(graph_ids)):
            raise ProgramValidationError("duplicate CFG identifiers")

        for source in self.sources:
            source.validate()
        spans_by_id = {item.span_id: item for item in self.spans}
        for span in self.spans:
            span.validate()
            _known((span.source_ref_id,), source_ids, f"span {span.span_id}")
        for item in (
            *self.symbols,
            *self.expressions,
            *self.commands,
            *self.functions,
            *(block for function in self.functions for block in function.cfg.blocks),
            *(condition for command in self.commands for condition in command.undefined_behavior),
        ):
            self._validate_source_map(item, source_ids, spans_by_id)

        _known(self.global_symbol_ids, symbol_ids, "global_symbol_ids")
        symbols_by_id = {item.symbol_id: item for item in self.symbols}
        for symbol_id in self.global_symbol_ids:
            if symbols_by_id[symbol_id].kind not in {
                SymbolKind.GLOBAL,
                SymbolKind.FUNCTION,
            }:
                raise ProgramValidationError(f"global scope contains non-global symbol {symbol_id}")
        expressions_by_id = {item.expression_id: item for item in self.expressions}
        for expression in self.expressions:
            _known(
                expression.operand_ids,
                expression_ids,
                f"expression {expression.expression_id}.operands",
            )
            _known(
                expression.symbol_ids,
                symbol_ids,
                f"expression {expression.expression_id}.symbols",
            )
            if expression.expression_id in expression.operand_ids:
                raise ProgramValidationError(
                    f"expression {expression.expression_id} references itself"
                )
        self._reject_expression_cycles(expressions_by_id)

        commands_by_id = {item.command_id: item for item in self.commands}
        for command in self.commands:
            _known(
                command.expression_ids,
                expression_ids,
                f"command {command.command_id}.expressions",
            )
            _known(
                command.target_symbol_ids,
                symbol_ids,
                f"command {command.command_id}.targets",
            )
            _known(
                command.effects.symbol_ids(),
                symbol_ids,
                f"command {command.command_id}.effects",
            )
            for condition in command.undefined_behavior:
                _known(
                    (condition.expression_id,),
                    expression_ids,
                    f"undefined behavior {condition.condition_id}",
                )

        owned_commands: dict[str, str] = {}
        used_scoped_symbols: set[str] = set()
        for function in self.functions:
            function.cfg.validate(
                known_command_ids=command_ids,
                known_expression_ids=expression_ids,
            )
            _known(function.scoped_symbol_ids, symbol_ids, f"function {function.function_id}")
            visible = set(self.global_symbol_ids) | set(function.scoped_symbol_ids)
            for symbol_id in function.parameter_symbol_ids:
                if symbols_by_id[symbol_id].kind is not SymbolKind.PARAMETER:
                    raise ProgramValidationError(
                        f"function parameter {symbol_id} is not a parameter symbol"
                    )
            for symbol_id in function.local_symbol_ids:
                if symbols_by_id[symbol_id].kind is not SymbolKind.LOCAL:
                    raise ProgramValidationError(
                        f"function local {symbol_id} is not a local symbol"
                    )
            for symbol_id in function.exception_symbol_ids:
                if symbols_by_id[symbol_id].kind is not SymbolKind.EXCEPTION:
                    raise ProgramValidationError(
                        f"function exception {symbol_id} is not an exception symbol"
                    )
            if function.result_symbol_id and (
                symbols_by_id[function.result_symbol_id].kind is not SymbolKind.RESULT
            ):
                raise ProgramValidationError(
                    f"function result {function.result_symbol_id} is not a result symbol"
                )
            overlap = used_scoped_symbols & set(function.scoped_symbol_ids)
            if overlap:
                raise ProgramValidationError(
                    f"function-local symbols have multiple owners: {sorted(overlap)}"
                )
            used_scoped_symbols.update(function.scoped_symbol_ids)
            _known(
                function.effects.symbol_ids(),
                visible,
                f"function {function.function_id}.effects",
            )
            edge_exceptions = {
                edge.exception_type
                for edge in function.cfg.edges
                if edge.kind is EdgeKind.EXCEPTION
            }
            undeclared_edge_exceptions = sorted(edge_exceptions - set(function.declared_exceptions))
            if undeclared_edge_exceptions:
                raise ProgramValidationError(
                    f"CFG {function.cfg.graph_id} raises undeclared exceptions "
                    f"{undeclared_edge_exceptions}"
                )
            for edge in function.cfg.edges:
                if edge.condition_expression_id:
                    referenced = self._expression_symbols(
                        (edge.condition_expression_id,), expressions_by_id
                    )
                    _known(
                        tuple(referenced),
                        visible,
                        f"edge {edge.edge_id} condition in function {function.function_id}",
                    )
            for command_id in function.cfg.command_ids:
                if command_id in owned_commands:
                    raise ProgramValidationError(
                        f"command {command_id} belongs to multiple functions"
                    )
                owned_commands[command_id] = function.function_id
                command = commands_by_id[command_id]
                _known(
                    command.target_symbol_ids,
                    visible,
                    f"command {command_id}.targets in function {function.function_id}",
                )
                _known(
                    command.effects.symbol_ids(),
                    visible,
                    f"command {command_id}.effects in function {function.function_id}",
                )
                if not command.effects.is_subset_of(function.effects):
                    raise ProgramValidationError(
                        f"command {command_id} effects exceed function "
                        f"{function.function_id} effects"
                    )
                roots = list(command.expression_ids)
                roots.extend(item.expression_id for item in command.undefined_behavior)
                for edge in function.cfg.edges:
                    if (
                        edge.source_block_id
                        in {
                            block.block_id
                            for block in function.cfg.blocks
                            if command_id in block.command_ids
                        }
                        and edge.condition_expression_id
                    ):
                        roots.append(edge.condition_expression_id)
                referenced = self._expression_symbols(roots, expressions_by_id)
                _known(
                    tuple(referenced),
                    visible,
                    f"command {command_id} expressions in function {function.function_id}",
                )
        unowned = sorted(command_ids - set(owned_commands))
        if unowned:
            raise ProgramValidationError(f"commands are not owned by a function: {unowned}")
        scoped_declared = {
            item.symbol_id
            for item in self.symbols
            if item.kind
            in {
                SymbolKind.PARAMETER,
                SymbolKind.LOCAL,
                SymbolKind.RESULT,
                SymbolKind.EXCEPTION,
            }
        }
        unowned_symbols = sorted(scoped_declared - used_scoped_symbols)
        if unowned_symbols:
            raise ProgramValidationError(
                f"scoped symbols are not bound to a function: {unowned_symbols}"
            )

    @staticmethod
    def _validate_source_map(
        item: object,
        source_ids: set[str],
        spans: Mapping[str, SourceSpan],
    ) -> None:
        sources = getattr(item, "source_ref_ids")
        span_ids = getattr(item, "span_ids")
        _known(sources, source_ids, f"{type(item).__name__}.source_ref_ids")
        _known(span_ids, set(spans), f"{type(item).__name__}.span_ids")
        if sources:
            unlisted = sorted(
                {
                    spans[span_id].source_ref_id
                    for span_id in span_ids
                    if spans[span_id].source_ref_id not in sources
                }
            )
            if unlisted:
                raise ProgramValidationError(
                    f"{type(item).__name__} spans belong to unlisted sources {unlisted}"
                )

    @staticmethod
    def _reject_expression_cycles(
        expressions: Mapping[str, ProgramExpression],
    ) -> None:
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(expression_id: str) -> None:
            if expression_id in visiting:
                raise ProgramValidationError(f"cyclic expression dependency at {expression_id}")
            if expression_id in visited:
                return
            visiting.add(expression_id)
            for child in expressions[expression_id].operand_ids:
                visit(child)
            visiting.remove(expression_id)
            visited.add(expression_id)

        for expression_id in expressions:
            visit(expression_id)

    @staticmethod
    def _expression_symbols(
        roots: Sequence[str],
        expressions: Mapping[str, ProgramExpression],
    ) -> set[str]:
        symbols: set[str] = set()
        pending = list(roots)
        seen: set[str] = set()
        while pending:
            current = pending.pop()
            if current in seen:
                continue
            seen.add(current)
            expression = expressions[current]
            symbols.update(expression.symbol_ids)
            pending.extend(expression.operand_ids)
        return symbols

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ProgramIR":
        value = _mapping(value, "program")
        return cls(
            sources=tuple(
                SourceRef.from_dict(_mapping(item, "source")) for item in value.get("sources", ())
            ),
            spans=tuple(
                SourceSpan.from_dict(_mapping(item, "span")) for item in value.get("spans", ())
            ),
            symbols=tuple(
                ProgramSymbol.from_dict(_mapping(item, "symbol"))
                for item in value.get("symbols", ())
            ),
            expressions=tuple(
                ProgramExpression.from_dict(_mapping(item, "expression"))
                for item in value.get("expressions", ())
            ),
            commands=tuple(
                ProgramCommand.from_dict(_mapping(item, "command"))
                for item in value.get("commands", ())
            ),
            functions=tuple(
                ProgramFunction.from_dict(_mapping(item, "function"))
                for item in value.get("functions", ())
            ),
            global_symbol_ids=tuple(value.get("global_symbol_ids", ())),
            metadata=_frozen(_mapping(value.get("metadata", {}), "metadata"), "metadata"),
            program_id=value.get("program_id", ""),
            schema_version=value.get("schema_version", PROGRAM_IR_SCHEMA_VERSION),
        )


# Concise compatibility spellings for consumers that already qualify the module.
Expression = ProgramExpression
Command = ProgramCommand
Function = ProgramFunction
CFG = ControlFlowGraph


__all__ = [
    "PROGRAM_IR_SCHEMA_VERSION",
    "BasicBlock",
    "CFG",
    "Command",
    "CommandKind",
    "ControlFlowEdge",
    "ControlFlowGraph",
    "EdgeKind",
    "EffectSummary",
    "Expression",
    "ExpressionKind",
    "Function",
    "ProgramCommand",
    "ProgramExpression",
    "ProgramFunction",
    "ProgramIR",
    "ProgramSymbol",
    "ProgramValidationError",
    "Purity",
    "SymbolKind",
    "UndefinedBehaviorCondition",
    "UndefinedBehaviorConsequence",
]
