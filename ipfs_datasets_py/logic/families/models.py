"""Pure-data contracts for the canonical logic-family taxonomy.

The declarations in this module are deliberately independent of solver and
provider implementations.  They are safe to import for capability discovery,
configuration validation, and wire-contract generation without probing a
runtime or importing an optional theorem prover.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, ClassVar, Final, Mapping, Sequence


TAXONOMY_SCHEMA_VERSION: Final = "logic-family-taxonomy/v1"
DESCRIPTOR_VERSION: Final = "1.0.0"

_IDENTIFIER_RE = re.compile(r"^[a-z][a-z0-9]*(?:[._:-][a-z0-9]+)*$")


class TaxonomyError(ValueError):
    """Raised when a taxonomy declaration is malformed or contradictory."""


class SupportLevel(str, Enum):
    """How a provider supports one family or fragment."""

    NATIVE = "native"
    TRANSLATED = "translated"
    DECLARATION_ONLY = "declaration_only"
    UNSUPPORTED = "unsupported"


class RuntimeKind(str, Enum):
    """Execution environment required by a provider."""

    IN_PROCESS = "in_process"
    NATIVE_PROCESS = "native_process"
    JVM = "jvm"
    OCAML = "ocaml"
    WASM = "wasm"
    REMOTE_SERVICE = "remote_service"
    DECLARATION_ONLY = "declaration_only"


class EvidenceKind(str, Enum):
    """Kind of evidence an operation can emit."""

    KERNEL_CHECKED_PROOF = "kernel_checked_proof"
    CHECKED_PROOF = "checked_proof"
    PROOF_CERTIFICATE = "proof_certificate"
    UNSAT_CORE = "unsat_core"
    MODEL = "model"
    COUNTEREXAMPLE = "counterexample"
    TRACE = "trace"
    MONITOR_VERDICT = "monitor_verdict"
    POLICY_DECISION = "policy_decision"
    ATTESTATION = "attestation"
    CANDIDATE = "candidate"
    DECLARATION = "declaration"


class EvidenceAuthority(str, Enum):
    """Authority conveyed by evidence, kept separate from its format."""

    AUTHORITATIVE = "authoritative"
    INDEPENDENTLY_CHECKABLE = "independently_checkable"
    BOUNDED = "bounded"
    ADVISORY = "advisory"
    NONE = "none"


class BoundednessKind(str, Enum):
    """Semantic scope of an operation's result."""

    UNBOUNDED = "unbounded"
    FINITE_DOMAIN = "finite_domain"
    FINITE_TRACE = "finite_trace"
    STEP_BOUNDED = "step_bounded"
    RESOURCE_BOUNDED = "resource_bounded"
    APPROXIMATE = "approximate"
    NOT_APPLICABLE = "not_applicable"


class TranslationKind(str, Enum):
    """Semantic guarantee made by a translation."""

    LOSSLESS = "lossless"
    SOUND_OVER_APPROXIMATION = "sound_over_approximation"
    SOUND_UNDER_APPROXIMATION = "sound_under_approximation"
    EQUISATISFIABLE = "equisatisfiable"
    HEURISTIC = "heuristic"


def _text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise TaxonomyError(f"{field_name} must be a non-empty trimmed string")
    if "\x00" in value:
        raise TaxonomyError(f"{field_name} must not contain NUL bytes")
    return value


def _identifier(value: object, field_name: str) -> str:
    result = _text(value, field_name)
    if not _IDENTIFIER_RE.fullmatch(result):
        raise TaxonomyError(
            f"{field_name} must be a lowercase canonical identifier; got {result!r}"
        )
    return result


def _version(value: object, field_name: str = "version") -> str:
    result = _text(value, field_name)
    if "/" in result or any(character.isspace() for character in result):
        raise TaxonomyError(f"{field_name} must not contain '/' or whitespace")
    return result


