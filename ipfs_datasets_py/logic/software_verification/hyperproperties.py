"""Provider-neutral hyperproperty and information-flow semantics.

``HyperpropertyIR@1`` represents multi-trace properties such as
noninterference without binding any HyperLTL, AutoHyper, or MCHyper
executable.  It records:

* ordered trace variables and quantifier alternation;
* explicit low/high labels, observations, and declassification;
* relational pre- and postconditions;
* finite self-composition bounds; and
* witness trace bundles.

Bounded self-composition and clean sample evidence are deliberately
non-authoritative.  A finite witness, a clean sample under declared bounds, or
an inconclusive bounded check can never become a universal proof of the
hyperproperty.
"""

from __future__ import annotations

import hashlib
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

HYPERPROPERTY_IR_INTERFACE: Final = "HyperpropertyIR@1"
HYPERPROPERTY_IR_SCHEMA_VERSION: Final = "hyperproperty-ir/v1"
HYPERPROPERTY_IR_IDENTITY_DOMAIN: Final = "logic.software-verification.hyperproperty"

TRACE_VARIABLE_SCHEMA_VERSION: Final = "hyperproperty-trace-variable/v1"
QUANTIFIER_BINDING_SCHEMA_VERSION: Final = "hyperproperty-quantifier-binding/v1"
SECURITY_LABEL_SCHEMA_VERSION: Final = "hyperproperty-security-label/v1"
OBSERVATION_SPEC_SCHEMA_VERSION: Final = "hyperproperty-observation/v1"
DECLASSIFICATION_SCHEMA_VERSION: Final = "hyperproperty-declassification/v1"
INFORMATION_FLOW_POLICY_SCHEMA_VERSION: Final = "hyperproperty-information-flow-policy/v1"
RELATIONAL_ATOM_SCHEMA_VERSION: Final = "hyperproperty-relational-atom/v1"
RELATIONAL_CONDITION_SCHEMA_VERSION: Final = "hyperproperty-relational-condition/v1"
HYPERPROPERTY_FORMULA_SCHEMA_VERSION: Final = "hyperproperty-formula/v1"
SELF_COMPOSITION_BOUND_SCHEMA_VERSION: Final = "hyperproperty-self-composition-bound/v1"
WITNESS_TRACE_SCHEMA_VERSION: Final = "hyperproperty-witness-trace/v1"
WITNESS_BUNDLE_SCHEMA_VERSION: Final = "hyperproperty-witness-bundle/v1"
HYPERPROPERTY_EVALUATION_SCHEMA_VERSION: Final = "hyperproperty-evaluation/v1"

DEFAULT_MAX_COMPOSITION_TRACES: Final = 32
DEFAULT_MAX_COMPOSITION_PAIRS: Final = 256

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")
_FIELD_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")


class HyperpropertyValidationError(ValueError):
    """Raised when hyperproperty or information-flow declarations are malformed."""


class AuthorityPromotionError(HyperpropertyValidationError):
    """Raised when bounded or sample evidence is treated as universal proof."""


class TraceQuantifier(StrEnum):
    """Quantification over a named execution (trace variable)."""

    FORALL = "forall"
    EXISTS = "exists"


class SecurityLevel(StrEnum):
    """Canonical lattice levels for information-flow labels."""

    LOW = "low"
    HIGH = "high"


class ObservationKind(StrEnum):
    """What an observation projects from an execution."""

    INPUT = "input"
    OUTPUT = "output"
    STATE = "state"
    EVENT = "event"
    CHANNEL = "channel"


class HyperpropertyKind(StrEnum):
    """Reviewed hyperproperty families represented by this IR."""

    NONINTERFERENCE = "noninterference"
    OBSERVATIONAL_DETERMINISM = "observational_determinism"
    DECLASSIFICATION = "declassification"
    GENERAL = "general"
    RELATIONAL = "relational"


class RelationalRole(StrEnum):
    """Role of a multi-trace condition relative to the quantified formula."""

    PRECONDITION = "precondition"
    POSTCONDITION = "postcondition"
    INVARIANT = "invariant"
    ASSUMPTION = "assumption"


class RelationalOperator(StrEnum):
    """Primitive relational comparison across one or more traces."""

    EQUAL = "equal"
    NOT_EQUAL = "not_equal"
    PREDICATE = "predicate"


class WitnessRole(StrEnum):
    """How a witness bundle relates to the claimed hyperproperty."""

    VIOLATION = "violation"
    SUPPORTING_SAMPLE = "supporting_sample"
    COUNTEREXAMPLE = "counterexample"


class HyperpropertyVerdict(StrEnum):
    """Conservative multi-trace evaluation result."""

    HOLDS = "holds"
    VIOLATED = "violated"
    INCONCLUSIVE = "inconclusive"


class HyperpropertyEvidenceKind(StrEnum):
    """Evidence path that produced an evaluation.

    Only engine-checked or independently reconstructed results (outside this
    module) may ever be authoritative.  Everything produced here is bounded or
    sample evidence.
    """

    BOUNDED_SELF_COMPOSITION = "bounded_self_composition"
    WITNESS_BUNDLE = "witness_bundle"
    CLEAN_SAMPLE = "clean_sample"
    DECLARATION_ONLY = "declaration_only"


class EvidenceAuthorityCeiling(StrEnum):
    """Maximum semantic authority an evaluation path may claim."""

    NONE = "none"
    ADVISORY = "advisory"
    BOUNDED = "bounded"
    # Universal proof is intentionally absent from local evaluation paths.
    AUTHORITATIVE = "authoritative"


_BOUNDED_EVIDENCE: Final[frozenset[HyperpropertyEvidenceKind]] = frozenset(
    {
        HyperpropertyEvidenceKind.BOUNDED_SELF_COMPOSITION,
        HyperpropertyEvidenceKind.WITNESS_BUNDLE,
        HyperpropertyEvidenceKind.CLEAN_SAMPLE,
        HyperpropertyEvidenceKind.DECLARATION_ONLY,
    }
)

_NON_AUTHORITATIVE_CEILINGS: Final[frozenset[EvidenceAuthorityCeiling]] = frozenset(
    {
        EvidenceAuthorityCeiling.NONE,
        EvidenceAuthorityCeiling.ADVISORY,
        EvidenceAuthorityCeiling.BOUNDED,
    }
)


def _text(value: object, label: str, *, optional: bool = False) -> str:
    if optional and (value == "" or value is None):
        return ""
    if not isinstance(value, str) or not value or value.strip() != value or "\x00" in value:
        raise HyperpropertyValidationError(
            f"{label} must be a non-empty trimmed string without NUL bytes"
        )
    return value


def _identifier(value: object, label: str) -> str:
    result = _text(value, label)
    if not _ID_RE.fullmatch(result):
        raise HyperpropertyValidationError(f"{label} must be a stable identifier")
    return result


def _field_path(value: object, label: str) -> str:
    result = _text(value, label)
    if not _FIELD_RE.fullmatch(result):
        raise HyperpropertyValidationError(f"{label} must be a stable field path")
    return result


def _enum(value: object, enum_type: type[StrEnum], label: str) -> Any:
    try:
        return value if isinstance(value, enum_type) else enum_type(value)
    except (TypeError, ValueError) as error:
        choices = ", ".join(repr(item.value) for item in enum_type)
        raise HyperpropertyValidationError(f"{label} must be one of {choices}") from error


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise HyperpropertyValidationError(f"{label} must be a mapping")
    return value


def _frozen(value: Mapping[str, Any] | FrozenMap, label: str) -> FrozenMap:
    try:
        return value if isinstance(value, FrozenMap) else FrozenMap(value)
    except (TypeError, ValueError) as error:
        raise HyperpropertyValidationError(
            f"{label} must contain immutable JSON-compatible data: {error}"
        ) from error


