"""Opt-in, source-withheld legal surface IR; not the measured canonical v1 IR.

Definitions and policy declarations are not deontic modalities. Literal slots
remain natural-language atoms: this representation is a structured candidate,
not a formal proof or a claim that those atoms have been logically interpreted.
Lineage belongs to the compilation receipt, not to the decompiler's input.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from datetime import date
from typing import ClassVar

from ..TDFOL.compiler_repairs import TemporalDeadline


EXTENDED_IR_SCHEMA = "legal-surface-ir/v2"
EXTENDED_DEADLINE_IR_SCHEMA = "legal-surface-ir-with-typed-deadlines/v1"
EFFECTIVE_DATE_IR_SCHEMA = "legal-surface-ir-with-effective-dates/v1"
MAX_STATEMENTS = 128
MAX_ATOM_CHARACTERS = 16_384


def _atom(value: object) -> None:
    if (type(value) is not str or not value or value != " ".join(value.split())
            or len(value) > MAX_ATOM_CHARACTERS or any(ord(ch) < 32 for ch in value)):
        raise ValueError("IR atoms must be bounded nonempty single-line normalized strings")


def _atoms(value: object, *, nonempty: bool = False) -> None:
    if type(value) is not tuple or len(value) > MAX_STATEMENTS or (nonempty and not value):
        raise ValueError("IR atom collections must be bounded immutable tuples")
    for atom in value:
        _atom(atom)


@dataclass(frozen=True, slots=True)
class EffectiveFrom:
    """An explicit source-supported civil start date, without applicability proof."""

    effective_from: str

    def __post_init__(self):
        if type(self.effective_from) is not str or len(self.effective_from) != 10:
            raise ValueError("effective-from must be an exact ISO civil date")
        try:
            parsed = date.fromisoformat(self.effective_from)
        except ValueError as error:
            raise ValueError("effective-from must be an exact ISO civil date") from error
        if parsed.isoformat() != self.effective_from:
            raise ValueError("effective-from must be an exact ISO civil date")

    def has_started_on(self, on_date: date) -> bool:
        EffectiveFrom.__post_init__(self)
        if type(on_date) is not date:
            raise ValueError("effective-from comparison requires an exact civil date")
        return on_date >= date.fromisoformat(self.effective_from)


@dataclass(frozen=True, slots=True)
class DefinitionV2:
    term: str
    relation: str
    meaning: str
    scope: tuple[str, ...] = ()
    conditions: tuple[str, ...] = ()
    exceptions: tuple[str, ...] = ()
    temporal: tuple[str, ...] = ()
    kind: str = field(default="definition", init=False)

    def __post_init__(self):
        for value in (self.term, self.meaning):
            _atom(value)
        if type(self.relation) is not str or self.relation not in {"means", "includes", "excludes"}:
            raise ValueError("definition relation must not be a deontic modality")
        for value in (self.scope, self.conditions, self.exceptions, self.temporal):
            _atoms(value)


@dataclass(frozen=True, slots=True)
class PolicyV2:
    authority: str
    stance: str
    objectives: tuple[str, ...]
    scope: tuple[str, ...] = ()
    conditions: tuple[str, ...] = ()
    exceptions: tuple[str, ...] = ()
    temporal: tuple[str, ...] = ()
    kind: str = field(default="policy", init=False)

    def __post_init__(self):
        _atom(self.authority)
        if type(self.stance) is not str or self.stance not in {"supports", "declares_policy"}:
            raise ValueError("policy stance must not be an obligation or permission")
        _atoms(self.objectives, nonempty=True)
        for value in (self.scope, self.conditions, self.exceptions, self.temporal):
            _atoms(value)


@dataclass(frozen=True, slots=True)
class NormV2:
    modality: str
    actor: str
    action: str
    object: str
    scope: tuple[str, ...] = ()
    conditions: tuple[str, ...] = ()
    exceptions: tuple[str, ...] = ()
    temporal: tuple[str | TemporalDeadline | EffectiveFrom, ...] = ()
    kind: str = field(default="norm", init=False)

    def __post_init__(self):
        if type(self.modality) is not str or self.modality not in {"O", "P", "F"}:
            raise ValueError("norm requires an explicit O/P/F modality")
        for value in (self.actor, self.action, self.object):
            _atom(value)
        for value in (self.scope, self.conditions, self.exceptions):
            _atoms(value)
        if type(self.temporal) is not tuple or len(self.temporal) > MAX_STATEMENTS:
            raise ValueError("IR temporal collections must be bounded immutable tuples")
        effective_dates = 0
        for temporal in self.temporal:
            if type(temporal) is str:
                _atom(temporal)
            elif type(temporal) is EffectiveFrom:
                EffectiveFrom.__post_init__(temporal)
                effective_dates += 1
            else:
                if type(temporal) is not TemporalDeadline:
                    raise ValueError("literal temporal atom, typed deadline or effective-from required")
                TemporalDeadline.__post_init__(temporal)
        if effective_dates > 1:
            raise ValueError("a norm may have at most one explicit effective-from date")


_KINDS = {"definition": DefinitionV2, "policy": PolicyV2, "norm": NormV2}
_COLLECTIONS = frozenset({"scope", "conditions", "exceptions", "temporal", "objectives"})


@dataclass(frozen=True, slots=True)
class ExtendedLegalIR:
    statements: tuple[DefinitionV2 | PolicyV2 | NormV2, ...]
    schema: ClassVar[str] = EXTENDED_IR_SCHEMA

    def __post_init__(self):
        if type(self.statements) is not tuple or not 1 <= len(self.statements) <= MAX_STATEMENTS:
            raise ValueError("IR needs a bounded nonempty tuple of statements")
        has_deadline = False
        has_effective_date = False
        for statement in self.statements:
            if type(statement) not in _KINDS.values():
                raise ValueError("unsupported statement type")
            # Recheck even objects produced through object.__new__/object.__setattr__.
            type(statement).__post_init__(statement)
            if statement.kind not in _KINDS or _KINDS[statement.kind] is not type(statement):
                raise ValueError("statement discriminator differs from type")
            if type(statement) is NormV2:
                if any(type(temporal) is TemporalDeadline for temporal in statement.temporal):
                    has_deadline = True
                if any(type(temporal) is EffectiveFrom for temporal in statement.temporal):
                    has_effective_date = True
        if has_effective_date != (self.schema == EFFECTIVE_DATE_IR_SCHEMA):
            raise ValueError("effective-from inventory differs from the selected IR schema")
        if self.schema != EFFECTIVE_DATE_IR_SCHEMA and has_deadline != (self.schema == EXTENDED_DEADLINE_IR_SCHEMA):
            raise ValueError("typed deadline inventory differs from the selected IR schema")

    def to_dict(self) -> dict:
        ExtendedLegalIR.__post_init__(self)
        statements = []
        for statement in self.statements:
            value = asdict(statement)
            statements.append({key: list(item) if isinstance(item, tuple) else item
                               for key, item in value.items()})
        return {"schema": self.schema, "statements": statements}

    @classmethod
    def from_dict(cls, value: dict) -> ExtendedLegalIR:
        if (type(value) is not dict or set(value) != {"schema", "statements"}
                or type(value["schema"]) is not str):
            raise ValueError("unknown IR schema or source-bearing extra field")
        ir_kind = {EXTENDED_IR_SCHEMA: ExtendedLegalIR,
                   EXTENDED_DEADLINE_IR_SCHEMA: ExtendedDeadlineLegalIR,
                   EFFECTIVE_DATE_IR_SCHEMA: ExtendedEffectiveDateLegalIR}.get(value["schema"])
        if ir_kind is None or (cls is not ExtendedLegalIR and cls.schema != value["schema"]):
            raise ValueError("unknown or mismatched extended IR schema")
        if type(value["statements"]) is not list or not 1 <= len(value["statements"]) <= MAX_STATEMENTS:
            raise ValueError("invalid statement inventory")
        statements = []
        for record in value["statements"]:
            if type(record) is not dict or type(record.get("kind")) is not str:
                raise ValueError("statement discriminator missing")
            kind = _KINDS.get(record["kind"])
            if kind is None or set(record) != {item.name for item in fields(kind)}:
                raise ValueError("unknown statement fields")
            arguments = {key: item for key, item in record.items() if key != "kind"}
            for key in arguments.keys() & _COLLECTIONS:
                if type(arguments[key]) is not list or len(arguments[key]) > MAX_STATEMENTS:
                    raise ValueError("wire atom collections must be bounded lists")
                arguments[key] = tuple(arguments[key])
            if kind is NormV2 and ir_kind in (ExtendedDeadlineLegalIR, ExtendedEffectiveDateLegalIR):
                temporal = []
                for item in arguments["temporal"]:
                    if type(item) is str:
                        temporal.append(item)
                    elif (ir_kind is ExtendedEffectiveDateLegalIR and type(item) is dict
                          and set(item) == {"effective_from"}):
                        temporal.append(EffectiveFrom(item["effective_from"]))
                    else:
                        temporal.append(TemporalDeadline.from_dict(item))
                arguments["temporal"] = tuple(temporal)
            statements.append(kind(**arguments))
        return (ir_kind if cls is ExtendedLegalIR else cls)(tuple(statements))


@dataclass(frozen=True, slots=True)
class ExtendedDeadlineLegalIR(ExtendedLegalIR):
    """The existing surface IR with at least one explicit typed normative deadline."""

    schema: ClassVar[str] = EXTENDED_DEADLINE_IR_SCHEMA


@dataclass(frozen=True, slots=True)
class ExtendedEffectiveDateLegalIR(ExtendedLegalIR):
    """The surface IR with an explicit effective-from; deadlines may coexist."""

    schema: ClassVar[str] = EFFECTIVE_DATE_IR_SCHEMA
