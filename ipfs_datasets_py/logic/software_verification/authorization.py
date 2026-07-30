"""Provider-neutral authorization, Datalog, and SecPAL-style semantics.

``AuthorizationIR@1`` describes a finite, stratification-aware authorization
policy above any Datalog, SecPAL, UCAN, or supervisor evaluator.  It records
principals, roles, ground facts, stratified rules, speaks-for and delegation
relations, constraints, deny/allow precedence, explanations, and
policy-decision queries.

This module deliberately contains no engine execution, solver request, or
theorem-proof verdict.  Authorization decisions use the closed
:class:`DecisionOutcome` vocabulary (``allow``, ``deny``, ``conflict``,
``unknown``) and a hard :class:`AuthorizationEvidenceAuthority` ceiling of
``authorization``.  A permit decision never establishes generated-code
correctness and cannot be relabeled as theorem proof.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, ClassVar, Final, Protocol

from ipfs_datasets_py.logic.ir_core.canonical import canonical_json_bytes
from ipfs_datasets_py.logic.ir_core.claims import FrozenMap
from ipfs_datasets_py.logic.ir_core.identity import (
    CanonicalIdentity,
    canonical_identity,
)
from ipfs_datasets_py.logic.ir_core.provenance import SourceRef, SourceSpan

AUTHORIZATION_IR_INTERFACE: Final = "AuthorizationIR@1"
AUTHORIZATION_IR_SCHEMA_VERSION: Final = "authorization-ir/v1"
AUTHORIZATION_IR_IDENTITY_DOMAIN: Final = (
    "logic.software-verification.authorization"
)

PRINCIPAL_SCHEMA_VERSION: Final = "authorization-principal/v1"
ROLE_SCHEMA_VERSION: Final = "authorization-role/v1"
PREDICATE_SCHEMA_VERSION: Final = "authorization-predicate/v1"
FACT_SCHEMA_VERSION: Final = "authorization-fact/v1"
RULE_SCHEMA_VERSION: Final = "authorization-rule/v1"
SPEAKS_FOR_SCHEMA_VERSION: Final = "authorization-speaks-for/v1"
DELEGATION_SCHEMA_VERSION: Final = "authorization-delegation/v1"
CONSTRAINT_SCHEMA_VERSION: Final = "authorization-constraint/v1"
BOUNDS_SCHEMA_VERSION: Final = "authorization-bounds/v1"
PRECEDENCE_SCHEMA_VERSION: Final = "authorization-precedence/v1"
QUERY_SCHEMA_VERSION: Final = "authorization-decision-query/v1"
EXPLANATION_SCHEMA_VERSION: Final = "authorization-explanation/v1"
DECISION_SCHEMA_VERSION: Final = "authorization-decision/v1"

# Match the supervisor finite-policy ceiling used by the reference evaluator.
MAX_DELEGATION_DEPTH: Final = 64
MAX_STRATUM: Final = 255
MAX_RULE_BODY_SIZE: Final = 256
MAX_FACT_ARITY: Final = 32

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


class AuthorizationValidationError(ValueError):
    """Raised when authorization semantics are malformed or ambiguous."""


class _SourceMapped(Protocol):
    @property
    def source_ref_ids(self) -> tuple[str, ...]: ...

    @property
    def span_ids(self) -> tuple[str, ...]: ...


class PrincipalKind(StrEnum):
    """Closed vocabulary for authorization principals."""

    AGENT = "agent"
    USER = "user"
    SERVICE = "service"
    GROUP = "group"
    ROLE = "role"
    SYSTEM = "system"
    ANONYMOUS = "anonymous"


class AtomPolarity(StrEnum):
    """Whether a body or head atom is positive or negated."""

    POSITIVE = "positive"
    NEGATIVE = "negative"


class RuleKind(StrEnum):
    """How a stratified rule is interpreted."""

    DATALOG = "datalog"
    SECPAL_SAYS = "secpal_says"
    ROLE_ASSIGNMENT = "role_assignment"
    CAPABILITY = "capability"
    SPEAKS_FOR = "speaks_for"
    DELEGATION = "delegation"


class ConstraintKind(StrEnum):
    """Closed constraint vocabulary for rule and query guards."""

    EQUALITY = "equality"
    INEQUALITY = "inequality"
    MEMBERSHIP = "membership"
    COMPARISON = "comparison"
    TEMPORAL_WINDOW = "temporal_window"
    SCOPE = "scope"
    CUSTOM = "custom"


class EffectKind(StrEnum):
    """Policy effect attached to a decision-producing rule head."""

    ALLOW = "allow"
    DENY = "deny"
    DERIVE = "derive"


class ConflictResolution(StrEnum):
    """How simultaneous allow and deny evidence is resolved.

    ``explicit_conflict`` never collapses opposing evidence: the decision
    outcome remains :attr:`DecisionOutcome.CONFLICT`.
    """

    DENY_OVERRIDES = "deny_overrides"
    ALLOW_OVERRIDES = "allow_overrides"
    FIRST_APPLICABLE = "first_applicable"
    EXPLICIT_CONFLICT = "explicit_conflict"


class DecisionOutcome(StrEnum):
    """Closed, non-interchangeable authorization conclusions.

    ``allow``, ``deny``, ``conflict``, and ``unknown`` are deliberately
    distinct.  Engines and fixtures must not collapse them.
    """

    ALLOW = "allow"
    DENY = "deny"
    CONFLICT = "conflict"
    UNKNOWN = "unknown"


class AuthorizationEvidenceAuthority(StrEnum):
    """Hard authority ceiling for authorization evidence.

    Only ``authorization`` is admitted.  Theorem, model-check, and related
    authorities are rejected so decisions cannot masquerade as proof.
    """

    AUTHORIZATION = "authorization"


class GeneratedCodeCorrectness(StrEnum):
    """The only correctness projection authorization evidence may carry."""

    NOT_ESTABLISHED = "not_established"


class ExplanationStepKind(StrEnum):
    """What kind of evidence an explanation step cites."""

    FACT = "fact"
    RULE = "rule"
    SPEAKS_FOR = "speaks_for"
    DELEGATION = "delegation"
    CONSTRAINT = "constraint"
    TRUST_ROOT = "trust_root"
    PRECEDENCE = "precedence"
    BOUND = "bound"


class TermKind(StrEnum):
    """Whether a term is a ground constant or a rule variable."""

    CONSTANT = "constant"
    VARIABLE = "variable"


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
        raise AuthorizationValidationError(
            f"{label} must be {qualifier}non-empty trimmed string without NUL bytes"
        )
    return value


def _identifier(value: object, label: str) -> str:
    result = _text(value, label)
    if not _ID_RE.fullmatch(result):
        raise AuthorizationValidationError(f"{label} must be a stable identifier")
    return result


def _enum(value: object, enum_type: type[StrEnum], label: str) -> Any:
    try:
        return value if isinstance(value, enum_type) else enum_type(value)
    except (TypeError, ValueError) as error:
        choices = ", ".join(repr(member.value) for member in enum_type)
        raise AuthorizationValidationError(
            f"{label} must be one of {choices}"
        ) from error


def _sequence(value: object, label: str) -> Sequence[Any]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise AuthorizationValidationError(f"{label} must be a sequence")
    return value


def _identifiers(
    values: object,
    label: str,
    *,
    sort: bool = True,
    required: bool = False,
) -> tuple[str, ...]:
    result = tuple(
        _identifier(item, f"{label} item") for item in _sequence(values, label)
    )
    if len(result) != len(set(result)):
        raise AuthorizationValidationError(f"{label} must not contain duplicates")
    if required and not result:
        raise AuthorizationValidationError(f"{label} must not be empty")
    return tuple(sorted(result)) if sort else result


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise AuthorizationValidationError(f"{label} must be a mapping")
    return value


def _frozen(value: Mapping[str, Any] | FrozenMap, label: str) -> FrozenMap:
    try:
        return value if isinstance(value, FrozenMap) else FrozenMap(value)
    except (TypeError, ValueError) as error:
        raise AuthorizationValidationError(
            f"{label} must contain immutable JSON-compatible data"
        ) from error


def _reject_unknown(
    value: Mapping[str, Any], allowed: frozenset[str], label: str
) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise AuthorizationValidationError(
            f"unknown {label} field(s): {', '.join(unknown)}"
        )


def _bool(value: object, label: str) -> bool:
    if not isinstance(value, bool):
        raise AuthorizationValidationError(f"{label} must be a boolean")
    return value


def _non_bool_int(value: object, label: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise AuthorizationValidationError(f"{label} must be an integer")
    if value < minimum:
        raise AuthorizationValidationError(
            f"{label} must be >= {minimum}"
        )
    return value


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
        raise AuthorizationValidationError(
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
                child_path = f"{path}.{key}" if path else str(key)
                folded = str(key).casefold().replace("-", "_")
                if folded in _OBSERVATIONAL_KEYS:
                    offending.append(child_path)
                visit(child, child_path)
        elif isinstance(item, tuple):
            for index, child in enumerate(item):
                visit(child, f"{path}[{index}]")

    visit(value, "")
    if offending:
        raise AuthorizationValidationError(
            f"{label} contains observational keys {sorted(offending)}; "
            "put runtime output in observations"
        )


def _known(values: Sequence[str], known: set[str], label: str) -> None:
    missing = sorted(set(values) - known)
    if missing:
        raise AuthorizationValidationError(
            f"{label} references unknown ids {missing}"
        )


@dataclass(frozen=True, slots=True)
class AuthorizationTerm:
    """A constant or variable appearing in a fact, rule, or query."""

    kind: TermKind | str
    value: str
    sort: str = "atom"

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", _enum(self.kind, TermKind, "term.kind"))
        object.__setattr__(self, "value", _identifier(self.value, "term.value"))
        object.__setattr__(self, "sort", _identifier(self.sort, "term.sort"))

    @classmethod
    def constant(cls, value: str, sort: str = "atom") -> AuthorizationTerm:
        return cls(TermKind.CONSTANT, value, sort)

    @classmethod
    def variable(cls, value: str, sort: str = "atom") -> AuthorizationTerm:
        return cls(TermKind.VARIABLE, value, sort)

    @property
    def is_ground(self) -> bool:
        return self.kind is TermKind.CONSTANT

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "sort": self.sort,
            "value": self.value,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> AuthorizationTerm:
        value = _mapping(value, "term")
        _reject_unknown(value, frozenset({"kind", "value", "sort"}), "term")
        return cls(
            kind=value.get("kind", ""),
            value=value.get("value", ""),
            sort=value.get("sort", "atom"),
        )


@dataclass(frozen=True, slots=True)
class AuthorizationAtom:
    """A positive or negative predicate application."""

    predicate_id: str
    arguments: tuple[AuthorizationTerm, ...] = ()
    polarity: AtomPolarity | str = AtomPolarity.POSITIVE

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "predicate_id",
            _identifier(self.predicate_id, "atom.predicate_id"),
        )
        arguments = tuple(
            item
            if isinstance(item, AuthorizationTerm)
            else AuthorizationTerm.from_dict(_mapping(item, "atom argument"))
            for item in _sequence(self.arguments, "atom.arguments")
        )
        if len(arguments) > MAX_FACT_ARITY:
            raise AuthorizationValidationError(
                f"atom arity exceeds {MAX_FACT_ARITY}"
            )
        object.__setattr__(self, "arguments", arguments)
        object.__setattr__(
            self, "polarity", _enum(self.polarity, AtomPolarity, "atom.polarity")
        )

    @property
    def is_ground(self) -> bool:
        return all(argument.is_ground for argument in self.arguments)

    @property
    def is_negative(self) -> bool:
        return self.polarity is AtomPolarity.NEGATIVE

    def to_dict(self) -> dict[str, Any]:
        return {
            "arguments": [item.to_dict() for item in self.arguments],
            "polarity": self.polarity.value,
            "predicate_id": self.predicate_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> AuthorizationAtom:
        value = _mapping(value, "atom")
        _reject_unknown(
            value,
            frozenset({"predicate_id", "arguments", "polarity"}),
            "atom",
        )
        return cls(
            predicate_id=value.get("predicate_id", ""),
            arguments=tuple(value.get("arguments", ())),
            polarity=value.get("polarity", AtomPolarity.POSITIVE.value),
        )


@dataclass(frozen=True, slots=True)
class AuthorizationPrincipal:
    """A stable policy principal, independent of display names."""

    principal_id: str
    name: str
    kind: PrincipalKind | str = PrincipalKind.AGENT
    attributes: FrozenMap = field(default_factory=FrozenMap)
    source_ref_ids: tuple[str, ...] = ()
    span_ids: tuple[str, ...] = ()
    schema_version: str = PRINCIPAL_SCHEMA_VERSION

    def __post_init__(self) -> None:
        sources, spans = _source_map(
            self.source_ref_ids, self.span_ids, owner="AuthorizationPrincipal"
        )
        object.__setattr__(
            self, "principal_id", _identifier(self.principal_id, "principal_id")
        )
        object.__setattr__(self, "name", _text(self.name, "principal.name"))
        object.__setattr__(
            self, "kind", _enum(self.kind, PrincipalKind, "principal.kind")
        )
        object.__setattr__(
            self, "attributes", _frozen(self.attributes, "principal.attributes")
        )
        object.__setattr__(self, "source_ref_ids", sources)
        object.__setattr__(self, "span_ids", spans)
        if self.schema_version != PRINCIPAL_SCHEMA_VERSION:
            raise AuthorizationValidationError(
                f"unsupported principal schema_version {self.schema_version!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": self.attributes.to_dict(),
            "kind": self.kind.value,
            "name": self.name,
            "principal_id": self.principal_id,
            "schema_version": self.schema_version,
            **_source_dict(self),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> AuthorizationPrincipal:
        value = _mapping(value, "principal")
        _reject_unknown(
            value,
            frozenset(
                {
                    "principal_id",
                    "name",
                    "kind",
                    "attributes",
                    "source_ref_ids",
                    "source_refs",
                    "span_ids",
                    "schema_version",
                }
            ),
            "principal",
        )
        sources, spans = _source_values(value)
        return cls(
            principal_id=value.get("principal_id", ""),
            name=value.get("name", ""),
            kind=value.get("kind", PrincipalKind.AGENT.value),
            attributes=_frozen(
                _mapping(value.get("attributes", {}), "attributes"), "attributes"
            ),
            source_ref_ids=sources,
            span_ids=spans,
            schema_version=value.get("schema_version", PRINCIPAL_SCHEMA_VERSION),
        )


@dataclass(frozen=True, slots=True)
class AuthorizationRole:
    """A named authorization role that principals may inhabit."""

    role_id: str
    name: str
    member_principal_ids: tuple[str, ...] = ()
    attributes: FrozenMap = field(default_factory=FrozenMap)
    source_ref_ids: tuple[str, ...] = ()
    span_ids: tuple[str, ...] = ()
    schema_version: str = ROLE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        sources, spans = _source_map(
            self.source_ref_ids, self.span_ids, owner="AuthorizationRole"
        )
        object.__setattr__(self, "role_id", _identifier(self.role_id, "role_id"))
        object.__setattr__(self, "name", _text(self.name, "role.name"))
        object.__setattr__(
            self,
            "member_principal_ids",
            _identifiers(self.member_principal_ids, "role.member_principal_ids"),
        )
        object.__setattr__(
            self, "attributes", _frozen(self.attributes, "role.attributes")
        )
        object.__setattr__(self, "source_ref_ids", sources)
        object.__setattr__(self, "span_ids", spans)
        if self.schema_version != ROLE_SCHEMA_VERSION:
            raise AuthorizationValidationError(
                f"unsupported role schema_version {self.schema_version!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": self.attributes.to_dict(),
            "member_principal_ids": list(self.member_principal_ids),
            "name": self.name,
            "role_id": self.role_id,
            "schema_version": self.schema_version,
            **_source_dict(self),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> AuthorizationRole:
        value = _mapping(value, "role")
        _reject_unknown(
            value,
            frozenset(
                {
                    "role_id",
                    "name",
                    "member_principal_ids",
                    "attributes",
                    "source_ref_ids",
                    "source_refs",
                    "span_ids",
                    "schema_version",
                }
            ),
            "role",
        )
        sources, spans = _source_values(value)
        return cls(
            role_id=value.get("role_id", ""),
            name=value.get("name", ""),
            member_principal_ids=tuple(value.get("member_principal_ids", ())),
            attributes=_frozen(
                _mapping(value.get("attributes", {}), "attributes"), "attributes"
            ),
            source_ref_ids=sources,
            span_ids=spans,
            schema_version=value.get("schema_version", ROLE_SCHEMA_VERSION),
        )


@dataclass(frozen=True, slots=True)
class PredicateSignature:
    """A finite predicate schema used by facts and rules."""

    predicate_id: str
    name: str
    arity: int
    argument_sorts: tuple[str, ...] = ()
    is_intensional: bool = False
    source_ref_ids: tuple[str, ...] = ()
    span_ids: tuple[str, ...] = ()
    schema_version: str = PREDICATE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        sources, spans = _source_map(
            self.source_ref_ids, self.span_ids, owner="PredicateSignature"
        )
        object.__setattr__(
            self, "predicate_id", _identifier(self.predicate_id, "predicate_id")
        )
        object.__setattr__(self, "name", _text(self.name, "predicate.name"))
        arity = _non_bool_int(self.arity, "predicate.arity", minimum=0)
        if arity > MAX_FACT_ARITY:
            raise AuthorizationValidationError(
                f"predicate arity exceeds {MAX_FACT_ARITY}"
            )
        object.__setattr__(self, "arity", arity)
        sorts = _identifiers(
            self.argument_sorts, "predicate.argument_sorts", sort=False
        )
        if sorts and len(sorts) != arity:
            raise AuthorizationValidationError(
                "predicate.argument_sorts length must equal arity"
            )
        object.__setattr__(self, "argument_sorts", sorts)
        object.__setattr__(
            self,
            "is_intensional",
            _bool(self.is_intensional, "predicate.is_intensional"),
        )
        object.__setattr__(self, "source_ref_ids", sources)
        object.__setattr__(self, "span_ids", spans)
        if self.schema_version != PREDICATE_SCHEMA_VERSION:
            raise AuthorizationValidationError(
                f"unsupported predicate schema_version {self.schema_version!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "argument_sorts": list(self.argument_sorts),
            "arity": self.arity,
            "is_intensional": self.is_intensional,
            "name": self.name,
            "predicate_id": self.predicate_id,
            "schema_version": self.schema_version,
            **_source_dict(self),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> PredicateSignature:
        value = _mapping(value, "predicate")
        _reject_unknown(
            value,
            frozenset(
                {
                    "predicate_id",
                    "name",
                    "arity",
                    "argument_sorts",
                    "is_intensional",
                    "source_ref_ids",
                    "source_refs",
                    "span_ids",
                    "schema_version",
                }
            ),
            "predicate",
        )
        sources, spans = _source_values(value)
        return cls(
            predicate_id=value.get("predicate_id", ""),
            name=value.get("name", ""),
            arity=value.get("arity", -1),
            argument_sorts=tuple(value.get("argument_sorts", ())),
            is_intensional=value.get("is_intensional", False),
            source_ref_ids=sources,
            span_ids=spans,
            schema_version=value.get("schema_version", PREDICATE_SCHEMA_VERSION),
        )


@dataclass(frozen=True, slots=True)
class AuthorizationFact:
    """A finite ground fact in the extensional database (EDB)."""

    fact_id: str
    atom: AuthorizationAtom
    issuer_principal_id: str = ""
    attributes: FrozenMap = field(default_factory=FrozenMap)
    source_ref_ids: tuple[str, ...] = ()
    span_ids: tuple[str, ...] = ()
    schema_version: str = FACT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        sources, spans = _source_map(
            self.source_ref_ids, self.span_ids, owner="AuthorizationFact"
        )
        object.__setattr__(self, "fact_id", _identifier(self.fact_id, "fact_id"))
        atom = (
            self.atom
            if isinstance(self.atom, AuthorizationAtom)
            else AuthorizationAtom.from_dict(_mapping(self.atom, "fact.atom"))
        )
        if not atom.is_ground:
            raise AuthorizationValidationError(
                "authorization facts must be ground (all constant arguments)"
            )
        if atom.is_negative:
            raise AuthorizationValidationError(
                "authorization facts must be positive; use stratified negation in rules"
            )
        object.__setattr__(self, "atom", atom)
        if self.issuer_principal_id:
            object.__setattr__(
                self,
                "issuer_principal_id",
                _identifier(self.issuer_principal_id, "fact.issuer_principal_id"),
            )
        object.__setattr__(
            self, "attributes", _frozen(self.attributes, "fact.attributes")
        )
        object.__setattr__(self, "source_ref_ids", sources)
        object.__setattr__(self, "span_ids", spans)
        if self.schema_version != FACT_SCHEMA_VERSION:
            raise AuthorizationValidationError(
                f"unsupported fact schema_version {self.schema_version!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "atom": self.atom.to_dict(),
            "attributes": self.attributes.to_dict(),
            "fact_id": self.fact_id,
            "issuer_principal_id": self.issuer_principal_id,
            "schema_version": self.schema_version,
            **_source_dict(self),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> AuthorizationFact:
        value = _mapping(value, "fact")
        _reject_unknown(
            value,
            frozenset(
                {
                    "fact_id",
                    "atom",
                    "issuer_principal_id",
                    "attributes",
                    "source_ref_ids",
                    "source_refs",
                    "span_ids",
                    "schema_version",
                }
            ),
            "fact",
        )
        sources, spans = _source_values(value)
        return cls(
            fact_id=value.get("fact_id", ""),
            atom=value.get("atom", {}),
            issuer_principal_id=value.get("issuer_principal_id", ""),
            attributes=_frozen(
                _mapping(value.get("attributes", {}), "attributes"), "attributes"
            ),
            source_ref_ids=sources,
            span_ids=spans,
            schema_version=value.get("schema_version", FACT_SCHEMA_VERSION),
        )


@dataclass(frozen=True, slots=True)
class AuthorizationConstraint:
    """A finite guard attached to a rule or decision query."""

    constraint_id: str
    kind: ConstraintKind | str
    expression: FrozenMap = field(default_factory=FrozenMap)
    statement: str = ""
    source_ref_ids: tuple[str, ...] = ()
    span_ids: tuple[str, ...] = ()
    schema_version: str = CONSTRAINT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        sources, spans = _source_map(
            self.source_ref_ids, self.span_ids, owner="AuthorizationConstraint"
        )
        object.__setattr__(
            self, "constraint_id", _identifier(self.constraint_id, "constraint_id")
        )
        object.__setattr__(
            self, "kind", _enum(self.kind, ConstraintKind, "constraint.kind")
        )
        object.__setattr__(
            self, "expression", _frozen(self.expression, "constraint.expression")
        )
        object.__setattr__(
            self,
            "statement",
            _text(self.statement, "constraint.statement", optional=True),
        )
        object.__setattr__(self, "source_ref_ids", sources)
        object.__setattr__(self, "span_ids", spans)
        if self.schema_version != CONSTRAINT_SCHEMA_VERSION:
            raise AuthorizationValidationError(
                f"unsupported constraint schema_version {self.schema_version!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "constraint_id": self.constraint_id,
            "expression": self.expression.to_dict(),
            "kind": self.kind.value,
            "schema_version": self.schema_version,
            "statement": self.statement,
            **_source_dict(self),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> AuthorizationConstraint:
        value = _mapping(value, "constraint")
        _reject_unknown(
            value,
            frozenset(
                {
                    "constraint_id",
                    "kind",
                    "expression",
                    "statement",
                    "source_ref_ids",
                    "source_refs",
                    "span_ids",
                    "schema_version",
                }
            ),
            "constraint",
        )
        sources, spans = _source_values(value)
        return cls(
            constraint_id=value.get("constraint_id", ""),
            kind=value.get("kind", ""),
            expression=_frozen(
                _mapping(value.get("expression", {}), "expression"), "expression"
            ),
            statement=value.get("statement", ""),
            source_ref_ids=sources,
            span_ids=spans,
            schema_version=value.get("schema_version", CONSTRAINT_SCHEMA_VERSION),
        )


@dataclass(frozen=True, slots=True)
class AuthorizationRule:
    """A stratified Datalog or SecPAL-style derivation rule.

    ``stratum`` places the rule in a finite stratification.  Negative body
    atoms may only mention predicates whose defining rules occupy strictly
    lower strata.  Heads with :attr:`EffectKind.ALLOW` or
    :attr:`EffectKind.DENY` contribute decision evidence; ``derive`` heads
    only extend the intensional database.
    """

    rule_id: str
    head: AuthorizationAtom
    body: tuple[AuthorizationAtom, ...] = ()
    constraint_ids: tuple[str, ...] = ()
    kind: RuleKind | str = RuleKind.DATALOG
    effect: EffectKind | str = EffectKind.DERIVE
    stratum: int = 0
    issuer_principal_id: str = ""
    attributes: FrozenMap = field(default_factory=FrozenMap)
    source_ref_ids: tuple[str, ...] = ()
    span_ids: tuple[str, ...] = ()
    schema_version: str = RULE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        sources, spans = _source_map(
            self.source_ref_ids, self.span_ids, owner="AuthorizationRule"
        )
        object.__setattr__(self, "rule_id", _identifier(self.rule_id, "rule_id"))
        head = (
            self.head
            if isinstance(self.head, AuthorizationAtom)
            else AuthorizationAtom.from_dict(_mapping(self.head, "rule.head"))
        )
        if head.is_negative:
            raise AuthorizationValidationError(
                "rule heads must be positive; negation is body-only"
            )
        object.__setattr__(self, "head", head)
        body = tuple(
            item
            if isinstance(item, AuthorizationAtom)
            else AuthorizationAtom.from_dict(_mapping(item, "rule body atom"))
            for item in _sequence(self.body, "rule.body")
        )
        if len(body) > MAX_RULE_BODY_SIZE:
            raise AuthorizationValidationError(
                f"rule body size exceeds {MAX_RULE_BODY_SIZE}"
            )
        object.__setattr__(self, "body", body)
        object.__setattr__(
            self,
            "constraint_ids",
            _identifiers(self.constraint_ids, "rule.constraint_ids"),
        )
        object.__setattr__(self, "kind", _enum(self.kind, RuleKind, "rule.kind"))
        object.__setattr__(
            self, "effect", _enum(self.effect, EffectKind, "rule.effect")
        )
        stratum = _non_bool_int(self.stratum, "rule.stratum", minimum=0)
        if stratum > MAX_STRATUM:
            raise AuthorizationValidationError(
                f"rule stratum exceeds {MAX_STRATUM}"
            )
        object.__setattr__(self, "stratum", stratum)
        if self.issuer_principal_id:
            object.__setattr__(
                self,
                "issuer_principal_id",
                _identifier(self.issuer_principal_id, "rule.issuer_principal_id"),
            )
        elif self.kind is RuleKind.SECPAL_SAYS:
            raise AuthorizationValidationError(
                "secpal_says rules require issuer_principal_id"
            )
        object.__setattr__(
            self, "attributes", _frozen(self.attributes, "rule.attributes")
        )
        object.__setattr__(self, "source_ref_ids", sources)
        object.__setattr__(self, "span_ids", spans)
        if self.schema_version != RULE_SCHEMA_VERSION:
            raise AuthorizationValidationError(
                f"unsupported rule schema_version {self.schema_version!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": self.attributes.to_dict(),
            "body": [item.to_dict() for item in self.body],
            "constraint_ids": list(self.constraint_ids),
            "effect": self.effect.value,
            "head": self.head.to_dict(),
            "issuer_principal_id": self.issuer_principal_id,
            "kind": self.kind.value,
            "rule_id": self.rule_id,
            "schema_version": self.schema_version,
            "stratum": self.stratum,
            **_source_dict(self),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> AuthorizationRule:
        value = _mapping(value, "rule")
        _reject_unknown(
            value,
            frozenset(
                {
                    "rule_id",
                    "head",
                    "body",
                    "constraint_ids",
                    "kind",
                    "effect",
                    "stratum",
                    "issuer_principal_id",
                    "attributes",
                    "source_ref_ids",
                    "source_refs",
                    "span_ids",
                    "schema_version",
                }
            ),
            "rule",
        )
        sources, spans = _source_values(value)
        return cls(
            rule_id=value.get("rule_id", ""),
            head=value.get("head", {}),
            body=tuple(value.get("body", ())),
            constraint_ids=tuple(value.get("constraint_ids", ())),
            kind=value.get("kind", RuleKind.DATALOG.value),
            effect=value.get("effect", EffectKind.DERIVE.value),
            stratum=value.get("stratum", 0),
            issuer_principal_id=value.get("issuer_principal_id", ""),
            attributes=_frozen(
                _mapping(value.get("attributes", {}), "attributes"), "attributes"
            ),
            source_ref_ids=sources,
            span_ids=spans,
            schema_version=value.get("schema_version", RULE_SCHEMA_VERSION),
        )


@dataclass(frozen=True, slots=True)
class SpeaksForRelation:
    """Principal *speaker* speaks for principal *subject*.

    Speaks-for is a first-class relation, not an ambient side effect of
    delegation.  Optional depth bounds limit how far speaks-for may be
    composed with other speaks-for edges.
    """

    speaks_for_id: str
    speaker_principal_id: str
    subject_principal_id: str
    max_composition_depth: int = 1
    constraint_ids: tuple[str, ...] = ()
    attributes: FrozenMap = field(default_factory=FrozenMap)
    source_ref_ids: tuple[str, ...] = ()
    span_ids: tuple[str, ...] = ()
    schema_version: str = SPEAKS_FOR_SCHEMA_VERSION

    def __post_init__(self) -> None:
        sources, spans = _source_map(
            self.source_ref_ids, self.span_ids, owner="SpeaksForRelation"
        )
        object.__setattr__(
            self, "speaks_for_id", _identifier(self.speaks_for_id, "speaks_for_id")
        )
        object.__setattr__(
            self,
            "speaker_principal_id",
            _identifier(self.speaker_principal_id, "speaker_principal_id"),
        )
        object.__setattr__(
            self,
            "subject_principal_id",
            _identifier(self.subject_principal_id, "subject_principal_id"),
        )
        if self.speaker_principal_id == self.subject_principal_id:
            raise AuthorizationValidationError(
                "speaks-for speaker and subject must differ"
            )
        depth = _non_bool_int(
            self.max_composition_depth, "max_composition_depth", minimum=1
        )
        if depth > MAX_DELEGATION_DEPTH:
            raise AuthorizationValidationError(
                f"max_composition_depth exceeds {MAX_DELEGATION_DEPTH}"
            )
        object.__setattr__(self, "max_composition_depth", depth)
        object.__setattr__(
            self,
            "constraint_ids",
            _identifiers(self.constraint_ids, "speaks_for.constraint_ids"),
        )
        object.__setattr__(
            self, "attributes", _frozen(self.attributes, "speaks_for.attributes")
        )
        object.__setattr__(self, "source_ref_ids", sources)
        object.__setattr__(self, "span_ids", spans)
        if self.schema_version != SPEAKS_FOR_SCHEMA_VERSION:
            raise AuthorizationValidationError(
                f"unsupported speaks-for schema_version {self.schema_version!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": self.attributes.to_dict(),
            "constraint_ids": list(self.constraint_ids),
            "max_composition_depth": self.max_composition_depth,
            "schema_version": self.schema_version,
            "speaker_principal_id": self.speaker_principal_id,
            "speaks_for_id": self.speaks_for_id,
            "subject_principal_id": self.subject_principal_id,
            **_source_dict(self),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> SpeaksForRelation:
        value = _mapping(value, "speaks-for")
        _reject_unknown(
            value,
            frozenset(
                {
                    "speaks_for_id",
                    "speaker_principal_id",
                    "subject_principal_id",
                    "max_composition_depth",
                    "constraint_ids",
                    "attributes",
                    "source_ref_ids",
                    "source_refs",
                    "span_ids",
                    "schema_version",
                }
            ),
            "speaks-for",
        )
        sources, spans = _source_values(value)
        return cls(
            speaks_for_id=value.get("speaks_for_id", ""),
            speaker_principal_id=value.get("speaker_principal_id", ""),
            subject_principal_id=value.get("subject_principal_id", ""),
            max_composition_depth=value.get("max_composition_depth", 1),
            constraint_ids=tuple(value.get("constraint_ids", ())),
            attributes=_frozen(
                _mapping(value.get("attributes", {}), "attributes"), "attributes"
            ),
            source_ref_ids=sources,
            span_ids=spans,
            schema_version=value.get("schema_version", SPEAKS_FOR_SCHEMA_VERSION),
        )


@dataclass(frozen=True, slots=True)
class DelegationStatement:
    """A SecPAL-style bounded delegation of a capability.

    ``delegation_depth`` is the number of additional hops the subject may
    make.  A child statement must name its parent and use a strictly smaller
    depth, which prevents ambient-authority chains.
    """

    delegation_id: str
    issuer_principal_id: str
    subject_principal_id: str
    capability: str
    delegation_depth: int = 0
    parent_delegation_id: str = ""
    resource_scope: tuple[str, ...] = ()
    constraint_ids: tuple[str, ...] = ()
    attributes: FrozenMap = field(default_factory=FrozenMap)
    source_ref_ids: tuple[str, ...] = ()
    span_ids: tuple[str, ...] = ()
    schema_version: str = DELEGATION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        sources, spans = _source_map(
            self.source_ref_ids, self.span_ids, owner="DelegationStatement"
        )
        object.__setattr__(
            self, "delegation_id", _identifier(self.delegation_id, "delegation_id")
        )
        object.__setattr__(
            self,
            "issuer_principal_id",
            _identifier(self.issuer_principal_id, "issuer_principal_id"),
        )
        object.__setattr__(
            self,
            "subject_principal_id",
            _identifier(self.subject_principal_id, "subject_principal_id"),
        )
        object.__setattr__(
            self, "capability", _identifier(self.capability, "capability")
        )
        depth = _non_bool_int(self.delegation_depth, "delegation_depth", minimum=0)
        if depth > MAX_DELEGATION_DEPTH:
            raise AuthorizationValidationError(
                f"delegation_depth exceeds {MAX_DELEGATION_DEPTH}"
            )
        object.__setattr__(self, "delegation_depth", depth)
        if self.parent_delegation_id:
            object.__setattr__(
                self,
                "parent_delegation_id",
                _identifier(self.parent_delegation_id, "parent_delegation_id"),
            )
        object.__setattr__(
            self,
            "resource_scope",
            _identifiers(self.resource_scope, "resource_scope", sort=True),
        )
        object.__setattr__(
            self,
            "constraint_ids",
            _identifiers(self.constraint_ids, "delegation.constraint_ids"),
        )
        object.__setattr__(
            self, "attributes", _frozen(self.attributes, "delegation.attributes")
        )
        object.__setattr__(self, "source_ref_ids", sources)
        object.__setattr__(self, "span_ids", spans)
        if self.schema_version != DELEGATION_SCHEMA_VERSION:
            raise AuthorizationValidationError(
                f"unsupported delegation schema_version {self.schema_version!r}"
            )

    @property
    def can_delegate(self) -> bool:
        return self.delegation_depth > 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": self.attributes.to_dict(),
            "capability": self.capability,
            "constraint_ids": list(self.constraint_ids),
            "delegation_depth": self.delegation_depth,
            "delegation_id": self.delegation_id,
            "issuer_principal_id": self.issuer_principal_id,
            "parent_delegation_id": self.parent_delegation_id,
            "resource_scope": list(self.resource_scope),
            "schema_version": self.schema_version,
            "subject_principal_id": self.subject_principal_id,
            **_source_dict(self),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> DelegationStatement:
        value = _mapping(value, "delegation")
        _reject_unknown(
            value,
            frozenset(
                {
                    "delegation_id",
                    "issuer_principal_id",
                    "subject_principal_id",
                    "capability",
                    "delegation_depth",
                    "parent_delegation_id",
                    "resource_scope",
                    "constraint_ids",
                    "attributes",
                    "source_ref_ids",
                    "source_refs",
                    "span_ids",
                    "schema_version",
                }
            ),
            "delegation",
        )
        sources, spans = _source_values(value)
        return cls(
            delegation_id=value.get("delegation_id", ""),
            issuer_principal_id=value.get("issuer_principal_id", ""),
            subject_principal_id=value.get("subject_principal_id", ""),
            capability=value.get("capability", ""),
            delegation_depth=value.get("delegation_depth", 0),
            parent_delegation_id=value.get("parent_delegation_id", ""),
            resource_scope=tuple(value.get("resource_scope", ())),
            constraint_ids=tuple(value.get("constraint_ids", ())),
            attributes=_frozen(
                _mapping(value.get("attributes", {}), "attributes"), "attributes"
            ),
            source_ref_ids=sources,
            span_ids=spans,
            schema_version=value.get("schema_version", DELEGATION_SCHEMA_VERSION),
        )


@dataclass(frozen=True, slots=True)
class PolicyBounds:
    """Explicit finite bounds for evaluation and trust.

    Authorization policies are always finite-domain.  Unbounded recursion,
    unbounded delegation, or empty trust roots fail closed.
    """

    max_delegation_depth: int = MAX_DELEGATION_DEPTH
    max_derivation_depth: int = 1024
    max_stratum: int = MAX_STRATUM
    max_facts: int = 100_000
    max_rules: int = 10_000
    universe_size: int | None = None
    schema_version: str = BOUNDS_SCHEMA_VERSION

    def __post_init__(self) -> None:
        max_delegation = _non_bool_int(
            self.max_delegation_depth, "max_delegation_depth", minimum=0
        )
        if max_delegation > MAX_DELEGATION_DEPTH:
            raise AuthorizationValidationError(
                f"max_delegation_depth exceeds hard ceiling {MAX_DELEGATION_DEPTH}"
            )
        object.__setattr__(self, "max_delegation_depth", max_delegation)
        object.__setattr__(
            self,
            "max_derivation_depth",
            _non_bool_int(
                self.max_derivation_depth, "max_derivation_depth", minimum=1
            ),
        )
        max_stratum = _non_bool_int(self.max_stratum, "max_stratum", minimum=0)
        if max_stratum > MAX_STRATUM:
            raise AuthorizationValidationError(
                f"max_stratum exceeds hard ceiling {MAX_STRATUM}"
            )
        object.__setattr__(self, "max_stratum", max_stratum)
        object.__setattr__(
            self,
            "max_facts",
            _non_bool_int(self.max_facts, "max_facts", minimum=1),
        )
        object.__setattr__(
            self,
            "max_rules",
            _non_bool_int(self.max_rules, "max_rules", minimum=1),
        )
        if self.universe_size is not None:
            object.__setattr__(
                self,
                "universe_size",
                _non_bool_int(self.universe_size, "universe_size", minimum=1),
            )
        if self.schema_version != BOUNDS_SCHEMA_VERSION:
            raise AuthorizationValidationError(
                f"unsupported bounds schema_version {self.schema_version!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_delegation_depth": self.max_delegation_depth,
            "max_derivation_depth": self.max_derivation_depth,
            "max_facts": self.max_facts,
            "max_rules": self.max_rules,
            "max_stratum": self.max_stratum,
            "schema_version": self.schema_version,
            "universe_size": self.universe_size,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> PolicyBounds:
        value = _mapping(value, "policy bounds")
        _reject_unknown(
            value,
            frozenset(
                {
                    "max_delegation_depth",
                    "max_derivation_depth",
                    "max_stratum",
                    "max_facts",
                    "max_rules",
                    "universe_size",
                    "schema_version",
                }
            ),
            "policy bounds",
        )
        return cls(
            max_delegation_depth=value.get(
                "max_delegation_depth", MAX_DELEGATION_DEPTH
            ),
            max_derivation_depth=value.get("max_derivation_depth", 1024),
            max_stratum=value.get("max_stratum", MAX_STRATUM),
            max_facts=value.get("max_facts", 100_000),
            max_rules=value.get("max_rules", 10_000),
            universe_size=value.get("universe_size"),
            schema_version=value.get("schema_version", BOUNDS_SCHEMA_VERSION),
        )


@dataclass(frozen=True, slots=True)
class PrecedencePolicy:
    """Deny/allow conflict resolution for decision-producing rules."""

    resolution: ConflictResolution | str = ConflictResolution.DENY_OVERRIDES
    statement: str = (
        "When allow and deny evidence co-exist, deny overrides unless the "
        "resolution policy says otherwise."
    )
    schema_version: str = PRECEDENCE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "resolution",
            _enum(self.resolution, ConflictResolution, "precedence.resolution"),
        )
        object.__setattr__(
            self, "statement", _text(self.statement, "precedence.statement")
        )
        if self.schema_version != PRECEDENCE_SCHEMA_VERSION:
            raise AuthorizationValidationError(
                f"unsupported precedence schema_version {self.schema_version!r}"
            )

    def resolve(
        self,
        allow_evidence: bool,
        deny_evidence: bool,
        *,
        first_effect: EffectKind | None = None,
    ) -> DecisionOutcome:
        """Map raw allow/deny evidence to a closed decision outcome.

        This is pure precedence arithmetic over already-derived evidence.  It
        does not execute rules or grant theorem authority.
        """

        if not allow_evidence and not deny_evidence:
            return DecisionOutcome.UNKNOWN
        if allow_evidence and deny_evidence:
            if self.resolution is ConflictResolution.EXPLICIT_CONFLICT:
                return DecisionOutcome.CONFLICT
            if self.resolution is ConflictResolution.DENY_OVERRIDES:
                return DecisionOutcome.DENY
            if self.resolution is ConflictResolution.ALLOW_OVERRIDES:
                return DecisionOutcome.ALLOW
            if self.resolution is ConflictResolution.FIRST_APPLICABLE:
                if first_effect is EffectKind.ALLOW:
                    return DecisionOutcome.ALLOW
                if first_effect is EffectKind.DENY:
                    return DecisionOutcome.DENY
                return DecisionOutcome.CONFLICT
        if deny_evidence:
            return DecisionOutcome.DENY
        return DecisionOutcome.ALLOW

    def to_dict(self) -> dict[str, Any]:
        return {
            "resolution": self.resolution.value,
            "schema_version": self.schema_version,
            "statement": self.statement,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> PrecedencePolicy:
        value = _mapping(value, "precedence")
        _reject_unknown(
            value,
            frozenset({"resolution", "statement", "schema_version"}),
            "precedence",
        )
        return cls(
            resolution=value.get(
                "resolution", ConflictResolution.DENY_OVERRIDES.value
            ),
            statement=value.get(
                "statement",
                "When allow and deny evidence co-exist, deny overrides unless "
                "the resolution policy says otherwise.",
            ),
            schema_version=value.get("schema_version", PRECEDENCE_SCHEMA_VERSION),
        )


@dataclass(frozen=True, slots=True)
class DecisionQuery:
    """One finite policy-decision question posed against the IR."""

    query_id: str
    principal_id: str
    action: str
    resource: str = ""
    context: FrozenMap = field(default_factory=FrozenMap)
    constraint_ids: tuple[str, ...] = ()
    goal_atom: AuthorizationAtom | None = None
    source_ref_ids: tuple[str, ...] = ()
    span_ids: tuple[str, ...] = ()
    schema_version: str = QUERY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        sources, spans = _source_map(
            self.source_ref_ids, self.span_ids, owner="DecisionQuery"
        )
        object.__setattr__(self, "query_id", _identifier(self.query_id, "query_id"))
        object.__setattr__(
            self, "principal_id", _identifier(self.principal_id, "query.principal_id")
        )
        object.__setattr__(self, "action", _identifier(self.action, "query.action"))
        object.__setattr__(
            self, "resource", _text(self.resource, "query.resource", optional=True)
        )
        object.__setattr__(
            self, "context", _frozen(self.context, "query.context")
        )
        object.__setattr__(
            self,
            "constraint_ids",
            _identifiers(self.constraint_ids, "query.constraint_ids"),
        )
        if self.goal_atom is not None:
            goal = (
                self.goal_atom
                if isinstance(self.goal_atom, AuthorizationAtom)
                else AuthorizationAtom.from_dict(
                    _mapping(self.goal_atom, "query.goal_atom")
                )
            )
            if goal.is_negative:
                raise AuthorizationValidationError(
                    "decision query goal_atom must be positive"
                )
            object.__setattr__(self, "goal_atom", goal)
        object.__setattr__(self, "source_ref_ids", sources)
        object.__setattr__(self, "span_ids", spans)
        if self.schema_version != QUERY_SCHEMA_VERSION:
            raise AuthorizationValidationError(
                f"unsupported query schema_version {self.schema_version!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "constraint_ids": list(self.constraint_ids),
            "context": self.context.to_dict(),
            "goal_atom": None if self.goal_atom is None else self.goal_atom.to_dict(),
            "principal_id": self.principal_id,
            "query_id": self.query_id,
            "resource": self.resource,
            "schema_version": self.schema_version,
            **_source_dict(self),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> DecisionQuery:
        value = _mapping(value, "decision query")
        _reject_unknown(
            value,
            frozenset(
                {
                    "query_id",
                    "principal_id",
                    "action",
                    "resource",
                    "context",
                    "constraint_ids",
                    "goal_atom",
                    "source_ref_ids",
                    "source_refs",
                    "span_ids",
                    "schema_version",
                }
            ),
            "decision query",
        )
        sources, spans = _source_values(value)
        raw_goal = value.get("goal_atom")
        return cls(
            query_id=value.get("query_id", ""),
            principal_id=value.get("principal_id", ""),
            action=value.get("action", ""),
            resource=value.get("resource", ""),
            context=_frozen(
                _mapping(value.get("context", {}), "context"), "context"
            ),
            constraint_ids=tuple(value.get("constraint_ids", ())),
            goal_atom=raw_goal,
            source_ref_ids=sources,
            span_ids=spans,
            schema_version=value.get("schema_version", QUERY_SCHEMA_VERSION),
        )


@dataclass(frozen=True, slots=True)
class ExplanationStep:
    """One bounded step binding a decision to IR evidence."""

    step_id: str
    kind: ExplanationStepKind | str
    reference_id: str
    statement: str = ""
    attributes: FrozenMap = field(default_factory=FrozenMap)

    def __post_init__(self) -> None:
        object.__setattr__(self, "step_id", _identifier(self.step_id, "step_id"))
        object.__setattr__(
            self, "kind", _enum(self.kind, ExplanationStepKind, "step.kind")
        )
        object.__setattr__(
            self, "reference_id", _identifier(self.reference_id, "step.reference_id")
        )
        object.__setattr__(
            self, "statement", _text(self.statement, "step.statement", optional=True)
        )
        object.__setattr__(
            self, "attributes", _frozen(self.attributes, "step.attributes")
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": self.attributes.to_dict(),
            "kind": self.kind.value,
            "reference_id": self.reference_id,
            "statement": self.statement,
            "step_id": self.step_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> ExplanationStep:
        value = _mapping(value, "explanation step")
        _reject_unknown(
            value,
            frozenset(
                {
                    "step_id",
                    "kind",
                    "reference_id",
                    "statement",
                    "attributes",
                }
            ),
            "explanation step",
        )
        return cls(
            step_id=value.get("step_id", ""),
            kind=value.get("kind", ""),
            reference_id=value.get("reference_id", ""),
            statement=value.get("statement", ""),
            attributes=_frozen(
                _mapping(value.get("attributes", {}), "attributes"), "attributes"
            ),
        )


@dataclass(frozen=True, slots=True)
class DecisionExplanation:
    """A finite explanation tree for one decision outcome."""

    explanation_id: str
    query_id: str
    outcome: DecisionOutcome | str
    steps: tuple[ExplanationStep, ...] = ()
    attributes: FrozenMap = field(default_factory=FrozenMap)
    source_ref_ids: tuple[str, ...] = ()
    span_ids: tuple[str, ...] = ()
    schema_version: str = EXPLANATION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        sources, spans = _source_map(
            self.source_ref_ids,
            self.span_ids,
            owner="DecisionExplanation",
            required=False,
        )
        object.__setattr__(
            self,
            "explanation_id",
            _identifier(self.explanation_id, "explanation_id"),
        )
        object.__setattr__(
            self, "query_id", _identifier(self.query_id, "explanation.query_id")
        )
        object.__setattr__(
            self, "outcome", _enum(self.outcome, DecisionOutcome, "explanation.outcome")
        )
        steps = tuple(
            item
            if isinstance(item, ExplanationStep)
            else ExplanationStep.from_dict(_mapping(item, "explanation step"))
            for item in _sequence(self.steps, "explanation.steps")
        )
        step_ids = [item.step_id for item in steps]
        if len(step_ids) != len(set(step_ids)):
            raise AuthorizationValidationError(
                "explanation step_id values must be unique"
            )
        object.__setattr__(self, "steps", steps)
        object.__setattr__(
            self, "attributes", _frozen(self.attributes, "explanation.attributes")
        )
        object.__setattr__(self, "source_ref_ids", sources)
        object.__setattr__(self, "span_ids", spans)
        if self.schema_version != EXPLANATION_SCHEMA_VERSION:
            raise AuthorizationValidationError(
                f"unsupported explanation schema_version {self.schema_version!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": self.attributes.to_dict(),
            "explanation_id": self.explanation_id,
            "outcome": self.outcome.value,
            "query_id": self.query_id,
            "schema_version": self.schema_version,
            "steps": [item.to_dict() for item in self.steps],
            **_source_dict(self),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> DecisionExplanation:
        value = _mapping(value, "explanation")
        _reject_unknown(
            value,
            frozenset(
                {
                    "explanation_id",
                    "query_id",
                    "outcome",
                    "steps",
                    "attributes",
                    "source_ref_ids",
                    "source_refs",
                    "span_ids",
                    "schema_version",
                }
            ),
            "explanation",
        )
        sources, spans = _source_values(value)
        return cls(
            explanation_id=value.get("explanation_id", ""),
            query_id=value.get("query_id", ""),
            outcome=value.get("outcome", ""),
            steps=tuple(value.get("steps", ())),
            attributes=_frozen(
                _mapping(value.get("attributes", {}), "attributes"), "attributes"
            ),
            source_ref_ids=sources,
            span_ids=spans,
            schema_version=value.get("schema_version", EXPLANATION_SCHEMA_VERSION),
        )


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    """A declared authorization decision with a hard authority ceiling.

    Decisions are descriptive records for fixtures and adapters.  Constructing
    a decision does not execute a policy engine.  The authority field is fixed
    to :attr:`AuthorizationEvidenceAuthority.AUTHORIZATION` and generated-code
    correctness is always :attr:`GeneratedCodeCorrectness.NOT_ESTABLISHED`.
    """

    decision_id: str
    query_id: str
    outcome: DecisionOutcome | str
    explanation_id: str = ""
    authority: AuthorizationEvidenceAuthority | str = (
        AuthorizationEvidenceAuthority.AUTHORIZATION
    )
    generated_code_correctness: GeneratedCodeCorrectness | str = (
        GeneratedCodeCorrectness.NOT_ESTABLISHED
    )
    attributes: FrozenMap = field(default_factory=FrozenMap)
    source_ref_ids: tuple[str, ...] = ()
    span_ids: tuple[str, ...] = ()
    schema_version: str = DECISION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        sources, spans = _source_map(
            self.source_ref_ids,
            self.span_ids,
            owner="PolicyDecision",
            required=False,
        )
        object.__setattr__(
            self, "decision_id", _identifier(self.decision_id, "decision_id")
        )
        object.__setattr__(
            self, "query_id", _identifier(self.query_id, "decision.query_id")
        )
        object.__setattr__(
            self, "outcome", _enum(self.outcome, DecisionOutcome, "decision.outcome")
        )
        if self.explanation_id:
            object.__setattr__(
                self,
                "explanation_id",
                _identifier(self.explanation_id, "decision.explanation_id"),
            )
        authority = _enum(
            self.authority,
            AuthorizationEvidenceAuthority,
            "decision.authority",
        )
        if authority is not AuthorizationEvidenceAuthority.AUTHORIZATION:
            raise AuthorizationValidationError(
                "authorization decisions cannot masquerade as theorem proof; "
                "authority must be 'authorization'"
            )
        object.__setattr__(self, "authority", authority)
        correctness = _enum(
            self.generated_code_correctness,
            GeneratedCodeCorrectness,
            "decision.generated_code_correctness",
        )
        if correctness is not GeneratedCodeCorrectness.NOT_ESTABLISHED:
            raise AuthorizationValidationError(
                "authorization decisions never establish generated-code correctness"
            )
        object.__setattr__(self, "generated_code_correctness", correctness)
        object.__setattr__(
            self, "attributes", _frozen(self.attributes, "decision.attributes")
        )
        object.__setattr__(self, "source_ref_ids", sources)
        object.__setattr__(self, "span_ids", spans)
        if self.schema_version != DECISION_SCHEMA_VERSION:
            raise AuthorizationValidationError(
                f"unsupported decision schema_version {self.schema_version!r}"
            )

    @property
    def is_theorem_authority(self) -> bool:
        """Authorization evidence never carries theorem authority."""

        return False

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": self.attributes.to_dict(),
            "authority": self.authority.value,
            "decision_id": self.decision_id,
            "explanation_id": self.explanation_id,
            "generated_code_correctness": self.generated_code_correctness.value,
            "outcome": self.outcome.value,
            "query_id": self.query_id,
            "schema_version": self.schema_version,
            **_source_dict(self),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> PolicyDecision:
        value = _mapping(value, "policy decision")
        _reject_unknown(
            value,
            frozenset(
                {
                    "decision_id",
                    "query_id",
                    "outcome",
                    "explanation_id",
                    "authority",
                    "generated_code_correctness",
                    "attributes",
                    "source_ref_ids",
                    "source_refs",
                    "span_ids",
                    "schema_version",
                }
            ),
            "policy decision",
        )
        sources, spans = _source_values(value)
        return cls(
            decision_id=value.get("decision_id", ""),
            query_id=value.get("query_id", ""),
            outcome=value.get("outcome", ""),
            explanation_id=value.get("explanation_id", ""),
            authority=value.get(
                "authority", AuthorizationEvidenceAuthority.AUTHORIZATION.value
            ),
            generated_code_correctness=value.get(
                "generated_code_correctness",
                GeneratedCodeCorrectness.NOT_ESTABLISHED.value,
            ),
            attributes=_frozen(
                _mapping(value.get("attributes", {}), "attributes"), "attributes"
            ),
            source_ref_ids=sources,
            span_ids=spans,
            schema_version=value.get("schema_version", DECISION_SCHEMA_VERSION),
        )


@dataclass(frozen=True, slots=True)
class AuthorizationIR:
    """Canonical, immutable, finite authorization policy model.

    The document is stratification-aware: rules declare strata and negative
    body atoms may only depend on predicates defined in strictly lower strata.
    Trust roots and delegation depth are bounded.  Declared decisions use a
    closed outcome vocabulary and cannot claim theorem authority.
    """

    sources: tuple[SourceRef, ...]
    principals: tuple[AuthorizationPrincipal, ...]
    trust_root_principal_ids: tuple[str, ...]
    spans: tuple[SourceSpan, ...] = ()
    roles: tuple[AuthorizationRole, ...] = ()
    predicates: tuple[PredicateSignature, ...] = ()
    facts: tuple[AuthorizationFact, ...] = ()
    rules: tuple[AuthorizationRule, ...] = ()
    constraints: tuple[AuthorizationConstraint, ...] = ()
    speaks_for: tuple[SpeaksForRelation, ...] = ()
    delegations: tuple[DelegationStatement, ...] = ()
    bounds: PolicyBounds = field(default_factory=PolicyBounds)
    precedence: PrecedencePolicy = field(default_factory=PrecedencePolicy)
    queries: tuple[DecisionQuery, ...] = ()
    explanations: tuple[DecisionExplanation, ...] = ()
    decisions: tuple[PolicyDecision, ...] = ()
    metadata: FrozenMap = field(default_factory=FrozenMap)
    observations: FrozenMap = field(default_factory=FrozenMap)
    document_id: str = ""
    schema_version: str = AUTHORIZATION_IR_SCHEMA_VERSION

    INTERFACE: ClassVar[str] = AUTHORIZATION_IR_INTERFACE

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
            "principals": (AuthorizationPrincipal, "principal_id"),
            "roles": (AuthorizationRole, "role_id"),
            "predicates": (PredicateSignature, "predicate_id"),
            "facts": (AuthorizationFact, "fact_id"),
            "rules": (AuthorizationRule, "rule_id"),
            "constraints": (AuthorizationConstraint, "constraint_id"),
            "speaks_for": (SpeaksForRelation, "speaks_for_id"),
            "delegations": (DelegationStatement, "delegation_id"),
            "queries": (DecisionQuery, "query_id"),
            "explanations": (DecisionExplanation, "explanation_id"),
            "decisions": (PolicyDecision, "decision_id"),
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
            "trust_root_principal_ids",
            _identifiers(
                self.trust_root_principal_ids,
                "trust_root_principal_ids",
                required=True,
            ),
        )
        object.__setattr__(
            self,
            "bounds",
            self.bounds
            if isinstance(self.bounds, PolicyBounds)
            else PolicyBounds.from_dict(_mapping(self.bounds, "bounds")),
        )
        object.__setattr__(
            self,
            "precedence",
            self.precedence
            if isinstance(self.precedence, PrecedencePolicy)
            else PrecedencePolicy.from_dict(_mapping(self.precedence, "precedence")),
        )
        metadata = _frozen(self.metadata, "metadata")
        observations = _frozen(self.observations, "observations")
        _reject_observations(metadata, label="metadata")
        object.__setattr__(self, "metadata", metadata)
        object.__setattr__(self, "observations", observations)

        self.validate()
        computed = self._compute_identity()
        if self.document_id and self.document_id != computed.cid:
            raise AuthorizationValidationError(
                "document_id does not match canonical authorization semantics"
            )
        object.__setattr__(self, "document_id", computed.cid)

    @property
    def interface(self) -> str:
        return AUTHORIZATION_IR_INTERFACE

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
            domain=AUTHORIZATION_IR_IDENTITY_DOMAIN,
            schema_version=AUTHORIZATION_IR_SCHEMA_VERSION,
        )

    def semantic_dict(self) -> dict[str, Any]:
        """Return the identity preimage, excluding runtime observations."""

        groups = (
            ("constraints", self.constraints, "constraint_id"),
            ("decisions", self.decisions, "decision_id"),
            ("delegations", self.delegations, "delegation_id"),
            ("explanations", self.explanations, "explanation_id"),
            ("facts", self.facts, "fact_id"),
            ("predicates", self.predicates, "predicate_id"),
            ("principals", self.principals, "principal_id"),
            ("queries", self.queries, "query_id"),
            ("roles", self.roles, "role_id"),
            ("rules", self.rules, "rule_id"),
            ("speaks_for", self.speaks_for, "speaks_for_id"),
        )
        result: dict[str, Any] = {
            "bounds": self.bounds.to_dict(),
            "interface": AUTHORIZATION_IR_INTERFACE,
            "metadata": self.metadata.to_dict(),
            "precedence": self.precedence.to_dict(),
            "schema_version": self.schema_version,
            "sources": [
                item.to_dict()
                for item in sorted(self.sources, key=lambda item: item.ref_id)
            ],
            "spans": [
                item.to_dict()
                for item in sorted(self.spans, key=lambda item: item.span_id)
            ],
            "trust_root_principal_ids": list(self.trust_root_principal_ids),
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

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> AuthorizationIR:
        value = _mapping(value, "authorization IR")
        _reject_unknown(
            value,
            frozenset(
                {
                    "sources",
                    "spans",
                    "principals",
                    "trust_root_principal_ids",
                    "roles",
                    "predicates",
                    "facts",
                    "rules",
                    "constraints",
                    "speaks_for",
                    "delegations",
                    "bounds",
                    "precedence",
                    "queries",
                    "explanations",
                    "decisions",
                    "metadata",
                    "observations",
                    "document_id",
                    "schema_version",
                    "interface",
                }
            ),
            "authorization IR",
        )
        return cls(
            sources=tuple(value.get("sources", ())),
            spans=tuple(value.get("spans", ())),
            principals=tuple(value.get("principals", ())),
            trust_root_principal_ids=tuple(
                value.get("trust_root_principal_ids", ())
            ),
            roles=tuple(value.get("roles", ())),
            predicates=tuple(value.get("predicates", ())),
            facts=tuple(value.get("facts", ())),
            rules=tuple(value.get("rules", ())),
            constraints=tuple(value.get("constraints", ())),
            speaks_for=tuple(value.get("speaks_for", ())),
            delegations=tuple(value.get("delegations", ())),
            bounds=value.get("bounds", {}),
            precedence=value.get("precedence", {}),
            queries=tuple(value.get("queries", ())),
            explanations=tuple(value.get("explanations", ())),
            decisions=tuple(value.get("decisions", ())),
            metadata=_frozen(
                _mapping(value.get("metadata", {}), "metadata"), "metadata"
            ),
            observations=_frozen(
                _mapping(value.get("observations", {}), "observations"),
                "observations",
            ),
            document_id=value.get("document_id", ""),
            schema_version=value.get(
                "schema_version", AUTHORIZATION_IR_SCHEMA_VERSION
            ),
        )

    @classmethod
    def from_json(cls, text: str) -> AuthorizationIR:
        import json

        payload = json.loads(text)
        if not isinstance(payload, Mapping):
            raise AuthorizationValidationError(
                "authorization IR JSON must decode to an object"
            )
        return cls.from_dict(payload)

    def validate(self) -> None:
        """Validate finiteness, stratification, trust, and cross-references."""

        if self.schema_version != AUTHORIZATION_IR_SCHEMA_VERSION:
            raise AuthorizationValidationError(
                f"unsupported schema_version {self.schema_version!r}"
            )
        if not self.sources:
            raise AuthorizationValidationError(
                "a source-grounded authorization policy requires sources"
            )
        if not self.principals:
            raise AuthorizationValidationError(
                "an authorization policy requires at least one principal"
            )

        groups = (
            (self.sources, "ref_id", "source"),
            (self.spans, "span_id", "span"),
            (self.principals, "principal_id", "principal"),
            (self.roles, "role_id", "role"),
            (self.predicates, "predicate_id", "predicate"),
            (self.facts, "fact_id", "fact"),
            (self.rules, "rule_id", "rule"),
            (self.constraints, "constraint_id", "constraint"),
            (self.speaks_for, "speaks_for_id", "speaks-for"),
            (self.delegations, "delegation_id", "delegation"),
            (self.queries, "query_id", "query"),
            (self.explanations, "explanation_id", "explanation"),
            (self.decisions, "decision_id", "decision"),
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
                raise AuthorizationValidationError(
                    f"semantic identifiers must be globally unique: {sorted(overlap)}"
                )
            semantic_ids.update(identifiers)

        source_ids = {item.ref_id for item in self.sources}
        spans = {item.span_id: item for item in self.spans}
        for source in self.sources:
            source.validate()
        for span in self.spans:
            span.validate()
            _known((span.source_ref_id,), source_ids, f"span {span.span_id}")

        source_mapped = (
            *self.principals,
            *self.roles,
            *self.predicates,
            *self.facts,
            *self.rules,
            *self.constraints,
            *self.speaks_for,
            *self.delegations,
            *self.queries,
        )
        for item in source_mapped:
            self._validate_source_map(item, source_ids, spans)
        for item in (*self.explanations, *self.decisions):
            if item.source_ref_ids or item.span_ids:
                self._validate_source_map(item, source_ids, spans)

        principal_ids = {item.principal_id for item in self.principals}
        role_ids = {item.role_id for item in self.roles}
        predicate_ids = {item.predicate_id for item in self.predicates}
        predicates_by_id = {item.predicate_id: item for item in self.predicates}
        constraint_ids = {item.constraint_id for item in self.constraints}
        fact_ids = {item.fact_id for item in self.facts}
        rule_ids = {item.rule_id for item in self.rules}
        speaks_for_ids = {item.speaks_for_id for item in self.speaks_for}
        delegation_ids = {item.delegation_id for item in self.delegations}
        query_ids = {item.query_id for item in self.queries}
        explanation_ids = {item.explanation_id for item in self.explanations}

        _known(
            self.trust_root_principal_ids,
            principal_ids,
            "trust_root_principal_ids",
        )
        if len(self.facts) > self.bounds.max_facts:
            raise AuthorizationValidationError(
                f"fact count {len(self.facts)} exceeds bounds.max_facts "
                f"{self.bounds.max_facts}"
            )
        if len(self.rules) > self.bounds.max_rules:
            raise AuthorizationValidationError(
                f"rule count {len(self.rules)} exceeds bounds.max_rules "
                f"{self.bounds.max_rules}"
            )

        for role in self.roles:
            _known(
                role.member_principal_ids,
                principal_ids,
                f"role {role.role_id}.member_principal_ids",
            )

        for fact in self.facts:
            self._validate_atom(
                fact.atom, predicates_by_id, f"fact {fact.fact_id}.atom"
            )
            if fact.issuer_principal_id:
                _known(
                    (fact.issuer_principal_id,),
                    principal_ids,
                    f"fact {fact.fact_id}.issuer_principal_id",
                )

        for rule in self.rules:
            if rule.stratum > self.bounds.max_stratum:
                raise AuthorizationValidationError(
                    f"rule {rule.rule_id!r} stratum {rule.stratum} exceeds "
                    f"bounds.max_stratum {self.bounds.max_stratum}"
                )
            self._validate_atom(
                rule.head, predicates_by_id, f"rule {rule.rule_id}.head"
            )
            for index, atom in enumerate(rule.body):
                self._validate_atom(
                    atom,
                    predicates_by_id,
                    f"rule {rule.rule_id}.body[{index}]",
                )
            _known(
                rule.constraint_ids,
                constraint_ids,
                f"rule {rule.rule_id}.constraint_ids",
            )
            if rule.issuer_principal_id:
                _known(
                    (rule.issuer_principal_id,),
                    principal_ids,
                    f"rule {rule.rule_id}.issuer_principal_id",
                )

        self._validate_stratification(predicates_by_id)

        for relation in self.speaks_for:
            _known(
                (relation.speaker_principal_id, relation.subject_principal_id),
                principal_ids,
                f"speaks_for {relation.speaks_for_id} principals",
            )
            _known(
                relation.constraint_ids,
                constraint_ids,
                f"speaks_for {relation.speaks_for_id}.constraint_ids",
            )

        for delegation in self.delegations:
            if delegation.delegation_depth > self.bounds.max_delegation_depth:
                raise AuthorizationValidationError(
                    f"delegation {delegation.delegation_id!r} depth "
                    f"{delegation.delegation_depth} exceeds "
                    f"bounds.max_delegation_depth "
                    f"{self.bounds.max_delegation_depth}"
                )
            _known(
                (
                    delegation.issuer_principal_id,
                    delegation.subject_principal_id,
                ),
                principal_ids,
                f"delegation {delegation.delegation_id} principals",
            )
            _known(
                delegation.constraint_ids,
                constraint_ids,
                f"delegation {delegation.delegation_id}.constraint_ids",
            )
            if delegation.parent_delegation_id:
                _known(
                    (delegation.parent_delegation_id,),
                    delegation_ids,
                    f"delegation {delegation.delegation_id}.parent_delegation_id",
                )
                parent = next(
                    item
                    for item in self.delegations
                    if item.delegation_id == delegation.parent_delegation_id
                )
                if delegation.delegation_depth >= parent.delegation_depth:
                    raise AuthorizationValidationError(
                        f"delegation {delegation.delegation_id!r} must use a "
                        "strictly smaller depth than its parent"
                    )
                if not parent.can_delegate:
                    raise AuthorizationValidationError(
                        f"delegation parent {parent.delegation_id!r} has zero "
                        "remaining depth and cannot authorize children"
                    )
                if parent.subject_principal_id != delegation.issuer_principal_id:
                    raise AuthorizationValidationError(
                        f"delegation {delegation.delegation_id!r} issuer must "
                        "be the parent subject"
                    )

        for query in self.queries:
            _known(
                (query.principal_id,),
                principal_ids,
                f"query {query.query_id}.principal_id",
            )
            _known(
                query.constraint_ids,
                constraint_ids,
                f"query {query.query_id}.constraint_ids",
            )
            if query.goal_atom is not None:
                self._validate_atom(
                    query.goal_atom,
                    predicates_by_id,
                    f"query {query.query_id}.goal_atom",
                )

        for explanation in self.explanations:
            _known(
                (explanation.query_id,),
                query_ids,
                f"explanation {explanation.explanation_id}.query_id",
            )
            for step in explanation.steps:
                self._validate_explanation_step(
                    step,
                    fact_ids=fact_ids,
                    rule_ids=rule_ids,
                    speaks_for_ids=speaks_for_ids,
                    delegation_ids=delegation_ids,
                    constraint_ids=constraint_ids,
                    principal_ids=principal_ids,
                )

        for decision in self.decisions:
            _known(
                (decision.query_id,),
                query_ids,
                f"decision {decision.decision_id}.query_id",
            )
            if decision.explanation_id:
                _known(
                    (decision.explanation_id,),
                    explanation_ids,
                    f"decision {decision.decision_id}.explanation_id",
                )
                explanation = next(
                    item
                    for item in self.explanations
                    if item.explanation_id == decision.explanation_id
                )
                if explanation.query_id != decision.query_id:
                    raise AuthorizationValidationError(
                        f"decision {decision.decision_id!r} explanation binds "
                        "a different query"
                    )
                if explanation.outcome != decision.outcome:
                    raise AuthorizationValidationError(
                        f"decision {decision.decision_id!r} outcome must match "
                        "its explanation outcome"
                    )
            if decision.is_theorem_authority:
                raise AuthorizationValidationError(
                    "authorization decisions cannot claim theorem authority"
                )

    def _validate_stratification(
        self, predicates_by_id: Mapping[str, PredicateSignature]
    ) -> None:
        """Ensure negation is stratified over a finite stratum assignment."""

        defining_strata: dict[str, set[int]] = {
            predicate_id: set() for predicate_id in predicates_by_id
        }
        for rule in self.rules:
            defining_strata.setdefault(rule.head.predicate_id, set()).add(rule.stratum)

        for rule in self.rules:
            for atom in rule.body:
                if not atom.is_negative:
                    continue
                defined = defining_strata.get(atom.predicate_id, set())
                if not defined:
                    # Negative reference to pure EDB (facts only) is stratum-safe.
                    continue
                if any(stratum >= rule.stratum for stratum in defined):
                    raise AuthorizationValidationError(
                        f"rule {rule.rule_id!r} is not stratified: negative "
                        f"literal {atom.predicate_id!r} is defined at strata "
                        f"{sorted(defined)} which are not strictly below "
                        f"stratum {rule.stratum}"
                    )

    def _validate_atom(
        self,
        atom: AuthorizationAtom,
        predicates_by_id: Mapping[str, PredicateSignature],
        label: str,
    ) -> None:
        if atom.predicate_id not in predicates_by_id:
            raise AuthorizationValidationError(
                f"{label} references unknown predicate {atom.predicate_id!r}"
            )
        signature = predicates_by_id[atom.predicate_id]
        if len(atom.arguments) != signature.arity:
            raise AuthorizationValidationError(
                f"{label} arity {len(atom.arguments)} does not match predicate "
                f"arity {signature.arity}"
            )
        if signature.argument_sorts:
            for index, (argument, expected) in enumerate(
                zip(atom.arguments, signature.argument_sorts, strict=True)
            ):
                if argument.sort != expected:
                    raise AuthorizationValidationError(
                        f"{label} argument {index} sort {argument.sort!r} "
                        f"does not match expected {expected!r}"
                    )

    def _validate_explanation_step(
        self,
        step: ExplanationStep,
        *,
        fact_ids: set[str],
        rule_ids: set[str],
        speaks_for_ids: set[str],
        delegation_ids: set[str],
        constraint_ids: set[str],
        principal_ids: set[str],
    ) -> None:
        if step.kind is ExplanationStepKind.FACT:
            _known((step.reference_id,), fact_ids, "explanation step fact")
        elif step.kind is ExplanationStepKind.RULE:
            _known((step.reference_id,), rule_ids, "explanation step rule")
        elif step.kind is ExplanationStepKind.SPEAKS_FOR:
            _known(
                (step.reference_id,), speaks_for_ids, "explanation step speaks-for"
            )
        elif step.kind is ExplanationStepKind.DELEGATION:
            _known(
                (step.reference_id,),
                delegation_ids,
                "explanation step delegation",
            )
        elif step.kind is ExplanationStepKind.CONSTRAINT:
            _known(
                (step.reference_id,),
                constraint_ids,
                "explanation step constraint",
            )
        elif step.kind is ExplanationStepKind.TRUST_ROOT:
            _known(
                (step.reference_id,),
                principal_ids & set(self.trust_root_principal_ids),
                "explanation step trust root",
            )
        elif step.kind is ExplanationStepKind.PRECEDENCE:
            if step.reference_id not in {
                "precedence",
                self.precedence.resolution.value,
            }:
                raise AuthorizationValidationError(
                    "explanation precedence step must reference 'precedence' "
                    "or the resolution value"
                )
        elif step.kind is ExplanationStepKind.BOUND:
            if step.reference_id not in {
                "bounds",
                "max_delegation_depth",
                "max_derivation_depth",
                "max_stratum",
            }:
                raise AuthorizationValidationError(
                    "explanation bound step has unknown reference_id "
                    f"{step.reference_id!r}"
                )

    def _validate_source_map(
        self,
        item: _SourceMapped,
        source_ids: set[str],
        spans: Mapping[str, SourceSpan],
    ) -> None:
        _known(item.source_ref_ids, source_ids, "source_ref_ids")
        unknown_spans = sorted(set(item.span_ids) - set(spans))
        if unknown_spans:
            raise AuthorizationValidationError(
                f"span_ids reference unknown spans {unknown_spans}"
            )
        for span_id in item.span_ids:
            span = spans[span_id]
            if item.source_ref_ids and span.source_ref_id not in item.source_ref_ids:
                raise AuthorizationValidationError(
                    f"span {span_id!r} is not among the declared source_ref_ids"
                )

    @staticmethod
    def _unique(values: Sequence[Any], id_field: str, label: str) -> None:
        identities = [getattr(item, id_field) for item in values]
        if len(identities) != len(set(identities)):
            raise AuthorizationValidationError(
                f"{label} identifiers must be unique"
            )


def distinct_decision_outcomes() -> frozenset[str]:
    """Return the closed, non-interchangeable decision outcome vocabulary."""

    return frozenset(item.value for item in DecisionOutcome)


def authority_is_authorization_only(
    authority: AuthorizationEvidenceAuthority | str,
) -> bool:
    """Return whether *authority* is the only admitted authorization authority."""

    try:
        selected = (
            authority
            if isinstance(authority, AuthorizationEvidenceAuthority)
            else AuthorizationEvidenceAuthority(authority)
        )
    except (TypeError, ValueError):
        return False
    return selected is AuthorizationEvidenceAuthority.AUTHORIZATION


__all__ = [
    "AUTHORIZATION_IR_IDENTITY_DOMAIN",
    "AUTHORIZATION_IR_INTERFACE",
    "AUTHORIZATION_IR_SCHEMA_VERSION",
    "BOUNDS_SCHEMA_VERSION",
    "CONSTRAINT_SCHEMA_VERSION",
    "DECISION_SCHEMA_VERSION",
    "DELEGATION_SCHEMA_VERSION",
    "EXPLANATION_SCHEMA_VERSION",
    "FACT_SCHEMA_VERSION",
    "MAX_DELEGATION_DEPTH",
    "MAX_FACT_ARITY",
    "MAX_RULE_BODY_SIZE",
    "MAX_STRATUM",
    "PRECEDENCE_SCHEMA_VERSION",
    "PREDICATE_SCHEMA_VERSION",
    "PRINCIPAL_SCHEMA_VERSION",
    "QUERY_SCHEMA_VERSION",
    "ROLE_SCHEMA_VERSION",
    "RULE_SCHEMA_VERSION",
    "SPEAKS_FOR_SCHEMA_VERSION",
    "AtomPolarity",
    "AuthorizationAtom",
    "AuthorizationConstraint",
    "AuthorizationEvidenceAuthority",
    "AuthorizationFact",
    "AuthorizationIR",
    "AuthorizationPrincipal",
    "AuthorizationRole",
    "AuthorizationRule",
    "AuthorizationTerm",
    "AuthorizationValidationError",
    "ConflictResolution",
    "ConstraintKind",
    "DecisionExplanation",
    "DecisionOutcome",
    "DecisionQuery",
    "DelegationStatement",
    "EffectKind",
    "ExplanationStep",
    "ExplanationStepKind",
    "GeneratedCodeCorrectness",
    "PolicyBounds",
    "PolicyDecision",
    "PrecedencePolicy",
    "PredicateSignature",
    "PrincipalKind",
    "RuleKind",
    "SpeaksForRelation",
    "TermKind",
    "authority_is_authorization_only",
    "distinct_decision_outcomes",
]