def _reject_unknown(value: Mapping[str, Any], allowed: frozenset[str], label: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise HyperpropertyValidationError(f"unknown {label} field(s): {', '.join(unknown)}")


def _ids(
    values: Sequence[str] | object,
    label: str,
    *,
    preserve_order: bool = False,
    required: bool = False,
) -> tuple[str, ...]:
    if isinstance(values, (str, bytes, bytearray)) or not isinstance(values, Sequence):
        raise HyperpropertyValidationError(f"{label} must be a sequence of identifiers")
    result = tuple(_identifier(item, f"{label} item") for item in values)
    if len(result) != len(set(result)):
        raise HyperpropertyValidationError(f"{label} must not contain duplicates")
    if required and not result:
        raise HyperpropertyValidationError(f"{label} must not be empty")
    return result if preserve_order else tuple(sorted(result))


def _fields(
    values: Sequence[str] | object,
    label: str,
    *,
    preserve_order: bool = False,
    required: bool = False,
) -> tuple[str, ...]:
    if isinstance(values, (str, bytes, bytearray)) or not isinstance(values, Sequence):
        raise HyperpropertyValidationError(f"{label} must be a sequence of field paths")
    result = tuple(_field_path(item, f"{label} item") for item in values)
    if len(result) != len(set(result)):
        raise HyperpropertyValidationError(f"{label} must not contain duplicates")
    if required and not result:
        raise HyperpropertyValidationError(f"{label} must not be empty")
    return result if preserve_order else tuple(sorted(result))


def _bool(value: object, label: str) -> bool:
    if not isinstance(value, bool):
        raise HyperpropertyValidationError(f"{label} must be a boolean")
    return value


def _positive_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise HyperpropertyValidationError(f"{label} must be a positive integer")
    return value


def _non_negative_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise HyperpropertyValidationError(f"{label} must be a non-negative integer")
    return value


def _digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _records(
    values: Sequence[Any] | object,
    record_type: type[Any],
    label: str,
) -> tuple[Any, ...]:
    if isinstance(values, (str, bytes, bytearray)) or not isinstance(values, Sequence):
        raise HyperpropertyValidationError(f"{label} must be a sequence")
    result: list[Any] = []
    for item in values:
        if isinstance(item, record_type):
            result.append(item)
        elif isinstance(item, Mapping):
            result.append(record_type.from_dict(item))
        else:
            raise HyperpropertyValidationError(
                f"{label} items must be {record_type.__name__} values"
            )
    return tuple(result)


def _unique_by(values: Sequence[Any], attribute: str, label: str) -> None:
    ids = [getattr(item, attribute) for item in values]
    if len(ids) != len(set(ids)):
        raise HyperpropertyValidationError(f"duplicate {label} identifiers")


def _path_value(value: Mapping[str, Any], path: str) -> Any:
    current: Any = value
    for component in path.split("."):
        if not isinstance(current, Mapping) or component not in current:
            return None
        current = current[component]
    return current


def _projection(value: Mapping[str, Any], paths: Sequence[str]) -> tuple[Any, ...]:
    return tuple(_path_value(value, path) for path in paths)


@dataclass(frozen=True, slots=True)
class TraceVariable:
    """A named quantified execution in a hyperproperty formula."""

    variable_id: str
    name: str
    description: str = ""
    schema_version: str = TRACE_VARIABLE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "variable_id", _identifier(self.variable_id, "variable_id"))
        object.__setattr__(self, "name", _identifier(self.name, "name"))
        object.__setattr__(
            self, "description", _text(self.description, "description", optional=True)
        )
        if self.schema_version != TRACE_VARIABLE_SCHEMA_VERSION:
            raise HyperpropertyValidationError(
                f"unsupported trace-variable schema_version {self.schema_version!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "description": self.description,
            "name": self.name,
            "schema_version": self.schema_version,
            "variable_id": self.variable_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> TraceVariable:
        value = _mapping(value, "trace variable")
        _reject_unknown(
            value,
            frozenset({"variable_id", "name", "description", "schema_version"}),
            "trace variable",
        )
        return cls(
            variable_id=value.get("variable_id", ""),
            name=value.get("name", ""),
            description=value.get("description", ""),
            schema_version=value.get("schema_version", TRACE_VARIABLE_SCHEMA_VERSION),
        )


@dataclass(frozen=True, slots=True)
class QuantifierBinding:
    """One ordered quantifier binding in a hyperproperty prefix.

    Binding order is semantic: ``forall pi1. exists pi2.`` is not the same
    formula as ``exists pi2. forall pi1.``.  The binding index is therefore
    part of the canonical identity of any formula that uses the prefix.
    """

    binding_id: str
    quantifier: TraceQuantifier
    variable_id: str
    index: int
    schema_version: str = QUANTIFIER_BINDING_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "binding_id", _identifier(self.binding_id, "binding_id"))
        object.__setattr__(
            self, "quantifier", _enum(self.quantifier, TraceQuantifier, "quantifier")
        )
        object.__setattr__(self, "variable_id", _identifier(self.variable_id, "variable_id"))
        object.__setattr__(self, "index", _non_negative_int(self.index, "index"))
        if self.schema_version != QUANTIFIER_BINDING_SCHEMA_VERSION:
            raise HyperpropertyValidationError(
                f"unsupported quantifier-binding schema_version {self.schema_version!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "binding_id": self.binding_id,
            "index": self.index,
            "quantifier": self.quantifier.value,
            "schema_version": self.schema_version,
            "variable_id": self.variable_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> QuantifierBinding:
        value = _mapping(value, "quantifier binding")
        _reject_unknown(
            value,
            frozenset(
                {
                    "binding_id",
                    "quantifier",
                    "variable_id",
                    "index",
                    "schema_version",
                }
            ),
            "quantifier binding",
        )
        return cls(
            binding_id=value.get("binding_id", ""),
            quantifier=value.get("quantifier", ""),
            variable_id=value.get("variable_id", ""),
            index=value.get("index", -1),
            schema_version=value.get("schema_version", QUANTIFIER_BINDING_SCHEMA_VERSION),
        )


@dataclass(frozen=True, slots=True)
class SecurityLabel:
    """Explicit low/high classification of one information-flow field."""

    label_id: str
    field: str
    level: SecurityLevel
    kind: ObservationKind = ObservationKind.STATE
    description: str = ""
    schema_version: str = SECURITY_LABEL_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "label_id", _identifier(self.label_id, "label_id"))
        object.__setattr__(self, "field", _field_path(self.field, "field"))
        object.__setattr__(self, "level", _enum(self.level, SecurityLevel, "level"))
        object.__setattr__(self, "kind", _enum(self.kind, ObservationKind, "kind"))
        object.__setattr__(
            self, "description", _text(self.description, "description", optional=True)
        )
        if self.schema_version != SECURITY_LABEL_SCHEMA_VERSION:
            raise HyperpropertyValidationError(
                f"unsupported security-label schema_version {self.schema_version!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "description": self.description,
            "field": self.field,
            "kind": self.kind.value,
            "label_id": self.label_id,
            "level": self.level.value,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> SecurityLabel:
        value = _mapping(value, "security label")
        _reject_unknown(
            value,
            frozenset(
                {
                    "label_id",
                    "field",
                    "level",
                    "kind",
                    "description",
                    "schema_version",
                }
            ),
            "security label",
        )
        return cls(
            label_id=value.get("label_id", ""),
            field=value.get("field", ""),
            level=value.get("level", ""),
            kind=value.get("kind", ObservationKind.STATE.value),
            description=value.get("description", ""),
            schema_version=value.get("schema_version", SECURITY_LABEL_SCHEMA_VERSION),
        )


@dataclass(frozen=True, slots=True)
class ObservationSpec:
    """An explicit observation that a hyperproperty may compare across traces.

    Observations are never inferred from field names.  Callers must declare
    every comparable path; absence of a declaration means the path is not an
    approved observation.
    """

    observation_id: str
    field: str
    kind: ObservationKind
    level: SecurityLevel = SecurityLevel.LOW
    required: bool = True
    description: str = ""
    schema_version: str = OBSERVATION_SPEC_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "observation_id", _identifier(self.observation_id, "observation_id")
        )
        object.__setattr__(self, "field", _field_path(self.field, "field"))
        object.__setattr__(self, "kind", _enum(self.kind, ObservationKind, "kind"))
        object.__setattr__(self, "level", _enum(self.level, SecurityLevel, "level"))
        object.__setattr__(self, "required", _bool(self.required, "required"))
        object.__setattr__(
            self, "description", _text(self.description, "description", optional=True)
        )
        if self.schema_version != OBSERVATION_SPEC_SCHEMA_VERSION:
            raise HyperpropertyValidationError(
                f"unsupported observation schema_version {self.schema_version!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "description": self.description,
            "field": self.field,
            "kind": self.kind.value,
            "level": self.level.value,
            "observation_id": self.observation_id,
            "required": self.required,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> ObservationSpec:
        value = _mapping(value, "observation")
        _reject_unknown(
            value,
            frozenset(
                {
                    "observation_id",
                    "field",
                    "kind",
                    "level",
                    "required",
                    "description",
                    "schema_version",
                }
            ),
            "observation",
        )
        return cls(
            observation_id=value.get("observation_id", ""),
            field=value.get("field", ""),
            kind=value.get("kind", ""),
            level=value.get("level", SecurityLevel.LOW.value),
            required=value.get("required", True),
            description=value.get("description", ""),
            schema_version=value.get("schema_version", OBSERVATION_SPEC_SCHEMA_VERSION),
        )


@dataclass(frozen=True, slots=True)
class DeclassificationPolicy:
    """Explicit release of a high field under a stated condition.

    Declassification is never implicit.  A high field remains high unless a
    policy names it, the releasing condition, and the resulting low observation.
    """

    policy_id: str
    high_field: str
    released_as: str
    condition: str
    description: str = ""
    schema_version: str = DECLASSIFICATION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "policy_id", _identifier(self.policy_id, "policy_id"))
        object.__setattr__(self, "high_field", _field_path(self.high_field, "high_field"))
        object.__setattr__(self, "released_as", _field_path(self.released_as, "released_as"))
        object.__setattr__(self, "condition", _text(self.condition, "condition"))
        object.__setattr__(
            self, "description", _text(self.description, "description", optional=True)
        )
        if self.high_field == self.released_as:
            raise HyperpropertyValidationError(
                "declassification must rename or reclassify the released observation"
            )
        if self.schema_version != DECLASSIFICATION_SCHEMA_VERSION:
            raise HyperpropertyValidationError(
                f"unsupported declassification schema_version {self.schema_version!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "condition": self.condition,
            "description": self.description,
            "high_field": self.high_field,
            "policy_id": self.policy_id,
            "released_as": self.released_as,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> DeclassificationPolicy:
        value = _mapping(value, "declassification policy")
        _reject_unknown(
            value,
            frozenset(
                {
                    "policy_id",
                    "high_field",
                    "released_as",
                    "condition",
                    "description",
                    "schema_version",
                }
            ),
            "declassification policy",
        )
        return cls(
            policy_id=value.get("policy_id", ""),
            high_field=value.get("high_field", ""),
            released_as=value.get("released_as", ""),
            condition=value.get("condition", ""),
            description=value.get("description", ""),
            schema_version=value.get("schema_version", DECLASSIFICATION_SCHEMA_VERSION),
        )


@dataclass(frozen=True, slots=True)
class InformationFlowPolicy:
    """Complete low/high/observation boundary for one hyperproperty.

    Private/high inputs are comparison-only: they may appear in evaluation
    inputs but never enter a public serialization of a witness or counterexample.
    """

    policy_id: str
    low_input_fields: tuple[str, ...]
    high_input_fields: tuple[str, ...]
    observation_fields: tuple[str, ...]
    labels: tuple[SecurityLabel, ...] = ()
    observations: tuple[ObservationSpec, ...] = ()
    declassifications: tuple[DeclassificationPolicy, ...] = ()
    subject_fields: tuple[str, ...] = ()
    description: str = ""
    schema_version: str = INFORMATION_FLOW_POLICY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "policy_id", _identifier(self.policy_id, "policy_id"))
        low = _fields(self.low_input_fields, "low_input_fields", preserve_order=True)
        high = _fields(self.high_input_fields, "high_input_fields", preserve_order=True)
        observed = _fields(
            self.observation_fields,
            "observation_fields",
            preserve_order=True,
            required=True,
        )
        subjects = _fields(self.subject_fields, "subject_fields", preserve_order=True)
        if set(low) & set(high):
            raise HyperpropertyValidationError(
                "low_input_fields and high_input_fields must be disjoint"
            )
        if set(high) & set(observed):
            raise HyperpropertyValidationError(
                "high inputs cannot also be approved observations without declassification"
            )
        object.__setattr__(self, "low_input_fields", low)
        object.__setattr__(self, "high_input_fields", high)
        object.__setattr__(self, "observation_fields", observed)
        object.__setattr__(self, "subject_fields", subjects)
        labels = _records(self.labels, SecurityLabel, "labels")
        _unique_by(labels, "label_id", "label")
        observations = _records(self.observations, ObservationSpec, "observations")
        _unique_by(observations, "observation_id", "observation")
        declassifications = _records(
            self.declassifications, DeclassificationPolicy, "declassifications"
        )
        _unique_by(declassifications, "policy_id", "declassification")
        object.__setattr__(self, "labels", labels)
        object.__setattr__(self, "observations", observations)
        object.__setattr__(self, "declassifications", declassifications)
        object.__setattr__(
            self, "description", _text(self.description, "description", optional=True)
        )
        observed_from_specs = {item.field for item in observations}
        if observations and observed_from_specs != set(observed):
            raise HyperpropertyValidationError(
                "observation_fields must exactly match declared ObservationSpec fields"
            )
        released = {item.released_as for item in declassifications}
        high_from_decl = {item.high_field for item in declassifications}
        if high_from_decl - set(high):
            raise HyperpropertyValidationError(
                "declassification high_field must be listed in high_input_fields"
            )
        if released - set(observed):
            raise HyperpropertyValidationError(
                "declassification released_as must be listed in observation_fields"
            )
        for label in labels:
            if label.level is SecurityLevel.LOW and label.field not in set(low) | set(observed):
                raise HyperpropertyValidationError(
                    f"low label field {label.field!r} is not a low input or observation"
                )
            if label.level is SecurityLevel.HIGH and label.field not in set(high):
                raise HyperpropertyValidationError(
                    f"high label field {label.field!r} is not a high input"
                )
        if self.schema_version != INFORMATION_FLOW_POLICY_SCHEMA_VERSION:
            raise HyperpropertyValidationError(
                f"unsupported information-flow-policy schema_version {self.schema_version!r}"
            )

    @property
    def policy_identity(self) -> CanonicalIdentity:
        return canonical_identity(
            self.semantic_dict(),
            domain=f"{HYPERPROPERTY_IR_IDENTITY_DOMAIN}.policy",
            schema_version=self.schema_version,
        )

    def semantic_dict(self) -> dict[str, Any]:
        return {
            "declassifications": [item.to_dict() for item in self.declassifications],
            "description": self.description,
            "high_input_fields": list(self.high_input_fields),
            "labels": [item.to_dict() for item in self.labels],
            "low_input_fields": list(self.low_input_fields),
            "observation_fields": list(self.observation_fields),
            "observations": [item.to_dict() for item in self.observations],
            "policy_id": self.policy_id,
            "schema_version": self.schema_version,
            "subject_fields": list(self.subject_fields),
        }

    def to_dict(self) -> dict[str, Any]:
        result = self.semantic_dict()
        result["content_id"] = self.policy_identity.cid
        return result

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> InformationFlowPolicy:
        value = _mapping(value, "information-flow policy")
        _reject_unknown(
            value,
            frozenset(
                {
                    "policy_id",
                    "low_input_fields",
                    "high_input_fields",
                    "observation_fields",
                    "labels",
                    "observations",
                    "declassifications",
                    "subject_fields",
                    "description",
                    "schema_version",
                    "content_id",
                }
            ),
            "information-flow policy",
        )
        result = cls(
            policy_id=value.get("policy_id", ""),
            low_input_fields=tuple(value.get("low_input_fields") or ()),
            high_input_fields=tuple(value.get("high_input_fields") or ()),
            observation_fields=tuple(value.get("observation_fields") or ()),
            labels=tuple(value.get("labels") or ()),
            observations=tuple(value.get("observations") or ()),
            declassifications=tuple(value.get("declassifications") or ()),
            subject_fields=tuple(value.get("subject_fields") or ()),
            description=value.get("description", ""),
            schema_version=value.get(
                "schema_version", INFORMATION_FLOW_POLICY_SCHEMA_VERSION
            ),
        )
        claimed = value.get("content_id")
        if claimed and claimed != result.policy_identity.cid:
            raise HyperpropertyValidationError(
                "information-flow policy content_id does not match payload"
            )
        return result


