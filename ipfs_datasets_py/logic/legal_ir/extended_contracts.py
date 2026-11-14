"""Opt-in, source-withheld legal surface IR; not the measured canonical v1 IR.

Definitions and policy declarations are not deontic modalities. Literal slots
remain natural-language atoms: this representation is a structured candidate,
not a formal proof or a claim that those atoms have been logically interpreted.
Lineage belongs to the compilation receipt, not to the decompiler's input.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from typing import ClassVar

from ..TDFOL.compiler_repairs import TemporalDeadline


EXTENDED_IR_SCHEMA = "legal-surface-ir/v2"
EXTENDED_DEADLINE_IR_SCHEMA = "legal-surface-ir-with-typed-deadlines/v1"
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
    temporal: tuple[str | TemporalDeadline, ...] = ()
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
        for temporal in self.temporal:
            if type(temporal) is str:
                _atom(temporal)
            else:
                if type(temporal) is not TemporalDeadline:
                    raise ValueError("literal temporal atom or typed deadline required")
                TemporalDeadline.__post_init__(temporal)


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
        for statement in self.statements:
            if type(statement) not in _KINDS.values():
                raise ValueError("unsupported statement type")
            # Recheck even objects produced through object.__new__/object.__setattr__.
            type(statement).__post_init__(statement)
            if statement.kind not in _KINDS or _KINDS[statement.kind] is not type(statement):
                raise ValueError("statement discriminator differs from type")
            if type(statement) is NormV2 and any(type(temporal) is TemporalDeadline for temporal in statement.temporal):
                has_deadline = True
        if has_deadline != (self.schema == EXTENDED_DEADLINE_IR_SCHEMA):
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
                   EXTENDED_DEADLINE_IR_SCHEMA: ExtendedDeadlineLegalIR}.get(value["schema"])
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
            if kind is NormV2 and ir_kind is ExtendedDeadlineLegalIR:
                arguments["temporal"] = tuple(
                    item if type(item) is str else TemporalDeadline.from_dict(item)
                    for item in arguments["temporal"])
            statements.append(kind(**arguments))
        return (ir_kind if cls is ExtendedLegalIR else cls)(tuple(statements))


@dataclass(frozen=True, slots=True)
class ExtendedDeadlineLegalIR(ExtendedLegalIR):
    """The existing surface IR with at least one explicit typed normative deadline."""

    schema: ClassVar[str] = EXTENDED_DEADLINE_IR_SCHEMA
