"""Loss-aware vocabulary for cross-logic translations.

The records in this module describe *what happened* while lowering one logic
family into another.  They contain no provider execution state and make no
proof claim.  :mod:`.receipts` binds these records to concrete source and
target artifacts in the ``LogicTranslationReceipt@1`` interface.

The vocabulary intentionally adapts both the canonical family taxonomy and
the agent-supervisor translation classes:

* exact/lossless;
* equisatisfiable;
* conservative over- or under-approximation;
* bounded abstraction;
* approximate;
* heuristic.

Every record is immutable and defensively copies nested JSON data.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum, StrEnum
from typing import Any, Final

from ipfs_datasets_py.logic.families.models import (
    BoundednessKind,
    EvidenceAuthority,
    TranslationKind,
)
from ipfs_datasets_py.logic.ir_core.claims import FrozenMap
from ipfs_datasets_py.logic.ir_core.identity import CanonicalIdentity, canonical_identity

TRANSLATION_VOCABULARY_SCHEMA_VERSION: Final = "logic-translation-vocabulary/v1"
TRANSLATION_COMPILER_SCHEMA_VERSION: Final = "logic-translation-compiler/v1"
TRANSLATION_BOUND_SCHEMA_VERSION: Final = "logic-translation-bound/v1"
UNSUPPORTED_CONSTRUCT_SCHEMA_VERSION: Final = "logic-unsupported-construct/v1"
SEMANTIC_MUTATION_SCHEMA_VERSION: Final = "logic-semantic-mutation/v1"
TRANSLATION_WITNESS_SCHEMA_VERSION: Final = "logic-translation-witness/v1"
PRESERVATION_CLAIM_SCHEMA_VERSION: Final = "logic-preservation-claim/v1"

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/+@-]{0,511}$")


class TranslationValidationError(ValueError):
    """Raised when translation evidence is malformed or contradictory."""


class PreservationKind(StrEnum):
    """Semantic relationship claimed between source and target."""

    EXACT = "exact"
    EQUISATISFIABLE = "equisatisfiable"
    CONSERVATIVE = "conservative"
    BOUNDED = "bounded"
    APPROXIMATE = "approximate"
    HEURISTIC = "heuristic"

    # Descriptive aliases used by the family taxonomy and supervisor.
    LOSSLESS = "exact"
    CONSERVATIVE_APPROXIMATION = "conservative"
    BOUNDED_ABSTRACTION = "bounded"

    @classmethod
    def _missing_(cls, value: object) -> PreservationKind | None:
        compatibility = {
            "lossless": cls.EXACT,
            "conservative_approximation": cls.CONSERVATIVE,
            "bounded_abstraction": cls.BOUNDED,
        }
        return compatibility.get(value) if isinstance(value, str) else None


# Compatibility names used by the supervisor and early objective drafts.
TranslationClass = PreservationKind
TranslationExactness = PreservationKind


class ApproximationDirection(StrEnum):
    """Direction of a conservative translation."""

    NONE = "none"
    OVER = "over_approximation"
    UNDER = "under_approximation"


class UnsupportedHandling(StrEnum):
    """How a source construct was handled by the translation."""

    REJECTED = "rejected"
    ABSTRACTED = "abstracted"
    APPROXIMATED = "approximated"
    OMITTED = "omitted"


class SemanticMutationKind(StrEnum):
    """A semantic change made visible by a translation."""

    ENCODING = "encoding"
    ASSUMPTION_INTRODUCED = "assumption_introduced"
    BOUND_INTRODUCED = "bound_introduced"
    ABSTRACTION = "abstraction"
    CONSTRUCT_DROPPED = "construct_dropped"
    CONSTRUCT_INTRODUCED = "construct_introduced"
    POLARITY_CHANGED = "polarity_changed"
    QUANTIFIER_CHANGED = "quantifier_changed"
    DOMAIN_CHANGED = "domain_changed"
    TEMPORAL_SCOPE_CHANGED = "temporal_scope_changed"
    OTHER = "other"


_AUTHORITY_RANK: Final[dict[EvidenceAuthority, int]] = {
    EvidenceAuthority.NONE: 0,
    EvidenceAuthority.ADVISORY: 1,
    EvidenceAuthority.BOUNDED: 2,
    EvidenceAuthority.INDEPENDENTLY_CHECKABLE: 3,
    EvidenceAuthority.AUTHORITATIVE: 4,
}

_MAXIMUM_AUTHORITY: Final[dict[PreservationKind, EvidenceAuthority]] = {
    PreservationKind.EXACT: EvidenceAuthority.AUTHORITATIVE,
    PreservationKind.EQUISATISFIABLE: EvidenceAuthority.INDEPENDENTLY_CHECKABLE,
    PreservationKind.CONSERVATIVE: EvidenceAuthority.INDEPENDENTLY_CHECKABLE,
    PreservationKind.BOUNDED: EvidenceAuthority.BOUNDED,
    PreservationKind.APPROXIMATE: EvidenceAuthority.ADVISORY,
    PreservationKind.HEURISTIC: EvidenceAuthority.NONE,
}


def _text(value: object, label: str, *, optional: bool = False) -> str:
    if optional and value == "":
        return ""
    if not isinstance(value, str) or not value or value.strip() != value or "\x00" in value:
        qualifier = "an empty or " if optional else "a "
        raise TranslationValidationError(
            f"{label} must be {qualifier}non-empty trimmed string without NUL bytes"
        )
    return value


def _identifier(value: object, label: str) -> str:
    result = _text(value, label)
    if not _ID_RE.fullmatch(result):
        raise TranslationValidationError(f"{label} must be a stable identifier")
    return result


def _version(value: object, label: str) -> str:
    result = _text(value, label)
    if any(character.isspace() for character in result):
        raise TranslationValidationError(f"{label} must not contain whitespace")
    return result


def _enum(value: object, enum_type: type[Enum], label: str) -> Any:
    try:
        return value if isinstance(value, enum_type) else enum_type(value)
    except (TypeError, ValueError) as error:
        choices = ", ".join(repr(member.value) for member in enum_type)
        raise TranslationValidationError(f"{label} must be one of {choices}") from error


def _strings(
    values: Sequence[str] | object,
    label: str,
    *,
    identifiers: bool = False,
) -> tuple[str, ...]:
    if isinstance(values, (str, bytes, bytearray)) or not isinstance(values, Sequence):
        raise TranslationValidationError(f"{label} must be a sequence of strings")
    validator = _identifier if identifiers else _text
    result = tuple(validator(item, f"{label} item") for item in values)
    if len(result) != len(set(result)):
        raise TranslationValidationError(f"{label} must not contain duplicates")
    return tuple(sorted(result))


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TranslationValidationError(f"{label} must be a mapping")
    return value


def _frozen(value: Mapping[str, Any] | FrozenMap, label: str) -> FrozenMap:
    try:
        return value if isinstance(value, FrozenMap) else FrozenMap(value)
    except (TypeError, ValueError) as error:
        raise TranslationValidationError(
            f"{label} must contain immutable JSON-compatible data"
        ) from error


def _reject_unknown(value: Mapping[str, Any], allowed: frozenset[str], label: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise TranslationValidationError(f"unknown {label} field(s): {', '.join(unknown)}")


def authority_at_most(
    authority: EvidenceAuthority | str,
    ceiling: EvidenceAuthority | str,
) -> bool:
    """Return whether *authority* is no stronger than *ceiling*."""

    selected = _enum(authority, EvidenceAuthority, "authority")
    maximum = _enum(ceiling, EvidenceAuthority, "ceiling")
    return _AUTHORITY_RANK[selected] <= _AUTHORITY_RANK[maximum]


def maximum_authority_for(
    kind: PreservationKind | str,
) -> EvidenceAuthority:
    """Return the hard authority ceiling for a preservation class."""

    return _MAXIMUM_AUTHORITY[_enum(kind, PreservationKind, "kind")]


def taxonomy_translation_kind(
    kind: PreservationKind | str,
    direction: ApproximationDirection | str = ApproximationDirection.NONE,
) -> TranslationKind:
    """Map the richer receipt vocabulary to the canonical family taxonomy."""

    selected = _enum(kind, PreservationKind, "kind")
    selected_direction = _enum(direction, ApproximationDirection, "approximation_direction")
    if selected is PreservationKind.EXACT:
        return TranslationKind.LOSSLESS
    if selected is PreservationKind.EQUISATISFIABLE:
        return TranslationKind.EQUISATISFIABLE
    if selected is PreservationKind.CONSERVATIVE:
        if selected_direction is ApproximationDirection.OVER:
            return TranslationKind.SOUND_OVER_APPROXIMATION
        if selected_direction is ApproximationDirection.UNDER:
            return TranslationKind.SOUND_UNDER_APPROXIMATION
        raise TranslationValidationError(
            "conservative translations require an approximation direction"
        )
    if selected in {PreservationKind.BOUNDED, PreservationKind.APPROXIMATE}:
        return TranslationKind.SOUND_OVER_APPROXIMATION
    return TranslationKind.HEURISTIC


@dataclass(frozen=True, slots=True)
class CompilerBinding:
    """Pinned identity of one compiler/translator stage."""

    compiler_id: str
    compiler_version: str
    implementation_identity: str
    stage: str = "translate"
    configuration_identity: str = ""
    schema_version: str = TRANSLATION_COMPILER_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "compiler_id", _identifier(self.compiler_id, "compiler_id"))
        object.__setattr__(
            self,
            "compiler_version",
            _version(self.compiler_version, "compiler_version"),
        )
        object.__setattr__(
            self,
            "implementation_identity",
            _text(self.implementation_identity, "implementation_identity"),
        )
        object.__setattr__(self, "stage", _identifier(self.stage, "stage"))
        object.__setattr__(
            self,
            "configuration_identity",
            _text(
                self.configuration_identity,
                "configuration_identity",
                optional=True,
            ),
        )
        if self.schema_version != TRANSLATION_COMPILER_SCHEMA_VERSION:
            raise TranslationValidationError(
                f"unsupported compiler binding schema {self.schema_version!r}"
            )

    @property
    def identity(self) -> CanonicalIdentity:
        return canonical_identity(
            self.to_dict(),
            domain="logic.translation.compiler",
            schema_version=self.schema_version,
        )

    @property
    def binding_id(self) -> str:
        return self.identity.cid

    def to_dict(self) -> dict[str, Any]:
        return {
            "compiler_id": self.compiler_id,
            "compiler_version": self.compiler_version,
            "configuration_identity": self.configuration_identity,
            "implementation_identity": self.implementation_identity,
            "schema_version": self.schema_version,
            "stage": self.stage,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> CompilerBinding:
        value = _mapping(value, "compiler binding")
        _reject_unknown(
            value,
            frozenset(
                {
                    "compiler_id",
                    "compiler_version",
                    "configuration_identity",
                    "implementation_identity",
                    "schema_version",
                    "stage",
                }
            ),
            "compiler binding",
        )
        return cls(
            compiler_id=value.get("compiler_id", ""),
            compiler_version=value.get("compiler_version", ""),
            implementation_identity=value.get("implementation_identity", ""),
            stage=value.get("stage", "translate"),
            configuration_identity=value.get("configuration_identity", ""),
            schema_version=value.get("schema_version", TRANSLATION_COMPILER_SCHEMA_VERSION),
        )


# A descriptive compatibility alias.
TranslationCompiler = CompilerBinding


@dataclass(frozen=True, slots=True)
class TranslationBound:
    """A finite or approximate semantic limit introduced by translation."""

    bound_id: str
    kind: BoundednessKind
    limits: FrozenMap
    description: str
    schema_version: str = TRANSLATION_BOUND_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "bound_id", _identifier(self.bound_id, "bound_id"))
        object.__setattr__(self, "kind", _enum(self.kind, BoundednessKind, "kind"))
        limits = _frozen(self.limits, "limits")
        if not limits:
            raise TranslationValidationError("translation bounds require limits")
        for name, value in limits.items():
            _identifier(name, "limit name")
            if isinstance(value, bool) or not isinstance(value, (int, float, str)):
                raise TranslationValidationError(
                    "translation bound limits must be finite numbers or unit-bearing strings"
                )
            if isinstance(value, (int, float)) and value < 0:
                raise TranslationValidationError("translation bound limits must be non-negative")
            if isinstance(value, float) and not math.isfinite(value):
                raise TranslationValidationError("translation bound limits must be finite")
            if isinstance(value, str):
                _text(value, "limit value")
        object.__setattr__(self, "limits", limits)
        object.__setattr__(self, "description", _text(self.description, "description"))
        if self.kind in {
            BoundednessKind.UNBOUNDED,
            BoundednessKind.NOT_APPLICABLE,
        }:
            raise TranslationValidationError(
                "translation bounds must use a genuinely bounded or approximate kind"
            )
        if self.schema_version != TRANSLATION_BOUND_SCHEMA_VERSION:
            raise TranslationValidationError(
                f"unsupported translation bound schema {self.schema_version!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "bound_id": self.bound_id,
            "description": self.description,
            "kind": self.kind.value,
            "limits": self.limits.to_dict(),
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> TranslationBound:
        value = _mapping(value, "translation bound")
        _reject_unknown(
            value,
            frozenset({"bound_id", "description", "kind", "limits", "schema_version"}),
            "translation bound",
        )
        return cls(
            bound_id=value.get("bound_id", ""),
            kind=value.get("kind", ""),
            limits=_frozen(value.get("limits", {}), "limits"),
            description=value.get("description", ""),
            schema_version=value.get("schema_version", TRANSLATION_BOUND_SCHEMA_VERSION),
        )


@dataclass(frozen=True, slots=True)
class UnsupportedConstruct:
    """A source construct that the target route does not natively support."""

    construct_id: str
    construct_kind: str
    description: str
    handling: UnsupportedHandling
    source_ref_ids: tuple[str, ...] = ()
    schema_version: str = UNSUPPORTED_CONSTRUCT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "construct_id", _identifier(self.construct_id, "construct_id"))
        object.__setattr__(
            self, "construct_kind", _identifier(self.construct_kind, "construct_kind")
        )
        object.__setattr__(self, "description", _text(self.description, "description"))
        object.__setattr__(
            self,
            "handling",
            _enum(self.handling, UnsupportedHandling, "handling"),
        )
        object.__setattr__(
            self,
            "source_ref_ids",
            _strings(self.source_ref_ids, "source_ref_ids", identifiers=True),
        )
        if self.schema_version != UNSUPPORTED_CONSTRUCT_SCHEMA_VERSION:
            raise TranslationValidationError(
                f"unsupported construct schema {self.schema_version!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "construct_id": self.construct_id,
            "construct_kind": self.construct_kind,
            "description": self.description,
            "handling": self.handling.value,
            "schema_version": self.schema_version,
            "source_ref_ids": list(self.source_ref_ids),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> UnsupportedConstruct:
        value = _mapping(value, "unsupported construct")
        _reject_unknown(
            value,
            frozenset(
                {
                    "construct_id",
                    "construct_kind",
                    "description",
                    "handling",
                    "schema_version",
                    "source_ref_ids",
                }
            ),
            "unsupported construct",
        )
        return cls(
            construct_id=value.get("construct_id", ""),
            construct_kind=value.get("construct_kind", ""),
            description=value.get("description", ""),
            handling=value.get("handling", ""),
            source_ref_ids=tuple(value.get("source_ref_ids", ())),
            schema_version=value.get("schema_version", UNSUPPORTED_CONSTRUCT_SCHEMA_VERSION),
        )


@dataclass(frozen=True, slots=True)
class SemanticMutation:
    """An explicit semantic delta between source and target."""

    mutation_id: str
    kind: SemanticMutationKind
    description: str
    source_construct_ids: tuple[str, ...] = ()
    target_construct_ids: tuple[str, ...] = ()
    assumption_ids: tuple[str, ...] = ()
    bound_ids: tuple[str, ...] = ()
    schema_version: str = SEMANTIC_MUTATION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "mutation_id", _identifier(self.mutation_id, "mutation_id"))
        object.__setattr__(self, "kind", _enum(self.kind, SemanticMutationKind, "kind"))
        object.__setattr__(self, "description", _text(self.description, "description"))
        for name in (
            "source_construct_ids",
            "target_construct_ids",
            "assumption_ids",
            "bound_ids",
        ):
            object.__setattr__(
                self,
                name,
                _strings(getattr(self, name), name, identifiers=True),
            )
        if not self.source_construct_ids and not self.target_construct_ids:
            raise TranslationValidationError(
                "semantic mutations must identify source or target constructs"
            )
        if self.schema_version != SEMANTIC_MUTATION_SCHEMA_VERSION:
            raise TranslationValidationError(
                f"unsupported semantic mutation schema {self.schema_version!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "assumption_ids": list(self.assumption_ids),
            "bound_ids": list(self.bound_ids),
            "description": self.description,
            "kind": self.kind.value,
            "mutation_id": self.mutation_id,
            "schema_version": self.schema_version,
            "source_construct_ids": list(self.source_construct_ids),
            "target_construct_ids": list(self.target_construct_ids),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> SemanticMutation:
        value = _mapping(value, "semantic mutation")
        _reject_unknown(
            value,
            frozenset(
                {
                    "assumption_ids",
                    "bound_ids",
                    "description",
                    "kind",
                    "mutation_id",
                    "schema_version",
                    "source_construct_ids",
                    "target_construct_ids",
                }
            ),
            "semantic mutation",
        )
        return cls(
            mutation_id=value.get("mutation_id", ""),
            kind=value.get("kind", ""),
            description=value.get("description", ""),
            source_construct_ids=tuple(value.get("source_construct_ids", ())),
            target_construct_ids=tuple(value.get("target_construct_ids", ())),
            assumption_ids=tuple(value.get("assumption_ids", ())),
            bound_ids=tuple(value.get("bound_ids", ())),
            schema_version=value.get("schema_version", SEMANTIC_MUTATION_SCHEMA_VERSION),
        )


@dataclass(frozen=True, slots=True)
class TranslationWitness:
    """Content-addressed witness supporting a preservation claim."""

    witness_id: str
    witness_kind: str
    artifact_identity: str
    checker_id: str = ""
    checker_version: str = ""
    metadata: FrozenMap = field(default_factory=FrozenMap)
    schema_version: str = TRANSLATION_WITNESS_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "witness_id", _identifier(self.witness_id, "witness_id"))
        object.__setattr__(self, "witness_kind", _identifier(self.witness_kind, "witness_kind"))
        object.__setattr__(
            self,
            "artifact_identity",
            _text(self.artifact_identity, "artifact_identity"),
        )
        object.__setattr__(self, "checker_id", _text(self.checker_id, "checker_id", optional=True))
        object.__setattr__(
            self,
            "checker_version",
            _text(self.checker_version, "checker_version", optional=True),
        )
        if bool(self.checker_id) != bool(self.checker_version):
            raise TranslationValidationError(
                "checker_id and checker_version must be provided together"
            )
        object.__setattr__(self, "metadata", _frozen(self.metadata, "metadata"))
        if self.schema_version != TRANSLATION_WITNESS_SCHEMA_VERSION:
            raise TranslationValidationError(
                f"unsupported translation witness schema {self.schema_version!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_identity": self.artifact_identity,
            "checker_id": self.checker_id,
            "checker_version": self.checker_version,
            "metadata": self.metadata.to_dict(),
            "schema_version": self.schema_version,
            "witness_id": self.witness_id,
            "witness_kind": self.witness_kind,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> TranslationWitness:
        value = _mapping(value, "translation witness")
        _reject_unknown(
            value,
            frozenset(
                {
                    "artifact_identity",
                    "checker_id",
                    "checker_version",
                    "metadata",
                    "schema_version",
                    "witness_id",
                    "witness_kind",
                }
            ),
            "translation witness",
        )
        return cls(
            witness_id=value.get("witness_id", ""),
            witness_kind=value.get("witness_kind", ""),
            artifact_identity=value.get("artifact_identity", ""),
            checker_id=value.get("checker_id", ""),
            checker_version=value.get("checker_version", ""),
            metadata=_frozen(value.get("metadata", {}), "metadata"),
            schema_version=value.get("schema_version", TRANSLATION_WITNESS_SCHEMA_VERSION),
        )


@dataclass(frozen=True, slots=True)
class PreservationClaim:
    """Reviewed preservation claim and its result-class restrictions."""

    kind: PreservationKind
    approximation_direction: ApproximationDirection = ApproximationDirection.NONE
    preserved_property_ids: tuple[str, ...] = ()
    permitted_result_classes: tuple[str, ...] = ()
    conditions: tuple[str, ...] = ()
    description: str = ""
    schema_version: str = PRESERVATION_CLAIM_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", _enum(self.kind, PreservationKind, "kind"))
        object.__setattr__(
            self,
            "approximation_direction",
            _enum(
                self.approximation_direction,
                ApproximationDirection,
                "approximation_direction",
            ),
        )
        object.__setattr__(
            self,
            "preserved_property_ids",
            _strings(
                self.preserved_property_ids,
                "preserved_property_ids",
                identifiers=True,
            ),
        )
        object.__setattr__(
            self,
            "permitted_result_classes",
            _strings(self.permitted_result_classes, "permitted_result_classes"),
        )
        object.__setattr__(self, "conditions", _strings(self.conditions, "conditions"))
        object.__setattr__(
            self,
            "description",
            _text(self.description, "description", optional=True),
        )
        if self.kind is PreservationKind.CONSERVATIVE:
            if self.approximation_direction is ApproximationDirection.NONE:
                raise TranslationValidationError(
                    "conservative preservation requires an approximation direction"
                )
        elif self.approximation_direction is not ApproximationDirection.NONE:
            raise TranslationValidationError(
                "approximation_direction is only valid for conservative preservation"
            )
        if self.schema_version != PRESERVATION_CLAIM_SCHEMA_VERSION:
            raise TranslationValidationError(
                f"unsupported preservation claim schema {self.schema_version!r}"
            )

    @property
    def maximum_authority(self) -> EvidenceAuthority:
        return maximum_authority_for(self.kind)

    @property
    def taxonomy_kind(self) -> TranslationKind:
        return taxonomy_translation_kind(self.kind, self.approximation_direction)

    def permits_authority(self, authority: EvidenceAuthority | str) -> bool:
        return authority_at_most(authority, self.maximum_authority)

    def permits_result(self, result_class: str) -> bool:
        result = _text(result_class, "result_class")
        return not self.permitted_result_classes or result in self.permitted_result_classes

    def to_dict(self) -> dict[str, Any]:
        return {
            "approximation_direction": self.approximation_direction.value,
            "conditions": list(self.conditions),
            "description": self.description,
            "kind": self.kind.value,
            "permitted_result_classes": list(self.permitted_result_classes),
            "preserved_property_ids": list(self.preserved_property_ids),
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> PreservationClaim:
        value = _mapping(value, "preservation claim")
        _reject_unknown(
            value,
            frozenset(
                {
                    "approximation_direction",
                    "conditions",
                    "description",
                    "kind",
                    "permitted_result_classes",
                    "preserved_property_ids",
                    "schema_version",
                }
            ),
            "preservation claim",
        )
        return cls(
            kind=value.get("kind", ""),
            approximation_direction=value.get(
                "approximation_direction", ApproximationDirection.NONE.value
            ),
            preserved_property_ids=tuple(value.get("preserved_property_ids", ())),
            permitted_result_classes=tuple(value.get("permitted_result_classes", ())),
            conditions=tuple(value.get("conditions", ())),
            description=value.get("description", ""),
            schema_version=value.get("schema_version", PRESERVATION_CLAIM_SCHEMA_VERSION),
        )


__all__ = [
    "ApproximationDirection",
    "CompilerBinding",
    "PRESERVATION_CLAIM_SCHEMA_VERSION",
    "PreservationClaim",
    "PreservationKind",
    "SemanticMutation",
    "SemanticMutationKind",
    "TranslationBound",
    "TranslationClass",
    "TranslationCompiler",
    "TranslationExactness",
    "TranslationValidationError",
    "TranslationWitness",
    "UnsupportedConstruct",
    "UnsupportedHandling",
    "authority_at_most",
    "maximum_authority_for",
    "taxonomy_translation_kind",
]