@dataclass(frozen=True, slots=True)
class RelationalAtom:
    """One multi-trace equality or predicate atom."""

    atom_id: str
    operator: RelationalOperator
    field: str
    trace_variable_ids: tuple[str, ...]
    predicate: str = ""
    schema_version: str = RELATIONAL_ATOM_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "atom_id", _identifier(self.atom_id, "atom_id"))
        object.__setattr__(
            self, "operator", _enum(self.operator, RelationalOperator, "operator")
        )
        object.__setattr__(self, "field", _field_path(self.field, "field"))
        variables = _ids(
            self.trace_variable_ids,
            "trace_variable_ids",
            preserve_order=True,
            required=True,
        )
        if self.operator in {RelationalOperator.EQUAL, RelationalOperator.NOT_EQUAL}:
            if len(variables) != 2:
                raise HyperpropertyValidationError(
                    f"{self.operator.value} atoms require exactly two trace variables"
                )
        object.__setattr__(self, "trace_variable_ids", variables)
        predicate = _text(self.predicate, "predicate", optional=True)
        if self.operator is RelationalOperator.PREDICATE and not predicate:
            raise HyperpropertyValidationError("predicate atoms require a predicate statement")
        if self.operator is not RelationalOperator.PREDICATE and predicate:
            raise HyperpropertyValidationError(
                "predicate text is only valid for PREDICATE atoms"
            )
        object.__setattr__(self, "predicate", predicate)
        if self.schema_version != RELATIONAL_ATOM_SCHEMA_VERSION:
            raise HyperpropertyValidationError(
                f"unsupported relational-atom schema_version {self.schema_version!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "atom_id": self.atom_id,
            "field": self.field,
            "operator": self.operator.value,
            "predicate": self.predicate,
            "schema_version": self.schema_version,
            "trace_variable_ids": list(self.trace_variable_ids),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> RelationalAtom:
        value = _mapping(value, "relational atom")
        _reject_unknown(
            value,
            frozenset(
                {
                    "atom_id",
                    "operator",
                    "field",
                    "trace_variable_ids",
                    "predicate",
                    "schema_version",
                }
            ),
            "relational atom",
        )
        return cls(
            atom_id=value.get("atom_id", ""),
            operator=value.get("operator", ""),
            field=value.get("field", ""),
            trace_variable_ids=tuple(value.get("trace_variable_ids") or ()),
            predicate=value.get("predicate", ""),
            schema_version=value.get("schema_version", RELATIONAL_ATOM_SCHEMA_VERSION),
        )


@dataclass(frozen=True, slots=True)
class RelationalCondition:
    """A conjunction of relational atoms used as pre/post/invariant/assumption."""

    condition_id: str
    role: RelationalRole
    atoms: tuple[RelationalAtom, ...]
    description: str = ""
    schema_version: str = RELATIONAL_CONDITION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "condition_id", _identifier(self.condition_id, "condition_id")
        )
        object.__setattr__(self, "role", _enum(self.role, RelationalRole, "role"))
        atoms = _records(self.atoms, RelationalAtom, "atoms")
        if not atoms:
            raise HyperpropertyValidationError("relational conditions require at least one atom")
        _unique_by(atoms, "atom_id", "atom")
        object.__setattr__(self, "atoms", atoms)
        object.__setattr__(
            self, "description", _text(self.description, "description", optional=True)
        )
        if self.schema_version != RELATIONAL_CONDITION_SCHEMA_VERSION:
            raise HyperpropertyValidationError(
                f"unsupported relational-condition schema_version {self.schema_version!r}"
            )

    def referenced_variable_ids(self) -> tuple[str, ...]:
        names: list[str] = []
        for atom in self.atoms:
            names.extend(atom.trace_variable_ids)
        # Order is semantic within each atom; overall set is sorted for identity.
        return tuple(sorted(set(names)))

    def to_dict(self) -> dict[str, Any]:
        return {
            "atoms": [item.to_dict() for item in self.atoms],
            "condition_id": self.condition_id,
            "description": self.description,
            "role": self.role.value,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> RelationalCondition:
        value = _mapping(value, "relational condition")
        _reject_unknown(
            value,
            frozenset(
                {
                    "condition_id",
                    "role",
                    "atoms",
                    "description",
                    "schema_version",
                }
            ),
            "relational condition",
        )
        return cls(
            condition_id=value.get("condition_id", ""),
            role=value.get("role", ""),
            atoms=tuple(value.get("atoms") or ()),
            description=value.get("description", ""),
            schema_version=value.get(
                "schema_version", RELATIONAL_CONDITION_SCHEMA_VERSION
            ),
        )


@dataclass(frozen=True, slots=True)
class SelfCompositionBound:
    """Finite bounds required before self-composition may run.

    Self-composition without declared positive bounds is rejected.  Hitting a
    bound yields inconclusive or violation evidence, never universal proof.
    """

    bound_id: str
    max_traces: int = DEFAULT_MAX_COMPOSITION_TRACES
    max_pairs: int = DEFAULT_MAX_COMPOSITION_PAIRS
    max_steps: int | None = None
    description: str = ""
    schema_version: str = SELF_COMPOSITION_BOUND_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "bound_id", _identifier(self.bound_id, "bound_id"))
        object.__setattr__(self, "max_traces", _positive_int(self.max_traces, "max_traces"))
        object.__setattr__(self, "max_pairs", _positive_int(self.max_pairs, "max_pairs"))
        if self.max_steps is not None:
            object.__setattr__(self, "max_steps", _positive_int(self.max_steps, "max_steps"))
        object.__setattr__(
            self, "description", _text(self.description, "description", optional=True)
        )
        if self.schema_version != SELF_COMPOSITION_BOUND_SCHEMA_VERSION:
            raise HyperpropertyValidationError(
                f"unsupported self-composition-bound schema_version {self.schema_version!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "bound_id": self.bound_id,
            "description": self.description,
            "max_pairs": self.max_pairs,
            "max_steps": self.max_steps,
            "max_traces": self.max_traces,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> SelfCompositionBound:
        value = _mapping(value, "self-composition bound")
        _reject_unknown(
            value,
            frozenset(
                {
                    "bound_id",
                    "max_traces",
                    "max_pairs",
                    "max_steps",
                    "description",
                    "schema_version",
                }
            ),
            "self-composition bound",
        )
        return cls(
            bound_id=value.get("bound_id", ""),
            max_traces=value.get("max_traces", DEFAULT_MAX_COMPOSITION_TRACES),
            max_pairs=value.get("max_pairs", DEFAULT_MAX_COMPOSITION_PAIRS),
            max_steps=value.get("max_steps"),
            description=value.get("description", ""),
            schema_version=value.get(
                "schema_version", SELF_COMPOSITION_BOUND_SCHEMA_VERSION
            ),
        )


@dataclass(frozen=True, slots=True)
class HyperpropertyFormula:
    """Quantified multi-trace formula with optional relational conditions.

    Trace cardinality is the number of quantifier bindings.  Quantifier order is
    part of the semantic identity and is never reordered during serialization.
    """

    formula_id: str
    kind: HyperpropertyKind
    variables: tuple[TraceVariable, ...]
    quantifier_prefix: tuple[QuantifierBinding, ...]
    matrix_statement: str
    information_flow_policy_id: str = ""
    preconditions: tuple[RelationalCondition, ...] = ()
    postconditions: tuple[RelationalCondition, ...] = ()
    assumptions: tuple[RelationalCondition, ...] = ()
    description: str = ""
    schema_version: str = HYPERPROPERTY_FORMULA_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "formula_id", _identifier(self.formula_id, "formula_id"))
        object.__setattr__(self, "kind", _enum(self.kind, HyperpropertyKind, "kind"))
        variables = _records(self.variables, TraceVariable, "variables")
        if not variables:
            raise HyperpropertyValidationError("hyperproperty formulas require trace variables")
        _unique_by(variables, "variable_id", "variable")
        names = [item.name for item in variables]
        if len(names) != len(set(names)):
            raise HyperpropertyValidationError("trace variable names must be unique")
        object.__setattr__(self, "variables", variables)
        known = {item.variable_id for item in variables}

        prefix = _records(self.quantifier_prefix, QuantifierBinding, "quantifier_prefix")
        if not prefix:
            raise HyperpropertyValidationError(
                "hyperproperty formulas require a non-empty quantifier prefix"
            )
        _unique_by(prefix, "binding_id", "quantifier binding")
        indices = [item.index for item in prefix]
        if indices != list(range(len(prefix))):
            raise HyperpropertyValidationError(
                "quantifier binding indices must be contiguous from zero in declaration order"
            )
        bound_variables = [item.variable_id for item in prefix]
        if len(bound_variables) != len(set(bound_variables)):
            raise HyperpropertyValidationError(
                "each trace variable may appear at most once in the quantifier prefix"
            )
        missing = sorted(set(bound_variables) - known)
        if missing:
            raise HyperpropertyValidationError(
                f"quantifier prefix references unknown variables {missing}"
            )
        unbound = sorted(known - set(bound_variables))
        if unbound:
            raise HyperpropertyValidationError(
                f"trace variables must all appear in the quantifier prefix: {unbound}"
            )
        object.__setattr__(self, "quantifier_prefix", prefix)

        object.__setattr__(
            self, "matrix_statement", _text(self.matrix_statement, "matrix_statement")
        )
        policy_id = _text(
            self.information_flow_policy_id,
            "information_flow_policy_id",
            optional=True,
        )
        if self.kind in {
            HyperpropertyKind.NONINTERFERENCE,
            HyperpropertyKind.OBSERVATIONAL_DETERMINISM,
            HyperpropertyKind.DECLASSIFICATION,
        } and not policy_id:
            raise HyperpropertyValidationError(
                f"{self.kind.value} formulas require an information_flow_policy_id"
            )
        object.__setattr__(self, "information_flow_policy_id", policy_id)

        preconditions = _records(self.preconditions, RelationalCondition, "preconditions")
        postconditions = _records(self.postconditions, RelationalCondition, "postconditions")
        assumptions = _records(self.assumptions, RelationalCondition, "assumptions")
        for group, role in (
            (preconditions, RelationalRole.PRECONDITION),
            (postconditions, RelationalRole.POSTCONDITION),
            (assumptions, RelationalRole.ASSUMPTION),
        ):
            for condition in group:
                if condition.role is not role:
                    raise HyperpropertyValidationError(
                        f"{condition.condition_id} must have role {role.value}"
                    )
                unknown = sorted(set(condition.referenced_variable_ids()) - known)
                if unknown:
                    raise HyperpropertyValidationError(
                        f"{condition.condition_id} references unknown variables {unknown}"
                    )
        object.__setattr__(self, "preconditions", preconditions)
        object.__setattr__(self, "postconditions", postconditions)
        object.__setattr__(self, "assumptions", assumptions)
        object.__setattr__(
            self, "description", _text(self.description, "description", optional=True)
        )

        if self.kind is HyperpropertyKind.NONINTERFERENCE:
            if self.trace_cardinality != 2:
                raise HyperpropertyValidationError(
                    "noninterference requires exactly two quantified traces"
                )
            if any(item.quantifier is not TraceQuantifier.FORALL for item in prefix):
                raise HyperpropertyValidationError(
                    "classical noninterference uses a universal two-trace prefix"
                )

        if self.schema_version != HYPERPROPERTY_FORMULA_SCHEMA_VERSION:
            raise HyperpropertyValidationError(
                f"unsupported formula schema_version {self.schema_version!r}"
            )

    @property
    def trace_cardinality(self) -> int:
        """Number of quantified traces; order-sensitive and canonical."""

        return len(self.quantifier_prefix)

    @property
    def quantifier_signature(self) -> tuple[str, ...]:
        """Ordered quantifier kinds used for identity and display."""

        return tuple(item.quantifier.value for item in self.quantifier_prefix)

    def semantic_dict(self) -> dict[str, Any]:
        return {
            "assumptions": [item.to_dict() for item in self.assumptions],
            "description": self.description,
            "formula_id": self.formula_id,
            "information_flow_policy_id": self.information_flow_policy_id,
            "kind": self.kind.value,
            "matrix_statement": self.matrix_statement,
            "postconditions": [item.to_dict() for item in self.postconditions],
            "preconditions": [item.to_dict() for item in self.preconditions],
            "quantifier_prefix": [item.to_dict() for item in self.quantifier_prefix],
            "schema_version": self.schema_version,
            "trace_cardinality": self.trace_cardinality,
            "variables": [item.to_dict() for item in self.variables],
        }

    def to_dict(self) -> dict[str, Any]:
        return self.semantic_dict()

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> HyperpropertyFormula:
        value = _mapping(value, "hyperproperty formula")
        _reject_unknown(
            value,
            frozenset(
                {
                    "formula_id",
                    "kind",
                    "variables",
                    "quantifier_prefix",
                    "matrix_statement",
                    "information_flow_policy_id",
                    "preconditions",
                    "postconditions",
                    "assumptions",
                    "description",
                    "schema_version",
                    "trace_cardinality",
                }
            ),
            "hyperproperty formula",
        )
        result = cls(
            formula_id=value.get("formula_id", ""),
            kind=value.get("kind", ""),
            variables=tuple(value.get("variables") or ()),
            quantifier_prefix=tuple(value.get("quantifier_prefix") or ()),
            matrix_statement=value.get("matrix_statement", ""),
            information_flow_policy_id=value.get("information_flow_policy_id", ""),
            preconditions=tuple(value.get("preconditions") or ()),
            postconditions=tuple(value.get("postconditions") or ()),
            assumptions=tuple(value.get("assumptions") or ()),
            description=value.get("description", ""),
            schema_version=value.get(
                "schema_version", HYPERPROPERTY_FORMULA_SCHEMA_VERSION
            ),
        )
        claimed_cardinality = value.get("trace_cardinality")
        if claimed_cardinality is not None and claimed_cardinality != result.trace_cardinality:
            raise HyperpropertyValidationError(
                "trace_cardinality does not match quantifier prefix length"
            )
        return result

    @classmethod
    def noninterference(
        cls,
        *,
        formula_id: str = "formula:noninterference",
        policy_id: str,
        left_name: str = "pi1",
        right_name: str = "pi2",
        description: str = "Classical two-trace noninterference",
    ) -> HyperpropertyFormula:
        """Build the canonical ``forall pi1. forall pi2. ...`` noninterference shape."""

        left = TraceVariable(f"var:{left_name}", left_name)
        right = TraceVariable(f"var:{right_name}", right_name)
        prefix = (
            QuantifierBinding("bind:0", TraceQuantifier.FORALL, left.variable_id, 0),
            QuantifierBinding("bind:1", TraceQuantifier.FORALL, right.variable_id, 1),
        )
        pre = RelationalCondition(
            "cond:low-inputs-equal",
            RelationalRole.PRECONDITION,
            (
                RelationalAtom(
                    "atom:low-inputs",
                    RelationalOperator.EQUAL,
                    "low_inputs",
                    (left.variable_id, right.variable_id),
                ),
            ),
            description="Low inputs agree across the two traces",
        )
        post = RelationalCondition(
            "cond:observations-equal",
            RelationalRole.POSTCONDITION,
            (
                RelationalAtom(
                    "atom:observations",
                    RelationalOperator.EQUAL,
                    "observations",
                    (left.variable_id, right.variable_id),
                ),
            ),
            description="Approved low observations agree across the two traces",
        )
        return cls(
            formula_id=formula_id,
            kind=HyperpropertyKind.NONINTERFERENCE,
            variables=(left, right),
            quantifier_prefix=prefix,
            matrix_statement=(
                f"forall {left_name}, {right_name}. "
                f"equal_low_inputs({left_name}, {right_name}) "
                f"-> equal_observations({left_name}, {right_name})"
            ),
            information_flow_policy_id=policy_id,
            preconditions=(pre,),
            postconditions=(post,),
            description=description,
        )


