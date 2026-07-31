"""Typed, provider-neutral symbolic cryptographic-protocol semantics.

``ProtocolIR`` describes a symbolic protocol above any Tamarin, ProVerif, or
other backend syntax.  It records the protocol's declarations, threat model,
rewrite facts, events, and claims, while deliberately containing no solver
request, execution result, or proof verdict.

Every declaration, assumption, fact, event, and claim is bound to exact source
bytes through the shared IR provenance types.  Terms are checked against the
declared sorts and function signatures.  The equational-theory vocabulary is
closed: callers must select a supported theory and cannot silently smuggle an
unknown theory through an extension string.
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

PROTOCOL_IR_INTERFACE: Final = "ProtocolIR@1"
PROTOCOL_IR_SCHEMA_VERSION: Final = "protocol-ir/v1"
PROTOCOL_IR_IDENTITY_DOMAIN: Final = "logic.software-verification.protocol"

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/+@-]{0,255}$")
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


class ProtocolValidationError(ValueError):
    """Raised when symbolic protocol semantics are malformed or ambiguous."""


class _SourceMapped(Protocol):
    @property
    def source_ref_ids(self) -> tuple[str, ...]: ...

    @property
    def span_ids(self) -> tuple[str, ...]: ...


class SortKind(StrEnum):
    """Semantic category of a protocol sort."""

    AGENT = "agent"
    BOOLEAN = "boolean"
    DATA = "data"
    KEY = "key"
    MESSAGE = "message"
    NONCE = "nonce"


class FreshNameKind(StrEnum):
    """How a freshly generated value is used."""

    EPHEMERAL_SECRET = "ephemeral_secret"
    NONCE = "nonce"
    RANDOM = "random"
    SESSION_ID = "session_id"


class KeyKind(StrEnum):
    """Symbolic key category."""

    PRIVATE = "private"
    PUBLIC = "public"
    SHARED_SECRET = "shared_secret"
    SYMMETRIC = "symmetric"


class FunctionKind(StrEnum):
    """Whether a symbolic function builds or reduces a message."""

    CONSTRUCTOR = "constructor"
    DESTRUCTOR = "destructor"


class EquationalTheory(StrEnum):
    """Closed set of equational theories understood by ``ProtocolIR@1``."""

    FREE = "free"
    PAIRING = "pairing"
    SYMMETRIC_ENCRYPTION = "symmetric_encryption"
    ASYMMETRIC_ENCRYPTION = "asymmetric_encryption"
    SIGNATURES = "signatures"
    HASHING = "hashing"


class ChannelSecurity(StrEnum):
    """Guarantees assumed of a protocol channel."""

    PUBLIC = "public"
    AUTHENTICATED = "authenticated"
    CONFIDENTIAL = "confidential"
    SECURE = "secure"


class AdversaryAccess(StrEnum):
    """Adversary power over traffic on a channel."""

    NONE = "none"
    OBSERVE = "observe"
    INJECT = "inject"
    CONTROL = "control"


class AdversaryKind(StrEnum):
    """Symbolic threat model."""

    NONE = "none"
    PASSIVE = "passive"
    DOLEV_YAO = "dolev_yao"


class AdversaryCapability(StrEnum):
    """Primitive symbolic powers granted to the adversary."""

    COMPOSE = "compose"
    DECOMPOSE = "decompose"
    DROP = "drop"
    INJECT = "inject"
    INTERCEPT = "intercept"
    REPLAY = "replay"


class EventPhase(StrEnum):
    """Conventional protocol-event phase."""

    BEGIN = "begin"
    ACCEPT = "accept"
    END = "end"
    REJECT = "reject"
    SIGNAL = "signal"


class ProtocolClaimKind(StrEnum):
    """Security questions kept distinct in the semantic model."""

    SECRECY = "secrecy"
    REACHABILITY = "reachability"
    AUTHENTICATION = "authentication"
    CORRESPONDENCE = "correspondence"
    EQUIVALENCE = "equivalence"


class CorrespondenceKind(StrEnum):
    """Multiplicity promised by an event correspondence."""

    NON_INJECTIVE = "non_injective"
    INJECTIVE = "injective"


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
        raise ProtocolValidationError(
            f"{label} must be {qualifier}non-empty trimmed string without NUL bytes"
        )
    return value


def _identifier(value: object, label: str) -> str:
    result = _text(value, label)
    if not _ID_RE.fullmatch(result):
        raise ProtocolValidationError(f"{label} must be a stable identifier")
    return result


def _enum(value: object, enum_type: type[StrEnum], label: str) -> Any:
    try:
        return value if isinstance(value, enum_type) else enum_type(value)
    except (TypeError, ValueError) as error:
        choices = ", ".join(repr(member.value) for member in enum_type)
        raise ProtocolValidationError(f"{label} must be one of {choices}") from error


def _sequence(value: object, label: str) -> Sequence[Any]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise ProtocolValidationError(f"{label} must be a sequence")
    return value


def _identifiers(values: object, label: str, *, sort: bool = True) -> tuple[str, ...]:
    result = tuple(
        _identifier(item, f"{label} item") for item in _sequence(values, label)
    )
    if len(result) != len(set(result)):
        raise ProtocolValidationError(f"{label} must not contain duplicates")
    return tuple(sorted(result)) if sort else result


def _enums(
    values: object,
    enum_type: type[StrEnum],
    label: str,
) -> tuple[Any, ...]:
    result = tuple(
        _enum(item, enum_type, f"{label} item") for item in _sequence(values, label)
    )
    if len(result) != len(set(result)):
        raise ProtocolValidationError(f"{label} must not contain duplicates")
    return tuple(sorted(result, key=lambda item: item.value))


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ProtocolValidationError(f"{label} must be a mapping")
    return value


def _frozen(value: Mapping[str, Any] | FrozenMap, label: str) -> FrozenMap:
    try:
        return value if isinstance(value, FrozenMap) else FrozenMap(value)
    except (TypeError, ValueError) as error:
        raise ProtocolValidationError(
            f"{label} must contain immutable JSON-compatible data"
        ) from error


def _reject_unknown(
    value: Mapping[str, Any], allowed: frozenset[str], label: str
) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ProtocolValidationError(
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
        raise ProtocolValidationError(
            f"{owner} must be source mapped with source_ref_ids or span_ids"
        )
    return sources, spans


def _source_dict(item: _SourceMapped) -> dict[str, Any]:
    return {
        "source_ref_ids": list(item.source_ref_ids),
        "span_ids": list(item.span_ids),
    }


def _source_values(
    value: Mapping[str, Any],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    return (
        tuple(value.get("source_ref_ids", value.get("source_refs", ()))),
        tuple(value.get("span_ids", ())),
    )


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
        raise ProtocolValidationError(
            f"{label} contains observational keys {sorted(offending)}; "
            "put runtime output in observations"
        )


@dataclass(frozen=True, slots=True)
class ProtocolTerm:
    """A typed atom or function application in the symbolic term algebra."""

    sort: str
    symbol_id: str = ""
    function_id: str = ""
    arguments: tuple[ProtocolTerm, ...] = ()
    literal: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "sort", _identifier(self.sort, "term.sort"))
        object.__setattr__(
            self,
            "arguments",
            tuple(
                item
                if isinstance(item, ProtocolTerm)
                else ProtocolTerm.from_dict(_mapping(item, "term argument"))
                for item in _sequence(self.arguments, "term.arguments")
            ),
        )
        forms = sum(bool(item) for item in (self.symbol_id, self.function_id, self.literal))
        if forms != 1:
            raise ProtocolValidationError(
                "a term must contain exactly one of symbol_id, function_id, or literal"
            )
        if self.symbol_id:
            object.__setattr__(
                self, "symbol_id", _identifier(self.symbol_id, "term.symbol_id")
            )
            if self.arguments:
                raise ProtocolValidationError("an atomic symbol term cannot have arguments")
        elif self.function_id:
            object.__setattr__(
                self, "function_id", _identifier(self.function_id, "term.function_id")
            )
        else:
            object.__setattr__(self, "literal", _text(self.literal, "term.literal"))
            if self.arguments:
                raise ProtocolValidationError("a literal term cannot have arguments")

    @classmethod
    def symbol(cls, symbol_id: str, sort: str) -> ProtocolTerm:
        return cls(sort=sort, symbol_id=symbol_id)

    @classmethod
    def application(
        cls,
        function_id: str,
        arguments: Sequence[ProtocolTerm],
        sort: str,
    ) -> ProtocolTerm:
        return cls(sort=sort, function_id=function_id, arguments=tuple(arguments))

    def to_dict(self) -> dict[str, Any]:
        return {
            "arguments": [item.to_dict() for item in self.arguments],
            "function_id": self.function_id,
            "literal": self.literal,
            "sort": self.sort,
            "symbol_id": self.symbol_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> ProtocolTerm:
        value = _mapping(value, "term")
        _reject_unknown(
            value,
            frozenset({"sort", "symbol_id", "function_id", "arguments", "literal"}),
            "term",
        )
        return cls(
            sort=value.get("sort", ""),
            symbol_id=value.get("symbol_id", ""),
            function_id=value.get("function_id", ""),
            arguments=tuple(value.get("arguments", ())),
            literal=value.get("literal", ""),
        )


@dataclass(frozen=True, slots=True)
class ProtocolSort:
    """A source-grounded sort declaration."""

    sort_id: str
    name: str
    kind: SortKind | str
    source_ref_ids: tuple[str, ...] = ()
    span_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        sources, spans = _source_map(
            self.source_ref_ids, self.span_ids, owner="ProtocolSort"
        )
        object.__setattr__(self, "sort_id", _identifier(self.sort_id, "sort_id"))
        object.__setattr__(self, "name", _text(self.name, "sort.name"))
        object.__setattr__(self, "kind", _enum(self.kind, SortKind, "sort.kind"))
        object.__setattr__(self, "source_ref_ids", sources)
        object.__setattr__(self, "span_ids", spans)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "name": self.name,
            "sort_id": self.sort_id,
            **_source_dict(self),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> ProtocolSort:
        value = _mapping(value, "sort")
        _reject_unknown(
            value,
            frozenset(
                {"sort_id", "name", "kind", "source_ref_ids", "source_refs", "span_ids"}
            ),
            "sort",
        )
        sources, spans = _source_values(value)
        return cls(
            sort_id=value.get("sort_id", ""),
            name=value.get("name", ""),
            kind=value.get("kind", ""),
            source_ref_ids=sources,
            span_ids=spans,
        )


@dataclass(frozen=True, slots=True)
class ProtocolVariable:
    """A typed symbolic variable, optionally scoped to one role."""

    variable_id: str
    name: str
    sort: str
    role_id: str = ""
    source_ref_ids: tuple[str, ...] = ()
    span_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        sources, spans = _source_map(
            self.source_ref_ids, self.span_ids, owner="ProtocolVariable"
        )
        object.__setattr__(
            self, "variable_id", _identifier(self.variable_id, "variable_id")
        )
        object.__setattr__(self, "name", _text(self.name, "variable.name"))
        object.__setattr__(self, "sort", _identifier(self.sort, "variable.sort"))
        if self.role_id:
            object.__setattr__(
                self, "role_id", _identifier(self.role_id, "variable.role_id")
            )
        object.__setattr__(self, "source_ref_ids", sources)
        object.__setattr__(self, "span_ids", spans)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "role_id": self.role_id,
            "sort": self.sort,
            "variable_id": self.variable_id,
            **_source_dict(self),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> ProtocolVariable:
        value = _mapping(value, "variable")
        _reject_unknown(
            value,
            frozenset(
                {
                    "variable_id",
                    "name",
                    "sort",
                    "role_id",
                    "source_ref_ids",
                    "source_refs",
                    "span_ids",
                }
            ),
            "variable",
        )
        sources, spans = _source_values(value)
        return cls(
            variable_id=value.get("variable_id", ""),
            name=value.get("name", ""),
            sort=value.get("sort", ""),
            role_id=value.get("role_id", ""),
            source_ref_ids=sources,
            span_ids=spans,
        )


@dataclass(frozen=True, slots=True)
class ProtocolRole:
    """A protocol participant and its typed local variables."""

    role_id: str
    name: str
    parameter_ids: tuple[str, ...] = ()
    source_ref_ids: tuple[str, ...] = ()
    span_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        sources, spans = _source_map(
            self.source_ref_ids, self.span_ids, owner="ProtocolRole"
        )
        object.__setattr__(self, "role_id", _identifier(self.role_id, "role_id"))
        object.__setattr__(self, "name", _text(self.name, "role.name"))
        object.__setattr__(
            self,
            "parameter_ids",
            _identifiers(self.parameter_ids, "role.parameter_ids"),
        )
        object.__setattr__(self, "source_ref_ids", sources)
        object.__setattr__(self, "span_ids", spans)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "parameter_ids": list(self.parameter_ids),
            "role_id": self.role_id,
            **_source_dict(self),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> ProtocolRole:
        value = _mapping(value, "role")
        _reject_unknown(
            value,
            frozenset(
                {
                    "role_id",
                    "name",
                    "parameter_ids",
                    "source_ref_ids",
                    "source_refs",
                    "span_ids",
                }
            ),
            "role",
        )
        sources, spans = _source_values(value)
        return cls(
            role_id=value.get("role_id", ""),
            name=value.get("name", ""),
            parameter_ids=tuple(value.get("parameter_ids", ())),
            source_ref_ids=sources,
            span_ids=spans,
        )


@dataclass(frozen=True, slots=True)
class FreshName:
    """A typed value generated freshly by a role."""

    name_id: str
    name: str
    sort: str
    generated_by_role_id: str
    kind: FreshNameKind | str = FreshNameKind.NONCE
    source_ref_ids: tuple[str, ...] = ()
    span_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        sources, spans = _source_map(
            self.source_ref_ids, self.span_ids, owner="FreshName"
        )
        object.__setattr__(self, "name_id", _identifier(self.name_id, "name_id"))
        object.__setattr__(self, "name", _text(self.name, "fresh_name.name"))
        object.__setattr__(self, "sort", _identifier(self.sort, "fresh_name.sort"))
        object.__setattr__(
            self,
            "generated_by_role_id",
            _identifier(self.generated_by_role_id, "generated_by_role_id"),
        )
        object.__setattr__(
            self, "kind", _enum(self.kind, FreshNameKind, "fresh_name.kind")
        )
        object.__setattr__(self, "source_ref_ids", sources)
        object.__setattr__(self, "span_ids", spans)

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_by_role_id": self.generated_by_role_id,
            "kind": self.kind.value,
            "name": self.name,
            "name_id": self.name_id,
            "sort": self.sort,
            **_source_dict(self),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> FreshName:
        value = _mapping(value, "fresh name")
        _reject_unknown(
            value,
            frozenset(
                {
                    "name_id",
                    "name",
                    "sort",
                    "generated_by_role_id",
                    "kind",
                    "source_ref_ids",
                    "source_refs",
                    "span_ids",
                }
            ),
            "fresh name",
        )
        sources, spans = _source_values(value)
        return cls(
            name_id=value.get("name_id", ""),
            name=value.get("name", ""),
            sort=value.get("sort", ""),
            generated_by_role_id=value.get("generated_by_role_id", ""),
            kind=value.get("kind", FreshNameKind.NONCE.value),
            source_ref_ids=sources,
            span_ids=spans,
        )


@dataclass(frozen=True, slots=True)
class ProtocolKey:
    """A typed key declaration with explicit ownership and key pairing."""

    key_id: str
    name: str
    sort: str
    kind: KeyKind | str
    owner_role_ids: tuple[str, ...]
    peer_key_id: str = ""
    source_ref_ids: tuple[str, ...] = ()
    span_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        sources, spans = _source_map(
            self.source_ref_ids, self.span_ids, owner="ProtocolKey"
        )
        object.__setattr__(self, "key_id", _identifier(self.key_id, "key_id"))
        object.__setattr__(self, "name", _text(self.name, "key.name"))
        object.__setattr__(self, "sort", _identifier(self.sort, "key.sort"))
        object.__setattr__(self, "kind", _enum(self.kind, KeyKind, "key.kind"))
        owners = _identifiers(self.owner_role_ids, "key.owner_role_ids")
        if not owners:
            raise ProtocolValidationError("key.owner_role_ids must not be empty")
        object.__setattr__(self, "owner_role_ids", owners)
        if self.peer_key_id:
            object.__setattr__(
                self, "peer_key_id", _identifier(self.peer_key_id, "peer_key_id")
            )
        object.__setattr__(self, "source_ref_ids", sources)
        object.__setattr__(self, "span_ids", spans)

    def to_dict(self) -> dict[str, Any]:
        return {
            "key_id": self.key_id,
            "kind": self.kind.value,
            "name": self.name,
            "owner_role_ids": list(self.owner_role_ids),
            "peer_key_id": self.peer_key_id,
            "sort": self.sort,
            **_source_dict(self),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> ProtocolKey:
        value = _mapping(value, "key")
        _reject_unknown(
            value,
            frozenset(
                {
                    "key_id",
                    "name",
                    "sort",
                    "kind",
                    "owner_role_ids",
                    "peer_key_id",
                    "source_ref_ids",
                    "source_refs",
                    "span_ids",
                }
            ),
            "key",
        )
        sources, spans = _source_values(value)
        return cls(
            key_id=value.get("key_id", ""),
            name=value.get("name", ""),
            sort=value.get("sort", ""),
            kind=value.get("kind", ""),
            owner_role_ids=tuple(value.get("owner_role_ids", ())),
            peer_key_id=value.get("peer_key_id", ""),
            source_ref_ids=sources,
            span_ids=spans,
        )


@dataclass(frozen=True, slots=True)
class ProtocolFunction:
    """A typed constructor or destructor in a supported theory."""

    function_id: str
    name: str
    parameter_sorts: tuple[str, ...]
    result_sort: str
    kind: FunctionKind | str
    theory: EquationalTheory | str = EquationalTheory.FREE
    source_ref_ids: tuple[str, ...] = ()
    span_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        sources, spans = _source_map(
            self.source_ref_ids, self.span_ids, owner="ProtocolFunction"
        )
        object.__setattr__(
            self, "function_id", _identifier(self.function_id, "function_id")
        )
        object.__setattr__(self, "name", _text(self.name, "function.name"))
        object.__setattr__(
            self,
            "parameter_sorts",
            tuple(
                _identifier(item, "function parameter sort")
                for item in _sequence(
                    self.parameter_sorts, "function.parameter_sorts"
                )
            ),
        )
        object.__setattr__(
            self, "result_sort", _identifier(self.result_sort, "function.result_sort")
        )
        object.__setattr__(
            self, "kind", _enum(self.kind, FunctionKind, "function.kind")
        )
        object.__setattr__(
            self, "theory", _enum(self.theory, EquationalTheory, "function.theory")
        )
        object.__setattr__(self, "source_ref_ids", sources)
        object.__setattr__(self, "span_ids", spans)

    def to_dict(self) -> dict[str, Any]:
        return {
            "function_id": self.function_id,
            "kind": self.kind.value,
            "name": self.name,
            "parameter_sorts": list(self.parameter_sorts),
            "result_sort": self.result_sort,
            "theory": self.theory.value,
            **_source_dict(self),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> ProtocolFunction:
        value = _mapping(value, "function")
        _reject_unknown(
            value,
            frozenset(
                {
                    "function_id",
                    "name",
                    "parameter_sorts",
                    "result_sort",
                    "kind",
                    "theory",
                    "source_ref_ids",
                    "source_refs",
                    "span_ids",
                }
            ),
            "function",
        )
        sources, spans = _source_values(value)
        return cls(
            function_id=value.get("function_id", ""),
            name=value.get("name", ""),
            parameter_sorts=tuple(value.get("parameter_sorts", ())),
            result_sort=value.get("result_sort", ""),
            kind=value.get("kind", ""),
            theory=value.get("theory", EquationalTheory.FREE.value),
            source_ref_ids=sources,
            span_ids=spans,
        )


@dataclass(frozen=True, slots=True)
class TrustAssumption:
    """An explicit trust premise; its presence is not proof of the premise."""

    assumption_id: str
    statement: str
    trusted_role_ids: tuple[str, ...] = ()
    trusted_key_ids: tuple[str, ...] = ()
    source_ref_ids: tuple[str, ...] = ()
    span_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        sources, spans = _source_map(
            self.source_ref_ids, self.span_ids, owner="TrustAssumption"
        )
        object.__setattr__(
            self,
            "assumption_id",
            _identifier(self.assumption_id, "assumption_id"),
        )
        object.__setattr__(
            self, "statement", _text(self.statement, "trust_assumption.statement")
        )
        object.__setattr__(
            self,
            "trusted_role_ids",
            _identifiers(self.trusted_role_ids, "trusted_role_ids"),
        )
        object.__setattr__(
            self,
            "trusted_key_ids",
            _identifiers(self.trusted_key_ids, "trusted_key_ids"),
        )
        if not self.trusted_role_ids and not self.trusted_key_ids:
            raise ProtocolValidationError(
                "a trust assumption must identify a trusted role or key"
            )
        object.__setattr__(self, "source_ref_ids", sources)
        object.__setattr__(self, "span_ids", spans)

    def to_dict(self) -> dict[str, Any]:
        return {
            "assumption_id": self.assumption_id,
            "statement": self.statement,
            "trusted_key_ids": list(self.trusted_key_ids),
            "trusted_role_ids": list(self.trusted_role_ids),
            **_source_dict(self),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> TrustAssumption:
        value = _mapping(value, "trust assumption")
        _reject_unknown(
            value,
            frozenset(
                {
                    "assumption_id",
                    "statement",
                    "trusted_role_ids",
                    "trusted_key_ids",
                    "source_ref_ids",
                    "source_refs",
                    "span_ids",
                }
            ),
            "trust assumption",
        )
        sources, spans = _source_values(value)
        return cls(
            assumption_id=value.get("assumption_id", ""),
            statement=value.get("statement", ""),
            trusted_role_ids=tuple(value.get("trusted_role_ids", ())),
            trusted_key_ids=tuple(value.get("trusted_key_ids", ())),
            source_ref_ids=sources,
            span_ids=spans,
        )


@dataclass(frozen=True, slots=True)
class ProtocolChannel:
    """A channel with explicit guarantees and adversary access."""

    channel_id: str
    name: str
    security: ChannelSecurity | str
    adversary_access: AdversaryAccess | str
    assumption_ids: tuple[str, ...] = ()
    source_ref_ids: tuple[str, ...] = ()
    span_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        sources, spans = _source_map(
            self.source_ref_ids, self.span_ids, owner="ProtocolChannel"
        )
        object.__setattr__(
            self, "channel_id", _identifier(self.channel_id, "channel_id")
        )
        object.__setattr__(self, "name", _text(self.name, "channel.name"))
        object.__setattr__(
            self,
            "security",
            _enum(self.security, ChannelSecurity, "channel.security"),
        )
        object.__setattr__(
            self,
            "adversary_access",
            _enum(
                self.adversary_access,
                AdversaryAccess,
                "channel.adversary_access",
            ),
        )
        object.__setattr__(
            self,
            "assumption_ids",
            _identifiers(self.assumption_ids, "channel.assumption_ids"),
        )
        if (
            self.security is ChannelSecurity.SECURE
            and self.adversary_access is not AdversaryAccess.NONE
        ):
            raise ProtocolValidationError(
                "a secure channel must deny adversary access"
            )
        object.__setattr__(self, "source_ref_ids", sources)
        object.__setattr__(self, "span_ids", spans)

    def to_dict(self) -> dict[str, Any]:
        return {
            "adversary_access": self.adversary_access.value,
            "assumption_ids": list(self.assumption_ids),
            "channel_id": self.channel_id,
            "name": self.name,
            "security": self.security.value,
            **_source_dict(self),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> ProtocolChannel:
        value = _mapping(value, "channel")
        _reject_unknown(
            value,
            frozenset(
                {
                    "channel_id",
                    "name",
                    "security",
                    "adversary_access",
                    "assumption_ids",
                    "source_ref_ids",
                    "source_refs",
                    "span_ids",
                }
            ),
            "channel",
        )
        sources, spans = _source_values(value)
        return cls(
            channel_id=value.get("channel_id", ""),
            name=value.get("name", ""),
            security=value.get("security", ""),
            adversary_access=value.get("adversary_access", ""),
            assumption_ids=tuple(value.get("assumption_ids", ())),
            source_ref_ids=sources,
            span_ids=spans,
        )


@dataclass(frozen=True, slots=True)
class ProtocolMessage:
    """One typed role-to-role send over a declared channel."""

    message_id: str
    name: str
    payload: ProtocolTerm
    sender_role_id: str
    receiver_role_ids: tuple[str, ...]
    channel_id: str
    source_ref_ids: tuple[str, ...] = ()
    span_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        sources, spans = _source_map(
            self.source_ref_ids, self.span_ids, owner="ProtocolMessage"
        )
        object.__setattr__(
            self, "message_id", _identifier(self.message_id, "message_id")
        )
        object.__setattr__(self, "name", _text(self.name, "message.name"))
        object.__setattr__(
            self,
            "payload",
            self.payload
            if isinstance(self.payload, ProtocolTerm)
            else ProtocolTerm.from_dict(_mapping(self.payload, "message.payload")),
        )
        object.__setattr__(
            self,
            "sender_role_id",
            _identifier(self.sender_role_id, "sender_role_id"),
        )
        receivers = _identifiers(
            self.receiver_role_ids, "message.receiver_role_ids"
        )
        if not receivers:
            raise ProtocolValidationError(
                "message.receiver_role_ids must not be empty"
            )
        object.__setattr__(self, "receiver_role_ids", receivers)
        object.__setattr__(
            self, "channel_id", _identifier(self.channel_id, "message.channel_id")
        )
        object.__setattr__(self, "source_ref_ids", sources)
        object.__setattr__(self, "span_ids", spans)

    def to_dict(self) -> dict[str, Any]:
        return {
            "channel_id": self.channel_id,
            "message_id": self.message_id,
            "name": self.name,
            "payload": self.payload.to_dict(),
            "receiver_role_ids": list(self.receiver_role_ids),
            "sender_role_id": self.sender_role_id,
            **_source_dict(self),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> ProtocolMessage:
        value = _mapping(value, "message")
        _reject_unknown(
            value,
            frozenset(
                {
                    "message_id",
                    "name",
                    "payload",
                    "sender_role_id",
                    "receiver_role_ids",
                    "channel_id",
                    "source_ref_ids",
                    "source_refs",
                    "span_ids",
                }
            ),
            "message",
        )
        sources, spans = _source_values(value)
        return cls(
            message_id=value.get("message_id", ""),
            name=value.get("name", ""),
            payload=ProtocolTerm.from_dict(
                _mapping(value.get("payload", {}), "message.payload")
            ),
            sender_role_id=value.get("sender_role_id", ""),
            receiver_role_ids=tuple(value.get("receiver_role_ids", ())),
            channel_id=value.get("channel_id", ""),
            source_ref_ids=sources,
            span_ids=spans,
        )


@dataclass(frozen=True, slots=True)
class AdversaryKnowledge:
    """A source-grounded fact initially or conditionally known by the adversary."""

    knowledge_id: str
    term: ProtocolTerm
    available_after_event_ids: tuple[str, ...] = ()
    source_ref_ids: tuple[str, ...] = ()
    span_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        sources, spans = _source_map(
            self.source_ref_ids, self.span_ids, owner="AdversaryKnowledge"
        )
        object.__setattr__(
            self,
            "knowledge_id",
            _identifier(self.knowledge_id, "knowledge_id"),
        )
        object.__setattr__(
            self,
            "term",
            self.term
            if isinstance(self.term, ProtocolTerm)
            else ProtocolTerm.from_dict(_mapping(self.term, "knowledge.term")),
        )
        object.__setattr__(
            self,
            "available_after_event_ids",
            _identifiers(
                self.available_after_event_ids,
                "knowledge.available_after_event_ids",
            ),
        )
        object.__setattr__(self, "source_ref_ids", sources)
        object.__setattr__(self, "span_ids", spans)

    def to_dict(self) -> dict[str, Any]:
        return {
            "available_after_event_ids": list(self.available_after_event_ids),
            "knowledge_id": self.knowledge_id,
            "term": self.term.to_dict(),
            **_source_dict(self),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> AdversaryKnowledge:
        value = _mapping(value, "adversary knowledge")
        _reject_unknown(
            value,
            frozenset(
                {
                    "knowledge_id",
                    "term",
                    "available_after_event_ids",
                    "source_ref_ids",
                    "source_refs",
                    "span_ids",
                }
            ),
            "adversary knowledge",
        )
        sources, spans = _source_values(value)
        return cls(
            knowledge_id=value.get("knowledge_id", ""),
            term=ProtocolTerm.from_dict(
                _mapping(value.get("term", {}), "knowledge.term")
            ),
            available_after_event_ids=tuple(
                value.get("available_after_event_ids", ())
            ),
            source_ref_ids=sources,
            span_ids=spans,
        )


@dataclass(frozen=True, slots=True)
class ProtocolAdversary:
    """Explicit symbolic adversary model and compromise boundary."""

    adversary_id: str
    kind: AdversaryKind | str
    capabilities: tuple[AdversaryCapability | str, ...]
    knowledge: tuple[AdversaryKnowledge, ...] = ()
    compromised_role_ids: tuple[str, ...] = ()
    compromised_key_ids: tuple[str, ...] = ()
    source_ref_ids: tuple[str, ...] = ()
    span_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        sources, spans = _source_map(
            self.source_ref_ids, self.span_ids, owner="ProtocolAdversary"
        )
        object.__setattr__(
            self, "adversary_id", _identifier(self.adversary_id, "adversary_id")
        )
        object.__setattr__(
            self, "kind", _enum(self.kind, AdversaryKind, "adversary.kind")
        )
        capabilities = _enums(
            self.capabilities, AdversaryCapability, "adversary.capabilities"
        )
        if self.kind is AdversaryKind.NONE and capabilities:
            raise ProtocolValidationError(
                "an absent adversary cannot have capabilities"
            )
        if self.kind is AdversaryKind.PASSIVE and any(
            item
            in {
                AdversaryCapability.DROP,
                AdversaryCapability.INJECT,
                AdversaryCapability.REPLAY,
            }
            for item in capabilities
        ):
            raise ProtocolValidationError(
                "a passive adversary cannot drop, inject, or replay messages"
            )
        object.__setattr__(self, "capabilities", capabilities)
        object.__setattr__(
            self,
            "knowledge",
            tuple(
                sorted(
                    (
                        item
                        if isinstance(item, AdversaryKnowledge)
                        else AdversaryKnowledge.from_dict(
                            _mapping(item, "adversary knowledge")
                        )
                        for item in _sequence(
                            self.knowledge, "adversary.knowledge"
                        )
                    ),
                    key=lambda item: item.knowledge_id,
                )
            ),
        )
        object.__setattr__(
            self,
            "compromised_role_ids",
            _identifiers(
                self.compromised_role_ids, "adversary.compromised_role_ids"
            ),
        )
        object.__setattr__(
            self,
            "compromised_key_ids",
            _identifiers(
                self.compromised_key_ids, "adversary.compromised_key_ids"
            ),
        )
        if self.kind is AdversaryKind.NONE and (
            self.knowledge
            or self.compromised_role_ids
            or self.compromised_key_ids
        ):
            raise ProtocolValidationError(
                "an absent adversary cannot have knowledge or compromises"
            )
        object.__setattr__(self, "source_ref_ids", sources)
        object.__setattr__(self, "span_ids", spans)

    def to_dict(self) -> dict[str, Any]:
        return {
            "adversary_id": self.adversary_id,
            "capabilities": [item.value for item in self.capabilities],
            "compromised_key_ids": list(self.compromised_key_ids),
            "compromised_role_ids": list(self.compromised_role_ids),
            "kind": self.kind.value,
            "knowledge": [
                item.to_dict()
                for item in sorted(self.knowledge, key=lambda item: item.knowledge_id)
            ],
            **_source_dict(self),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> ProtocolAdversary:
        value = _mapping(value, "adversary")
        _reject_unknown(
            value,
            frozenset(
                {
                    "adversary_id",
                    "kind",
                    "capabilities",
                    "knowledge",
                    "compromised_role_ids",
                    "compromised_key_ids",
                    "source_ref_ids",
                    "source_refs",
                    "span_ids",
                }
            ),
            "adversary",
        )
        sources, spans = _source_values(value)
        return cls(
            adversary_id=value.get("adversary_id", ""),
            kind=value.get("kind", ""),
            capabilities=tuple(value.get("capabilities", ())),
            knowledge=tuple(value.get("knowledge", ())),
            compromised_role_ids=tuple(value.get("compromised_role_ids", ())),
            compromised_key_ids=tuple(value.get("compromised_key_ids", ())),
            source_ref_ids=sources,
            span_ids=spans,
        )


@dataclass(frozen=True, slots=True)
class RewriteFact:
    """A typed, oriented symbolic rewrite fact."""

    fact_id: str
    left: ProtocolTerm
    right: ProtocolTerm
    theory: EquationalTheory | str
    source_ref_ids: tuple[str, ...] = ()
    span_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        sources, spans = _source_map(
            self.source_ref_ids, self.span_ids, owner="RewriteFact"
        )
        object.__setattr__(self, "fact_id", _identifier(self.fact_id, "fact_id"))
        object.__setattr__(
            self,
            "left",
            self.left
            if isinstance(self.left, ProtocolTerm)
            else ProtocolTerm.from_dict(_mapping(self.left, "rewrite.left")),
        )
        object.__setattr__(
            self,
            "right",
            self.right
            if isinstance(self.right, ProtocolTerm)
            else ProtocolTerm.from_dict(_mapping(self.right, "rewrite.right")),
        )
        object.__setattr__(
            self, "theory", _enum(self.theory, EquationalTheory, "rewrite.theory")
        )
        if self.left.sort != self.right.sort:
            raise ProtocolValidationError(
                "rewrite facts must preserve the term sort"
            )
        object.__setattr__(self, "source_ref_ids", sources)
        object.__setattr__(self, "span_ids", spans)

    def to_dict(self) -> dict[str, Any]:
        return {
            "fact_id": self.fact_id,
            "left": self.left.to_dict(),
            "right": self.right.to_dict(),
            "theory": self.theory.value,
            **_source_dict(self),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> RewriteFact:
        value = _mapping(value, "rewrite fact")
        _reject_unknown(
            value,
            frozenset(
                {
                    "fact_id",
                    "left",
                    "right",
                    "theory",
                    "source_ref_ids",
                    "source_refs",
                    "span_ids",
                }
            ),
            "rewrite fact",
        )
        sources, spans = _source_values(value)
        return cls(
            fact_id=value.get("fact_id", ""),
            left=ProtocolTerm.from_dict(
                _mapping(value.get("left", {}), "rewrite.left")
            ),
            right=ProtocolTerm.from_dict(
                _mapping(value.get("right", {}), "rewrite.right")
            ),
            theory=value.get("theory", ""),
            source_ref_ids=sources,
            span_ids=spans,
        )


@dataclass(frozen=True, slots=True)
class ProtocolEvent:
    """A typed event used by reachability and correspondence claims."""

    event_id: str
    name: str
    role_id: str
    parameters: tuple[ProtocolTerm, ...] = ()
    phase: EventPhase | str = EventPhase.SIGNAL
    source_ref_ids: tuple[str, ...] = ()
    span_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        sources, spans = _source_map(
            self.source_ref_ids, self.span_ids, owner="ProtocolEvent"
        )
        object.__setattr__(self, "event_id", _identifier(self.event_id, "event_id"))
        object.__setattr__(self, "name", _text(self.name, "event.name"))
        object.__setattr__(self, "role_id", _identifier(self.role_id, "event.role_id"))
        object.__setattr__(
            self,
            "parameters",
            tuple(
                item
                if isinstance(item, ProtocolTerm)
                else ProtocolTerm.from_dict(_mapping(item, "event parameter"))
                for item in _sequence(self.parameters, "event.parameters")
            ),
        )
        object.__setattr__(
            self, "phase", _enum(self.phase, EventPhase, "event.phase")
        )
        object.__setattr__(self, "source_ref_ids", sources)
        object.__setattr__(self, "span_ids", spans)

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "name": self.name,
            "parameters": [item.to_dict() for item in self.parameters],
            "phase": self.phase.value,
            "role_id": self.role_id,
            **_source_dict(self),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> ProtocolEvent:
        value = _mapping(value, "event")
        _reject_unknown(
            value,
            frozenset(
                {
                    "event_id",
                    "name",
                    "role_id",
                    "parameters",
                    "phase",
                    "source_ref_ids",
                    "source_refs",
                    "span_ids",
                }
            ),
            "event",
        )
        sources, spans = _source_values(value)
        return cls(
            event_id=value.get("event_id", ""),
            name=value.get("name", ""),
            role_id=value.get("role_id", ""),
            parameters=tuple(value.get("parameters", ())),
            phase=value.get("phase", EventPhase.SIGNAL.value),
            source_ref_ids=sources,
            span_ids=spans,
        )


@dataclass(frozen=True, slots=True)
class ProtocolClaim:
    """A typed protocol question with kind-specific operands.

    The five operand groups are intentionally separate.  This prevents a
    reachability question from being serialized as a secrecy or equivalence
    question merely because a backend happens to use similar query syntax.
    """

    claim_id: str
    kind: ProtocolClaimKind | str
    statement: str
    secret_terms: tuple[ProtocolTerm, ...] = ()
    reachable_event_ids: tuple[str, ...] = ()
    antecedent_event_ids: tuple[str, ...] = ()
    consequent_event_ids: tuple[str, ...] = ()
    left_terms: tuple[ProtocolTerm, ...] = ()
    right_terms: tuple[ProtocolTerm, ...] = ()
    correspondence: CorrespondenceKind | str = CorrespondenceKind.NON_INJECTIVE
    assumption_ids: tuple[str, ...] = ()
    source_ref_ids: tuple[str, ...] = ()
    span_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        sources, spans = _source_map(
            self.source_ref_ids, self.span_ids, owner="ProtocolClaim"
        )
        object.__setattr__(self, "claim_id", _identifier(self.claim_id, "claim_id"))
        object.__setattr__(
            self, "kind", _enum(self.kind, ProtocolClaimKind, "claim.kind")
        )
        object.__setattr__(self, "statement", _text(self.statement, "claim.statement"))
        for name in ("secret_terms", "left_terms", "right_terms"):
            object.__setattr__(
                self,
                name,
                tuple(
                    item
                    if isinstance(item, ProtocolTerm)
                    else ProtocolTerm.from_dict(_mapping(item, f"claim.{name} item"))
                    for item in _sequence(getattr(self, name), f"claim.{name}")
                ),
            )
        for name in (
            "reachable_event_ids",
            "antecedent_event_ids",
            "consequent_event_ids",
            "assumption_ids",
        ):
            object.__setattr__(
                self,
                name,
                _identifiers(getattr(self, name), f"claim.{name}"),
            )
        object.__setattr__(
            self,
            "correspondence",
            _enum(
                self.correspondence,
                CorrespondenceKind,
                "claim.correspondence",
            ),
        )
        object.__setattr__(self, "source_ref_ids", sources)
        object.__setattr__(self, "span_ids", spans)
        self._validate_shape()

    def _validate_shape(self) -> None:
        populated = {
            "secret_terms": bool(self.secret_terms),
            "reachable_event_ids": bool(self.reachable_event_ids),
            "antecedent_event_ids": bool(self.antecedent_event_ids),
            "consequent_event_ids": bool(self.consequent_event_ids),
            "left_terms": bool(self.left_terms),
            "right_terms": bool(self.right_terms),
        }
        if self.kind is ProtocolClaimKind.SECRECY:
            valid = populated["secret_terms"] and not any(
                populated[name] for name in populated if name != "secret_terms"
            )
        elif self.kind is ProtocolClaimKind.REACHABILITY:
            valid = populated["reachable_event_ids"] and not any(
                populated[name]
                for name in populated
                if name != "reachable_event_ids"
            )
        elif self.kind in {
            ProtocolClaimKind.AUTHENTICATION,
            ProtocolClaimKind.CORRESPONDENCE,
        }:
            valid = (
                populated["antecedent_event_ids"]
                and populated["consequent_event_ids"]
                and not any(
                    populated[name]
                    for name in (
                        "secret_terms",
                        "reachable_event_ids",
                        "left_terms",
                        "right_terms",
                    )
                )
            )
        else:
            valid = (
                populated["left_terms"]
                and populated["right_terms"]
                and len(self.left_terms) == len(self.right_terms)
                and all(
                    left.sort == right.sort
                    for left, right in zip(
                        self.left_terms, self.right_terms, strict=True
                    )
                )
                and not any(
                    populated[name]
                    for name in (
                        "secret_terms",
                        "reachable_event_ids",
                        "antecedent_event_ids",
                        "consequent_event_ids",
                    )
                )
            )
        if not valid:
            raise ProtocolValidationError(
                f"{self.kind.value} claim has incompatible or missing operands"
            )
        if (
            self.kind
            not in {
                ProtocolClaimKind.AUTHENTICATION,
                ProtocolClaimKind.CORRESPONDENCE,
            }
            and self.correspondence is not CorrespondenceKind.NON_INJECTIVE
        ):
            raise ProtocolValidationError(
                "injective correspondence applies only to authentication or "
                "correspondence claims"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "antecedent_event_ids": list(self.antecedent_event_ids),
            "assumption_ids": list(self.assumption_ids),
            "claim_id": self.claim_id,
            "consequent_event_ids": list(self.consequent_event_ids),
            "correspondence": self.correspondence.value,
            "kind": self.kind.value,
            "left_terms": [item.to_dict() for item in self.left_terms],
            "reachable_event_ids": list(self.reachable_event_ids),
            "right_terms": [item.to_dict() for item in self.right_terms],
            "secret_terms": [item.to_dict() for item in self.secret_terms],
            "statement": self.statement,
            **_source_dict(self),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> ProtocolClaim:
        value = _mapping(value, "claim")
        _reject_unknown(
            value,
            frozenset(
                {
                    "claim_id",
                    "kind",
                    "statement",
                    "secret_terms",
                    "reachable_event_ids",
                    "antecedent_event_ids",
                    "consequent_event_ids",
                    "left_terms",
                    "right_terms",
                    "correspondence",
                    "assumption_ids",
                    "source_ref_ids",
                    "source_refs",
                    "span_ids",
                }
            ),
            "claim",
        )
        sources, spans = _source_values(value)
        return cls(
            claim_id=value.get("claim_id", ""),
            kind=value.get("kind", ""),
            statement=value.get("statement", ""),
            secret_terms=tuple(value.get("secret_terms", ())),
            reachable_event_ids=tuple(value.get("reachable_event_ids", ())),
            antecedent_event_ids=tuple(value.get("antecedent_event_ids", ())),
            consequent_event_ids=tuple(value.get("consequent_event_ids", ())),
            left_terms=tuple(value.get("left_terms", ())),
            right_terms=tuple(value.get("right_terms", ())),
            correspondence=value.get(
                "correspondence", CorrespondenceKind.NON_INJECTIVE.value
            ),
            assumption_ids=tuple(value.get("assumption_ids", ())),
            source_ref_ids=sources,
            span_ids=spans,
        )


@dataclass(frozen=True, slots=True)
class ProtocolIR:
    """Canonical, immutable, source-grounded symbolic protocol model."""

    sources: tuple[SourceRef, ...]
    sorts: tuple[ProtocolSort, ...]
    roles: tuple[ProtocolRole, ...]
    adversary: ProtocolAdversary
    spans: tuple[SourceSpan, ...] = ()
    variables: tuple[ProtocolVariable, ...] = ()
    fresh_names: tuple[FreshName, ...] = ()
    keys: tuple[ProtocolKey, ...] = ()
    functions: tuple[ProtocolFunction, ...] = ()
    trust_assumptions: tuple[TrustAssumption, ...] = ()
    channels: tuple[ProtocolChannel, ...] = ()
    messages: tuple[ProtocolMessage, ...] = ()
    rewrite_facts: tuple[RewriteFact, ...] = ()
    events: tuple[ProtocolEvent, ...] = ()
    claims: tuple[ProtocolClaim, ...] = ()
    equational_theories: tuple[EquationalTheory | str, ...] = (
        EquationalTheory.FREE,
    )
    metadata: FrozenMap = field(default_factory=FrozenMap)
    observations: FrozenMap = field(default_factory=FrozenMap)
    document_id: str = ""
    schema_version: str = PROTOCOL_IR_SCHEMA_VERSION

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
        record_types = {
            "sorts": (ProtocolSort, "sort_id"),
            "variables": (ProtocolVariable, "variable_id"),
            "roles": (ProtocolRole, "role_id"),
            "fresh_names": (FreshName, "name_id"),
            "keys": (ProtocolKey, "key_id"),
            "functions": (ProtocolFunction, "function_id"),
            "trust_assumptions": (TrustAssumption, "assumption_id"),
            "channels": (ProtocolChannel, "channel_id"),
            "messages": (ProtocolMessage, "message_id"),
            "rewrite_facts": (RewriteFact, "fact_id"),
            "events": (ProtocolEvent, "event_id"),
            "claims": (ProtocolClaim, "claim_id"),
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
        object.__setattr__(
            self,
            "adversary",
            self.adversary
            if isinstance(self.adversary, ProtocolAdversary)
            else ProtocolAdversary.from_dict(_mapping(self.adversary, "adversary")),
        )
        theories = _enums(
            self.equational_theories,
            EquationalTheory,
            "equational_theories",
        )
        if EquationalTheory.FREE not in theories:
            raise ProtocolValidationError(
                "equational_theories must explicitly include the free theory"
            )
        object.__setattr__(self, "equational_theories", theories)
        metadata = _frozen(self.metadata, "metadata")
        observations = _frozen(self.observations, "observations")
        _reject_observations(metadata, label="metadata")
        object.__setattr__(self, "metadata", metadata)
        object.__setattr__(self, "observations", observations)

        self.validate()
        computed = self._compute_identity()
        if self.document_id and self.document_id != computed.cid:
            raise ProtocolValidationError(
                "document_id does not match canonical protocol semantics"
            )
        object.__setattr__(self, "document_id", computed.cid)

    @property
    def interface(self) -> str:
        return PROTOCOL_IR_INTERFACE

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
            domain=PROTOCOL_IR_IDENTITY_DOMAIN,
            schema_version=PROTOCOL_IR_SCHEMA_VERSION,
        )

    def semantic_dict(self) -> dict[str, Any]:
        """Return the identity preimage, excluding runtime observations."""

        groups = (
            ("channels", self.channels, "channel_id"),
            ("claims", self.claims, "claim_id"),
            ("events", self.events, "event_id"),
            ("fresh_names", self.fresh_names, "name_id"),
            ("functions", self.functions, "function_id"),
            ("keys", self.keys, "key_id"),
            ("messages", self.messages, "message_id"),
            ("rewrite_facts", self.rewrite_facts, "fact_id"),
            ("roles", self.roles, "role_id"),
            ("sorts", self.sorts, "sort_id"),
            (
                "trust_assumptions",
                self.trust_assumptions,
                "assumption_id",
            ),
            ("variables", self.variables, "variable_id"),
        )
        result: dict[str, Any] = {
            "adversary": self.adversary.to_dict(),
            "equational_theories": [
                item.value for item in self.equational_theories
            ],
            "interface": PROTOCOL_IR_INTERFACE,
            "metadata": self.metadata.to_dict(),
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
        for name, values, id_field in groups:
            result[name] = [
                item.to_dict()
                for item in sorted(values, key=lambda item: getattr(item, id_field))
            ]
        return result

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

    def validate(self) -> None:
        """Validate all source maps, types, theories, and cross-references."""

        if self.schema_version != PROTOCOL_IR_SCHEMA_VERSION:
            raise ProtocolValidationError(
                f"unsupported schema_version {self.schema_version!r}"
            )
        if not self.sources:
            raise ProtocolValidationError(
                "a source-grounded protocol requires sources"
            )
        if not self.sorts:
            raise ProtocolValidationError("a typed protocol requires sorts")
        if not self.roles:
            raise ProtocolValidationError("a protocol requires at least one role")

        groups = (
            (self.sources, "ref_id", "source"),
            (self.spans, "span_id", "span"),
            (self.sorts, "sort_id", "sort"),
            (self.variables, "variable_id", "variable"),
            (self.roles, "role_id", "role"),
            (self.fresh_names, "name_id", "fresh name"),
            (self.keys, "key_id", "key"),
            (self.functions, "function_id", "function"),
            (self.trust_assumptions, "assumption_id", "trust assumption"),
            (self.channels, "channel_id", "channel"),
            (self.messages, "message_id", "message"),
            ((self.adversary,), "adversary_id", "adversary"),
            (self.adversary.knowledge, "knowledge_id", "adversary knowledge"),
            (self.rewrite_facts, "fact_id", "rewrite fact"),
            (self.events, "event_id", "event"),
            (self.claims, "claim_id", "claim"),
        )
        for values, id_field, label in groups:
            self._unique(values, id_field, label)

        semantic_id_groups = [
            {getattr(item, id_field) for item in values}
            for values, id_field, _ in groups[2:]
        ]
        semantic_ids: set[str] = set()
        for identifiers in semantic_id_groups:
            overlap = semantic_ids & identifiers
            if overlap:
                raise ProtocolValidationError(
                    f"semantic identifiers must be globally unique: {sorted(overlap)}"
                )
            semantic_ids.update(identifiers)

        source_ids = {item.ref_id for item in self.sources}
        spans = {item.span_id: item for item in self.spans}
        for source in self.sources:
            source.validate()
        for span in self.spans:
            span.validate()
            self._known((span.source_ref_id,), source_ids, f"span {span.span_id}")

        source_mapped = (
            *self.sorts,
            *self.variables,
            *self.roles,
            *self.fresh_names,
            *self.keys,
            *self.functions,
            *self.trust_assumptions,
            *self.channels,
            *self.messages,
            self.adversary,
            *self.adversary.knowledge,
            *self.rewrite_facts,
            *self.events,
            *self.claims,
        )
        for item in source_mapped:
            self._validate_source_map(item, source_ids, spans)

        sort_ids = {item.sort_id for item in self.sorts}
        role_ids = {item.role_id for item in self.roles}
        variable_ids = {item.variable_id for item in self.variables}
        key_ids = {item.key_id for item in self.keys}
        assumption_ids = {
            item.assumption_id for item in self.trust_assumptions
        }
        channel_ids = {item.channel_id for item in self.channels}
        event_ids = {item.event_id for item in self.events}

        symbol_sorts: dict[str, str] = {}
        for item in self.variables:
            self._known((item.sort,), sort_ids, f"variable {item.variable_id}.sort")
            if item.role_id:
                self._known(
                    (item.role_id,), role_ids, f"variable {item.variable_id}.role_id"
                )
            symbol_sorts[item.variable_id] = item.sort
        for role in self.roles:
            self._known(
                role.parameter_ids,
                variable_ids,
                f"role {role.role_id}.parameter_ids",
            )
            wrong_scope = sorted(
                variable_id
                for variable_id in role.parameter_ids
                if next(
                    item for item in self.variables if item.variable_id == variable_id
                ).role_id
                != role.role_id
            )
            if wrong_scope:
                raise ProtocolValidationError(
                    f"role {role.role_id}.parameter_ids contain variables scoped "
                    f"elsewhere: {wrong_scope}"
                )
        for item in self.fresh_names:
            self._known((item.sort,), sort_ids, f"fresh name {item.name_id}.sort")
            self._known(
                (item.generated_by_role_id,),
                role_ids,
                f"fresh name {item.name_id}.generated_by_role_id",
            )
            symbol_sorts[item.name_id] = item.sort
        keys_by_id = {item.key_id: item for item in self.keys}
        for item in self.keys:
            self._known((item.sort,), sort_ids, f"key {item.key_id}.sort")
            self._known(
                item.owner_role_ids, role_ids, f"key {item.key_id}.owner_role_ids"
            )
            if item.peer_key_id:
                self._known(
                    (item.peer_key_id,), key_ids, f"key {item.key_id}.peer_key_id"
                )
                peer = keys_by_id[item.peer_key_id]
                if peer.peer_key_id != item.key_id:
                    raise ProtocolValidationError(
                        f"key pair {item.key_id!r}/{item.peer_key_id!r} "
                        "must be reciprocal"
                    )
                if {item.kind, peer.kind} != {KeyKind.PRIVATE, KeyKind.PUBLIC}:
                    raise ProtocolValidationError(
                        "paired keys must contain one private and one public key"
                    )
            symbol_sorts[item.key_id] = item.sort

        functions_by_id = {item.function_id: item for item in self.functions}
        enabled_theories = set(self.equational_theories)
        for item in self.functions:
            self._known(
                item.parameter_sorts,
                sort_ids,
                f"function {item.function_id}.parameter_sorts",
            )
            self._known(
                (item.result_sort,),
                sort_ids,
                f"function {item.function_id}.result_sort",
            )
            if item.theory not in enabled_theories:
                raise ProtocolValidationError(
                    f"function {item.function_id!r} uses disabled equational "
                    f"theory {item.theory.value!r}"
                )

        for item in self.trust_assumptions:
            self._known(
                item.trusted_role_ids,
                role_ids,
                f"trust assumption {item.assumption_id}.trusted_role_ids",
            )
            self._known(
                item.trusted_key_ids,
                key_ids,
                f"trust assumption {item.assumption_id}.trusted_key_ids",
            )
        for item in self.channels:
            self._known(
                item.assumption_ids,
                assumption_ids,
                f"channel {item.channel_id}.assumption_ids",
            )
            if (
                self.adversary.kind is AdversaryKind.NONE
                and item.adversary_access is not AdversaryAccess.NONE
            ):
                raise ProtocolValidationError(
                    f"channel {item.channel_id!r} grants access to an absent "
                    "adversary"
                )
            if (
                self.adversary.kind is AdversaryKind.PASSIVE
                and item.adversary_access
                in {AdversaryAccess.INJECT, AdversaryAccess.CONTROL}
            ):
                raise ProtocolValidationError(
                    f"channel {item.channel_id!r} grants active access to a "
                    "passive adversary"
                )
            required_capabilities = {
                AdversaryAccess.NONE: frozenset(),
                AdversaryAccess.OBSERVE: frozenset(
                    {AdversaryCapability.INTERCEPT}
                ),
                AdversaryAccess.INJECT: frozenset(
                    {AdversaryCapability.INJECT}
                ),
                AdversaryAccess.CONTROL: frozenset(
                    {
                        AdversaryCapability.INTERCEPT,
                        AdversaryCapability.INJECT,
                    }
                ),
            }[item.adversary_access]
            missing_capabilities = required_capabilities - set(
                self.adversary.capabilities
            )
            if missing_capabilities:
                raise ProtocolValidationError(
                    f"channel {item.channel_id!r} adversary_access requires "
                    "capabilities "
                    f"{sorted(capability.value for capability in missing_capabilities)}"
                )
        for item in self.messages:
            self._known(
                (item.sender_role_id,),
                role_ids,
                f"message {item.message_id}.sender_role_id",
            )
            self._known(
                item.receiver_role_ids,
                role_ids,
                f"message {item.message_id}.receiver_role_ids",
            )
            self._known(
                (item.channel_id,),
                channel_ids,
                f"message {item.message_id}.channel_id",
            )
            self._validate_term(
                item.payload, sort_ids, symbol_sorts, functions_by_id
            )

        self._known(
            self.adversary.compromised_role_ids,
            role_ids,
            "adversary.compromised_role_ids",
        )
        self._known(
            self.adversary.compromised_key_ids,
            key_ids,
            "adversary.compromised_key_ids",
        )
        for item in self.adversary.knowledge:
            self._known(
                item.available_after_event_ids,
                event_ids,
                f"knowledge {item.knowledge_id}.available_after_event_ids",
            )
            self._validate_term(
                item.term, sort_ids, symbol_sorts, functions_by_id
            )
        for item in self.rewrite_facts:
            if item.theory not in enabled_theories:
                raise ProtocolValidationError(
                    f"rewrite fact {item.fact_id!r} uses disabled equational "
                    f"theory {item.theory.value!r}"
                )
            self._validate_term(
                item.left, sort_ids, symbol_sorts, functions_by_id
            )
            self._validate_term(
                item.right, sort_ids, symbol_sorts, functions_by_id
            )
        for item in self.events:
            self._known(
                (item.role_id,), role_ids, f"event {item.event_id}.role_id"
            )
            for term in item.parameters:
                self._validate_term(
                    term, sort_ids, symbol_sorts, functions_by_id
                )
        for item in self.claims:
            self._known(
                item.assumption_ids,
                assumption_ids,
                f"claim {item.claim_id}.assumption_ids",
            )
            self._known(
                (
                    *item.reachable_event_ids,
                    *item.antecedent_event_ids,
                    *item.consequent_event_ids,
                ),
                event_ids,
                f"claim {item.claim_id}.event_ids",
            )
            for term in (
                *item.secret_terms,
                *item.left_terms,
                *item.right_terms,
            ):
                self._validate_term(
                    term, sort_ids, symbol_sorts, functions_by_id
                )

    @staticmethod
    def _validate_term(
        term: ProtocolTerm,
        sort_ids: set[str],
        symbol_sorts: Mapping[str, str],
        functions: Mapping[str, ProtocolFunction],
    ) -> None:
        if term.sort not in sort_ids:
            raise ProtocolValidationError(
                f"term references unknown sort {term.sort!r}"
            )
        if term.symbol_id:
            if term.symbol_id not in symbol_sorts:
                raise ProtocolValidationError(
                    f"term references unknown symbol {term.symbol_id!r}"
                )
            expected = symbol_sorts[term.symbol_id]
            if term.sort != expected:
                raise ProtocolValidationError(
                    f"symbol {term.symbol_id!r} has sort {expected!r}, "
                    f"not {term.sort!r}"
                )
            return
        if term.literal:
            return
        function = functions.get(term.function_id)
        if function is None:
            raise ProtocolValidationError(
                f"term references unknown function {term.function_id!r}"
            )
        if term.sort != function.result_sort:
            raise ProtocolValidationError(
                f"function {term.function_id!r} returns {function.result_sort!r}, "
                f"not {term.sort!r}"
            )
        if len(term.arguments) != len(function.parameter_sorts):
            raise ProtocolValidationError(
                f"function {term.function_id!r} expects "
                f"{len(function.parameter_sorts)} arguments, got "
                f"{len(term.arguments)}"
            )
        for index, (argument, expected) in enumerate(
            zip(term.arguments, function.parameter_sorts, strict=True)
        ):
            ProtocolIR._validate_term(
                argument, sort_ids, symbol_sorts, functions
            )
            if argument.sort != expected:
                raise ProtocolValidationError(
                    f"function {term.function_id!r} argument {index} expects "
                    f"{expected!r}, got {argument.sort!r}"
                )

    @staticmethod
    def _unique(values: Sequence[object], field_name: str, label: str) -> None:
        ids = [getattr(item, field_name) for item in values]
        if len(ids) != len(set(ids)):
            raise ProtocolValidationError(f"duplicate {label} identifiers")

    @staticmethod
    def _known(values: Sequence[str], known: set[str], label: str) -> None:
        missing = sorted(set(values) - known)
        if missing:
            raise ProtocolValidationError(f"{label} references unknown ids {missing}")

    @classmethod
    def _validate_source_map(
        cls,
        item: _SourceMapped,
        source_ids: set[str],
        spans: Mapping[str, SourceSpan],
    ) -> None:
        sources = item.source_ref_ids
        span_ids = item.span_ids
        cls._known(sources, source_ids, "source_ref_ids")
        cls._known(span_ids, set(spans), "span_ids")
        if sources:
            unlisted = sorted(
                {
                    spans[span_id].source_ref_id
                    for span_id in span_ids
                    if spans[span_id].source_ref_id not in sources
                }
            )
            if unlisted:
                raise ProtocolValidationError(
                    f"source-mapped item spans belong to unlisted sources {unlisted}"
                )

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> ProtocolIR:
        value = _mapping(value, "protocol document")
        _reject_unknown(
            value,
            frozenset(
                {
                    "sources",
                    "spans",
                    "sorts",
                    "variables",
                    "roles",
                    "fresh_names",
                    "keys",
                    "functions",
                    "trust_assumptions",
                    "channels",
                    "messages",
                    "adversary",
                    "rewrite_facts",
                    "events",
                    "claims",
                    "equational_theories",
                    "metadata",
                    "observations",
                    "document_id",
                    "schema_version",
                    "interface",
                }
            ),
            "protocol document",
        )
        if value.get("interface", PROTOCOL_IR_INTERFACE) != PROTOCOL_IR_INTERFACE:
            raise ProtocolValidationError("unsupported protocol interface")
        return cls(
            sources=tuple(value.get("sources", ())),
            spans=tuple(value.get("spans", ())),
            sorts=tuple(value.get("sorts", ())),
            variables=tuple(value.get("variables", ())),
            roles=tuple(value.get("roles", ())),
            fresh_names=tuple(value.get("fresh_names", ())),
            keys=tuple(value.get("keys", ())),
            functions=tuple(value.get("functions", ())),
            trust_assumptions=tuple(value.get("trust_assumptions", ())),
            channels=tuple(value.get("channels", ())),
            messages=tuple(value.get("messages", ())),
            adversary=ProtocolAdversary.from_dict(
                _mapping(value.get("adversary", {}), "adversary")
            ),
            rewrite_facts=tuple(value.get("rewrite_facts", ())),
            events=tuple(value.get("events", ())),
            claims=tuple(value.get("claims", ())),
            equational_theories=tuple(
                value.get("equational_theories", (EquationalTheory.FREE.value,))
            ),
            metadata=_frozen(_mapping(value.get("metadata", {}), "metadata"), "metadata"),
            observations=_frozen(
                _mapping(value.get("observations", {}), "observations"),
                "observations",
            ),
            document_id=value.get("document_id", ""),
            schema_version=value.get(
                "schema_version", PROTOCOL_IR_SCHEMA_VERSION
            ),
        )

    @classmethod
    def from_json(cls, value: str | bytes | bytearray) -> ProtocolIR:
        try:
            decoded = json.loads(value)
        except (TypeError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ProtocolValidationError("protocol JSON is malformed") from error
        if not isinstance(decoded, Mapping):
            raise ProtocolValidationError("protocol JSON must contain an object")
        return cls.from_dict(decoded)


# Descriptive aliases used in objective drafts and downstream adapters.
ProtocolRewriteFact = RewriteFact
ProtocolTrustAssumption = TrustAssumption


__all__ = [
    "PROTOCOL_IR_IDENTITY_DOMAIN",
    "PROTOCOL_IR_INTERFACE",
    "PROTOCOL_IR_SCHEMA_VERSION",
    "AdversaryAccess",
    "AdversaryCapability",
    "AdversaryKind",
    "AdversaryKnowledge",
    "ChannelSecurity",
    "CorrespondenceKind",
    "EquationalTheory",
    "EventPhase",
    "FreshName",
    "FreshNameKind",
    "FunctionKind",
    "KeyKind",
    "ProtocolAdversary",
    "ProtocolChannel",
    "ProtocolClaim",
    "ProtocolClaimKind",
    "ProtocolEvent",
    "ProtocolFunction",
    "ProtocolIR",
    "ProtocolKey",
    "ProtocolMessage",
    "ProtocolRewriteFact",
    "ProtocolRole",
    "ProtocolSort",
    "ProtocolTerm",
    "ProtocolTrustAssumption",
    "ProtocolValidationError",
    "ProtocolVariable",
    "RewriteFact",
    "SortKind",
    "TrustAssumption",
]
