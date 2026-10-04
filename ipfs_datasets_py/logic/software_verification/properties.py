"""Provider-neutral property and assumption declarations.

This module defines the shared vocabulary used by software-verification
frontends and backends.  A property describes *what* is to be checked; it does
not contain a backend request, a solver result, or proof authority.

Every property and assumption is source mapped.  Structured expressions and
extension payloads are recursively frozen on construction so callers cannot
change a declaration after its identity has been computed by
``SoftwareVerificationIR``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
import re
from typing import Any, Final

from ipfs_datasets_py.logic.ir_core.claims import FrozenMap


VERIFICATION_PROPERTY_SCHEMA_VERSION: Final = "verification-property/v1"
VERIFICATION_ASSUMPTION_SCHEMA_VERSION: Final = "verification-assumption/v1"

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")
_EXTENSION_RE = re.compile(
    r"^[a-z][a-z0-9_-]*(?:[.:/][a-z0-9][a-z0-9_.:/-]*)+$"
)


class PropertyValidationError(ValueError):
    """Raised when a property or assumption is not a valid shared declaration."""


class PropertyKind(str, Enum):
    """Canonical version-one software-verification property vocabulary.

    The values deliberately match the property identifiers in the inert
    logic-family registry.  Domain-specific property kinds remain possible as
    namespaced strings (for example ``"example.memory.constant_time"``).
    """

    AUTHENTICATION = "authentication"
    AUTHORIZATION = "authorization"
    CONTRACT = "contract"
    DATA_RACE_FREEDOM = "data_race_freedom"
    HEAP_SAFETY = "heap_safety"
    HYPERPROPERTY = "hyperproperty"
    INVARIANT = "invariant"
    LIVENESS = "liveness"
    NONINTERFERENCE = "noninterference"
    REACHABILITY = "reachability"
    REFINEMENT = "refinement"
    SAFETY = "safety"
    SATISFIABILITY = "satisfiability"
    SECRECY = "secrecy"
    TERMINATION = "termination"
    THEOREM = "theorem"
    TRACE_CONFORMANCE = "trace_conformance"
    VALIDITY = "validity"


class AssumptionKind(str, Enum):
    """Why an unproved premise is present in a verification document."""

    SEMANTIC = "semantic"
    ENVIRONMENT = "environment"
    MODELING = "modeling"
    PLATFORM = "platform"
    FAIRNESS = "fairness"
    TRUST = "trust"
    BOUNDEDNESS = "boundedness"
    TRANSLATION = "translation"


PROPERTY_VOCABULARY: Final[tuple[str, ...]] = tuple(
    sorted(item.value for item in PropertyKind)
)
ASSUMPTION_VOCABULARY: Final[tuple[str, ...]] = tuple(
    sorted(item.value for item in AssumptionKind)
)


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise PropertyValidationError(
            f"{label} must be a non-empty string without surrounding whitespace"
        )
    if "\x00" in value:
        raise PropertyValidationError(f"{label} must not contain NUL bytes")
    return value


def _identifier(value: object, label: str) -> str:
    result = _text(value, label)
    if not _ID_RE.fullmatch(result):
        raise PropertyValidationError(f"{label} must be a stable identifier")
    return result


def _identifiers(values: Sequence[str], label: str) -> tuple[str, ...]:
    if isinstance(values, (str, bytes, bytearray)) or not isinstance(
        values, Sequence
    ):
        raise PropertyValidationError(f"{label} must be a sequence of identifiers")
    result = tuple(_identifier(item, f"{label} item") for item in values)
    if len(result) != len(set(result)):
        raise PropertyValidationError(f"{label} must not contain duplicates")
    return tuple(sorted(result))


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise PropertyValidationError(f"{label} must be a mapping")
    return value


def _freeze_mapping(value: Mapping[str, Any] | FrozenMap, label: str) -> FrozenMap:
    try:
        return value if isinstance(value, FrozenMap) else FrozenMap(value)
    except (TypeError, ValueError) as error:
        raise PropertyValidationError(
            f"{label} must contain JSON-compatible data: {error}"
        ) from error


def validate_extensions(
    value: Mapping[str, Any] | FrozenMap,
    *,
    label: str = "extensions",
) -> FrozenMap:
    """Defensively freeze extensions and require every key to be namespaced."""

    result = _freeze_mapping(value, label)
    invalid = sorted(key for key in result if not _EXTENSION_RE.fullmatch(key))
    if invalid:
        raise PropertyValidationError(
            f"{label} keys must be lowercase namespaced identifiers: {invalid}"
        )
    return result


def _source_mapping(
    source_ref_ids: Sequence[str],
    span_ids: Sequence[str],
    *,
    owner: str,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    sources = _identifiers(source_ref_ids, f"{owner}.source_ref_ids")
    spans = _identifiers(span_ids, f"{owner}.span_ids")
    if not sources and not spans:
        raise PropertyValidationError(
            f"{owner} must be source mapped with source_ref_ids or span_ids"
        )
    return sources, spans


def _property_kind(value: PropertyKind | str) -> PropertyKind | str:
    if isinstance(value, PropertyKind):
        return value
    text = _text(value, "kind")
    try:
        return PropertyKind(text)
    except ValueError:
        if not _EXTENSION_RE.fullmatch(text):
            raise PropertyValidationError(
                "custom property kinds must be lowercase namespaced identifiers"
            )
        return text


def _assumption_kind(value: AssumptionKind | str) -> AssumptionKind | str:
    if isinstance(value, AssumptionKind):
        return value
    text = _text(value, "kind")
    try:
        return AssumptionKind(text)
    except ValueError:
        if not _EXTENSION_RE.fullmatch(text):
            raise PropertyValidationError(
                "custom assumption kinds must be lowercase namespaced identifiers"
            )
        return text


def _kind_value(value: Enum | str) -> str:
    return value.value if isinstance(value, Enum) else value


def _reject_unknown(
    value: Mapping[str, Any], allowed: frozenset[str], label: str
) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise PropertyValidationError(
            f"unknown {label} field(s): {', '.join(unknown)}"
        )


@dataclass(frozen=True, slots=True)
class VerificationAssumption:
    """A source-grounded premise with no implied truth or proof authority."""

    assumption_id: str
    statement: str
    kind: AssumptionKind | str = AssumptionKind.SEMANTIC
    expression: FrozenMap = field(default_factory=FrozenMap)
    subject_ids: tuple[str, ...] = ()
    source_ref_ids: tuple[str, ...] = ()
    span_ids: tuple[str, ...] = ()
    extensions: FrozenMap = field(default_factory=FrozenMap)
    schema_version: str = VERIFICATION_ASSUMPTION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        sources, spans = _source_mapping(
            self.source_ref_ids,
            self.span_ids,
            owner="VerificationAssumption",
        )
        object.__setattr__(
            self,
            "assumption_id",
            _identifier(self.assumption_id, "assumption_id"),
        )
        object.__setattr__(self, "statement", _text(self.statement, "statement"))
        object.__setattr__(self, "kind", _assumption_kind(self.kind))
        object.__setattr__(
            self,
            "expression",
            _freeze_mapping(self.expression, "expression"),
        )
        object.__setattr__(
            self,
            "subject_ids",
            _identifiers(self.subject_ids, "subject_ids"),
        )
        object.__setattr__(self, "source_ref_ids", sources)
        object.__setattr__(self, "span_ids", spans)
        object.__setattr__(
            self,
            "extensions",
            validate_extensions(self.extensions),
        )
        if self.schema_version != VERIFICATION_ASSUMPTION_SCHEMA_VERSION:
            raise PropertyValidationError(
                f"unsupported assumption schema_version {self.schema_version!r}"
            )

    @property
    def source_refs(self) -> tuple[str, ...]:
        """Compatibility spelling used by the shared claim kernel."""

        return self.source_ref_ids

    def to_dict(self) -> dict[str, Any]:
        return {
            "assumption_id": self.assumption_id,
            "expression": self.expression.to_dict(),
            "extensions": self.extensions.to_dict(),
            "kind": _kind_value(self.kind),
            "schema_version": self.schema_version,
            "source_ref_ids": list(self.source_ref_ids),
            "span_ids": list(self.span_ids),
            "statement": self.statement,
            "subject_ids": list(self.subject_ids),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "VerificationAssumption":
        value = _mapping(value, "assumption")
        _reject_unknown(
            value,
            frozenset(
                {
                    "assumption_id",
                    "statement",
                    "kind",
                    "expression",
                    "subject_ids",
                    "source_ref_ids",
                    "source_refs",
                    "span_ids",
                    "extensions",
                    "schema_version",
                }
            ),
            "assumption",
        )
        source_ids = value.get("source_ref_ids", value.get("source_refs", ()))
        return cls(
            assumption_id=value.get("assumption_id", ""),
            statement=value.get("statement", ""),
            kind=value.get("kind", AssumptionKind.SEMANTIC.value),
            expression=FrozenMap(_mapping(value.get("expression", {}), "expression")),
            subject_ids=tuple(value.get("subject_ids", ())),
            source_ref_ids=tuple(source_ids),
            span_ids=tuple(value.get("span_ids", ())),
            extensions=FrozenMap(_mapping(value.get("extensions", {}), "extensions")),
            schema_version=value.get(
                "schema_version", VERIFICATION_ASSUMPTION_SCHEMA_VERSION
            ),
        )


@dataclass(frozen=True, slots=True)
class VerificationProperty:
    """A source-grounded semantic target, independent of provider syntax."""

    property_id: str
    kind: PropertyKind | str
    statement: str
    expression: FrozenMap = field(default_factory=FrozenMap)
    logic_family: str = "unspecified"
    subject_ids: tuple[str, ...] = ()
    assumption_ids: tuple[str, ...] = ()
    bound_ids: tuple[str, ...] = ()
    source_ref_ids: tuple[str, ...] = ()
    span_ids: tuple[str, ...] = ()
    extensions: FrozenMap = field(default_factory=FrozenMap)
    schema_version: str = VERIFICATION_PROPERTY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        sources, spans = _source_mapping(
            self.source_ref_ids,
            self.span_ids,
            owner="VerificationProperty",
        )
        object.__setattr__(
            self, "property_id", _identifier(self.property_id, "property_id")
        )
        object.__setattr__(self, "kind", _property_kind(self.kind))
        object.__setattr__(self, "statement", _text(self.statement, "statement"))
        object.__setattr__(
            self,
            "expression",
            _freeze_mapping(self.expression, "expression"),
        )
        object.__setattr__(
            self,
            "logic_family",
            _text(self.logic_family, "logic_family"),
        )
        for name in ("subject_ids", "assumption_ids", "bound_ids"):
            object.__setattr__(
                self,
                name,
                _identifiers(getattr(self, name), name),
            )
        object.__setattr__(self, "source_ref_ids", sources)
        object.__setattr__(self, "span_ids", spans)
        object.__setattr__(
            self,
            "extensions",
            validate_extensions(self.extensions),
        )
        if self.schema_version != VERIFICATION_PROPERTY_SCHEMA_VERSION:
            raise PropertyValidationError(
                f"unsupported property schema_version {self.schema_version!r}"
            )

    @property
    def source_refs(self) -> tuple[str, ...]:
        """Compatibility spelling used by the shared claim kernel."""

        return self.source_ref_ids

    @property
    def property_kind(self) -> PropertyKind | str:
        return self.kind

    def to_dict(self) -> dict[str, Any]:
        return {
            "assumption_ids": list(self.assumption_ids),
            "bound_ids": list(self.bound_ids),
            "expression": self.expression.to_dict(),
            "extensions": self.extensions.to_dict(),
            "kind": _kind_value(self.kind),
            "logic_family": self.logic_family,
            "property_id": self.property_id,
            "schema_version": self.schema_version,
            "source_ref_ids": list(self.source_ref_ids),
            "span_ids": list(self.span_ids),
            "statement": self.statement,
            "subject_ids": list(self.subject_ids),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "VerificationProperty":
        value = _mapping(value, "property")
        _reject_unknown(
            value,
            frozenset(
                {
                    "property_id",
                    "kind",
                    "property_kind",
                    "statement",
                    "expression",
                    "formula",
                    "logic_family",
                    "subject_ids",
                    "assumption_ids",
                    "bound_ids",
                    "source_ref_ids",
                    "source_refs",
                    "span_ids",
                    "extensions",
                    "schema_version",
                }
            ),
            "property",
        )
        source_ids = value.get("source_ref_ids", value.get("source_refs", ()))
        expression = value.get("expression", value.get("formula", {}))
        return cls(
            property_id=value.get("property_id", ""),
            kind=value.get("kind", value.get("property_kind", "")),
            statement=value.get("statement", ""),
            expression=FrozenMap(_mapping(expression, "expression")),
            logic_family=value.get("logic_family", "unspecified"),
            subject_ids=tuple(value.get("subject_ids", ())),
            assumption_ids=tuple(value.get("assumption_ids", ())),
            bound_ids=tuple(value.get("bound_ids", ())),
            source_ref_ids=tuple(source_ids),
            span_ids=tuple(value.get("span_ids", ())),
            extensions=FrozenMap(_mapping(value.get("extensions", {}), "extensions")),
            schema_version=value.get(
                "schema_version", VERIFICATION_PROPERTY_SCHEMA_VERSION
            ),
        )


__all__ = [
    "ASSUMPTION_VOCABULARY",
    "PROPERTY_VOCABULARY",
    "VERIFICATION_ASSUMPTION_SCHEMA_VERSION",
    "VERIFICATION_PROPERTY_SCHEMA_VERSION",
    "AssumptionKind",
    "PropertyKind",
    "PropertyValidationError",
    "VerificationAssumption",
    "VerificationProperty",
    "validate_extensions",
]