@dataclass(frozen=True, slots=True)
class WitnessTrace:
    """One redacted execution reference inside a witness bundle.

    High/private inputs are never serialized.  Only digests of public inputs
    and approved observations are retained.
    """

    trace_id: str
    variable_id: str
    public_inputs: FrozenMap = field(default_factory=FrozenMap)
    observations: FrozenMap = field(default_factory=FrozenMap)
    subject: FrozenMap = field(default_factory=FrozenMap)
    public_inputs_digest: str = ""
    observations_digest: str = ""
    schema_version: str = WITNESS_TRACE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "trace_id", _identifier(self.trace_id, "trace_id"))
        object.__setattr__(self, "variable_id", _identifier(self.variable_id, "variable_id"))
        public_inputs = _frozen(self.public_inputs, "public_inputs")
        observations = _frozen(self.observations, "observations")
        subject = _frozen(self.subject, "subject")
        object.__setattr__(self, "public_inputs", public_inputs)
        object.__setattr__(self, "observations", observations)
        object.__setattr__(self, "subject", subject)
        public_digest = self.public_inputs_digest or _digest(dict(public_inputs))
        obs_digest = self.observations_digest or _digest(dict(observations))
        if not public_digest.startswith("sha256:"):
            raise HyperpropertyValidationError("public_inputs_digest must be a sha256 digest")
        if not obs_digest.startswith("sha256:"):
            raise HyperpropertyValidationError("observations_digest must be a sha256 digest")
        object.__setattr__(self, "public_inputs_digest", public_digest)
        object.__setattr__(self, "observations_digest", obs_digest)
        if self.schema_version != WITNESS_TRACE_SCHEMA_VERSION:
            raise HyperpropertyValidationError(
                f"unsupported witness-trace schema_version {self.schema_version!r}"
            )

    @property
    def public_ref(self) -> str:
        return canonical_identity(
            {
                "observations_digest": self.observations_digest,
                "public_inputs_digest": self.public_inputs_digest,
                "subject": dict(self.subject),
                "trace_id": self.trace_id,
                "variable_id": self.variable_id,
            },
            domain=f"{HYPERPROPERTY_IR_IDENTITY_DOMAIN}.witness-trace",
            schema_version=self.schema_version,
        ).cid

    def to_dict(self) -> dict[str, Any]:
        return {
            "observations": dict(self.observations),
            "observations_digest": self.observations_digest,
            "public_inputs": dict(self.public_inputs),
            "public_inputs_digest": self.public_inputs_digest,
            "public_ref": self.public_ref,
            "schema_version": self.schema_version,
            "subject": dict(self.subject),
            "trace_id": self.trace_id,
            "variable_id": self.variable_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> WitnessTrace:
        value = _mapping(value, "witness trace")
        _reject_unknown(
            value,
            frozenset(
                {
                    "trace_id",
                    "variable_id",
                    "public_inputs",
                    "observations",
                    "subject",
                    "public_inputs_digest",
                    "observations_digest",
                    "public_ref",
                    "schema_version",
                }
            ),
            "witness trace",
        )
        result = cls(
            trace_id=value.get("trace_id", ""),
            variable_id=value.get("variable_id", ""),
            public_inputs=_frozen(
                _mapping(value.get("public_inputs", {}), "public_inputs"),
                "public_inputs",
            ),
            observations=_frozen(
                _mapping(value.get("observations", {}), "observations"),
                "observations",
            ),
            subject=_frozen(_mapping(value.get("subject", {}), "subject"), "subject"),
            public_inputs_digest=value.get("public_inputs_digest", ""),
            observations_digest=value.get("observations_digest", ""),
            schema_version=value.get("schema_version", WITNESS_TRACE_SCHEMA_VERSION),
        )
        claimed = value.get("public_ref")
        if claimed and claimed != result.public_ref:
            raise HyperpropertyValidationError("witness trace public_ref does not match payload")
        return result

    @classmethod
    def from_execution(
        cls,
        *,
        trace_id: str,
        variable_id: str,
        public_inputs: Mapping[str, Any],
        observations: Mapping[str, Any],
        subject: Mapping[str, Any] | None = None,
        private_inputs: Mapping[str, Any] | None = None,
    ) -> WitnessTrace:
        """Build a redacted witness from execution data.

        ``private_inputs`` is accepted only to force callers to name high data
        and is intentionally discarded before serialization.
        """

        del private_inputs  # high data is never retained on a witness
        return cls(
            trace_id=trace_id,
            variable_id=variable_id,
            public_inputs=_frozen(public_inputs, "public_inputs"),
            observations=_frozen(observations, "observations"),
            subject=_frozen(subject or {}, "subject"),
        )


@dataclass(frozen=True, slots=True)
class ObservationDifference:
    """Value-free difference at one policy-approved observation path."""

    field: str
    left_digest: str
    right_digest: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "field", _field_path(self.field, "field"))
        for name in ("left_digest", "right_digest"):
            value = _text(getattr(self, name), name)
            if not value.startswith("sha256:"):
                raise HyperpropertyValidationError(f"{name} must be a sha256 digest")
            object.__setattr__(self, name, value)

    def to_dict(self) -> dict[str, Any]:
        return {
            "field": self.field,
            "left_digest": self.left_digest,
            "right_digest": self.right_digest,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> ObservationDifference:
        value = _mapping(value, "observation difference")
        _reject_unknown(
            value,
            frozenset({"field", "left_digest", "right_digest"}),
            "observation difference",
        )
        return cls(
            field=value.get("field", ""),
            left_digest=value.get("left_digest", ""),
            right_digest=value.get("right_digest", ""),
        )


@dataclass(frozen=True, slots=True)
class WitnessTraceBundle:
    """A finite multi-trace witness that cannot authorize universal proof.

    Supporting samples and even violation bundles remain bounded evidence.
    Callers that need universal assurance must use a separately capability-bound
    hyperproperty engine with its own authority model.
    """

    bundle_id: str
    role: WitnessRole
    formula_id: str
    traces: tuple[WitnessTrace, ...]
    differences: tuple[ObservationDifference, ...] = ()
    observed_fields: tuple[str, ...] = ()
    redacted: bool = True
    description: str = ""
    schema_version: str = WITNESS_BUNDLE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "bundle_id", _identifier(self.bundle_id, "bundle_id"))
        object.__setattr__(self, "role", _enum(self.role, WitnessRole, "role"))
        object.__setattr__(self, "formula_id", _identifier(self.formula_id, "formula_id"))
        traces = _records(self.traces, WitnessTrace, "traces")
        if not traces:
            raise HyperpropertyValidationError("witness bundles require at least one trace")
        _unique_by(traces, "trace_id", "witness trace")
        object.__setattr__(self, "traces", traces)
        differences = _records(self.differences, ObservationDifference, "differences")
        object.__setattr__(
            self,
            "differences",
            tuple(sorted(differences, key=lambda item: item.field)),
        )
        object.__setattr__(
            self,
            "observed_fields",
            _fields(self.observed_fields, "observed_fields", preserve_order=True),
        )
        object.__setattr__(self, "redacted", _bool(self.redacted, "redacted"))
        if self.redacted is not True:
            raise HyperpropertyValidationError("witness bundles must be redacted")
        if self.role in {WitnessRole.VIOLATION, WitnessRole.COUNTEREXAMPLE}:
            if not self.differences:
                raise HyperpropertyValidationError(
                    "violation and counterexample bundles require observation differences"
                )
        object.__setattr__(
            self, "description", _text(self.description, "description", optional=True)
        )
        if self.schema_version != WITNESS_BUNDLE_SCHEMA_VERSION:
            raise HyperpropertyValidationError(
                f"unsupported witness-bundle schema_version {self.schema_version!r}"
            )

    @property
    def authorizes_universal_proof(self) -> bool:
        """Witness bundles never prove the universal hyperproperty."""

        return False

    @property
    def authority_ceiling(self) -> EvidenceAuthorityCeiling:
        return EvidenceAuthorityCeiling.BOUNDED

    @property
    def evidence_kind(self) -> HyperpropertyEvidenceKind:
        if self.role is WitnessRole.SUPPORTING_SAMPLE:
            return HyperpropertyEvidenceKind.CLEAN_SAMPLE
        return HyperpropertyEvidenceKind.WITNESS_BUNDLE

    def semantic_dict(self) -> dict[str, Any]:
        return {
            "authority_ceiling": self.authority_ceiling.value,
            "authorizes_universal_proof": False,
            "bundle_id": self.bundle_id,
            "description": self.description,
            "differences": [item.to_dict() for item in self.differences],
            "evidence_kind": self.evidence_kind.value,
            "formula_id": self.formula_id,
            "observed_fields": list(self.observed_fields),
            "redacted": True,
            "role": self.role.value,
            "schema_version": self.schema_version,
            "traces": [item.to_dict() for item in self.traces],
        }

    def to_dict(self) -> dict[str, Any]:
        return self.semantic_dict()

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> WitnessTraceBundle:
        value = _mapping(value, "witness bundle")
        _reject_unknown(
            value,
            frozenset(
                {
                    "bundle_id",
                    "role",
                    "formula_id",
                    "traces",
                    "differences",
                    "observed_fields",
                    "redacted",
                    "description",
                    "schema_version",
                    "authorizes_universal_proof",
                    "authority_ceiling",
                    "evidence_kind",
                }
            ),
            "witness bundle",
        )
        if value.get("authorizes_universal_proof") not in (None, False):
            raise AuthorityPromotionError(
                "a witness bundle cannot claim authorizes_universal_proof"
            )
        return cls(
            bundle_id=value.get("bundle_id", ""),
            role=value.get("role", ""),
            formula_id=value.get("formula_id", ""),
            traces=tuple(value.get("traces") or ()),
            differences=tuple(value.get("differences") or ()),
            observed_fields=tuple(value.get("observed_fields") or ()),
            redacted=value.get("redacted", True),
            description=value.get("description", ""),
            schema_version=value.get("schema_version", WITNESS_BUNDLE_SCHEMA_VERSION),
        )


