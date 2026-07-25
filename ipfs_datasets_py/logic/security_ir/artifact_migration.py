"""Deterministic, reversible migration maps for legacy Security IR artifacts.

This module deliberately performs no artifact moves.  It converts the
read-only ``SecurityArtifactInventory@1`` records into a content-bound plan
for the v1 layout and verifies that the legacy bytes still agree with that
plan.  Applying the plan is therefore a separate, reviewed operation.

The migration manifest has an explicit identity boundary:

* ``deterministic`` contains the complete reversible mapping and is covered by
  ``manifest_id``;
* ``observations`` may contain timestamps, host details, or audit-run
  measurements and never changes ``manifest_id``.

Ambiguous filename variants are archived pending review.  No filename,
timestamp, or producer guess is treated as an authority decision.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
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


SECURITY_ARTIFACT_MIGRATION_INTERFACE: Final = "SecurityArtifactMigration@1"
SECURITY_ARTIFACT_MIGRATION_SCHEMA_VERSION: Final = (
    "security-artifact-migration/v1"
)
SECURITY_ARTIFACT_INVENTORY_SCHEMA_VERSION: Final = (
    "SecurityArtifactInventory@1"
)
SECURITY_ARTIFACT_MIGRATION_IDENTITY_DOMAIN: Final = (
    "security.artifact-migration"
)
DEFAULT_INVENTORY_PATH: Final = (
    "docs/security_verification/security_ir_artifact_inventory.json"
)
DEFAULT_MANIFEST_PATH: Final = "security_ir_artifacts/migrations/manifest.json"
DEFAULT_ARTIFACT_ROOT: Final = "security_ir_artifacts"
LEGACY_RUN_ID: Final = "legacy-import"

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
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
    """Raised when a migration manifest is incomplete or internally unsafe."""


class ArtifactMigrationIntegrityError(ArtifactMigrationValidationError):
    """Raised when legacy bytes no longer match a migration manifest."""

    def __init__(self, report: "MigrationIntegrityReport") -> None:
        self.report = report
        detail = "; ".join(issue.message for issue in report.issues)
        super().__init__(detail or "Security artifact migration integrity failed")


class ArtifactClass(str, Enum):
    """Destination class in the normalized Security artifact layout."""

    SOURCE = "source"
    GOLDEN = "golden"
    RUN = "run"
    PROMOTED = "promoted"
    ARCHIVE = "archive"


class MigrationFlag(str, Enum):
    """Non-authoritative conditions retained from the source inventory."""

    AMBIGUOUS = "ambiguous"
    MUTABLE_ALIAS = "mutable_alias"
    NEW_VARIANT = "new_variant"
    OBSERVATIONAL = "observational"
    TRANSIENT = "transient"
    UNKNOWN = "unknown"


class MigrationIssueKind(str, Enum):
    """Stable integrity failure categories for migration auditing."""

    CHANGED = "changed"
    DUPLICATE = "duplicate"
    INVALID = "invalid"
    MISSING = "missing"
    UNMAPPED = "unmapped"


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


def _require_exact_fields(
    value: Mapping[str, Any],
    allowed: frozenset[str],
    label: str,
    *,
    required: frozenset[str] | None = None,
) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ArtifactMigrationValidationError(
            f"unknown {label} field(s): {', '.join(unknown)}"
        )
    missing = sorted((required or allowed) - set(value))
    if missing:
        raise ArtifactMigrationValidationError(
            f"missing {label} field(s): {', '.join(missing)}"
        )


def _text(value: Any, label: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise ArtifactMigrationValidationError(f"{label} must be a string")
    if value != value.strip():
        raise ArtifactMigrationValidationError(
            f"{label} must not have surrounding whitespace"
        )
    if not value and not allow_empty:
        raise ArtifactMigrationValidationError(f"{label} must not be empty")
    return value


def _sha256(value: Any, label: str) -> str:
    result = _text(value, label)
    if not _SHA256_RE.fullmatch(result):
        raise ArtifactMigrationValidationError(
            f"{label} must be 64 lowercase hexadecimal characters"
        )
    return result


def _non_negative_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ArtifactMigrationValidationError(
            f"{label} must be a non-negative integer"
        )
    return value


def _relative_path(value: Any, label: str) -> str:
    result = _text(value, label)
    if "\\" in result or "\x00" in result:
        raise ArtifactMigrationValidationError(
            f"{label} must be a root-relative POSIX path"
        )
    path = PurePosixPath(result)
    if (
        path.is_absolute()
        or any(part in {"", ".", ".."} for part in path.parts)
        or path.as_posix() != result
    ):
        raise ArtifactMigrationValidationError(
            f"{label} must be a normalized root-relative POSIX path"
        )
    return result


def _string_tuple(value: Any, label: str) -> tuple[str, ...]:
    result = tuple(
        _text(item, label) for item in _sequence(value, label)
    )
    if len(result) != len(set(result)):
        raise ArtifactMigrationValidationError(
            f"{label} must not contain duplicate values"
        )
    return result


def _reject_observations(value: Any, label: str) -> None:
    offending: list[str] = []

    def visit(item: Any, path: str) -> None:
        if isinstance(item, Mapping):
            for key, child in item.items():
                normalized_key = str(key).casefold().replace("-", "_")
                child_path = f"{path}.{key}" if path else str(key)
                if normalized_key in _OBSERVATIONAL_KEYS:
                    offending.append(child_path)
                visit(child, child_path)
        elif isinstance(item, (list, tuple)):
            for index, child in enumerate(item):
                visit(child, f"{path}[{index}]")

    visit(value, "")
    if offending:
        raise ArtifactMigrationValidationError(
            f"{label} contains observational fields {sorted(offending)}; "
            "place them under observations"
        )


def _freeze_mapping(value: Mapping[str, Any], label: str) -> Mapping[str, Any]:
    try:
        return freeze_json_mapping(value)
    except ProvenanceValidationError as exc:
        raise ArtifactMigrationValidationError(f"{label}: {exc}") from exc


@dataclass(frozen=True, slots=True, order=True)
class LegacyIdentifier:
    """One verbatim identity value extracted from a legacy artifact."""

    field: str
    value: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "field", _text(self.field, "legacy ID field"))
        object.__setattr__(self, "value", _text(self.value, "legacy ID value"))

    def to_dict(self) -> dict[str, str]:
        return {"field": self.field, "value": self.value}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "LegacyIdentifier":
        _require_exact_fields(
            value,
            frozenset({"field", "value"}),
            "legacy identifier",
        )
        return cls(field=value["field"], value=value["value"])


@dataclass(frozen=True, slots=True)
class ArtifactMigration:
    """A content-bound, one-to-one mapping for one legacy artifact."""

    legacy_path: str
    target_path: str
    artifact_class: ArtifactClass
    legacy_sha256: str
    legacy_size_bytes: int
    legacy_ids: tuple[LegacyIdentifier, ...] = ()
    legacy_classification: str = "unknown"
    detected_format: str = "unknown"
    legacy_file_type: str = "regular-file"
    flags: tuple[MigrationFlag, ...] = ()
    variant_of: str = ""
    variant_kinds: tuple[str, ...] = ()
    ambiguity_reasons: tuple[str, ...] = ()
    likely_producers: tuple[str, ...] = ()
    recommendations: tuple[str, ...] = ()
    authority_selected: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "legacy_path", _relative_path(self.legacy_path, "legacy_path")
        )
        object.__setattr__(
            self, "target_path", _relative_path(self.target_path, "target_path")
        )
        try:
            artifact_class = ArtifactClass(self.artifact_class)
        except (TypeError, ValueError) as exc:
            raise ArtifactMigrationValidationError(
                f"unsupported artifact class: {self.artifact_class!r}"
            ) from exc
        object.__setattr__(self, "artifact_class", artifact_class)
        object.__setattr__(
            self,
            "legacy_sha256",
            _sha256(self.legacy_sha256, "legacy_sha256"),
        )
        object.__setattr__(
            self,
            "legacy_size_bytes",
            _non_negative_int(self.legacy_size_bytes, "legacy_size_bytes"),
        )
        identifiers = tuple(
            item
            if isinstance(item, LegacyIdentifier)
            else LegacyIdentifier.from_dict(_mapping(item, "legacy identifier"))
            for item in self.legacy_ids
        )
        if len(identifiers) != len(set(identifiers)):
            raise ArtifactMigrationValidationError(
                "legacy_ids must not contain duplicate field/value pairs"
            )
        object.__setattr__(
            self, "legacy_ids", tuple(sorted(identifiers))
        )
        classification = _text(
            self.legacy_classification, "legacy_classification"
        )
        if classification not in _INVENTORY_CLASSIFICATIONS:
            raise ArtifactMigrationValidationError(
                f"unsupported legacy classification: {classification!r}"
            )
        object.__setattr__(self, "legacy_classification", classification)
        object.__setattr__(
            self, "detected_format", _text(self.detected_format, "detected_format")
        )
        file_type = _text(self.legacy_file_type, "legacy_file_type")
        if file_type not in {"regular-file", "symbolic-link"}:
            raise ArtifactMigrationValidationError(
                f"unsupported legacy_file_type: {file_type!r}"
            )
        object.__setattr__(self, "legacy_file_type", file_type)
        try:
            raw_flags = tuple(MigrationFlag(item) for item in self.flags)
        except (TypeError, ValueError) as exc:
            raise ArtifactMigrationValidationError(
                "flags contains an unsupported migration flag"
            ) from exc
        if len(raw_flags) != len(set(raw_flags)):
            raise ArtifactMigrationValidationError(
                "flags must not contain duplicate values"
            )
        flags = tuple(sorted(raw_flags, key=lambda item: item.value))
        object.__setattr__(self, "flags", flags)
        if self.variant_of:
            object.__setattr__(
                self, "variant_of", _relative_path(self.variant_of, "variant_of")
            )
        object.__setattr__(
            self,
            "variant_kinds",
            tuple(sorted(_string_tuple(self.variant_kinds, "variant_kinds"))),
        )
        object.__setattr__(
            self,
            "ambiguity_reasons",
            tuple(
                sorted(
                    _string_tuple(self.ambiguity_reasons, "ambiguity_reasons")
                )
            ),
        )
        object.__setattr__(
            self,
            "likely_producers",
            tuple(sorted(_string_tuple(self.likely_producers, "likely_producers"))),
        )
        object.__setattr__(
            self,
            "recommendations",
            tuple(sorted(_string_tuple(self.recommendations, "recommendations"))),
        )
        if not isinstance(self.authority_selected, bool):
            raise ArtifactMigrationValidationError(
                "authority_selected must be a boolean"
            )
        if self.authority_selected:
            raise ArtifactMigrationValidationError(
                "migration cannot select legacy artifact authority"
            )
        expected_class, expected_flags = classify_inventory_record(
            {
                "classification": self.legacy_classification,
                "is_mutable_alias": MigrationFlag.MUTABLE_ALIAS in flags,
                "is_new_variant": MigrationFlag.NEW_VARIANT in flags,
                "is_temporary": MigrationFlag.TRANSIENT in flags,
            }
        )
        if artifact_class is not expected_class:
            raise ArtifactMigrationValidationError(
                f"{self.legacy_classification!r} must migrate to "
                f"{expected_class.value!r}, not {artifact_class.value!r}"
            )
        if not expected_flags.issubset(set(flags)):
            raise ArtifactMigrationValidationError(
                "migration flags do not preserve the inventory classification"
            )
        if target_path_for(self.legacy_path, artifact_class) != self.target_path:
            raise ArtifactMigrationValidationError(
                "target_path does not match the deterministic migration policy"
            )

    @property
    def legacy_digest(self) -> str:
        return f"sha256:{self.legacy_sha256}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "ambiguity_reasons": list(self.ambiguity_reasons),
            "artifact_class": self.artifact_class.value,
            "authority_selected": self.authority_selected,
            "detected_format": self.detected_format,
            "flags": [flag.value for flag in self.flags],
            "legacy_classification": self.legacy_classification,
            "legacy_file_type": self.legacy_file_type,
            "legacy_ids": [item.to_dict() for item in self.legacy_ids],
            "legacy_path": self.legacy_path,
            "legacy_sha256": self.legacy_sha256,
            "legacy_size_bytes": self.legacy_size_bytes,
            "likely_producers": list(self.likely_producers),
            "recommendations": list(self.recommendations),
            "target_path": self.target_path,
            "variant_kinds": list(self.variant_kinds),
            "variant_of": self.variant_of,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ArtifactMigration":
        allowed = frozenset(
            {
                "artifact_class",
                "ambiguity_reasons",
                "authority_selected",
                "detected_format",
                "flags",
                "legacy_classification",
                "legacy_file_type",
                "legacy_ids",
                "legacy_path",
                "legacy_sha256",
                "legacy_size_bytes",
                "likely_producers",
                "recommendations",
                "target_path",
                "variant_kinds",
                "variant_of",
            }
        )
        _require_exact_fields(value, allowed, "artifact migration")
        return cls(
            legacy_path=value["legacy_path"],
            target_path=value["target_path"],
            artifact_class=value["artifact_class"],
            legacy_sha256=value["legacy_sha256"],
            legacy_size_bytes=value["legacy_size_bytes"],
            legacy_ids=tuple(
                LegacyIdentifier.from_dict(_mapping(item, "legacy identifier"))
                for item in _sequence(value["legacy_ids"], "legacy_ids")
            ),
            legacy_classification=value["legacy_classification"],
            detected_format=value["detected_format"],
            legacy_file_type=value["legacy_file_type"],
            flags=tuple(_sequence(value["flags"], "flags")),
            variant_of=value["variant_of"],
            variant_kinds=tuple(
                _sequence(value["variant_kinds"], "variant_kinds")
            ),
            ambiguity_reasons=tuple(
                _sequence(value["ambiguity_reasons"], "ambiguity_reasons")
            ),
            likely_producers=tuple(
                _sequence(value["likely_producers"], "likely_producers")
            ),
            recommendations=tuple(
                _sequence(value["recommendations"], "recommendations")
            ),
            authority_selected=value["authority_selected"],
        )


@dataclass(frozen=True, slots=True)
class InventoryBinding:
    """Integrity binding to the exact read-only inventory used for migration."""

    path: str
    inventory_sha256: str
    content_sha256: str
    artifact_count: int
    total_size_bytes: int
    schema_version: str = SECURITY_ARTIFACT_INVENTORY_SCHEMA_VERSION
    repository_revision: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "path", _relative_path(self.path, "inventory path"))
        object.__setattr__(
            self,
            "inventory_sha256",
            _sha256(self.inventory_sha256, "inventory_sha256"),
        )
        object.__setattr__(
            self,
            "content_sha256",
            _sha256(self.content_sha256, "inventory content_sha256"),
        )
        object.__setattr__(
            self,
            "artifact_count",
            _non_negative_int(self.artifact_count, "inventory artifact_count"),
        )
        object.__setattr__(
            self,
            "total_size_bytes",
            _non_negative_int(
                self.total_size_bytes, "inventory total_size_bytes"
            ),
        )
        if self.schema_version != SECURITY_ARTIFACT_INVENTORY_SCHEMA_VERSION:
            raise ArtifactMigrationValidationError(
                f"unsupported inventory schema version: {self.schema_version!r}"
            )
        if self.repository_revision:
            object.__setattr__(
                self,
                "repository_revision",
                _text(self.repository_revision, "repository_revision"),
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_count": self.artifact_count,
            "content_sha256": self.content_sha256,
            "inventory_sha256": self.inventory_sha256,
            "path": self.path,
            "repository_revision": self.repository_revision,
            "schema_version": self.schema_version,
            "total_size_bytes": self.total_size_bytes,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "InventoryBinding":
        allowed = frozenset(
            {
                "artifact_count",
                "content_sha256",
                "inventory_sha256",
                "path",
                "repository_revision",
                "schema_version",
                "total_size_bytes",
            }
        )
        _require_exact_fields(value, allowed, "inventory binding")
        return cls(**{name: value[name] for name in allowed})


@dataclass(frozen=True, slots=True)
class MigrationObservations:
    """Audit observations excluded from the deterministic manifest identity."""

    generated_at: str = ""
    environment: Mapping[str, Any] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "generated_at",
            _text(self.generated_at, "generated_at", allow_empty=True),
        )
        object.__setattr__(
            self,
            "environment",
            _freeze_mapping(self.environment, "observations.environment"),
        )
        object.__setattr__(
            self,
            "metadata",
            _freeze_mapping(self.metadata, "observations.metadata"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "environment": thaw_json(self.environment),
            "generated_at": self.generated_at,
            "metadata": thaw_json(self.metadata),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "MigrationObservations":
        allowed = frozenset({"environment", "generated_at", "metadata"})
        _require_exact_fields(value, allowed, "migration observations")
        return cls(
            generated_at=value["generated_at"],
            environment=_mapping(value["environment"], "observations.environment"),
            metadata=_mapping(value["metadata"], "observations.metadata"),
        )


@dataclass(frozen=True, slots=True)
class MigrationIssue:
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
    """Deterministically ordered integrity receipt for a migration plan."""

    issues: tuple[MigrationIssue, ...] = ()
    checked_legacy_paths: tuple[str, ...] = ()
    manifest_id: str = ""

    @property
    def valid(self) -> bool:
        return not self.issues

    def to_dict(self) -> dict[str, Any]:
        return {
            "checked_legacy_paths": list(self.checked_legacy_paths),
            "issues": [issue.to_dict() for issue in self.issues],
            "manifest_id": self.manifest_id,
            "valid": self.valid,
        }


@dataclass(frozen=True, slots=True)
class SecurityArtifactMigration:
    """Immutable, idempotent, and reversible Security artifact migration."""

    inventory: InventoryBinding
    artifacts: tuple[ArtifactMigration, ...]
    observations: MigrationObservations = field(
        default_factory=MigrationObservations
    )
    deterministic_metadata: Mapping[str, Any] = field(default_factory=dict)
    manifest_id: str = ""
    schema_version: str = SECURITY_ARTIFACT_MIGRATION_SCHEMA_VERSION
    interface: str = SECURITY_ARTIFACT_MIGRATION_INTERFACE

    def __post_init__(self) -> None:
        inventory = (
            self.inventory
            if isinstance(self.inventory, InventoryBinding)
            else InventoryBinding.from_dict(_mapping(self.inventory, "inventory"))
        )
        artifacts = tuple(
            item
            if isinstance(item, ArtifactMigration)
            else ArtifactMigration.from_dict(_mapping(item, "artifact migration"))
            for item in self.artifacts
        )
        artifacts = tuple(sorted(artifacts, key=lambda item: item.legacy_path))
        observations = (
            self.observations
            if isinstance(self.observations, MigrationObservations)
            else MigrationObservations.from_dict(
                _mapping(self.observations, "observations")
            )
        )
        metadata = _freeze_mapping(
            self.deterministic_metadata, "deterministic_metadata"
        )
        _reject_observations(metadata, "deterministic_metadata")
        object.__setattr__(self, "inventory", inventory)
        object.__setattr__(self, "artifacts", artifacts)
        object.__setattr__(self, "observations", observations)
        object.__setattr__(self, "deterministic_metadata", metadata)
        self._validate()
        computed = self._computed_manifest_id()
        if self.manifest_id and self.manifest_id != computed:
            raise ArtifactMigrationValidationError(
                "manifest_id does not match deterministic migration content"
            )
        object.__setattr__(self, "manifest_id", computed)

    @property
    def artifact_count(self) -> int:
        return len(self.artifacts)

    @property
    def total_size_bytes(self) -> int:
        return sum(item.legacy_size_bytes for item in self.artifacts)

    @property
    def class_counts(self) -> Mapping[str, int]:
        counts = Counter(item.artifact_class.value for item in self.artifacts)
        return MappingProxyType(
            {item.value: counts[item.value] for item in ArtifactClass}
        )

    @property
    def flag_counts(self) -> Mapping[str, int]:
        counts = Counter(flag.value for item in self.artifacts for flag in item.flags)
        return MappingProxyType(
            {item.value: counts[item.value] for item in MigrationFlag}
        )

    def _validate(self) -> None:
        if self.schema_version != SECURITY_ARTIFACT_MIGRATION_SCHEMA_VERSION:
            raise ArtifactMigrationValidationError(
                f"unsupported migration schema version: {self.schema_version!r}"
            )
        if self.interface != SECURITY_ARTIFACT_MIGRATION_INTERFACE:
            raise ArtifactMigrationValidationError(
                f"unsupported migration interface: {self.interface!r}"
            )
        if self.artifact_count != self.inventory.artifact_count:
            raise ArtifactMigrationValidationError(
                "migration artifact count does not match source inventory"
            )
        if self.total_size_bytes != self.inventory.total_size_bytes:
            raise ArtifactMigrationValidationError(
                "migration byte count does not match source inventory"
            )
        legacy_paths = [item.legacy_path for item in self.artifacts]
        target_paths = [item.target_path for item in self.artifacts]
        if len(legacy_paths) != len(set(legacy_paths)):
            raise ArtifactMigrationValidationError(
                "duplicate legacy paths make migration non-idempotent"
            )
        if len(target_paths) != len(set(target_paths)):
            raise ArtifactMigrationValidationError(
                "duplicate target paths make migration non-reversible"
            )

    def deterministic_dict(self) -> dict[str, Any]:
        return {
            "artifacts": [item.to_dict() for item in self.artifacts],
            "class_counts": dict(self.class_counts),
            "deterministic_metadata": thaw_json(self.deterministic_metadata),
            "flag_counts": dict(self.flag_counts),
            "inventory": self.inventory.to_dict(),
            "legacy_artifact_count": self.artifact_count,
            "legacy_total_size_bytes": self.total_size_bytes,
            "policy": {
                "ambiguous_authority": "archive_pending_review",
                "artifact_moves_performed": False,
                "idempotency_key": (
                    f"sha256:{self.inventory.inventory_sha256}"
                ),
                "legacy_bytes_rewritten": False,
                "legacy_identifiers": "verbatim",
                "run_id": LEGACY_RUN_ID,
                "target_layout": {
                    "archive": "archive/",
                    "golden": "golden/",
                    "promoted": "promoted/",
                    "run": f"runs/{LEGACY_RUN_ID}/",
                    "source": "inputs/",
                },
            },
        }

    def _identity_preimage(self) -> dict[str, Any]:
        return {
            "deterministic": self.deterministic_dict(),
            "interface": self.interface,
            "schema_version": self.schema_version,
        }

    def _computed_manifest_id(self) -> str:
        return canonical_identity(
            self._identity_preimage(),
            domain=SECURITY_ARTIFACT_MIGRATION_IDENTITY_DOMAIN,
            schema_version=self.schema_version,
        ).cid

    def deterministic_bytes(self) -> bytes:
        return canonical_json_bytes(self._identity_preimage())

    def to_dict(self) -> dict[str, Any]:
        return {
            "deterministic": self.deterministic_dict(),
            "interface": self.interface,
            "manifest_id": self.manifest_id,
            "observations": self.observations.to_dict(),
            "schema_version": self.schema_version,
        }

    def to_json(self, *, pretty: bool = False) -> str:
        if pretty:
            return json.dumps(
                self.to_dict(), ensure_ascii=True, indent=2, sort_keys=True
            ) + "\n"
        return canonical_json_bytes(self.to_dict()).decode("utf-8")

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SecurityArtifactMigration":
        allowed = frozenset(
            {
                "deterministic",
                "interface",
                "manifest_id",
                "observations",
                "schema_version",
            }
        )
        _require_exact_fields(value, allowed, "migration manifest")
        deterministic = _mapping(value["deterministic"], "deterministic")
        deterministic_allowed = frozenset(
            {
                "artifacts",
                "class_counts",
                "deterministic_metadata",
                "flag_counts",
                "inventory",
                "legacy_artifact_count",
                "legacy_total_size_bytes",
                "policy",
            }
        )
        _require_exact_fields(
            deterministic, deterministic_allowed, "deterministic migration"
        )
        result = cls(
            inventory=InventoryBinding.from_dict(
                _mapping(deterministic["inventory"], "inventory")
            ),
            artifacts=tuple(
                ArtifactMigration.from_dict(_mapping(item, "artifact migration"))
                for item in _sequence(deterministic["artifacts"], "artifacts")
            ),
            observations=MigrationObservations.from_dict(
                _mapping(value["observations"], "observations")
            ),
            deterministic_metadata=_mapping(
                deterministic["deterministic_metadata"],
                "deterministic_metadata",
            ),
            manifest_id=value["manifest_id"],
            schema_version=value["schema_version"],
            interface=value["interface"],
        )
        if deterministic["legacy_artifact_count"] != result.artifact_count:
            raise ArtifactMigrationValidationError(
                "legacy_artifact_count does not match artifact records"
            )
        if deterministic["legacy_total_size_bytes"] != result.total_size_bytes:
            raise ArtifactMigrationValidationError(
                "legacy_total_size_bytes does not match artifact records"
            )
        if deterministic["class_counts"] != dict(result.class_counts):
            raise ArtifactMigrationValidationError(
                "class_counts does not match artifact records"
            )
        if deterministic["flag_counts"] != dict(result.flag_counts):
            raise ArtifactMigrationValidationError(
                "flag_counts does not match artifact records"
            )
        if deterministic["policy"] != result.deterministic_dict()["policy"]:
            raise ArtifactMigrationValidationError(
                "migration policy is not the supported deterministic policy"
            )
        return result

    @classmethod
    def from_json(cls, value: str | bytes | bytearray) -> "SecurityArtifactMigration":
        try:
            payload = json.loads(value)
        except (TypeError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ArtifactMigrationValidationError(
                "migration manifest must be valid UTF-8 JSON"
            ) from exc
        return cls.from_dict(_mapping(payload, "migration manifest"))

    def forward_mapping(self) -> Mapping[str, str]:
        """Return the immutable legacy-to-target path map."""

        return MappingProxyType(
            {item.legacy_path: item.target_path for item in self.artifacts}
        )

    def reverse_mapping(self) -> Mapping[str, str]:
        """Return the exact inverse map used for rollback/review."""

        return MappingProxyType(
            {item.target_path: item.legacy_path for item in self.artifacts}
        )

    def target_for(self, legacy_path: str) -> str:
        return self.forward_mapping()[_relative_path(legacy_path, "legacy_path")]

    def legacy_for(self, target_path: str) -> str:
        return self.reverse_mapping()[_relative_path(target_path, "target_path")]

    def with_observations(
        self, observations: MigrationObservations
    ) -> "SecurityArtifactMigration":
        """Attach audit observations without changing deterministic identity."""

        return replace(self, observations=observations)

    def audit_integrity(
        self,
        repo_root: str | Path,
        *,
        reject_unmapped: bool = False,
        verify_inventory: bool = False,
    ) -> MigrationIntegrityReport:
        """Verify legacy bytes and, optionally, the bound inventory itself."""

        root = Path(repo_root)
        issues: list[MigrationIssue] = []
        checked: list[str] = []
        try:
            resolved_root = root.resolve(strict=True)
        except FileNotFoundError:
            issues.append(
                MigrationIssue(
                    MigrationIssueKind.MISSING,
                    f"repository root does not exist: {root}",
                )
            )
            return _integrity_report(issues, checked, self.manifest_id)
        if not resolved_root.is_dir():
            issues.append(
                MigrationIssue(
                    MigrationIssueKind.INVALID,
                    f"repository root is not a directory: {root}",
                )
            )
            return _integrity_report(issues, checked, self.manifest_id)

        if verify_inventory:
            inventory_path = resolved_root.joinpath(
                *PurePosixPath(self.inventory.path).parts
            )
            try:
                resolved_inventory = inventory_path.resolve(strict=True)
            except FileNotFoundError:
                issues.append(
                    MigrationIssue(
                        MigrationIssueKind.MISSING,
                        f"source inventory is missing: {self.inventory.path}",
                        legacy_path=self.inventory.path,
                    )
                )
            else:
                if (
                    not resolved_inventory.is_relative_to(resolved_root)
                    or not resolved_inventory.is_file()
                    or inventory_path.is_symlink()
                ):
                    issues.append(
                        MigrationIssue(
                            MigrationIssueKind.INVALID,
                            f"source inventory path is unsafe: "
                            f"{self.inventory.path}",
                            legacy_path=self.inventory.path,
                        )
                    )
                else:
                    actual_inventory_sha256 = hashlib.sha256(
                        resolved_inventory.read_bytes()
                    ).hexdigest()
                    if (
                        actual_inventory_sha256
                        != self.inventory.content_sha256
                    ):
                        issues.append(
                            MigrationIssue(
                                MigrationIssueKind.CHANGED,
                                f"source inventory digest changed: "
                                f"{self.inventory.path}",
                                legacy_path=self.inventory.path,
                                expected=self.inventory.content_sha256,
                                actual=actual_inventory_sha256,
                            )
                        )

        for artifact in self.artifacts:
            checked.append(artifact.legacy_path)
            candidate = resolved_root.joinpath(
                *PurePosixPath(artifact.legacy_path).parts
            )
            try:
                candidate.lstat()
            except FileNotFoundError:
                issues.append(
                    MigrationIssue(
                        MigrationIssueKind.MISSING,
                        f"legacy artifact is missing: {artifact.legacy_path}",
                        legacy_path=artifact.legacy_path,
                    )
                )
                continue
            if artifact.legacy_file_type == "symbolic-link":
                if not candidate.is_symlink():
                    issues.append(
                        MigrationIssue(
                            MigrationIssueKind.CHANGED,
                            f"legacy symbolic link changed type: "
                            f"{artifact.legacy_path}",
                            legacy_path=artifact.legacy_path,
                            expected="symbolic-link",
                            actual="regular-file",
                        )
                    )
                    continue
                data = os.readlink(candidate).encode(
                    "utf-8", errors="surrogateescape"
                )
                size = len(data)
                actual_sha256 = hashlib.sha256(data).hexdigest()
            else:
                try:
                    resolved = candidate.resolve(strict=True)
                except FileNotFoundError:
                    issues.append(
                        MigrationIssue(
                            MigrationIssueKind.MISSING,
                            f"legacy artifact target is missing: "
                            f"{artifact.legacy_path}",
                            legacy_path=artifact.legacy_path,
                        )
                    )
                    continue
                if (
                    candidate.is_symlink()
                    or not resolved.is_relative_to(resolved_root)
                    or not resolved.is_file()
                ):
                    issues.append(
                        MigrationIssue(
                            MigrationIssueKind.INVALID,
                            f"legacy artifact path is unsafe: "
                            f"{artifact.legacy_path}",
                            legacy_path=artifact.legacy_path,
                        )
                    )
                    continue
                digest = hashlib.sha256()
                size = 0
                with resolved.open("rb") as handle:
                    for chunk in iter(
                        lambda: handle.read(1024 * 1024), b""
                    ):
                        digest.update(chunk)
                        size += len(chunk)
                actual_sha256 = digest.hexdigest()
            if size != artifact.legacy_size_bytes:
                issues.append(
                    MigrationIssue(
                        MigrationIssueKind.CHANGED,
                        f"legacy artifact size changed: {artifact.legacy_path}",
                        legacy_path=artifact.legacy_path,
                        expected=str(artifact.legacy_size_bytes),
                        actual=str(size),
                    )
                )
            if actual_sha256 != artifact.legacy_sha256:
                issues.append(
                    MigrationIssue(
                        MigrationIssueKind.CHANGED,
                        f"legacy artifact digest changed: {artifact.legacy_path}",
                        legacy_path=artifact.legacy_path,
                        expected=artifact.legacy_sha256,
                        actual=actual_sha256,
                    )
                )

        if reject_unmapped:
            artifact_root = resolved_root / DEFAULT_ARTIFACT_ROOT
            mapped = set(self.forward_mapping())
            if artifact_root.is_dir():
                for path in sorted(
                    item for item in artifact_root.rglob("*") if item.is_file()
                ):
                    relative = path.relative_to(resolved_root).as_posix()
                    if (
                        relative not in mapped
                        and relative != DEFAULT_MANIFEST_PATH
                        and not relative.startswith(
                            f"{DEFAULT_ARTIFACT_ROOT}/migrations/"
                        )
                    ):
                        issues.append(
                            MigrationIssue(
                                MigrationIssueKind.UNMAPPED,
                                f"legacy artifact is not mapped: {relative}",
                                legacy_path=relative,
                            )
                        )
        return _integrity_report(issues, checked, self.manifest_id)

    def verify_integrity(
        self,
        repo_root: str | Path,
        *,
        reject_unmapped: bool = False,
        verify_inventory: bool = False,
    ) -> MigrationIntegrityReport:
        report = self.audit_integrity(
            repo_root,
            reject_unmapped=reject_unmapped,
            verify_inventory=verify_inventory,
        )
        if not report.valid:
            raise ArtifactMigrationIntegrityError(report)
        return report


def classify_inventory_record(
    record: Mapping[str, Any],
) -> tuple[ArtifactClass, set[MigrationFlag]]:
    """Classify an inventory record without inferring evidentiary authority."""

    classification = _text(
        record.get("classification"), "inventory classification"
    )
    if classification not in _INVENTORY_CLASSIFICATIONS:
        raise ArtifactMigrationValidationError(
            f"unsupported inventory classification: {classification!r}"
        )
    flags: set[MigrationFlag] = set()
    if bool(record.get("is_new_variant")):
        flags.add(MigrationFlag.NEW_VARIANT)
    if bool(record.get("is_mutable_alias")):
        flags.add(MigrationFlag.MUTABLE_ALIAS)
    if bool(record.get("is_temporary")):
        flags.add(MigrationFlag.TRANSIENT)

    if classification == "source":
        return ArtifactClass.SOURCE, flags
    if classification == "golden":
        return ArtifactClass.GOLDEN, flags
    if classification == "run output":
        return ArtifactClass.RUN, flags
    if classification == "promoted evidence":
        return ArtifactClass.PROMOTED, flags
    if classification == "environment record":
        flags.add(MigrationFlag.OBSERVATIONAL)
    elif classification == "transient compiler output":
        flags.add(MigrationFlag.TRANSIENT)
    elif classification == "ambiguous":
        flags.add(MigrationFlag.AMBIGUOUS)
    elif classification == "unknown":
        flags.add(MigrationFlag.UNKNOWN)
    return ArtifactClass.ARCHIVE, flags


def target_path_for(legacy_path: str, artifact_class: ArtifactClass) -> str:
    """Return the collision-free normalized path for a legacy path."""

    source = PurePosixPath(_relative_path(legacy_path, "legacy_path"))
    root = PurePosixPath(DEFAULT_ARTIFACT_ROOT)
    try:
        relative = source.relative_to(root)
    except ValueError as exc:
        raise ArtifactMigrationValidationError(
            f"legacy_path must be below {DEFAULT_ARTIFACT_ROOT}/"
        ) from exc
    prefix = {
        ArtifactClass.SOURCE: PurePosixPath(DEFAULT_ARTIFACT_ROOT, "inputs"),
        ArtifactClass.GOLDEN: PurePosixPath(DEFAULT_ARTIFACT_ROOT, "golden"),
        ArtifactClass.RUN: PurePosixPath(
            DEFAULT_ARTIFACT_ROOT, "runs", LEGACY_RUN_ID
        ),
        ArtifactClass.PROMOTED: PurePosixPath(
            DEFAULT_ARTIFACT_ROOT, "promoted"
        ),
        ArtifactClass.ARCHIVE: PurePosixPath(DEFAULT_ARTIFACT_ROOT, "archive"),
    }[ArtifactClass(artifact_class)]
    return (prefix / relative).as_posix()


def _inventory_record_to_migration(
    value: Mapping[str, Any],
) -> ArtifactMigration:
    artifact_class, flags = classify_inventory_record(value)
    legacy_path = value.get("path")
    if value.get("ambiguity_reasons"):
        flags.add(MigrationFlag.AMBIGUOUS)
    return ArtifactMigration(
        legacy_path=legacy_path,
        target_path=target_path_for(legacy_path, artifact_class),
        artifact_class=artifact_class,
        legacy_sha256=value.get("sha256"),
        legacy_size_bytes=value.get("size_bytes"),
        legacy_ids=tuple(
            LegacyIdentifier.from_dict(_mapping(item, "legacy identifier"))
            for item in _sequence(value.get("legacy_ids"), "legacy_ids")
        ),
        legacy_classification=value.get("classification"),
        detected_format=value.get("detected_format"),
        legacy_file_type=value.get("file_type"),
        flags=tuple(flags),
        variant_of=value.get("variant_of") or "",
        variant_kinds=tuple(
            _sequence(value.get("variant_kinds"), "variant_kinds")
        ),
        ambiguity_reasons=tuple(
            _sequence(value.get("ambiguity_reasons"), "ambiguity_reasons")
        ),
        likely_producers=tuple(
            _sequence(value.get("likely_producers"), "likely_producers")
        ),
        recommendations=tuple(
            _sequence(value.get("recommendations"), "recommendations")
        ),
        authority_selected=value.get("authority_selected"),
    )


def build_migration_manifest(
    inventory: Mapping[str, Any],
    *,
    inventory_path: str = DEFAULT_INVENTORY_PATH,
    inventory_content_sha256: str | None = None,
    repository_revision: str = "",
    deterministic_metadata: Mapping[str, Any] | None = None,
    observations: MigrationObservations | None = None,
) -> SecurityArtifactMigration:
    """Build the same manifest for the same inventory (idempotently)."""

    inventory = _mapping(inventory, "inventory")
    if inventory.get("schema_version") != SECURITY_ARTIFACT_INVENTORY_SCHEMA_VERSION:
        raise ArtifactMigrationValidationError(
            f"unsupported inventory schema version: "
            f"{inventory.get('schema_version')!r}"
        )
    records = tuple(
        _mapping(item, "inventory artifact")
        for item in _sequence(inventory.get("artifacts"), "inventory artifacts")
    )
    artifact_count = _non_negative_int(
        inventory.get("artifact_count"), "inventory artifact_count"
    )
    total_size_bytes = _non_negative_int(
        inventory.get("total_size_bytes"), "inventory total_size_bytes"
    )
    if artifact_count != len(records):
        raise ArtifactMigrationValidationError(
            "inventory artifact_count does not match artifact records"
        )
    if total_size_bytes != sum(
        _non_negative_int(item.get("size_bytes"), "artifact size_bytes")
        for item in records
    ):
        raise ArtifactMigrationValidationError(
            "inventory total_size_bytes does not match artifact records"
        )
    canonical_records = json.dumps(
        records,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    computed_inventory_sha256 = hashlib.sha256(canonical_records).hexdigest()
    if inventory.get("inventory_sha256") != computed_inventory_sha256:
        raise ArtifactMigrationValidationError(
            "inventory_sha256 does not match canonical artifact records"
        )
    if inventory_content_sha256 is None:
        inventory_content_sha256 = hashlib.sha256(
            json.dumps(
                inventory, ensure_ascii=True, indent=2, sort_keys=True
            ).encode("utf-8")
            + b"\n"
        ).hexdigest()
    binding = InventoryBinding(
        path=inventory_path,
        inventory_sha256=computed_inventory_sha256,
        content_sha256=inventory_content_sha256,
        artifact_count=artifact_count,
        total_size_bytes=total_size_bytes,
        schema_version=inventory["schema_version"],
        repository_revision=repository_revision,
    )
    return SecurityArtifactMigration(
        inventory=binding,
        artifacts=tuple(_inventory_record_to_migration(item) for item in records),
        observations=observations or MigrationObservations(),
        deterministic_metadata=deterministic_metadata or {},
    )


def load_migration_manifest(
    path: str | Path = DEFAULT_MANIFEST_PATH,
) -> SecurityArtifactMigration:
    """Load and validate a migration manifest, including ``manifest_id``."""

    try:
        content = Path(path).read_bytes()
    except OSError as exc:
        raise ArtifactMigrationValidationError(
            f"unable to read migration manifest: {path}"
        ) from exc
    return SecurityArtifactMigration.from_json(content)


def build_migration_manifest_from_inventory_file(
    inventory_path: str | Path,
    *,
    repository_revision: str = "",
    deterministic_metadata: Mapping[str, Any] | None = None,
    observations: MigrationObservations | None = None,
) -> SecurityArtifactMigration:
    """Build a manifest bound to the exact serialized inventory file."""

    path = Path(inventory_path)
    try:
        content = path.read_bytes()
        inventory = json.loads(content)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ArtifactMigrationValidationError(
            f"unable to load Security artifact inventory: {path}"
        ) from exc
    try:
        relative_path = path.resolve().relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        relative_path = path.as_posix()
    return build_migration_manifest(
        inventory,
        inventory_path=relative_path,
        inventory_content_sha256=hashlib.sha256(content).hexdigest(),
        repository_revision=repository_revision,
        deterministic_metadata=deterministic_metadata,
        observations=observations,
    )


def write_migration_manifest(
    manifest: SecurityArtifactMigration,
    path: str | Path = DEFAULT_MANIFEST_PATH,
) -> bool:
    """Write a manifest atomically; identical existing content is a no-op.

    Returns ``True`` when a new file was installed and ``False`` for an
    idempotent repeat.  A different existing manifest is never overwritten.
    """

    destination = Path(path)
    candidate = PurePosixPath(destination.as_posix())
    bound_paths = {
        PurePosixPath(bound_path)
        for artifact in manifest.artifacts
        for bound_path in (artifact.legacy_path, artifact.target_path)
    }
    for bound_path in bound_paths:
        if candidate == bound_path or (
            candidate.is_absolute()
            and len(candidate.parts) >= len(bound_path.parts)
            and candidate.parts[-len(bound_path.parts) :] == bound_path.parts
        ):
            raise ArtifactMigrationValidationError(
                "refusing to write migration metadata to a mapped artifact path"
            )
    if destination.is_symlink():
        raise ArtifactMigrationValidationError(
            "refusing to write a migration manifest through a symbolic link"
        )
    content = manifest.to_json(pretty=True).encode("utf-8")
    if destination.exists():
        try:
            current = destination.read_bytes()
        except OSError as exc:
            raise ArtifactMigrationValidationError(
                f"unable to read existing migration manifest: {destination}"
            ) from exc
        if current == content:
            return False
        raise ArtifactMigrationValidationError(
            "refusing to overwrite a different migration manifest"
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        suffix=".tmp",
        dir=destination.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, destination)
        except FileExistsError:
            if destination.read_bytes() == content:
                return False
            raise ArtifactMigrationValidationError(
                "refusing to overwrite a concurrently installed "
                "migration manifest"
            )
    finally:
        if temporary.exists():
            temporary.unlink()
    return True


def _integrity_report(
    issues: Sequence[MigrationIssue],
    checked: Sequence[str],
    manifest_id: str,
) -> MigrationIntegrityReport:
    return MigrationIntegrityReport(
        issues=tuple(
            sorted(
                issues,
                key=lambda item: (
                    item.kind.value,
                    item.legacy_path,
                    item.message,
                    item.expected,
                    item.actual,
                ),
            )
        ),
        checked_legacy_paths=tuple(sorted(set(checked))),
        manifest_id=manifest_id,
    )


# Compatibility aliases use the interface wording from the implementation
# board while retaining the more precise class name in public documentation.
MigrationManifest = SecurityArtifactMigration
MigrationRecord = ArtifactMigration


__all__ = [
    "ArtifactClass",
    "ArtifactMigration",
    "ArtifactMigrationIntegrityError",
    "ArtifactMigrationValidationError",
    "DEFAULT_ARTIFACT_ROOT",
    "DEFAULT_INVENTORY_PATH",
    "DEFAULT_MANIFEST_PATH",
    "InventoryBinding",
    "LegacyIdentifier",
    "MigrationFlag",
    "MigrationIntegrityReport",
    "MigrationIssue",
    "MigrationIssueKind",
    "MigrationManifest",
    "MigrationObservations",
    "MigrationRecord",
    "SECURITY_ARTIFACT_MIGRATION_INTERFACE",
    "SECURITY_ARTIFACT_MIGRATION_SCHEMA_VERSION",
    "SecurityArtifactMigration",
    "build_migration_manifest",
    "build_migration_manifest_from_inventory_file",
    "classify_inventory_record",
    "load_migration_manifest",
    "target_path_for",
    "write_migration_manifest",
]
