"""Program contracts, Hoare triples, loop obligations, and dynamic logic.

Contracts are declarations of obligations, not proof results.  They retain
normal and exceptional postconditions as different types, make frames and
effects explicit, and can be checked against a closed :class:`ProgramIR`.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Final

from ipfs_datasets_py.logic.ir_core.claims import FrozenMap

from .program import (
    EffectSummary,
    ProgramIR,
    ProgramValidationError,
    Purity,
    UndefinedBehaviorCondition,
    _enum,
    _frozen,
    _identifier,
    _ids,
    _known,
    _mapping,
    _source_map,
    _text,
)

PROGRAM_CONTRACT_SCHEMA_VERSION: Final = "program-contract/v1"


class ContractValidationError(ValueError):
    """Raised when contract semantics are malformed or unresolved."""


class ContractClauseKind(str, Enum):
    PRECONDITION = "precondition"
    POSTCONDITION = "postcondition"
    EXCEPTIONAL_POSTCONDITION = "exceptional_postcondition"
    LOOP_INVARIANT = "loop_invariant"
    LOOP_VARIANT = "loop_variant"


class DynamicLogicModality(str, Enum):
    BOX = "box"
    DIAMOND = "diamond"


class DynamicProgramKind(str, Enum):
    COMMAND = "command"
    CFG = "cfg"
    FUNCTION = "function"


class DynamicLogicExit(str, Enum):
    NORMAL = "normal"
    EXCEPTIONAL = "exceptional"


def _contract_enum(value: object, enum_type: type[Enum], label: str) -> Any:
    try:
        return _enum(value, enum_type, label)
    except ProgramValidationError as error:
        raise ContractValidationError(str(error)) from error


def _contract_source(
    source_ref_ids: Sequence[str], span_ids: Sequence[str], owner: str
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    try:
        return _source_map(source_ref_ids, span_ids, owner)
    except ProgramValidationError as error:
        raise ContractValidationError(str(error)) from error


@dataclass(frozen=True, slots=True)
class ContractClause:
    clause_id: str
    kind: ContractClauseKind | str
    expression_id: str
    statement: str
    exception_type: str = ""
    source_ref_ids: tuple[str, ...] = ()
    span_ids: tuple[str, ...] = ()
    attributes: FrozenMap = field(default_factory=FrozenMap)

    def __post_init__(self) -> None:
        sources, spans = _contract_source(self.source_ref_ids, self.span_ids, "ContractClause")
        kind = _contract_enum(self.kind, ContractClauseKind, "kind")
        exception_type = self.exception_type
        if exception_type:
            exception_type = _text(exception_type, "exception_type")
        if kind is ContractClauseKind.EXCEPTIONAL_POSTCONDITION:
            if not exception_type:
                raise ContractValidationError("exceptional postconditions require exception_type")
        elif exception_type:
            raise ContractValidationError(
                "exception_type is only valid on exceptional postconditions"
            )
        try:
            object.__setattr__(self, "clause_id", _identifier(self.clause_id, "clause_id"))
            object.__setattr__(
                self,
                "expression_id",
                _identifier(self.expression_id, "expression_id"),
            )
            object.__setattr__(self, "statement", _text(self.statement, "statement"))
            object.__setattr__(self, "attributes", _frozen(self.attributes, "attributes"))
        except ProgramValidationError as error:
            raise ContractValidationError(str(error)) from error
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "exception_type", exception_type)
        object.__setattr__(self, "source_ref_ids", sources)
        object.__setattr__(self, "span_ids", spans)

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": self.attributes.to_dict(),
            "clause_id": self.clause_id,
            "exception_type": self.exception_type,
            "expression_id": self.expression_id,
            "kind": self.kind.value,
            "source_ref_ids": list(self.source_ref_ids),
            "span_ids": list(self.span_ids),
            "statement": self.statement,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ContractClause":
        return cls(
            clause_id=value.get("clause_id", ""),
            kind=value.get("kind", ""),
            expression_id=value.get("expression_id", ""),
            statement=value.get("statement", ""),
            exception_type=value.get("exception_type", ""),
            source_ref_ids=tuple(value.get("source_ref_ids", ())),
            span_ids=tuple(value.get("span_ids", ())),
            attributes=_frozen(_mapping(value.get("attributes", {}), "attributes"), "attributes"),
        )


@dataclass(frozen=True, slots=True)
class FrameCondition:
    """Locations a contract permits a function to observe or modify.

    Empty tuples with ``allows_all_*`` false mean "none", never "unspecified".
    """

    readable_symbol_ids: tuple[str, ...] = ()
    writable_symbol_ids: tuple[str, ...] = ()
    allows_all_reads: bool = False
    allows_all_writes: bool = False

    def __post_init__(self) -> None:
        try:
            reads = _ids(self.readable_symbol_ids, "readable_symbol_ids")
            writes = _ids(self.writable_symbol_ids, "writable_symbol_ids")
        except ProgramValidationError as error:
            raise ContractValidationError(str(error)) from error
        if not isinstance(self.allows_all_reads, bool) or not isinstance(
            self.allows_all_writes, bool
        ):
            raise ContractValidationError("frame wildcard flags must be boolean")
        if self.allows_all_reads and reads:
            raise ContractValidationError("readable_symbol_ids cannot accompany allows_all_reads")
        if self.allows_all_writes and writes:
            raise ContractValidationError("writable_symbol_ids cannot accompany allows_all_writes")
        object.__setattr__(self, "readable_symbol_ids", reads)
        object.__setattr__(self, "writable_symbol_ids", writes)

    def permits(self, effects: EffectSummary) -> bool:
        modified = set(effects.writes + effects.allocates + effects.deallocates)
        return (self.allows_all_reads or set(effects.reads) <= set(self.readable_symbol_ids)) and (
            self.allows_all_writes or modified <= set(self.writable_symbol_ids)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "allows_all_reads": self.allows_all_reads,
            "allows_all_writes": self.allows_all_writes,
            "readable_symbol_ids": list(self.readable_symbol_ids),
            "writable_symbol_ids": list(self.writable_symbol_ids),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "FrameCondition":
        return cls(
            readable_symbol_ids=tuple(value.get("readable_symbol_ids", ())),
            writable_symbol_ids=tuple(value.get("writable_symbol_ids", ())),
            allows_all_reads=value.get("allows_all_reads", False),
            allows_all_writes=value.get("allows_all_writes", False),
        )


def _clauses(
    values: Sequence[ContractClause | Mapping[str, Any]],
    expected: ContractClauseKind,
    label: str,
) -> tuple[ContractClause, ...]:
    result = tuple(
        item
        if isinstance(item, ContractClause)
        else ContractClause.from_dict(_mapping(item, f"{label} item"))
        for item in values
    )
    wrong = [item.clause_id for item in result if item.kind is not expected]
    if wrong:
        raise ContractValidationError(f"{label} contains clauses with the wrong kind: {wrong}")
    ids = [item.clause_id for item in result]
    if len(ids) != len(set(ids)):
        raise ContractValidationError(f"{label} contains duplicate clause ids")
    return result


def _validate_source_maps(program: ProgramIR, items: Sequence[object]) -> None:
    source_ids = {item.ref_id for item in program.sources}
    spans = {item.span_id: item for item in program.spans}
    for item in items:
        try:
            _known(
                getattr(item, "source_ref_ids"),
                source_ids,
                f"{type(item).__name__}.source_ref_ids",
            )
            _known(
                getattr(item, "span_ids"),
                set(spans),
                f"{type(item).__name__}.span_ids",
            )
        except ProgramValidationError as error:
            raise ContractValidationError(str(error)) from error
        if getattr(item, "source_ref_ids"):
            unlisted = sorted(
                {
                    spans[span_id].source_ref_id
                    for span_id in getattr(item, "span_ids")
                    if spans[span_id].source_ref_id not in getattr(item, "source_ref_ids")
                }
            )
            if unlisted:
                raise ContractValidationError(
                    f"{type(item).__name__} spans belong to unlisted sources {unlisted}"
                )


def _validate_expression_scope(
    program: ProgramIR,
    expression_ids: Sequence[str],
    function_id: str,
    label: str,
) -> None:
    functions = {item.function_id: item for item in program.functions}
    expressions = {item.expression_id: item for item in program.expressions}
    function = functions[function_id]
    visible = set(program.global_symbol_ids) | set(function.scoped_symbol_ids)
    referenced = program._expression_symbols(expression_ids, expressions)
    try:
        _known(tuple(referenced), visible, label)
    except ProgramValidationError as error:
        raise ContractValidationError(str(error)) from error


@dataclass(frozen=True, slots=True)
class ProgramContract:
    """A complete function contract (``ProgramContract@1``)."""

    contract_id: str
    function_id: str
    preconditions: tuple[ContractClause, ...] = ()
    postconditions: tuple[ContractClause, ...] = ()
    exceptional_postconditions: tuple[ContractClause, ...] = ()
    frame: FrameCondition = field(default_factory=FrameCondition)
    effects: EffectSummary = field(default_factory=EffectSummary)
    purity: Purity | str = Purity.UNKNOWN
    undefined_behavior: tuple[UndefinedBehaviorCondition, ...] = ()
    source_ref_ids: tuple[str, ...] = ()
    span_ids: tuple[str, ...] = ()
    attributes: FrozenMap = field(default_factory=FrozenMap)
    schema_version: str = PROGRAM_CONTRACT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        sources, spans = _contract_source(self.source_ref_ids, self.span_ids, "ProgramContract")
        pre = _clauses(self.preconditions, ContractClauseKind.PRECONDITION, "preconditions")
        post = _clauses(self.postconditions, ContractClauseKind.POSTCONDITION, "postconditions")
        exceptional = _clauses(
            self.exceptional_postconditions,
            ContractClauseKind.EXCEPTIONAL_POSTCONDITION,
            "exceptional_postconditions",
        )
        all_ids = [item.clause_id for item in (*pre, *post, *exceptional)]
        if len(all_ids) != len(set(all_ids)):
            raise ContractValidationError("clause identifiers must be unique across a contract")
        frame = (
            self.frame
            if isinstance(self.frame, FrameCondition)
            else FrameCondition.from_dict(_mapping(self.frame, "frame"))
        )
        effects = (
            self.effects
            if isinstance(self.effects, EffectSummary)
            else EffectSummary.from_dict(_mapping(self.effects, "effects"))
        )
        purity = _contract_enum(self.purity, Purity, "purity")
        undefined = tuple(
            item
            if isinstance(item, UndefinedBehaviorCondition)
            else UndefinedBehaviorCondition.from_dict(_mapping(item, "undefined_behavior item"))
            for item in self.undefined_behavior
        )
        if purity is Purity.PURE and not effects.is_pure:
            raise ContractValidationError("a pure contract cannot permit impure effects")
        if purity is Purity.READ_ONLY and not effects.is_read_only:
            raise ContractValidationError("a read-only contract cannot permit write effects")
        if not frame.permits(effects):
            raise ContractValidationError("declared effects exceed the contract frame")
        if self.schema_version != PROGRAM_CONTRACT_SCHEMA_VERSION:
            raise ContractValidationError(f"unsupported schema_version {self.schema_version!r}")
        try:
            object.__setattr__(self, "contract_id", _identifier(self.contract_id, "contract_id"))
            object.__setattr__(self, "function_id", _identifier(self.function_id, "function_id"))
            object.__setattr__(self, "attributes", _frozen(self.attributes, "attributes"))
        except ProgramValidationError as error:
            raise ContractValidationError(str(error)) from error
        object.__setattr__(self, "preconditions", pre)
        object.__setattr__(self, "postconditions", post)
        object.__setattr__(self, "exceptional_postconditions", exceptional)
        object.__setattr__(self, "frame", frame)
        object.__setattr__(self, "effects", effects)
        object.__setattr__(self, "purity", purity)
        object.__setattr__(self, "undefined_behavior", undefined)
        object.__setattr__(self, "source_ref_ids", sources)
        object.__setattr__(self, "span_ids", spans)

    @property
    def normal_postconditions(self) -> tuple[ContractClause, ...]:
        return self.postconditions

    def validate_against(self, program: ProgramIR) -> None:
        """Resolve every contract reference against ``program`` or fail closed."""

        functions = {item.function_id: item for item in program.functions}
        expressions_by_id = {item.expression_id: item for item in program.expressions}
        expressions = set(expressions_by_id)
        if self.function_id not in functions:
            raise ContractValidationError(
                f"contract references unknown function {self.function_id!r}"
            )
        function = functions[self.function_id]
        visible = set(program.global_symbol_ids) | set(function.scoped_symbol_ids)
        clause_expressions = tuple(
            item.expression_id
            for item in (
                *self.preconditions,
                *self.postconditions,
                *self.exceptional_postconditions,
            )
        )
        try:
            _known(clause_expressions, expressions, f"contract {self.contract_id}")
            _known(
                self.frame.readable_symbol_ids + self.frame.writable_symbol_ids,
                visible,
                f"contract {self.contract_id}.frame",
            )
            _known(
                self.effects.symbol_ids(),
                visible,
                f"contract {self.contract_id}.effects",
            )
            _known(
                tuple(item.expression_id for item in self.undefined_behavior),
                expressions,
                f"contract {self.contract_id}.undefined_behavior",
            )
        except ProgramValidationError as error:
            raise ContractValidationError(str(error)) from error
        referenced_symbols = program._expression_symbols(
            clause_expressions + tuple(item.expression_id for item in self.undefined_behavior),
            expressions_by_id,
        )
        try:
            _known(
                tuple(referenced_symbols),
                visible,
                f"contract {self.contract_id}.expressions",
            )
        except ProgramValidationError as error:
            raise ContractValidationError(str(error)) from error
        exception_types = {item.exception_type for item in self.exceptional_postconditions}
        undeclared = sorted(exception_types - set(function.declared_exceptions))
        if undeclared:
            raise ContractValidationError(
                f"exceptional postconditions reference undeclared exceptions {undeclared}"
            )
        if not function.effects.is_subset_of(self.effects):
            raise ContractValidationError(
                "function effects exceed the effects permitted by its contract"
            )
        if not self.frame.permits(function.effects):
            raise ContractValidationError(
                "function effects exceed the frame permitted by its contract"
            )
        self._validate_sources(program)

    def _validate_sources(self, program: ProgramIR) -> None:
        _validate_source_maps(
            program,
            (
                self,
                *self.preconditions,
                *self.postconditions,
                *self.exceptional_postconditions,
                *self.undefined_behavior,
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": self.attributes.to_dict(),
            "contract_id": self.contract_id,
            "effects": self.effects.to_dict(),
            "exceptional_postconditions": [
                item.to_dict() for item in self.exceptional_postconditions
            ],
            "frame": self.frame.to_dict(),
            "function_id": self.function_id,
            "postconditions": [item.to_dict() for item in self.postconditions],
            "preconditions": [item.to_dict() for item in self.preconditions],
            "purity": self.purity.value,
            "schema_version": self.schema_version,
            "source_ref_ids": list(self.source_ref_ids),
            "span_ids": list(self.span_ids),
            "undefined_behavior": [item.to_dict() for item in self.undefined_behavior],
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ProgramContract":
        return cls(
            contract_id=value.get("contract_id", ""),
            function_id=value.get("function_id", ""),
            preconditions=tuple(
                ContractClause.from_dict(_mapping(item, "precondition"))
                for item in value.get("preconditions", ())
            ),
            postconditions=tuple(
                ContractClause.from_dict(_mapping(item, "postcondition"))
                for item in value.get("postconditions", ())
            ),
            exceptional_postconditions=tuple(
                ContractClause.from_dict(_mapping(item, "exceptional postcondition"))
                for item in value.get("exceptional_postconditions", ())
            ),
            frame=FrameCondition.from_dict(_mapping(value.get("frame", {}), "frame")),
            effects=EffectSummary.from_dict(_mapping(value.get("effects", {}), "effects")),
            purity=value.get("purity", Purity.UNKNOWN.value),
            undefined_behavior=tuple(
                UndefinedBehaviorCondition.from_dict(_mapping(item, "undefined_behavior item"))
                for item in value.get("undefined_behavior", ())
            ),
            source_ref_ids=tuple(value.get("source_ref_ids", ())),
            span_ids=tuple(value.get("span_ids", ())),
            attributes=_frozen(_mapping(value.get("attributes", {}), "attributes"), "attributes"),
            schema_version=value.get("schema_version", PROGRAM_CONTRACT_SCHEMA_VERSION),
        )


@dataclass(frozen=True, slots=True)
class ExceptionalPostcondition:
    exception_type: str
    expression_id: str

    def __post_init__(self) -> None:
        try:
            object.__setattr__(self, "exception_type", _text(self.exception_type, "exception_type"))
            object.__setattr__(
                self,
                "expression_id",
                _identifier(self.expression_id, "expression_id"),
            )
        except ProgramValidationError as error:
            raise ContractValidationError(str(error)) from error

    def to_dict(self) -> dict[str, str]:
        return {
            "exception_type": self.exception_type,
            "expression_id": self.expression_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ExceptionalPostcondition":
        return cls(
            exception_type=value.get("exception_type", ""),
            expression_id=value.get("expression_id", ""),
        )


@dataclass(frozen=True, slots=True)
class HoareTriple:
    """Partial- or total-correctness judgment with separate exit channels."""

    triple_id: str
    command_id: str
    precondition_ids: tuple[str, ...]
    normal_postcondition_ids: tuple[str, ...]
    exceptional_postconditions: tuple[ExceptionalPostcondition, ...] = ()
    total_correctness: bool = False
    variant_expression_ids: tuple[str, ...] = ()
    source_ref_ids: tuple[str, ...] = ()
    span_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        sources, spans = _contract_source(self.source_ref_ids, self.span_ids, "HoareTriple")
        exceptional = tuple(
            item
            if isinstance(item, ExceptionalPostcondition)
            else ExceptionalPostcondition.from_dict(_mapping(item, "exceptional_postcondition"))
            for item in self.exceptional_postconditions
        )
        exception_types = [item.exception_type for item in exceptional]
        if len(exception_types) != len(set(exception_types)):
            raise ContractValidationError(
                "Hoare triples cannot have ambiguous exceptional postconditions"
            )
        if not isinstance(self.total_correctness, bool):
            raise ContractValidationError("total_correctness must be boolean")
        try:
            object.__setattr__(self, "triple_id", _identifier(self.triple_id, "triple_id"))
            object.__setattr__(self, "command_id", _identifier(self.command_id, "command_id"))
            object.__setattr__(
                self,
                "precondition_ids",
                _ids(self.precondition_ids, "precondition_ids"),
            )
            object.__setattr__(
                self,
                "normal_postcondition_ids",
                _ids(self.normal_postcondition_ids, "normal_postcondition_ids"),
            )
            object.__setattr__(
                self,
                "variant_expression_ids",
                _ids(
                    self.variant_expression_ids,
                    "variant_expression_ids",
                    preserve_order=True,
                ),
            )
        except ProgramValidationError as error:
            raise ContractValidationError(str(error)) from error
        if not self.precondition_ids or not self.normal_postcondition_ids:
            raise ContractValidationError(
                "Hoare triples require preconditions and normal postconditions"
            )
        if self.total_correctness and not self.variant_expression_ids:
            raise ContractValidationError("total-correctness Hoare triples require a variant")
        object.__setattr__(self, "exceptional_postconditions", exceptional)
        object.__setattr__(self, "source_ref_ids", sources)
        object.__setattr__(self, "span_ids", spans)

    def validate_against(self, program: ProgramIR) -> None:
        expressions = {item.expression_id for item in program.expressions}
        commands = {item.command_id for item in program.commands}
        try:
            _known((self.command_id,), commands, f"Hoare triple {self.triple_id}")
            _known(
                self.precondition_ids
                + self.normal_postcondition_ids
                + self.variant_expression_ids
                + tuple(item.expression_id for item in self.exceptional_postconditions),
                expressions,
                f"Hoare triple {self.triple_id}",
            )
        except ProgramValidationError as error:
            raise ContractValidationError(str(error)) from error
        owners = [
            function
            for function in program.functions
            if self.command_id in function.cfg.command_ids
        ]
        if len(owners) != 1:
            raise ContractValidationError(
                f"Hoare triple command {self.command_id!r} has no unique owner"
            )
        _validate_expression_scope(
            program,
            self.precondition_ids
            + self.normal_postcondition_ids
            + self.variant_expression_ids
            + tuple(item.expression_id for item in self.exceptional_postconditions),
            owners[0].function_id,
            f"Hoare triple {self.triple_id}.expressions",
        )
        _validate_source_maps(program, (self,))

    def to_dict(self) -> dict[str, Any]:
        return {
            "command_id": self.command_id,
            "exceptional_postconditions": [
                item.to_dict() for item in self.exceptional_postconditions
            ],
            "normal_postcondition_ids": list(self.normal_postcondition_ids),
            "precondition_ids": list(self.precondition_ids),
            "source_ref_ids": list(self.source_ref_ids),
            "span_ids": list(self.span_ids),
            "total_correctness": self.total_correctness,
            "triple_id": self.triple_id,
            "variant_expression_ids": list(self.variant_expression_ids),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "HoareTriple":
        return cls(
            triple_id=value.get("triple_id", ""),
            command_id=value.get("command_id", ""),
            precondition_ids=tuple(value.get("precondition_ids", ())),
            normal_postcondition_ids=tuple(value.get("normal_postcondition_ids", ())),
            exceptional_postconditions=tuple(
                ExceptionalPostcondition.from_dict(_mapping(item, "exceptional_postcondition"))
                for item in value.get("exceptional_postconditions", ())
            ),
            total_correctness=value.get("total_correctness", False),
            variant_expression_ids=tuple(value.get("variant_expression_ids", ())),
            source_ref_ids=tuple(value.get("source_ref_ids", ())),
            span_ids=tuple(value.get("span_ids", ())),
        )


@dataclass(frozen=True, slots=True)
class LoopContract:
    loop_id: str
    function_id: str
    header_block_id: str
    invariants: tuple[ContractClause, ...]
    variants: tuple[ContractClause, ...] = ()
    total_correctness: bool = False
    source_ref_ids: tuple[str, ...] = ()
    span_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        sources, spans = _contract_source(self.source_ref_ids, self.span_ids, "LoopContract")
        invariants = _clauses(self.invariants, ContractClauseKind.LOOP_INVARIANT, "invariants")
        variants = _clauses(self.variants, ContractClauseKind.LOOP_VARIANT, "variants")
        if not invariants:
            raise ContractValidationError("loop contracts require an invariant")
        if not isinstance(self.total_correctness, bool):
            raise ContractValidationError("total_correctness must be boolean")
        if self.total_correctness and not variants:
            raise ContractValidationError("total-correctness loop contracts require a variant")
        try:
            object.__setattr__(self, "loop_id", _identifier(self.loop_id, "loop_id"))
            object.__setattr__(self, "function_id", _identifier(self.function_id, "function_id"))
            object.__setattr__(
                self,
                "header_block_id",
                _identifier(self.header_block_id, "header_block_id"),
            )
        except ProgramValidationError as error:
            raise ContractValidationError(str(error)) from error
        object.__setattr__(self, "invariants", invariants)
        object.__setattr__(self, "variants", variants)
        object.__setattr__(self, "source_ref_ids", sources)
        object.__setattr__(self, "span_ids", spans)

    def validate_against(self, program: ProgramIR) -> None:
        functions = {item.function_id: item for item in program.functions}
        if self.function_id not in functions:
            raise ContractValidationError(
                f"loop contract references unknown function {self.function_id!r}"
            )
        blocks = {item.block_id for item in functions[self.function_id].cfg.blocks}
        expressions = {item.expression_id for item in program.expressions}
        if self.header_block_id not in blocks:
            raise ContractValidationError(
                f"loop contract references unknown header block {self.header_block_id!r}"
            )
        try:
            _known(
                tuple(item.expression_id for item in (*self.invariants, *self.variants)),
                expressions,
                f"loop contract {self.loop_id}",
            )
        except ProgramValidationError as error:
            raise ContractValidationError(str(error)) from error
        _validate_expression_scope(
            program,
            tuple(item.expression_id for item in (*self.invariants, *self.variants)),
            self.function_id,
            f"loop contract {self.loop_id}.expressions",
        )
        _validate_source_maps(program, (self, *self.invariants, *self.variants))

    def to_dict(self) -> dict[str, Any]:
        return {
            "function_id": self.function_id,
            "header_block_id": self.header_block_id,
            "invariants": [item.to_dict() for item in self.invariants],
            "loop_id": self.loop_id,
            "source_ref_ids": list(self.source_ref_ids),
            "span_ids": list(self.span_ids),
            "total_correctness": self.total_correctness,
            "variants": [item.to_dict() for item in self.variants],
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "LoopContract":
        return cls(
            loop_id=value.get("loop_id", ""),
            function_id=value.get("function_id", ""),
            header_block_id=value.get("header_block_id", ""),
            invariants=tuple(
                ContractClause.from_dict(_mapping(item, "invariant"))
                for item in value.get("invariants", ())
            ),
            variants=tuple(
                ContractClause.from_dict(_mapping(item, "variant"))
                for item in value.get("variants", ())
            ),
            total_correctness=value.get("total_correctness", False),
            source_ref_ids=tuple(value.get("source_ref_ids", ())),
            span_ids=tuple(value.get("span_ids", ())),
        )


@dataclass(frozen=True, slots=True)
class DynamicLogicFormula:
    """A box/diamond formula over a command, CFG, or function."""

    formula_id: str
    modality: DynamicLogicModality | str
    program_kind: DynamicProgramKind | str
    program_ref_id: str
    postcondition_expression_id: str
    exit: DynamicLogicExit | str = DynamicLogicExit.NORMAL
    exception_type: str = ""
    source_ref_ids: tuple[str, ...] = ()
    span_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        sources, spans = _contract_source(self.source_ref_ids, self.span_ids, "DynamicLogicFormula")
        modality = _contract_enum(self.modality, DynamicLogicModality, "modality")
        program_kind = _contract_enum(self.program_kind, DynamicProgramKind, "program_kind")
        exit_kind = _contract_enum(self.exit, DynamicLogicExit, "exit")
        exception_type = self.exception_type
        if exception_type:
            exception_type = _text(exception_type, "exception_type")
        if exit_kind is DynamicLogicExit.EXCEPTIONAL and not exception_type:
            raise ContractValidationError(
                "exceptional dynamic-logic formulas require exception_type"
            )
        if exit_kind is DynamicLogicExit.NORMAL and exception_type:
            raise ContractValidationError(
                "normal dynamic-logic formulas cannot name an exception_type"
            )
        try:
            object.__setattr__(self, "formula_id", _identifier(self.formula_id, "formula_id"))
            object.__setattr__(
                self, "program_ref_id", _identifier(self.program_ref_id, "program_ref_id")
            )
            object.__setattr__(
                self,
                "postcondition_expression_id",
                _identifier(
                    self.postcondition_expression_id,
                    "postcondition_expression_id",
                ),
            )
        except ProgramValidationError as error:
            raise ContractValidationError(str(error)) from error
        object.__setattr__(self, "modality", modality)
        object.__setattr__(self, "program_kind", program_kind)
        object.__setattr__(self, "exit", exit_kind)
        object.__setattr__(self, "exception_type", exception_type)
        object.__setattr__(self, "source_ref_ids", sources)
        object.__setattr__(self, "span_ids", spans)

    def validate_against(self, program: ProgramIR) -> None:
        if self.program_kind is DynamicProgramKind.COMMAND:
            known = {item.command_id for item in program.commands}
            owning_functions = [
                function
                for function in program.functions
                if self.program_ref_id in function.cfg.command_ids
            ]
        elif self.program_kind is DynamicProgramKind.CFG:
            known = {item.cfg.graph_id for item in program.functions}
            owning_functions = [
                function
                for function in program.functions
                if function.cfg.graph_id == self.program_ref_id
            ]
        else:
            known = {item.function_id for item in program.functions}
            owning_functions = [
                function
                for function in program.functions
                if function.function_id == self.program_ref_id
            ]
        expressions = {item.expression_id for item in program.expressions}
        try:
            _known((self.program_ref_id,), known, f"formula {self.formula_id}.program")
            _known(
                (self.postcondition_expression_id,),
                expressions,
                f"formula {self.formula_id}.postcondition",
            )
        except ProgramValidationError as error:
            raise ContractValidationError(str(error)) from error
        if len(owning_functions) != 1:
            raise ContractValidationError(
                f"formula program {self.program_ref_id!r} has no unique owner"
            )
        _validate_expression_scope(
            program,
            (self.postcondition_expression_id,),
            owning_functions[0].function_id,
            f"formula {self.formula_id}.postcondition",
        )
        if self.exit is DynamicLogicExit.EXCEPTIONAL:
            if any(
                self.exception_type not in function.declared_exceptions
                for function in owning_functions
            ):
                raise ContractValidationError(
                    f"formula references undeclared exception {self.exception_type!r}"
                )
        _validate_source_maps(program, (self,))

    def to_dict(self) -> dict[str, Any]:
        return {
            "exception_type": self.exception_type,
            "exit": self.exit.value,
            "formula_id": self.formula_id,
            "modality": self.modality.value,
            "postcondition_expression_id": self.postcondition_expression_id,
            "program_kind": self.program_kind.value,
            "program_ref_id": self.program_ref_id,
            "source_ref_ids": list(self.source_ref_ids),
            "span_ids": list(self.span_ids),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "DynamicLogicFormula":
        return cls(
            formula_id=value.get("formula_id", ""),
            modality=value.get("modality", ""),
            program_kind=value.get("program_kind", ""),
            program_ref_id=value.get("program_ref_id", ""),
            postcondition_expression_id=value.get("postcondition_expression_id", ""),
            exit=value.get("exit", DynamicLogicExit.NORMAL.value),
            exception_type=value.get("exception_type", ""),
            source_ref_ids=tuple(value.get("source_ref_ids", ())),
            span_ids=tuple(value.get("span_ids", ())),
        )


__all__ = [
    "PROGRAM_CONTRACT_SCHEMA_VERSION",
    "ContractClause",
    "ContractClauseKind",
    "ContractValidationError",
    "DynamicLogicExit",
    "DynamicLogicFormula",
    "DynamicLogicModality",
    "DynamicProgramKind",
    "ExceptionalPostcondition",
    "FrameCondition",
    "HoareTriple",
    "LoopContract",
    "ProgramContract",
]