@dataclass(frozen=True, slots=True)
class HyperpropertyEvaluation:
    """Result of a local hyperproperty check with an explicit authority ceiling.

    Local evaluation paths in this module always set
    ``authorizes_universal_proof`` to ``False``.  Bounded holds and clean
    samples remain inconclusive for universal claims.
    """

    verdict: HyperpropertyVerdict
    evidence_kind: HyperpropertyEvidenceKind
    authority_ceiling: EvidenceAuthorityCeiling
    formula_id: str
    policy_id: str
    reason: str
    bounded: bool = True
    authorizes_universal_proof: bool = False
    explored_traces: int = 0
    explored_pairs: int = 0
    maximum_pairs: int = 0
    bound_hit: bool = False
    witness_bundle: WitnessTraceBundle | None = None
    schema_version: str = HYPERPROPERTY_EVALUATION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "verdict", _enum(self.verdict, HyperpropertyVerdict, "verdict")
        )
        object.__setattr__(
            self,
            "evidence_kind",
            _enum(self.evidence_kind, HyperpropertyEvidenceKind, "evidence_kind"),
        )
        object.__setattr__(
            self,
            "authority_ceiling",
            _enum(self.authority_ceiling, EvidenceAuthorityCeiling, "authority_ceiling"),
        )
        object.__setattr__(self, "formula_id", _identifier(self.formula_id, "formula_id"))
        object.__setattr__(self, "policy_id", _identifier(self.policy_id, "policy_id"))
        object.__setattr__(self, "reason", _text(self.reason, "reason"))
        object.__setattr__(self, "bounded", _bool(self.bounded, "bounded"))
        object.__setattr__(
            self,
            "authorizes_universal_proof",
            _bool(self.authorizes_universal_proof, "authorizes_universal_proof"),
        )
        object.__setattr__(
            self, "explored_traces", _non_negative_int(self.explored_traces, "explored_traces")
        )
        object.__setattr__(
            self, "explored_pairs", _non_negative_int(self.explored_pairs, "explored_pairs")
        )
        object.__setattr__(
            self, "maximum_pairs", _non_negative_int(self.maximum_pairs, "maximum_pairs")
        )
        object.__setattr__(self, "bound_hit", _bool(self.bound_hit, "bound_hit"))
        if self.explored_pairs > self.maximum_pairs and self.maximum_pairs > 0:
            raise HyperpropertyValidationError("explored_pairs exceeds maximum_pairs")

        if self.evidence_kind in _BOUNDED_EVIDENCE:
            if self.authorizes_universal_proof:
                raise AuthorityPromotionError(
                    "bounded or sample evidence cannot authorize universal proof"
                )
            if self.authority_ceiling is EvidenceAuthorityCeiling.AUTHORITATIVE:
                raise AuthorityPromotionError(
                    "bounded or sample evidence cannot claim authoritative ceiling"
                )
            if self.authority_ceiling not in _NON_AUTHORITATIVE_CEILINGS:
                raise HyperpropertyValidationError(
                    "unsupported authority ceiling for local hyperproperty evidence"
                )
            if not self.bounded and self.evidence_kind is not HyperpropertyEvidenceKind.DECLARATION_ONLY:
                raise HyperpropertyValidationError(
                    "self-composition and sample evidence must remain bounded"
                )

        if self.witness_bundle is not None:
            if isinstance(self.witness_bundle, Mapping):
                object.__setattr__(
                    self,
                    "witness_bundle",
                    WitnessTraceBundle.from_dict(self.witness_bundle),
                )
            if not isinstance(self.witness_bundle, WitnessTraceBundle):
                raise HyperpropertyValidationError(
                    "witness_bundle must be a WitnessTraceBundle"
                )
            if self.witness_bundle.formula_id != self.formula_id:
                raise HyperpropertyValidationError(
                    "witness bundle formula_id does not match evaluation"
                )
            if self.verdict is HyperpropertyVerdict.VIOLATED:
                if self.witness_bundle.role not in {
                    WitnessRole.VIOLATION,
                    WitnessRole.COUNTEREXAMPLE,
                }:
                    raise HyperpropertyValidationError(
                        "violated evaluations require a violation/counterexample bundle"
                    )
            if self.witness_bundle.authorizes_universal_proof:
                raise AuthorityPromotionError(
                    "evaluation witness cannot authorize universal proof"
                )

        if (
            self.verdict is HyperpropertyVerdict.VIOLATED
            and self.witness_bundle is None
            and self.evidence_kind is HyperpropertyEvidenceKind.BOUNDED_SELF_COMPOSITION
        ):
            raise HyperpropertyValidationError(
                "a violated bounded self-composition result requires a witness bundle"
            )

        if self.schema_version != HYPERPROPERTY_EVALUATION_SCHEMA_VERSION:
            raise HyperpropertyValidationError(
                f"unsupported evaluation schema_version {self.schema_version!r}"
            )

    @property
    def conclusive(self) -> bool:
        return self.verdict in {HyperpropertyVerdict.HOLDS, HyperpropertyVerdict.VIOLATED}

    @property
    def holds(self) -> bool:
        if self.verdict is HyperpropertyVerdict.HOLDS:
            return True
        if self.verdict is HyperpropertyVerdict.VIOLATED:
            return False
        raise HyperpropertyValidationError(
            "inconclusive evaluations have no boolean holds value"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority_ceiling": self.authority_ceiling.value,
            "authorizes_universal_proof": False,
            "bound_hit": self.bound_hit,
            "bounded": self.bounded,
            "evidence_kind": self.evidence_kind.value,
            "explored_pairs": self.explored_pairs,
            "explored_traces": self.explored_traces,
            "formula_id": self.formula_id,
            "maximum_pairs": self.maximum_pairs,
            "policy_id": self.policy_id,
            "reason": self.reason,
            "schema_version": self.schema_version,
            "verdict": self.verdict.value,
            "witness_bundle": (
                None if self.witness_bundle is None else self.witness_bundle.to_dict()
            ),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> HyperpropertyEvaluation:
        value = _mapping(value, "hyperproperty evaluation")
        _reject_unknown(
            value,
            frozenset(
                {
                    "verdict",
                    "evidence_kind",
                    "authority_ceiling",
                    "formula_id",
                    "policy_id",
                    "reason",
                    "bounded",
                    "authorizes_universal_proof",
                    "explored_traces",
                    "explored_pairs",
                    "maximum_pairs",
                    "bound_hit",
                    "witness_bundle",
                    "schema_version",
                }
            ),
            "hyperproperty evaluation",
        )
        if value.get("authorizes_universal_proof") not in (None, False):
            raise AuthorityPromotionError(
                "evaluations cannot claim authorizes_universal_proof from local evidence"
            )
        raw_bundle = value.get("witness_bundle")
        return cls(
            verdict=value.get("verdict", ""),
            evidence_kind=value.get("evidence_kind", ""),
            authority_ceiling=value.get("authority_ceiling", ""),
            formula_id=value.get("formula_id", ""),
            policy_id=value.get("policy_id", ""),
            reason=value.get("reason", ""),
            bounded=value.get("bounded", True),
            authorizes_universal_proof=False,
            explored_traces=value.get("explored_traces", 0),
            explored_pairs=value.get("explored_pairs", 0),
            maximum_pairs=value.get("maximum_pairs", 0),
            bound_hit=value.get("bound_hit", False),
            witness_bundle=(
                None
                if raw_bundle is None
                else WitnessTraceBundle.from_dict(_mapping(raw_bundle, "witness_bundle"))
            ),
            schema_version=value.get(
                "schema_version", HYPERPROPERTY_EVALUATION_SCHEMA_VERSION
            ),
        )


@dataclass(frozen=True, slots=True)
class ExecutionTrace:
    """One concrete execution used only for local bounded evaluation.

    ``private_inputs`` never enters public serialization methods.  It exists
    solely so self-composition can detect high-input variation.
    """

    trace_id: str
    public_inputs: FrozenMap
    observations: FrozenMap
    private_inputs: FrozenMap = field(default_factory=FrozenMap, repr=False, compare=False)
    subject: FrozenMap = field(default_factory=FrozenMap)

    def __post_init__(self) -> None:
        object.__setattr__(self, "trace_id", _identifier(self.trace_id, "trace_id"))
        object.__setattr__(
            self, "public_inputs", _frozen(self.public_inputs, "public_inputs")
        )
        object.__setattr__(
            self, "observations", _frozen(self.observations, "observations")
        )
        object.__setattr__(
            self, "private_inputs", _frozen(self.private_inputs, "private_inputs")
        )
        object.__setattr__(self, "subject", _frozen(self.subject, "subject"))

    def subject_projection(self, fields: Sequence[str]) -> tuple[Any, ...]:
        return _projection(dict(self.subject), fields)

    def to_witness(
        self,
        variable_id: str,
        *,
        observation_fields: Sequence[str] | None = None,
    ) -> WitnessTrace:
        observations = dict(self.observations)
        if observation_fields is not None:
            observations = {
                field: _path_value(observations, field) for field in observation_fields
            }
        return WitnessTrace.from_execution(
            trace_id=self.trace_id,
            variable_id=variable_id,
            public_inputs=dict(self.public_inputs),
            observations=observations,
            subject=dict(self.subject),
            private_inputs=dict(self.private_inputs),
        )

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "observations_digest": _digest(dict(self.observations)),
            "private_inputs_redacted": True,
            "public_inputs_digest": _digest(dict(self.public_inputs)),
            "subject": dict(self.subject),
            "trace_id": self.trace_id,
        }