def _strings(
    value: Sequence[str] | None,
    field_name: str,
    *,
    identifiers: bool = False,
) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise TaxonomyError(f"{field_name} must be a sequence of strings")
    validator = _identifier if identifiers else _text
    result = tuple(validator(item, f"{field_name} item") for item in value)
    if len(set(result)) != len(result):
        raise TaxonomyError(f"{field_name} must not contain duplicates")
    return tuple(sorted(result))


def _enum(value: object, enum_type: type[Enum], field_name: str) -> Any:
    try:
        return value if isinstance(value, enum_type) else enum_type(value)
    except (TypeError, ValueError) as error:
        choices = ", ".join(repr(member.value) for member in enum_type)
        raise TaxonomyError(f"{field_name} must be one of {choices}") from error


def _named_values(
    *,
    identifier: object,
    identifier_field: str,
    name: object,
    description: object,
    version: object,
    aliases: Sequence[str] | None,
    semantic_identity: object,
) -> tuple[str, str, str, str, tuple[str, ...], str]:
    return (
        _identifier(identifier, identifier_field),
        _text(name, "name"),
        _text(description, "description") if description else "",
        _version(version),
        _strings(aliases, "aliases"),
        _text(semantic_identity, "semantic_identity"),
    )


@dataclass(frozen=True, slots=True)
class LogicFragmentDescriptor:
    """A named syntactic or semantic fragment within a logic family."""

    fragment_id: str
    name: str
    semantic_identity: str
    description: str = ""
    aliases: tuple[str, ...] = ()
    version: str = DESCRIPTOR_VERSION

    schema_version: ClassVar[str] = TAXONOMY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        values = _named_values(
            identifier=self.fragment_id,
            identifier_field="fragment_id",
            name=self.name,
            description=self.description,
            version=self.version,
            aliases=self.aliases,
            semantic_identity=self.semantic_identity,
        )
        for field_name, value in zip(
            ("fragment_id", "name", "description", "version", "aliases", "semantic_identity"),
            values,
        ):
            object.__setattr__(self, field_name, value)

    @property
    def id(self) -> str:
        return self.fragment_id

    def to_dict(self) -> dict[str, Any]:
        return {
            "aliases": list(self.aliases),
            "description": self.description,
            "fragment_id": self.fragment_id,
            "name": self.name,
            "schema_version": self.schema_version,
            "semantic_identity": self.semantic_identity,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "LogicFragmentDescriptor":
        return cls(
            fragment_id=value["fragment_id"],
            name=value["name"],
            semantic_identity=value["semantic_identity"],
            description=value.get("description", ""),
            aliases=tuple(value.get("aliases", ())),
            version=value.get("version", DESCRIPTOR_VERSION),
        )


@dataclass(frozen=True, slots=True)
class LogicPropertyDescriptor:
    """A property vocabulary entry, independent of any provider syntax."""

    property_id: str
    name: str
    semantic_identity: str
    description: str = ""
    aliases: tuple[str, ...] = ()
    version: str = DESCRIPTOR_VERSION

    schema_version: ClassVar[str] = TAXONOMY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        values = _named_values(
            identifier=self.property_id,
            identifier_field="property_id",
            name=self.name,
            description=self.description,
            version=self.version,
            aliases=self.aliases,
            semantic_identity=self.semantic_identity,
        )
        for field_name, value in zip(
            ("property_id", "name", "description", "version", "aliases", "semantic_identity"),
            values,
        ):
            object.__setattr__(self, field_name, value)

    @property
    def id(self) -> str:
        return self.property_id

    def to_dict(self) -> dict[str, Any]:
        return {
            "aliases": list(self.aliases),
            "description": self.description,
            "name": self.name,
            "property_id": self.property_id,
            "schema_version": self.schema_version,
            "semantic_identity": self.semantic_identity,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "LogicPropertyDescriptor":
        return cls(
            property_id=value["property_id"],
            name=value["name"],
            semantic_identity=value["semantic_identity"],
            description=value.get("description", ""),
            aliases=tuple(value.get("aliases", ())),
            version=value.get("version", DESCRIPTOR_VERSION),
        )


@dataclass(frozen=True, slots=True)
class LogicOperationDescriptor:
    """An operation over declarations or properties."""

    operation_id: str
    name: str
    semantic_identity: str
    description: str = ""
    property_ids: tuple[str, ...] = ()
    requires_boundedness: bool = False
    aliases: tuple[str, ...] = ()
    version: str = DESCRIPTOR_VERSION

    schema_version: ClassVar[str] = TAXONOMY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        values = _named_values(
            identifier=self.operation_id,
            identifier_field="operation_id",
            name=self.name,
            description=self.description,
            version=self.version,
            aliases=self.aliases,
            semantic_identity=self.semantic_identity,
        )
        for field_name, value in zip(
            ("operation_id", "name", "description", "version", "aliases", "semantic_identity"),
            values,
        ):
            object.__setattr__(self, field_name, value)
        object.__setattr__(
            self,
            "property_ids",
            _strings(self.property_ids, "property_ids", identifiers=True),
        )
        if not isinstance(self.requires_boundedness, bool):
            raise TaxonomyError("requires_boundedness must be a boolean")

    @property
    def id(self) -> str:
        return self.operation_id

    def to_dict(self) -> dict[str, Any]:
        return {
            "aliases": list(self.aliases),
            "description": self.description,
            "name": self.name,
            "operation_id": self.operation_id,
            "property_ids": list(self.property_ids),
            "requires_boundedness": self.requires_boundedness,
            "schema_version": self.schema_version,
            "semantic_identity": self.semantic_identity,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "LogicOperationDescriptor":
        return cls(
            operation_id=value["operation_id"],
            name=value["name"],
            semantic_identity=value["semantic_identity"],
            description=value.get("description", ""),
            property_ids=tuple(value.get("property_ids", ())),
            requires_boundedness=value.get("requires_boundedness", False),
            aliases=tuple(value.get("aliases", ())),
            version=value.get("version", DESCRIPTOR_VERSION),
        )


@dataclass(frozen=True, slots=True)
class RuntimeDescriptor:
    """A declarative runtime requirement; never an executable runtime object."""

    runtime_id: str
    name: str
    runtime_kind: RuntimeKind
    description: str = ""
    requires_isolation: bool = True
    deterministic: bool | None = None
    version: str = DESCRIPTOR_VERSION

    schema_version: ClassVar[str] = TAXONOMY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "runtime_id", _identifier(self.runtime_id, "runtime_id"))
        object.__setattr__(self, "name", _text(self.name, "name"))
        object.__setattr__(
            self, "runtime_kind", _enum(self.runtime_kind, RuntimeKind, "runtime_kind")
        )
        object.__setattr__(
            self,
            "description",
            _text(self.description, "description") if self.description else "",
        )
        object.__setattr__(self, "version", _version(self.version))
        if not isinstance(self.requires_isolation, bool):
            raise TaxonomyError("requires_isolation must be a boolean")
        if self.deterministic is not None and not isinstance(self.deterministic, bool):
            raise TaxonomyError("deterministic must be a boolean or None")

    @property
    def id(self) -> str:
        return self.runtime_id

    def to_dict(self) -> dict[str, Any]:
        return {
            "description": self.description,
            "deterministic": self.deterministic,
            "name": self.name,
            "requires_isolation": self.requires_isolation,
            "runtime_id": self.runtime_id,
            "runtime_kind": self.runtime_kind.value,
            "schema_version": self.schema_version,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "RuntimeDescriptor":
        return cls(
            runtime_id=value["runtime_id"],
            name=value["name"],
            runtime_kind=value["runtime_kind"],
            description=value.get("description", ""),
            requires_isolation=value.get("requires_isolation", True),
            deterministic=value.get("deterministic"),
            version=value.get("version", DESCRIPTOR_VERSION),
        )


@dataclass(frozen=True, slots=True)
class EvidenceDescriptor:
    """Evidence format and its authority semantics."""

    evidence_id: str
    name: str
    evidence_kind: EvidenceKind
    authority: EvidenceAuthority
    description: str = ""
    machine_checkable: bool = False
    version: str = DESCRIPTOR_VERSION

    schema_version: ClassVar[str] = TAXONOMY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "evidence_id", _identifier(self.evidence_id, "evidence_id")
        )
        object.__setattr__(self, "name", _text(self.name, "name"))
        object.__setattr__(
            self, "evidence_kind", _enum(self.evidence_kind, EvidenceKind, "evidence_kind")
        )
        object.__setattr__(
            self, "authority", _enum(self.authority, EvidenceAuthority, "authority")
        )
        object.__setattr__(
            self,
            "description",
            _text(self.description, "description") if self.description else "",
        )
        object.__setattr__(self, "version", _version(self.version))
        if not isinstance(self.machine_checkable, bool):
            raise TaxonomyError("machine_checkable must be a boolean")
        if (
            self.authority is EvidenceAuthority.INDEPENDENTLY_CHECKABLE
            and not self.machine_checkable
        ):
            raise TaxonomyError(
                "independently_checkable evidence must be machine_checkable"
            )

    @property
    def id(self) -> str:
        return self.evidence_id

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority": self.authority.value,
            "description": self.description,
            "evidence_id": self.evidence_id,
            "evidence_kind": self.evidence_kind.value,
            "machine_checkable": self.machine_checkable,
            "name": self.name,
            "schema_version": self.schema_version,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "EvidenceDescriptor":
        return cls(
            evidence_id=value["evidence_id"],
            name=value["name"],
            evidence_kind=value["evidence_kind"],
            authority=value["authority"],
            description=value.get("description", ""),
            machine_checkable=value.get("machine_checkable", False),
            version=value.get("version", DESCRIPTOR_VERSION),
        )


@dataclass(frozen=True, slots=True)
class BoundednessDescriptor:
    """Bounds required for a claim and the scope of the resulting evidence."""

    boundedness_id: str
    name: str
    boundedness_kind: BoundednessKind
    description: str = ""
    limit_names: tuple[str, ...] = ()
    sound_for_property_ids: tuple[str, ...] = ()
    version: str = DESCRIPTOR_VERSION

    schema_version: ClassVar[str] = TAXONOMY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "boundedness_id",
            _identifier(self.boundedness_id, "boundedness_id"),
        )
        object.__setattr__(self, "name", _text(self.name, "name"))
        object.__setattr__(
            self,
            "boundedness_kind",
            _enum(self.boundedness_kind, BoundednessKind, "boundedness_kind"),
        )
        object.__setattr__(
            self,
            "description",
            _text(self.description, "description") if self.description else "",
        )
        object.__setattr__(
            self, "limit_names", _strings(self.limit_names, "limit_names", identifiers=True)
        )
        object.__setattr__(
            self,
            "sound_for_property_ids",
            _strings(
                self.sound_for_property_ids,
                "sound_for_property_ids",
                identifiers=True,
            ),
        )
        object.__setattr__(self, "version", _version(self.version))
        if (
            self.boundedness_kind
            not in {BoundednessKind.UNBOUNDED, BoundednessKind.NOT_APPLICABLE}
            and not self.limit_names
        ):
            raise TaxonomyError(
                "bounded descriptors must declare at least one limit name"
            )

    @property
    def id(self) -> str:
        return self.boundedness_id

    def to_dict(self) -> dict[str, Any]:
        return {
            "boundedness_id": self.boundedness_id,
            "boundedness_kind": self.boundedness_kind.value,
            "description": self.description,
            "limit_names": list(self.limit_names),
            "name": self.name,
            "schema_version": self.schema_version,
            "sound_for_property_ids": list(self.sound_for_property_ids),
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "BoundednessDescriptor":
        return cls(
            boundedness_id=value["boundedness_id"],
            name=value["name"],
            boundedness_kind=value["boundedness_kind"],
            description=value.get("description", ""),
            limit_names=tuple(value.get("limit_names", ())),
            sound_for_property_ids=tuple(value.get("sound_for_property_ids", ())),
            version=value.get("version", DESCRIPTOR_VERSION),
        )


@dataclass(frozen=True, slots=True)
class TranslationDescriptor:
    """A declared cross-family translation and its semantic losses."""

    translation_id: str
    source_family_id: str
    target_family_id: str
    translation_kind: TranslationKind
    preserves_property_ids: tuple[str, ...] = ()
    loses_property_ids: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    description: str = ""
    version: str = DESCRIPTOR_VERSION

    schema_version: ClassVar[str] = TAXONOMY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "translation_id",
            _identifier(self.translation_id, "translation_id"),
        )
        object.__setattr__(
            self,
            "source_family_id",
            _identifier(self.source_family_id, "source_family_id"),
        )
        object.__setattr__(
            self,
            "target_family_id",
            _identifier(self.target_family_id, "target_family_id"),
        )
        object.__setattr__(
            self,
            "translation_kind",
            _enum(self.translation_kind, TranslationKind, "translation_kind"),
        )
        object.__setattr__(
            self,
            "preserves_property_ids",
            _strings(
                self.preserves_property_ids,
                "preserves_property_ids",
                identifiers=True,
            ),
        )
        object.__setattr__(
            self,
            "loses_property_ids",
            _strings(
                self.loses_property_ids, "loses_property_ids", identifiers=True
            ),
        )
        object.__setattr__(
            self,
            "evidence_ids",
            _strings(self.evidence_ids, "evidence_ids", identifiers=True),
        )
        object.__setattr__(
            self,
            "description",
            _text(self.description, "description") if self.description else "",
        )
        object.__setattr__(self, "version", _version(self.version))
        overlap = set(self.preserves_property_ids) & set(self.loses_property_ids)
        if overlap:
            raise TaxonomyError(
                "translation cannot both preserve and lose properties: "
                + ", ".join(sorted(overlap))
            )
        if self.translation_kind is TranslationKind.LOSSLESS and self.loses_property_ids:
            raise TaxonomyError("a lossless translation cannot declare property loss")

    @property
    def id(self) -> str:
        return self.translation_id

    def to_dict(self) -> dict[str, Any]:
        return {
            "description": self.description,
            "evidence_ids": list(self.evidence_ids),
            "loses_property_ids": list(self.loses_property_ids),
            "preserves_property_ids": list(self.preserves_property_ids),
            "schema_version": self.schema_version,
            "source_family_id": self.source_family_id,
            "target_family_id": self.target_family_id,
            "translation_id": self.translation_id,
            "translation_kind": self.translation_kind.value,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "TranslationDescriptor":
        return cls(
            translation_id=value["translation_id"],
            source_family_id=value["source_family_id"],
            target_family_id=value["target_family_id"],
            translation_kind=value["translation_kind"],
            preserves_property_ids=tuple(value.get("preserves_property_ids", ())),
            loses_property_ids=tuple(value.get("loses_property_ids", ())),
            evidence_ids=tuple(value.get("evidence_ids", ())),
            description=value.get("description", ""),
            version=value.get("version", DESCRIPTOR_VERSION),
        )


@dataclass(frozen=True, slots=True)
class LogicFamilyDescriptor:
    """Canonical identity and supported vocabulary for one logic family."""

    family_id: str
    name: str
    semantic_identity: str
    description: str = ""
    aliases: tuple[str, ...] = ()
    fragment_ids: tuple[str, ...] = ()
    property_ids: tuple[str, ...] = ()
    operation_ids: tuple[str, ...] = ()
    declaration_only: bool = False
    equivalent_to: str | None = None
    version: str = DESCRIPTOR_VERSION

    schema_version: ClassVar[str] = TAXONOMY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        values = _named_values(
            identifier=self.family_id,
            identifier_field="family_id",
            name=self.name,
            description=self.description,
            version=self.version,
            aliases=self.aliases,
            semantic_identity=self.semantic_identity,
        )
        for field_name, value in zip(
            ("family_id", "name", "description", "version", "aliases", "semantic_identity"),
            values,
        ):
            object.__setattr__(self, field_name, value)
        for field_name in ("fragment_ids", "property_ids", "operation_ids"):
            object.__setattr__(
                self,
                field_name,
                _strings(getattr(self, field_name), field_name, identifiers=True),
            )
        if not isinstance(self.declaration_only, bool):
            raise TaxonomyError("declaration_only must be a boolean")
        if self.declaration_only and self.operation_ids:
            raise TaxonomyError(
                "declaration-only families cannot claim executable operations"
            )
        if self.equivalent_to is not None:
            object.__setattr__(
                self, "equivalent_to", _identifier(self.equivalent_to, "equivalent_to")
            )
            if self.equivalent_to == self.family_id:
                raise TaxonomyError("a family cannot be equivalent to itself")

    @property
    def id(self) -> str:
        return self.family_id

    def to_dict(self) -> dict[str, Any]:
        return {
            "aliases": list(self.aliases),
            "declaration_only": self.declaration_only,
            "description": self.description,
            "equivalent_to": self.equivalent_to,
            "family_id": self.family_id,
            "fragment_ids": list(self.fragment_ids),
            "name": self.name,
            "operation_ids": list(self.operation_ids),
            "property_ids": list(self.property_ids),
            "schema_version": self.schema_version,
            "semantic_identity": self.semantic_identity,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "LogicFamilyDescriptor":
        return cls(
            family_id=value["family_id"],
            name=value["name"],
            semantic_identity=value["semantic_identity"],
            description=value.get("description", ""),
            aliases=tuple(value.get("aliases", ())),
            fragment_ids=tuple(value.get("fragment_ids", ())),
            property_ids=tuple(value.get("property_ids", ())),
            operation_ids=tuple(value.get("operation_ids", ())),
            declaration_only=value.get("declaration_only", False),
            equivalent_to=value.get("equivalent_to"),
            version=value.get("version", DESCRIPTOR_VERSION),
        )


@dataclass(frozen=True, slots=True)
class FamilySupportDescriptor:
    """A provider's explicit support statement for exactly one family."""

    family_id: str
    support_level: SupportLevel
    fragment_ids: tuple[str, ...] = ()
    property_ids: tuple[str, ...] = ()
    operation_ids: tuple[str, ...] = ()
    translation_ids: tuple[str, ...] = ()
    notes: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "family_id", _identifier(self.family_id, "family_id")
        )
        object.__setattr__(
            self,
            "support_level",
            _enum(self.support_level, SupportLevel, "support_level"),
        )
        for field_name in (
            "fragment_ids",
            "property_ids",
            "operation_ids",
            "translation_ids",
        ):
            object.__setattr__(
                self,
                field_name,
                _strings(getattr(self, field_name), field_name, identifiers=True),
            )
        object.__setattr__(
            self, "notes", _text(self.notes, "notes") if self.notes else ""
        )
        if self.support_level is SupportLevel.UNSUPPORTED and any(
            (
                self.fragment_ids,
                self.property_ids,
                self.operation_ids,
                self.translation_ids,
            )
        ):
            raise TaxonomyError(
                "unsupported family declarations cannot claim capabilities"
            )
        if (
            self.support_level is SupportLevel.DECLARATION_ONLY
            and self.operation_ids
        ):
            raise TaxonomyError(
                "declaration-only support cannot claim executable operations"
            )
        if (
            self.support_level is SupportLevel.TRANSLATED
            and not self.translation_ids
        ):
            raise TaxonomyError(
                "translated support must identify at least one translation"
            )
        if (
            self.support_level is not SupportLevel.TRANSLATED
            and self.translation_ids
        ):
            raise TaxonomyError(
                "translation_ids are valid only for translated support"
            )

    @property
    def level(self) -> SupportLevel:
        return self.support_level

    def to_dict(self) -> dict[str, Any]:
        return {
            "family_id": self.family_id,
            "fragment_ids": list(self.fragment_ids),
            "notes": self.notes,
            "operation_ids": list(self.operation_ids),
            "property_ids": list(self.property_ids),
            "support_level": self.support_level.value,
            "translation_ids": list(self.translation_ids),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "FamilySupportDescriptor":
        return cls(
            family_id=value["family_id"],
            support_level=value["support_level"],
            fragment_ids=tuple(value.get("fragment_ids", ())),
            property_ids=tuple(value.get("property_ids", ())),
            operation_ids=tuple(value.get("operation_ids", ())),
            translation_ids=tuple(value.get("translation_ids", ())),
            notes=value.get("notes", ""),
        )


@dataclass(frozen=True, slots=True)
class ProviderCapabilityDescriptor:
    """Versioned, inert capability declaration for a logic provider."""

    provider_id: str
    provider_version: str
    family_support: tuple[FamilySupportDescriptor, ...]
    runtime_ids: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    boundedness_ids: tuple[str, ...] = ()
    translation_ids: tuple[str, ...] = ()
    deterministic: bool | None = None
    metadata: tuple[tuple[str, str], ...] = field(default_factory=tuple)
    version: str = DESCRIPTOR_VERSION

    schema_version: ClassVar[str] = "provider-capability/v1"

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "provider_id", _identifier(self.provider_id, "provider_id")
        )
        object.__setattr__(
            self, "provider_version", _version(self.provider_version, "provider_version")
        )
        object.__setattr__(self, "version", _version(self.version))
        if isinstance(self.family_support, (str, bytes, bytearray)) or not isinstance(
            self.family_support, Sequence
        ):
            raise TaxonomyError(
                "family_support must be a sequence of FamilySupportDescriptor values"
            )
        support = tuple(
            item
            if isinstance(item, FamilySupportDescriptor)
            else FamilySupportDescriptor.from_dict(item)
            for item in self.family_support
        )
        support = tuple(sorted(support, key=lambda item: item.family_id))
        family_ids = tuple(item.family_id for item in support)
        if len(set(family_ids)) != len(family_ids):
            raise TaxonomyError("family_support must declare each family at most once")
        object.__setattr__(self, "family_support", support)
        for field_name in (
            "runtime_ids",
            "evidence_ids",
            "boundedness_ids",
            "translation_ids",
        ):
            object.__setattr__(
                self,
                field_name,
                _strings(getattr(self, field_name), field_name, identifiers=True),
            )
        if self.deterministic is not None and not isinstance(self.deterministic, bool):
            raise TaxonomyError("deterministic must be a boolean or None")
        raw_metadata: object = self.metadata
        if isinstance(raw_metadata, Mapping):
            raw_metadata = tuple(raw_metadata.items())
        if (
            isinstance(raw_metadata, (str, bytes, bytearray))
            or not isinstance(raw_metadata, Sequence)
        ):
            raise TaxonomyError("metadata must be a mapping or key/value sequence")
        metadata: list[tuple[str, str]] = []
        for item in raw_metadata:
            if (
                not isinstance(item, Sequence)
                or isinstance(item, (str, bytes, bytearray))
                or len(item) != 2
            ):
                raise TaxonomyError("metadata entries must be key/value pairs")
            key = _identifier(item[0], "metadata key")
            metadata.append((key, _text(item[1], f"metadata[{key}]")))
        if len({key for key, _ in metadata}) != len(metadata):
            raise TaxonomyError("metadata must not contain duplicate keys")
        object.__setattr__(self, "metadata", tuple(sorted(metadata)))

    @property
    def capability_id(self) -> str:
        return f"{self.provider_id}@{self.provider_version}"

    def support_for(self, family_id: str) -> FamilySupportDescriptor:
        canonical = _identifier(family_id, "family_id")
        for support in self.family_support:
            if support.family_id == canonical:
                return support
        return FamilySupportDescriptor(canonical, SupportLevel.UNSUPPORTED)

    def supports(
        self,
        family_id: str,
        *,
        operation_id: str | None = None,
        include_declarations: bool = False,
    ) -> bool:
        support = self.support_for(family_id)
        permitted = {SupportLevel.NATIVE, SupportLevel.TRANSLATED}
        if include_declarations:
            permitted.add(SupportLevel.DECLARATION_ONLY)
        if support.support_level not in permitted:
            return False
        if operation_id is None:
            return True
        operation = _identifier(operation_id, "operation_id")
        return operation in support.operation_ids

    def to_dict(self) -> dict[str, Any]:
        return {
            "boundedness_ids": list(self.boundedness_ids),
            "deterministic": self.deterministic,
            "evidence_ids": list(self.evidence_ids),
            "family_support": [item.to_dict() for item in self.family_support],
            "metadata": {key: value for key, value in self.metadata},
            "provider_id": self.provider_id,
            "provider_version": self.provider_version,
            "runtime_ids": list(self.runtime_ids),
            "schema_version": self.schema_version,
            "translation_ids": list(self.translation_ids),
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ProviderCapabilityDescriptor":
        return cls(
            provider_id=value["provider_id"],
            provider_version=value["provider_version"],
            family_support=tuple(
                FamilySupportDescriptor.from_dict(item)
                for item in value.get("family_support", ())
            ),
            runtime_ids=tuple(value.get("runtime_ids", ())),
            evidence_ids=tuple(value.get("evidence_ids", ())),
            boundedness_ids=tuple(value.get("boundedness_ids", ())),
            translation_ids=tuple(value.get("translation_ids", ())),
            deterministic=value.get("deterministic"),
            metadata=value.get("metadata", {}),
            version=value.get("version", DESCRIPTOR_VERSION),
        )


# Short names make the wire vocabulary pleasant to consume while the explicit
# names above remain unambiguous in larger modules.
FamilyDescriptor = LogicFamilyDescriptor
FragmentDescriptor = LogicFragmentDescriptor
PropertyDescriptor = LogicPropertyDescriptor
OperationDescriptor = LogicOperationDescriptor
FamilySupport = FamilySupportDescriptor
ProviderFamilySupport = FamilySupportDescriptor
SupportMode = SupportLevel


__all__ = [
    "BoundednessDescriptor",
    "BoundednessKind",
    "DESCRIPTOR_VERSION",
    "EvidenceAuthority",
    "EvidenceDescriptor",
    "EvidenceKind",
    "FamilyDescriptor",
    "FamilySupport",
    "FamilySupportDescriptor",
    "FragmentDescriptor",
    "LogicFamilyDescriptor",
    "LogicFragmentDescriptor",
    "LogicOperationDescriptor",
    "LogicPropertyDescriptor",
    "OperationDescriptor",
    "PropertyDescriptor",
    "ProviderCapabilityDescriptor",
    "ProviderFamilySupport",
    "RuntimeDescriptor",
    "RuntimeKind",
    "SupportLevel",
    "SupportMode",
    "TAXONOMY_SCHEMA_VERSION",
    "TaxonomyError",
    "TranslationDescriptor",
    "TranslationKind",
]
