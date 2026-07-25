"""Deterministic, reversible migration maps for legacy Security IR artifacts.

This module does not move, rewrite, or delete artifact bytes.  It turns the
read-only ``SecurityArtifactInventory@1`` document into a content-bound map
from every legacy path and identifier to a proposed Security artifact layout:

``source -> inputs``, ``golden -> golden``, ``run -> runs``,
``promoted -> promoted``, and anything unsafe to promote -> ``archive``.

Filename variants, mutable aliases, transient compiler files, and unknown
formats are quarantined in the archive class.  Quarantine is not an authority
decision: every variant remains independently addressable and no member of an
ambiguous group is selected.

The serialized manifest has disjoint ``deterministic`` and ``observations``
objects.  Only the former contributes to ``manifest_id``.  Path migration is
idempotent, and every migrated path can be restored to its exact legacy path.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import tempfile
from types import MappingProxyType
from typing import Any, Final

from ..ir_core.canonical import canonical_json_bytes
from ..ir_core.identity import canonical_identity
from ..ir_core.provenance import (
    ProvenanceValidationError,
    freeze_json_mapping,
    thaw_json,
)


SECURITY_ARTIFACT_MIGRATION_SCHEMA_VERSION: Final = (
    "SecurityArtifactMigration@1"
)
SECURITY_ARTIFACT_MIGRATION_IDENTITY_DOMAIN: Final = (
    "security-artifact-migration"
)
SECURITY_ARTIFACT_INVENTORY_SCHEMA_VERSION: Final = (
    "SecurityArtifactInventory@1"
)
MIGRATION_POLICY_VERSION: Final = "security-artifact-classification/v1"
DEFAULT_INVENTORY_PATH: Final = (
    "docs/security_verification/security_ir_artifact_inventory.json"
)
DEFAULT_MANIFEST_PATH: Final = (
    "security_ir_artifacts/migrations/manifest.json"
)

# Compatibility names kept explicit for callers that use the shorter spelling.
MIGRATION_SCHEMA_VERSION = SECURITY_ARTIFACT_MIGRATION_SCHEMA_VERSION
SCHEMA_VERSION = SECURITY_ARTIFACT_MIGRATION_SCHEMA_VERSION

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ARTIFACT_ROOT = PurePosixPath("security_ir_artifacts")
_INVENTORY_CLASSIFICATIONS = frozenset(
    {
        "source",
        "golden",
        "run output",
        "promoted evidence",
        "environment record",
        "transient compiler output",
        "ambiguous",
        "unknown",
    }
)


class ArtifactMigrationValidationError(ValueError):
    """Raised when a migration manifest is malformed or non-reversible."""


class ArtifactMigrationIntegrityError(ArtifactMigrationValidationError):
    """Raised when legacy bytes or inventory bindings fail verification."""

    def __init__(self, report: "MigrationIntegrityReport") -> None:
        self.report = report
        summary = "; ".join(issue.message for issue in report.issues)
        super().__init__(summary or "Security artifact migration integrity failed")


class ArtifactClass(str, Enum):
    """Closed v1 storage classes used by the migration map."""

    SOURCE = "source"
    GOLDEN = "golden"
    RUN = "run"
    PROMOTED = "promoted"
    ARCHIVE = "archive"


# A descriptive alias matching the interface terminology.
MigrationClass = ArtifactClass


class MigrationIssueKind(str, Enum):
    """Stable integrity issue categories."""

    MISSING = "missing"
    CHANGED = "changed"
    DUPLICATE = "duplicate"
    UNBOUND = "unbound"
    INVALID = "invalid"


_CLASSIFICATION_MAP: Final[Mapping[str, ArtifactClass]] = MappingProxyType(
    {
        "source": ArtifactClass.SOURCE,
        "golden": ArtifactClass.GOLDEN,
        "run output": ArtifactClass.RUN,
        "environment record": ArtifactClass.RUN,
        "promoted evidence": ArtifactClass.PROMOTED,
        "transient compiler output": ArtifactClass.ARCHIVE,
        "ambiguous": ArtifactClass.ARCHIVE,
        "unknown": ArtifactClass.ARCHIVE,
    }
)

_DIRECTORY_MAP: Final[Mapping[ArtifactClass, str]] = MappingProxyType(
    {
        ArtifactClass.SOURCE: "inputs",
        ArtifactClass.GOLDEN: "golden",
        ArtifactClass.RUN: "runs",
        ArtifactClass.PROMOTED: "promoted",
        ArtifactClass.ARCHIVE: "archive",
    }
)


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ArtifactMigrationValidationError(f"{label} must be a mapping")
    return value


def _sequence(value: Any, label: str) -> Sequence[Any]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(
        value, Sequence
    ):
        raise ArtifactMigrationValidationError(f"{label} must be a sequence")
    return value


def _known_fields(
    value: Mapping[str, Any], allowed: frozenset[str], label: str
) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ArtifactMigrationValidationError(
            f"unknown {label} field(s): {', '.join(unknown)}"
        )


def _text(value: Any, label: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise ArtifactMigrationValidationError(f"{label} must be a string")
    if value != value.strip() or (not allow_empty and not value):
        raise ArtifactMigrationValidationError(
            f"{label} must be trimmed and {'may be' if allow_empty else 'not be'} empty"
        )
    return value


def _sha256(value: Any, label: str) -> str:
    value = _text(value, label)
    if not _SHA256_RE.fullmatch(value):
        raise ArtifactMigrationValidationError(
            f"{label} must be 64 lowercase hexadecimal characters"
        )
    return value


def _nonnegative_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ArtifactMigrationValidationError(
            f"{label} must be a non-negative integer"
        )
    return value


def _relative_path(value: Any, label: str) -> str:
    value = _text(value, label)
    if "\\" in value or "\x00" in value:
        raise ArtifactMigrationValidationError(
            f"{label} must be a repository-relative POSIX path"
        )
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or path.as_posix() != value
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ArtifactMigrationValidationError(
            f"{label} must be a normalized repository-relative POSIX path"
        )
    return value


def _legacy_relative_path(path: str) -> PurePosixPath:
    parsed = PurePosixPath(_relative_path(path, "legacy_path"))
    prefix = _ARTIFACT_ROOT.parts
    if parsed.parts[: len(prefix)] != prefix or len(parsed.parts) == len(prefix):
        raise ArtifactMigrationValidationError(
            "legacy_path must name a file below security_ir_artifacts"
        )
    if parsed.parts[len(prefix)] == "migrations":
        raise ArtifactMigrationValidationError(
            "migration manifests cannot migrate themselves"
        )
    return PurePosixPath(*parsed.parts[len(prefix) :])


def _target_path(legacy_path: str, target_class: ArtifactClass) -> str:
    relative = _legacy_relative_path(legacy_path)
    directory = _DIRECTORY_MAP[target_class]
    lane = "legacy-import" if target_class is ArtifactClass.RUN else "legacy"
    return (_ARTIFACT_ROOT / directory / lane / relative).as_posix()


def _record_identity_payload(
    *,
    legacy_path: str,
    legacy_sha256: str,
    legacy_size_bytes: int,
    target_class: ArtifactClass,
    target_path: str,
) -> dict[str, Any]:
    return {
        "legacy_path": legacy_path,
        "legacy_sha256": legacy_sha256,
        "legacy_size_bytes": legacy_size_bytes,
        "target_class": target_class.value,
        "target_path": target_path,
    }


def _artifact_id(**values: Any) -> str:
    identity = canonical_identity(
        _record_identity_payload(**values),
        domain="security-artifact-migration-record",
        schema_version=SECURITY_ARTIFACT_MIGRATION_SCHEMA_VERSION,
    )
    return f"security-artifact:{identity.cid}"


@dataclass(frozen=True, slots=True, order=True)
class LegacyIdentifier:
    """One verbatim ID/CID extracted by the legacy inventory."""

    field: str
    value: str

    def __post_init__(self) -> None:
        _text(self.field, "legacy identifier field")
        _text(self.value, "legacy identifier value")

    def to_dict(self) -> dict[str, str]:
        return {"field": self.field, "value": self.value}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "LegacyIdentifier":
        value = _mapping(value, "legacy identifier")
        _known_fields(value, frozenset({"field", "value"}), "legacy identifier")
        return cls(field=value.get("field", ""), value=value.get("value", ""))


@dataclass(frozen=True, slots=True)
class ArtifactMigrationRecord:
    """A lossless mapping from one legacy artifact to one proposed v1 record."""

    artifact_id: str
    legacy_path: str
    legacy_sha256: str
    legacy_size_bytes: int
    legacy_ids: tuple[LegacyIdentifier, ...]
    legacy_classification: str
    target_class: ArtifactClass
    target_path: str
    flags: tuple[str, ...] = ()
    detected_format: str = ""
    file_type: str = "regular-file"
    is_mutable_alias: bool = False
    is_new_variant: bool = False
    is_temporary: bool = False
    likely_producers: tuple[str, ...] = ()
    ambiguity_reasons: tuple[str, ...] = ()
    recommendations: tuple[str, ...] = ()
    variant_kinds: tuple[str, ...] = ()
    variant_of: str | None = None
    authority_selected: bool = False

    def __post_init__(self) -> None:
        legacy_ids = tuple(
            item
            if isinstance(item, LegacyIdentifier)
            else LegacyIdentifier.from_dict(_mapping(item, "legacy identifier"))
            for item in self.legacy_ids
        )
        try:
            target_class = (
                self.target_class
                if isinstance(self.target_class, ArtifactClass)
                else ArtifactClass(self.target_class)
            )
        except (TypeError, ValueError) as exc:
            raise ArtifactMigrationValidationError(
                f"unsupported target_class {self.target_class!r}"
            ) from exc
        flags = tuple(sorted(set(self.flags)))
        producers = tuple(self.likely_producers)
        ambiguity = tuple(self.ambiguity_reasons)
        recommendations = tuple(self.recommendations)
        variant_kinds = tuple(self.variant_kinds)
        object.__setattr__(self, "legacy_ids", legacy_ids)
        object.__setattr__(self, "target_class", target_class)
        object.__setattr__(self, "flags", flags)
        object.__setattr__(self, "likely_producers", producers)
        object.__setattr__(self, "ambiguity_reasons", ambiguity)
        object.__setattr__(self, "recommendations", recommendations)
        object.__setattr__(self, "variant_kinds", variant_kinds)
        self.validate()

    @property
    def is_unknown(self) -> bool:
        return "unknown" in self.flags

    @property
    def is_transient(self) -> bool:
        return "transient" in self.flags

    @property
    def requires_review(self) -> bool:
        return "requires_review" in self.flags

    def validate(self) -> None:
        legacy_path = _relative_path(self.legacy_path, "legacy_path")
        _legacy_relative_path(legacy_path)
        _sha256(self.legacy_sha256, "legacy_sha256")
        _nonnegative_int(self.legacy_size_bytes, "legacy_size_bytes")
        if self.legacy_classification not in _INVENTORY_CLASSIFICATIONS:
            raise ArtifactMigrationValidationError(
                f"unsupported legacy classification {self.legacy_classification!r}"
            )
        expected_class = _CLASSIFICATION_MAP[self.legacy_classification]
        if self.target_class is not expected_class:
            raise ArtifactMigrationValidationError(
                f"{self.legacy_classification!r} must map to "
                f"{expected_class.value!r}, not {self.target_class.value!r}"
            )
        expected_path = _target_path(legacy_path, self.target_class)
        if self.target_path != expected_path:
            raise ArtifactMigrationValidationError(
                f"target_path must be the reversible policy path {expected_path!r}"
            )
        expected_id = _artifact_id(
            legacy_path=legacy_path,
            legacy_sha256=self.legacy_sha256,
            legacy_size_bytes=self.legacy_size_bytes,
            target_class=self.target_class,
            target_path=self.target_path,
        )
        if self.artifact_id != expected_id:
            raise ArtifactMigrationValidationError(
                "artifact_id does not match the content-bound migration record"
            )
        if not isinstance(self.authority_selected, bool):
            raise ArtifactMigrationValidationError(
                "authority_selected must be a boolean"
            )
        if self.authority_selected:
            raise ArtifactMigrationValidationError(
                "the unreviewed migration manifest cannot select authority"
            )
        for label, values in (
            ("flags", self.flags),
            ("likely_producers", self.likely_producers),
            ("ambiguity_reasons", self.ambiguity_reasons),
            ("recommendations", self.recommendations),
            ("variant_kinds", self.variant_kinds),
        ):
            if any(not isinstance(item, str) or not item for item in values):
                raise ArtifactMigrationValidationError(
                    f"{label} must contain non-empty strings"
                )
        _text(self.detected_format, "detected_format")
        _text(self.file_type, "file_type")
        for label, value in (
            ("is_mutable_alias", self.is_mutable_alias),
            ("is_new_variant", self.is_new_variant),
            ("is_temporary", self.is_temporary),
        ):
            if not isinstance(value, bool):
                raise ArtifactMigrationValidationError(f"{label} must be a boolean")
        if self.variant_of is not None:
            _legacy_relative_path(self.variant_of)
        required_flags = set()
        if self.legacy_classification == "unknown":
            required_flags.update(("unknown", "requires_review"))
        if self.legacy_classification == "transient compiler output":
            required_flags.update(("transient", "requires_review"))
        if self.legacy_classification == "ambiguous":
            required_flags.update(("ambiguous", "requires_review"))
        if self.is_mutable_alias:
            required_flags.update(("mutable_alias", "requires_review"))
        if self.is_new_variant:
            required_flags.update(("new_variant", "requires_review"))
        if self.is_temporary:
            required_flags.add("temporary")
        if not required_flags <= set(self.flags):
            raise ArtifactMigrationValidationError(
                f"record is missing required flags {sorted(required_flags - set(self.flags))}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "ambiguity_reasons": list(self.ambiguity_reasons),
            "artifact_id": self.artifact_id,
            "authority_selected": self.authority_selected,
            "detected_format": self.detected_format,
            "file_type": self.file_type,
            "flags": list(self.flags),
            "is_mutable_alias": self.is_mutable_alias,
            "is_new_variant": self.is_new_variant,
            "is_temporary": self.is_temporary,
            "legacy_classification": self.legacy_classification,
            "legacy_ids": [item.to_dict() for item in self.legacy_ids],
            "legacy_path": self.legacy_path,
            "legacy_sha256": self.legacy_sha256,
            "legacy_size_bytes": self.legacy_size_bytes,
            "likely_producers": list(self.likely_producers),
            "recommendations": list(self.recommendations),
            "target_class": self.target_class.value,
            "target_path": self.target_path,
            "variant_kinds": list(self.variant_kinds),
            "variant_of": self.variant_of,
        }

    def to_inventory_record(self) -> dict[str, Any]:
        """Reconstruct the exact per-artifact legacy inventory record."""

        return {
            "ambiguity_reasons": list(self.ambiguity_reasons),
            "authority_selected": self.authority_selected,
            "classification": self.legacy_classification,
            "detected_format": self.detected_format,
            "file_type": self.file_type,
            "is_mutable_alias": self.is_mutable_alias,
            "is_new_variant": self.is_new_variant,
            "is_temporary": self.is_temporary,
            "legacy_ids": [item.to_dict() for item in self.legacy_ids],
            "likely_producers": list(self.likely_producers),
            "path": self.legacy_path,
            "recommendations": list(self.recommendations),
            "sha256": self.legacy_sha256,
            "size_bytes": self.legacy_size_bytes,
            "variant_kinds": list(self.variant_kinds),
            "variant_of": self.variant_of,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ArtifactMigrationRecord":
        value = _mapping(value, "migration record")
        fields = frozenset(
            {
                "ambiguity_reasons",
                "artifact_id",
                "authority_selected",
                "detected_format",
                "file_type",
                "flags",
                "is_mutable_alias",
                "is_new_variant",
                "is_temporary",
                "legacy_classification",
                "legacy_ids",
                "legacy_path",
                "legacy_sha256",
                "legacy_size_bytes",
                "likely_producers",
                "recommendations",
                "target_class",
                "target_path",
                "variant_kinds",
                "variant_of",
            }
        )
        _known_fields(value, fields, "migration record")
        return cls(
            artifact_id=value.get("artifact_id", ""),
            legacy_path=value.get("legacy_path", ""),
            legacy_sha256=value.get("legacy_sha256", ""),
            legacy_size_bytes=value.get("legacy_size_bytes", -1),
            legacy_ids=tuple(
                LegacyIdentifier.from_dict(_mapping(item, "legacy identifier"))
                for item in _sequence(value.get("legacy_ids", ()), "legacy_ids")
            ),
            legacy_classification=value.get("legacy_classification", ""),
            target_class=value.get("target_class", ""),
            target_path=value.get("target_path", ""),
            flags=tuple(_sequence(value.get("flags", ()), "flags")),
            detected_format=value.get("detected_format", ""),
            file_type=value.get("file_type", ""),
            is_mutable_alias=value.get("is_mutable_alias", False),
            is_new_variant=value.get("is_new_variant", False),
            is_temporary=value.get("is_temporary", False),
            likely_producers=tuple(
                _sequence(value.get("likely_producers", ()), "likely_producers")
            ),
            ambiguity_reasons=tuple(
                _sequence(value.get("ambiguity_reasons", ()), "ambiguity_reasons")
            ),
            recommendations=tuple(
                _sequence(value.get("recommendations", ()), "recommendations")
            ),
            variant_kinds=tuple(
                _sequence(value.get("variant_kinds", ()), "variant_kinds")
            ),
            variant_of=value.get("variant_of"),
            authority_selected=value.get("authority_selected", False),
        )


# Compatibility spelling useful in callers that treat entries as mappings.
MigrationRecord = ArtifactMigrationRecord


@dataclass(frozen=True, slots=True)
class InventoryBinding:
    """Deterministic binding to the read-only legacy inventory."""

    path: str
    schema_version: str
    inventory_sha256: str
    artifact_count: int
    scope: str

    def __post_init__(self) -> None:
        _relative_path(self.path, "inventory path")
        if self.schema_version != SECURITY_ARTIFACT_INVENTORY_SCHEMA_VERSION:
            raise ArtifactMigrationValidationError(
                f"unsupported inventory schema {self.schema_version!r}"
            )
        _sha256(self.inventory_sha256, "inventory_sha256")
        _nonnegative_int(self.artifact_count, "inventory artifact_count")
        _text(self.scope, "inventory scope")

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_count": self.artifact_count,
            "inventory_sha256": self.inventory_sha256,
            "path": self.path,
            "schema_version": self.schema_version,
            "scope": self.scope,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "InventoryBinding":
        value = _mapping(value, "source_inventory")
        _known_fields(
            value,
            frozenset(
                {
                    "artifact_count",
                    "inventory_sha256",
                    "path",
                    "schema_version",
                    "scope",
                }
            ),
            "source_inventory",
        )
        return cls(
            path=value.get("path", ""),
            schema_version=value.get("schema_version", ""),
            inventory_sha256=value.get("inventory_sha256", ""),
            artifact_count=value.get("artifact_count", -1),
            scope=value.get("scope", ""),
        )


@dataclass(frozen=True, slots=True)
class MigrationIntegrityIssue:
    kind: MigrationIssueKind
    message: str
    legacy_path: str = ""
    expected: str = ""
    actual: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "actual": self.actual,
            "expected": self.expected,
            "kind": self.kind.value,
            "legacy_path": self.legacy_path,
            "message": self.message,
        }


@dataclass(frozen=True, slots=True)
class MigrationIntegrityReport:
    """Deterministically ordered migration/inventory integrity receipt."""

    manifest_id: str
    inventory_sha256: str
    checked_artifact_count: int
    issues: tuple[MigrationIntegrityIssue, ...] = ()

    @property
    def valid(self) -> bool:
        return not self.issues

    @property
    def is_valid(self) -> bool:
        return self.valid

    @property
    def issue_kinds(self) -> tuple[MigrationIssueKind, ...]:
        return tuple(
            sorted({issue.kind for issue in self.issues}, key=lambda item: item.value)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "checked_artifact_count": self.checked_artifact_count,
            "inventory_sha256": self.inventory_sha256,
            "issues": [issue.to_dict() for issue in self.issues],
            "manifest_id": self.manifest_id,
            "valid": self.valid,
        }


@dataclass(frozen=True, slots=True)
class SecurityArtifactMigration:
    """Immutable migration manifest with path and legacy-ID indexes."""

    artifacts: tuple[ArtifactMigrationRecord, ...]
    source_inventory: InventoryBinding
    repository_commit: str
    observations: Mapping[str, Any] = field(default_factory=dict)
    manifest_id: str = ""
    schema_version: str = SECURITY_ARTIFACT_MIGRATION_SCHEMA_VERSION
    migration_policy: str = MIGRATION_POLICY_VERSION

    def __post_init__(self) -> None:
        artifacts = tuple(
            item
            if isinstance(item, ArtifactMigrationRecord)
            else ArtifactMigrationRecord.from_dict(_mapping(item, "migration record"))
            for item in self.artifacts
        )
        source_inventory = (
            self.source_inventory
            if isinstance(self.source_inventory, InventoryBinding)
            else InventoryBinding.from_dict(
                _mapping(self.source_inventory, "source_inventory")
            )
        )
        try:
            observations = freeze_json_mapping(self.observations)
        except ProvenanceValidationError as exc:
            raise ArtifactMigrationValidationError(str(exc)) from exc
        object.__setattr__(self, "artifacts", artifacts)
        object.__setattr__(self, "source_inventory", source_inventory)
        object.__setattr__(self, "observations", observations)
        self.validate(check_identity=False)
        identity = self._compute_identity()
        if self.manifest_id and self.manifest_id != identity.cid:
            raise ArtifactMigrationValidationError(
                "manifest_id does not match deterministic migration content"
            )
        object.__setattr__(self, "manifest_id", identity.cid)

    @property
    def records(self) -> tuple[ArtifactMigrationRecord, ...]:
        return self.artifacts

    @property
    def artifact_count(self) -> int:
        return len(self.artifacts)

    @property
    def sha256(self) -> str:
        return self._compute_identity().hexdigest

    @property
    def class_counts(self) -> dict[str, int]:
        counts = Counter(item.target_class.value for item in self.artifacts)
        return {
            artifact_class.value: counts.get(artifact_class.value, 0)
            for artifact_class in ArtifactClass
        }

    @property
    def flag_counts(self) -> dict[str, int]:
        counts = Counter(flag for item in self.artifacts for flag in item.flags)
        required = (
            "ambiguous",
            "mutable_alias",
            "new_variant",
            "requires_review",
            "temporary",
            "transient",
            "unknown",
        )
        return {name: counts.get(name, 0) for name in required}

    def _compute_identity(self):
        return canonical_identity(
            self.deterministic_dict(),
            domain=SECURITY_ARTIFACT_MIGRATION_IDENTITY_DOMAIN,
            schema_version=SECURITY_ARTIFACT_MIGRATION_SCHEMA_VERSION,
        )

    def deterministic_dict(self) -> dict[str, Any]:
        """Return exactly the fields included in ``manifest_id``."""

        return {
            "artifact_count": self.artifact_count,
            "artifacts": [
                item.to_dict()
                for item in sorted(self.artifacts, key=lambda item: item.legacy_path)
            ],
            "class_counts": self.class_counts,
            "flag_counts": self.flag_counts,
            "migration_policy": self.migration_policy,
            "repository_commit": self.repository_commit,
            "source_inventory": self.source_inventory.to_dict(),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "deterministic": self.deterministic_dict(),
            "manifest_id": self.manifest_id,
            "observations": thaw_json(self.observations),
            "schema_version": self.schema_version,
        }

    def deterministic_bytes(self) -> bytes:
        self.validate()
        return canonical_json_bytes(self.deterministic_dict())

    def canonical_bytes(self) -> bytes:
        self.validate()
        return canonical_json_bytes(self.to_dict())

    def to_json(self, *, pretty: bool = False) -> str:
        if pretty:
            return (
                json.dumps(
                    self.to_dict(),
                    ensure_ascii=True,
                    indent=2,
                    sort_keys=True,
                )
                + "\n"
            )
        return self.canonical_bytes().decode("utf-8")

    def validate(self, *, check_identity: bool = True) -> None:
        if self.schema_version != SECURITY_ARTIFACT_MIGRATION_SCHEMA_VERSION:
            raise ArtifactMigrationValidationError(
                f"unsupported migration schema {self.schema_version!r}"
            )
        if self.migration_policy != MIGRATION_POLICY_VERSION:
            raise ArtifactMigrationValidationError(
                f"unsupported migration policy {self.migration_policy!r}"
            )
        _text(self.repository_commit, "repository_commit")
        if len(self.artifacts) != self.source_inventory.artifact_count:
            raise ArtifactMigrationValidationError(
                "artifact count does not match the source inventory binding"
            )
        for attribute in ("artifact_id", "legacy_path", "target_path"):
            values = [getattr(item, attribute) for item in self.artifacts]
            duplicates = sorted(
                value for value, count in Counter(values).items() if count > 1
            )
            if duplicates:
                raise ArtifactMigrationValidationError(
                    f"duplicate {attribute} values: {duplicates}"
                )
        if check_identity and self._compute_identity().cid != self.manifest_id:
            raise ArtifactMigrationValidationError(
                "manifest_id does not match deterministic migration content"
            )

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SecurityArtifactMigration":
        value = _mapping(value, "migration manifest")
        _known_fields(
            value,
            frozenset(
                {"deterministic", "manifest_id", "observations", "schema_version"}
            ),
            "migration manifest",
        )
        deterministic = _mapping(value.get("deterministic"), "deterministic")
        _known_fields(
            deterministic,
            frozenset(
                {
                    "artifact_count",
                    "artifacts",
                    "class_counts",
                    "flag_counts",
                    "migration_policy",
                    "repository_commit",
                    "source_inventory",
                }
            ),
            "deterministic",
        )
        artifacts = tuple(
            ArtifactMigrationRecord.from_dict(_mapping(item, "migration record"))
            for item in _sequence(
                deterministic.get("artifacts", ()), "deterministic.artifacts"
            )
        )
        declared_count = deterministic.get("artifact_count", -1)
        if declared_count != len(artifacts):
            raise ArtifactMigrationValidationError(
                "deterministic.artifact_count does not match artifacts"
            )
        manifest = cls(
            artifacts=artifacts,
            source_inventory=InventoryBinding.from_dict(
                _mapping(
                    deterministic.get("source_inventory"),
                    "deterministic.source_inventory",
                )
            ),
            repository_commit=deterministic.get("repository_commit", ""),
            observations=_mapping(value.get("observations", {}), "observations"),
            manifest_id=value.get("manifest_id", ""),
            schema_version=value.get("schema_version", ""),
            migration_policy=deterministic.get("migration_policy", ""),
        )
        if deterministic.get("class_counts") != manifest.class_counts:
            raise ArtifactMigrationValidationError(
                "deterministic.class_counts does not match artifacts"
            )
        if deterministic.get("flag_counts") != manifest.flag_counts:
            raise ArtifactMigrationValidationError(
                "deterministic.flag_counts does not match artifacts"
            )
        return manifest

    @classmethod
    def from_json(
        cls, value: str | bytes | bytearray
    ) -> "SecurityArtifactMigration":
        try:
            decoded = json.loads(value)
        except (TypeError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ArtifactMigrationValidationError(
                "migration manifest is not valid JSON"
            ) from exc
        return cls.from_dict(_mapping(decoded, "migration manifest"))

    def _legacy_index(self) -> dict[str, ArtifactMigrationRecord]:
        return {item.legacy_path: item for item in self.artifacts}

    def _target_index(self) -> dict[str, ArtifactMigrationRecord]:
        return {item.target_path: item for item in self.artifacts}

    def migrate_path(self, path: str | PurePosixPath) -> str:
        """Map a legacy path once; an already migrated path is unchanged."""

        normalized = _relative_path(str(path), "artifact path")
        target_index = self._target_index()
        if normalized in target_index:
            return normalized
        try:
            return self._legacy_index()[normalized].target_path
        except KeyError as exc:
            raise KeyError(f"path is not bound by migration: {normalized}") from exc

    def restore_path(self, path: str | PurePosixPath) -> str:
        """Restore a migrated path; an exact legacy path is unchanged."""

        normalized = _relative_path(str(path), "artifact path")
        legacy_index = self._legacy_index()
        if normalized in legacy_index:
            return normalized
        try:
            return self._target_index()[normalized].legacy_path
        except KeyError as exc:
            raise KeyError(f"path is not bound by migration: {normalized}") from exc

    # Reversal-oriented spelling used by migration consumers.
    reverse_path = restore_path

    def restore_record(
        self, path: str | PurePosixPath
    ) -> dict[str, Any]:
        """Recover the exact legacy inventory record from either path form."""

        legacy_path = self.restore_path(path)
        return self._legacy_index()[legacy_path].to_inventory_record()

    def records_for_legacy_id(
        self, field: str, value: str
    ) -> tuple[ArtifactMigrationRecord, ...]:
        """Return every matching record without selecting among duplicates."""

        needle = LegacyIdentifier(field=field, value=value)
        return tuple(
            sorted(
                (item for item in self.artifacts if needle in item.legacy_ids),
                key=lambda item: item.legacy_path,
            )
        )

    def audit_integrity(
        self,
        repository_root: str | Path,
        *,
        inventory: Mapping[str, Any] | None = None,
    ) -> MigrationIntegrityReport:
        """Verify exact legacy bytes and, when supplied, every inventory field."""

        root = Path(repository_root)
        issues: list[MigrationIntegrityIssue] = []
        checked = 0
        for record in sorted(self.artifacts, key=lambda item: item.legacy_path):
            path = root.joinpath(*PurePosixPath(record.legacy_path).parts)
            try:
                if path.is_symlink():
                    content = os.readlink(path).encode(
                        "utf-8", errors="surrogateescape"
                    )
                else:
                    content = path.read_bytes()
            except (FileNotFoundError, IsADirectoryError, OSError) as exc:
                issues.append(
                    MigrationIntegrityIssue(
                        kind=MigrationIssueKind.MISSING,
                        message=f"legacy artifact is missing: {record.legacy_path}",
                        legacy_path=record.legacy_path,
                        expected=record.legacy_sha256,
                        actual=type(exc).__name__,
                    )
                )
                continue
            checked += 1
            actual_sha256 = hashlib.sha256(content).hexdigest()
            if actual_sha256 != record.legacy_sha256:
                issues.append(
                    MigrationIntegrityIssue(
                        kind=MigrationIssueKind.CHANGED,
                        message=f"legacy artifact digest changed: {record.legacy_path}",
                        legacy_path=record.legacy_path,
                        expected=record.legacy_sha256,
                        actual=actual_sha256,
                    )
                )
            if len(content) != record.legacy_size_bytes:
                issues.append(
                    MigrationIntegrityIssue(
                        kind=MigrationIssueKind.CHANGED,
                        message=f"legacy artifact size changed: {record.legacy_path}",
                        legacy_path=record.legacy_path,
                        expected=str(record.legacy_size_bytes),
                        actual=str(len(content)),
                    )
                )
        if inventory is not None:
            issues.extend(self._inventory_issues(inventory))
        issues.sort(
            key=lambda item: (
                item.legacy_path.encode("utf-8"),
                item.kind.value,
                item.message,
            )
        )
        return MigrationIntegrityReport(
            manifest_id=self.manifest_id,
            inventory_sha256=self.source_inventory.inventory_sha256,
            checked_artifact_count=checked,
            issues=tuple(issues),
        )

    def verify_integrity(
        self,
        repository_root: str | Path,
        *,
        inventory: Mapping[str, Any] | None = None,
    ) -> MigrationIntegrityReport:
        report = self.audit_integrity(repository_root, inventory=inventory)
        if not report.valid:
            raise ArtifactMigrationIntegrityError(report)
        return report

    def _inventory_issues(
        self, inventory: Mapping[str, Any]
    ) -> list[MigrationIntegrityIssue]:
        issues: list[MigrationIntegrityIssue] = []
        try:
            rebuilt = build_migration_manifest(
                inventory,
                source_inventory_path=self.source_inventory.path,
                repository_commit=self.repository_commit,
                observations=thaw_json(self.observations),
            )
        except (ArtifactMigrationValidationError, KeyError, TypeError) as exc:
            return [
                MigrationIntegrityIssue(
                    kind=MigrationIssueKind.INVALID,
                    message=f"source inventory is invalid: {exc}",
                )
            ]
        if rebuilt.source_inventory != self.source_inventory:
            issues.append(
                MigrationIntegrityIssue(
                    kind=MigrationIssueKind.CHANGED,
                    message="source inventory binding changed",
                    expected=self.source_inventory.inventory_sha256,
                    actual=rebuilt.source_inventory.inventory_sha256,
                )
            )
        expected = {item.legacy_path: item for item in self.artifacts}
        actual = {item.legacy_path: item for item in rebuilt.artifacts}
        for path in sorted(set(expected) - set(actual)):
            issues.append(
                MigrationIntegrityIssue(
                    kind=MigrationIssueKind.UNBOUND,
                    message=f"manifest path is absent from inventory: {path}",
                    legacy_path=path,
                )
            )
        for path in sorted(set(actual) - set(expected)):
            issues.append(
                MigrationIntegrityIssue(
                    kind=MigrationIssueKind.UNBOUND,
                    message=f"inventory path is absent from manifest: {path}",
                    legacy_path=path,
                )
            )
        for path in sorted(set(expected) & set(actual)):
            if expected[path] != actual[path]:
                issues.append(
                    MigrationIntegrityIssue(
                        kind=MigrationIssueKind.CHANGED,
                        message=f"inventory mapping changed: {path}",
                        legacy_path=path,
                        expected=expected[path].legacy_sha256,
                        actual=actual[path].legacy_sha256,
                    )
                )
        return issues


# Shorter public spelling.
MigrationManifest = SecurityArtifactMigration


def _record_from_inventory(value: Mapping[str, Any]) -> ArtifactMigrationRecord:
    value = _mapping(value, "inventory artifact")
    classification = value.get("classification", "")
    if classification not in _INVENTORY_CLASSIFICATIONS:
        raise ArtifactMigrationValidationError(
            f"unsupported inventory classification {classification!r}"
        )
    legacy_path = value.get("path", "")
    legacy_sha256 = value.get("sha256", "")
    legacy_size = value.get("size_bytes", -1)
    target_class = _CLASSIFICATION_MAP[classification]
    target_path = _target_path(legacy_path, target_class)
    flags: set[str] = set()
    if classification == "unknown":
        flags.add("unknown")
    if classification == "transient compiler output":
        flags.add("transient")
    if classification == "ambiguous":
        flags.add("ambiguous")
    if value.get("is_temporary"):
        flags.add("temporary")
    if value.get("is_new_variant"):
        flags.add("new_variant")
    if value.get("is_mutable_alias"):
        flags.add("mutable_alias")
    if (
        target_class is ArtifactClass.ARCHIVE
        or value.get("ambiguity_reasons")
        or value.get("is_new_variant")
        or value.get("is_mutable_alias")
    ):
        flags.add("requires_review")
    artifact_id = _artifact_id(
        legacy_path=legacy_path,
        legacy_sha256=legacy_sha256,
        legacy_size_bytes=legacy_size,
        target_class=target_class,
        target_path=target_path,
    )
    return ArtifactMigrationRecord(
        artifact_id=artifact_id,
        legacy_path=legacy_path,
        legacy_sha256=legacy_sha256,
        legacy_size_bytes=legacy_size,
        legacy_ids=tuple(
            LegacyIdentifier.from_dict(_mapping(item, "legacy identifier"))
            for item in _sequence(value.get("legacy_ids", ()), "legacy_ids")
        ),
        legacy_classification=classification,
        target_class=target_class,
        target_path=target_path,
        flags=tuple(flags),
        detected_format=value.get("detected_format", ""),
        file_type=value.get("file_type", ""),
        is_mutable_alias=value.get("is_mutable_alias", False),
        is_new_variant=value.get("is_new_variant", False),
        is_temporary=value.get("is_temporary", False),
        likely_producers=tuple(
            _sequence(value.get("likely_producers", ()), "likely_producers")
        ),
        ambiguity_reasons=tuple(
            _sequence(value.get("ambiguity_reasons", ()), "ambiguity_reasons")
        ),
        recommendations=tuple(
            _sequence(value.get("recommendations", ()), "recommendations")
        ),
        variant_kinds=tuple(
            _sequence(value.get("variant_kinds", ()), "variant_kinds")
        ),
        variant_of=value.get("variant_of"),
        authority_selected=value.get("authority_selected", False),
    )


def build_migration_manifest(
    inventory: Mapping[str, Any],
    *,
    source_inventory_path: str = DEFAULT_INVENTORY_PATH,
    repository_commit: str = "unrecorded",
    observations: Mapping[str, Any] | None = None,
) -> SecurityArtifactMigration:
    """Build a deterministic migration map from a read-only inventory."""

    inventory = _mapping(inventory, "inventory")
    if inventory.get("schema_version") != SECURITY_ARTIFACT_INVENTORY_SCHEMA_VERSION:
        raise ArtifactMigrationValidationError(
            f"unsupported inventory schema {inventory.get('schema_version')!r}"
        )
    artifacts_value = _sequence(inventory.get("artifacts", ()), "inventory.artifacts")
    inventory_preimage = json.dumps(
        artifacts_value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    actual_inventory_sha256 = hashlib.sha256(inventory_preimage).hexdigest()
    declared_inventory_sha256 = inventory.get("inventory_sha256", "")
    if actual_inventory_sha256 != declared_inventory_sha256:
        raise ArtifactMigrationValidationError(
            "inventory_sha256 does not match the canonical artifact records"
        )
    artifacts = tuple(
        sorted(
            (
                _record_from_inventory(_mapping(item, "inventory artifact"))
                for item in artifacts_value
            ),
            key=lambda item: item.legacy_path,
        )
    )
    declared_count = inventory.get("artifact_count", -1)
    if declared_count != len(artifacts):
        raise ArtifactMigrationValidationError(
            "inventory artifact_count does not match artifacts"
        )
    source_inventory = InventoryBinding(
        path=source_inventory_path,
        schema_version=inventory.get("schema_version", ""),
        inventory_sha256=inventory.get("inventory_sha256", ""),
        artifact_count=declared_count,
        scope=inventory.get("scope", ""),
    )
    return SecurityArtifactMigration(
        artifacts=artifacts,
        source_inventory=source_inventory,
        repository_commit=repository_commit,
        observations=observations or {},
    )


# Descriptive aliases for callers discovering the migration API.
migration_manifest_from_inventory = build_migration_manifest
create_migration_manifest = build_migration_manifest


def load_migration_manifest(
    path: str | Path = DEFAULT_MANIFEST_PATH,
) -> SecurityArtifactMigration:
    """Load and strictly validate a serialized migration manifest."""

    return SecurityArtifactMigration.from_json(Path(path).read_bytes())


def render_migration_manifest(manifest: SecurityArtifactMigration) -> str:
    """Render the stable checked-in JSON representation."""

    return manifest.to_json(pretty=True)


def write_migration_manifest(
    manifest: SecurityArtifactMigration,
    path: str | Path = DEFAULT_MANIFEST_PATH,
) -> None:
    """Atomically write a manifest, never touching any mapped legacy path."""

    output = Path(path)
    normalized_output = PurePosixPath(output.as_posix())
    mapped_paths = {
        PurePosixPath(item.legacy_path) for item in manifest.artifacts
    } | {PurePosixPath(item.target_path) for item in manifest.artifacts}

    def aliases_mapped_path(candidate: PurePosixPath) -> bool:
        for mapped in mapped_paths:
            if candidate == mapped:
                return True
            if (
                candidate.is_absolute()
                and len(candidate.parts) >= len(mapped.parts)
                and candidate.parts[-len(mapped.parts) :] == mapped.parts
            ):
                return True
        return False

    if aliases_mapped_path(normalized_output):
        raise ArtifactMigrationValidationError(
            "refusing to overwrite a legacy or proposed artifact path"
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    rendered = render_migration_manifest(manifest)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{output.name}.", suffix=".tmp", dir=output.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(rendered)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(output)
    finally:
        if temporary.exists():
            temporary.unlink()


def verify_migration_manifest(
    manifest: SecurityArtifactMigration,
    repository_root: str | Path,
    *,
    inventory: Mapping[str, Any] | None = None,
) -> MigrationIntegrityReport:
    """Functional wrapper returning an integrity receipt or raising."""

    return manifest.verify_integrity(repository_root, inventory=inventory)


__all__ = [
    "ArtifactClass",
    "ArtifactMigrationIntegrityError",
    "ArtifactMigrationRecord",
    "ArtifactMigrationValidationError",
    "DEFAULT_INVENTORY_PATH",
    "DEFAULT_MANIFEST_PATH",
    "InventoryBinding",
    "LegacyIdentifier",
    "MIGRATION_POLICY_VERSION",
    "MIGRATION_SCHEMA_VERSION",
    "MigrationClass",
    "MigrationIntegrityIssue",
    "MigrationIntegrityReport",
    "MigrationIssueKind",
    "MigrationManifest",
    "MigrationRecord",
    "SCHEMA_VERSION",
    "SECURITY_ARTIFACT_MIGRATION_SCHEMA_VERSION",
    "SecurityArtifactMigration",
    "build_migration_manifest",
    "create_migration_manifest",
    "load_migration_manifest",
    "migration_manifest_from_inventory",
    "render_migration_manifest",
    "verify_migration_manifest",
    "write_migration_manifest",
]