@dataclass(frozen=True, slots=True)
class HyperpropertyIR:
    """Immutable hyperproperty document implementing ``HyperpropertyIR@1``.

    The document identity excludes observational runtime keys.  Evaluation
    results may be attached under ``observations`` for transport but never
    enter the semantic preimage.
    """

    formula: HyperpropertyFormula
    information_flow_policy: InformationFlowPolicy
    self_composition_bound: SelfCompositionBound
    witness_bundles: tuple[WitnessTraceBundle, ...] = ()
    metadata: FrozenMap = field(default_factory=FrozenMap)
    observations: FrozenMap = field(default_factory=FrozenMap)
    document_id: str = ""
    schema_version: str = HYPERPROPERTY_IR_SCHEMA_VERSION

    INTERFACE: ClassVar[str] = HYPERPROPERTY_IR_INTERFACE

    def __post_init__(self) -> None:
        formula = self.formula
        if isinstance(formula, Mapping):
            formula = HyperpropertyFormula.from_dict(formula)
        if not isinstance(formula, HyperpropertyFormula):
            raise HyperpropertyValidationError("formula must be a HyperpropertyFormula")
        object.__setattr__(self, "formula", formula)

        policy = self.information_flow_policy
        if isinstance(policy, Mapping):
            policy = InformationFlowPolicy.from_dict(policy)
        if not isinstance(policy, InformationFlowPolicy):
            raise HyperpropertyValidationError(
                "information_flow_policy must be an InformationFlowPolicy"
            )
        if (
            formula.information_flow_policy_id
            and formula.information_flow_policy_id != policy.policy_id
        ):
            raise HyperpropertyValidationError(
                "formula information_flow_policy_id does not match embedded policy"
            )
        object.__setattr__(self, "information_flow_policy", policy)

        bound = self.self_composition_bound
        if isinstance(bound, Mapping):
            bound = SelfCompositionBound.from_dict(bound)
        if not isinstance(bound, SelfCompositionBound):
            raise HyperpropertyValidationError(
                "self_composition_bound must be a SelfCompositionBound"
            )
        object.__setattr__(self, "self_composition_bound", bound)

        bundles = _records(self.witness_bundles, WitnessTraceBundle, "witness_bundles")
        _unique_by(bundles, "bundle_id", "witness bundle")
        for bundle in bundles:
            if bundle.formula_id != formula.formula_id:
                raise HyperpropertyValidationError(
                    f"witness bundle {bundle.bundle_id} references a different formula"
                )
            if bundle.authorizes_universal_proof:
                raise AuthorityPromotionError(
                    "document witness bundles cannot authorize universal proof"
                )
        object.__setattr__(self, "witness_bundles", bundles)
        object.__setattr__(self, "metadata", _frozen(self.metadata, "metadata"))
        object.__setattr__(
            self, "observations", _frozen(self.observations, "observations")
        )

        if self.schema_version != HYPERPROPERTY_IR_SCHEMA_VERSION:
            raise HyperpropertyValidationError(
                f"unsupported hyperproperty-ir schema_version {self.schema_version!r}"
            )

        identity = self._compute_identity()
        if self.document_id and self.document_id != identity.cid:
            raise HyperpropertyValidationError(
                "document_id does not match canonical semantic content"
            )
        object.__setattr__(self, "document_id", identity.cid)

    @property
    def identity(self) -> CanonicalIdentity:
        return self._compute_identity()

    @property
    def content_id(self) -> str:
        return self.document_id

    @property
    def trace_cardinality(self) -> int:
        return self.formula.trace_cardinality

    @property
    def quantifier_signature(self) -> tuple[str, ...]:
        return self.formula.quantifier_signature

    def semantic_dict(self) -> dict[str, Any]:
        return {
            "formula": self.formula.semantic_dict(),
            "information_flow_policy": self.information_flow_policy.semantic_dict(),
            "interface": HYPERPROPERTY_IR_INTERFACE,
            "metadata": dict(self.metadata),
            "schema_version": self.schema_version,
            "self_composition_bound": self.self_composition_bound.to_dict(),
            "witness_bundles": [item.semantic_dict() for item in self.witness_bundles],
        }

    deterministic_dict = semantic_dict

    def to_dict(self) -> dict[str, Any]:
        result = self.semantic_dict()
        result["document_id"] = self.document_id
        result["observations"] = dict(self.observations)
        return result

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.semantic_dict())

    def _compute_identity(self) -> CanonicalIdentity:
        return canonical_identity(
            self.semantic_dict(),
            domain=HYPERPROPERTY_IR_IDENTITY_DOMAIN,
            schema_version=self.schema_version,
        )

    def evaluate_bounded_noninterference(
        self,
        traces: Sequence[ExecutionTrace],
    ) -> HyperpropertyEvaluation:
        """Run bounded self-composition for a two-trace noninterference formula.

        The result is always non-authoritative.  A clean sample under the
        declared bounds yields ``holds`` with authority ceiling ``bounded`` and
        ``authorizes_universal_proof=False``.
        """

        if self.formula.kind is not HyperpropertyKind.NONINTERFERENCE:
            raise HyperpropertyValidationError(
                "evaluate_bounded_noninterference requires a noninterference formula"
            )
        values = tuple(traces)
        if any(not isinstance(item, ExecutionTrace) for item in values):
            raise HyperpropertyValidationError("traces must contain ExecutionTrace values")

        bound = self.self_composition_bound
        policy = self.information_flow_policy
        selected = tuple(sorted(values, key=lambda item: item.trace_id))[: bound.max_traces]
        pairs = 0
        eligible_pairs = 0
        possible_pairs = len(selected) * max(0, len(selected) - 1) // 2
        bound_hit = len(values) > len(selected) or possible_pairs > bound.max_pairs
        left_var, right_var = (
            self.formula.variables[0].variable_id,
            self.formula.variables[1].variable_id,
        )

        for left_index, left in enumerate(selected):
            for right in selected[left_index + 1 :]:
                if pairs >= bound.max_pairs:
                    bound_hit = True
                    break
                pairs += 1
                if policy.subject_fields and left.subject_projection(
                    policy.subject_fields
                ) != right.subject_projection(policy.subject_fields):
                    continue
                if _projection(dict(left.public_inputs), policy.low_input_fields) != _projection(
                    dict(right.public_inputs), policy.low_input_fields
                ):
                    continue
                if dict(left.private_inputs) == dict(right.private_inputs):
                    # No high variation: pair does not stress noninterference.
                    continue
                eligible_pairs += 1
                differences = tuple(
                    ObservationDifference(
                        field=field_name,
                        left_digest=_digest(
                            _path_value(dict(left.observations), field_name)
                        ),
                        right_digest=_digest(
                            _path_value(dict(right.observations), field_name)
                        ),
                    )
                    for field_name in policy.observation_fields
                    if _path_value(dict(left.observations), field_name)
                    != _path_value(dict(right.observations), field_name)
                )
                if differences:
                    differences = differences[:1]
                    bundle = WitnessTraceBundle(
                        bundle_id=f"bundle:violation-{left.trace_id}-{right.trace_id}",
                        role=WitnessRole.COUNTEREXAMPLE,
                        formula_id=self.formula.formula_id,
                        traces=(
                            left.to_witness(
                                left_var, observation_fields=policy.observation_fields
                            ),
                            right.to_witness(
                                right_var, observation_fields=policy.observation_fields
                            ),
                        ),
                        differences=differences,
                        observed_fields=policy.observation_fields,
                        description="Bounded self-composition counterexample",
                    )
                    return HyperpropertyEvaluation(
                        verdict=HyperpropertyVerdict.VIOLATED,
                        evidence_kind=HyperpropertyEvidenceKind.BOUNDED_SELF_COMPOSITION,
                        authority_ceiling=EvidenceAuthorityCeiling.BOUNDED,
                        formula_id=self.formula.formula_id,
                        policy_id=policy.policy_id,
                        reason=(
                            "bounded self-composition found a low-observable difference "
                            "under varying high inputs"
                        ),
                        bounded=True,
                        authorizes_universal_proof=False,
                        explored_traces=len(selected),
                        explored_pairs=pairs,
                        maximum_pairs=bound.max_pairs,
                        bound_hit=bound_hit,
                        witness_bundle=bundle,
                    )
            if pairs >= bound.max_pairs:
                break

        if eligible_pairs == 0:
            verdict = HyperpropertyVerdict.INCONCLUSIVE
            reason = "no low-equivalent trace pair varied a private/high input"
            evidence = HyperpropertyEvidenceKind.BOUNDED_SELF_COMPOSITION
        elif bound_hit:
            verdict = HyperpropertyVerdict.INCONCLUSIVE
            reason = "no violation observed before a self-composition bound was reached"
            evidence = HyperpropertyEvidenceKind.BOUNDED_SELF_COMPOSITION
        else:
            verdict = HyperpropertyVerdict.HOLDS
            reason = (
                "all bounded low-equivalent high-varying pairs preserved approved observations"
            )
            evidence = HyperpropertyEvidenceKind.CLEAN_SAMPLE

        sample_bundle: WitnessTraceBundle | None = None
        if selected and verdict is HyperpropertyVerdict.HOLDS:
            sample_traces = tuple(
                item.to_witness(
                    self.formula.variables[min(index, 1)].variable_id,
                    observation_fields=policy.observation_fields,
                )
                for index, item in enumerate(selected[: self.trace_cardinality])
            )
            if sample_traces:
                sample_bundle = WitnessTraceBundle(
                    bundle_id="bundle:clean-sample",
                    role=WitnessRole.SUPPORTING_SAMPLE,
                    formula_id=self.formula.formula_id,
                    traces=sample_traces,
                    observed_fields=policy.observation_fields,
                    description="Clean bounded sample; not a universal proof",
                )

        return HyperpropertyEvaluation(
            verdict=verdict,
            evidence_kind=evidence,
            authority_ceiling=EvidenceAuthorityCeiling.BOUNDED,
            formula_id=self.formula.formula_id,
            policy_id=policy.policy_id,
            reason=reason,
            bounded=True,
            authorizes_universal_proof=False,
            explored_traces=len(selected),
            explored_pairs=pairs,
            maximum_pairs=bound.max_pairs,
            bound_hit=bound_hit,
            witness_bundle=sample_bundle,
        )

    @classmethod
    def noninterference_document(
        cls,
        *,
        policy: InformationFlowPolicy,
        bound: SelfCompositionBound | None = None,
        formula_id: str = "formula:noninterference",
        metadata: Mapping[str, Any] | None = None,
    ) -> HyperpropertyIR:
        """Convenience constructor for classical two-trace noninterference."""

        formula = HyperpropertyFormula.noninterference(
            formula_id=formula_id,
            policy_id=policy.policy_id,
        )
        return cls(
            formula=formula,
            information_flow_policy=policy,
            self_composition_bound=bound
            or SelfCompositionBound(
                "bound:default",
                max_traces=DEFAULT_MAX_COMPOSITION_TRACES,
                max_pairs=DEFAULT_MAX_COMPOSITION_PAIRS,
            ),
            metadata=_frozen(metadata or {}, "metadata"),
        )

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> HyperpropertyIR:
        value = _mapping(value, "hyperproperty document")
        _reject_unknown(
            value,
            frozenset(
                {
                    "formula",
                    "information_flow_policy",
                    "self_composition_bound",
                    "witness_bundles",
                    "metadata",
                    "observations",
                    "document_id",
                    "schema_version",
                    "interface",
                }
            ),
            "hyperproperty document",
        )
        if value.get("interface", HYPERPROPERTY_IR_INTERFACE) != HYPERPROPERTY_IR_INTERFACE:
            raise HyperpropertyValidationError("unsupported hyperproperty interface")
        return cls(
            formula=HyperpropertyFormula.from_dict(
                _mapping(value.get("formula", {}), "formula")
            ),
            information_flow_policy=InformationFlowPolicy.from_dict(
                _mapping(value.get("information_flow_policy", {}), "information_flow_policy")
            ),
            self_composition_bound=SelfCompositionBound.from_dict(
                _mapping(value.get("self_composition_bound", {}), "self_composition_bound")
            ),
            witness_bundles=tuple(value.get("witness_bundles") or ()),
            metadata=_frozen(_mapping(value.get("metadata", {}), "metadata"), "metadata"),
            observations=_frozen(
                _mapping(value.get("observations", {}), "observations"),
                "observations",
            ),
            document_id=value.get("document_id", ""),
            schema_version=value.get("schema_version", HYPERPROPERTY_IR_SCHEMA_VERSION),
        )


def quantifier_order_is_canonical(
    left: Sequence[QuantifierBinding],
    right: Sequence[QuantifierBinding],
) -> bool:
    """Whether two prefixes are identical in quantifier order and binding."""

    left_sig = [(item.quantifier, item.variable_id, item.index) for item in left]
    right_sig = [(item.quantifier, item.variable_id, item.index) for item in right]
    return left_sig == right_sig


def refuse_universal_proof(evaluation: HyperpropertyEvaluation) -> None:
    """Fail closed if a caller tries to promote local evidence to universal proof."""

    if evaluation.authorizes_universal_proof:
        raise AuthorityPromotionError(
            "local hyperproperty evidence cannot authorize universal proof"
        )
    if evaluation.authority_ceiling is EvidenceAuthorityCeiling.AUTHORITATIVE:
        raise AuthorityPromotionError(
            "local hyperproperty evidence cannot claim authoritative ceiling"
        )
    if evaluation.evidence_kind in _BOUNDED_EVIDENCE and evaluation.verdict is HyperpropertyVerdict.HOLDS:
        # Clean samples and bounded holds remain non-universal by construction.
        return


__all__ = [
    "DEFAULT_MAX_COMPOSITION_PAIRS",
    "DEFAULT_MAX_COMPOSITION_TRACES",
    "HYPERPROPERTY_IR_IDENTITY_DOMAIN",
    "HYPERPROPERTY_IR_INTERFACE",
    "HYPERPROPERTY_IR_SCHEMA_VERSION",
    "AuthorityPromotionError",
    "DeclassificationPolicy",
    "EvidenceAuthorityCeiling",
    "ExecutionTrace",
    "HyperpropertyEvaluation",
    "HyperpropertyEvidenceKind",
    "HyperpropertyFormula",
    "HyperpropertyIR",
    "HyperpropertyKind",
    "HyperpropertyValidationError",
    "HyperpropertyVerdict",
    "InformationFlowPolicy",
    "ObservationDifference",
    "ObservationKind",
    "ObservationSpec",
    "QuantifierBinding",
    "RelationalAtom",
    "RelationalCondition",
    "RelationalOperator",
    "RelationalRole",
    "SecurityLabel",
    "SecurityLevel",
    "SelfCompositionBound",
    "TraceQuantifier",
    "TraceVariable",
    "WitnessRole",
    "WitnessTrace",
    "WitnessTraceBundle",
    "quantifier_order_is_canonical",
    "refuse_universal_proof",
]
